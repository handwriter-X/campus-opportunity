"""GeniOS 代码节点：组队匹配 · 第一段「硬筛 + 拼文本」。

对应设计文档 `docs/module2_team_matching.md` §5.2 / §5.3。

## 这个节点干两件事

1. **硬筛**：用枚举字段（校区 / 每周可投入 / 技能）把候选从几百人压到几十人。
   这是**查询不是理解**——所以放在代码节点里，不消耗大模型。
2. **拼文本**：把结构化的一行画像拼成一段自然语言。
   **没有这一步，后面的「语义匹配」无从谈起**——大模型看不懂字典，看得懂句子。

## 实测依据

- 多维表格的多选字段筛选实测可用（`docs/findings.md` S7），但这里刻意**在代码节点里做**：
  这样工作流不依赖插件，换成 gateway 供数也能跑。
- 代码节点契约：必须 `def handler(inputs): ... return {...}`，不能顶层 `return`
  （`docs/findings.md` Q3）。

## 硬筛的两条计数原则

- **约束只在「需求方和候选方都有值」时生效**。候选没填校区 → 不算冲突，放行交给大模型判断。
  否则选填字段为空的好苗子会被误杀。
- 每次淘汰都记进 `dropped`，**淘汰原因要可见**——这是答辩时能讲的东西。
"""

import json

# 节点版本号。**必须手工递增** —— 它会被写到 End 的输出里，
# 用来判定"平台上跑的到底是哪一版"，免得来回猜。
# 整数，避免输出声明里还要改类型（平台默认就是 integer）
CODE_VERSION = 202610145

# 每周可投入的序数。投入度是「至少」语义：候选人投入 >= 需求期望即可
HOURS_ORDER = {"<5h": 0, "5-10h": 1, "10-20h": 2, ">20h": 3}


# ---------------------------------------------------------------- 输入收集


def _collect(obj, keys, found=None):
    """递归扫描输入结构，收集需要的字段。

    节点连线的产物形状不确定（可能平铺、可能嵌一层、可能是 JSON 字符串），
    所以不假设形状，直接深挖。与 `parse_and_validate.py::_collect` 同一套路。
    """
    if found is None:
        found = {}
    if isinstance(obj, str):
        s = obj.strip()
        if s[:1] in "{[":
            try:
                _collect(json.loads(s), keys, found)
            except (ValueError, TypeError):
                pass
        return found
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in keys and k not in found:
                found[k] = v
            _collect(v, keys, found)
    elif isinstance(obj, list):
        for v in obj:
            _collect(v, keys, found)
    return found


def _as_obj(value):
    """把一个可能是 JSON 字符串的值解析成 dict；失败返回 {}。"""
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        s = value.strip()
        if s[:1] == "{":
            try:
                data = json.loads(s)
            except (ValueError, TypeError):
                return {}
            return data if isinstance(data, dict) else {}
    return {}


def _as_list(value):
    """把一个可能是 JSON 字符串 / 单值 / 列表的值统一成 list。"""
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        s = value.strip()
        if s[:1] == "[":
            try:
                data = json.loads(s)
            except (ValueError, TypeError):
                data = None
            if isinstance(data, list):
                return data
        return [value] if s else []
    if value in (None, ""):
        return []
    return [value]


def _flatten_text(value):
    """把飞书返回的字段值压成字符串。

    ⚠️ **实测（2026-10-14，多维表格插件真实返回）**：**文本字段**是**富文本分段**
        `[{"text": "张三", "type": "text"}]`
    而**单选/多选**是普通字符串 / 字符串数组：
        `"年级": "大二"`、`"技能标签": ["编程", "设计"]`

    不处理分段就会把 `{'text': '张三', 'type': 'text'}` 当成姓名 ——
    而且**不报错**，只是画像文本变成一堆垃圾。见 `docs/findings.md` S7。
    """
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        for key in ("text", "name", "id"):
            inner = value.get(key)
            if isinstance(inner, str) and inner.strip():
                return inner.strip()
        return ""
    if isinstance(value, list):
        parts = []
        for item in value:
            text = _flatten_text(item)
            if text and text not in parts:
                parts.append(text)
        return "、".join(parts)
    return str(value).strip()


