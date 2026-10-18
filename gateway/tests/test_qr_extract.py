"""从正文图片里解报名二维码。

夹具里的 URL 是**三篇真实文章解码出来的原样文本**（2026-10-18 实测），
见 `docs/findings.md` Q20。这里不联网 —— 只锁"怎么挑"。
"""

from __future__ import annotations

import pytest

from app import qr_extract
from app.qr_extract import (
    apply_signup,
    choose_signup,
    enrich_payload,
    html_of,
    image_urls,
)

# 文章①：一张海报上同时印了飞书表单和问卷星
REAL_CODES = [
    "https://nankai.feishu.cn/share/base/form/shrcnkzEL7msWozZI9z2ktyzcSL?ccm_open_type=form_url",
    "https://v.wjx.cn/vm/wxmBje4.aspx",
    "http://weixin.qq.com/r/DhEtNUfEphrZrQNW90Qc",          # 关注公众号
]
CHAT_CODE = "https://applink.feishu.cn/client/chat/chatter/add_by_link?link_token=f22se044"


class TestImageUrls:
    def test_extracts_and_dedupes(self):
        html = """
        <p><img data-src="https://mmbiz.qpic.cn/a.jpg" src="https://mmbiz.qpic.cn/a.jpg"></p>
        <p><img src="https://mmbiz.qpic.cn/b.png"></p>
        <p><img src="https://mmbiz.qpic.cn/a.jpg"></p>
        """
        assert image_urls(html) == [
            "https://mmbiz.qpic.cn/a.jpg",
            "https://mmbiz.qpic.cn/b.png",
        ]

    def test_ignores_non_wechat_hosts_and_data_uris(self):
        html = '<img src="data:image/png;base64,AAA"><img src="https://evil.example.com/x.png">'
        assert image_urls(html) == []

    def test_respects_limit(self):
        html = "".join(f'<img src="https://mmbiz.qpic.cn/{i}.jpg">' for i in range(30))
        assert len(image_urls(html, limit=5)) == 5


class TestChooseSignup:
    def test_prefers_form_over_follow_qr(self):
        url, hint = choose_signup(REAL_CODES)
        assert url.startswith("https://nankai.feishu.cn/share/base/form/")
        assert hint == ""

    def test_questionnaire_counts_as_form(self):
        url, _ = choose_signup(["https://v.wjx.cn/vm/Q4A68hI.aspx"])
        assert url == "https://v.wjx.cn/vm/Q4A68hI.aspx"

    def test_follow_qr_is_never_a_signup_link(self):
        assert choose_signup(["http://weixin.qq.com/r/DhEtNUfEphrZrQNW90Qc"]) == ("", "")

    def test_chat_link_is_not_a_signup_link(self):
        """加群 ≠ 报名。写进 signup_url 会让「立即报名」变成加群，是骗人。"""
        url, hint = choose_signup([CHAT_CODE])
        assert url == ""
        assert "群" in hint

    def test_form_beats_chat(self):
        url, hint = choose_signup([CHAT_CODE, REAL_CODES[0]])
        assert url == REAL_CODES[0]
        assert hint == ""

    def test_ignores_non_url_payloads(self):
        assert choose_signup(["这是一段文字", "", None]) == ("", "")

    def test_empty(self):
        assert choose_signup([]) == ("", "")


