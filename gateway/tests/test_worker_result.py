"""worker 取回 GeniOS 结果后的两个纯函数。

对应 2026-10-07 的改动：既然不再让 GeniOS 用 HTTP 节点回写，**worker 拿到结果就直接入库**，
那么「剥信封」和「字段名对齐」这两步就从代码节点搬到了 gateway 里，必须锁住。
"""

from __future__ import annotations

from app.worker import extract_llm_payload, to_opportunity_data


class TestExtractLlmPayload:
    def test_unwraps_double_envelope(self):
        """实测的真实形状：查询响应 → output(字符串) → output(字符串) → 抽取结果。"""
        raw = {
            "status": "success",
            "output": '{"output": "{\\"is_opportunity\\": true, \\"items\\": []}"}',
        }
        assert extract_llm_payload(raw) == {"is_opportunity": True, "items": []}

    def test_finds_payload_nested_deeply(self):
        raw = {"data": {"result": {"payload": '{"items": [{"name": "x"}]}'}}}
        assert extract_llm_payload(raw) == {"items": [{"name": "x"}]}

    def test_returns_none_when_absent(self):
        assert extract_llm_payload({"status": "success", "output": None}) is None
        assert extract_llm_payload({"status": "success", "output": "null"}) is None

    def test_unfinished_response_yields_none(self):
        """还在跑时 output 是 null —— 不能把它当成结果（这是踩过的坑）。"""
        assert extract_llm_payload({"runId": "x", "status": "processing", "output": None}) is None


class TestToOpportunityData:
    def test_renames_fields_to_gateway_names(self):
        item = {
            "name": "某竞赛", "type": "竞赛",
            "event_time_text": "11月2日 9:00-14:00",
            "signup_method_text": "填问卷",
            "type_specific": {"level": "校级"},
        }
        data = to_opportunity_data(item, source="某公众号", url="https://mp/x", article_id="abc")
        assert data["event_time_raw"] == "11月2日 9:00-14:00"
        assert data["signup_method"] == "填问卷"
        assert data["extra"] == {"type_specific": {"level": "校级"}}
        assert data["source_account"] == "某公众号"
        assert data["source_url"] == "https://mp/x"
        assert data["article_id"] == "abc"
        # 旧名字不该残留，否则 store 认不出来
        assert "event_time_text" not in data
        assert "signup_method_text" not in data

    def test_drops_empty_values(self):
        """空字符串/空列表不该覆盖库里已有的值（配合 _merge_missing 的「只补空缺」语义）。"""
        data = to_opportunity_data(
            {"name": "x", "type": "竞赛", "location": "", "tags": [], "quota": None},
            source=None, url=None, article_id=None,
        )
        assert "location" not in data
        assert "tags" not in data
        assert "quota" not in data

    def test_keeps_datetime_fields_as_is(self):
        """时间字段原样透传，由 store 的 _coerce_dt 去解析（它认得 ISO 与 naive 两种）。"""
        data = to_opportunity_data(
            {"name": "x", "type": "竞赛", "event_start": "2026-11-02T09:00:00+08:00",
             "signup_deadline": "2026-10-25T00:00:00+08:00"},
            source=None, url=None, article_id=None,
        )
        assert data["event_start"] == "2026-11-02T09:00:00+08:00"
        assert data["signup_deadline"] == "2026-10-25T00:00:00+08:00"
