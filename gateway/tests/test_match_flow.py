"""模块二 · 组队匹配（gateway 侧）。

覆盖三块：
1. **多维表格字段解析** —— 富文本分段、人员字段取 `id` 不取 `name`（这两个都曾静默出错）
2. **两张卡片的构造** —— 按钮的 `value` 必须带对参数，否则回调处理不了
3. **卡片回调的分派与权限** —— 尤其「只有被邀请人本人能回应」
"""

from __future__ import annotations

import json

import pytest

from app.bitable import flatten_text, open_ids_of, split_record
from app.match_cards import (
    ACTION_ACCEPT,
    ACTION_DECLINE,
    ACTION_INVITE,
    build_invite_card,
    build_match_card,
    build_no_match_card,
    split_reasons,
)
from app.match_flow import MatchFlow

# ---------------------------------------------------------------- 字段解析


class TestBitableParsing:
    def test_flatten_text_handles_rich_text_segments(self):
        """⚠️ 实测：文本字段经插件返回是 `[{"text": "王五", "type": "text"}]`。"""
        assert flatten_text([{"text": "王五", "type": "text"}]) == "王五"
        assert flatten_text("大二") == "大二"
        assert flatten_text(["编程", "设计"]) == "编程、设计"
        assert flatten_text(None) == ""

    def test_open_ids_prefers_id_over_display_name(self):
        """⚠️ 人员字段的 open_id 在 `id` 里。按 name 取会把「谢国辉」当账号，且不报错。"""
        user_field = [{"id": "ou_abc", "name": "谢国辉", "email": "x@nankai.edu.cn"}]
        assert open_ids_of(user_field) == ["ou_abc"]
        assert "谢国辉" not in open_ids_of(user_field)

    def test_open_ids_ignores_non_ou_values(self):
        assert open_ids_of([{"name": "谢国辉"}]) == []
        assert open_ids_of([]) == []
        assert open_ids_of("ou_ok") == ["ou_ok"]

    def test_split_record_flattens_fields_and_keeps_record_id(self):
        record = {"fields": {"姓名": [{"text": "王五", "type": "text"}]}, "record_id": "rec1"}
        flat = split_record(record)
        assert flat["record_id"] == "rec1"
        assert flatten_text(flat["姓名"]) == "王五"


# ---------------------------------------------------------------- 理由拆分


class TestSplitReasons:
    def test_splits_numbered_lines(self):
        text = "1. 他会设计，正好补缺（92 分）\n2. 编程强但方向重合（80 分）"
        assert split_reasons(text) == ["他会设计，正好补缺（92 分）", "编程强但方向重合（80 分）"]

    def test_falls_back_to_whole_text(self):
        assert split_reasons("没有编号的一句话") == ["没有编号的一句话"]
        assert split_reasons("") == []

    def test_continuation_lines_stick_to_previous(self):
        text = "1. 第一句\n接上一行\n2. 第二条"
        assert split_reasons(text) == ["第一句\n接上一行", "第二条"]


class TestBitableUrls:
    def test_url_is_not_double_prefixed(self, settings):
        """⚠️ 冒烟测试当场抓到的 bug：`FEISHU_BASE` 已含 `/open-apis`，
        再拼一次就成了 `/open-apis/open-apis/...`，飞书回 404。
        这种错**任何单测都测不到**，只有真跑一次才暴露 —— 所以锁住它。"""
        from app.bitable import BitableClient

        settings.bitable_app_token = "base1"
        client = BitableClient(settings, None, None)  # type: ignore[arg-type]
        url = client._records_url("tbl1")
        assert url.count("/open-apis") == 1
        assert url == (
            "https://open.feishu.cn/open-apis/bitable/v1/apps/base1/tables/tbl1/records"
        )


# ---------------------------------------------------------------- 卡片 A


