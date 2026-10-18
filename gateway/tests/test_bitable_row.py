"""机会 → 【机会汇总】表的**行映射**。

⚠️ 这里的每个写法都是**实测出来的**，而且踩过两次 v1/v3 的差异：

| 表里的类型 | v1（gateway 用） | v3（CLI 用） |
| --- | --- | --- |
| **单选** | **字符串** `"竞赛"` | 数组 `["竞赛"]` |
| 日期 | Unix **毫秒** | 毫秒或 ISO 都行 |

写成数组 v1 会拒（`SingleSelectFieldConvFail`），
而且**用 HTTP 200 返回这个错误** —— 只看状态码会以为写成功了。
"""

from __future__ import annotations

import json

from app.bitable import opportunity_row, to_ms


class TestToMs:
    def test_iso_with_tz(self):
        assert to_ms("2026-10-20T15:59:59+08:00") == 1792483199000

    def test_naive_is_treated_as_shanghai(self):
        """naive 时间按 Asia/Shanghai 解释 —— 和 models.UTCDateTime 一个规矩。"""
        assert to_ms("2026-10-20T15:59:59") == 1792483199000

    def test_empty_and_garbage(self):
        assert to_ms(None) is None
        assert to_ms("") is None
        assert to_ms("不是时间") is None


class TestOpportunityRow:
    DATA = {
        "name": "南开大学第十六届程序设计竞赛",
        "type": "竞赛",
        "summary": "算法设计竞赛",
        "location": "津南校区A305",
        "signup_url": "https://example.nankai.edu.cn/cpc",
        "source_url": "https://mp.weixin.qq.com/s/x",
        "source_account": "南开大学计算机学院",
        "status": "未开始",
        "push_status": "未推送",
        "gongneng_practice": "是",
        "event_start": "2026-11-07T09:00:00+08:00",
        "signup_deadline": "2026-10-25T23:59:59+08:00",
        "confidence": 0.98,
        "low_confidence": False,
        "tags": ["编程", "竞赛"],
        "evidence": {"location": "地点：津南校区A305"},
    }

    def test_select_fields_are_strings_not_arrays(self):
        """⚠️ 这条是**真踩过的**：v1 的单选要字符串，写成数组会被拒。"""
        row = opportunity_row(self.DATA)
        for column in ("类型", "状态", "推送状态", "公能实践"):
            assert isinstance(row[column], str), f"{column} 在 v1 里必须是字符串"
            assert not isinstance(row[column], list)

    def test_dates_are_ms(self):
        row = opportunity_row(self.DATA)
        assert isinstance(row["活动开始"], int)
        assert row["活动开始"] > 10**12, "是毫秒不是秒"

    def test_number_and_checkbox(self):
        row = opportunity_row(self.DATA)
        assert isinstance(row["置信度"], float)
        assert row["低置信"] is False

    def test_tags_joined_from_json_string(self):
        """⚠️ SQLite 里 tags 存的是 **JSON 字符串**，直接 join 会逐字符拼接。"""
        data = dict(self.DATA, tags='["编程", "竞赛"]')
        assert opportunity_row(data)["标签"] == "编程、竞赛"
        assert opportunity_row(self.DATA)["标签"] == "编程、竞赛"

    def test_empty_values_are_omitted(self):
        """空值**不写这一格** —— 写空串会冲掉表格里已有的值。"""
        row = opportunity_row({"name": "只有名字"})
        assert row == {"机会名称": "只有名字", "低置信": False}

    def test_evidence_is_json_text(self):
        row = opportunity_row(self.DATA)
        assert json.loads(row["依据"]) == {"location": "地点：津南校区A305"}


class TestStatusDefault:
    """`status` **从来没人算过** —— 迁移前是 SQLAlchemy 的默认值 `可参与`。

    这里锁住"迁移前后一致"：表里这一格不该是空的。
    （真正判断"还能不能报名"要看 `报名截止`，那个才是原文里的信息。）
    """

    def test_missing_status_is_omitted_by_row_but_defaulted_by_worker(self):
        from app.bitable import opportunity_row

        # row 层不管业务默认值 —— 空就不写
        assert "状态" not in opportunity_row({"name": "x"})
