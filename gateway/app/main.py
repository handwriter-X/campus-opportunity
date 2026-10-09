"""campus-gateway 应用装配。

`create_app(settings)` 是工厂，便于测试注入临时数据库与关掉后台 worker；
`app = create_app()` 供 uvicorn 使用（`uvicorn app.main:app --app-dir gateway`）。
"""

from __future__ import annotations

import asyncio
import contextlib
import datetime as dt
import logging
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import FastAPI, Request
from sqlalchemy import func, select

from . import __version__
from .config import Settings, get_settings
from .debug import router as debug_router
from .genios_client import GeniosClient
from .ingest import router as ingest_router
from .models import Article
from .opportunities import router as opportunities_router
from .feishu_app import FeishuAppClient
from .push import Alerter, FeishuWebhook, RateLimiter
from .push_router import router as push_router
from .store import init_db, make_engine, make_session_factory, requeue_stale_dispatched
from .tz import UTC, SHANGHAI, iso_shanghai
from .worker import ArticleWorker

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(name)s | %(message)s",
)
logger = logging.getLogger("campus")

DESCRIPTION = """
校园机会搭子 · campus-gateway

只做三件事：**搬运、排队、持久化**。判断一篇文章是不是机会、该不该推送，都在 GeniOS 工作流里。

- `POST /ingest`          We-MP-RSS 的 Webhook 入口（需 `X-Ingest-Secret`）
- `POST /opportunities`   GeniOS 工作流回写机会记录（需 `X-Internal-Secret`）
- `GET  /opportunities`   查询机会（周报卡片 / 后续对话）
- `POST /push`            飞书推送降级通道（需 `X-Internal-Secret`）
- `GET  /health`          存活探针
- `POST /_debug/echo`     探针 S5：验证 GeniOS → 本服务的连通性（**不鉴权**）
- `POST /ingest/_debug`   探针 S3：捕获 We-MP-RSS 原始载荷（**不鉴权**）
"""


def _ensure_sqlite_dir(database_url: str) -> None:
    if not database_url.startswith("sqlite"):
        return
    raw = database_url.split("///", 1)[-1]
    if raw in ("", ":memory:") or raw.startswith("file:"):
        return
    parent = Path(raw).expanduser().resolve().parent
    parent.mkdir(parents=True, exist_ok=True)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    _ensure_sqlite_dir(settings.database_url)

    engine = make_engine(settings.database_url)
    init_db(engine)
    session_factory = make_session_factory(engine)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        http = httpx.AsyncClient(follow_redirects=True)
        app.state.http = http
        app.state.settings = settings

        client = GeniosClient(settings, http)
        alerter = Alerter(settings, http)
        feishu_app = FeishuAppClient(settings, http)
        app.state.genios_client = client
        app.state.alerter = alerter
        app.state.feishu_app = feishu_app
        app.state.opportunity_webhook = FeishuWebhook(
            settings.feishu_opportunity_webhook_url,
            settings.feishu_opportunity_webhook_secret,
            http,
            RateLimiter(settings.feishu_rate_limit_per_minute),
        )

        # 崩溃恢复：把卡在 dispatched 的文章打回 queued
        with session_factory() as session:
            requeued = requeue_stale_dispatched(session)
            session.commit()
        if requeued:
            logger.warning("启动恢复：%s 篇文章重新入队", requeued)

        worker_task: asyncio.Task | None = None
        worker = ArticleWorker(settings, session_factory, client, alerter, feishu_app)
        app.state.worker = worker
        if settings.worker_enabled:
            worker_task = asyncio.create_task(worker.run_forever())
        else:
            logger.warning("worker 已禁用（WORKER_ENABLED=0）—— 文章会停在 queued")

        if not settings.genios_configured:
            logger.warning("GeniOS 凭据未配置，worker 处于 dry-run 模式（探针 S1 后填 .env）")

        try:
            yield
        finally:
            worker.stop()
            if worker_task is not None:
                worker_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await worker_task
            # 推送是后台异步跑的，关服务前给它一次跑完的机会，别半路掐断
            await worker.drain()
            await http.aclose()
            engine.dispose()

    app = FastAPI(
        title="campus-gateway",
        description=DESCRIPTION,
        version=__version__,
        lifespan=lifespan,
    )

    # 路由挂载前先放好状态，避免依赖函数在 lifespan 之前被访问
    app.state.settings = settings
    app.state.session_factory = session_factory
    app.state.last_ingest_at = None

    app.include_router(ingest_router)
    app.include_router(opportunities_router)
    app.include_router(push_router)
    app.include_router(debug_router)

    @app.get("/health", tags=["ops"])
    async def health(request: Request) -> dict[str, object]:
        with session_factory() as session:
            latest = session.scalar(select(func.max(Article.created_at)))
            pending = session.scalar(
                select(func.count()).select_from(Article).where(Article.status == "queued")
            )
            failed = session.scalar(
                select(func.count()).select_from(Article).where(Article.status == "failed")
            )
        if latest is not None and latest.tzinfo is None:
            latest = latest.replace(tzinfo=UTC)

        return {
            "status": "ok",
            "version": __version__,
            "now": dt.datetime.now(SHANGHAI).isoformat(timespec="seconds"),
            "genios_configured": settings.genios_configured,
            "genios_dry_run": settings.genios_dry_run or not settings.genios_configured,
            "worker_enabled": settings.worker_enabled,
            "feishu_configured": bool(settings.feishu_opportunity_webhook_url),
            "alert_configured": bool(settings.feishu_alert_webhook_url),
            "enable_push_after": iso_shanghai(settings.enable_push_after),
            "last_article_at": iso_shanghai(latest),
            "last_ingest_at": iso_shanghai(app.state.last_ingest_at)
            if app.state.last_ingest_at
            else None,
            "articles": {"queued": pending or 0, "failed": failed or 0},
        }

    return app


app = create_app()