def _has_records(value):
    """判断一个值里**真的有没有候选记录**。

    ⚠️ 这个函数是 2026-10-14 被一个真实 bug 逼出来的：
    试运行时 `candidates_json` 被填成了 `"{}"`（空对象字符串），
    而 `_as_list("{}")` 会返回 `["{}"]` —— **非空**，
    于是它"赢"了，插件的 `items`（5 条真记录）永远轮不到。

    教训：判断"有没有值"不能只看空串，要看**里面有没有东西**。
    """
    if value is None or value == "":
        return False
    if isinstance(value, str):
        s = value.strip()
        if s[:1] not in "{[":
            return True  # 普通字符串，可能是单条记录的 JSON
        try:
            value = json.loads(s)
        except (ValueError, TypeError):
            return False
    if isinstance(value, dict):
        if not value:
            return False
        for key in ("items", "records"):
            if key in value and value.get(key):
                return True
        # 只有元信息（分页游标之类）不算有记录
        meta = {"has_more", "page_token", "total", "code", "msg", "error"}
        return bool(set(value) - meta)
    if isinstance(value, list):
        return any(item not in ({}, "", None) for item in value)
    return False


def _as_str_list(value):
    """转成字符串列表，丢掉空值。用于技能这类多选字段。"""
    out = []
    for item in _as_list(value):
        text = _flatten_text(item)
        if text and text not in out:
            out.append(text)
    return out


def _hours_rank(value):
    """每周可投入 → 序数；认不出来返回 None（不参与比较）。"""
    for item in _as_list(value):
        text = _flatten_text(item)
        if text in HOURS_ORDER:
            return HOURS_ORDER[text]
    return None


def _campus_of(obj):
    for key in ("campus", "所在校区"):
        if key in obj:
            text = _flatten_text(obj.get(key))
            if text:
                return text
    return ""


def _skills_of(obj):
    for key in ("skills", "技能标签"):
        if key in obj:
            return _as_str_list(obj.get(key))
    return []


def _open_ids_of(obj):
    """从人员字段里取 open_id。

    ⚠️ 多维表格 v1 接口的人员字段返回的是
    `[{"id": "ou_…", "name": "谢国辉", "email": …, "en_name": …}]`
    —— **要的是 `id`，不是 `name`**。按名字取会把展示名当成账号，
    而且**不报错**，只会一路错到飞书推送那一步。这里用 `ou_` 前缀兜底。

    （实测依据：`docs/findings.md` S7 实测记录）
    """
    for key in ("open_id", "owner_open_id", "飞书账号", "发起人", "负责人"):
        if key not in obj:
            continue
        out = []
        for item in _as_list(obj.get(key)):
            if isinstance(item, dict):
                value = item.get("id") or item.get("open_id")
            else:
                value = item
            text = str(value).strip() if value is not None else ""
            if text.startswith("ou_"):
                out.append(text)
        if out:
            return out
    return []


def _unwrap_record(raw):
    """把一条记录拆成「字段字典」。

    v1 接口返回的是 `{"fields": {…}, "record_id": "rec…", "id": "rec…"}`，
    而 gateway 供数或手工试运行时是**平的字段字典**。两种形状都要吃，
    否则接上插件的那一刻就会全线读不到字段（且不报错）。
    """
    if not isinstance(raw, dict):
        return {}
    inner = raw.get("fields")
    if isinstance(inner, dict):
        merged = dict(inner)
        record_id = raw.get("record_id") or raw.get("id")
        if record_id and "record_id" not in merged:
            merged["record_id"] = record_id
        return merged
    return raw


def _text_of(obj, *keys, default="未填写"):
    for key in keys:
        if key in obj:
            text = _flatten_text(obj.get(key))
            if text:
                return text
    return default


# ---------------------------------------------------------------- 拼文本


def _profile_line(index, cand):
    """把一条候选人画像拼成一行自然语言。`[index]` 是给大模型回传的锚点。"""
    parts = []
    grade = _text_of(cand, "grade", "年级", default="")
    college = _text_of(cand, "college", "major", "学院", "专业", default="")
    head = " · ".join(p for p in (grade, college) if p)
    if head:
        parts.append(head)

    skills = _skills_of(cand)
    if skills:
        parts.append("技能：" + "、".join(skills))

    campus = _campus_of(cand)
    if campus:
        parts.append("校区：" + campus)

    hours = _text_of(cand, "weekly_hours", "每周可投入", default="")
    if hours:
        parts.append("每周可投入：" + hours)

    direction = _as_str_list(cand.get("direction") or cand.get("意向方向") or [])
    if direction:
        parts.append("意向方向：" + "、".join(direction))

    line = "[%d] %s" % (index, " · ".join(parts) if parts else "（画像信息很少）")

    experience = _text_of(cand, "experience", "过往经历", default="")
    if experience and experience != "未填写":
        line += "\n    经历：" + experience

    intro = _text_of(cand, "intro", "一句话自我介绍", default="")
    if intro and intro != "未填写":
        line += "\n    自述：" + intro

    return line


