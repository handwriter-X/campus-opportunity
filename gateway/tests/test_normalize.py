from __future__ import annotations

import datetime as dt

from app.normalize import (
    article_id_for,
    canonical_url,
    clean_body,
    extract_links,
    is_backfill,
    make_dedup_key,
    normalize_text,
)
from app.tz import SHANGHAI


class TestNormalizeText:
    def test_fullwidth_folded(self):
        assert normalize_text("ＡＢＣ１２３") == normalize_text("abc123")

    def test_whitespace_and_punct_dropped(self):
        assert normalize_text("第十五届 程序设计竞赛！") == normalize_text("第十五届程序设计竞赛")

    def test_none_and_empty(self):
        assert normalize_text(None) == ""
        assert normalize_text("") == ""

    def test_case_insensitive(self):
        assert normalize_text("ACM-ICPC") == normalize_text("acm icpc")


class TestDedupKey:
    def test_same_event_same_key(self):
        start = dt.datetime(2026, 11, 2, 9, 0, tzinfo=SHANGHAI)
        a = make_dedup_key("程序设计竞赛", start, "计算机学院A305")
        b = make_dedup_key("程序设计 竞赛！", start, "计算机学院 A305")
        assert a == b

    def test_different_date_different_key(self):
        a = make_dedup_key("程序设计竞赛", dt.datetime(2026, 11, 2, tzinfo=SHANGHAI), "A305")
        b = make_dedup_key("程序设计竞赛", dt.datetime(2026, 11, 3, tzinfo=SHANGHAI), "A305")
        assert a != b

    def test_falls_back_to_raw_time_expression(self):
        key = make_dedup_key("讲座", None, "报告厅", "11月2日 19:00")
        assert key == make_dedup_key("讲座", None, "报告厅", "11月2日 19:00")

    def test_timezone_invariant_for_same_instant(self):
        """同一时刻用不同时区表示，去重键必须一致。"""
        utc = dt.datetime(2026, 11, 2, 1, 0, tzinfo=dt.timezone.utc)
        sh = utc.astimezone(SHANGHAI)
        assert make_dedup_key("讲座", utc, "报告厅") == make_dedup_key("讲座", sh, "报告厅")


class TestArticleId:
    def test_stable_for_same_url(self):
        assert article_id_for("https://a.b/c") == article_id_for("https://a.b/c")

    def test_fragment_ignored(self):
        assert article_id_for("https://a.b/c#part2") == article_id_for("https://a.b/c")

    def test_trailing_slash_ignored(self):
        assert article_id_for("https://a.b/c/") == article_id_for("https://a.b/c")

    def test_query_kept(self):
        """公众号链接常靠 query 区分文章，不能丢。"""
        assert article_id_for("https://a.b/c?id=1") != article_id_for("https://a.b/c?id=2")

    def test_canonical_url(self):
        assert canonical_url("  https://a.b/c#x  ") == "https://a.b/c"


class TestExtractLinks:
    def test_dedupes_and_keeps_order(self):
        text = "见 https://a.b/1 和 https://a.b/2，还有 https://a.b/1"
        assert extract_links(text) == ["https://a.b/1", "https://a.b/2"]

    def test_strips_chinese_punctuation(self):
        """中文句读紧贴链接时不能被吃进 URL。"""
        assert extract_links("报名：https://a.b/c，截止明天") == ["https://a.b/c"]

    def test_empty(self):
        assert extract_links(None, "") == []


class TestCleanBody:
    def test_strips_tags_and_decodes_entities(self):
        html = "<p>你好&nbsp;世界</p><br/><script>bad()</script>"
        cleaned = clean_body(html)
        assert "你好" in cleaned
        assert "世界" in cleaned
        assert "<p>" not in cleaned
        assert "bad()" not in cleaned

    def test_collapses_blank_lines(self):
        assert "\n\n\n" not in clean_body("a<br/><br/><br/><br/>b")


class TestBackfill:
    def test_old_article_is_backfill(self):
        assert is_backfill(dt.datetime(2026, 9, 30, tzinfo=SHANGHAI), dt.datetime(2026, 10, 1, tzinfo=SHANGHAI))

    def test_new_article_is_live(self):
        assert not is_backfill(dt.datetime(2026, 10, 2, tzinfo=SHANGHAI), dt.datetime(2026, 10, 1, tzinfo=SHANGHAI))

    def test_unknown_time_is_backfill(self):
        """首次启动倒灌历史文章是验收清单第 7 条明令禁止的，所以未知时间一律保守判 backfill。"""
        assert is_backfill(None, dt.datetime(2026, 10, 1, tzinfo=SHANGHAI))

    def test_exact_boundary_is_live(self):
        boundary = dt.datetime(2026, 10, 1, tzinfo=SHANGHAI)
        assert not is_backfill(boundary, boundary)
