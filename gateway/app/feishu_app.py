"""飞书自建应用推送通道。

## 为什么不用群自定义机器人 Webhook（PLAN §4 的首选）

本服务最终要跑在校内网、被飞连零信任网关挡着，**公网打不进来**。
自建应用 + 长连接这条通道已经实测验证过（`docs/findings.md` S6），
推送也走同一套凭据，就不必再维护第二套密钥了。

## 与 `push.py` 的分工

- `push.py`：**自定义机器人 Webhook**（`FEISHU_*_WEBHOOK_URL`），方案 §4 的首选路径。
- 本模块：**自建应用**（`FEISHU_APP_ID/SECRET`），飞连环境下的替代路径。

## 凭据处理

`tenant_access_token` **只在内存里缓存**，不落盘、不进日志（铁律 1）。
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any

import httpx

from .config import Settings

FEISHU_BASE = "https://open.feishu.cn/open-apis"
# 提前 5 分钟续期，避免边界上刚好过期
TOKEN_REFRESH_MARGIN_SECONDS = 300.0


class FeishuAppError(RuntimeError):
    pass


def id_type_of(target: str) -> str:
    """`oc_` 是群，`ou_` 是用户，其余按 open_id 试。"""
    if target.startswith("oc_"):
        return "chat_id"
    if target.startswith("ou_"):
        return "open_id"
    return "open_id"


class FeishuAppClient:
    def __init__(self, settings: Settings, http: httpx.AsyncClient) -> None:
        self.settings = settings
        self.http = http
        self._token: str | None = None
        self._token_expires_at: float = 0.0
        self._lock = asyncio.Lock()

    # ---------------- 凭据 ----------------

    @property
    def configured(self) -> bool:
        return bool(self.settings.feishu_app_id and self.settings.feishu_app_secret)

    async def _tenant_token(self) -> str:
        """取 tenant_access_token（内存缓存 + 提前续期）。**不打印、不落盘。**"""
        async with self._lock:
            now = time.monotonic()
            if self._token and now < self._token_expires_at:
                return self._token
            if not self.configured:
                raise FeishuAppError("未配置 FEISHU_APP_ID / FEISHU_APP_SECRET")
            response = await self.http.post(
                f"{FEISHU_BASE}/auth/v3/tenant_access_token/internal",
                json={
                    "app_id": self.settings.feishu_app_id,
                    "app_secret": self.settings.feishu_app_secret,
                },
                timeout=20.0,
            )
            data = _safe_json(response)
            token = data.get("tenant_access_token")
            if not token:
                raise FeishuAppError(f"换取 token 失败：code={data.get('code')} msg={data.get('msg')}")
            # expire 单位是秒，默认 7200
            ttl = float(data.get("expire") or 7200)
            self._token = token
            self._token_expires_at = now + max(ttl - TOKEN_REFRESH_MARGIN_SECONDS, 60.0)
            return token

    # ---------------- 发送 ----------------

    async def send(
        self,
        msg_type: str,
        content: dict[str, Any],
        *,
        target: str | None = None,
    ) -> dict[str, Any]:
        """发消息。`target` 留空则用 `FEISHU_NOTIFY_TARGET`。"""
        destination = (target or self.settings.feishu_notify_target).strip()
        if not destination:
            raise FeishuAppError("没有推送目标（FEISHU_NOTIFY_TARGET 为空）")

        token = await self._tenant_token()
        response = await self.http.post(
            f"{FEISHU_BASE}/im/v1/messages",
            params={"receive_id_type": id_type_of(destination)},
            headers={"Authorization": f"Bearer {token}"},
            json={
                "receive_id": destination,
                "msg_type": msg_type,
                "content": json.dumps(content, ensure_ascii=False),
            },
            timeout=20.0,
        )
        data = _safe_json(response)
        if data.get("code") not in (0, None):
            raise FeishuAppError(f"发送失败：code={data.get('code')} msg={data.get('msg')}")
        return data

    async def send_text(self, text: str, *, target: str | None = None) -> dict[str, Any]:
        return await self.send("text", {"text": text}, target=target)

    async def send_card(self, card: dict[str, Any], *, target: str | None = None) -> dict[str, Any]:
        """发交互卡片。卡片结构见 genios/feishu_cards/。"""
        return await self.send("interactive", card, target=target)


def _safe_json(response: httpx.Response) -> Any:
    try:
        return response.json()
    except ValueError:
        return {"code": -1, "msg": f"HTTP {response.status_code}: {response.text[:300]}"}