REQUEST = {
    "record_id": "rec_REQ",
    "需求标题": "找队友参加数学建模",
    "项目类型": "竞赛",
    "预期目标": "参加校内选拔，冲击国赛",
    "需要什么技能": ["编程", "设计"],
    "所在校区": "津南",
    "期望每周投入": "10-20h",
    "匹配理由": "1. 他会设计，正好补缺（92 分）",
}


class TestMatchCard:
    def _card(self, candidates=None):
        return build_match_card(
            request=REQUEST,
            candidates=candidates if candidates is not None else [
                {"open_id": "ou_wangwu",
                 "profile": {"姓名": "王五", "年级": "大二", "学院": "软件学院",
                             "技能标签": ["编程", "设计"], "所在校区": "津南"}},
            ],
            reason_text=REQUEST["匹配理由"],
        )

    def test_lists_candidate_and_reason(self):
        card = self._card()
        text = json.dumps(card, ensure_ascii=False)
        assert "王五" in text
        assert "大二" in text and "软件学院" in text
        assert "他会设计" in text
        assert "为你找到 1 位队友" in text

    def test_invite_button_carries_business_params(self):
        card = self._card()
        buttons = [b for el in card["elements"] if el["tag"] == "action"
                   for b in el["actions"]]
        assert len(buttons) == 1
        value = buttons[0]["value"]
        assert value["action"] == ACTION_INVITE
        assert value["request_record_id"] == "rec_REQ"
        assert value["candidate_open_id"] == "ou_wangwu"
        assert value["candidate_index"] == 0
        assert "url" not in buttons[0], "邀请必须走回传，不能是跳转"

    def test_promises_not_to_disturb_before_invite(self):
        """这条措辞是产品承诺 —— 让发起人知道按钮的后果。改掉会削弱设计。"""
        assert "邀请前不会打扰对方" in json.dumps(self._card(), ensure_ascii=False)

    def test_zero_candidates_becomes_no_match_card(self):
        card = self._card(candidates=[])
        assert "暂未找到" in json.dumps(card, ensure_ascii=False)
        assert not [el for el in card["elements"] if el["tag"] == "action"]

    def test_no_match_card_is_explicit(self):
        card = build_no_match_card(request=REQUEST)
        text = json.dumps(card, ensure_ascii=False)
        assert "找队友参加数学建模" in text
        assert "本次没有推荐任何人" in text


# ---------------------------------------------------------------- 卡片 B


class TestInviteCard:
    def _card(self):
        return build_invite_card(
            invite={"record_id": "rec_INV"},
            requester_name="谢国辉",
            request=REQUEST,
            reason="你会 Figma，正是 TA 缺的设计",
        )

    def test_carries_requester_name_and_request(self):
        text = json.dumps(self._card(), ensure_ascii=False)
        assert "谢国辉" in text
        assert "找队友参加数学建模" in text
        assert "参加校内选拔" in text
        assert "你会 Figma" in text

    def test_accept_and_decline_buttons(self):
        card = self._card()
        buttons = [b for el in card["elements"] if el["tag"] == "action"
                   for b in el["actions"]]
        actions = {b["value"]["action"]: b["value"]["invite_record_id"] for b in buttons}
        assert actions == {ACTION_ACCEPT: "rec_INV", ACTION_DECLINE: "rec_INV"}


# ---------------------------------------------------------------- 编排


