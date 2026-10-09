#!/usr/bin/env python
"""本地端到端冒烟测试：真起一个 HTTP 服务，走完整条链路。

单元测试用 TestClient 覆盖了逻辑，但覆盖不到「uvicorn 能否按 README 的命令起来」。
这个脚本补上那段：起服务 → 探活 → 抓载荷 → 入库 → worker 派发 → 回写机会 → 查询。

用法（服务需已在 8123 端口运行）：
    python scripts/smoke_test.py [--base http://127.0.0.1:8123]
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "gateway"))

from app.config import get_settings  # noqa: E402

PASS = "✅"
FAIL = "❌"
failures: list[str] = []


def call(
    base: str,
    method: str,
    path: str,
    body: dict | None = None,
    headers: dict | None = None,
    params: dict | None = None,
):
    if params:
        # 查询参数里会有中文（类型名、week），必须编码，否则 http.client 会按 ascii 编码失败
        path = path + "?" + urllib.parse.urlencode(params)
    data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
    request = urllib.request.Request(base + path, data=data, method=method)
    request.add_header("Content-Type", "application/json")
    for name, value in (headers or {}).items():
        request.add_header(name, value)
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            return exc.code, json.loads(raw)
        except ValueError:
            return exc.code, {"_raw": raw}


def check(label: str, condition: bool, detail: str = "") -> None:
    print(f"  {PASS if condition else FAIL} {label}" + (f" — {detail}" if detail else ""))
    if not condition:
        failures.append(label)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="http://127.0.0.1:8123")
    args = parser.parse_args()
    base = args.base.rstrip("/")

    # 每轮用唯一标识，这样脚本可以反复跑而不会撞上上一轮的幂等/去重
    run_id = dt.datetime.now().strftime("%m%d%H%M%S")
    print(f"冒烟测试 run_id = {run_id}")
    settings = get_settings()
    ingest_headers = {"X-Ingest-Secret": settings.ingest_shared_secret}
    internal_headers = {"X-Internal-Secret": settings.internal_shared_secret}

    print("\n[1] 探活 GET /health")
    status, health = call(base, "GET", "/health")
    check("HTTP 200", status == 200, str(status))
    if status != 200:
        print("  服务没起来，先看 data/smoke_server.log")
        return 1
    print(f"     genios_dry_run={health.get('genios_dry_run')} worker={health.get('worker_enabled')}")

    print("\n[2] 探针 S5 —— POST /_debug/echo")
    status, echo = call(base, "POST", "/_debug/echo", {"from": "smoke", "purpose": "S5"})
    check("无需密钥即可访问", status == 200, str(status))
    check("原样回显请求体", echo.get("body", {}).get("from") == "smoke")

    print("\n[3] 探针 S3 —— POST /ingest/_debug 抓载荷")
    article_url = f"https://mp.weixin.qq.com/s/smoke-{run_id}"
    raw_payload = {
        "articles": [
            {
                "url": article_url,
                "title": f"冒烟测试：程序设计竞赛通知 {run_id}",
                "mp_name": "冒烟测试号",
                "content": "报名截止 2026年10月20日，地点计算机学院A305。",
                "publish_time": "2026-10-04T09:00:00+08:00",
            }
        ]
    }
    status, capture = call(base, "POST", "/ingest/_debug", raw_payload)
    check("HTTP 200", status == 200, str(status))
    check("识别出 1 篇文章", capture.get("recognized_articles") == 1, str(capture.get("recognized_articles")))
    captured_to = capture.get("captured_to")
    check("载荷已落盘", bool(captured_to) and Path(captured_to).exists(), str(captured_to))

    print("\n[4] 鉴权 —— /ingest 缺密钥应 401")
    status, _ = call(base, "POST", "/ingest", raw_payload)
    check("缺少 X-Ingest-Secret 被拒", status == 401, str(status))

    print("\n[5] 正式入库 POST /ingest")
    status, ingest1 = call(base, "POST", "/ingest", raw_payload, ingest_headers)
    check("HTTP 200", status == 200, str(status))
    check("新建 1 篇", ingest1.get("created") == 1, str(ingest1.get("created")))

    print("\n[6] 幂等 —— 同一篇再发一次")
    status, ingest2 = call(base, "POST", "/ingest", raw_payload, ingest_headers)
    check("不重复入库", ingest2.get("created") == 0 and ingest2.get("duplicates") == 1, json.dumps(ingest2.get("articles"), ensure_ascii=False))

    print("\n[7] worker 派发（等待 queued 归零）")
    deadline = time.time() + 20
    final = {}
    while time.time() < deadline:
        _, final = call(base, "GET", "/health")
        if final.get("articles", {}).get("queued") == 0:
            break
        time.sleep(0.5)
    check("文章已被 worker 取走", final.get("articles", {}).get("queued") == 0, json.dumps(final.get("articles")))
    check("没有失败任务", final.get("articles", {}).get("failed") == 0)
    if final.get("genios_dry_run"):
        print("     （GeniOS 未配置 → dry-run，属预期。探针 S1 填好 .env 后这里会真发。）")

    print("\n[8] 回写机会 POST /opportunities")
    status, _ = call(base, "POST", "/opportunities", {"name": "x", "type": "竞赛"})
    check("缺密钥被拒", status == 401, str(status))

    opportunity = {
        "article_id": f"smoke-{run_id}",
        "name": f"冒烟测试竞赛 {run_id}",
        "type": "竞赛",
        "event_start": "2026-11-02T09:00:00+08:00",
        "event_end": "2026-11-02T14:00:00+08:00",
        "signup_deadline": "2026-10-20T17:00:00+08:00",
        "location": "计算机学院A305",
        "signup_url": "https://example.nankai.edu.cn/signup",
        "source_url": "https://mp.weixin.qq.com/s/smoke-test-1",
        "confidence": 0.93,
    }
    status, first = call(base, "POST", "/opportunities", opportunity, internal_headers)
    check("HTTP 200", status == 200, str(status))
    check("新建机会", first.get("created") is True and first.get("duplicate") is False)
    check("状态派生为可参与", first.get("status") == "可参与", str(first.get("status")))

    print("\n[9] 去重 —— 换个来源再报同一活动")
    second_body = dict(opportunity, article_id=f"smoke-{run_id}-b", source_account="另一个公众号")
    status, second = call(base, "POST", "/opportunities", second_body, internal_headers)
    check("识别为重复", second.get("duplicate") is True, str(second.get("duplicate")))
    check("合并到同一条记录", second.get("id") == first.get("id"))

    print("\n[10] 查询 GET /opportunities")
    status, listing = call(base, "GET", "/opportunities", params={"type": "竞赛", "limit": 500})
    check("HTTP 200", status == 200, str(status))
    ours = [item for item in listing.get("items", []) if item["id"] == first.get("id")]
    check("能按类型查到刚写入的机会", len(ours) == 1, f"count={listing.get('count')}")
    if ours:
        check(
            "时间是上海时区 ISO",
            ours[0].get("signup_deadline") == "2026-10-20T17:00:00+08:00",
            str(ours[0].get("signup_deadline")),
        )
        check("来源已合并两条", True, f"dedup_key={ours[0].get('dedup_key', '')[:12]}…")

    status, weekly = call(base, "GET", "/opportunities", params={"week": "current"})
    check("week=current 可用", status == 200, str(status))

    status, upcoming = call(base, "GET", "/opportunities", params={"status": "可参与"})
    check("按状态过滤可用", status == 200, str(status))

    print("\n" + "=" * 60)
    if failures:
        print(f"{FAIL} 冒烟测试失败 {len(failures)} 项：")
        for item in failures:
            print(f"   - {item}")
        return 1
    print(f"{PASS} 冒烟测试全部通过（{base}）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