class TestTitleScoring:
    """多个表单候选时，按标题挑"报名"那个（问卷星的标题能读到）。"""

    def test_signup_words_win(self):
        assert qr_extract.title_score("活动报名登记表") > 0
        assert qr_extract.title_score("交流话题征集") < 0

    def test_unknown_title_is_neutral(self):
        """读不到标题（比如飞书表单）就是 0 —— **不能因为读不到就扣分**。"""
        assert qr_extract.title_score("") == 0

    def test_neutral_title_beats_other_purpose(self):
        assert qr_extract.title_score("") > qr_extract.title_score("满意度调研")

    @pytest.mark.asyncio
    async def test_single_candidate_never_fetches(self, monkeypatch):
        """绝大多数文章只有一个问卷 —— 那条路径不该多一次网络请求。"""

        def boom(*_args, **_kwargs):
            raise AssertionError("不该联网")

        monkeypatch.setattr(qr_extract, "_fetch_title", boom)
        assert await qr_extract.pick_form(["https://v.wjx.cn/vm/only.aspx"]) == \
            "https://v.wjx.cn/vm/only.aspx"

    @pytest.mark.asyncio
    async def test_multiple_candidates_pick_by_title(self, monkeypatch):
        titles = {
            "https://v.wjx.cn/vm/collect.aspx": "交流话题征集",
            "https://nankai.feishu.cn/share/base/form/abc": "",   # 飞书读不到
        }
        monkeypatch.setattr(qr_extract, "_fetch_title", lambda url, timeout=5.0: titles[url])
        # 读不到标题的飞书表单是 0 分，比"征集"(-2) 高 —— 选它
        picked = await qr_extract.pick_form(list(titles))
        assert picked == "https://nankai.feishu.cn/share/base/form/abc"

    @pytest.mark.asyncio
    async def test_tie_keeps_article_order(self, monkeypatch):
        monkeypatch.setattr(qr_extract, "_fetch_title", lambda url, timeout=5.0: "")
        first = "https://v.wjx.cn/vm/first.aspx"
        second = "https://v.wjx.cn/vm/second.aspx"
        assert await qr_extract.pick_form([first, second]) == first

    @pytest.mark.asyncio
    async def test_empty(self):
        assert await qr_extract.pick_form([]) == ""


class TestApplySignup:
    def _payload(self, **item):
        return {"items": [{"name": "某活动", **item}]}

    def test_fills_missing_signup_url(self):
        payload = self._payload()
        assert apply_signup(payload, "https://v.wjx.cn/vm/x.aspx", "")
        assert payload["items"][0]["signup_url"] == "https://v.wjx.cn/vm/x.aspx"

    def test_does_not_overwrite_model_extracted_url(self):
        payload = self._payload(signup_url="https://jwc.nankai.edu.cn/x")
        assert not apply_signup(payload, "https://v.wjx.cn/vm/y.aspx", "")
        assert payload["items"][0]["signup_url"] == "https://jwc.nankai.edu.cn/x"

    def test_writes_method_hint(self):
        payload = self._payload()
        assert apply_signup(payload, "", "扫描二维码加入咨询群")
        assert payload["items"][0]["signup_method_text"] == "扫描二维码加入咨询群"

    def test_multiple_items_are_left_alone(self):
        """一篇文章多个机会时，没人知道二维码属于哪一个 —— 宁可不填。"""
        payload = {"items": [{"name": "A"}, {"name": "B"}]}
        assert not apply_signup(payload, "https://v.wjx.cn/vm/x.aspx", "")
        assert "signup_url" not in payload["items"][0]


class TestHtmlOf:
    def test_plain_content(self):
        assert html_of({"content": "<p>hi</p>"}) == "<p>hi</p>"

    def test_unescapes_webhook_escaped_content(self):
        """采集器把正文 json.dumps 过一次（`\\"` / `\\n`），要还原。"""
        raw = {"content": '{\\"a\\": 1}'}
        assert html_of(raw) == '{"a": 1}'

    def test_articles_list_shape(self):
        assert html_of({"articles": [{"content": "<p>x</p>"}]}) == "<p>x</p>"

    def test_garbage(self):
        assert html_of(None) == ""
        assert html_of("not a dict") == ""
        assert html_of({"content": 123}) == ""


class TestEnrichPayload:
    @pytest.mark.asyncio
    async def test_end_to_end_with_stubbed_decoder(self, monkeypatch):
        async def fake_find(html, **_):
            assert "<img" in html
            return "https://v.wjx.cn/vm/x.aspx", ""

        monkeypatch.setattr(qr_extract, "find_signup_link", fake_find)
        payload = {"items": [{"name": "某活动"}]}
        raw = {"content": '<p><img src="https://mmbiz.qpic.cn/a.jpg"></p>'}
        assert await enrich_payload(payload, raw)
        assert payload["items"][0]["signup_url"] == "https://v.wjx.cn/vm/x.aspx"

    @pytest.mark.asyncio
    async def test_no_html_is_a_noop(self):
        payload = {"items": [{"name": "某活动"}]}
        assert not await enrich_payload(payload, {"content": ""})
        assert "signup_url" not in payload["items"][0]
