"""组队匹配的两张飞书卡片。

## 为什么是两张不一样的卡

需求原文是「飞书提醒**双方**」，但两边的诉求完全不同：

- **卡片 A → 发起人**：AI 帮你找到了人，**你决定要不要邀请**。
  按钮只有「邀请 TA」——点了才会惊动对方。
- **卡片 B → 被邀请人**：有人想和你组队。**你决定接不接受**。
  按钮是「我想加入 / 这次先不了」。

## ⚠️ 按钮走的是**回传**（`value`），不是跳转（`url`）

`value` 里塞业务参数，飞书把点击回调到我们的长连接（已实测，见 S8）：
- 回调里带 `operator.open_id` → **点按钮的人是谁**，飞书给的，不能伪造
- 回调里带 `action.value` → 我们塞进去的参数
- 回调里带 `context.open_message_id` → 哪张卡，**可以原地更新它**

⇒ 用户在卡片上一下点完，不用跳多维表格。

## 一个刻意的措辞

卡片 A 的 note 写着「邀请前不会打扰对方」。这是**产品承诺**，
让发起人知道按钮的后果 —— 也是这套设计能减少骚扰的关键。

## 版式

见 `card_kit.py` 顶部的约定：**标题说清是什么 → 关键信息第一行 → 细节分行 → 一个主按钮 → 脚注免责**。
"""

from __future__ import annotations

import re
from typing import Any

from .card_kit import action, button, card, div, hr, note

# 卡片配色语义（飞书官方）：blue=通知 · green=成功 · orange=警告 · red=错误
TEMPLATE_MATCH = "green"
TEMPLATE_INVITE = "blue"
TEMPLATE_EMPTY = "grey"

# 回传参数里的动作名 —— 处理回调时按它分派
ACTION_INVITE = "invite"
ACTION_ACCEPT = "accept"
ACTION_DECLINE = "decline"

def split_reasons(text: str) -> list[str]:
    """把写回表里的「1. …\\n2. …」拆成逐条理由。

    GeniOS 的代码03 就是这么写的（`1. <理由>（<分数> 分）`）。
    拆不出来时**整体返回一条**，宁可啰嗦也别丢信息。
    """
    lines = [line.strip() for line in (text or "").splitlines() if line.strip()]
    chunks: list[str] = []
    for line in lines:
        if re.match(r"^\d+[.、]", line):
            chunks.append(re.sub(r"^\d+[.、]\s*", "", line))
        elif chunks:
            chunks[-1] += "\n" + line
        else:
            chunks.append(line)
    return chunks or ([text.strip()] if text and text.strip() else [])


def _text_of(value: Any) -> str:
    if isinstance(value, list):
        return "、".join(str(v) for v in value if v)
    if isinstance(value, str):
        return value.strip()
    return "" if value is None else str(value).strip()


def _profile_line(profile: dict[str, Any] | None) -> str:
    """候选人一句话画像：`大三 · 计算机学院 · 津南 · 每周 10-20h`。"""
    if not profile:
        return ""
    parts = []
    for key in ("年级", "学院"):
        value = _text_of(profile.get(key))
        if value:
            parts.append(value)
    for key, label in (("所在校区", ""), ("每周可投入", "每周")):
        value = _text_of(profile.get(key))
        if value:
            parts.append(f"{label} {value}".strip())
    return " · ".join(parts)


def _skills_line(profile: dict[str, Any] | None) -> str:
    skills = _text_of((profile or {}).get("技能标签"))
    return f"🛠 {skills}" if skills else ""


def _request_facts(request: dict[str, Any]) -> list[str]:
    """需求的关键维度，**一行一个**，缺的跳过。"""
    facts = []
    wants = _text_of(request.get("需要什么技能"))
    if wants:
        facts.append(f"🛠 **需要**　{wants}")
    campus = _text_of(request.get("所在校区"))
    if campus:
        facts.append(f"📍 **校区**　{campus}")
    hours = _text_of(request.get("期望每周投入"))
    if hours:
        facts.append(f"⏱ **每周投入**　{hours}")
    return facts


