"""GeniOS **对话型/对话流型**智能体的客户端。

## 这不是 `genios_client.py` 那套

`genios_client.py` 打的是**流程编排型**的 `run_app_workflow`（单轮、异步、传 `InputData` 字符串）。
对话型是**完全不同的一族 API**（多轮、会话、**SSE 流式**）：

```
POST /api/proxy/api/v1/create_conversation   {"userID": "ou_…"}
   → {"Conversation": {"AppConversationID": "db8o…"}}
POST /api/proxy/api/v1/chat_query            {"userID","AppConversationID","Query"}
   → text/event-stream
```

**这些都是探出来的，不是文档里抄的**（`docs/findings.md` Q11）——
原先猜的 `chat` / `run_app` / `create_message` / `send_message` 之类**全是 404**。

## ⚠️ 三个实测踩到的坑

1. **SSE 格式怪**：每帧是 `event:text\n` + `data:data: {…}\n\n` ——
   **`data:` 字段的内容本身又以 `data:` 开头**，剥一层还不够。
2. **回复双重编码**：`answer` 是**字符串**，里面还套着 `{"output": "{\"reply\": \"…\"}"}`。
   要**递归剥**才能拿到人话（`worker.extract_llm_payload` 是同一个思路）。
3. **要用 `AppConversationID`**（`create_conversation` 返回的那个），
   不是同一个响应里的 `ConversationID` —— 名字太像了，传错了只会得到 400。
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

import httpx

from .config import Settings

logger = logging.getLogger("gateway.genios.chat")


class GeniosChatError(RuntimeError):
    pass


def unwrap_text(payload: Any, *, depth: int = 0) -> str:
    """从各种嵌套的 JSON 里挖出**人话**。

    实测的返回长这样（每一层都是字符串）::

        answer = '{"output": "{\\"reply\\": \\"同学好呀…\\"}"}'

    所以先剥字符串里的 JSON，再从字典里挑最像正文的字段。
    """
    if depth > 6:
        return ""
    if isinstance(payload, str):
        text = payload.strip()
        # ⚠️ `"` 也算：某层可能是个**带引号的 JSON 字符串**（`'"南开…"'`）。
        # 不认它的话，回复会原样带着引号显示出来（实测踩过）。
        if text[:1] in '{"[':
            try:
                return unwrap_text(json.loads(text), depth=depth + 1)
            except (ValueError, TypeError):
                return text
        return text
    if isinstance(payload, dict):
        # 优先级：正文类字段优先；`output` 常常是"再套一层"的中转。
        #
        # ⚠️ 这个列表**永远追不上画布的改法** —— 实测踩过两次：
        #   · 2026-10-16：字段叫 `response`，漏了 → "帧在、正文剥不出来"
        #   · 2026-10-17：**不同分支的字段名还不一样**！
        #       查机会分支 → `response`
        #       找队友分支 → `output_match`   ← 而同一层还有个空的 `output`
        #     结果挑中了空的 `output`，返回空串。
        #
        # ⇒ 所以这里只是**优先猜**，猜不中就走下面的兜底：
        #   **把所有值都剥一遍，取最长的那段文本**。
        for key in ("reply", "response", "answer", "text", "content",
                    "message", "result", "output", "output_match"):
            if key in payload:
                got = unwrap_text(payload[key], depth=depth + 1)
                if got:
                    return got

        best = ""
        for value in payload.values():          # 兜底：字段名不认识就取最长的
            got = unwrap_text(value, depth=depth + 1)
            if len(got) > len(best):
                best = got
        return best
    if isinstance(payload, list):
        for item in payload:
            got = unwrap_text(item, depth=depth + 1)
            if got:
                return got
    return ""


def parse_sse(raw: str) -> list[dict[str, Any]]:
    """把 SSE 文本拆成事件列表。

    ⚠️ **这个平台的 SSE 是 `event:text` + `data:data: {…}`** ——
    `data:` 的值本身又以 `data:` 开头。标准 SSE 解析器会把它当成
    值为 `data: {…}` 的字符串，于是 json 解析失败。这里**显式剥掉那一层**。
    """
    events: list[dict[str, Any]] = []
    for frame in re.split(r"\n\s*\n", raw or ""):
        payload = None
        for line in frame.splitlines():
            line = line.strip()
            if not line.startswith("data:"):
                continue
            body = line[len("data:"):].strip()
            if body.startswith("data:"):          # ← 剥第二层
                body = body[len("data:"):].strip()
            try:
                payload = json.loads(body)
            except (ValueError, TypeError):
                continue
        if isinstance(payload, dict):
            events.append(payload)
    return events


def reply_of(events: list[dict[str, Any]]) -> str:
    """从事件流里取回复正文。

    正文在 `event == "message"` 那帧的 `answer` 里（双重编码，用 `unwrap_text` 剥）。
    """
    for event in events:
        if event.get("event") != "message":
            continue
        text = unwrap_text(event.get("answer"))
        if text:
            return text
    # 兜底：万一某天改了事件名，就从所有帧里找最长的一段人话
    best = ""
    for event in events:
        text = unwrap_text(event.get("answer") or event.get("content"))
        if len(text) > len(best):
            best = text
    return best


class GeniosChatClient:
    def __init__(self, settings: Settings, http: httpx.AsyncClient) -> None:
        self.settings = settings
        self.http = http

    @property
    def configured(self) -> bool:
        return bool(
            self.settings.genios_api_base_url
            and self.settings.genios_chat_api_key
            and self.settings.genios_chat_enabled
        )

    # ---------------- 底层 ----------------

    def _url(self, path: str) -> str:
        return self.settings.genios_api_base_url.rstrip("/") + "/" + path.lstrip("/")

    def _headers(self) -> dict[str, str]:
        # 和流程编排型一样：密钥放 `Apikey` 头（实测）
        return {
            "Content-Type": "application/json",
            "Apikey": self.settings.genios_chat_api_key,
        }

    async def _post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        if not self.configured:
            raise GeniosChatError("对话智能体未配置（GENIOS_CHAT_ENABLED / GENIOS_CHAT_API_KEY）")
        response = await self.http.post(
            self._url(path), headers=self._headers(), json=body,
            timeout=self.settings.genios_timeout_seconds,
        )
        if response.status_code >= 400:
            raise GeniosChatError(f"HTTP {response.status_code}: {response.text[:300]}")
        try:
            return response.json()
        except ValueError as exc:
            raise GeniosChatError(f"返回不是 JSON：{response.text[:200]}") from exc

    # ---------------- 用法 ----------------

    async def create_conversation(self, user_id: str) -> str:
        """建一个会话，返回 **`AppConversationID`**（`chat_query` 要的是它）。"""
        data = await self._post("/api/proxy/api/v1/create_conversation", {"userID": user_id})
        conversation = data.get("Conversation") if isinstance(data.get("Conversation"), dict) else {}
        app_id = conversation.get("AppConversationID") or ""
        if not app_id:
            raise GeniosChatError(f"没拿到 AppConversationID：{json.dumps(data, ensure_ascii=False)[:200]}")
        return app_id

    async def chat(self, user_id: str, app_conversation_id: str, query: str) -> str:
        """问一句，拿回回复文本。

        ⚠️ 返回是 **SSE 流**，要**整个读完**再解析（`parse_sse` + `reply_of`）。
        """
        if not self.configured:
            raise GeniosChatError("对话智能体未配置")
        async with self.http.stream(
            "POST",
            self._url("/api/proxy/api/v1/chat_query"),
            headers=self._headers(),
            json={"userID": user_id, "AppConversationID": app_conversation_id, "Query": query},
            timeout=self.settings.genios_timeout_seconds,
        ) as response:
            if response.status_code >= 400:
                body = await response.aread()
                raise GeniosChatError(
                    f"HTTP {response.status_code}: {body.decode('utf-8', 'replace')[:300]}"
                )
            chunks: list[bytes] = []
            async for chunk in response.aiter_bytes():
                chunks.append(chunk)
        raw = b"".join(chunks).decode("utf-8", errors="replace")
        events = parse_sse(raw)
        text = reply_of(events)
        if not text:
            # ⚠️ **打印事件名而不是原文** —— 上次只截了原文前 300 字（全是 message_start/flow_start），
            # 看不出到底缺了哪一帧，白查一轮。
            names = [e.get("event") for e in events]
            frame = next((e for e in events if e.get("event") == "message"), None)
            logger.warning(
                "对话返回里没找到正文｜事件=%s｜字节=%d｜message 帧原样=%s",
                names, len(raw),
                json.dumps(frame, ensure_ascii=False)[:600] if frame else "（没有 message 帧）",
            )
            raise GeniosChatError(f"对话返回里没有正文（只有这些事件：{names}）")
        return text
