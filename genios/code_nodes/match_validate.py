"""GeniOS 代码节点：组队匹配 · 第二段「校验 + 防幻觉映射」。

对应设计文档 `docs/module2_team_matching.md` §5.5 的节点 5。

## 这个节点解决的核心问题：**大模型会编造用户**

大模型看到的是 `[0] 大二 · 软件学院 · …` 这样的编号列表。如果让它**直接回传 open_id**，
它一定会编——它根本不知道真实的 open_id 长什么样。

所以约定：**大模型只回传编号 `idx`，由本节点把 `idx` 映射回真实的 open_id。**
编出来的编号会越界，直接被这里拦下。这与第一段链路里「依据校验」是同一个思路。

## 另外校验

- `score` 必须在 0–100，且必须有值（没有锚点的分数会飘，见提示词里的分档说明）
- `reason` 必须非空（需求 5 明确要求「生成推荐匹配理由」）
- 去重：同一个候选人只保留分数最高的那条
- 排序 + 截断：按 score 降序取前 top_n，并丢掉低于 min_score 的
"""

import json

# 节点版本号，会被写到 End 的输出里（同上）。
CODE_VERSION = 202610141

# 一份理由短于这个长度基本就是敷衍，判为无效
MIN_REASON_LEN = 6


# ---------------------------------------------------------------- 输入收集


def _collect(obj, keys, found=None):
    """递归扫描输入结构。连了「大模型节点」和「上一段代码节点」两个上游，
    平铺还是嵌套都能找到。与 `parse_and_validate.py::_collect` 同一套路。
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


def _find_matches_payload(blob, found=None):
    """在所有字符串/字典里找那个「像匹配结果」的 JSON（含 matches 键）。"""
    if found is None:
        found = []
    if isinstance(blob, str):
        s = blob.strip()
        if s[:1] in "{[":
            try:
                data = json.loads(s)
            except (ValueError, TypeError):
                data = None
            if isinstance(data, dict):
                if "matches" in data:
                    found.append(data)
                else:
                    _find_matches_payload(data, found)
            elif isinstance(data, list):
                _find_matches_payload(data, found)
    elif isinstance(blob, dict):
        if "matches" in blob:
            found.append(blob)
        for v in blob.values():
            _find_matches_payload(v, found)
    elif isinstance(blob, list):
        for v in blob:
            _find_matches_payload(v, found)
    return found


def _to_int(value, default=None):
    try:
        return int(round(float(str(value).strip())))
    except (TypeError, ValueError):
        return default


def _to_float(value):
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None


def _as_str_list(value):
    if isinstance(value, list):
        out = []
        for item in value:
            if isinstance(item, str) and item.strip():
                out.append(item.strip())
        return out
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


# ---------------------------------------------------------------- 入口


def handler(inputs):
    collected = _collect(
        inputs,
        ("candidate_ids", "candidate_count", "top_n", "min_score", "match_id", "issues"),
    )

    candidate_ids = _as_str_list(collected.get("candidate_ids"))
    match_id = collected.get("match_id") or ""
    top_n = _to_int(collected.get("top_n"), 3) or 3
    min_score = _to_float(collected.get("min_score"))
    if min_score is None:
        min_score = 70.0

    issues = []

    if not candidate_ids:
        return {
            "ok": False,
            "match_id": match_id,
            "matches": [],
            "match_count": 0,
            "issues": ["没拿到候选编号表（candidate_ids 为空）——上游代码节点是否已连进来？"],
        }

    payloads = _find_matches_payload(inputs)
    if not payloads:
        return {
            "ok": False,
            "match_id": match_id,
            "matches": [],
            "match_count": 0,
            "issues": ["未能从上游输出里找到匹配结果 JSON（含 matches 键）"],
        }

    raw_matches = payloads[0].get("matches") or []
    if not isinstance(raw_matches, list):
        raw_matches = [raw_matches]

    # 先按 idx 聚合，同一个候选人取最高分
    best = {}
    for entry in raw_matches:
        if not isinstance(entry, dict):
            issues.append("丢弃一条非对象结果：%r" % (entry,))
            continue

        idx = _to_int(entry.get("idx"))
        if idx is None or idx < 0 or idx >= len(candidate_ids):
            # ★ 防幻觉：越界编号说明大模型编了一个不存在的候选人
            issues.append("丢弃越界编号 idx=%r（候选共 %d 个）" % (entry.get("idx"), len(candidate_ids)))
            continue

        open_id = candidate_ids[idx]
        if not open_id:
            issues.append("丢弃 idx=%d：该候选没有 open_id" % idx)
            continue

        score = _to_float(entry.get("score"))
        if score is None:
            issues.append("丢弃 idx=%d：score 缺失或非数字" % idx)
            continue
        if score < 0 or score > 100:
            issues.append("丢弃 idx=%d：score=%s 超出 0-100" % (idx, score))
            continue

        reason = entry.get("reason")
        reason = reason.strip() if isinstance(reason, str) else ""
        if len(reason) < MIN_REASON_LEN:
            issues.append("丢弃 idx=%d：理由为空或过短" % idx)
            continue

        # 给**被邀请人**看的那份理由（视角不同：这里的「你」指候选人）。
        # 缺了不至于丢掉整条匹配 —— 退回用 reason，总比让对方的卡片上没理由强。
        invite_reason = entry.get("invite_reason")
        invite_reason = invite_reason.strip() if isinstance(invite_reason, str) else ""
        if len(invite_reason) < MIN_REASON_LEN:
            issues.append("idx=%d 没有独立的 invite_reason（会用 reason 顶替）" % idx)
            invite_reason = reason
        elif invite_reason == reason:
            issues.append("idx=%d 的 invite_reason 和 reason 一模一样（模型没换视角）" % idx)

        previous = best.get(open_id)
        if previous is None or score > previous["score"]:
            best[open_id] = {
                "open_id": open_id, "idx": idx, "score": score,
                "reason": reason, "invite_reason": invite_reason,
            }

    matched = sorted(best.values(), key=lambda m: m["score"], reverse=True)
    above = [m for m in matched if m["score"] >= min_score]
    trimmed = above[:top_n] if top_n > 0 else above

    if matched and not above:
        issues.append("有 %d 个候选但分数都低于 %g，未推荐" % (len(matched), min_score))
    if len(above) > len(trimmed):
        issues.append("分数达标的 %d 个里只取前 %d 个" % (len(above), len(trimmed)))
    if not payloads[0].get("matches"):
        issues.append("大模型认为没有合适的队友")

    return {
        "ok": bool(trimmed),
        "code_version": CODE_VERSION,
        "match_id": match_id,
        "matches": trimmed,
        "match_count": len(trimmed),
        "candidate_count": len(candidate_ids),
        "min_score": min_score,
        "top_n": top_n,
        "issues": issues,
    }
