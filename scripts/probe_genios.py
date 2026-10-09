#!/usr/bin/env python
"""探针 S1：摸清 GeniOS 流程编排型智能体的调用方式。

Q1 还没关闭 —— 平台文档在南开飞书知识库内、需登录，没有公开页面。所以这个脚本**不猜格式**，
而是给你几种「试探」手段，把真实请求/响应打出来：

  1. 按 .env 里的 GENIOS_* 组装并发送（`--dry-run` 先看要发什么）
  2. 直接指定 URL / 请求头 / 请求体，绕过配置试结构
  3. 把文档里的 curl 示例整段粘进来重放（`--curl`）—— 有文档时最省事

用法：
    python scripts/probe_genios.py --dry-run
    python scripts/probe_genios.py
    python scripts/probe_genios.py --url https://... --header "Authorization: Bearer xxx" \
        --body '{"input":"hi"}'
    python scripts/probe_genios.py --curl 'curl -X POST https://... -H "Authorization: Bearer xxx" \
        -H "Content-Type: application/json" -d "{\"input\":\"hi\"}"'

拿到结果后，请把**完整响应**贴回，并写进 docs/findings.md 的 Q1。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import shlex
import sys
from pathlib import Path
from typing import Any

import httpx

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "gateway"))

from app.config import get_settings  # noqa: E402
from app.genios_client import GeniosClient  # noqa: E402

SAMPLE_PAYLOAD = {
    "article_id": "0" * 64,
    "mode": "live",
    "source": "探针测试号",
    "title": "探针 S1 测试文章",
    "url": "https://mp.weixin.qq.com/s/probe-s1",
    "publish_time": "2026-10-04T09:30:00+08:00",
    "publish_weekday": "星期日",
    "text": "这是一篇用于探针 S1 的测试正文。报名截止时间：2026年10月20日。",
    "links": ["https://example.nankai.edu.cn/signup"],
}


def parse_curl(command: str) -> tuple[str, str, dict[str, str], str | None]:
    """解析 curl 命令的一个常用子集：-X/--request、-H/--header、-d/--data/--data-raw。

    只覆盖文档里常见的写法。解析失败会明确报错，而不是悄悄发一个错的请求。
    """
    try:
        tokens = shlex.split(command)
    except ValueError as exc:
        raise SystemExit(f"curl 命令无法解析（引号不匹配？）：{exc}") from exc

    if not tokens or tokens[0] != "curl":
        raise SystemExit("--curl 需要以 `curl` 开头")

    method: str | None = None
    headers: dict[str, str] = {}
    data: str | None = None
    url: str | None = None

    index = 1
    while index < len(tokens):
        token = tokens[index]
        if token in ("-X", "--request"):
            method = tokens[index + 1]
            index += 2
        elif token in ("-H", "--header"):
            raw = tokens[index + 1]
            if ":" not in raw:
                raise SystemExit(f"请求头缺少冒号：{raw!r}")
            name, _, value = raw.partition(":")
            headers[name.strip()] = value.strip()
            index += 2
        elif token in ("-d", "--data", "--data-raw", "--data-binary"):
            data = tokens[index + 1]
            index += 2
        elif token.startswith("-"):
            index += 1  # 忽略我们看不懂的开关
        else:
            url = token
            index += 1

    if not url:
        raise SystemExit("curl 命令里没找到 URL")
    if data and method is None:
        method = "POST"
    return (method or "GET"), url, headers, data


async def send_once(
    method: str, url: str, headers: dict[str, str], body: str | None, timeout: float
) -> None:
    print(f"\n→ {method} {url}")
    print("  headers: " + json.dumps(_mask(headers), ensure_ascii=False))
    if body:
        print("  body:    " + (body if len(body) < 2000 else body[:2000] + " …(截断)"))

    async with httpx.AsyncClient(follow_redirects=True) as client:
        try:
            response = await client.request(
                method,
                url,
                headers=headers,
                content=body.encode("utf-8") if body else None,
                timeout=timeout,
            )
        except httpx.HTTPError as exc:
            print(f"\n❌ 请求失败：{type(exc).__name__}: {exc}")
            print("   若为超时/连接失败，请确认网络能否访问 GeniOS（探针 S5）。")
            return

    print(f"\n← HTTP {response.status_code}")
    print("  response headers: " + json.dumps(dict(response.headers), ensure_ascii=False))
    text = response.text
    print("  response body:")
    try:
        print(json.dumps(response.json(), ensure_ascii=False, indent=2))
    except ValueError:
        print("  " + (text if len(text) < 4000 else text[:4000] + " …(截断)"))

    print("\n" + "─" * 70)
    print("请把上面的 **URL / 请求头 / 请求体 / 响应** 贴回给 Claude Code，用于关闭 Q1。")
    if response.status_code < 400:
        print("若响应里出现了任务 ID / conversation_id 之类的字段，请特别标注 —— 那是异步结果的钥匙。")


def _mask(headers: dict[str, str]) -> dict[str, str]:
    """打印时给密钥打码。日志里出现密钥是铁律 1 明令禁止的。"""
    masked = {}
    for name, value in headers.items():
        lowered = name.lower()
        if lowered in ("authorization", "x-api-key", "apikey", "api-key", "token") or "secret" in lowered:
            masked[name] = value[:12] + "…(已打码)" if len(value) > 12 else "…(已打码)"
        else:
            masked[name] = value
    return masked


def main() -> int:
    parser = argparse.ArgumentParser(description="探针 S1：GeniOS API")
    parser.add_argument("--dry-run", action="store_true", help="只打印将要发送的内容，不发请求")
    parser.add_argument("--url", help="直接指定 URL（覆盖 .env）")
    parser.add_argument("--method", default="POST", help="HTTP 方法，默认 POST")
    parser.add_argument("--header", action="append", default=[], help='形如 "Name: value"，可重复')
    parser.add_argument("--body", help="原始请求体字符串（覆盖内置模板）")
    parser.add_argument("--body-file", help="从文件读请求体")
    parser.add_argument("--curl", help="直接粘一整条 curl 命令，脚本会解析后重放")
    parser.add_argument("--payload", help="要作为 input 的 JSON 字符串（默认用内置样例）")
    parser.add_argument("--timeout", type=float, default=60.0)
    args = parser.parse_args()

    settings = get_settings()

    # ---- 模式 3：重放文档里的 curl ----
    if args.curl:
        method, url, headers, body = parse_curl(args.curl)
        print("已解析文档里的 curl 示例。")
        return asyncio.run(_run(send_once, method, url, headers, body, args.timeout))

    payload = json.loads(args.payload) if args.payload else SAMPLE_PAYLOAD
    payload_json = json.dumps(payload, ensure_ascii=False)

    # ---- 模式 2：手工指定 ----
    if args.url:
        headers = {"Content-Type": "application/json"}
        for raw in args.header:
            name, _, value = raw.partition(":")
            headers[name.strip()] = value.strip()
        body = args.body
        if args.body_file:
            body = Path(args.body_file).read_text(encoding="utf-8")
        if body is None:
            body = json.dumps({"input": payload_json}, ensure_ascii=False)
        return asyncio.run(_run(send_once, args.method, args.url, headers, body, args.timeout))

    # ---- 模式 1：按 .env 组装 ----
    print("=" * 70)
    print("GeniOS 配置现状（来自 .env）")
    print("=" * 70)
    print(f"  API_BASE_URL   : {settings.genios_api_base_url or '(空)'}")
    print(f"  API_PATH       : {settings.genios_api_path or '(空)'}")
    print(f"  APP_ID         : {settings.genios_app_id or '(空)'}")
    print(f"  API_KEY        : {'已设置' if settings.genios_api_key else '(空)'}")
    print(f"  AUTH_MODE      : {settings.genios_auth_mode}")
    print(f"  DRY_RUN        : {settings.genios_dry_run}")

    if not settings.genios_configured:
        print("\n⚠️  .env 里的 GENIOS_* 还没填齐。三种走法：")
        print("   1. 填好 .env 后重跑本脚本")
        print('   2. python scripts/probe_genios.py --curl "<文档里的 curl 示例>"')
        print('   3. python scripts/probe_genios.py --url <地址> --header "Authorization: Bearer xxx" \\')
        print("          --body '{\"input\":\"hi\"}'")
        return 2

    client = GeniosClient(settings, httpx.AsyncClient())
    url, headers, body = client.build_request(payload)

    print("\n" + "=" * 70)
    print("将要发送的请求")
    print("=" * 70)
    print(f"  {url}")
    print("  headers: " + json.dumps(_mask(headers), ensure_ascii=False))
    print("  body:")
    print("  " + json.dumps(body, ensure_ascii=False, indent=2).replace("\n", "\n  "))

    if args.dry_run:
        print("\n--dry-run：未发送。确认无误后去掉该参数重跑。")
        return 0

    print("\n" + "=" * 70)
    print("发送中…")
    print("=" * 70)
    return asyncio.run(_run(send_once, "POST", url, headers, json.dumps(body, ensure_ascii=False), args.timeout))


async def _run(func, *args) -> int:
    await func(*args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
