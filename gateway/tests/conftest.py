"""pytest 公共夹具。

测试一律用临时 SQLite，且 `_env_file=None` —— 避免开发者本机的 .env 影响断言。
"""

from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

import pytest

GATEWAY_DIR = Path(__file__).resolve().parents[1]
if str(GATEWAY_DIR) not in sys.path:
    sys.path.insert(0, str(GATEWAY_DIR))

from fastapi.testclient import TestClient  # noqa: E402

from app.config import Settings  # noqa: E402
from app.main import create_app  # noqa: E402
from app.store import init_db, make_engine, make_session_factory  # noqa: E402
from app.tz import SHANGHAI  # noqa: E402

INGEST_SECRET = "test-ingest-secret"
INTERNAL_SECRET = "test-internal-secret"
PUSH_AFTER = dt.datetime(2026, 10, 1, 0, 0, tzinfo=SHANGHAI)


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        _env_file=None,
        database_url=f"sqlite:///{(tmp_path / 'test.db').as_posix()}",
        worker_enabled=False,
        genios_dry_run=True,
        ingest_shared_secret=INGEST_SECRET,
        internal_shared_secret=INTERNAL_SECRET,
        enable_push_after=PUSH_AFTER,
        debug_capture_dir=str(tmp_path / "captures"),
        debug_endpoints_enabled=True,
        feishu_opportunity_webhook_url="",
        feishu_alert_webhook_url="",
    )


@pytest.fixture
def session_factory(settings: Settings):
    engine = make_engine(settings.database_url)
    init_db(engine)
    factory = make_session_factory(engine)
    yield factory
    engine.dispose()


@pytest.fixture
def client(settings: Settings):
    with TestClient(create_app(settings)) as test_client:
        yield test_client


@pytest.fixture
def ingest_headers() -> dict[str, str]:
    return {"X-Ingest-Secret": INGEST_SECRET}


@pytest.fixture
def internal_headers() -> dict[str, str]:
    return {"X-Internal-Secret": INTERNAL_SECRET}


def make_payload(
    *,
    url: str = "https://mp.weixin.qq.com/s/abc123",
    title: str = "关于举办程序设计竞赛的通知",
    source: str = "南开大学教务处",
    content: str = "报名截止时间：2026年10月20日。详见 https://example.nankai.edu.cn/signup",
    publish_time: str | None = "2026-10-02T09:30:00+08:00",
) -> dict:
    article = {"url": url, "title": title, "mp_name": source, "content": content}
    if publish_time is not None:
        article["publish_time"] = publish_time
    return {"articles": [article]}
