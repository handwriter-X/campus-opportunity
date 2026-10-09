"""探针端点：S5 的 /_debug/echo 与 S3 的 /ingest/_debug。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest


class TestEcho:
    def test_echoes_body(self, client):
        response = client.post("/_debug/echo", json={"from": "genios", "ts": "test"})
        assert response.status_code == 200
        body = response.json()
        assert body["ok"] is True
        assert body["body"] == {"from": "genios", "ts": "test"}

    def test_echoes_headers(self, client):
        body = client.post("/_debug/echo", json={}, headers={"X-Probe": "s5"}).json()
        assert body["headers"].get("x-probe") == "s5"

    def test_accepts_non_json(self, client):
        response = client.post(
            "/_debug/echo", content=b"plain text body", headers={"Content-Type": "text/plain"}
        )
        assert response.status_code == 200
        assert response.json()["body"] == "plain text body"

    def test_needs_no_auth(self, client):
        """GeniOS 的 HTTP 节点不会带我们的密钥，所以这个端点必须免鉴权。"""
        assert client.post("/_debug/echo", json={}).status_code == 200


class TestIngestDebug:
    def test_captures_payload_to_disk(self, client, settings):
        payload = {"articles": [{"url": "https://a.b/1", "title": "标题", "content": "正文",
                                 "publish_time": "2026-10-02T09:00:00+08:00"}]}
        body = client.post("/ingest/_debug", json=payload).json()

        assert body["ok"] is True
        assert body["recognized_articles"] == 1
        assert body["preview"][0]["url"] == "https://a.b/1"

        capture = Path(body["captured_to"])
        assert capture.exists()
        saved = json.loads(capture.read_text(encoding="utf-8"))
        assert saved["parsed_json"] == payload
        assert "content-type" in saved["headers"]

    def test_reports_unrecognized_fields(self, client):
        body = client.post("/ingest/_debug", json={"weird": "shape"}).json()
        assert body["recognized_articles"] == 0
        assert body["notes"]

    def test_does_not_write_business_db(self, client, session_factory):
        from sqlalchemy import select

        from app.models import Article

        client.post("/ingest/_debug", json={"articles": [{"url": "https://a.b/1", "title": "T"}]})
        with session_factory() as session:
            assert list(session.scalars(select(Article))) == []

    def test_captures_non_json_body(self, client):
        body = client.post(
            "/ingest/_debug", content="url=https://a.b/1", headers={"Content-Type": "text/plain"}
        ).json()
        assert body["ok"] is True
        assert body["recognized_articles"] == 0


class TestDebugDisabled:
    @pytest.fixture
    def locked_client(self, settings):
        from fastapi.testclient import TestClient

        from app.main import create_app

        with TestClient(create_app(settings.model_copy(update={"debug_endpoints_enabled": False}))) as c:
            yield c

    def test_echo_404_when_disabled(self, locked_client):
        assert locked_client.post("/_debug/echo", json={}).status_code == 404

    def test_ingest_debug_404_when_disabled(self, locked_client):
        assert locked_client.post("/ingest/_debug", json={}).status_code == 404


class TestHealth:
    def test_health_reports_state(self, client):
        body = client.get("/health").json()
        assert body["status"] == "ok"
        assert body["worker_enabled"] is False
        assert body["articles"] == {"queued": 0, "failed": 0}

    def test_health_counts_queue(self, client, ingest_headers):
        client.post(
            "/ingest",
            json={"articles": [{"url": "https://a.b/1", "title": "T", "content": "C"}]},
            headers=ingest_headers,
        )
        body = client.get("/health").json()
        assert body["articles"]["queued"] == 1
        assert body["last_article_at"] is not None
