"""授权自检 —— 答辩前跑一次，看三个智能体的插件授权还活着没有。

## 它验的是什么

**不是** gateway 的凭据（那个用应用身份、自动刷新、不会过期）。
验的是 **GeniOS 工作流里「飞书多维表格插件」的用户级 OAuth 授权** ——
它**约 2 小时**过期，而且**每个智能体各有一份**。

## 用法

```bash
# 跑一次，看三个智能体谁是绿的
env -u ALL_PROXY -u all_proxy -u HTTPS_PROXY -u https_proxy \\
  .venv/bin/python scripts/check_auth.py

# 每 10 分钟跑一次，记录状态变化 —— 用来**精确测出过期间隔**
env -u ALL_PROXY -u all_proxy -u HTTPS_PROXY -u https_proxy \\
  .venv/bin/python scripts/check_auth.py --loop 600
```

状态会同时追加到 `data/auth_checks.jsonl`，跑一段时间后
`scripts/check_auth.py --report` 就能算出「平均多久过期一次」。

## ⚠️ 它会真的调一次 GeniOS

- 模块一 / 模块二：**会跑一次工作流**（消耗少量 token）
- 对话：问一句"你好"

所以**别高频跑**（loop 间隔建议 ≥ 5 分钟）。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "gateway"))

import httpx  # noqa: E402

from app.config import MatchGeniosProfile, get_settings  # noqa: E402
from app.genios_chat import GeniosChatClient  # noqa: E402
from app.genios_client import GeniosClient  # noqa: E402

LOG = REPO_ROOT / "data" / "auth_checks.jsonl"

# 授权失败的几种长相（实测都见过）
AUTH_MARKERS = ("authen/v1/authorize", "需要授权", "91403", "99991663")


def _auth_link(text: str) -> str | None:
    """从报错里抠出重授权链接。

    ⚠️ **必须停在这些字符**：平台的 msg 是 `请点击[这里](https://…&state=xxx)进行授权`，
    `\\S+` 会把 `)进行授权` 一起吃进去，导致用户点开永远 `state expired`。
    """
    import re

    match = re.search(
        r"https://accounts\.feishu\.cn/open-apis/authen/v1/authorize[^\s)\]\"'<>]+",
        text or "",
    )
    return match.group(0) if match else None


def _looks_like_auth(text: str) -> bool:
    return any(marker in (text or "") for marker in AUTH_MARKERS)


async def check_extract(settings, http: httpx.AsyncClient) -> dict:
    """模块一 · 机会抽取 —— **不需要授权**。

    它的工作流只有 `Start / End / LLM / Code`，**没有任何插件节点**
    （`genios/workflows/campus_opportunity_extract.import.json` 里可以核实），
    所以永远不会遇到插件 OAuth 的问题。这里直接返回 ✅，不浪费一次调用。
    """
    return {"ok": True, "error": "", "link": None, "note": "无插件节点，无需授权"}


async def check_match(settings, http: httpx.AsyncClient) -> dict:
    """模块二 · 组队匹配（用 MatchGeniosProfile）

    刻意留空 `request_record_id` —— 代码03 会报"没给 record_id"，
    但**插件读画像那一步仍然会跑**，正好用来验授权。
    """
    client = GeniosClient(MatchGeniosProfile(settings), http)
    result = await client.dispatch({
        "match_id": "auth-check",
        "request_json": json.dumps({
            "title": "鉴权自检", "skills_needed": ["编程"], "campus": "津南",
            "owner_profile": {"skills": ["编程"]},
        }, ensure_ascii=False),
        "candidates_json": "",
        "request_record_id": "",
        "top_n": "1",
        "min_score": "70",
    })
    err = (result.error or "") if not result.ok else ""
    return {"ok": result.ok or not _looks_like_auth(err), "error": err,
            "link": _auth_link(err)}


async def check_chat(settings, http: httpx.AsyncClient) -> dict:
    """对话流（用 GeniosChatClient）

    ⚠️ **必须问一句会触发插件读表的话。**
    第一版问的是"你好" —— 那会走【其他】分支，**一张表都不读**，
    于是授权过期了它也照样绿（**假绿**，实测踩过）。
    这里问「有哪些适合我的比赛」，必走【查机会】分支。
    """
    client = GeniosChatClient(settings, http)
    # ⚠️ **必须和生产用同一个 userID**（`genios_chat_user_id`）。
    # 插件 OAuth 是按 userID 绑定的 —— 用一个"测试专用 id"去自检，
    # 结果是**自检绿了、线上红**（实测踩过，2026-10-17）。
    uid = settings.genios_chat_user_id or settings.genios_user_id
    try:
        conv = await client.create_conversation(uid)
        reply = await client.chat(uid, conv, "有哪些适合我的比赛")
    except Exception as exc:  # noqa: BLE001
        text = str(exc)
        return {"ok": not _looks_like_auth(text), "error": text,
                "link": _auth_link(text)}
    return {"ok": not _looks_like_auth(reply), "error": "", "link": _auth_link(reply)}


async def run_once() -> dict:
    settings = get_settings()
    async with httpx.AsyncClient(timeout=180) as http:
        results = {}
        for name, fn in (("模块一·机会抽取", check_extract),
                         ("模块二·组队匹配", check_match),
                         ("对话流", check_chat)):
            try:
                results[name] = await fn(settings, http)
            except Exception as exc:  # noqa: BLE001
                results[name] = {"ok": False, "error": f"{type(exc).__name__}: {exc}",
                                 "link": None}
    return results


def print_report(results: dict) -> None:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"\n授权自检 · {now}\n" + "=" * 60)
    links = []
    for name, info in results.items():
        mark = "✅ 正常" if info.get("ok") else "❌ 需要授权"
        print(f"  {name:16} {mark}")
        if info.get("link"):
            links.append((name, info["link"]))
        elif not info.get("ok") and info.get("error"):
            print(f"       {info['error'][:110]}")
    if links:
        print("\n需要重新授权的链接（**整条复制粘贴到浏览器**）：")
        for name, link in links:
            print(f"\n【{name}】\n{link}")
    print("=" * 60 + "\n")


def append_log(results: dict) -> None:
    LOG.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "at": datetime.now().isoformat(timespec="seconds"),
        "epoch": int(time.time()),
        "results": {k: bool(v.get("ok")) for k, v in results.items()},
    }
    with LOG.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")


def report_ttl() -> None:
    """从历史记录里算：每个智能体最后一次绿 → 第一次红，间隔多久。"""
    if not LOG.exists():
        print(f"还没有历史记录（{LOG}）—— 先跑几次 `--loop` 再来。")
        return
    rows = [json.loads(line) for line in LOG.read_text(encoding="utf-8").splitlines() if line.strip()]
    print(f"\n共 {len(rows)} 次检查\n" + "=" * 60)
    for name in rows[0]["results"]:
        dies = []
        last_ok = None
        for row in rows:
            ok = row["results"].get(name)
            if ok:
                last_ok = row
            elif last_ok and not dies:
                dies.append((last_ok["at"], row["at"]))
                last_ok = None
        print(f"  {name:16} 记录到 {len(dies)} 次「由绿变红」")
        for a, b in dies:
            from datetime import datetime as dt
            span = (dt.fromisoformat(b) - dt.fromisoformat(a)).total_seconds() / 3600
            print(f"       {a} → {b}   （约 {span:.1f} 小时）")
    print("=" * 60 + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description="GeniOS 智能体插件授权自检")
    parser.add_argument("--loop", type=int, default=0,
                        help="每隔多少秒跑一次（0=只跑一次），建议 ≥300")
    parser.add_argument("--report", action="store_true", help="从历史记录算过期间隔")
    args = parser.parse_args()

    if args.report:
        report_ttl()
        return 0

    if args.loop <= 0:
        results = asyncio.run(run_once())
        print_report(results)
        append_log(results)
        bad = [n for n, v in results.items() if not v.get("ok")]
        return 0 if not bad else 1

    print(f"每 {args.loop} 秒自检一次，Ctrl-C 退出。记录：{LOG}")
    try:
        while True:
            results = asyncio.run(run_once())
            print_report(results)
            append_log(results)
            time.sleep(args.loop)
    except KeyboardInterrupt:
        print("\n停止。跑 `--report` 看统计。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
