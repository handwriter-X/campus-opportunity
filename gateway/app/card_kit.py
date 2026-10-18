"""飞书卡片的公共零件与版式。

## 版式约定（所有卡片都遵守）

| 位置 | 放什么 | 为什么 |
| --- | --- | --- |
| **header** | **主体名称**（机会名 / 需求名） | 飞书卡片里**唯一能放大的位置**，也是通知栏露出的那一行 |
| **第一个 div** | **最该先知道的时间**（报名截止） | 决定"还来不来得及" |
| 中间 div | 一行一个维度（地点 / 名额 / 面向…） | 不要堆成一坨 |
| **action** | 一个主按钮 + 一个次要按钮 | 主按钮多了等于没有 |
| **note** | 来源 / 免责 | 建立信任，也是合规 |

> ⚠️ **一张卡只放一个机会**。多放几个，标题就只能写"发现 3 个机会"，
> 名字退回正文的小字号 —— 那正是这次要改掉的东西。

## 几条踩过的约束

- **`note` 里的 `plain_text` 不会被转成链接** → 需要用户复制的长链接放这里。
  卡片 `button.url` 会被飞书**重新编码**，`%2F` 变 `/` 会截断查询串（错误码 20029）。
- **`lark_md` 支持 `**加粗**`，但不支持字号** —— 想要"大"，只能用 header。
- **`hr` 用来分隔并列项**。
- 卡片 `template` 是**语义**：green=成功 · blue=通知 · orange=警告 · red=错误 · grey=中性。
"""

from __future__ import annotations

import datetime as dt
import re
from typing import Any

# 四类机会的视觉锚点。**逐字对齐枚举值**（AGENTS 不变量 5）
TYPE_EMOJI = {
    "竞赛": "🏆",
    "学术与学习交流": "🎓",
    "志愿活动与社会实践": "🤝",
    "校园文体活动": "🎨",
}
TYPE_TEMPLATE = {
    "竞赛": "turquoise",
    "学术与学习交流": "blue",
    "志愿活动与社会实践": "green",
    "校园文体活动": "purple",
}

CN_TZ = dt.timezone(dt.timedelta(hours=8))


# ---------------------------------------------------------------- 零件


def div(content: str) -> dict[str, Any]:
    return {"tag": "div", "text": {"tag": "lark_md", "content": content}}


def plain(content: str) -> dict[str, Any]:
    """纯文本 div —— **不会被自动识别成链接**，用于让人复制的东西。"""
    return {"tag": "div", "text": {"tag": "plain_text", "content": content}}


def note(content: str) -> dict[str, Any]:
    return {"tag": "note", "elements": [{"tag": "plain_text", "content": content}]}


def hr() -> dict[str, Any]:
    return {"tag": "hr"}


def action(buttons: list[dict[str, Any]]) -> dict[str, Any]:
    return {"tag": "action", "actions": buttons}


def button(
    label: str,
    *,
    value: dict[str, Any] | None = None,
    url: str | None = None,
    kind: str = "default",
) -> dict[str, Any]:
    """按钮。**`value` 走回调，`url` 走跳转** —— 两者不能混用（飞书会 20029）。"""
    item: dict[str, Any] = {
        "tag": "button",
        "text": {"tag": "plain_text", "content": label},
        "type": kind,
    }
    if url:
        item["url"] = url
    if value is not None:
        item["value"] = value
    return item


def card(*, template: str, title: str, elements: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "config": {"wide_screen_mode": True},
        "header": {"template": template, "title": {"tag": "plain_text", "content": title}},
        "elements": elements,
    }


# ---------------------------------------------------------------- 格式化


def fmt_when(value: Any) -> str:
    """时间 → `10月25日 23:59`。认不出来就原样返回（别吞信息）。

    支持三种输入：**毫秒时间戳**（多维表格的日期字段）、ISO 字符串、普通文本。
    """
    if value in (None, ""):
        return ""
    if isinstance(value, (int, float)):
        try:
            moment = dt.datetime.fromtimestamp(float(value) / 1000, CN_TZ)
        except (OSError, ValueError):
            return ""
        return _cn(moment)

    text = str(value).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        moment = dt.datetime.fromisoformat(text)
    except ValueError:
        return text
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=CN_TZ)
    return _cn(moment.astimezone(CN_TZ))


