"""小程序 BFF 的卡片（独立于 gateway，但版式要一致）。

⚠️ 关键不是好看，而是**按钮的 `value` 必须能被 gateway 的回调认出来** ——
`action` 和 `invite_record_id` 写错了，用户点了就毫无反应。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from bff.cards import ACTION_ACCEPT, ACTION_DECLINE, build_apply_card  # noqa: E402


def _card(**kwargs):
    base = dict(
        title="CANN 大赛组队",
        who="李培涛",
        message="你好，我做过两年算法竞赛，想加入你们。",
        invite_record_id="rec_INV_1",
    )
    base.update(kwargs)
    return build_apply_card(**base)


class TestApplyCard:
    def test_header_names_the_project(self):
        card = _card()
        assert "CANN 大赛组队" in card["header"]["title"]["content"]

    def test_message_is_shown(self):
        """申请留言是这张卡的主角 —— 发起人靠它判断要不要同意。"""
        text = json.dumps(_card(), ensure_ascii=False)
        assert "我做过两年算法竞赛" in text

    def test_empty_message_is_explicit(self):
        text = json.dumps(_card(message=""), ensure_ascii=False)
        assert "没有留言" in text

    def test_buttons_match_gateway_actions(self):
        """⚠️ 这两个字符串**必须**和 `gateway/app/match_cards.py` 里的常量一致。"""
        card = _card()
        buttons = [b for el in card["elements"] if el["tag"] == "action"
                   for b in el["actions"]]
        actions = {b["value"]["action"]: b["value"]["invite_record_id"] for b in buttons}
        assert actions == {ACTION_ACCEPT: "rec_INV_1", ACTION_DECLINE: "rec_INV_1"}

    def test_buttons_carry_apply_source(self):
        """⚠️ 少了 `source: "apply"`，gateway 会按"邀请"方向校验 →
        发起人点「同意」会被回「这条邀请不是发给你的」。"""
        card = _card()
        for el in card["elements"]:
            if el["tag"] == "action":
                for b in el["actions"]:
                    assert b["value"]["source"] == "apply"

    def test_buttons_carry_no_url(self):
        """卡片按钮必须是**回传**，不是跳转 —— 否则点完什么都不发生。"""
        card = _card()
        for el in card["elements"]:
            if el["tag"] == "action":
                for b in el["actions"]:
                    assert "url" not in b

    def test_long_title_is_truncated(self):
        card = _card(title="非常长的项目名称" * 5)
        assert len(card["header"]["title"]["content"]) <= 30


class TestLinkedRecordIds:
    """⚠️ 关联字段写进去是字符串数组，**读回来是对象** —— 按字符串比较永远不相等。"""

    def test_reads_back_object_shape(self):
        from bff.app import linked_record_ids

        raw = [{"record_ids": ["recABC"], "table_id": "tbl_x",
                "text": "CANN大赛组队", "type": "text"}]
        assert linked_record_ids(raw) == ["recABC"]

    def test_accepts_plain_string_array(self):
        from bff.app import linked_record_ids

        assert linked_record_ids(["recABC", "recDEF"]) == ["recABC", "recDEF"]

    def test_accepts_single_dict(self):
        from bff.app import linked_record_ids

        assert linked_record_ids({"record_ids": ["recABC"]}) == ["recABC"]

    def test_empty(self):
        from bff.app import linked_record_ids

        assert linked_record_ids(None) == []
        assert linked_record_ids([]) == []
