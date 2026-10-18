"""对话流 · 代码节点：把两张表拼成**给大模型看的上下文**。

## 它接在哪

```
Start ─┬─▶ 插件 search_records（读【机会汇总】）──┐
       ├─▶ 插件 search_records（读【队友画像】）──┤
       └───────────────────────────────────────▶ 代码节点（本文件）
                                                     │
                                                     ▼
                                            意图识别 / 大模型节点
```

## 它干两件事

1. **把表格行拼成人话** —— 大模型看不懂 `{"报名截止": 1792915199000}`，
   看得懂「报名截止 2026-10-25」。
2. **把"我是谁"挑出来** —— 用户问"有哪些**适合我**的比赛"，
   模型必须知道 TA 的技能/校区/年级。画像表里其他人也在，所以要**按 `user_id` 找出本人**。

## ⚠️ 关键：`user_id` 是**对话流开始节点白给的**

对话流的开始节点有系统参数 `user_id`（飞书 open_id）。
**这是我们唯一需要传进去的身份** —— 有它才能查画像。
（来源：`conver.md` 的「对话流与工作流差异点」一节。）
"""

import json
import datetime as dt

CN_TZ = dt.timezone(dt.timedelta(hours=8))

# 机会表里"值得讲给用户听"的字段，按这个顺序拼
OPPORTUNITY_FIELDS = (
    ("机会名称", "名称"),
    ("类型", "类型"),
    ("报名截止", "报名截止"),
    ("活动开始", "开始时间"),
    ("地点", "地点"),
    ("参与对象", "面向"),
    ("名额", "名额"),
    ("报名方式", "报名方式"),
    ("报名链接", "报名链接"),
    ("原文链接", "原文"),
)


def _collect(obj, keys, found=None):
    """按**固定名字**递归取标量参数（开始节点的系统参数名字是固定的：user_id / query…）。"""
    if found is None:
        found = {}
    if isinstance(obj, str):
        t = obj.strip()
        if t[:1] in "{[":
            try:
                _collect(json.loads(t), keys, found)
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


def _find_record_lists(obj, out=None, depth=0):
    """递归找出输入里**所有的「记录列表」**。

    ## ⚠️ 为什么不按变量名找

    第一版是按 `opportunities` / `机会汇总` 这种**变量名**去找的 ——
    但**画布上连线时变量名叫什么是人定的**，对不上就一个都找不到，
    表现为"模型说列表是空的"，**而且不报错**（实测踩过）。

    ## 现在的办法：按**字段特征**认

    - 行里有 `机会名称` → 机会表的记录
    - 行里有 `姓名` / `技能标签` / `飞书账号` → 画像表的记录

    这样就完全不依赖变量名了。
    """
    if out is None:
        out = []
    if depth > 8:
        return out
    if isinstance(obj, str):
        s = obj.strip()
        if s[:1] in "{[":
            try:
                _find_record_lists(json.loads(s), out, depth + 1)
            except (ValueError, TypeError):
                pass
        return out
    if isinstance(obj, dict):
        for value in obj.values():
            _find_record_lists(value, out, depth + 1)
        return out
    if isinstance(obj, list):
        rows = [_fields(item) for item in obj if isinstance(item, dict)]
        rows = [r for r in rows if r]
        if rows:
            out.append(rows)
            return out                       # 已经是一层记录了，别再往下拆
        for item in obj:
            _find_record_lists(item, out, depth + 1)
        return out
    return out


def _pick(lists, marker_keys):
    """从所有记录列表里，挑出**行里带这些字段**的那些，合并起来。"""
    picked = []
    for rows in lists:
        if rows and any(key in rows[0] for key in marker_keys):
            picked.extend(rows)
    return picked


def _fields(row):
    """记录可能是 `{"fields": {...}}`，也可能已经摊平了。

    ⚠️ **把 `record_id` 带进来** —— 插件返回的是 `{"record_id": "rec…", "fields": {...}}`，
    只取 `fields` 会把它丢掉。而"推荐了哪一条"必须能让 gateway 精确定位到行
    （模型照着编一个名字是不可信的）。
    """
    if not isinstance(row, dict):
        return {}
    inner = row.get("fields")
    if isinstance(inner, dict):
        flat = dict(inner)
        if row.get("record_id"):
            flat.setdefault("record_id", row["record_id"])
        return flat
    return row


