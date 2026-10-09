"""GeniOS 代码节点：解析大模型输出 + 三层校验。

对应 PLAN §6「三层校验」（格式层 / 逻辑层 / 依据层）。

## 为什么需要这个节点

1. **大模型节点的输出信封是 `{"raw_output": "<字符串>"}`**（实测，见 docs/findings.md Q2）——
   里面的 JSON 是**字符串**不是对象，必须显式解析一次。
2. 三层校验按方案要求要落在这里（实测代码节点支持 `json`/`re`/`datetime`/`zoneinfo`，Python 3.10.19）。

## 实测确认的接口契约（见 docs/findings.md Q3）

- **不能**用顶层 `return`，也**不能**只靠 `print`；
  运行时期望模块里有一个叫 `handler` 的函数，并执行 `call_function(handler, inputs)`。
- 所以本文件定义 `def handler(inputs): ... return {...}`。

## 上游要连什么

这个节点的输入**至少要包含两样**（在 GeniOS 里把两个上游都连进来）：
- 大模型节点的输出（含 `raw_output`）
- Start 节点传来的原始文章（含 `text` / `links` / `publish_time`）

因为第三层「依据校验」要拿抽取结果去**原文里做子串匹配**，没有原文就校验不了。
下面 `_collect()` 会递归扫输入，把需要的东西找出来，所以两者是平铺还是嵌套都能work。
"""

import datetime as dt
import json
import re
import unicodedata

OPPORTUNITY_TYPES = ("竞赛", "学术与学习交流", "志愿活动与社会实践", "校园文体活动")
GONGNENG = ("是", "否", "未说明", "不适用")

# 第三层校验要验的「关键字段」
EVIDENCE_FIELDS = ("event_start", "event_end", "signup_start", "signup_deadline", "location", "quota", "signup_url")

# 判定为「有值」的最小长度：太短的片段（如「a」）在原文里匹配上没有意义
MIN_EVIDENCE_LEN = 4


# ---------------------------------------------------------------- 输入收集


