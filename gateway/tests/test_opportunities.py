"""阶段 1 验收：机会去重、来源合并、查询过滤。"""

from __future__ import annotations

import datetime as dt

from sqlalchemy import select

from app.models import Opportunity, OpportunitySource
from app.tz import SHANGHAI


def opportunity_body(**overrides) -> dict:
    body = {
        "article_id": "a" * 64,
        "name": "第十五届程序设计竞赛",
        "type": "竞赛",
        "summary": "面向全校本科生的算法竞赛",
        "event_time_raw": "11月2日 9:00-14:00",
        "event_start": "2026-11-02T09:00:00+08:00",
        "event_end": "2026-11-02T14:00:00+08:00",
        "signup_deadline": "2026-10-20T17:00:00+08:00",
        "location": "计算机学院A305",
        "quota": "不限",
        "signup_url": "https://example.nankai.edu.cn/signup",
        "gongneng_practice": "是",
        "source_url": "https://mp.weixin.qq.com/s/abc123",
        "source_account": "南开大学教务处",
        "confidence": 0.92,
        "tags": ["编程", "校级"],
    }
    body.update(overrides)
    return body


class TestAuth:
    def test_post_requires_internal_secret(self, client):
        assert client.post("/opportunities", json=opportunity_body()).status_code == 401

    def test_post_with_secret(self, client, internal_headers):
        response = client.post("/opportunities", json=opportunity_body(), headers=internal_headers)
        assert response.status_code == 200

    def test_requires_name(self, client, internal_headers):
        response = client.post("/opportunities", json={"type": "竞赛"}, headers=internal_headers)
        assert response.status_code == 422


class TestDedup:
    def test_first_write_is_new(self, client, internal_headers):
        body = client.post("/opportunities", json=opportunity_body(), headers=internal_headers).json()
        assert body["created"] is True
        assert body["duplicate"] is False
        assert body["push_status"] == "未推送"

    def test_same_event_from_two_sources_is_duplicate(self, client, internal_headers, session_factory):
        """同一活动被两个公众号转发 → 只有一条记录，第二次 duplicate=true（工作流据此不推送）。"""
        first = client.post(
            "/opportunities", json=opportunity_body(article_id="a" * 64), headers=internal_headers
        ).json()
        second = client.post(
            "/opportunities",
            json=opportunity_body(
                article_id="b" * 64,
                source_account="南开大学计算机学院",
                source_url="https://mp.weixin.qq.com/s/xyz789",
                summary=None,  # 第二次缺简介，也不该覆盖已有的
            ),
            headers=internal_headers,
        ).json()

        assert first["created"] is True
        assert second["created"] is False
        assert second["duplicate"] is True
        assert second["id"] == first["id"]

        with session_factory() as session:
            assert len(list(session.scalars(select(Opportunity)))) == 1
            sources = list(session.scalars(select(OpportunitySource)))
            assert {s.article_id for s in sources} == {"a" * 64, "b" * 64}
            assert session.scalar(select(Opportunity)).summary == "面向全校本科生的算法竞赛"

    def test_duplicate_does_not_reset_push_status(self, client, internal_headers, session_factory):
        created = client.post("/opportunities", json=opportunity_body(), headers=internal_headers).json()
        client.post(
            f"/opportunities/{created['id']}/push-status",
            json={"push_status": "已即时推送"},
            headers=internal_headers,
        )
        again = client.post("/opportunities", json=opportunity_body(), headers=internal_headers).json()
        assert again["duplicate"] is True
        assert again["push_status"] == "已即时推送"

    def test_punctuation_and_spacing_insensitive(self, client, internal_headers, session_factory):
        client.post("/opportunities", json=opportunity_body(), headers=internal_headers)
        client.post(
            "/opportunities",
            json=opportunity_body(name="第十五届 程序设计竞赛！", location="计算机学院 A305"),
            headers=internal_headers,
        )
        with session_factory() as session:
            assert len(list(session.scalars(select(Opportunity)))) == 1

    def test_different_date_is_new_record(self, client, internal_headers, session_factory):
        client.post("/opportunities", json=opportunity_body(), headers=internal_headers)
        client.post(
            "/opportunities",
            json=opportunity_body(event_start="2026-11-09T09:00:00+08:00", event_end=None),
            headers=internal_headers,
        )
        with session_factory() as session:
            assert len(list(session.scalars(select(Opportunity)))) == 2


