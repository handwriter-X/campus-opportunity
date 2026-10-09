#!/usr/bin/env python
"""探针 S4：飞书群自定义机器人。

发三条消息，验证：能不能发、卡片长什么样、签名对不对、告警 Webhook 是否独立可用。

用法：
    python scripts/probe_feishu_webhook.py --text      # 纯文本
    python scripts/probe_feishu_webhook.py --card      # 机会卡片（阶段 4 的版式预览）
    python scripts/probe_feishu_webhook.py --card --variant weekly
    python scripts/probe_feishu_webhook.py --alert     # 运维告警 Webhook（另一个群）
    python scripts/probe_feishu_webhook.py --all
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

import httpx

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "gateway"))

from app.config import get_settings  # noqa: E402
from app.push import FeishuError, FeishuWebhook, RateLimiter, text_card  # noqa: E402

TYPE_EMOJI = {
    "竞赛": "🏆",
    "学术与学习交流": "🎓",
    "志愿活动与社会实践": "🤝",
    "校园文体活动": "🎭",
}


def instant_card(opportunity: dict[str, Any]) -> dict[str, Any]:
    """即时推送卡片（阶段 4 的 `genios/feishu_cards/instant.json` 预览版）。"""
    emoji = TYPE_EMOJI.get(opportunity.get("type", ""), "📌")
    lines = [f"**{opportunity['name']}**", f"{emoji} {opportunity.get('type', '未分类')}"]

    if opportunity.get("event_time"):
        lines.append(f"🕐 活动时间：{opportunity['event_time']}")
    if opportunity.get("signup_deadline"):
        lines.append(f"⏰ **报名截止：{opportunity['signup_deadline']}**")
    if opportunity.get("signup_start"):
        lines.append(f"🚀 报名开始：{opportunity['signup_start']}")
    if opportunity.get("quota"):
        lines.append(f"👥 名额：{opportunity['quota']}")
    if opportunity.get("location"):
        lines.append(f"📍 地点：{opportunity['location']}")
    if opportunity.get("audience"):
        lines.append(f"🎯 参与对象：{opportunity['audience']}")

    elements: list[dict[str, Any]] = [
        {"tag": "div", "text": {"tag": "lark_md", "content": "\n".join(lines)}}
    ]

    buttons = []
    if opportunity.get("signup_url"):
        buttons.append(
            {
                "tag": "button",
                "text": {"tag": "plain_text", "content": "立即报名"},
                "type": "primary",
                "url": opportunity["signup_url"],
            }
        )
    if opportunity.get("source_url"):
        buttons.append(
            {
                "tag": "button",
                "text": {"tag": "plain_text", "content": "查看原文"},
                "type": "default",
                "url": opportunity["source_url"],
            }
        )
    if buttons:
        elements.append({"tag": "action", "actions": buttons})

    elements.append(
        {
            "tag": "note",
            "elements": [
                {"tag": "plain_text", "content": "信息由 AI 从公众号原文抽取，请以原文为准"}
            ],
        }
    )

    return {
        "config": {"wide_screen_mode": True},
        "header": {
            "template": "turquoise",
            "title": {"tag": "plain_text", "content": "校园机会 · 新发现"},
        },
        "elements": elements,
    }


def weekly_card(opportunities: list[dict[str, Any]]) -> dict[str, Any]:
    """周报卡片（阶段 4 的 `genios/feishu_cards/weekly.json` 预览版）。"""
    elements: list[dict[str, Any]] = []
    for index, item in enumerate(opportunities):
        if index:
            elements.append({"tag": "hr"})
        emoji = TYPE_EMOJI.get(item.get("type", ""), "📌")
        body = [f"**{item['name']}** {emoji}", item.get("summary", "")]
        if item.get("signup_deadline"):
            body.append(f"⏰ 截止 {item['signup_deadline']}")
        elements.append(
            {
                "tag": "div",
                "text": {"tag": "lark_md", "content": "\n".join(line for line in body if line)},
            }
        )
    if not elements:
        elements.append({"tag": "div", "text": {"tag": "lark_md", "content": "本周暂无新机会"}})

    return {
        "config": {"wide_screen_mode": True},
        "header": {
            "template": "blue",
            "title": {"tag": "plain_text", "content": "本周校园机会汇总"},
        },
        "elements": elements,
    }


SAMPLE_INSTANT = {
    "name": "南开大学第十五届程序设计竞赛",
    "type": "竞赛",
    "event_time": "11月2日（星期日）9:00-14:00",
    "signup_start": "10月8日 09:00",
    "signup_deadline": "10月20日 17:00",
    "quota": "不限",
    "location": "计算机学院 A305",
    "audience": "全校本科生",
    "signup_url": "https://example.nankai.edu.cn/signup",
    "source_url": "https://mp.weixin.qq.com/s/sample",
}

SAMPLE_WEEKLY = [
    {
        "name": "数学建模校内选拔赛",
        "type": "竞赛",
        "summary": "面向全校选拔参加全国大学生数学建模竞赛的队伍",
        "signup_deadline": "10月15日 24:00",
    },
    {
        "name": "王教授学术讲座《人工智能前沿》",
        "type": "学术与学习交流",
        "summary": "介绍大模型时代的研究范式变化",
        "signup_deadline": "无需报名",
    },
    {
        "name": "校运动会志愿者招募",
        "type": "志愿活动与社会实践",
        "summary": "需要 20 名志愿者，服务时长计入志愿时长",
        "signup_deadline": "10月12日",
    },
]


async def main_async(args: argparse.Namespace) -> int:
    settings = get_settings()

    targets: list[tuple[str, str, str]] = []
    if args.url:
        targets.append(("自定义", args.url, args.secret or ""))
    else:
        if args.alert:
            targets.append(
                ("告警群", settings.feishu_alert_webhook_url, settings.feishu_alert_webhook_secret)
            )
        else:
            targets.append(
                (
                    "机会群",
                    settings.feishu_opportunity_webhook_url,
                    settings.feishu_opportunity_webhook_secret,
                )
            )

    for label, url, secret in targets:
        if not url:
            print(f"❌ {label}的 Webhook URL 未配置。请填 .env 后重跑。")
            return 2
        print(f"\n{'=' * 70}\n{label}：{url[:60]}…\n{'=' * 70}")
        print(f"  签名校验：{'已启用' if secret else '未启用'}")

        webhook = FeishuWebhook(url, secret, httpx.AsyncClient(), RateLimiter(30))

        if args.text or args.all:
            await send(webhook, "文本", {"msg_type": "text", "content": {"text": "校园机会 · 探针 S4 文本消息 ✅"}})
        if args.alert and not args.text and not args.card:
            await send(
                webhook,
                "告警卡片",
                None,
                card=text_card(
                    "采集端疑似失效",
                    ["已 **200 分钟**未收到任何 `/ingest`", "请检查 We-MP-RSS 授权是否过期"],
                ),
            )
        if args.card or args.all:
            variant = args.variant
            card = instant_card(SAMPLE_INSTANT) if variant == "instant" else weekly_card(SAMPLE_WEEKLY)
            await send(webhook, f"{variant} 卡片", None, card=card)

    return 0


async def send(
    webhook: FeishuWebhook, label: str, payload: dict | None, card: dict | None = None
) -> None:
    try:
        if card is not None:
            result = await webhook.send_card(card)
        else:
            result = await webhook.send(payload or {})
    except FeishuError as exc:
        print(f"  ❌ {label} 发送失败：{exc}")
        print("     常见原因：安全设置的关键词不匹配、签名密钥不对、被频控。")
        return
    print(f"  ✅ {label} 已发送：{json.dumps(result, ensure_ascii=False)[:200]}")

    if card is not None:
        print("     卡片 JSON（可复制进 genios/feishu_cards/）：")
        print("     " + json.dumps(card, ensure_ascii=False, indent=2).replace("\n", "\n     ")[:1500])


def main() -> int:
    parser = argparse.ArgumentParser(description="探针 S4：飞书 Webhook")
    parser.add_argument("--text", action="store_true", help="发一条文本")
    parser.add_argument("--card", action="store_true", help="发机会卡片")
    parser.add_argument("--variant", choices=["instant", "weekly"], default="instant")
    parser.add_argument("--alert", action="store_true", help="用告警 Webhook 发告警卡片")
    parser.add_argument("--all", action="store_true", help="文本 + 卡片都发")
    parser.add_argument("--url", help="临时指定 Webhook（覆盖 .env）")
    parser.add_argument("--secret", help="配合 --url 的签名密钥")
    args = parser.parse_args()

    if not any([args.text, args.card, args.alert, args.all]):
        parser.print_help()
        print("\n提示：先用 --text 确认能发出去，再用 --card 看版式。")
        return 1

    return asyncio.run(main_async(args))


if __name__ == "__main__":
    raise SystemExit(main())