class FakeBitable:
    """假的表格客户端。**要区分表** —— 邀请表是独立的一份数据。"""

    def __init__(self):
        self.updated: list[tuple[str, str, dict]] = []
        self.created: list[tuple[str, dict]] = []
        self.records: dict[str, dict] = {}   # 【组队需求】/【队友画像】
        self.invites: dict[str, dict] = {}   # 【邀请】
        self._invite_seq = 0

    configured = True

    async def list_records(self, table_id, **kwargs):
        if table_id == "tbl_inv":
            return list(self.invites.values())
        return list(self.records.values())

    async def get_record(self, table_id, record_id):
        if table_id == "tbl_inv":
            return self.invites.get(record_id, {})
        return self.records.get(record_id, {})

    async def update_record(self, table_id, record_id, fields):
        self.updated.append((table_id, record_id, fields))
        store = self.invites if table_id == "tbl_inv" else self.records
        store.setdefault(record_id, {}).update(
            {k: (v[0] if isinstance(v, list) and v and isinstance(v[0], str) else v)
             for k, v in fields.items()}
        )

    async def create_records(self, table_id, rows):
        self.created.append((table_id, rows[0]))
        self._invite_seq += 1
        rid = "rec_INV_%d" % self._invite_seq
        if table_id == "tbl_inv":
            self.invites[rid] = {**rows[0], "record_id": rid}
        return [rid]


class FakeApp:
    def __init__(self):
        self.cards: list[tuple[dict, str]] = []

    async def send_card(self, card, *, target=None):
        self.cards.append((card, target or ""))
        return {"code": 0}


@pytest.fixture()
def flow(settings):
    from app.config import MatchGeniosProfile
    from app.genios_client import GeniosClient

    settings.bitable_enabled = True
    settings.bitable_app_token = "basetoken"
    settings.bitable_request_table_id = "tbl_req"
    settings.bitable_profile_table_id = "tbl_prof"
    settings.bitable_invite_table_id = "tbl_inv"
    bitable = FakeBitable()
    app = FakeApp()
    genios = GeniosClient(MatchGeniosProfile(settings), None)  # 不真调
    instance = MatchFlow(settings, None, app, bitable, genios)
    instance._bitable, instance._app = bitable, app
    return instance


class TestCardActionDispatch:
    @pytest.mark.asyncio
    async def test_unknown_action(self, flow):
        toast, card = await flow.handle_card_action({"action": "nope"}, "ou_x")
        assert toast == "未知操作" and card is None

    @pytest.mark.asyncio
    async def test_cannot_invite_yourself(self, flow):
        toast, _ = await flow.handle_card_action(
            {"action": ACTION_INVITE, "request_record_id": "rec1",
             "candidate_open_id": "ou_me"}, "ou_me")
        assert toast == "不能邀请自己"

    @pytest.mark.asyncio
    async def test_invite_writes_table_and_cards_the_candidate(self, flow):
        flow._bitable.records["rec_REQ"] = dict(REQUEST)

        toast, _ = await flow.handle_card_action(
            {"action": ACTION_INVITE, "request_record_id": "rec_REQ",
             "candidate_open_id": "ou_wangwu", "candidate_index": 0},
            "ou_requester")

        assert toast == "已通知对方"
        table_id, row = flow._bitable.created[0]
        assert table_id == "tbl_inv"
        assert row["被邀请人"] == [{"id": "ou_wangwu"}]
        assert row["发起人"] == [{"id": "ou_requester"}]
        # ⚠️ v1 的单选字段必须是**字符串**
        assert row["状态"] == "待回应"
        assert isinstance(row["状态"], str)
        # 卡片发给了**被邀请人**，不是发起人
        assert flow._app.cards[-1][1] == "ou_wangwu"

    @pytest.mark.asyncio
    async def test_only_the_invitee_can_respond(self, flow):
        """知道 invite_record_id 的人不能替别人答应。"""
        flow._bitable.invites["rec_INV"] = {
            "record_id": "rec_INV", "发起人": [{"id": "ou_requester"}],
            "被邀请人": [{"id": "ou_invitee"}], "需求标题": "找队友",
        }
        toast, _ = await flow.handle_card_action(
            {"action": ACTION_ACCEPT, "invite_record_id": "rec_INV"}, "ou_stranger")
        assert toast == "这条邀请不是发给你的"
        assert flow._bitable.updated == [], "不该写任何状态"

    @pytest.mark.asyncio
    async def test_accept_updates_status_and_notifies_requester(self, flow):
        flow._bitable.invites["rec_INV"] = {
            "record_id": "rec_INV", "发起人": [{"id": "ou_requester"}],
            "被邀请人": [{"id": "ou_invitee"}], "需求标题": "找队友参加数学建模",
        }
        toast, card = await flow.handle_card_action(
            {"action": ACTION_ACCEPT, "invite_record_id": "rec_INV"}, "ou_invitee")

        assert toast == "已告诉对方" and card is None
        assert flow._bitable.updated[-1][2] == {"状态": "已接受"}
        notified = flow._app.cards[-1]
        assert notified[1] == "ou_requester"
        assert "接受了你的组队邀请" in json.dumps(notified[0], ensure_ascii=False)

    @pytest.mark.asyncio
    async def test_decline_is_not_an_error(self, flow):
        flow._bitable.invites["rec_INV"] = {
            "record_id": "rec_INV", "发起人": [{"id": "ou_requester"}],
            "被邀请人": [{"id": "ou_invitee"}], "需求标题": "找队友",
        }
        toast, _ = await flow.handle_card_action(
            {"action": ACTION_DECLINE, "invite_record_id": "rec_INV"}, "ou_invitee")
        assert toast == "已婉拒"
        assert flow._bitable.updated[-1][2] == {"状态": "已婉拒"}
        assert "先不了" in json.dumps(flow._app.cards[-1][0], ensure_ascii=False)