def _request_text(req):
    """把需求 + 发起人画像拼成一段。**发起人画像必须在这里**——
    没有「发起人自己会什么」，大模型就只能找『像需求的人』，而不是『补需求的人』。"""
    lines = []
    title = _text_of(req, "title", "需求标题", default="")
    if title:
        lines.append("标题：" + title)
    lines.append("项目类型：" + _text_of(req, "project_type", "项目类型"))

    goal = _text_of(req, "goal", "预期目标", default="")
    if goal:
        lines.append("预期目标：" + goal)

    needed = _as_str_list(req.get("skills_needed") or req.get("需要的技能") or [])
    lines.append("需要什么技能：" + ("、".join(needed) if needed else "未指定"))

    campus = _campus_of(req)
    lines.append("所在校区：" + (campus or "未指定"))
    lines.append("期望每周投入：" + _text_of(req, "weekly_hours", "期望每周投入"))

    major_pref = _text_of(req, "major_pref", "专业背景偏好", default="")
    if major_pref:
        lines.append("专业背景偏好：" + major_pref)
    schedule = _text_of(req, "schedule", "时间安排", default="")
    if schedule:
        lines.append("时间安排：" + schedule)

    owner = _as_obj(req.get("owner_profile") or req.get("发起人画像") or {})
    owner_name = _text_of(owner, "name", "姓名", default=_text_of(req, "owner_name", "发起人", default="发起人"))
    owner_bits = []
    for key, label in (("grade", "年级"), ("college", "学院"), ("major", "专业")):
        value = _text_of(owner, key, label, default="")
        if value:
            owner_bits.append(value)
    owner_skills = _skills_of(owner)
    if owner_skills:
        owner_bits.append("技能：" + "、".join(owner_skills))
    owner_hours = _text_of(owner, "weekly_hours", "每周可投入", default="")
    if owner_hours:
        owner_bits.append("每周可投入：" + owner_hours)
    owner_campus = _campus_of(owner)
    if owner_campus and not campus:
        owner_bits.append("校区：" + owner_campus)

    lines.append("")
    lines.append("【发起人本人】" + owner_name + ("（" + " · ".join(owner_bits) + "）" if owner_bits else ""))
    owner_exp = _text_of(owner, "experience", "过往经历", default="")
    if owner_exp and owner_exp != "未填写":
        lines.append("发起人经历：" + owner_exp)

    return "\n".join(lines)


# ---------------------------------------------------------------- 入口


