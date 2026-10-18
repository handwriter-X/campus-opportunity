"""模块二 · 组队匹配的常驻服务。

## 它同时干两件事

1. **定时轮询**【组队需求】，发现 `状态=待匹配` 就派发给 GeniOS（`MatchFlow.poll_once`）
2. **长连接收卡片回调** —— 用户点「邀请 TA」/「我想加入」/「这次先不了」

两件事为什么放一个进程：飞书的卡片回调走**长连接**（我们主动连出去的 WebSocket），
而轮询本来就要常驻。一个进程两条线程，比拆成两个服务再共享状态简单。

## 用法

    cd <仓库根>
    env -u ALL_PROXY -u all_proxy -u HTTPS_PROXY -u https_proxy \\
        .venv/bin/python scripts/match_service.py

    # 只跑一遍轮询就退出（用来验证/排查）
    ... scripts/match_service.py --once

⚠️ **代理环境变量必须清掉** —— WebSocket 走代理连不上（和 S6/S8 的结论一致）。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
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

from app.bitable import BitableClient  # noqa: E402
from app.config import MatchGeniosProfile, get_settings  # noqa: E402
from app.feishu_app import FeishuAppClient  # noqa: E402
from app.genios_client import GeniosClient  # noqa: E402
from app.chat_flow import ChatFlow  # noqa: E402
from app.genios_chat import GeniosChatClient  # noqa: E402
from app.store import init_db, make_engine, make_session_factory  # noqa: E402
from app.match_flow import MatchFlow, parse_card_action  # noqa: E402

CALLBACK_LOG = REPO_ROOT / "data" / "captures" / "match_callbacks.jsonl"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(name)s | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("gateway.match.service")


def _log_callback(payload: dict) -> None:
    CALLBACK_LOG.parent.mkdir(parents=True, exist_ok=True)
    with CALLBACK_LOG.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(
            {"at": datetime.now().isoformat(timespec="seconds"), "payload": payload},
            ensure_ascii=False) + "\n")


async def _poll_loop(flow: MatchFlow, interval: float, stop: asyncio.Event) -> None:
    while not stop.is_set():
        try:
            summary = await flow.poll_once()
            if summary.get("dispatched") or summary.get("errors"):
                logger.info("轮询：%s", summary)
        except Exception as exc:  # 轮询不能因为单次异常就死掉
            logger.exception("轮询出错：%s", exc)
        try:
            await asyncio.wait_for(stop.wait(), timeout=interval)
        except asyncio.TimeoutError:
            pass


def main() -> int:
    parser = argparse.ArgumentParser(description="模块二 · 组队匹配常驻服务")
    parser.add_argument("--once", action="store_true", help="只跑一遍轮询就退出")
    parser.add_argument("--interval", type=float, default=0.0, help="覆盖轮询间隔（秒）")
    parser.add_argument("--no-listen", action="store_true", help="不收卡片回调（只轮询）")
    args = parser.parse_args()

    settings = get_settings()
    if not settings.bitable_enabled:
        print("⚠️ BITABLE_ENABLED 没开 —— 先把 .env 配好（见 .env.example 的「功能模块二」一节）")
    if not settings.genios_match_enabled:
        print("⚠️ GENIOS_MATCH_ENABLED 没开 —— 匹配工作流不会真被调用")

    interval = args.interval or settings.match_poll_interval_seconds

    async def run() -> int:
        stop = asyncio.Event()
        loop = asyncio.get_running_loop()
        _install_signal_handlers(loop, stop)

        async with httpx.AsyncClient(timeout=60.0) as http:
            app = FeishuAppClient(settings, http)
            bitable = BitableClient(settings, http, app)
            genios = GeniosClient(MatchGeniosProfile(settings), http)
            flow = MatchFlow(settings, http, app, bitable, genios)

            # 对话那层要一张「open_id → 会话 id」的表。**自己 init_db** ——
            # 常驻服务不走 FastAPI 的 startup 钩子，不建表第一次对话就会炸。
            engine = make_engine(settings.database_url)
            session_factory = make_session_factory(engine)
            init_db(engine)
            chat = ChatFlow(
                settings, http, app,
                genios_chat=GeniosChatClient(settings, http),
                session_factory=session_factory,
                bitable=bitable,          # 用来查"提问者本人的画像"（见 _with_profile）
            )

            if args.once:
                summary = await flow.poll_once()
                print("轮询结果：", json.dumps(summary, ensure_ascii=False))
                return 0

            ws_thread = None
            if not args.no_listen:
                ws_thread = _start_listener(settings, flow, chat, loop)

            logger.info("开始轮询【组队需求】，间隔 %.0fs（Ctrl-C 退出）", interval)
            await _poll_loop(flow, interval, stop)
            logger.info("已停止。")
            del ws_thread
        return 0

    return asyncio.run(run())


def _install_signal_handlers(loop: asyncio.AbstractEventLoop, stop: asyncio.Event) -> None:
    def _shutdown(*_: object) -> None:
        loop.call_soon_threadsafe(stop.set)

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _shutdown)
        except NotImplementedError:  # Windows 等
            signal.signal(sig, lambda *_: loop.call_soon_threadsafe(stop.set))


async def _run_card_action(flow: MatchFlow, value: dict, operator: str) -> None:
    """后台跑一次卡片动作。

    **成败都要说** —— 回调已经先行回执了「已收到，正在处理…」，
    如果这里失败还不吭声，用户看到的就是"点了没反应"。
    """
    action = value.get("action")
    try:
        toast, _card = await flow.handle_card_action(value, operator)
        logger.info("卡片动作完成（%s）：%s", action, toast)
    except Exception as exc:
        logger.exception("卡片动作失败（%s）：%s", action, exc)
        try:
            await flow.notify(operator, "⚠️ 操作没成功",
                              f"刚才那一下没能处理完成。\n\n原因：`{exc}`\n\n可以稍后再试一次。")
        except Exception:
            logger.exception("连失败通知都没发出去")


def _start_listener(settings, flow: MatchFlow, chat: ChatFlow,
                    loop: asyncio.AbstractEventLoop):
    """在单独线程里跑飞书长连接，把卡片回调送回主事件循环。"""

    def on_card_action(data: P2CardActionTrigger) -> P2CardActionTriggerResponse:
        # ⚠️ `lark.JSON.marshal(data)` 返回的是 **JSON 字符串**，不是 dict。
        # 原先直接 `dumped.get("event")` → `'str' object has no attribute 'get'`，
        # **回调被整个打死** → 用户点了「邀请」却没反应。
        # （探针脚本里只 print 没 .get()，所以一直没暴露。）
        raw = lark.JSON.marshal(data)
        try:
            payload = json.loads(raw) if isinstance(raw, str) else (raw or {})
        except (TypeError, ValueError):
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        _log_callback(payload)

        value, operator = parse_card_action(payload)
        logger.info("卡片回调：action=%s operator=%s value=%s",
                    value.get("action"), operator, json.dumps(value, ensure_ascii=False))

        # ⚠️ **立刻回执，活儿丢后台干。**
        # 飞书的卡片回调**约 3 秒就超时**（实测报「目标回调服务超时未响应」），
        # 而处理一次邀请要串 5 次飞书 API（查记录 → 查重 → 读画像 → 写表 → 发卡），
        # 加上代理延迟实测 **8 秒** —— 同步等它必然超时。
        # 飞书官方也是这个路子：先 ack，再异步做，慢的结果另外通知。
        asyncio.run_coroutine_threadsafe(
            _run_card_action(flow, value, operator), loop
        )
        return P2CardActionTriggerResponse(
            {"toast": {"type": "info", "content": "已收到，正在处理…"}}
        )

    def on_message(data: P2ImMessageReceiveV1) -> None:
        """学生发来的消息 —— 交给对话路由。**永远不抛异常**，别把通道打断。"""
        raw = lark.JSON.marshal(data)
        try:
            payload = json.loads(raw) if isinstance(raw, str) else (raw or {})
        except (TypeError, ValueError):
            payload = {}
        asyncio.run_coroutine_threadsafe(chat.handle_message(payload), loop)

    handler = (
        lark.EventDispatcherHandler.builder("", "")
        .register_p2_card_action_trigger(on_card_action)
        # ★ 同一个长连接同时收「卡片回调」和「消息」——
        # 飞书一个应用只允许一条长连接，所以两者**必须**在同一个进程里注册。
        .register_p2_im_message_receive_v1(on_message)
        .build()
    )
    client = lark.ws.Client(
        settings.feishu_app_id,
        settings.feishu_app_secret,
        event_handler=handler,
        log_level=lark.LogLevel.INFO,
    )
    thread = threading.Thread(target=client.start, name="feishu-ws", daemon=True)
    thread.start()
    logger.info("飞书长连接已启动（卡片回调监听中）")
    time.sleep(1)  # 让连接先建立
    return thread


if __name__ == "__main__":
    raise SystemExit(main())
