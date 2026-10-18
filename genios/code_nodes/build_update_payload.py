"""GeniOS 代码节点：组队匹配 · 第三段「组装写回多维表格的入参」。

## 它接在哪

    … → 代码02(校验) ──▶ 代码03(本节点) ──▶ 插件 update_records ──▶ End

## 为什么需要它

代码02 产出的是 `matches` **数组**：
    [{"open_id": "ou_a", "idx": 0, "score": 92, "reason": "…"}, …]

而 `update_records` 要的是**一条记录的字段对象**：
    {"推荐队友1": [{"id": "ou_a"}], "匹配理由": "…", "状态": "已匹配"}

**数组 → 记录对象** 这一层变形，就是本节点的全部工作。

## ⚠️ v1 接口的字段值写法（实测，和 v3 不一样）

| 字段类型 | 写法 |
| --- | --- |
| **单选** | **字符串**（`"已匹配"`）—— 用数组会被拒：`the value of 'Single Option' must be a string` |
| 多选 | 字符串数组 |
| 人员 | `[{"id": "ou_…"}]` |
| 文本 | 字符串 |

依据：`docs/findings.md` S7 实测记录。
"""

import json

CODE_VERSION = 202610141

# 最多写回几个推荐队友 —— 和表里的「推荐队友1/2/3」三个字段对应
MAX_TEAMMATES = 3

# 没有匹配到人时把状态置成这个（否则 gateway 会一直重试同一行）
NO_MATCH_STATUS = "已结束"


def _collect(obj, keys, found=None):
    """递归扫描输入结构，和另外两个代码节点同一套路。"""
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


def _as_list(value):
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
    """把飞书返回的字段值压成字符串（富文本分段 / 多选数组 / 人员对象都吃）。"""
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


def _safe_int(value, default=0):
    try:
        return int(round(float(str(value).strip())))
    except (TypeError, ValueError):
        return default


def handler(inputs):
    collected = _collect(
        inputs,
        ("matches", "match_id", "record_id", "request_record_id", "code_version"),
    )

    matches = [m for m in _as_list(collected.get("matches")) if isinstance(m, dict)]
    match_id = collected.get("match_id") or ""

    # 需求行的 record_id 可能来自 Start，也可能来自上游代码节点
    record_id = ""
    for value in (collected.get("request_record_id"), collected.get("record_id")):
        text = _flatten_text(value)
        if text.startswith("rec"):
            record_id = text
            break

    issues = []
    if not record_id:
        issues.append(
            "没拿到需求行的 record_id —— Start 有没有加 request_record_id 参数？"
            "（没有它就没有要更新的目标行）"
        )

    # 按分数降序（代码02 已经排过，这里再稳一次），最多取前 3 个
    ordered = sorted(matches, key=lambda m: -_safe_int(m.get("score")))[:MAX_TEAMMATES]

    fields = {}
    reason_lines = []
    invite_lines = []
    for index, match in enumerate(ordered):
        open_id = _flatten_text(match.get("open_id"))
        if not open_id:
            continue
        # 人员字段：v1 要 [{"id": "ou_..."}]
        fields["推荐队友%d" % (index + 1)] = [{"id": open_id}]
        score = _safe_int(match.get("score"))
        reason_lines.append(
            "%d. %s（%s 分）" % (index + 1, _flatten_text(match.get("reason")), score)
        )
        # **给被邀请人看的那一份**，视角不同（「你」指候选人）。
        # 缺了就退回用 reason —— 总比对方卡片上没理由强。
        invite_lines.append(
            "%d. %s（%s 分）"
            % (index + 1, _flatten_text(match.get("invite_reason")) or _flatten_text(match.get("reason")), score)
        )

    if reason_lines:
        fields["匹配理由"] = "\n".join(reason_lines)
        fields["邀请理由"] = "\n".join(invite_lines)
        # ⚠️ 单选字段在 v1 里必须是**字符串**，不能是数组
        fields["状态"] = "已匹配"
        recommendation = True
    else:
        # 一个都没匹配到：把状态收敛掉，否则 gateway 会一直重试同一行。
        # 这是产品取舍 —— 也可以改成保持「待匹配」，等有新的人注册再重试。
        fields["匹配理由"] = "本次未找到合适的队友，可重新发起。"
        fields["状态"] = NO_MATCH_STATUS
        recommendation = False
        issues.append("没有匹配到人，把状态置为「%s」" % NO_MATCH_STATUS)

    payload = {}
    if record_id:
        payload = {"record_id": record_id, "fields_json": json.dumps(fields, ensure_ascii=False)}

    return {
        "ok": bool(record_id) and bool(fields),
        "code_version": CODE_VERSION,
        "match_id": match_id,
        "will_update": bool(record_id),
        "record_id": record_id,
        # 给插件 update_records 用：fields_json 是**字符串**（参数名带 json）
        "fields_json": payload.get("fields_json", ""),
        # 同时给一份对象形态，万一插件那个参数其实吃对象、不吃字符串
        "fields_object": fields,
        "recommended_count": len(ordered) if recommendation else 0,
        # 透传下去，这样 End 只依赖本节点一个上游，接线更简单
        "matches": ordered,
        "match_count": len(ordered),
        "issues": issues,
    }