def handler(inputs):
    collected = _collect(
        inputs,
        ("request_json", "candidates_json", "candidates", "records", "items",
         "top_n", "min_score", "match_id"),
    )

    request = _as_obj(collected.get("request_json"))
    if not request:
        # 容错：调用方可能直接把需求对象平铺在 Start 参数里
        request = input_if_dict(inputs, "request") or {}

    # 两种上游都要能吃：
    # - gateway / 手工试运行：`candidates_json`（JSON 字符串）
    # - 多维表格插件 `search_records`：结构化对象，记录在 `items` / `records` 里
    candidate_source = ""
    candidate_raw = None
    candidates = []
    empty_sources = []
    for key in ("candidates_json", "candidates", "records", "items"):
        value = collected.get(key)
        if not _has_records(value):
            # 记下"有值但是空的"来源 —— 这正是上一次那个 `"{}"` 的情形
            if value not in (None, ""):
                empty_sources.append(key)
            continue
        candidates = _as_list(value)
        candidate_source, candidate_raw = key, value
        break
    candidates = [c for c in candidates if isinstance(c, dict) or isinstance(c, str)]

    match_id = collected.get("match_id") or request.get("match_id") or ""
    top_n = _safe_int(collected.get("top_n"), 3)
    min_score = _safe_int(collected.get("min_score"), 70)

    owner_ids = set(_open_ids_of(request))
    need_skills = set(_as_str_list(request.get("skills_needed") or request.get("需要的技能") or []))
    req_campus = _campus_of(request)
    req_hours = _hours_rank(request.get("weekly_hours") or request.get("期望每周投入"))

    dropped = {"本人": 0, "缺少飞书账号": 0, "校区不符": 0, "投入不足": 0,
               "技能不匹配": 0, "无法解析": 0}
    kept = []
    for raw in candidates:
        cand = _unwrap_record(_as_obj(raw) if isinstance(raw, str) else raw)
        if not cand:
            # 这里是"收到了东西但解析不出字段"。**必须计数** ——
            # 2026-10-14 就是因为这里静默跳过，出现"1 个进去 0 个淘汰 0 个留下"
            # 这种自相矛盾的结果，白查了一轮。
            dropped["无法解析"] += 1
            continue

        cand_ids = set(_open_ids_of(cand))
        if owner_ids and cand_ids & owner_ids:
            dropped["本人"] += 1
            continue

        # 没有飞书账号就没法通知、也没法写回匹配记录，直接淘汰（否则会一路错到推送那步）
        if not cand_ids:
            dropped["缺少飞书账号"] += 1
            continue

        # ① 校区：只在两边都有值时才当硬约束
        cand_campus = _campus_of(cand)
        if req_campus and cand_campus and cand_campus != req_campus:
            dropped["校区不符"] += 1
            continue

        # ② 每周可投入：候选人 >= 需求期望（投入度是「至少」语义）
        cand_hours = _hours_rank(cand.get("weekly_hours") or cand.get("每周可投入"))
        if req_hours is not None and cand_hours is not None and cand_hours < req_hours:
            dropped["投入不足"] += 1
            continue

        # ③ 技能：交集非空。候选没填技能 → 放行
        cand_skills = set(_skills_of(cand))
        if need_skills and cand_skills and not (need_skills & cand_skills):
            dropped["技能不匹配"] += 1
            continue

        kept.append(cand)

    # 超出上限时截断，避免大模型输入过长；截断是「谁先进表谁优先」，可接受
    max_candidates = 60
    truncated = max(0, len(kept) - max_candidates)
    kept = kept[:max_candidates]

    lines = []
    for index, cand in enumerate(kept):
        lines.append(_profile_line(index, cand))

    candidate_text = "\n".join(lines) if lines else "（没有通过硬筛的候选人）"

    # 编号顺序必须与 candidate_text 里的 [idx] 严格一一对应，
    # 否则下游 match_validate 的映射就会整体错位
    candidate_ids = [_open_ids_of(cand)[0] for cand in kept]

    issues = []
    if not request:
        issues.append("未收到需求（request_json 为空或解析失败）")
    if not candidates:
        issues.append("未收到候选人（candidates_json 为空）")
    if not kept and candidate_raw is not None:
        # 自诊断：一次运行就能看出"数据没接到"还是"接到了但形状不对"
        issues.append(
            "调试·候选来自 %r 键；共 %d 个元素；原始值类型=%s；预览=%s"
            % (candidate_source, len(candidates),
               type(candidate_raw).__name__, repr(candidate_raw)[:200])
        )
    elif not kept:
        issues.append(
            "调试·没拿到任何候选值；代码01 实际收到的键=%r" % (sorted(collected.keys()),)
        )
    if not kept and empty_sources:
        issues.append(
            "调试·这些键**有值但是空的**，已被跳过：%r —— "
            "若里面有 candidates_json，说明试运行时给它填了 `{}`；应该留空" % (empty_sources,)
        )
    if truncated:
        issues.append("候选人超过 %d 人，已截断 %d 人" % (max_candidates, truncated))
    if not kept:
        issues.append("硬筛后没有剩余候选人")

    return {
        "ok": bool(request) and bool(kept),
        "code_version": CODE_VERSION,
        "match_id": match_id,
        "request_text": _request_text(request),
        "candidate_text": candidate_text,
        "candidate_ids": candidate_ids,
        "candidate_count": len(kept),
        "input_count": len(candidates),
        "dropped": dropped,
        "top_n": top_n,
        "min_score": min_score,
        "issues": issues,
    }


def input_if_dict(inputs, key):
    if isinstance(inputs, dict):
        value = inputs.get(key)
        if isinstance(value, dict):
            return value
    return None


def _safe_int(value, default):
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default
