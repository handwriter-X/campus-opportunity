"""把**所有飞书卡片 / 消息样式**一次性发给自己看。

## 为什么需要它

卡片的观感只能用眼睛验收 —— 跑真实链路要等文章、等匹配，太慢。
这个脚本用**假数据**把每一种版式都渲染一遍，一次点开就能看完。

## 用法

```bash
env -u ALL_PROXY -u all_proxy -u HTTPS_PROXY -u https_proxy \\
  .venv/bin/python scripts/preview_cards.py                 # 发到 FEISHU_NOTIFY_TARGET
... --target ou_xxx                                          # 发给别人
... --dry-run                                                # 只打印 JSON，不发
```

> ⚠️ 发的是**假数据**，别当成真通知。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "gateway"))

import httpx  # noqa: E402

from app.card_kit import (  # noqa: E402
    build_opportunity_card,
    build_opportunity_cards,
    payload_item_to_item,
)
from app.config import get_settings  # noqa: E402
from app.feishu_app import FeishuAppClient  # noqa: E402
from app.match_cards import (  # noqa: E402
    build_invite_card,
    build_match_card,
    build_no_match_card,
)
from app.richtext import markdown_to_post  # noqa: E402

REQUEST = {
    "record_id": "rec_DEMO",
    "需求标题": "CANN 大赛找队友",
    "项目类型": "竞赛",
    "预期目标": "冲进国赛，做一个人机交互的 demo",
    "需要什么技能": ["编程", "设计"],
    "所在校区": "津南",
    "期望每周投入": "10-20h",
}

PROFILES = [
    {"姓名": "李培涛", "年级": "大三", "学院": "计算机学院",
     "技能标签": ["编程", "数据分析"], "所在校区": "津南", "每周可投入": "10-20h"},
    {"姓名": "王小明", "年级": "大二", "学院": "软件学院",
     "技能标签": ["设计", "演讲"], "所在校区": "八里台", "每周可投入": "5-10h"},
]

REASONS = (
    "1. TA 的编程和数据分析正好补上你缺的后端能力（92 分）\n"
    "2. 同一校区，线下约讨论方便（86 分）"
)

OPPORTUNITIES = {
    "is_opportunity": True,
    "items": [
        {
            "name": "南开大学第十六届程序设计竞赛",
            "type": "竞赛",
            "summary": "面向全校本科生的个人赛，分设一二三等奖，优胜者进入校队。",
            "event_time_text": "11月2日 9:00-14:00",
            "signup_deadline": "2026-10-25T23:59:59+08:00",
            "location": "计算机学院 A305",
            "audience": "全校本科生",
            "quota": "一等奖 5 名",
            "signup_url": "https://example.nankai.edu.cn/cpc-signup",
        },
        {
            "name": "数学建模竞赛校内选拔赛",
            "type": "竞赛",
            "summary": "校内选拔，为参加全国大学生数学建模竞赛组队。",
            "signup_deadline": "2026-10-20T23:59:59+08:00",
            "audience": "全校本科生",
            "low_confidence": True,
            "confidence": 0.55,
        },
    ],
}


def build_all() -> list[tuple[str, dict]]:
    opportunity_cards = build_opportunity_cards(
        OPPORTUNITIES, source="南开大学创新创业学院", url="https://mp.weixin.qq.com/s/demo"
    )
    cards = [
        (f"① 机会推送（第 {i + 1} 张）", c) for i, c in enumerate(opportunity_cards)
    ] + [
        ("② 匹配结果（卡片 A）", build_match_card(
            request=REQUEST,
            candidates=[{"open_id": f"ou_{i}", "profile": p} for i, p in enumerate(PROFILES)],
            reason_text=REASONS)),
        ("③ 邀请（卡片 B）", build_invite_card(
            invite={"record_id": "rec_INV"},
            requester_name="谢国辉",
            request=REQUEST,
            reason="你会 Figma，正是 TA 缺的设计；而且你们都在津南，线下讨论方便。")),
        ("④ 没有匹配到", build_no_match_card(request=REQUEST)),
        # 对话推荐机会时补发的那张（同一套版式，脚注不同）
        ("⑤ 对话推荐卡片", build_opportunity_card(
            payload_item_to_item(OPPORTUNITIES["items"][0]),
            footer="由 AI 从机会库挑出 · 详情以原文为准")),
    ]
    return [(name, c) for name, c in cards if c is not None]


CHAT_SAMPLE = """好的，给你挑了三个**适合你**的：

- **智能体应用创新大赛** — 你的编程和设计都能用上，10月30日截止
- **第十六届程序设计竞赛** — 就在津南，10月25日截止
- **数学建模校内选拔赛** — 数据分析对口，可以跨学院组队

想报哪个的话，我可以把[报名入口](https://jwc.nankai.edu.cn)发你。"""


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--target", default="", help="默认 FEISHU_NOTIFY_TARGET")
    parser.add_argument("--dry-run", action="store_true", help="只打印 JSON，不发")
    args = parser.parse_args()

    items = build_all()
    if args.dry_run:
        for name, card in items:
            print("=" * 60 + f"\n{name}\n" + "=" * 60)
            print(json.dumps(card, ensure_ascii=False, indent=2))
        print("=" * 60 + "\n⑦ 聊天回复（富文本）\n" + "=" * 60)
        print(json.dumps(markdown_to_post(CHAT_SAMPLE), ensure_ascii=False, indent=2))
        return 0

    settings = get_settings()
    target = args.target or settings.feishu_notify_target
    if not target:
        print("❌ 没有推送目标（传 --target 或配 FEISHU_NOTIFY_TARGET）")
        return 1

    async with httpx.AsyncClient(timeout=30.0) as http:
        app = FeishuAppClient(settings, http)
        for name, card in items:
            await app.send_card(card, target=target)
            print(f"✅ {name}")
            await asyncio.sleep(0.4)
        await app.send_post(markdown_to_post(CHAT_SAMPLE), target=target)
        print("✅ ⑦ 聊天回复（富文本）")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
