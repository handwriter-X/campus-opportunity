"""阶段 1 验收：幂等、历史过滤、鉴权、多文章载荷。"""

from __future__ import annotations

from sqlalchemy import select

from app.models import Article
from tests.conftest import make_payload


class TestAuth:
    def test_missing_secret_rejected(self, client):
        response = client.post("/ingest", json=make_payload())
        assert response.status_code == 401

    def test_wrong_secret_rejected(self, client):
        response = client.post("/ingest", json=make_payload(), headers={"X-Ingest-Secret": "nope"})
        assert response.status_code == 401

    def test_correct_secret_accepted(self, client, ingest_headers):
        response = client.post("/ingest", json=make_payload(), headers=ingest_headers)
        assert response.status_code == 200


class TestIngest:
    def test_creates_article(self, client, ingest_headers, session_factory):
        response = client.post("/ingest", json=make_payload(), headers=ingest_headers)
        body = response.json()
        assert body["ok"] is True
        assert body["received"] == 1
        assert body["created"] == 1
        assert body["duplicates"] == 0

        with session_factory() as session:
            article = session.scalar(select(Article))
        assert article is not None
        assert article.status == "queued"
        assert article.title == "关于举办程序设计竞赛的通知"
        assert article.source == "南开大学教务处"
        assert "报名截止时间" in article.text
        assert article.publish_weekday == "星期五"  # 2026-10-02 是星期五

    def test_idempotent_on_repeat(self, client, ingest_headers, session_factory):
        """同一篇文章发两次，只处理一次（阶段 1 验收第 1 条）。"""
        first = client.post("/ingest", json=make_payload(), headers=ingest_headers).json()
        second = client.post("/ingest", json=make_payload(), headers=ingest_headers).json()

        assert first["created"] == 1
        assert second["created"] == 0
        assert second["duplicates"] == 1
        assert second["articles"][0]["duplicate"] is True

        with session_factory() as session:
            assert len(list(session.scalars(select(Article)))) == 1

    def test_duplicate_does_not_reset_status(self, client, ingest_headers, session_factory):
        """重发不能把已完成的文章打回 queued，否则会重复推送（验收清单第 5 条）。"""
        client.post("/ingest", json=make_payload(), headers=ingest_headers)
        with session_factory() as session:
            article = session.scalar(select(Article))
            article.status = "done"
            session.commit()

        client.post("/ingest", json=make_payload(), headers=ingest_headers)
        with session_factory() as session:
            article = session.scalar(select(Article))
        assert article.status == "done"

    def test_url_variants_are_same_article(self, client, ingest_headers, session_factory):
        """带 #fragment 的同一链接不应被当成两篇。"""
        client.post("/ingest", json=make_payload(url="https://a.b/c"), headers=ingest_headers)
        client.post("/ingest", json=make_payload(url="https://a.b/c#from=groupmessage"), headers=ingest_headers)
        with session_factory() as session:
            assert len(list(session.scalars(select(Article)))) == 1


class TestHistoryFilter:
    def test_new_article_is_live(self, client, ingest_headers):
        body = client.post(
            "/ingest",
            json=make_payload(publish_time="2026-10-03T09:00:00+08:00"),
            headers=ingest_headers,
        ).json()
        assert body["articles"][0]["mode"] == "live"
        assert body["articles"][0]["push_eligible"] is True

    def test_old_article_is_backfill_and_not_pushable(self, client, ingest_headers):
        body = client.post(
            "/ingest",
            json=make_payload(publish_time="2026-08-01T09:00:00+08:00"),
            headers=ingest_headers,
        ).json()
        assert body["articles"][0]["mode"] == "backfill"
        assert body["articles"][0]["push_eligible"] is False

    def test_backfill_still_queued_for_extraction(self, client, ingest_headers, session_factory):
        """backfill 仍要送工作流抽取（用于积累评测样本），只是不推送。"""
        client.post(
            "/ingest",
            json=make_payload(publish_time="2026-08-01T09:00:00+08:00"),
            headers=ingest_headers,
        )
        with session_factory() as session:
            article = session.scalar(select(Article))
        assert article.status == "queued"
        assert article.pushes is False

    def test_missing_publish_time_is_backfill(self, client, ingest_headers):
        body = client.post(
            "/ingest", json=make_payload(publish_time=None), headers=ingest_headers
        ).json()
        assert body["articles"][0]["mode"] == "backfill"


class TestMultiArticle:
    def test_aggregated_post_splits(self, client, ingest_headers, session_factory):
        payload = {
            "articles": [
                {"url": "https://a.b/1", "title": "数学建模选拔赛", "mp_name": "X", "content": "10月15日截止"},
                {"url": "https://a.b/2", "title": "人工智能讲座", "mp_name": "X", "content": "10月9日"},
                {"url": "https://a.b/3", "title": "运动会志愿者招募", "mp_name": "X", "content": "需20人"},
            ]
        }
        body = client.post("/ingest", json=payload, headers=ingest_headers).json()
        assert body["received"] == 3
        assert body["created"] == 3
        with session_factory() as session:
            assert len(list(session.scalars(select(Article)))) == 3


class TestMalformedPayload:
    def test_unrecognizable_payload_returns_ok_false(self, client, ingest_headers):
        body = client.post("/ingest", json={"foo": "bar"}, headers=ingest_headers).json()
        assert body["ok"] is False
        assert body["received"] == 0
        assert body["notes"]

    def test_flat_single_article_accepted(self, client, ingest_headers):
        """载荷可能不是 {articles:[...]}，单篇平铺也要认。"""
        body = client.post(
            "/ingest",
            json={"url": "https://a.b/solo", "title": "单篇", "content": "正文"},
            headers=ingest_headers,
        ).json()
        assert body["created"] == 1

    def test_list_payload_accepted(self, client, ingest_headers):
        body = client.post(
            "/ingest",
            json=[{"url": "https://a.b/l1", "title": "一"}],
            headers=ingest_headers,
        ).json()
        assert body["created"] == 1