def _cn(moment: dt.datetime) -> str:
    return moment.strftime("%m月%d日 %H:%M").lstrip("0").replace("月0", "月")


def _short(text: Any, limit: int) -> str:
    value = "" if text is None else str(text).strip()
    return value if len(value) <= limit else value[: limit - 1] + "…"


# 「要扫码 / 要进群」的信号词。抽到这些就说明**大概率没有能点的报名链接**。
QR_HINTS = ("扫码", "二维码", "识别", "扫一扫", "群二维码", "加群", "入群")


def qr_signup_hint(method: str) -> bool:
    return any(word in (method or "") for word in QR_HINTS)


def _method_line(method: str, *, has_link: bool) -> str:
    """「报名方式」那一行。

    ⚠️ **别把链接重复念一遍** —— 抽取经常把 URL 也塞进 `signup_method`，
    卡片上已经有按钮了，再写一行 "报名方式：登录 https://…" 纯属噪音。
    """
    text = (method or "").strip()
    if not text:
        return ""
    if has_link:
        text = re.sub(r"https?://\S+", "", text).strip(" ：:，,、·")
        if not text or text in ("登录", "报名链接", "在线报名"):
            return ""
    return f"📝 报名方式：{text}"


def _title_of(name: str, limit: int = 34) -> str:
    return name if len(name) <= limit else name[: limit - 1] + "…"


def _text(value: Any) -> str:
    """飞书字段值 → 字符串（富文本分段 / 人员 / 多选都压平）。"""
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, dict):
        for key in ("text", "name", "id"):
            inner = value.get(key)
            if isinstance(inner, str) and inner.strip():
                return inner.strip()
        return ""
    if isinstance(value, (list, tuple)):
        return "、".join(p for p in (_text(v) for v in value) if p)
    return str(value).strip()


# ---------------------------------------------------------------- 机会卡片


def row_to_item(row: dict[str, Any]) -> dict[str, Any]:
    """【机会汇总】的一行 → 卡片用的 item。

    模块一从抽取结果建卡、对话从表里建卡，**都走这里**，版式才不会分叉。
    """
    return {
        "name": _text(row.get("机会名称")),
        "type": _text(row.get("类型")),
        "summary": _text(row.get("简介")),
        "event_time_text": _text(row.get("活动时间原文")),
        "event_start": row.get("活动开始"),
        "signup_deadline": row.get("报名截止"),
        "location": _text(row.get("地点")),
        "audience": _text(row.get("参与对象")),
        "quota": _text(row.get("名额")),
        "signup_url": _text(row.get("报名链接")),
        "signup_method": _text(row.get("报名方式")),
        "origin_url": _text(row.get("原文链接")),
        "source": _text(row.get("来源公众号")),
        "low_confidence": bool(row.get("低置信")),
        "confidence": row.get("置信度"),
        "date_conflict": row.get("date_conflict"),
    }


def payload_item_to_item(item: dict[str, Any]) -> dict[str, Any]:
    """抽取结果（step1 的 items[]）→ 同一形状。"""
    return {
        "name": _text(item.get("name")),
        "type": _text(item.get("type")),
        "summary": _text(item.get("summary")),
        "event_time_text": _text(item.get("event_time_text") or item.get("event_time_raw")),
        "event_start": item.get("event_start") or item.get("event_time_text"),
        "signup_deadline": item.get("signup_deadline"),
        "location": _text(item.get("location")),
        "audience": _text(item.get("audience")),
        "quota": _text(item.get("quota")),
        "signup_url": _text(item.get("signup_url")),
        "signup_method": _text(item.get("signup_method_text") or item.get("signup_method")),
        "origin_url": "",
        "source": "",
        "low_confidence": bool(item.get("low_confidence")),
        "confidence": item.get("confidence"),
        "date_conflict": item.get("date_conflict"),
    }


