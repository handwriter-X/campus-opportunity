"""功能模块二「组队匹配」的两个 GeniOS 代码节点。

它们跑在 GeniOS 里（不是 gateway 的一部分），但**逻辑是我们可以本地验证的**，
而且这两段恰好是整条链路上最容易静默出错的地方：

- 代码节点 1：硬筛 —— 筛错了会「没人可推荐」，但**不报错**
- 代码节点 2：防幻觉映射 —— 大模型编造编号，**不拦住就会指向不存在的人**

所以按项目纪律（"改了行为就补测试"）把它们锁在测试套件里。
对应设计文档 `docs/module2_team_matching.md` §5。
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
CODE_NODES = REPO_ROOT / "genios" / "code_nodes"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, CODE_NODES / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


hard_filter = _load("match_hard_filter")
validate = _load("match_validate")


REQUEST = {
    "match_id": "req-001",
    "owner_open_id": "ou_owner",
    "owner_name": "张三",
    "title": "找队友参加数学建模",
    "project_type": "竞赛",
    "goal": "参加校内选拔，冲击国赛",
    "skills_needed": ["编程", "设计"],
    "campus": "津南",
    "weekly_hours": "10-20h",
    "owner_profile": {
        "name": "张三",
        "grade": "大二",
        "college": "计算机学院",
        "campus": "津南",
        "skills": ["编程"],
        "weekly_hours": "10-20h",
        "experience": "ACM 校赛二等奖",
    },
}

CANDIDATES = [
    {  # 校区不符
        "open_id": "ou_lisi", "name": "李四", "grade": "大三", "college": "文学院",
        "campus": "八里台", "skills": ["设计", "文案"], "weekly_hours": "5-10h",
        "experience": "校刊美编",
    },
    {  # 通过：技能互补（设计）
        "open_id": "ou_wangwu", "name": "王五", "grade": "大二", "college": "软件学院",
        "campus": "津南", "skills": ["编程", "设计"], "weekly_hours": "10-20h",
        "experience": "前端外包，会用 Figma",
    },
    {  # 校区不符 + 投入不足
        "open_id": "ou_zhaoliu", "name": "赵六", "grade": "研一", "college": "金融学院",
        "campus": "泰达", "skills": ["数据分析"], "weekly_hours": "<5h",
        "experience": "券商实习",
    },
    {  # 发起人本人
        "open_id": "ou_owner", "name": "张三", "grade": "大二", "college": "计算机学院",
        "campus": "津南", "skills": ["编程"], "weekly_hours": "10-20h",
        "experience": "ACM 校赛二等奖",
    },
    {  # 通过：没填校区与投入 —— 不该被误杀
        "open_id": "ou_zhouba", "name": "周八", "grade": "大二",
        "skills": ["设计"], "experience": "只填了技能",
    },
]


def _filter(request=None, candidates=None, **overrides):
    payload = {
        "request_json": json.dumps(request if request is not None else REQUEST, ensure_ascii=False),
        "candidates_json": json.dumps(candidates if candidates is not None else CANDIDATES,
                                      ensure_ascii=False),
        "match_id": "req-001",
        "top_n": "3",
        "min_score": "70",
    }
    payload.update(overrides)
    return hard_filter.handler(payload)


class TestHardFilter:
    def test_keeps_only_campus_match_and_complementary_skills(self):
        out = _filter()
        assert out["ok"] is True
        assert out["candidate_ids"] == ["ou_wangwu", "ou_zhouba"]
        assert out["input_count"] == 5
        assert out["candidate_count"] == 2

    def test_drop_reasons_are_counted(self):
        out = _filter()
        assert out["dropped"]["本人"] == 1
        assert out["dropped"]["校区不符"] == 2

    def test_missing_optional_fields_are_not_fatal(self):
        """候选没填校区/投入时应当放行交给大模型，而不是当作"不符"淘汰。"""
        out = _filter()
        assert "ou_zhouba" in out["candidate_ids"]

    def test_candidate_text_is_numbered_and_quotes_request(self):
        out = _filter()
        assert out["candidate_text"].startswith("[0] ")
        assert "[1] " in out["candidate_text"]
        # 发起人画像必须出现在需求文本里 —— 没有它就只能找"相似"而非"互补"
        assert "【发起人本人】" in out["request_text"]
        assert "ACM 校赛二等奖" in out["request_text"]

    def test_empty_candidates_reports_issue(self):
        out = _filter(candidates=[])
        assert out["ok"] is False
        assert out["candidate_ids"] == []
        assert any("候选人" in issue for issue in out["issues"])

    def test_bad_json_does_not_raise(self):
        out = hard_filter.handler({"request_json": "不是 JSON", "candidates_json": "{"})
        assert out["ok"] is False
        assert any("需求" in issue for issue in out["issues"])


class TestValidate:
    def _llm(self, matches):
        return {"raw_output": json.dumps({"matches": matches}, ensure_ascii=False)}

    def _validate(self, matches, ids=("ou_wangwu", "ou_zhouba"), **overrides):
        payload = dict(self._llm(matches))
        payload["candidate_ids"] = list(ids)
        payload["match_id"] = "req-001"
        payload["top_n"] = "3"
        payload["min_score"] = "70"
        payload.update(overrides)
        return validate.handler(payload)

    def test_maps_index_back_to_open_id(self):
        out = self._validate([{"idx": 0, "score": 93, "reason": "会设计，正好补你缺的环节"}])
        assert out["ok"] is True
        assert out["matches"][0]["open_id"] == "ou_wangwu"
        assert out["matches"][0]["score"] == 93.0

    def test_hallucinated_index_is_rejected(self):
        """大模型编造编号 → 必须拦下，否则会把不存在的人写进结果。"""
        out = self._validate([{"idx": 9, "score": 95, "reason": "编出来的候选人"}])
        assert out["ok"] is False
        assert out["matches"] == []
        assert any("越界" in issue for issue in out["issues"])

    def test_out_of_range_score_rejected(self):
        out = self._validate([{"idx": 0, "score": 150, "reason": "分数越界了"}])
        assert out["matches"] == []
        assert any("0-100" in issue for issue in out["issues"])

    def test_empty_reason_rejected(self):
        out = self._validate([{"idx": 0, "score": 88, "reason": "   "}])
        assert out["matches"] == []
        assert any("理由" in issue for issue in out["issues"])

    def test_below_threshold_yields_nothing(self):
        out = self._validate([{"idx": 0, "score": 55, "reason": "勉强但不太合适吧"}])
        assert out["ok"] is False
        assert out["matches"] == []
        assert any("低于" in issue for issue in out["issues"])

    def test_sorted_desc_and_trimmed_to_top_n(self):
        out = self._validate([
            {"idx": 0, "score": 80, "reason": "还行吧，可以考虑一下"},
            {"idx": 1, "score": 95, "reason": "非常合适，强烈推荐这位"},
        ])
        assert [m["open_id"] for m in out["matches"]] == ["ou_zhouba", "ou_wangwu"]

    def test_duplicate_index_keeps_highest_score(self):
        out = self._validate([
            {"idx": 0, "score": 72, "reason": "第一次评价：一般般啦"},
            {"idx": 0, "score": 88, "reason": "第二次评价：其实很合适"},
        ])
        assert len(out["matches"]) == 1
        assert out["matches"][0]["score"] == 88.0

    def test_empty_matches_is_not_an_error(self):
        """没有合适的人 → 如实返回空，不要硬凑。"""
        out = self._validate([])
        assert out["ok"] is False
        assert out["matches"] == []
        assert any("没有合适" in issue for issue in out["issues"])

    def test_missing_candidate_ids_short_circuits(self):
        out = validate.handler({"raw_output": '{"matches": []}'})
        assert out["ok"] is False
        assert any("candidate_ids" in issue for issue in out["issues"])


class TestBitableRecordShape:
    """接飞书多维表格插件之后的真实输入形状。

    这些是 2026-10-14 用 CLI 打 v1 接口**实测回来的**真实返回
    （见 `docs/findings.md` S7 实测记录），不是推测：

        {"fields": {…}, "record_id": "rec…", "id": "rec…"}

    人员字段是 `[{"id": "ou_…", "name": "谢国辉", "email": …, "en_name": …}]`
    —— **open_id 在 `id` 里，不在 `name` 里**。
    """

    RECORDS = [
        {
            "fields": {
                "姓名": "王五", "学院": "软件学院", "年级": "大二", "所在校区": "津南",
                "技能标签": ["编程", "设计"], "每周可投入": "10-20h",
                "过往经历": "做过前端外包，会用 Figma",
                "飞书账号": [{"id": "ou_wangwu", "name": "谢国辉",
                              "email": "x@mail.nankai.edu.cn"}],
            },
            "record_id": "rec1", "id": "rec1",
        },
        {  # 没填飞书账号 —— 通知不了，也必须写不回匹配记录
            "fields": {
                "姓名": "孙七", "学院": "计算机学院", "年级": "大二", "所在校区": "津南",
                "技能标签": ["编程"], "每周可投入": ">20h",
            },
            "record_id": "rec2", "id": "rec2",
        },
    ]

    def _run(self):
        return _filter(candidates=self.RECORDS)

    def test_fields_are_unwrapped(self):
        out = self._run()
        assert out["candidate_count"] == 1
        assert "[0] 大二 · 软件学院 · 技能：编程、设计 · 校区：津南" in out["candidate_text"]
        assert "做过前端外包" in out["candidate_text"]

    def test_user_field_yields_id_not_display_name(self):
        """按 name 取就把「谢国辉」当成账号了 —— 而且不报错。"""
        out = self._run()
        assert out["candidate_ids"] == ["ou_wangwu"]
        assert "谢国辉" not in out["candidate_ids"]

    def test_record_without_user_field_is_dropped_loudly(self):
        out = self._run()
        assert out["dropped"]["缺少飞书账号"] == 1
        assert "孙七" not in out["candidate_text"]

    def test_record_id_is_carried_through(self):
        unwrapped = hard_filter._unwrap_record(self.RECORDS[0])
        assert unwrapped["record_id"] == "rec1"
        assert unwrapped["技能标签"] == ["编程", "设计"]

    def test_flat_dict_still_works(self):
        """gateway 供数时是平的字段字典，也要能吃。"""
        flat = [{"open_id": "ou_flat", "campus": "津南", "skills": ["编程"],
                 "weekly_hours": "10-20h"}]
        out = _filter(candidates=flat)
        assert out["candidate_ids"] == ["ou_flat"]

    def test_empty_object_string_does_not_shadow_the_plugin(self):
        """⚠️ 2026-10-14 的真实 bug 回归。

        试运行时 `candidates_json` 被填成了 `"{}"`，而 `_as_list("{}")` 返回 `["{}"]`
        —— **非空**，于是它"赢"了，插件的 `items`（5 条真记录）永远轮不到。
        结果就是「1 个进去 / 0 个淘汰 / 0 个留下」这种自相矛盾的局面。
        """
        out = hard_filter.handler({
            "request_json": json.dumps(REQUEST, ensure_ascii=False),
            "candidates_json": "{}",                      # ← 罪魁祸首
            "search_records": self.REAL_PLUGIN_OUTPUT,    # ← 真正该用的
            "top_n": "3", "min_score": "70",
        })
        assert out["candidate_count"] == 1
        assert out["candidate_ids"] == ["ou_wangwu"]
        assert any("有值但是空的" in issue for issue in out["issues"]) or not out["issues"]

    def test_has_records_distinguishes_empty_from_real(self):
        assert hard_filter._has_records("{}") is False
        assert hard_filter._has_records("[]") is False
        assert hard_filter._has_records({}) is False
        assert hard_filter._has_records("") is False
        assert hard_filter._has_records(None) is False
        assert hard_filter._has_records({"has_more": False, "total": 0}) is False
        assert hard_filter._has_records([{}, ""]) is False
        assert hard_filter._has_records([{"fields": {"姓名": "王五"}}]) is True
        assert hard_filter._has_records({"items": [{"fields": {}}]}) is True
        assert hard_filter._has_records('[{"fields":{"姓名":"王五"}}]') is True

    def test_plugin_object_shape_works(self):
        """插件 search_records 的输出是**结构化对象**（记录在 items 里），
        不是 `candidates_json` 那种 JSON 字符串。两种上游都要能吃。"""
        out = hard_filter.handler({
            "request_json": json.dumps(REQUEST, ensure_ascii=False),
            "search_records": {"items": self.RECORDS, "has_more": False, "total": 2},
            "top_n": "3",
            "min_score": "70",
        })
        assert out["ok"] is True
        assert out["candidate_ids"] == ["ou_wangwu"]
        assert out["dropped"]["缺少飞书账号"] == 1

    # ↓↓↓ 以下用 2026-10-14 在 GeniOS 里真实跑出来的插件返回（逐字复制，未加工）↓↓↓

    REAL_PLUGIN_OUTPUT = {
        "data": {"code": 0, "data": {"has_more": False, "items": [
            {"fields": {
                "姓名": [{"text": "张三", "type": "text"}],
                "学院": [{"text": "计算机学院", "type": "text"}],
                "年级": "大二", "所在校区": "津南",
                "技能标签": ["编程", "数据分析"], "每周可投入": "10-20h",
                "过往经历": [{"text": "ACM 校赛二等奖，做过一个校园二手交易小程序",
                              "type": "text"}],
            }, "record_id": "recvy0aIfnVVZP"},
            {"fields": {
                "姓名": [{"text": "王五", "type": "text"}],
                "学院": [{"text": "软件学院", "type": "text"}],
                "年级": "大二", "所在校区": "津南",
                "技能标签": ["编程", "设计"], "每周可投入": "10-20h",
                "过往经历": [{"text": "做过前端外包，会用 Figma", "type": "text"}],
                "飞书账号": [{"email": "2411520@mail.nankai.edu.cn", "en_name": "谢国辉",
                              "id": "ou_wangwu",
                              "name": "谢国辉"}],
            }, "record_id": "recvy0aIfnQpsd"},
        ], "page_token": None, "total": 5}, "error": None, "msg": "success"}
    }

    def test_real_plugin_output_text_fields_are_rich_text_segments(self):
        """⚠️ 真实数据暴露的坑：**文本字段经插件返回时是富文本分段**
        `[{"text": "王五", "type": "text"}]`，而单选/多选是普通字符串/数组。

        不压平就会把 `{'text': '王五', 'type': 'text'}` 当成姓名 —— 而且**不报错**。
        """
        out = hard_filter.handler({
            "request_json": json.dumps(REQUEST, ensure_ascii=False),
            "search_records": self.REAL_PLUGIN_OUTPUT,
            "top_n": "3", "min_score": "70",
        })
        assert out["candidate_count"] == 1
        line = out["candidate_text"]
        assert "软件学院" in line
        assert "做过前端外包，会用 Figma" in line
        assert "text" not in line.replace("（画像信息很少）", "")  # 没漏出分段残留
        assert "{" not in line
        assert out["candidate_ids"] == ["ou_wangwu"]

    def test_flatten_text_handles_all_observed_shapes(self):
        assert hard_filter._flatten_text("大二") == "大二"
        assert hard_filter._flatten_text([{"text": "张三", "type": "text"}]) == "张三"
        assert hard_filter._flatten_text([{"text": "A", "type": "text"},
                                          {"text": "B", "type": "text"}]) == "A、B"
        assert hard_filter._flatten_text(["编程", "设计"]) == "编程、设计"
        assert hard_filter._flatten_text([{"id": "ou_x", "name": "谢国辉"}]) == "谢国辉"
        assert hard_filter._flatten_text(None) == ""


build_payload = _load("build_update_payload")


class TestBuildUpdatePayload:
    """代码03：把 `matches` 数组组装成 `update_records` 的入参。

    ⚠️ **v1 接口的单选字段必须是字符串**（实测：用数组会被拒
    `the value of 'Single Option' must be a string`）。这条如果不锁住，
    写回会整条失败，而报错信息在 GeniOS 里很难看到。
    """

    MATCHES = [
        {"open_id": "ou_a", "idx": 0, "score": 92, "reason": "会设计，正好补上缺口"},
        {"open_id": "ou_b", "idx": 1, "score": 80, "reason": "编程强但方向重合"},
    ]

    def _run(self, matches=None, record_id="rec_REQ1", **extra):
        payload = {"matches": self.MATCHES if matches is None else matches,
                   "match_id": "req-1", "request_record_id": record_id}
        payload.update(extra)
        return build_payload.handler(payload)

    def test_fields_json_shape(self):
        out = self._run()
        assert out["will_update"] is True
        assert out["record_id"] == "rec_REQ1"
        fields = json.loads(out["fields_json"])
        # 人员字段：v1 要 [{"id": "ou_…"}]
        assert fields["推荐队友1"] == [{"id": "ou_a"}]
        assert fields["推荐队友2"] == [{"id": "ou_b"}]
        # ⚠️ 单选字段必须是**字符串**
        assert fields["状态"] == "已匹配"
        assert isinstance(fields["状态"], str)
        assert "ou_a" not in out["fields_json"].replace('"ou_a"', "")  # 未泄漏裸 id
        assert "会设计" in fields["匹配理由"]

    def test_at_most_three_teammates(self):
        many = [{"open_id": "ou_%d" % i, "score": 90 - i, "reason": "理由 %d" % i}
                for i in range(5)]
        fields = json.loads(self._run(matches=many)["fields_json"])
        assert "推荐队友1" in fields and "推荐队友3" in fields
        assert "推荐队友4" not in fields

    def test_no_match_closes_the_request(self):
        """没匹配到人要收敛状态，否则 gateway 会一直重试同一行。"""
        out = self._run(matches=[])
        fields = json.loads(out["fields_json"])
        assert fields["状态"] == "已结束"
        assert out["recommended_count"] == 0

    def test_missing_record_id_reports_loudly(self):
        out = self._run(record_id="")
        assert out["will_update"] is False
        assert out["ok"] is False
        assert any("record_id" in issue for issue in out["issues"])

    def test_matches_are_passed_through_for_end(self):
        """End 只依赖代码03 一个上游，所以 matches 必须透传。"""
        out = self._run()
        assert out["match_count"] == 2
        assert out["matches"][0]["open_id"] == "ou_a"

    def test_sorted_by_score_desc(self):
        unordered = [{"open_id": "ou_low", "score": 60, "reason": "低分理由"},
                     {"open_id": "ou_high", "score": 95, "reason": "高分理由"}]
        fields = json.loads(self._run(matches=unordered)["fields_json"])
        assert fields["推荐队友1"] == [{"id": "ou_high"}]


class TestChain:
    def test_end_to_end_shapes_match_end_node_schema(self):
        """串起来跑一遍：Start → 代码01 → (大模型) → 代码02 → End。

        大模型那一步用固定的合法响应替代（真实调用要在 GeniOS 里跑），
        验的是**两个代码节点之间的契约**：`candidate_ids` 的顺序必须和
        `candidate_text` 里的 `[idx]` 一一对应，否则映射就会错位。
        """
        filtered = _filter()
        assert filtered["ok"] is True

        # 模拟大模型：给 0 号高分（技能互补），1 号低分
        llm = {
            "raw_output": json.dumps(
                {"matches": [
                    {"idx": 0, "score": 92, "reason": "会设计且投入充足，正好补上缺口"},
                    {"idx": 1, "score": 58, "reason": "只会设计，信息太少不好判断"},
                ]},
                ensure_ascii=False,
            )
        }

        final = validate.handler({**llm, **filtered})

        assert final["ok"] is True
        assert final["match_count"] == 1
        assert final["matches"][0]["open_id"] == "ou_wangwu"
        # End 节点声明的字段：两个理由**视角不同**，都要在
        assert set(final["matches"][0]) == {
            "open_id", "idx", "score", "reason", "invite_reason"
        }
