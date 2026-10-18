"""表单预填 —— 飞书表单的 `?prefill_题目=值`。"""

from __future__ import annotations

from app.forms import personalize_links, prefill_form

PROFILE = "https://nankai.feishu.cn/share/base/shrcnrNj3Dh5T7ce4OxZUO3huBf"
REQUEST = "https://nankai.feishu.cn/share/base/shrcnH1oQRYtBvm1y7WYAj38gne"


class TestPrefillForm:
    def test_appends_question(self):
        url = prefill_form(PROFILE, {"姓名": "谢国辉"})
        assert url.startswith(PROFILE + "?prefill_")
        assert "%E8%B0%A2%E5%9B%BD%E8%BE%89" in url

    def test_keeps_existing_query(self):
        url = prefill_form(PROFILE + "?from=chat", {"姓名": "李雷"})
        assert url.startswith(PROFILE + "?from=chat&prefill_")

    def test_multiple_answers(self):
        url = prefill_form(PROFILE, {"姓名": "李雷", "所在校区": "津南"})
        assert "prefill_%E5%A7%93%E5%90%8D=" in url
        assert "prefill_%E6%89%80%E5%9C%A8%E6%A0%A1%E5%8C%BA=" in url

    def test_blank_value_skipped(self):
        assert prefill_form(PROFILE, {"姓名": ""}) == PROFILE

    def test_idempotent(self):
        once = prefill_form(PROFILE, {"姓名": "李雷"})
        assert prefill_form(once, {"姓名": "韩梅梅"}) == once

    def test_empty_url(self):
        assert prefill_form("", {"姓名": "李雷"}) == ""

    def test_hide_added_for_prefilled_question(self):
        url = prefill_form(PROFILE, {"姓名": "李雷"}, hidden=("姓名",))
        assert "prefill_%E5%A7%93%E5%90%8D=" in url
        assert "hide_%E5%A7%93%E5%90%8D=1" in url

    def test_hide_skipped_without_value(self):
        """藏一个空题 = 用户永远填不了。只有在确实预填了值时才隐藏。"""
        url = prefill_form(PROFILE, {"姓名": ""}, hidden=("姓名",))
        assert "hide_" not in url
        assert url == PROFILE


class TestPersonalizeLinks:
    def test_profile_link_gets_name_and_account(self):
        text = f"先填个画像：{PROFILE}"
        out = personalize_links(text, name="谢国辉", profile_form_url=PROFILE)
        assert "prefill_%E5%A7%93%E5%90%8D=" in out                    # 姓名
        assert "prefill_%E9%A3%9E%E4%B9%A6%E8%B4%A6%E5%8F%B7=" in out  # 飞书账号
        # 题目**保持可见** —— 用户要能看到"这是我自己"
        assert "hide_" not in out

    def test_request_link_prefills_owner(self):
        text = f"点这个找队友：{REQUEST}"
        out = personalize_links(text, name="谢国辉", request_form_url=REQUEST)
        # 人员字段的题目名是「发起人」，不是「姓名」
        assert "prefill_%E5%8F%91%E8%B5%B7%E4%BA%BA=" in out
        assert "hide_" not in out

    def test_both_links_in_one_reply(self):
        text = f"画像 {PROFILE} 需求 {REQUEST}"
        out = personalize_links(
            text, name="李雷", profile_form_url=PROFILE, request_form_url=REQUEST
        )
        assert "prefill_%E5%A7%93%E5%90%8D=" in out
        assert "prefill_%E5%8F%91%E8%B5%B7%E4%BA%BA=" in out

    def test_hidden_questions_are_url_encoded(self):
        """中文题目名不编码会截断查询串 —— 这条挡的是"半截链接"。"""
        out = personalize_links(f"填 {PROFILE}", name="李雷", profile_form_url=PROFILE)
        assert "?" in out
        query = out.split("?", 1)[1]
        assert "姓名" not in query and "飞书账号" not in query

    def test_no_name_leaves_text_alone(self):
        text = f"点这个：{REQUEST}"
        assert personalize_links(text, name="", request_form_url=REQUEST) == text
        assert personalize_links(text, name=None, request_form_url=REQUEST) == text

    def test_unrelated_links_untouched(self):
        text = "看这个 https://jwc.nankai.edu.cn/agent-contest"
        assert personalize_links(text, name="李雷", request_form_url=REQUEST) == text
