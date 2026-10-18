"""飞书自建应用 · **卡片回传回调**探针。

## 要回答的问题

模块二里有两个"点按钮"的动作：
- **④ 发起人点「邀请」** —— 决定要不要惊动被推荐的人
- **⑥ 被推荐的人点「接受 / 婉拒」**

这两步是**走飞书卡片回调**（一下就好），还是**退化成"跳到多维表格再点按钮"**（多点两下），
取决于：**长连接能不能收到卡片按钮的回调？**

SDK 里有 `register_p2_card_action_trigger` —— 说明**理论上支持**。本脚本做实测。

## 用法

    cd <仓库根>
    env -u ALL_PROXY -u all_proxy -u HTTPS_PROXY -u https_proxy \\
        .venv/bin/python scripts/feishu_card_callback_probe.py

脚本会：① 发一张带回传按钮的测试卡给你 → ② 开始监听。
**你点一下按钮**，终端会打印收到的完整回调载荷；事件同时落盘到
`data/captures/feishu_card_callbacks.jsonl`。

⚠️ 代理环境变量必须清掉（WebSocket 走代理容易连不上），和 `feishu_longconn_probe.py` 一样。
"""

from __future__ import annotations

import json
import signal
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "gateway"))

import httpx  # noqa: E402
import lark_oapi as lark  # noqa: E402
from lark_oapi.api.im.v1 import P2ImMessageReceiveV1  # noqa: E402
from lark_oapi.event.callback.model.p2_card_action_trigger import (  # noqa: E402
    P2CardActionTrigger,
    P2CardActionTriggerResponse,
)

CALLBACK_LOG = REPO_ROOT / "data" / "captures" / "feishu_card_callbacks.jsonl"
PROBE_MARKER = "campus-card-callback-probe"


def load_env() -> dict[str, str]:
    env: dict[str, str] = {}
    path = REPO_ROOT / ".env"
    if not path.exists():
        return env
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        env[key.strip()] = value.strip()
    return env


def build_probe_card() -> dict:
    """一张最小卡片：一个**回传按钮**（有 `value`，没有 `url`）。"""
    return {
        "config": {"wide_screen_mode": True},
        "header": {
            "template": "blue",
            "title": {"tag": "plain_text", "content": "🔬 卡片回调探针"},
        },
        "elements": [
            {
                "tag": "div",
                "text": {
                    "tag": "lark_md",
                    "content": (
                        "**请点下面的按钮。**\n"
                        "这是为了验证「飞书能不能把卡片按钮的点击，送回我们的长连接」。\n"
                        "点完回我一句，我看这边有没有收到。"
                    ),
                },
            },
            {
                "tag": "action",
                "actions": [
                    {
                        "tag": "button",
                        "text": {"tag": "plain_text", "content": "点我试试"},
                        "type": "primary",
                        # ★ 关键：有 value 才是"回传"，没有 url 就不会跳转
                        "value": {
                            "probe": PROBE_MARKER,
                            "sent_at": datetime.now().isoformat(timespec="seconds"),
                        },
                    }
                ],
            },
            {
                "tag": "note",
                "elements": [
                    {"tag": "plain_text",
                     "content": "由 campus-gateway 探针发出 · 仅用于验证回调通道"}
                ],
            },
        ],
    }


def send_card(env: dict[str, str]) -> str | None:
    app_id = env.get("FEISHU_APP_ID", "")
    app_secret = env.get("FEISHU_APP_SECRET", "")
    target = env.get("FEISHU_NOTIFY_TARGET", "")
    if not (app_id and app_secret and target):
        print("❌ .env 里缺 FEISHU_APP_ID / FEISHU_APP_SECRET / FEISHU_NOTIFY_TARGET")
        return None

    id_type = "chat_id" if target.startswith("oc_") else "open_id"
    with httpx.Client(timeout=30) as client:
        resp = client.post(
            "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
            json={"app_id": app_id, "app_secret": app_secret},
        )
        token = (resp.json() or {}).get("tenant_access_token")
        if not token:
            print("❌ 拿不到 tenant_access_token:", resp.text[:300])
            return None
        resp = client.post(
            "https://open.feishu.cn/open-apis/im/v1/messages",
            params={"receive_id_type": id_type},
            headers={"Authorization": f"Bearer {token}"},
            json={
                "receive_id": target,
                "msg_type": "interactive",
                "content": json.dumps(build_probe_card(), ensure_ascii=False),
            },
        )
        data = resp.json() or {}
    if data.get("code") != 0:
        print("❌ 发卡片失败:", json.dumps(data, ensure_ascii=False)[:400])
        return None
    print(f"✅ 卡片已发到 {target}（message_id={data.get('data', {}).get('message_id')}）")
    return target


def main() -> int:
    env = load_env()
    app_id = env.get("FEISHU_APP_ID", "")
    app_secret = env.get("FEISHU_APP_SECRET", "")
    if not (app_id and app_secret):
        print("❌ .env 里缺 FEISHU_APP_ID / FEISHU_APP_SECRET")
        return 2

    CALLBACK_LOG.parent.mkdir(parents=True, exist_ok=True)

    def _log(kind: str, payload: object) -> None:
        record = {"kind": kind, "at": datetime.now().isoformat(timespec="seconds"),
                  "payload": payload}
        with CALLBACK_LOG.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")

    def on_card_action(data: P2CardActionTrigger) -> P2CardActionTriggerResponse:
        dumped = lark.JSON.marshal(data)
        print("\n" + "=" * 70)
        print("🎉 收到卡片回调！")
        print("=" * 70)
        print(json.dumps(dumped, ensure_ascii=False, indent=2))
        _log("card_action", dumped)
        # 回一个 toast，让你在飞书里能看到反馈
        return P2CardActionTriggerResponse(
            {"toast": {"type": "success", "content": "网关收到了！"}}
        )

    def on_message(data: P2ImMessageReceiveV1) -> None:
        dumped = lark.JSON.marshal(data)
        text = ((dumped.get("event") or {}).get("message") or {}).get("content", "")
        print(f"💬 收到消息（{text[:60]}）")
        _log("message", dumped)

    handler = (
        lark.EventDispatcherHandler.builder("", "")
        .register_p2_card_action_trigger(on_card_action)
        .register_p2_im_message_receive_v1(on_message)
        .build()
    )
    client = lark.ws.Client(
        app_id,
        app_secret,
        event_handler=handler,
        log_level=lark.LogLevel.INFO,
    )

    target = send_card(env)
    if not target:
        return 2

    stop = threading.Event()

    def _shutdown(*_: object) -> None:
        stop.set()

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    print("\n👂 开始监听卡片回调……**请去飞书点那个「点我试试」按钮**")
    print(f"   回调会落盘到 {CALLBACK_LOG}")
    print("   （Ctrl-C 退出）\n")

    worker = threading.Thread(target=client.start, daemon=True)
    worker.start()
    try:
        while not stop.is_set() and worker.is_alive():
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    print("\n监听结束。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