def build_match_card(
    *,
    request: dict[str, Any],
    candidates: list[dict[str, Any]],
    reason_text: str,
) -> dict[str, Any]:
    """卡片 A：给发起人，列出候选人，每人一个「邀请 TA」。

    `candidates` 每项形如 `{"open_id": "ou_…", "profile": {…}}`，**顺序即分数顺序**。
    """
    if not candidates:
        return build_no_match_card(request=request)

    reasons = split_reasons(reason_text)
    elements: list[dict[str, Any]] = []

    title = _text_of(request.get("需求标题")) or "你的组队需求"
    elements.append(
        div(f"为「**{title}**」匹配到下面几位。点「邀请 TA」之后，**对方才会收到通知**。")
    )
    elements.append(hr())

    for index, candidate in enumerate(candidates):
        open_id = candidate.get("open_id", "")
        profile = candidate.get("profile") or {}
        name = _text_of(profile.get("姓名")) or "这位同学"
        line = _profile_line(profile)
        skills = _skills_line(profile)
        reason = reasons[index] if index < len(reasons) else ""

        elements.append(div(f"**{index + 1}. {name}**" + (f"　·　{line}" if line else "")))
        if skills:
            elements.append(div(skills))
        if reason:
            elements.append(div(f"**为什么推荐**：{reason}"))
        elements.append(
            action([
                button(
                    f"邀请 {name}",
                    value={
                        "action": ACTION_INVITE,
                        "request_record_id": request.get("record_id", ""),
                        "candidate_open_id": open_id,
                        "candidate_index": index,
                    },
                    kind="primary",
                )
            ])
        )
        if index < len(candidates) - 1:
            elements.append(hr())

    elements.append(
        note("由 AI 根据你的需求与该同学的画像匹配 · 邀请前不会打扰对方")
    )

    return card(
        template=TEMPLATE_MATCH,
        title=f"🎯 为你找到 {len(candidates)} 位队友",
        elements=elements,
    )


def build_no_match_card(*, request: dict[str, Any]) -> dict[str, Any]:
    """一条都没匹配到。**如实告诉用户**，并且不硬凑。"""
    title = _text_of(request.get("需求标题")) or "你的组队需求"
    elements = [
        div(f"**{title}**"),
        div(
            "暂时没有匹配到合适的同学。常见原因是：**校区**或**每周投入**对不上，"
            "或者暂时还没有同学填写画像。"
        ),
        div("🔄 新同学填了画像之后，我们会重新为你匹配，不用再提交一次。"),
        note("由 AI 匹配 · 本次没有推荐任何人"),
    ]
    return card(template=TEMPLATE_EMPTY, title="本次暂未找到合适的队友", elements=elements)


def build_invite_card(
    *,
    invite: dict[str, Any],
    requester_name: str,
    request: dict[str, Any],
    reason: str,
) -> dict[str, Any]:
    """卡片 B：给被邀请人。**这时候才带发起人的信息**（因为是 TA 主动邀请的）。"""
    title = _text_of(request.get("需求标题")) or "组队需求"
    project = _text_of(request.get("项目类型"))
    goal = _text_of(request.get("预期目标"))

    elements: list[dict[str, Any]] = [
        div(f"**{title}**" + (f"　·　{project}" if project else "")),
    ]
    if goal:
        elements.append(div(f"🎯 **目标**　{goal}"))
    facts = _request_facts(request)
    if facts:
        elements.append(div("\n".join(facts)))

    if reason:
        elements.append(hr())
        elements.append(div(f"**TA 为什么邀请你**\n{reason}"))

    elements.append(div("感兴趣的话点下面的按钮，TA 会收到通知；不点就不会打扰任何人。"))
    elements.append(
        action([
            button(
                "我想加入",
                value={"action": ACTION_ACCEPT, "invite_record_id": invite.get("record_id", "")},
                kind="primary",
            ),
            button(
                "这次先不了",
                value={"action": ACTION_DECLINE, "invite_record_id": invite.get("record_id", "")},
            ),
        ])
    )
    elements.append(note("你可以随时忽略这条消息 · 不想再收到组队邀请请回复「关闭」"))

    short_title = title if len(title) <= 18 else title[:17] + "…"
    headline = f"🤝 {requester_name} 邀请你加入「{short_title}」"
    return card(template=TEMPLATE_INVITE, title=headline, elements=elements)