class TestRequestPayload:
    def test_owner_profile_is_included(self, flow):
        """⚠️ 没有 owner_profile，大模型就只能找「像需求的人」而非「补短板的人」。"""
        row = dict(REQUEST)
        row["发起人"] = [{"id": "ou_owner"}]
        profiles = {"ou_owner": {
            "姓名": [{"text": "某某", "type": "text"}], "年级": "大二",
            "学院": [{"text": "计算机学院", "type": "text"}],
            "技能标签": ["编程"], "每周可投入": "10-20h",
        }}
        payload = flow._build_request_json(row, profiles)
        assert payload["owner_open_id"] == "ou_owner"
        assert payload["owner_profile"]["skills"] == ["编程"]
        assert payload["owner_profile"]["college"] == "计算机学院"
        assert payload["skills_needed"] == ["编程", "设计"]
        assert payload["title"] == "找队友参加数学建模"


class TestPendingSelection:
    """哪些行会被轮询器拾取。

    ⚠️ 回归一个**我自己引入的 bug**：为了让表单干净，把「状态」题目从表单里拿掉了，
    结果新提交的行状态是空的 —— 只认 `== 待匹配` 的话，新需求永远等不到匹配。
    """

    def test_empty_status_counts_as_pending(self):
        from app.match_flow import is_pending

        assert is_pending({"状态": ""}) is True
        assert is_pending({}) is True
        assert is_pending({"状态": "待匹配"}) is True

    def test_other_statuses_are_not_pending(self):
        from app.match_flow import is_pending

        for status in ("匹配中", "已匹配", "已结束", "已通知"):
            assert is_pending({"状态": status}) is False


class TestGeniosTerminalStates:
    """轮询的终态判定。

    ⚠️ 两个真实 bug（2026-10-14）：
    1. 插件的 OAuth 授权过期时工作流停在 `interrupted`，而它**不在终态列表里**
       → 轮询一直空转到超时；
    2. 超时后 `dispatch` 仍返回 `ok=True` → **把失败当成功**。
    """

    def test_interrupted_is_terminal(self):
        from app.genios_client import _looks_finished

        assert _looks_finished({"status": "interrupted"}) is True
        assert _looks_finished({"status": "processing"}) is False
        assert _looks_finished({"status": "success"}) is True

    def test_problem_reports_platform_message(self):
        from app.genios_client import _problem_of

        data = {"status": "interrupted",
                "msg": "使用工具 search_records 需要授权, 请点击[这里](https://…)进行授权"}
        problem = _problem_of(data)
        assert problem is not None
        assert "需要授权" in problem, "平台给的 msg 必须原样带出来，否则排障只能靠猜"

    def test_success_is_not_a_problem(self):
        from app.genios_client import _problem_of

        assert _problem_of({"status": "success", "output": "{}"}) is None
        assert _problem_of({"status": "processing"}) is None