def build_opportunity_card(
    item: dict[str, Any],
    *,
    source: str | None = None,
    original_url: str | None = None,
    footer: str | None = None,
) -> dict[str, Any] | None:
    """**一个机会一张卡**，标题就是机会名。

    `item` 用 `row_to_item` / `payload_item_to_item` 归一化过。
    """
    name = _text(item.get("name"))
    if not name:
        return None

    type_text = _text(item.get("type"))
    emoji = TYPE_EMOJI.get(type_text, "📌")
    template = TYPE_TEMPLATE.get(type_text, "turquoise")
    source = source or _text(item.get("source"))
    original_url = original_url or _text(item.get("origin_url"))

    elements: list[dict[str, Any]] = []

    # ① 时间 —— 用户最先要知道的就是"还来不来得及"
    deadline = fmt_when(item.get("signup_deadline"))
    when = _text(item.get("event_time_text")) or fmt_when(item.get("event_start"))
    head_bits = []
    if deadline:
        head_bits.append(f"⏰ **报名截止 {deadline}**")
    if when:
        head_bits.append(f"🕐 {when}")
    if head_bits:
        elements.append(div("　·　".join(head_bits)))

    # ② 事实行：地点 / 名额
    facts = []
    if _text(item.get("location")):
        facts.append(f"📍 {_text(item.get('location'))}")
    if _text(item.get("quota")):
        facts.append(f"👥 {_text(item.get('quota'))}")
    if facts:
        elements.append(div("　".join(facts)))

    # ③ 面向
    if _text(item.get("audience")):
        elements.append(div(f"🎯 面向：{_text(item.get('audience'))}"))

    # ④ 报名方式 —— 公众号经常只用二维码，没有可点的链接
    method = _text(item.get("signup_method"))
    method_line = _method_line(method, has_link=bool(_text(item.get("signup_url"))))
    if method_line:
        elements.append(div(method_line))

    # ⑤ 简介
    summary = _short(_text(item.get("summary")), 100)
    if summary:
        elements.append(div(summary))

    # ⑤ 异常提示
    conflicts = item.get("date_conflict")
    if conflicts:
        if isinstance(conflicts, (list, tuple)):
            conflicts = "；".join(str(c) for c in conflicts)
        elements.append(div(f"⚠️ 原文里的时间对不上，请核对：{conflicts}"))
    elif item.get("low_confidence"):
        elements.append(div(f"⚠️ AI 对这条把握不大（置信度 {item.get('confidence', '—')}）"))

    # ⑦ 按钮
    #
    # ⚠️ **没有报名链接时，别留一个点不动的「立即报名」。**
    # 公众号常见做法是"扫码报名"：`报名链接` 是空的，二维码在原文里。
    # 这时候唯一诚实的入口就是原文 —— 把主按钮换成它，并说清去干什么。
    signup_url = _text(item.get("signup_url"))
    buttons = []
    if signup_url:
        buttons.append(button("立即报名", url=signup_url, kind="primary"))
        if original_url:
            buttons.append(button("查看原文", url=original_url))
    elif original_url:
        label = "去原文扫码报名" if qr_signup_hint(method) else "去原文看怎么报名"
        buttons.append(button(label, url=original_url, kind="primary"))
    if buttons:
        elements.append(action(buttons))

    elements.append(note(footer or f"来源：{source or '未知公众号'} · 由 AI 从原文抽取，请以原文为准"))

    return card(template=template, title=f"{emoji} {_title_of(name)}", elements=elements)


def build_opportunity_cards(
    payload: dict[str, Any],
    *,
    source: str | None,
    url: str | None,
    stored: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """模块一：一篇文章可能抽出多条机会 → **每条一张卡**。"""
    cards: list[dict[str, Any]] = []
    for index, raw in enumerate(payload.get("items") or []):
        if not isinstance(raw, dict):
            continue
        item = payload_item_to_item(raw)
        footer = None
        if stored and index < len(stored) and stored[index].get("duplicate"):
            footer = "这条活动之前已收录过，来源已合并"
        built = build_opportunity_card(item, source=source, original_url=url, footer=footer)
        if built is not None:
            cards.append(built)
    return cards
