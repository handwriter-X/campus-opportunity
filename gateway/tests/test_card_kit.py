"""卡片版式：**标题就是机会名**，一条机会一张卡。"""

from __future__ import annotations

import json

from app.card_kit import (
    build_opportunity_card,
    build_opportunity_cards,
    fmt_when,
    payload_item_to_item,
    row_to_item,
)

ITEM = {
    "name": "南开大学第十六届程序设计竞赛",
    "type": "竞赛",
    "summary": "面向全校本科生的个人赛。",
    "event_time_text": "11月2日 9:00-14:00",
    "signup_deadline": "2026-10-25T23:59:59+08:00",
    "location": "计算机学院 A305",
    "audience": "全校本科生",
    "quota": "一等奖 5 名",
    "signup_url": "https://example.nankai.edu.cn/cpc",
}


def _text(card: dict) -> str:
    return json.dumps(card, ensure_ascii=False)


class TestOpportunityCard:
    def test_header_is_the_opportunity_name(self):
        """⚠️ 标题栏是飞书卡片里**唯一能放大**的位置 —— 必须放机会名。"""
        card = build_opportunity_card(ITEM)
        assert card is not None
        assert "程序设计竞赛" in card["header"]["title"]["content"]

    def test_deadline_comes_first(self):
        card = build_opportunity_card(ITEM)
        first = card["elements"][0]["text"]["content"]
        assert "报名截止" in first
        assert "10月25日" in first

    def test_has_apply_and_original_buttons(self):
        card = build_opportunity_card(
            ITEM, original_url="https://mp.weixin.qq.com/s/x"
        )
        buttons = [b for el in card["elements"] if el["tag"] == "action"
                   for b in el["actions"]]
        urls = {b["text"]["content"]: b["url"] for b in buttons}
        assert urls["立即报名"] == "https://example.nankai.edu.cn/cpc"
        assert urls["查看原文"] == "https://mp.weixin.qq.com/s/x"

    def test_without_link_the_original_article_becomes_primary(self):
        """没有报名链接时不能留一个点不动的「立即报名」。"""
        item = dict(ITEM)
        item["signup_url"] = ""
        card = build_opportunity_card(item, original_url="https://mp.weixin.qq.com/s/x")
        buttons = [b for el in card["elements"] if el["tag"] == "action"
                   for b in el["actions"]]
        assert len(buttons) == 1
        assert buttons[0]["type"] == "primary"
        assert buttons[0]["url"] == "https://mp.weixin.qq.com/s/x"
        assert "原文" in buttons[0]["text"]["content"]

    def test_long_name_is_truncated_in_header(self):
        card = build_opportunity_card({**ITEM, "name": "很长的活动名" * 10})
        assert len(card["header"]["title"]["content"]) <= 40

    def test_empty_name_returns_none(self):
        assert build_opportunity_card({"name": ""}) is None

    def test_template_follows_type(self):
        assert build_opportunity_card(ITEM)["header"]["template"] == "turquoise"
        assert build_opportunity_card({**ITEM, "type": "校园文体活动"})["header"]["template"] == "purple"


class TestMultipleItems:
    def test_one_card_per_opportunity(self):
        payload = {"items": [ITEM, {**ITEM, "name": "数学建模校内选拔赛"}]}
        cards = build_opportunity_cards(payload, source="某公众号", url="https://mp.weixin.qq.com/s/x")
        assert len(cards) == 2
        names = [c["header"]["title"]["content"] for c in cards]
        assert "程序设计竞赛" in names[0]
        assert "数学建模" in names[1]

    def test_items_without_name_are_skipped(self):
        payload = {"items": [ITEM, {"type": "竞赛"}]}
        assert len(build_opportunity_cards(payload, source="x", url=None)) == 1


class TestRowMapping:
    def test_bitable_row_maps_to_same_shape(self):
        """对话补发卡片走的是**表里的行**，版式必须和模块一完全一致。"""
        row = {
            "record_id": "rec_x",
            "机会名称": [{"text": "智能体应用创新大赛", "type": "text"}],
            "类型": "竞赛",
            "报名截止": 1793375999000,
            "报名链接": [{"text": "https://jwc.nankai.edu.cn/a", "type": "text"}],
            "原文链接": [{"text": "https://mp.weixin.qq.com/s/y", "type": "text"}],
        }
        card = build_opportunity_card(row_to_item(row))
        text = _text(card)
        assert "智能体应用创新大赛" in text
        assert "https://jwc.nankai.edu.cn/a" in text
        assert "https://mp.weixin.qq.com/s/y" in text

    def test_payload_item_maps_to_same_shape(self):
        item = payload_item_to_item(ITEM)
        assert item["name"] == ITEM["name"]
        assert item["signup_url"] == ITEM["signup_url"]


class TestFmtWhen:
    def test_milliseconds(self):
        assert fmt_when(1793375999000) == "10月30日 23:59"

    def test_iso_string(self):
        assert fmt_when("2026-10-25T23:59:59+08:00") == "10月25日 23:59"

    def test_unparseable_text_kept(self):
        assert fmt_when("报名咨询群") == "报名咨询群"

    def test_empty(self):
        assert fmt_when(None) == ""
