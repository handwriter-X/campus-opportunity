"""GeniOS 流程编排型智能体 API 客户端。

🔴 **Q1 未关闭**：真实的 URL / 鉴权头 / 请求体 / 异步结果获取方式都还没实测（探针 S1）。
因此这里刻意把「请求怎么拼」与「响应怎么读」隔离成两个方法，并**全部由 .env 驱动**。

探针 S1 完成后，通常只需要改 `.env`：
    GENIOS_API_BASE_URL / GENIOS_API_PATH / GENIOS_APP_ID / GENIOS_API_KEY
    GENIOS_AUTH_MODE / GENIOS_REQUEST_TEMPLATE / GENIOS_TASK_ID_PATH ...
只有在默认响应结构完全对不上时，才需要动 `parse_response`。

`GENIOS_DRY_RUN=1` 时不发网络请求，直接返回合成结果 —— 用于在拿到凭据之前跑通整条链路。
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass
from typing import Any

import httpx

from .config import Settings


@dataclass(slots=True)
class DispatchResult:
    ok: bool
    task_id: str | None
    response: Any
    error: str | None = None
    dry_run: bool = False


class GeniosNotConfigured(RuntimeError):
    pass


class GeniosClient:
    def __init__(self, settings: Settings, http: httpx.AsyncClient) -> None:
        self.settings = settings
        self.http = http

    # ---------------- 请求组装 ----------------

    def build_request(self, payload: dict[str, Any]) -> tuple[str, dict[str, str], dict[str, Any]]:
        settings = self.settings
        payload_json = json.dumps(payload, ensure_ascii=False)

        headers: dict[str, str] = {"Content-Type": "application/json"}
        body: dict[str, Any]

        if settings.genios_request_template.strip():
            rendered = settings.genios_request_template
            # 每个占位符都会被替换成一个**完整的、带引号且转义好的 JSON 字符串字面量**，
            # 所以模板里不要再自己加引号：
            #   ✅ {"appId": "{app_id}", "input": {payload_json}}
            #   ❌ {"appId": "{app_id}", "input": "{payload_json}"}
            for token, value in (
                ("{payload_json}", payload_json),
                ("{app_id}", settings.genios_app_id),
                ("{api_key}", settings.genios_api_key),
                ("{user_id}", settings.genios_user_id),
            ):
                rendered = rendered.replace(token, json.dumps(value, ensure_ascii=False))
            try:
                body = json.loads(rendered)
            except ValueError as exc:
                raise GeniosNotConfigured(
                    f"GENIOS_REQUEST_TEMPLATE 不是合法 JSON：{exc}。模板渲染后为：{rendered[:500]}"
                ) from exc
        else:
            # 默认猜测结构 —— S1 实测后请用 GENIOS_REQUEST_TEMPLATE 覆盖
            body = {"app_id": settings.genios_app_id, "input": payload_json}

        mode = settings.genios_auth_mode.strip().lower()
        key = settings.genios_api_key
        if mode == "bearer":
            headers["Authorization"] = f"Bearer {key}" if key else ""
        elif mode == "header":
            prefix = settings.genios_api_key_prefix
            headers[settings.genios_api_key_header] = f"{prefix} {key}".strip() if prefix else key
        elif mode == "body":
            body[settings.genios_api_key_header] = key
        else:
            raise GeniosNotConfigured(
                f"未知 GENIOS_AUTH_MODE={settings.genios_auth_mode!r}，只能是 bearer/header/body"
            )

        return settings.genios_url, headers, body

    # ---------------- 响应解析 ----------------

    def parse_response(self, data: Any) -> tuple[str | None, Any]:
        """返回 (task_id, 结果载荷)。默认实现按常见字段名找任务 ID。

        S1 确认真实结构后，用 GENIOS_TASK_ID_PATH 指定取值路径（点号分隔，如 `data.task_id`）。
        """
        task_id: str | None = None
        path = self.settings.genios_task_id_path.strip()
        if path:
            task_id = _dig(data, path)
            task_id = str(task_id) if task_id is not None else None
        elif self.settings.genios_task_id_field.strip():
            task_id = _dig(data, self.settings.genios_task_id_field.strip())
            task_id = str(task_id) if task_id is not None else None
        elif isinstance(data, dict):
            for key in ("task_id", "taskId", "id", "run_id", "execution_id", "conversation_id"):
                value = data.get(key)
                if value not in (None, ""):
                    task_id = str(value)
                    break
        return task_id, data

    # ---------------- 调用 ----------------

    async def dispatch(self, payload: dict[str, Any]) -> DispatchResult:
        settings = self.settings

        if settings.genios_dry_run or not settings.genios_configured:
            reason = "GENIOS_DRY_RUN=1" if settings.genios_dry_run else "GeniOS 凭据未配置"
            return DispatchResult(
                ok=True,
                task_id=None,
                response={"dry_run": True, "reason": reason, "would_send": payload},
                dry_run=True,
            )

        url, headers, body = self.build_request(payload)

        try:
            response = await self.http.post(
                url, headers=headers, json=body, timeout=settings.genios_timeout_seconds
            )
        except httpx.HTTPError as exc:
            return DispatchResult(ok=False, task_id=None, response=None, error=_describe(exc))

        if response.status_code >= 400:
            return DispatchResult(
                ok=False,
                task_id=None,
                response=_safe_json(response),
                error=f"HTTP {response.status_code}: {response.text[:500]}",
            )

        data = _safe_json(response)
        task_id, parsed = self.parse_response(data)

        if task_id and settings.genios_status_path.strip():
            # 有异步任务 ID 且配了查询路径 → 轮询到出结果（S1 确认后再启用）
            polled = await self._poll(task_id)
            if polled is not None:
                return DispatchResult(ok=True, task_id=task_id, response=polled)

        return DispatchResult(ok=True, task_id=task_id, response=parsed)

    def build_query_body(self, task_id: str) -> dict[str, Any]:
        """组装「查询异步结果」的请求体。

        实测（见 docs/findings.md Q1）：HiAgent 的 `query_run_app_process` 要
        **POST + body**（`{"RunID": …, "UserID": …}`），**不是 GET**。
        所以查询体也做成 .env 可配的模板，换平台不用改代码。
        """
        settings = self.settings
        rendered = settings.genios_query_template.strip() or '{"RunID": {task_id}, "UserID": {user_id}}'
        for token, value in (
            ("{task_id}", task_id),
            ("{user_id}", settings.genios_user_id),
            ("{app_id}", settings.genios_app_id),
            ("{api_key}", settings.genios_api_key),
        ):
            rendered = rendered.replace(token, json.dumps(value, ensure_ascii=False))
        try:
            return json.loads(rendered)
        except ValueError as exc:
            raise GeniosNotConfigured(
                f"GENIOS_QUERY_TEMPLATE 不是合法 JSON：{exc}。渲染后为：{rendered[:300]}"
            ) from exc

    async def _poll(self, task_id: str) -> Any | None:
        """轮询异步结果。超时返回 None（不视为失败 —— 结果仍会由工作流回写 gateway）。"""
        settings = self.settings
        status_path = settings.genios_status_path.strip()
        url = status_path
        if not url.startswith("http"):
            url = settings.genios_api_base_url.rstrip("/") + "/" + status_path.lstrip("/")
        url = url.replace("{task_id}", task_id).replace("{id}", task_id)

        headers = self.build_request({})[1]
        body = self.build_query_body(task_id)

        deadline = time.monotonic() + settings.genios_poll_max_seconds
        while time.monotonic() < deadline:
            await asyncio.sleep(settings.genios_poll_interval_seconds)
            try:
                response = await self.http.post(
                    url, headers=headers, json=body, timeout=settings.genios_timeout_seconds
                )
            except httpx.HTTPError:
                continue
            if response.status_code >= 400:
                continue
            data = _safe_json(response)
            if _looks_finished(data):
                return data
        return None


def _describe(exc: Exception) -> str:
    return f"{type(exc).__name__}: {exc}"


def _safe_json(response: httpx.Response) -> Any:
    try:
        return response.json()
    except ValueError:
        return {"_raw_text": response.text[:2000]}


def _dig(data: Any, path: str) -> Any:
    current = data
    for part in path.split("."):
        if isinstance(current, dict):
            current = current.get(part)
        elif isinstance(current, list) and part.isdigit():
            index = int(part)
            current = current[index] if index < len(current) else None
        else:
            return None
    return current


_TERMINAL_STATES = (
    "succeeded", "success", "finished", "completed", "done", "failed", "error",
)


def _looks_finished(data: Any) -> bool:
    """判断轮询到的响应是不是「已出结果」。

    ⚠️ 这里有个实测踩到的坑（2026-10-07）：HiAgent 的 `query_run_app_process`
    **无论跑没跑完都会返回 `output` 字段**（没跑完时是 `null`）。
    最初的实现「只要响应里有 output 就算完成」会把还在跑的任务提前取走，
    结果拿到一个空的 output，表现为「结果未识别」。
    所以：**只要有 status 字段，就一律以 status 为准，不再看 output 在不在。**
    """
    if not isinstance(data, dict):
        return False
    for key in ("status", "state", "task_status", "run_status"):
        if key in data and isinstance(data.get(key), str):
            return data[key].lower() in _TERMINAL_STATES
    # 没有状态字段时，才退回「看有没有结果字段」这种弱判断
    return any(key in data for key in ("output", "outputs", "result", "answer"))
