"""对话路由（gateway 侧）。

载荷形状取自 **S6 探针的真实落盘**（`data/captures/feishu_events.jsonl`），
不是照着文档编的 —— 见 `gateway/app/chat_flow.py` 的模块说明。
"""

from __future__ import annotations

import json

import pytest

from app.chat_flow import (
    PLACEHOLDER_REPLY,
    ChatFlow,
    message_text,
    parse_message_event,
    strip_mention,
)

# 真实抓到的形状（event 里的 content 是 **JSON 字符串**）
REAL_P2P = {
    "schema": "2.0",
    "header": {"event_type": "im.message.receive_v1"},
    "event": {
        "sender": {"sender_id": {"open_id": "ou_sender", "union_id": "on_x"}},
        "message": {
            "chat_id": "oc_p2p", "chat_type": "p2p", "message_type": "text",
            "message_id": "om_x", "content": "{\"text\":\"有哪些适合我的比赛\"}",
        },
    },
}


class TestMessageText:
    def test_parses_json_string_content(self):
        """⚠️ `content` 是**字符串**不是对象，要再解析一次。"""
        assert message_text('{"text":"hi"}') == "hi"
        assert message_text('{"text":"有哪些比赛"}') == "有哪些比赛"

    def test_tolerates_dict_and_garbage(self):
        assert message_text({"text": "hi"}) == "hi"
        assert message_text("不是 JSON 也不是对象") == "不是 JSON 也不是对象"
        assert message_text("{坏掉的 json") == ""
        assert message_text(None) == ""
        assert message_text(12345) == ""

    def test_mention_placeholder_is_stripped(self):
        """群里 @ 会留下 `@_user_1` 这种占位符，送进模型会干扰理解。"""
        assert strip_mention("@_user_1 有哪些比赛") == "有哪些比赛"
        assert strip_mention("@_user_1@_user_2 你好") == "你好"


class TestParseMessageEvent:
    def test_real_shape(self):
        got = parse_message_event(REAL_P2P)
        assert got["chat_id"] == "oc_p2p"
        assert got["chat_type"] == "p2p"
        assert got["open_id"] == "ou_sender"
        assert got["text"] == "有哪些适合我的比赛"

    def test_survives_wrong_shapes(self):
        """形状变了不该把链路打断（卡片回调那边吃过这个亏）。"""
        assert parse_message_event(None) == {}
        assert parse_message_event("字符串") == {}
        assert parse_message_event({})["text"] == ""
        assert parse_message_event({"event": "不是字典"})["chat_id"] == ""


class FakeApp:
    def __init__(self):
        self.sent: list[tuple[str, str]] = []

    async def send_text(self, text, *, target=None):
        self.sent.append((text, target or ""))
        return {"code": 0}


@pytest.fixture()
def chat(settings):
    return ChatFlow(settings, None, FakeApp())


class TestChatFlow:
    @pytest.mark.asyncio
    async def test_replies_in_p2p(self, chat):
        await chat.handle_message(REAL_P2P)
        assert len(chat.app.sent) == 1
        text, target = chat.app.sent[0]
        assert target == "oc_p2p", "回复要发回**这个会话**，不是发给固定的人"
        assert text == PLACEHOLDER_REPLY

    @pytest.mark.asyncio
    async def test_ignores_group_chats(self, chat):
        """⚠️ 群里逐条回话会把人烦死 —— 先只做单聊。"""
        payload = json.loads(json.dumps(REAL_P2P))
        payload["event"]["message"]["chat_type"] = "group"
        await chat.handle_message(payload)
        assert chat.app.sent == []

    @pytest.mark.asyncio
    async def test_non_text_message_gets_a_hint(self, chat):
        payload = json.loads(json.dumps(REAL_P2P))
        payload["event"]["message"]["content"] = '{"file_key":"x"}'
        payload["event"]["message"]["message_type"] = "file"
        await chat.handle_message(payload)
        assert chat.app.sent and "文字消息" in chat.app.sent[0][0]

    @pytest.mark.asyncio
    async def test_missing_chat_id_does_not_crash(self, chat):
        broken = {"event": {"message": {"content": '{"text":"hi"}'}}}
        await chat.handle_message(broken)
        assert chat.app.sent == []

    @pytest.mark.asyncio
    async def test_respond_failure_still_replies(self, chat, monkeypatch):
        """生成回复崩了也要给一句话 —— 否则学生看到的是"发了没反应"。"""

        async def boom(open_id, text):
            raise RuntimeError("模拟 GeniOS 挂了")

        monkeypatch.setattr(chat, "_respond", boom)
        await chat.handle_message(REAL_P2P)
        assert chat.app.sent and "稍后再发" in chat.app.sent[0][0]


class TestNeedProfileNote:
    """方案 B：没画像的人去发组队需求时，先补一条画像链接。"""

    def test_detects_request_form_link(self, chat):
        assert chat._mentions_request_form(f"点这个 {chat.settings.feishu_request_form_url}")
        assert not chat._mentions_request_form("看这个 https://jwc.nankai.edu.cn/contest")

    def test_note_points_at_profile_form(self, chat):
        note = chat._need_profile_note("谢国辉")
        assert chat.settings.feishu_profile_form_url in note
        # 名字已知才敢说"已经帮你填好了"
        assert "帮你填好了" in note

    def test_note_without_name_does_not_overpromise(self, chat):
        """拿不到名字时不能骗人说已填好 —— 用户打开会看到一个空题。"""
        note = chat._need_profile_note("")
        assert chat.settings.feishu_profile_form_url in note
        assert "帮你填好了" not in note


class TestCardMarkers:
    """模型推荐机会时吐的 `[[rec…]]` —— 文字照发，卡片按 id 补。"""

    def test_extracts_and_strips(self):
        from app.chat_flow import extract_card_markers

        ids, text = extract_card_markers(
            "给你挑了这两个：\n\n[[reczz28NvViIdJTk]]\n[[rec1234567890abc]]\n\n想报哪个？"
        )
        assert ids == ["reczz28NvViIdJTk", "rec1234567890abc"]
        assert "[[" not in text and "]]" not in text
        assert "想报哪个" in text

    def test_duplicates_are_removed(self):
        from app.chat_flow import extract_card_markers

        ids, _ = extract_card_markers("[[recAAAAAAAAAA]] [[recAAAAAAAAAA]]")
        assert ids == ["recAAAAAAAAAA"]

    def test_capped(self):
        from app.chat_flow import MAX_CARDS_PER_REPLY, extract_card_markers

        raw = " ".join(f"[[rec{i:010d}]]" for i in range(10))
        ids, _ = extract_card_markers(raw)
        assert len(ids) == MAX_CARDS_PER_REPLY

    def test_text_without_markers_is_untouched(self):
        from app.chat_flow import extract_card_markers

        ids, text = extract_card_markers("暂时没有合适的，可以下周再看看。")
        assert ids == []
        assert text == "暂时没有合适的，可以下周再看看。"