def _collect(obj, keys, found=None):
    """递归扫描输入结构，收集所有需要顶层/嵌套字段。

    GeniOS 里节点连线的产物形状不确定（可能是平铺 dict，也可能嵌一层），
    所以这里不假设形状，直接深挖。
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


def _find_json_payload(blob, found=None):
    """在所有字符串里找那个「看起来像抽取结果」的 JSON。"""
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
                if "items" in data or "is_opportunity" in data:
                    found.append(data)
                else:
                    _find_json_payload(data, found)
    elif isinstance(blob, dict):
        if "items" in blob or "is_opportunity" in blob:
            found.append(blob)
        for v in blob.values():
            _find_json_payload(v, found)
    elif isinstance(blob, list):
        for v in blob:
            _find_json_payload(v, found)
    return found


# ---------------------------------------------------------------- 归一化


def _norm(text):
    """做空白与全半角归一化，用于「依据是否真实存在于原文」的比对。

    方案 §6 明确要求：做空白与全半角归一化后的子串匹配。
    """
    if text is None:
        return ""
    s = unicodedata.normalize("NFKC", str(text))
    return re.sub(r"\s+", "", s)


def _in_source(snippet, source_norm):
    return bool(snippet) and _norm(snippet) in source_norm


WEEKDAY_CN = ("星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日")

_WEEKDAY_RE = re.compile(r"(?:星期|周|礼拜)([一二三四五六日天])")


def _stated_weekday(text):
    """从一段文字里提取中文星期标注，如「10月18日（星期六）」→ 星期六。"""
    match = _WEEKDAY_RE.search(_norm(text))
    if not match:
        return None
    char = match.group(1)
    return "星期日" if char == "天" else f"星期{char}"


def _weekday_cn(value):
    return WEEKDAY_CN[value.weekday()]


# ---------------------------------------------------------------- 各层校验


_DAY_END = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[T ]24:00(?::00)?(?:\.\d+)?(?P<tz>Z|[+-]\d{2}:?\d{2})?$"
)


def _parse_dt(value):
    """解析 ISO 时间；带时区的按上海理解（本服务只服务校内）。

    ⚠️ 平台代码节点是 **Python 3.10**，它的 `fromisoformat` 比 3.11+ 严格：
    不接受 `T24:00:00`（ISO 8601 允许它表示「当日终点」）。而中文通知里
    「10月15日24:00 截止」非常常见，所以这里先手工归一化成次日 00:00。
    这个坑在 3.11+ 上复现不出来（那里能直接解析），别被本地环境骗了。
    """
    if not value or not isinstance(value, str):
        return None
    text = value.strip().replace("Z", "+00:00")

    day_end = _DAY_END.match(text)
    if day_end:
        next_day = dt.date(int(day_end.group(1)), int(day_end.group(2)), int(day_end.group(3))) + dt.timedelta(days=1)
        text = f"{next_day.isoformat()}T00:00:00{day_end.group('tz') or ''}"

    try:
        parsed = dt.datetime.fromisoformat(text)
    except ValueError:
        try:
            parsed = dt.datetime.combine(dt.date.fromisoformat(text), dt.time.min)
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone(dt.timedelta(hours=8)))
    return parsed


def _is_url(value):
    return bool(value) and re.match(r"^https?://[^\s]+$", str(value).strip())


def _validate_item(item, source_norm, links, publish_dt, index):
    """返回 (清洗后的 item, 问题列表)。不满足「依据层」的字段会被置空。"""
    issues = []
    if not isinstance(item, dict):
        return None, [f"items[{index}] 不是对象"]

    # ---- 第一层：格式 ----
    name = item.get("name")
    if not name or not str(name).strip():
        issues.append(f"items[{index}] 缺少 name，已丢弃")
        return None, issues

    otype = item.get("type")
    if otype not in OPPORTUNITY_TYPES:
        issues.append(f"items[{index}] 类型 {otype!r} 不在四类枚举内，已丢弃")
        return None, issues

    if item.get("gongneng_practice") not in GONGNENG:
        item["gongneng_practice"] = "未说明"

    # ---- 第二层：逻辑 ----
    parsed = {}
    for field in ("event_start", "event_end", "signup_start", "signup_deadline"):
        value = item.get(field)
        if value in (None, "", "null"):
            item[field] = None
            continue
        parsed_dt = _parse_dt(value)
        if parsed_dt is None:
            issues.append(f"items[{index}].{field} 不是可解析的 ISO 时间，已置空")
            item[field] = None
        else:
            parsed[field] = parsed_dt
            item[field] = parsed_dt.isoformat(timespec="seconds")

    start, end = parsed.get("event_start"), parsed.get("event_end")
    if start and end and start > end:
        issues.append(f"items[{index}] 活动开始晚于结束，event_start/event_end 已置空")
        item["event_start"] = item["event_end"] = None

    deadline = parsed.get("signup_deadline")
    if publish_dt and deadline and deadline < publish_dt - dt.timedelta(days=1):
        issues.append(f"items[{index}] 报名截止早于发布时间超过 1 天，signup_deadline 已置空")
        item["signup_deadline"] = None
        deadline = None

    # 年份与发布时间相差不超过 1 年
    if publish_dt:
        for field, value in list(parsed.items()):
            if abs(value.year - publish_dt.year) > 1:
                issues.append(f"items[{index}].{field} 年份({value.year})与发布时间差超过 1 年，已置空")
                item[field] = None

    signup_url = item.get("signup_url")
    if signup_url and not _is_url(signup_url):
        issues.append(f"items[{index}].signup_url 不是合法 URL，已置空")
        item["signup_url"] = None
        signup_url = None

    # ---- 第三层：依据（关键字段必须能在原文里找到） ----
    evidence = item.get("evidence") if isinstance(item.get("evidence"), dict) else {}
    kept_evidence = {}
    for field, snippet in evidence.items():
        if isinstance(snippet, str) and len(snippet.strip()) >= MIN_EVIDENCE_LEN and _in_source(snippet, source_norm):
            kept_evidence[field] = snippet
        else:
            issues.append(f"items[{index}] 字段 {field} 的原文依据未在原文中找到，该依据被丢弃")

    for field in EVIDENCE_FIELDS:
        value = item.get(field)
        if not value:
            continue
        snippet = kept_evidence.get(field)
        if not snippet:
            # 没有可信依据 → 置空并降置信度（方案 §6 的做法）
            issues.append(f"items[{index}].{field} 缺少可验证的原文依据，已置空")
            item[field] = None

    # 报名链接必须出现在原文或传入的 links 里
    if item.get("signup_url"):
        if not (_in_source(signup_url, source_norm) or signup_url in links):
            issues.append(f"items[{index}].signup_url 既不在原文也不在上游 links 里，已置空")
            item["signup_url"] = None

    item["evidence"] = kept_evidence

    # ---- 附加校验：原文星期标注 vs 规范化日期的真实星期 ----
    # 中文通知普遍写「10月18日（星期六）」，这个星期就是**免费的校验锚点**。
    # 实测踩到的坑：文章是 2025 年的，模型按「当前年份」推成了 2026 —— 日期整体错了一年，
    # 而「年份差 ≤ 1 年」的容差恰好放它过去。用星期一比就露馅了。
    date_conflicts = []
    for field, value in parsed.items():
        if item.get(field) is None:
            continue
        snippet = kept_evidence.get(field, "")
        stated = _stated_weekday(snippet)
        if not stated:
            continue
        # 「10月24日（星期六）24:00」这种写法，24:00 归一化后会滚到次日 00:00，
        # 但原文的星期说的是**滚之前那一天**。不处理就会误报。
        comparable = value
        if re.search(r"24[:：]00", _norm(snippet)):
            comparable = value - dt.timedelta(days=1)
        if stated != _weekday_cn(comparable):
            date_conflicts.append(
                f"{field}={item[field]} 与原文标注的{stated}不符（该日期实际是{_weekday_cn(comparable)}）"
            )
    if date_conflicts:
        issues.extend(f"items[{index}] 日期可疑：{c}" for c in date_conflicts)
        # 不静默置空 —— 日期本身可能仍有用，但必须让人知道它可疑
        item["date_conflict"] = date_conflicts

    # ---- 置信度 ----
    try:
        conf = float(item.get("confidence", 0))
    except (TypeError, ValueError):
        conf = 0.0
    conf = min(max(conf, 0.0), 1.0)
    if issues:
        conf = max(0.0, conf - 0.15 * len(issues))
    item["confidence"] = round(conf, 3)
    item["low_confidence"] = conf < 0.6

    item.setdefault("tags", [])
    return item, issues


# ---------------------------------------------------------------- 输出整形


def _to_gateway_shape(item, collected, publish_dt):
    """把抽取结果的键名对齐 gateway `POST /opportunities` 的字段名。

    网关的 `_OPPORTUNITY_FIELDS`（gateway/app/store.py:194）接受的键是：
    name / type / summary / event_time_raw / signup_deadline_raw / location / audience /
    quota / signup_method / signup_url / gongneng_practice / source_url / source_account /
    confidence / low_confidence
    加上 datetime 字段 publish_time / signup_start / event_start / event_end / signup_deadline，
    以及 article_id / tags / evidence / extra。

    对齐之后，HTTP 节点可以把本节点的输出**原样**作为请求体发出去，不需要再映射。
    """
    item["event_time_raw"] = item.pop("event_time_text", None)
    item["signup_method"] = item.pop("signup_method_text", None)
    item["source_account"] = collected.get("source")
    item["source_url"] = collected.get("url")
    item["article_id"] = collected.get("article_id")
    if publish_dt is not None:
        item["publish_time"] = publish_dt.isoformat(timespec="seconds")

    # 类型专属字段整体塞进 extra（网关会原样存 JSON），避免为四种类型各加一批列
    item["extra"] = {"type_specific": item.pop("type_specific", {})}
    return item


# ---------------------------------------------------------------- 入口


def handler(inputs):
    """GeniOS 代码节点入口（实测契约：运行时会调用 handler(inputs)）。"""
    collected = _collect(inputs, {"text", "links", "article_id", "publish_time", "source", "title", "url"})

    raw_text = collected.get("text") or ""
    links = collected.get("links") or []
    if isinstance(links, str):
        try:
            links = json.loads(links)
        except (ValueError, TypeError):
            links = [links]
    links = [str(x) for x in links] if isinstance(links, list) else []

    publish_dt = _parse_dt(collected.get("publish_time"))
    source_norm = _norm(raw_text)

    candidates = _find_json_payload(inputs)
    if not candidates:
        return {
            "ok": False,
            "reason": "未能从上游输出里找到抽取结果 JSON",
            "article_id": collected.get("article_id"),
            "items": [],
            "issues": ["未找到含 items/is_opportunity 的 JSON 对象"],
        }

    payload = candidates[0]
    items_in = payload.get("items") or []
    if not isinstance(items_in, list):
        items_in = [items_in]

    issues = []
    cleaned = []
    for i, item in enumerate(items_in):
        result, item_issues = _validate_item(item, source_norm, links, publish_dt, i)
        issues.extend(item_issues)
        if result is not None:
            cleaned.append(_to_gateway_shape(result, collected, publish_dt))

    # `first_item` 是给 HTTP 请求节点的便利输出：
    # `/opportunities` 一次只收一条记录，而 GeniOS 的变量选择器不一定支持
    # `items[0]` 这种下标写法，所以直接把第一条单独放一份，Body 里点选它即可。
    return {
        "ok": bool(cleaned),
        "is_opportunity": bool(payload.get("is_opportunity")) and bool(cleaned),
        "article_id": collected.get("article_id"),
        "items": cleaned,
        "first_item": cleaned[0] if cleaned else None,
        "issues": issues,
        "item_count": len(cleaned),
    }
