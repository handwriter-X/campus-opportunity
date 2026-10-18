"""公众号经常只用二维码报名 —— 卡片要诚实，别给一个点不动的按钮。"""

from __future__ import annotations

import json

from app.card_kit import build_opportunity_card

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


def _card(**overrides):
    """默认**没有报名链接** —— 正是要测的那种情况。"""
    return build_opportunity_card(
        {**ITEM, "signup_url": "", **overrides},
        original_url="https://mp.weixin.qq.com/s/x",
    )


def _buttons(card):
    return [b for el in card["elements"] if el["tag"] == "action" for b in el["actions"]]


class TestSignupMethod:
    def test_qr_method_changes_button_wording(self):
        card = _card(signup_method="扫描海报二维码报名")
        buttons = _buttons(card)
        assert len(buttons) == 1
        assert "扫码" in buttons[0]["text"]["content"]
        assert buttons[0]["type"] == "primary"

    def test_non_qr_method_says_look_at_original(self):
        card = _card(signup_method="现场报名")
        buttons = _buttons(card)
        assert len(buttons) == 1
        assert "原文" in buttons[0]["text"]["content"]
        assert "扫码" not in buttons[0]["text"]["content"]

    def test_method_is_shown_on_card(self):
        card = _card(signup_method="扫描海报二维码报名")
        text = json.dumps(card, ensure_ascii=False)
        assert "报名方式" in text
        assert "扫描海报二维码报名" in text

    def test_method_url_is_not_repeated_when_button_exists(self):
        """有链接时，别再写一行「报名方式：登录 https://…」—— 纯噪音。"""
        card = build_opportunity_card(
            {**ITEM, "signup_method": "登录 https://example.nankai.edu.cn/cpc"},
        )
        text = json.dumps(card, ensure_ascii=False)
        assert "报名方式" not in text

    def test_method_text_kept_when_it_adds_info(self):
        card = build_opportunity_card(
            {**ITEM, "signup_method": "登录 https://x.y/z 后填表"},
        )
        text = json.dumps(card, ensure_ascii=False)
        assert "报名方式" in text
        assert "后填表" in text

    def test_no_link_and_no_original_url_has_no_buttons(self):
        card = build_opportunity_card({**ITEM, "signup_url": ""})
        assert _buttons(card) == []