class TestReauthAlert:
    """插件授权过期时，要**把重新授权链接推给人**。

    不做的话这种失败是静默的 —— 工作流只是没结果，没人点链接匹配就一直停着。
    """

    ERROR = (
        "工作流未成功（status=interrupted）：使用工具 search_records 需要授权, "
        "请点击[这里](https://accounts.feishu.cn/open-apis/authen/v1/authorize"
        "?client_id=cli_xxx&scope=bitable%3Aapp&state=abc123)进行授权"
    )

    @pytest.mark.asyncio
    async def test_pushes_card_with_the_link(self, flow):
        flow.settings.feishu_notify_target = "ou_me"
        await flow._alert_if_reauth_needed(self.ERROR)
        assert flow._app.cards, "应该推了一张卡"
        card, target = flow._app.cards[-1]
        assert target == "ou_me"
        text = json.dumps(card, ensure_ascii=False)
        assert "需要重新授权" in text
        assert "state=abc123" in text, "链接必须原样带出去，否则点不了"

    @pytest.mark.asyncio
    async def test_cooldown_suppresses_repeats(self, flow):
        """⚠️ 每轮都推的话 90 秒一条，会把人烦死。"""
        flow.settings.feishu_notify_target = "ou_me"
        flow.settings.match_reauth_alert_cooldown_seconds = 1800
        await flow._alert_if_reauth_needed(self.ERROR)
        await flow._alert_if_reauth_needed(self.ERROR)
        assert len(flow._app.cards) == 1, "冷却期内只应推一次"

    @pytest.mark.asyncio
    async def test_other_errors_are_not_pushed(self, flow):
        flow.settings.feishu_notify_target = "ou_me"
        await flow._alert_if_reauth_needed("工作流未成功（status=failed）：超时")
        assert flow._app.cards == [], "普通失败不该触发重新授权告警"


class TestParseCardAction:
    """回调载荷的解析。

    ⚠️ 实测踩过的坑：`lark.JSON.marshal()` 返回的是 **JSON 字符串**，
    直接 `.get("event")` 会 `'str' object has no attribute 'get'`，
    **按钮点下去毫无反应**，看起来像"没收到回调"。
    """

    REAL = {
        "schema": "2.0",
        "header": {"event_type": "card.action.trigger"},
        "event": {
            "operator": {"open_id": "ou_clicker", "union_id": "on_x"},
            "action": {"value": {"action": "invite", "candidate_index": 0,
                                 "candidate_open_id": "ou_cand",
                                 "request_record_id": "rec_REQ"}, "tag": "button"},
            "context": {"open_message_id": "om_x"},
        },
    }

    def test_extracts_value_and_operator(self):
        from app.match_flow import parse_card_action

        value, operator = parse_card_action(self.REAL)
        assert operator == "ou_clicker"
        assert value["action"] == "invite"
        assert value["candidate_open_id"] == "ou_cand"

    def test_survives_wrong_shapes(self):
        from app.match_flow import parse_card_action

        # 上一版就是在这里崩的：marshal 出来是字符串
        assert parse_card_action("{\"event\": {}}") == ({}, "")
        assert parse_card_action(None) == ({}, "")
        assert parse_card_action({}) == ({}, "")
        assert parse_card_action({"event": "不是字典"}) == ({}, "")
        assert parse_card_action({"event": {"action": "不是字典"}}) == ({}, "")
        assert parse_card_action({"event": {"action": {"value": "不是字典"}}}) == ({}, "")


