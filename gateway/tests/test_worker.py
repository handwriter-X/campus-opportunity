"""阶段 1 验收：worker 重试、失败落库、派发载荷契约。"""

from __future__ import annotations

import asyncio
import datetime as dt

import pytest
from sqlalchemy import select

from app.config import Settings
from app.genios_client import DispatchResult, GeniosNotConfigured
from app.models import Article
from app.store import ingest_article
from app.tz import SHANGHAI, UTC
from app.worker import ArticleWorker, backoff_seconds, build_article_payload


class FakeClient:
    def __init__(self, results: list | None = None) -> None:
        self.results = list(results or [])
        self.calls: list[dict] = []

    async def dispatch(self, payload: dict) -> DispatchResult:
        self.calls.append(payload)
        if not self.results:
            return DispatchResult(ok=True, task_id="task-1", response={"ok": True})
        result = self.results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


class FakeAlerter:
    def __init__(self) -> None:
        self.alerts: list[tuple[str, list[str]]] = []

    async def alert(self, title: str, lines: list[str], **_kwargs) -> bool:
        self.alerts.append((title, lines))
        return True


@pytest.fixture
def worker_factory(session_factory, settings: Settings):
    def build(client: FakeClient | None = None, **overrides) -> tuple[ArticleWorker, FakeClient, FakeAlerter]:
        effective = settings.model_copy(update=overrides) if overrides else settings
        fake_client = client or FakeClient()
        alerter = FakeAlerter()
        worker = ArticleWorker(effective, session_factory, fake_client, alerter)
        return worker, fake_client, alerter

    return build


def seed_article(session_factory, *, url: str = "https://a.b/1", publish_time=None, mode="live") -> int:
    with session_factory() as session:
        outcome = ingest_article(
            session,
            article_id=url.replace("/", "_"),
            url=url,
            title="测试文章",
            source="测试公众号",
            text="正文内容",
            publish_time=publish_time or dt.datetime(2026, 10, 3, 9, 0, tzinfo=SHANGHAI),
            publish_weekday="星期六",
            links=["https://example.nankai.edu.cn/signup"],
            mode=mode,
        )
        session.commit()
        return outcome.article.id


def load_article(session_factory, article_id: int) -> Article:
    with session_factory() as session:
        article = session.get(Article, article_id)
        assert article is not None
        return article


class TestPayloadContract:
    def test_fields_match_spec_7_1(self, session_factory):
        article_id = seed_article(session_factory)
        payload = build_article_payload(load_article(session_factory, article_id))
        assert set(payload) == {
            "article_id", "mode", "source", "title", "url",
            "publish_time", "publish_weekday", "text", "links",
        }

    def test_publish_time_is_iso_shanghai(self, session_factory):
        article_id = seed_article(session_factory)
        payload = build_article_payload(load_article(session_factory, article_id))
        assert payload["publish_time"] == "2026-10-03T09:00:00+08:00"
        assert payload["publish_weekday"] == "星期六"

    def test_backfill_mode_propagated(self, session_factory):
        article_id = seed_article(session_factory, mode="backfill")
        payload = build_article_payload(load_article(session_factory, article_id))
        assert payload["mode"] == "backfill"


class TestDispatch:
    def test_success_marks_done(self, session_factory, worker_factory):
        article_id = seed_article(session_factory)
        worker, client, _ = worker_factory()

        processed = asyncio.run(worker.run_once())

        assert processed == 1
        assert len(client.calls) == 1
        article = load_article(session_factory, article_id)
        assert article.status == "done"
        assert article.genios_task_id == "task-1"

    def test_nothing_to_do_returns_zero(self, session_factory, worker_factory):
        worker, _, _ = worker_factory()
        assert asyncio.run(worker.run_once()) == 0

    def test_claim_marks_dispatched_so_no_double_send(self, session_factory, worker_factory):
        seed_article(session_factory, url="https://a.b/1")
        worker, client, _ = worker_factory()

        asyncio.run(worker.run_once())
        asyncio.run(worker.run_once())

        assert len(client.calls) == 1  # 第二次不应重复派发