class TestLowConfidence:
    def test_low_confidence_flag_derived(self, client, internal_headers):
        body = client.post(
            "/opportunities",
            json=opportunity_body(confidence=0.3),
            headers=internal_headers,
        ).json()
        assert body["low_confidence"] is True

    def test_explicit_flag_respected(self, client, internal_headers):
        body = client.post(
            "/opportunities",
            json=opportunity_body(confidence=0.99, low_confidence=True),
            headers=internal_headers,
        ).json()
        assert body["low_confidence"] is True


class TestStatusDerivation:
    def test_expired_deadline_is_closed(self, client, internal_headers):
        body = client.post(
            "/opportunities",
            json=opportunity_body(signup_deadline="2020-01-01T00:00:00+08:00"),
            headers=internal_headers,
        ).json()
        assert body["status"] == "已截止"

    def test_future_signup_start_is_pending(self, client, internal_headers):
        future = dt.datetime.now(SHANGHAI) + dt.timedelta(days=30)
        body = client.post(
            "/opportunities",
            json=opportunity_body(signup_start=future.isoformat(), signup_deadline=None),
            headers=internal_headers,
        ).json()
        assert body["status"] == "未开始"

    def test_open_by_default(self, client, internal_headers):
        body = client.post("/opportunities", json=opportunity_body(), headers=internal_headers).json()
        assert body["status"] == "可参与"


class TestQuery:
    def test_filter_by_type(self, client, internal_headers):
        client.post("/opportunities", json=opportunity_body(), headers=internal_headers)
        client.post(
            "/opportunities",
            json=opportunity_body(name="志愿活动", type="志愿活动与社会实践", event_start="2026-12-01T09:00:00+08:00"),
            headers=internal_headers,
        )
        body = client.get("/opportunities", params={"type": "竞赛"}).json()
        assert body["count"] == 1
        assert body["items"][0]["name"] == "第十五届程序设计竞赛"

    def test_week_current_excludes_past(self, client, internal_headers):
        client.post(
            "/opportunities",
            json=opportunity_body(signup_deadline="2020-01-01T00:00:00+08:00"),
            headers=internal_headers,
        )
        body = client.get("/opportunities", params={"week": "current"}).json()
        assert body["count"] == 0

    def test_week_current_includes_open(self, client, internal_headers):
        future = dt.datetime.now(SHANGHAI) + dt.timedelta(days=3)
        client.post(
            "/opportunities",
            json=opportunity_body(
                signup_deadline=future.isoformat(),
                event_start=future.isoformat(),
                event_end=(future + dt.timedelta(hours=3)).isoformat(),
            ),
            headers=internal_headers,
        )
        body = client.get("/opportunities", params={"week": "current"}).json()
        assert body["count"] == 1

    def test_week_current_excludes_already_finished_event(self, client, internal_headers):
        """上周就办完、又没有截止时间的活动，不该再进周报。"""
        past = dt.datetime.now(SHANGHAI) - dt.timedelta(days=20)
        client.post(
            "/opportunities",
            json=opportunity_body(
                event_start=past.isoformat(),
                event_end=(past + dt.timedelta(hours=2)).isoformat(),
                signup_deadline=None,
            ),
            headers=internal_headers,
        )
        assert client.get("/opportunities", params={"week": "current"}).json()["count"] == 0

    def test_week_current_excludes_far_future_signup(self, client, internal_headers):
        """两个月后才开放报名的活动，不该这周就推。"""
        far = dt.datetime.now(SHANGHAI) + dt.timedelta(days=60)
        client.post(
            "/opportunities",
            json=opportunity_body(
                signup_start=far.isoformat(),
                signup_deadline=(far + dt.timedelta(days=7)).isoformat(),
                event_start=(far + dt.timedelta(days=10)).isoformat(),
                event_end=None,
            ),
            headers=internal_headers,
        )
        assert client.get("/opportunities", params={"week": "current"}).json()["count"] == 0

    def test_get_open_by_default(self, client, internal_headers):
        client.post("/opportunities", json=opportunity_body(), headers=internal_headers)
        assert client.get("/opportunities").status_code == 200

    def test_serialized_times_are_shanghai(self, client, internal_headers):
        client.post("/opportunities", json=opportunity_body(), headers=internal_headers)
        item = client.get("/opportunities").json()["items"][0]
        assert item["event_start"] == "2026-11-02T09:00:00+08:00"
        assert item["signup_deadline"] == "2026-10-20T17:00:00+08:00"