def _flat(value):
    """飞书返回的字段值 → 字符串。

    ⚠️ **文本字段是富文本分段** `[{"text": "张三", "type": "text"}]`；
    单选/多选是普通字符串 / 字符串数组。不处理分段就会拼出乱码。
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
            text = _flat(item)
            if text and text not in parts:
                parts.append(text)
        return "、".join(parts)
    return str(value).strip()


def _open_ids(value):
    """人员字段 → open_id 列表。**要 `id`，不是 `name`**。"""
    if value in (None, ""):
        return []
    items = value if isinstance(value, list) else [value]
    out = []
    for item in items:
        candidate = item.get("id") if isinstance(item, dict) else item
        text = str(candidate).strip() if candidate is not None else ""
        if text.startswith("ou_") and text not in out:
            out.append(text)
    return out


def _ms_to_text(value):
    """毫秒时间戳 → `2026-10-28 23:59`（按东八区）。"""
    try:
        moment = dt.datetime.fromtimestamp(int(value) / 1000, CN_TZ)
    except (TypeError, ValueError, OSError):
        return ""
    return moment.strftime("%Y-%m-%d %H:%M")


def _opportunity_line(index, row):
    fields = _fields(row)
    bits = []
    for key, label in OPPORTUNITY_FIELDS:
        raw = fields.get(key)
        if key in ("报名截止", "活动开始"):
            text = _ms_to_text(raw) if raw else ""
        else:
            text = _flat(raw)
        if text:
            bits.append(f"{label}：{text}")
    header = f"[{index}] " + (bits[0].replace("名称：", "") if bits else "（无名称）")
    # ⚠️ 编号放在标题行末尾 —— 模型推荐某条时**原样抄这一串**，
    # gateway 才能精确取出那一行发卡片。抄错就是没有卡片，不会发错活动。
    record_id = _flat(fields.get("record_id"))
    if record_id:
        header += f"（{record_id}）"
    rest = bits[1:]
    return header + ("\n    " + " · ".join(rest) if rest else "")


def _profile_line(row):
    fields = _fields(row)
    bits = []
    for key, label in (("姓名", ""), ("年级", ""), ("学院", ""), ("所在校区", ""),
                       ("每周可投入", "每周"), ("技能标签", "技能")):
        text = _flat(fields.get(key))
        if text:
            bits.append(f"{label}：{text}" if label else text)
    return " · ".join(bits)


def handler(inputs):
    # ⚠️ 开始节点的系统参数（user_id / query）是**固定名字**，可以按名字取；
    # 但两个插件节点的输出**名字由人定**，所以按**字段特征**认（见 _find_record_lists）。
    sys_params = _collect(inputs, ("user_id", "query", "user_query"))
    user_id = _flat(sys_params.get("user_id"))
    query = _flat(sys_params.get("query") or sys_params.get("user_query"))

    lists = _find_record_lists(inputs)
    opp_rows = _pick(lists, ("机会名称",))
    profile_rows = _pick(lists, ("姓名", "技能标签", "飞书账号"))

    now_ms = int(dt.datetime.now(CN_TZ).timestamp() * 1000)

    open_lines = []
    expired = 0
    for row in opp_rows:
        fields = _fields(row)
        deadline = fields.get("报名截止")
        if isinstance(deadline, (int, float)) and deadline and deadline < now_ms:
            expired += 1
            continue
        open_lines.append(_opportunity_line(len(open_lines), row))

    # ── 找出"提问者本人" ──
    #
    # ⚠️ **优先用 gateway 拼在 query 里的那份**（`【我的画像】…`）。
    #
    # 为什么不靠 user_id 去画像表里匹配（**实测踩过，2026-10-17**）：
    # 飞书的 **open_id 是「按应用」算的** —— 同一个人，两个应用下是两个 ID。
    #   gateway（自建应用）读表 → ou_87ad…
    #   飞书消息的 sender        → ou_87ad…   ← 对得上
    #   本节点通过插件读表        → ou_1b65…   ← 另一个应用，**永远对不上**
    # 所以 gateway 查好、拼进来，这边直接用。
    me = ""
    if "【我的画像】" in query:
        me = query.split("【我的画像】", 1)[1].split("\n", 1)[0].strip()
    if not me:                      # 兜底：万一 gateway 没拼（比如直接调 API 调试）
        for row in profile_rows:
            if user_id and user_id in _open_ids(_fields(row).get("飞书账号")):
                me = _profile_line(row)
                break

    issues = []
    if not opp_rows:
        issues.append("没读到机会表 —— 插件节点连上了吗？")
    if not me:
        issues.append("没拿到提问者的画像（gateway 没拼进来，表里也没匹配上）")

    # ⚠️ **第一行就把"读没读到"写死**。
    # 起因：模型答"列表是空的"时，我们分不清是"表真的空"还是"根本没连上" ——
    # 而诊断只有平台的调试面板能看到，排查时拿不到截图。
    # 现在把原始条数写进标题，模型**照着念就会把真相带出来**。
    head = "【可报名的机会】共 %d 条" % len(open_lines)
    if opp_rows:
        head += "（表里读到 %d 条，%d 条已过报名截止）" % (len(opp_rows), expired)
    else:
        head += "（警告：系统没有读到机会表。请如实告诉同学：系统暂时读不到数据，不要说没有机会。不要编造活动。）"
    context = [head]
    context.extend(open_lines or ["（暂无）"])
    context.append("")
    context.append("【提问的同学】" + (me if me else "（还没填过画像，只能给通用推荐）"))

    # ⚠️ **把诊断信息塞进上下文，让模型替我们说**。
    # 起因：代码节点的 `issues` 只有平台的调试面板能看到，
    # 而排查时拿不到截图 —— 于是"读不到数据"只能表现为模型说"列表是空的"，
    # **看不出到底是没连上、还是表真的空**。
    # 有诊断时多加一段，模型会照实转达（提示词里已交代）。
    if issues:
        context.append("")
        context.append("【系统提示·请如实转达给同学】" + "；".join(issues))

    return {
        "ok": bool(opp_rows),
        "code_version": 202610161,
        "user_id": user_id,
        "query": query,
        "context": "\n".join(context),
        "opportunity_count": len(opp_rows),
        "open_count": len(open_lines),
        "expired_count": expired,
        "has_profile": bool(me),
        "profile_line": me,
        "issues": issues,
    }
