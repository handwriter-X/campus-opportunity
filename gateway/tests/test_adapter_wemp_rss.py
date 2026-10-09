"""We-MP-RSS 适配层回归测试。

载荷形状取自**上游源码**（Q6 于 2026-10-05 读 `jobs/webhook.py:72-98` 的默认模板关闭），
见 docs/findings.md。这里把它固化成测试，防止以后改适配层时把已知的真实结构改坏。
"""

from __future__ import annotations

import datetime as dt

from app.adapters.wemp_rss import parse_payload


def real_payload(**overrides) -> dict:
    """按上游默认模板逐字构造的载荷（字段名列与上游一致）。"""
    article = {
        "id": "MzA3abc==",
        "mp_id": "MP_WXS_123",
        "title": "关于举办程序设计竞赛的通知",
        "pic_url": "https://mmbiz.qpic.cn/x.jpg",
        "url": "https://mp.weixin.qq.com/s/abc",
        "description": "报名截止 2026年10月20日，地点计算机学院A305。",
        "publish_time": "2026-10-05 09:30:00",  # 上游是 naive 字符串
    }
    article.update(overrides.pop("article", {}))
    payload = {
        "feed": {"id": "MP_WXS_123", "name": "南开就业"},
        "articles": [article],
        "task": {"id": "uuid-1", "name": "每日推送"},
        "now": "2026-10-05 15:57:00",
    }
    payload.update(overrides)
    return payload


class TestRealPayloadShape:
    def test_fields_map(self):
        articles, notes = parse_payload(real_payload())
        assert len(articles) == 1
        a = articles[0]
        assert a.url == "https://mp.weixin.qq.com/s/abc"
        assert a.title == "关于举办程序设计竞赛的通知"
        assert a.text == "报名截止 2026年10月20日，地点计算机学院A305。"
        assert notes == []

    def test_publish_time_is_shanghai_not_naive(self):
        """上游给的是 naive 字符串；必须落到 Asia/Shanghai，不能是 naive。"""
        articles, _ = parse_payload(real_payload())
        published = articles[0].publish_time
        assert published is not None
        assert published.tzinfo is not None
        assert published.utcoffset() == dt.timedelta(hours=8)
        assert published.hour == 9  # 没被误当 UTC 平移


class TestEnvelopeSourceFallback:
    def test_source_taken_from_feed_name(self):
        """Q6：公众号名在信封层 feed.name，不在文章对象里（文章只有 mp_id）。"""
        articles, notes = parse_payload(real_payload())
        assert articles[0].source == "南开就业"
        assert notes == []

    def test_article_level_source_wins(self):
        """文章自己带了 mp_name 时，优先用文章级的。"""
        articles, _ = parse_payload(real_payload(article={"mp_name": "文章级来源"}))
        assert articles[0].source == "文章级来源"

    def test_missing_everywhere_is_reported(self):
        payload = real_payload()
        payload.pop("feed")
        articles, notes = parse_payload(payload)
        assert articles[0].source is None
        assert any("缺少公众号名" in n for n in notes)