class TestInviteReasonAndIdempotency:
    """两个都来自同一次真实体验（2026-10-15）。

    1. 被邀请人看到的理由**和发起人看到的一模一样**（而且是以发起人为第二人称写的）
       —— 对方读到「你缺的正是设计」会一头雾水。
    2. 连点两下「邀请」，【邀请】表出现**两行重复**、对方收到**两张卡**。
    """

    REQ_ROW = {
        **REQUEST,
        "匹配理由": "1. 你缺的正是设计，而 TA 做过海报（这是给发起人看的）",
        "邀请理由": "1. 谢国辉在找人做可视化，而你会 Figma（这是给候选人看的）",
    }

    @pytest.mark.asyncio
    async def test_invitee_gets_the_invite_reason(self, flow):
        flow._bitable.records["rec_REQ"] = dict(self.REQ_ROW)
        await flow.handle_card_action(
            {"action": ACTION_INVITE, "request_record_id": "rec_REQ",
             "candidate_open_id": "ou_wangwu", "candidate_index": 0},
            "ou_requester")
        _, row = flow._bitable.created[0]
        assert "给候选人看的" in row["邀请理由"]
        assert "给发起人看的" not in row["邀请理由"]
        # 卡片 B 上用的也是这一份
        card, target = flow._app.cards[-1]
        assert target == "ou_wangwu"
        assert "给候选人看的" in json.dumps(card, ensure_ascii=False)

    @pytest.mark.asyncio
    async def test_falls_back_to_match_reason_for_legacy_rows(self, flow):
        """老数据没有「邀请理由」字段时，退回用「匹配理由」，不要空着。"""
        legacy = dict(REQUEST)
        legacy.pop("邀请理由", None)
        flow._bitable.records["rec_REQ"] = legacy
        await flow.handle_card_action(
            {"action": ACTION_INVITE, "request_record_id": "rec_REQ",
             "candidate_open_id": "ou_wangwu", "candidate_index": 0},
            "ou_requester")
        _, row = flow._bitable.created[0]
        assert "他会设计" in row["邀请理由"]

    @pytest.mark.asyncio
    async def test_invite_row_records_its_source(self, flow):
        """同一张【邀请】表装两种方向 —— 方向必须落在数据里，不能只存在卡片 value 里。"""
        flow._bitable.records["rec_REQ"] = dict(self.REQ_ROW)
        await flow.handle_card_action(
            {"action": ACTION_INVITE, "request_record_id": "rec_REQ",
             "candidate_open_id": "ou_wangwu", "candidate_index": 0},
            "ou_requester")
        _, row = flow._bitable.created[0]
        assert row["来源"] == "匹配邀请"

    @pytest.mark.asyncio
    async def test_inviting_someone_who_already_applied(self, flow):
        """对方已在小程序里申请过 → 不要去建第二条，也别回"已经邀请过 TA 了"
        （那是"我邀请的"，会让发起人误解）。"""
        flow._bitable.records["rec_REQ"] = dict(self.REQ_ROW)
        flow._bitable.invites["rec_APPLIED"] = {
            "record_id": "rec_APPLIED",
            "发起人": [{"id": "ou_requester"}],
            "被邀请人": [{"id": "ou_wangwu"}],
            "需求标题": self.REQ_ROW["需求标题"],
            "来源": "小程序申请",
        }
        toast, _ = await flow.handle_card_action(
            {"action": ACTION_INVITE, "request_record_id": "rec_REQ",
             "candidate_open_id": "ou_wangwu", "candidate_index": 0},
            "ou_requester")
        assert toast == "TA 已经申请加入了，去【邀请】表处理就行"
        assert flow._bitable.created == []

    @pytest.mark.asyncio
    async def test_second_click_does_not_duplicate(self, flow):
        flow._bitable.records["rec_REQ"] = dict(self.REQ_ROW)
        action = {"action": ACTION_INVITE, "request_record_id": "rec_REQ",
                  "candidate_open_id": "ou_wangwu", "candidate_index": 0}

        toast1, _ = await flow.handle_card_action(dict(action), "ou_requester")
        cards_after_first = len(flow._app.cards)
        toast2, _ = await flow.handle_card_action(dict(action), "ou_requester")

        assert toast1 == "已通知对方"
        assert toast2 == "已经邀请过 TA 了"
        assert len(flow._bitable.created) == 1, "不能建第二行"
        assert len(flow._app.cards) == cards_after_first, "不能再发一次卡片"

    @pytest.mark.asyncio
    async def test_inviting_a_different_candidate_still_works(self, flow):
        """幂等只针对「同一个人对同一条需求」，换个人照样能邀。"""
        flow._bitable.records["rec_REQ"] = dict(self.REQ_ROW)
        await flow.handle_card_action(
            {"action": ACTION_INVITE, "request_record_id": "rec_REQ",
             "candidate_open_id": "ou_a", "candidate_index": 0}, "ou_requester")
        toast, _ = await flow.handle_card_action(
            {"action": ACTION_INVITE, "request_record_id": "rec_REQ",
             "candidate_open_id": "ou_b", "candidate_index": 0}, "ou_requester")
        assert toast == "已通知对方"
        assert len(flow._bitable.created) == 2

    def test_creator_wins_over_picked_owner(self, flow):
        """表单没有只读题目 —— 用户能把「发起人」选成别人。

        `创建人` 是飞书自动填的提交人，改不了，所以**只要它确实有画像，就以它为准**。
        """
        row = dict(REQUEST)
        row["发起人"] = [{"id": "ou_someone_else"}]   # 用户手滑选了别人
        row["创建人"] = {"id": "ou_real_submitter", "name": "本人"}
        profiles = {
            "ou_someone_else": {"姓名": [{"text": "别人", "type": "text"}]},
            "ou_real_submitter": {"姓名": [{"text": "本人", "type": "text"}]},
        }
        payload = flow._build_request_json(row, profiles)
        assert payload["owner_open_id"] == "ou_real_submitter"

    def test_falls_back_to_picked_owner_without_creator_profile(self, flow):
        """API 建的行 `创建人` 是应用所有者 —— 查不到画像就退回用户选的那个。"""
        row = dict(REQUEST)
        row["发起人"] = [{"id": "ou_owner"}]
        row["创建人"] = {"id": "ou_app_owner", "name": "应用所有者"}
        profiles = {"ou_owner": {"姓名": [{"text": "某某", "type": "text"}]}}
        payload = flow._build_request_json(row, profiles)
        assert payload["owner_open_id"] == "ou_owner"