class TestRetry:
    def test_transient_failure_is_requeued_with_backoff(self, session_factory, worker_factory):
        article_id = seed_article(session_factory)
        worker, _, _ = worker_factory(
            FakeClient([DispatchResult(ok=False, task_id=None, response=None, error="HTTP 500")]),
            worker_max_attempts=3,
            worker_backoff_base_seconds=2.0,
        )

        asyncio.run(worker.run_once())

        article = load_article(session_factory, article_id)
        assert article.status == "queued"
        assert article.attempts == 1
        assert article.last_error == "HTTP 500"
        assert article.next_attempt_at is not None
        assert article.next_attempt_at > dt.datetime.now(UTC)

    def test_gives_up_after_max_attempts(self, session_factory, worker_factory):
        article_id = seed_article(session_factory)
        failure = DispatchResult(ok=False, task_id=None, response=None, error="HTTP 500")
        worker, _, _ = worker_factory(
            FakeClient([failure] * 5),
            worker_max_attempts=3,
            worker_backoff_base_seconds=0.0,
        )

        for _ in range(3):
            asyncio.run(worker.run_once())
            # 清掉退避等待，让下一次 run_once 立刻能认领
            with session_factory() as session:
                article = session.get(Article, article_id)
                article.next_attempt_at = dt.datetime.now(UTC)
                session.commit()

        article = load_article(session_factory, article_id)
        assert article.status == "failed"
        assert article.attempts == 3
        assert "HTTP 500" in article.last_error

    def test_failed_article_is_not_reclaimed(self, session_factory, worker_factory):
        seed_article(session_factory)
        worker, client, _ = worker_factory(
            FakeClient([DispatchResult(ok=False, task_id=None, response=None, error="boom")] * 5),
            worker_max_attempts=1,
        )
        asyncio.run(worker.run_once())
        assert asyncio.run(worker.run_once()) == 0
        assert len(client.calls) == 1

    def test_unconfigured_genios_fails_fast_and_alerts(self, session_factory, worker_factory):
        """配置错误重试没意义 —— 应立刻判失败并告警，而不是白耗 4 次重试。"""
        article_id = seed_article(session_factory)
        worker, _, alerter = worker_factory(
            FakeClient([GeniosNotConfigured("GENIOS_API_KEY 为空")]),
            worker_max_attempts=4,
        )

        asyncio.run(worker.run_once())

        article = load_article(session_factory, article_id)
        assert article.status == "failed"
        assert "配置错误" in article.last_error
        assert alerter.alerts and "GeniOS 配置错误" in alerter.alerts[0][0]

    def test_backoff_is_exponential_and_capped(self):
        assert backoff_seconds(2.0, 0) == 2.0
        assert backoff_seconds(2.0, 1) == 4.0
        assert backoff_seconds(2.0, 2) == 8.0
        assert backoff_seconds(2.0, 100) == 300.0  # 封顶


class TestLivenessMonitor:
    def test_no_alert_when_no_articles(self, session_factory, worker_factory):
        worker, _, alerter = worker_factory()
        assert asyncio.run(worker.check_liveness()) is False
        assert alerter.alerts == []

    def test_alert_when_idle_too_long(self, session_factory, worker_factory):
        article_id = seed_article(session_factory)
        with session_factory() as session:
            article = session.get(Article, article_id)
            article.created_at = dt.datetime.now(UTC) - dt.timedelta(hours=10)
            session.commit()

        worker, _, alerter = worker_factory(alert_if_no_ingest_minutes=180)
        assert asyncio.run(worker.check_liveness()) is True
        assert "采集端疑似失效" in alerter.alerts[0][0]

    def test_no_alert_when_recent(self, session_factory, worker_factory):
        seed_article(session_factory)
        worker, _, alerter = worker_factory(alert_if_no_ingest_minutes=180)
        assert asyncio.run(worker.check_liveness()) is False
        assert alerter.alerts == []
