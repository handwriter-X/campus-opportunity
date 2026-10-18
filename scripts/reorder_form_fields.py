"""调整飞书表单的**题目顺序**。

## 为什么用脚本而不是手动拖

顺序是**设计决定**，要能重复、能进 git、能解释为什么这么排。
手动拖一次就没痕迹了，下次换个人还得猜。

## 飞书的机制

```
PATCH /bitable/v1/apps/{app_token}/tables/{table_id}/forms/{form_id}/fields/{field_id}
{"pre_field_id": "<前一道题的 field_id>"}      # 空串 = 排到第一位
```

⇒ 按**目标顺序**逐个调用，每次把当前题放到"上一题"后面。
前一道已经在位了，所以一遍就收敛。

> ⚠️ `visible: false` 的题目**不允许更新** —— 隐藏题不参与排序，跳过。

## 用法

```bash
env -u ALL_PROXY -u all_proxy -u HTTPS_PROXY -u https_proxy \\
  .venv/bin/python scripts/reorder_form_fields.py          # 执行
... --check                                                # 只看现状
```

## 排序的依据（改之前先读这段）

| 原则 | 为什么 |
| --- | --- |
| **身份题永远第一** | 预填好了，一点就过；也是后面所有关联的锚 |
| **必填全部排在选填前面** | 填写疲劳只该出现在最后一题 |
| **长文本永远最后** | 打字最费劲，放前面会劝退 |
| **硬筛维度相邻** | 校区 + 每周投入是匹配的两把硬尺子，挨着问更连贯 |
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "gateway"))

import httpx  # noqa: E402

from app.bitable import FEISHU_BASE  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.feishu_app import FeishuAppClient  # noqa: E402


# ============================================================
# 目标顺序
# ============================================================

PROFILE_ORDER = [
    "飞书账号",      # 必 · 身份（预填）
    "姓名",          # 必 · 身份（预填）—— 两道身份题挨着，确认一下就是你
    "技能标签",      # 必 · 匹配的主维度，也是最有表达欲的一题
    "所在校区",      # 必 · 硬筛
    "每周可投入",    # 必 · 硬筛
    "年级",          # 选
    "学院",          # 选
    "过往经历",      # 选 · 长文本，最后
]

REQUEST_ORDER = [
    "发起人",        # 必 · 身份（预填）
    "需求标题",      # 必 · 整个匹配的主输入，必须靠前
    "项目类型",      # 必 · 一拍即合的单选题
    "需要什么技能",  # 必 · 硬筛
    "所在校区",      # 必 · 硬筛
    "期望每周投入",  # 必 · 硬筛
    "预期目标",      # 选 · 长文本，最后
]


async def _list_fields(http, token, app_token, table_id, form_id) -> list[dict]:
    url = f"{FEISHU_BASE}/bitable/v1/apps/{app_token}/tables/{table_id}/forms/{form_id}/fields"
    all_items: list[dict] = []
    page_token = ""
    while True:
        params = {"page_size": 100}
        if page_token:
            params["page_token"] = page_token
        response = await http.get(url, params=params,
                                  headers={"Authorization": f"Bearer {token}"})
        data = response.json()
        if data.get("code") != 0:
            raise SystemExit(f"读表单题目失败：{data.get('code')} {data.get('msg')}")
        payload = data.get("data") or {}
        all_items.extend(payload.get("items") or [])
        if not payload.get("has_more"):
            return all_items
        page_token = payload.get("page_token") or ""


async def reorder(http, token, app_token, table_id, form_id, order, *, check_only=False):
    items = await _list_fields(http, token, app_token, table_id, form_id)
    visible = [f for f in items if f.get("visible", True)]
    by_title = {f["title"]: f for f in visible}

    print("\n  现状：")
    for i, f in enumerate(visible):
        print(f"    {i + 1}. {f['title']}")

    missing = [t for t in order if t not in by_title]
    if missing:
        raise SystemExit(f"❌ 表单里找不到这些题：{missing}")
    extra = [f["title"] for f in visible if f["title"] not in order]
    if extra:
        print(f"  ⚠️ 这些题不在排序表里，保持在原位：{extra}")

    if check_only:
        return

    prev = ""
    for title in order:
        field_id = by_title[title]["field_id"]
        response = await http.patch(
            f"{FEISHU_BASE}/bitable/v1/apps/{app_token}/tables/{table_id}"
            f"/forms/{form_id}/fields/{field_id}",
            headers={"Authorization": f"Bearer {token}"},
            json={"pre_field_id": prev},
        )
        data = response.json()
        if data.get("code") != 0:
            raise SystemExit(f"❌ 调整「{title}」失败：{data.get('code')} {data.get('msg')}")
        prev = field_id

    items = await _list_fields(http, token, app_token, table_id, form_id)
    visible = [f for f in items if f.get("visible", True)]
    print("\n  调整后：")
    for i, f in enumerate(visible):
        mark = "✓" if i < len(order) and f["title"] == order[i] else " "
        print(f"    {mark} {i + 1}. {f['title']}")


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="只看现状，不改")
    args = parser.parse_args()

    settings = get_settings()
    if not settings.bitable_profile_form_id or not settings.bitable_request_form_id:
        print("❌ 没配表单 id（BITABLE_PROFILE_FORM_ID / BITABLE_REQUEST_FORM_ID）")
        return 1

    async with httpx.AsyncClient(timeout=30.0) as http:
        app = FeishuAppClient(settings, http)
        token = await app.tenant_token()

        print("=" * 60 + "\n【队友画像建档】\n" + "=" * 60)
        await reorder(http, token, settings.bitable_app_token,
                      settings.bitable_profile_table_id,
                      settings.bitable_profile_form_id, PROFILE_ORDER,
                      check_only=args.check)

        print("\n" + "=" * 60 + "\n【发布组队需求】\n" + "=" * 60)
        await reorder(http, token, settings.bitable_app_token,
                      settings.bitable_request_table_id,
                      settings.bitable_request_form_id, REQUEST_ORDER,
                      check_only=args.check)
    return 0


if __name__ == "__main__":
    os.environ.setdefault("PYTHONUTF8", "1")
    raise SystemExit(asyncio.run(main()))
