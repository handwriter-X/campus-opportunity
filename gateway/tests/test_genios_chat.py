"""GeniOS 对话型智能体的客户端。

**所有形状都取自实测**（`docs/findings.md` Q11）—— 这个 API 没有文档，
是靠"打端点、读报错"一层层问出来的：

```
POST /api/proxy/api/v1/create_conversation   {"userID"}
POST /api/proxy/api/v1/chat_query            {"userID","AppConversationID","Query"} → SSE
```
"""

from __future__ import annotations

import json

from app.genios_chat import parse_sse, reply_of, unwrap_text

# 真实返回（原文，未加工）
REAL_SSE = (
    'event:text\n'
    'data:data: {"event": "message_start", "task_id": "t1", "conversation_id": "c1"}\n'
    '\n'
    'event:text\n'
    'data:data: {"event": "flow_start", "run_id": "t1"}\n'
    '\n'
    'event:text\n'
    'data:data: {"event": "message", "answer": "{\\"output\\": '
    '\\"{\\\\\\"reply\\\\\\": \\\\\\"同学好呀，我是校园机会助手\\\\\\"}\\"}", '
    '"conversation_id": "c1"}\n'
    '\n'
    'event:text\n'
    'data:data: {"event": "message_cost", "input_tokens": 348, "output_tokens": 108}\n'
    '\n'
    'event:text\n'
    'data:data: {"event": "message_end"}\n'
    '\n'
)


class TestParseSse:
    def test_double_data_prefix(self):
        """⚠️ 这个平台的 SSE 是 `data:data: {…}` —— `data:` 里还套一层。

        标准解析器会把值当成 `data: {…}` 的字符串，json 直接失败。
        """
        events = parse_sse(REAL_SSE)
        assert [e.get("event") for e in events] == [
            "message_start", "flow_start", "message", "message_cost", "message_end"
        ]

    def test_bad_frames_are_skipped(self):
        assert parse_sse("event:text\ndata:data: 不是json\n\n") == []
        assert parse_sse("") == []
        assert parse_sse(None) == []


class TestUnwrapText:
    def test_double_encoded_answer(self):
        """实测：`answer` 是字符串，里面还套着 `{"output": "{\\"reply\\": \\"…\\"}"}`。"""
        payload = '{"output": "{\\"reply\\": \\"同学好呀\\"}"}'
        assert unwrap_text(payload) == "同学好呀"

    def test_quoted_json_string(self):
        """⚠️ 某层是**带引号的 JSON 字符串**时，别把引号一起返回（实测踩过）。"""
        assert unwrap_text('"南开大学校园机会助手"') == "南开大学校园机会助手"

    def test_plain_text_passes_through(self):
        assert unwrap_text("就是一句普通的话") == "就是一句普通的话"

    def test_dict_priority_prefers_reply(self):
        assert unwrap_text({"output": "中转", "reply": "正文"}) == "正文"

    def test_garbage_is_empty(self):
        assert unwrap_text(None) == ""
        assert unwrap_text({}) == ""
        assert unwrap_text(12345) == ""


class TestReplyOf:
    def test_picks_the_message_event(self):
        assert reply_of(parse_sse(REAL_SSE)) == "同学好呀，我是校园机会助手"

    def test_empty_when_no_answer(self):
        events = [{"event": "message_start"}, {"event": "message_end"}]
        assert reply_of(events) == ""


class TestRealShapesFromTheField:
    """⚠️ 两个形状都是 **2026-10-16 从真实运行日志里抄出来的**。

    当时的现象是"`message` 帧在，但正文剥不出来"，
    原因是 `unwrap_text` 的字段优先级列表**漏了 `response`**。
    """

    def test_response_field(self):
        """画布输出的字段叫 `response`（不是 `reply`）。"""
        answer = '{"output": "{\\"response\\": \\"嗨，我是南开校园机会助手\\"}"}'
        assert unwrap_text(answer) == "嗨，我是南开校园机会助手"

    def test_still_handles_reply(self):
        """`reply` 那条路也得留着 —— 画布换个字段名不该把这边弄坏。"""
        assert unwrap_text('{"output": "{\\"reply\\": \\"正文\\"}"}') == "正文"

    def test_structured_non_reply_now_returns_longest(self):
        """画布如果输出的是**自述结构**（没有回复字段），现在的行为是
        「取最长的那段文本」，而不是返回空。

        ⚠️ 这是**有意改的**：宁可给出一句不完美的文本，也别让用户收到
        「刚才没处理过来」——后者看起来像系统坏了。
        代价是可能把结构化字段（比如 `校园机会助手`）当正文发出去 ——
        这是降级，不是理想态。**所以画布的 End 还是要固定输出一个正文字段。**"""
        answer = ('{"output": "{\\"name\\": \\"校园机会助手\\", \\"type\\": \\"agent\\", '
                  '\\"capabilities\\": [\\"机会推荐\\"]}"}')
        got = unwrap_text(answer)
        assert got, "现在不再返回空 —— 会兜底取最长的那段"
        assert "校园机会助手" in got


class TestArbitraryOutputFields:
    """⚠️ **不同分支的字段名不一样** —— 2026-10-17 从真实日志里抄的。

    查机会分支输出 `response`；找队友分支输出 `output_match`，
    **而同一层还有一个空的 `output`**。只按固定字段名挑，会挑中那个空的。
    """

    def test_output_match_field(self):
        answer = ('{"other": "", "output": "", "output_match": '
                  '"{\\"reply\\": \\"给智能体应用创新大赛找队友的话，填一下这个表单就行\\"}"}')
        assert "填一下这个表单" in unwrap_text(answer)

    def test_empty_output_does_not_win(self):
        """空的 `output` 不能被当成正文。"""
        answer = '{"output": "", "response": "真正的回复"}'
        assert unwrap_text(answer) == "真正的回复"

    def test_unknown_field_falls_back_to_longest(self):
        """完全不认识的字段名，取最长的那段 —— 总比返回空强。"""
        answer = '{"a": "", "b": "短", "c": "这是一段明显更长的正文内容"}'
        assert unwrap_text(answer) == "这是一段明显更长的正文内容"