class TestApplyDirection:
    """小程序申请：卡片发给**发起人**，角色和「邀请」是反的。

    用 `source: "apply"` 区分方向 —— 少了它，发起人点「同意」会被
    "这条邀请不是发给你的" 挡下来，表现为**点了没反应**。
    """

    @pytest.mark.asyncio
    async def test_requester_can_accept_application(self, flow):
        flow._bitable.invites["rec_APP"] = {
            "record_id": "rec_APP",
            "发起人": [{"id": "ou_requester"}],
            "被邀请人": [{"id": "ou_applicant"}],
            "需求标题": "CANN 大赛组队",
        }
        toast, _ = await flow.handle_card_action(
            {"action": ACTION_ACCEPT, "invite_record_id": "rec_APP", "source": "apply"},
            "ou_requester",
        )
        assert toast == "已告诉对方"
        assert flow._bitable.updated[-1][2] == {"状态": "已接受"}
        # 通知的是**申请人**，不是发起人
        assert flow._app.cards[-1][1] == "ou_applicant"
        assert "同意了你的加入申请" in json.dumps(flow._app.cards[-1][0], ensure_ascii=False)

    @pytest.mark.asyncio
    async def test_applicant_cannot_answer_own_application(self, flow):
        """申请人是**被申请的那个人**，不能替发起人答应自己。"""
        flow._bitable.invites["rec_APP2"] = {
            "record_id": "rec_APP2",
            "发起人": [{"id": "ou_requester"}],
            "被邀请人": [{"id": "ou_applicant"}],
            "需求标题": "CANN 大赛组队",
        }
        toast, _ = await flow.handle_card_action(
            {"action": ACTION_ACCEPT, "invite_record_id": "rec_APP2", "source": "apply"},
            "ou_applicant",
        )
        assert toast == "这条申请不是发给你的"
        assert flow._bitable.updated == [] or flow._bitable.updated[-1][0] != "tbl_inv"

    @pytest.mark.asyncio
    async def test_table_source_beats_card_value(self, flow):
        """表里的 `来源` 是权威 —— 卡片上的 value 可能过期或被伪造。"""
        flow._bitable.invites["rec_APP3"] = {
            "record_id": "rec_APP3",
            "发起人": [{"id": "ou_requester"}],
            "被邀请人": [{"id": "ou_applicant"}],
            "需求标题": "CANN 大赛组队",
            "来源": "小程序申请",
        }
        # 卡片**没带** source，但表里写了「小程序申请」→ 仍按申请方向处理
        toast, _ = await flow.handle_card_action(
            {"action": ACTION_ACCEPT, "invite_record_id": "rec_APP3"}, "ou_requester"
        )
        assert toast == "已告诉对方"
        assert flow._app.cards[-1][1] == "ou_applicant"

    @pytest.mark.asyncio
    async def test_match_invite_source_keeps_original_direction(self, flow):
        """表里写「匹配邀请」→ 仍由**被邀请人**回应，发起人不能代按。"""
        flow._bitable.invites["rec_INV3"] = {
            "record_id": "rec_INV3",
            "发起人": [{"id": "ou_requester"}],
            "被邀请人": [{"id": "ou_invitee"}],
            "需求标题": "找队友",
            "来源": "匹配邀请",
        }
        toast, _ = await flow.handle_card_action(
            {"action": ACTION_ACCEPT, "invite_record_id": "rec_INV3"}, "ou_requester"
        )
        assert toast == "这条邀请不是发给你的"


