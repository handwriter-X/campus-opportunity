"""BFF 发的卡片。

**独立于 gateway**：BFF 可能部署在云上，不能 import 校内网那套代码。
版式上和 `gateway/app/card_kit.py` 保持一致（标题说清是什么 → 关键信息 → 一个主按钮 → 脚注）。

## 按钮走的是**回传**

`value` 里的 `action` / `invite_record_id` 必须和 gateway 的常量逐字一致：
`accept` / `decline`。点下去以后由 **gateway 的长连接**接住（同一个飞书应用）。
"""

from __future__ import annotations

from typing import Any

ACTION_ACCEPT = "accept"
ACTION_DECLINE = "decline"


def _div(content: str) -> dict[str, Any]:
    return {"tag": "div", "text": {"tag": "lark_md", "content": content}}


def _button(label: str, value: dict[str, Any], *, kind: str = "default") -> dict[str, Any]:
    return {
        "tag": "button",
        "text": {"tag": "plain_text", "content": label},
        "type": kind,
        "value": value,
    }


def build_apply_card(
    *,
    title: str,
    who: str,
    message: str,
    invite_record_id: str,
    campus: str = "",
    hours: str = "",
) -> dict[str, Any]:
    """给**发起人**：有人通过小程序申请加入。

    `message` 就是申请人在小程序里写的「想说的话」—— 这是这张卡的主角。
    """
    short_title = title if len(title) <= 18 else title[:17] + "…"
    elements: list[dict[str, Any]] = [
        _div(f"**{who}** 申请加入你的组队。"),
    ]

    facts = [x for x in (campus, hours) if x]
    if facts:
        elements.append(_div("　·　".join(facts)))

    if message:
        elements.append(_div(f"「{message}」"))
    else:
        elements.append(_div("（TA 没有留言）"))

    elements.append(_div("同意之后 TA 会收到通知；不点就不会打扰任何人。"))
    # ⚠️ `source: "apply"` 不能少 —— gateway 靠它判断**谁该按这个按钮**。
    # 没有它，gateway 会按"邀请"方向校验（要求按的人是**被邀请人**），
    # 而这张卡是发给**发起人**的 → 点了会被回一句"这条邀请不是发给你的"。
    elements.append({
        "tag": "action",
        "actions": [
            _button("同意 TA 加入",
                    {"action": ACTION_ACCEPT, "invite_record_id": invite_record_id,
                     "source": "apply"},
                    kind="primary"),
            _button("这次先不了",
                    {"action": ACTION_DECLINE, "invite_record_id": invite_record_id,
                     "source": "apply"}),
        ],
    })
    elements.append({"tag": "note", "elements": [
        {"tag": "plain_text", "content": "校园机会搭子 · 来自小程序里的申请"},
    ]})

    return {
        "config": {"wide_screen_mode": True},
        "header": {
            "template": "blue",
            "title": {"tag": "plain_text", "content": f"🤝 有人想加入「{short_title}」"},
        },
        "elements": elements,
    }
