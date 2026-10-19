"""BFF 发的卡片（JSON 2.0）。

**独立于 gateway**：BFF 可能部署在云上，不能 import 校内网那套代码。
版式与 `gateway/app/card_kit.py` 保持一致：

```
header   主体 + 副标题 + 类型标签
  ↓
申请人   头像胶囊
  ↓
留言     「想说的话」—— 这张卡的主角
  ↓
按钮     同意 / 这次先不了
  ↓
脚注     来源
```

## 按钮走的是**回传**

`value` 里的 `action` / `invite_record_id` / `source` 必须和 gateway 的常量逐字一致：
`accept` / `decline` / `apply`。点下去以后由 **gateway 的长连接**接住（同一个飞书应用）。
"""

from __future__ import annotations

from typing import Any

ACTION_ACCEPT = "accept"
ACTION_DECLINE = "decline"

BRAND_TEMPLATE = "purple"


def _md(content: str) -> dict[str, Any]:
    return {"tag": "markdown", "content": content}


def _tag(text: str, color: str = "neutral") -> str:
    return f"<text_tag color='{color}'>{text}</text_tag>"


def _person(open_id: str) -> dict[str, Any]:
    return {
        "tag": "person",
        "user_id": open_id,
        "size": "small",
        "show_avatar": True,
        "show_name": True,
        "style": "capsule",
    }


def _button(label: str, value: dict[str, Any], *, kind: str = "default") -> dict[str, Any]:
    return {
        "tag": "button",
        "text": {"tag": "plain_text", "content": label},
        "type": kind,
        "behaviors": [{"type": "callback", "value": value}],
    }


def build_apply_card(
    *,
    title: str,
    who: str,
    message: str,
    invite_record_id: str,
    campus: str = "",
    hours: str = "",
    applicant_open_id: str = "",
) -> dict[str, Any]:
    """给**发起人**：有人通过小程序申请加入。"""
    short_title = title if len(title) <= 18 else title[:17] + "…"

    elements: list[dict[str, Any]] = []
    if applicant_open_id:
        elements.append(_person(applicant_open_id))
    else:
        elements.append(_md(f"**{who}**"))

    facts = [x for x in (campus and _tag(f"📍 {campus}", "wathet"),
                         hours and _tag(f"⏱ 每周 {hours}", "lime")) if x]
    if facts:
        elements.append(_md("　".join(facts)))

    if message:
        elements.append(_md(f"「{message}」"))
    else:
        elements.append(_md("<font color='grey'>（TA 没有留言）</font>"))

    elements.append(_md("同意之后 TA 会收到通知；不点就不会打扰任何人。"))

    # ⚠️ `source: "apply"` 不能少 —— gateway 靠它判断**谁该按这个按钮**。
    # 没有它，gateway 会按"邀请"方向校验（要求按的人是**被邀请人**），
    # 而这张卡是发给**发起人**的 → 点了会被回一句"这条邀请不是发给你的"。
    elements.append(_button(
        "同意 TA 加入",
        {"action": ACTION_ACCEPT, "invite_record_id": invite_record_id, "source": "apply"},
        kind="primary",
    ))
    elements.append(_button(
        "这次先不了",
        {"action": ACTION_DECLINE, "invite_record_id": invite_record_id, "source": "apply"},
    ))
    elements.append({"tag": "div", "text": {"tag": "plain_text",
                     "content": "校园机会搭子 · 来自小程序里的申请"}, "text_size": "notation"})

    return {
        "schema": "2.0",
        "config": {"wide_screen_mode": True},
        "header": {
            "template": BRAND_TEMPLATE,
            "title": {"tag": "plain_text", "content": f"🤝 有人想加入「{short_title}」"},
            "subtitle": {"tag": "plain_text", "content": "来自小程序里的申请"},
            "text_tag_list": [{
                "tag": "text_tag",
                "text": {"tag": "plain_text", "content": "申请"},
                "color": "blue",
            }],
        },
        "body": {"elements": elements},
    }