class TestResponseIdempotency:
    """同意/婉拒只能**生效一次** —— 连点两下不该收到两条"有人答应了"。"""

    def _invite(self, flow, record_id="rec_IDEM"):
        flow._bitable.invites[record_id] = {
            "record_id": record_id,
            "发起人": [{"id": "ou_requester"}],
            "被邀请人": [{"id": "ou_invitee"}],
            "需求标题": "找队友",
            "来源": "匹配邀请",
        }

    @pytest.mark.asyncio
    async def test_accept_twice_notifies_once(self, flow):
        self._invite(flow)
        first, _ = await flow.handle_card_action(
            {"action": ACTION_ACCEPT, "invite_record_id": "rec_IDEM"}, "ou_invitee")
        sent = len(flow._app.cards)

        second, _ = await flow.handle_card_action(
            {"action": ACTION_ACCEPT, "invite_record_id": "rec_IDEM"}, "ou_invitee")

        assert first == "已告诉对方"
        assert second == "这条已经处理过了"
        assert len(flow._app.cards) == sent, "重复点击不该再发一张通知卡"

    @pytest.mark.asyncio
    async def test_decline_then_accept_does_not_flip(self, flow):
        self._invite(flow, "rec_IDEM2")
        await flow.handle_card_action(
            {"action": ACTION_DECLINE, "invite_record_id": "rec_IDEM2"}, "ou_invitee")
        sent = len(flow._app.cards)

        toast, _ = await flow.handle_card_action(
            {"action": ACTION_ACCEPT, "invite_record_id": "rec_IDEM2"}, "ou_invitee")

        assert toast == "这条已经处理过了"
        assert flow._bitable.invites["rec_IDEM2"]["状态"] == "已婉拒"
        assert len(flow._app.cards) == sent
