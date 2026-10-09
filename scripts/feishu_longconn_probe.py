"""飞书自建应用 · 长连接（WebSocket）事件订阅探针。

**目的**：验证「我们的服务 ↔ 飞书」这条**接收**通道能通。

为什么用长连接而不是「把通知发送到开发者服务器」：
- 我们的服务将来要跑在校内网、被飞连零信任网关挡着，**公网打不进来**；
- 飞书的「事件订阅 → 请求地址」模式要求服务有**可达的公网 URL**，并且保存时飞书会先发
  `url_verification` 校验、要求 3 秒内回显 `challenge`（实测填地址后 3 秒超时）；
- 长连接是**我们主动连出去**的 WebSocket，**不需要任何公网地址**，也绕开飞连入站限制。

**用法**：

    cd <仓库根>
    env -u ALL_PROXY -u all_proxy -u HTTPS_PROXY -u https_proxy \\
        .venv/bin/python scripts/feishu_longconn_probe.py

凭据从 `.env` 读：`FEISHU_APP_ID` / `FEISHU_APP_SECRET`。

**这个脚本只做「收到并打印」，不接任何业务逻辑**（PLAN.md §0 明确阶段 1 不做飞书自建应用）。
事件同时落盘到 `data/captures/feishu_events.jsonl`，方便事后核对。

⚠️ 代理环境变量必须清掉：本机设了 `ALL_PROXY=socks5://...`，WebSocket 走它容易连不上。
"""

from __future__ import annotations

import json
import signal
import sys
import threading
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "gateway"))

import lark_oapi as lark  # noqa: E402
from lark_oapi.api.im.v1 import P2ImMessageReceiveV1  # noqa: E402

EVENT_LOG = REPO_ROOT / "data" / "captures" / "feishu_events.jsonl"

_lock = threading.Lock()


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _record(kind: str, payload: object) -> None:
    """把事件写进 jsonl，并 echo 到控制台。"""
    line = json.dumps({"at": _now(), "kind": kind, "payload": payload}, ensure_ascii=False, default=str)
    with _lock:
        EVENT_LOG.parent.mkdir(parents=True, exist_ok=True)
        with EVENT_LOG.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
        print(f"\n[{_now()}] ← 收到事件: {kind}")
        print(json.dumps(payload, ensure_ascii=False, indent=2, default=str)[:2000], flush=True)


def on_message_receive(data: P2ImMessageReceiveV1) -> None:
    """接收消息事件 im.message.receive_v1 —— 验证长连接最直观的事件。"""
    event = data.event
    message = event.message if event else None
    sender_id = getattr(getattr(event, "sender", None), "sender_id", None)
    info = {
        "event_type": "im.message.receive_v1",
        "event_id": getattr(data.header, "event_id", None),
        "chat_id": getattr(message, "chat_id", None),
        "chat_type": getattr(message, "chat_type", None),
        "message_type": getattr(message, "message_type", None),
        "message_id": getattr(message, "message_id", None),
        "sender_open_id": getattr(sender_id, "open_id", None),
        "sender_union_id": getattr(sender_id, "union_id", None),
        "sender_user_id": getattr(sender_id, "user_id", None),
        "content": getattr(message, "content", None),
    }
    _record("im.message.receive_v1", info)


def load_credentials() -> tuple[str, str]:
    """从 .env 读 App ID / App Secret（凭据只放 .env，不进代码）。"""
    env_path = REPO_ROOT / ".env"
    values: dict[str, str] = {}
    if env_path.exists():
        for raw in env_path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            values[key.strip()] = value.strip()
    app_id = values.get("FEISHU_APP_ID", "")
    app_secret = values.get("FEISHU_APP_SECRET", "")
    if not app_id or not app_secret:
        raise SystemExit(
            "缺少 FEISHU_APP_ID / FEISHU_APP_SECRET。请在 .env 里填好这两项再跑。"
        )
    return app_id, app_secret


def main() -> int:
    import os

    for var in ("ALL_PROXY", "all_proxy", "HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy"):
        if var in os.environ:
            print(f"⚠️  检测到 {var}={os.environ[var]}，长连接可能走代理失败。"
                  f"建议用 `env -u {var} ...` 运行。")

    app_id, app_secret = load_credentials()
    print(f"App ID: {app_id}")
    print("正在建立长连接（Ctrl-C 退出）…")

    handler = (
        lark.EventDispatcherHandler.builder("", "")
        .register_p2_im_message_receive_v1(on_message_receive)
        .build()
    )

    client = lark.ws.Client(
        app_id,
        app_secret,
        event_handler=handler,
        log_level=lark.LogLevel.INFO,
    )

    # `client.start()` 是阻塞且自己管重连的，没有给外部留停止入口。
    # 所以信号处理必须**直接退出进程** —— 只设一个 Event 标志是没用的
    # （那个标志没有任何人在检查），进程会挂着不走。
    def _terminate(*_args: object) -> None:
        print(f"\n[{_now()}] 收到退出信号，关闭长连接…", flush=True)
        os._exit(0)

    signal.signal(signal.SIGINT, _terminate)
    signal.signal(signal.SIGTERM, _terminate)

    client.start()  # 阻塞式，内部自动重连
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
