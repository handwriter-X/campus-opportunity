"""飞书推送：签名、频控、错误识别。

⚠️ 签名算法来自飞书官方「自定义机器人 · 签名校验」：
    string_to_sign = "{timestamp}\\n{secret}"，把它当作 **HMAC 的密钥**，消息体为空。
    （不常见，但确实是官方规定的用法。）
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import time

import httpx
import pytest

from app.config import Settings
from app.push import Alerter, FeishuError, FeishuWebhook, RateLimiter, sign, text_card


def test_sign_matches_official_algorithm():
    timestamp = 1700000000
    secret = "test-secret"
    expected = base64.b64encode(
        hmac.new(f"{timestamp}\n{secret}".encode("utf-8"), b"", digestmod=hashlib.sha256).digest()
    ).decode()
    assert sign(secret, timestamp) == expected


def test_sign_changes_with_timestamp():
    assert sign("s", 1) != sign("s", 2)


def make_webhook(handler, **kwargs) -> tuple[FeishuWebhook, httpx.AsyncClient]:
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    webhook = FeishuWebhook(
        kwargs.pop("url", "https://open.feishu.cn/open-apis/bot/v2/hook/fake"),
        kwargs.pop("secret", ""),
        client,
        kwargs.pop("limiter", RateLimiter(100000)),
    )
    return webhook, client


class TestSend:
    def test_sends_text(self):
        captured = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["body"] = json.loads(request.content)
            return httpx.Response(200, json={"code": 0, "msg": "success"})

        webhook, client = make_webhook(handler)
        result = asyncio.run(webhook.send_text("hello"))
        assert result["code"] == 0
        assert captured["body"]["msg_type"] == "text"
        assert captured["body"]["content"]["text"] == "hello"
        asyncio.run(client.aclose())

    def test_includes_signature_when_secret_set(self):
        captured = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["body"] = json.loads(request.content)
            return httpx.Response(200, json={"code": 0})

        webhook, client = make_webhook(handler, secret="s3cr3t")
        asyncio.run(webhook.send_text("hi"))
        assert "timestamp" in captured["body"]
        assert captured["body"]["sign"] == sign("s3cr3t", int(captured["body"]["timestamp"]))
        asyncio.run(client.aclose())

    def test_no_signature_without_secret(self):
        captured = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["body"] = json.loads(request.content)
            return httpx.Response(200, json={"code": 0})

        webhook, client = make_webhook(handler)
        asyncio.run(webhook.send_text("hi"))
        assert "sign" not in captured["body"]
        asyncio.run(client.aclose())

    def test_business_error_detected_despite_http_200(self):
        """飞书业务失败也返回 HTTP 200，必须看 body 里的 code。"""

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"code": 19021, "msg": "sign match fail"})

        webhook, client = make_webhook(handler)
        with pytest.raises(FeishuError, match="19021"):
            asyncio.run(webhook.send_text("hi"))
        asyncio.run(client.aclose())

    def test_http_error_raises(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, text="boom")

        webhook, client = make_webhook(handler)
        with pytest.raises(FeishuError):
            asyncio.run(webhook.send_text("hi"))
        asyncio.run(client.aclose())

    def test_unconfigured_raises(self):
        webhook = FeishuWebhook("", "", httpx.AsyncClient(), RateLimiter(100))
        assert webhook.configured is False
        with pytest.raises(FeishuError, match="未配置"):
            asyncio.run(webhook.send_text("hi"))

    def test_card_payload_shape(self):
        captured = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["body"] = json.loads(request.content)
            return httpx.Response(200, json={"code": 0})

        webhook, client = make_webhook(handler)
        card = text_card("标题", ["行一", "行二"])
        asyncio.run(webhook.send_card(card))
        assert captured["body"]["msg_type"] == "interactive"
        assert captured["body"]["card"]["header"]["title"]["content"] == "标题"
        asyncio.run(client.aclose())


class TestRateLimiter:
    def test_enforces_minimum_interval(self):
        async def run() -> float:
            limiter = RateLimiter(600)  # 0.1s 间隔
            start = time.monotonic()
            for _ in range(3):
                await limiter.acquire()
            return time.monotonic() - start

        # 第 1 次不等待，第 2、3 次各等 ~0.1s
        assert asyncio.run(run()) >= 0.18

    def test_zero_per_minute_does_not_hang(self):
        async def run() -> None:
            await RateLimiter(0).acquire()

        asyncio.run(run())  # max(1, per_minute) 兜底，不应除零


class TestAlerter:
    def make(self, settings: Settings, handler, **overrides) -> Alerter:
        effective = settings.model_copy(
            update={"feishu_alert_webhook_url": "https://open.feishu.cn/hook/alert", **overrides}
        )
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        return Alerter(effective, client)

    def test_unconfigured_returns_false(self, settings):
        alerter = Alerter(settings.model_copy(update={"feishu_alert_webhook_url": ""}), httpx.AsyncClient())
        assert asyncio.run(alerter.alert("t", ["l"])) is False

    def test_sends_alert(self, settings):
        calls = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(json.loads(request.content))
            return httpx.Response(200, json={"code": 0})

        alerter = self.make(settings, handler)
        assert asyncio.run(alerter.alert("采集端疑似失效", ["空闲 200 分钟"])) is True
        assert len(calls) == 1

    def test_dedupes_repeated_alert(self, settings):
        calls = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(1)
            return httpx.Response(200, json={"code": 0})

        alerter = self.make(settings, handler)
        asyncio.run(alerter.alert("同样的标题", ["a"]))
        asyncio.run(alerter.alert("同样的标题", ["b"]))
        assert len(calls) == 1  # 去重窗口内只发一次，避免刷屏

        asyncio.run(alerter.alert("不同标题", ["c"]))
        assert len(calls) == 2
