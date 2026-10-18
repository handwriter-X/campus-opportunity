"""Markdown → 飞书富文本（post）。

起因：模型返回的是 Markdown，而 `msg_type=text` 会把 `**` 原样显示 ——
用户看到满屏星号。这里把该转的都转掉，**转不了的原样保留**（宁丑不丢）。
"""

from __future__ import annotations

from app.richtext import markdown_to_post


def _paragraphs(markdown: str) -> list[list[dict]]:
    post = markdown_to_post(markdown)
    assert post is not None
    return post["zh_cn"]["content"]


def _texts(paragraph: list[dict]) -> str:
    return "".join(p.get("text", "") for p in paragraph)


class TestInline:
    def test_bold_becomes_style(self):
        [para] = _paragraphs("**智能体应用创新大赛**")
        assert para == [{"tag": "text", "text": "智能体应用创新大赛", "style": ["bold"]}]

    def test_link_becomes_anchor(self):
        [para] = _paragraphs("[报名](https://jwc.nankai.edu.cn/x)")
        assert para[0]["tag"] == "a"
        assert para[0]["href"] == "https://jwc.nankai.edu.cn/x"
        assert para[0]["text"] == "报名"

    def test_bold_and_link_in_one_line(self):
        [para] = _paragraphs("看 **这个** [链接](https://a.b/c)")
        assert "看 " in _texts(para)
        assert any(p.get("style") == ["bold"] and p["text"] == "这个" for p in para)
        assert any(p["tag"] == "a" and p["href"] == "https://a.b/c" for p in para)

    def test_bare_url_stays_text(self):
        """裸 URL 保持文本 —— 自动加链接会被飞书重新编码（Q15 的坑）。"""
        [para] = _paragraphs("https://accounts.feishu.cn/x?a=%2Fb")
        assert para[0]["tag"] == "text"
        assert "%2F" in para[0]["text"]


class TestBlocks:
    def test_bullets_become_dots(self):
        paras = _paragraphs("- 第一\n- 第二")
        assert [_texts(p) for p in paras] == ["• 第一", "• 第二"]

    def test_heading_is_bold_and_has_no_hashes(self):
        [para] = _paragraphs("## 本周推荐")
        assert _texts(para) == "本周推荐"
        assert para[0].get("style") == ["bold"]

    def test_quote_marker_dropped(self):
        [para] = _paragraphs("> 一句引用")
        assert _texts(para) == "一句引用"

    def test_code_fence_content_kept(self):
        paras = _paragraphs("```\nprint(1)\n```")
        assert [_texts(p) for p in paras] == ["print(1)"]

    def test_inline_code_backticks_removed(self):
        [para] = _paragraphs("用 `search_records` 读表")
        assert "`" not in _texts(para)


class TestEdges:
    def test_empty_returns_none(self):
        assert markdown_to_post("") is None
        assert markdown_to_post("   \n\n  ") is None

    def test_blank_lines_do_not_create_empty_paragraphs(self):
        paras = _paragraphs("第一段\n\n\n第二段")
        assert len(paras) == 2

    def test_plain_text_survives(self):
        paras = _paragraphs("同学你好，有什么可以帮你？")
        assert _texts(paras[0]) == "同学你好，有什么可以帮你？"
