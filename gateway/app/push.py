"""飞书群自定义机器人推送：签名、频控、告警。

⚠️ 频控数字（约 100 次/分钟/机器人）来自第三方文档，非飞书官方。
所以默认保守取 80，并且**排队而不是丢弃**。
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import time
from typing import Any

import httpx

from .config import Settings


class FeishuError(RuntimeError):
    pass


class RateLimiter:
    """串行化的最小间隔限流器：保证每分钟不超过 N 次，超出的调用排队等待。"""

    def __init__(self, per_minute: int) -> None:
        self.min_interval = 60.0 / max(1, per_minute)
        self._lock = asyncio.Lock()
        self._next_allowed = 0.0

    async def acquire(self) -> None:
        async with self._lock:
            now = time.monotonic()
            wait = max(0.0, self._next_allowed - now)
            self._next_allowed = max(now, self._next_allowed) + self.min_interval
        if wait > 0:
            await asyncio.sleep(wait)


def sign(secret: str, timestamp: int) -> str:
    """飞书自定义机器人签名：以 `{timestamp}\\n{secret}` 为密钥做 HMAC-SHA256 再 base64。"""
    string_to_sign = f"{timestamp}\n{secret}"
    digest = hmac.new(string_to_sign.encode("utf-8"), b"", digestmod=hashlib.sha256).digest()
    return base64.b64encode(digest).decode("utf-8")


class FeishuWebhook:
    def __init__(self, url: str, secret: str, http: httpx.AsyncClient, limiter: RateLimiter) -> None:
        self.url = url
        self.secret = secret
        self.http = http
        self.limiter = limiter

    @property
    def configured(self) -> bool:
        return bool(self.url)

    async def send(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not self.configured:
            raise FeishuError("Webhook URL 未配置")
        body = dict(payload)
        if self.secret:
            timestamp = int(time.time())
            body["timestamp"] = str(timestamp)
            body["sign"] = sign(self.secret, timestamp)
        await self.limiter.acquire()
        response = await self.http.post(self.url, json=body, timeout=15.0)
        data = _safe_json(response)
        # 飞书即使业务失败也常返回 HTTP 200，必须看 body 里的 code
        if response.status_code >= 400 or (isinstance(data, dict) and data.get("code") not in (None, 0)):
            raise FeishuError(f"飞书返回异常：HTTP {response.status_code} {data}")
        return data if isinstance(data, dict) else {"raw": data}

    async def send_text(self, text: str) -> dict[str, Any]:
        return await self.send({"msg_type": "text", "content": {"text": text}})

    async def send_card(self, card: dict[str, Any]) -> dict[str, Any]:
        return await self.send({"msg_type": "interactive", "card": card})


def _safe_json(response: httpx.Response) -> Any:
    try:
        return response.json()
    except ValueError:
        return {"_raw_text": response.text[:1000]}


# --------------------------------------------------------------------------
# 卡片
# --------------------------------------------------------------------------


def text_card(title: str, lines: list[str], *, template: str = "blue") -> dict[str, Any]:
    """通用告警/通知卡片。机会卡片在 genios/feishu_cards/ 下（由 GeniOS 工作流发送）。"""
    body = "\n".join(lines) if lines else "（无内容）"
    return {
        "config": {"wide_screen_mode": True},
        "header": {"template": template, "title": {"tag": "plain_text", "content": title}},
        "elements": [{"tag": "div", "text": {"tag": "lark_md", "content": body}}],
    }


class Alerter:
    """运维告警。**必须用独立的 Webhook**，不要和机会推送混在一个群（方案阶段 2）。"""

    def __init__(self, settings: Settings, http: httpx.AsyncClient) -> None:
        self.webhook = FeishuWebhook(
            settings.feishu_alert_webhook_url,
            settings.feishu_alert_webhook_secret,
            http,
            RateLimiter(settings.feishu_rate_limit_per_minute),
        )
        self._last_key: str | None = None
        self._last_at: float = 0.0
        self.dedupe_window_seconds = 1800.0

    async def alert(self, title: str, lines: list[str], *, template: str = "red") -> bool:
        """发送告警。同一标题在去重窗口内只发一次，避免把告警群刷屏。"""
        now = time.monotonic()
        if title == self._last_key and now - self._last_at < self.dedupe_window_seconds:
            return False
        if not self.webhook.configured:
            return False
        try:
            await self.webhook.send_card(text_card(title, lines, template=template))
        except (FeishuError, httpx.HTTPError):
            return False
        self._last_key = title
        self._last_at = now
        return True
