"""探针用端点：`/_debug/echo`（S5）与 `/ingest/_debug`（S3）。

⚠️ 这两个端点**不鉴权**（GeniOS 的 HTTP 节点不会带我们的密钥），所以由
`DEBUG_ENDPOINTS_ENABLED` 开关控制，对外长期暴露前必须关掉。
它们只落盘、只回显，**不写业务库**。
"""

from __future__ import annotations

import datetime as dt
import json
import logging
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request

from .adapters import parse_payload
from .tz import SHANGHAI

logger = logging.getLogger("campus.debug")
router = APIRouter(tags=["debug"])


def _ensure_enabled(request: Request) -> None:
    if not request.app.state.settings.debug_endpoints_enabled:
        raise HTTPException(status_code=404, detail="调试端点已关闭（DEBUG_ENDPOINTS_ENABLED=0）")


@router.post("/_debug/echo")
async def echo(request: Request) -> dict[str, Any]:
    """原样回显。探针 S5：证明 GeniOS 的 HTTP 节点能否访问到本服务。"""
    _ensure_enabled(request)
    raw = await request.body()
    try:
        body: Any = json.loads(raw) if raw else None
    except ValueError:
        body = raw.decode("utf-8", errors="replace")

    headers = {k: v for k, v in request.headers.items()}
    logger.info("收到 GeniOS 探针请求：%s %s", request.method, request.url.path)

    return {
        "ok": True,
        "received_at": dt.datetime.now(SHANGHAI).isoformat(timespec="seconds"),
        "method": request.method,
        "path": request.url.path,
        "query": dict(request.query_params),
        "headers": headers,
        "body": body,
        "note": "看到本条响应即表示 GeniOS 能访问本服务（探针 S5 ✅）",
    }


@router.post("/ingest/_debug")
async def ingest_debug(request: Request) -> dict[str, Any]:
    """捕获 We-MP-RSS 的原始载荷（探针 S3）。

    做三件事：原样落盘、跑一遍适配器、报告「哪些字段认出来了、哪些没认出来」。
    """
    _ensure_enabled(request)
    raw_bytes = await request.body()
    text = raw_bytes.decode("utf-8", errors="replace")

    try:
        payload: Any = json.loads(text) if text else None
    except ValueError:
        payload = None  # 可能是 form 或纯文本，照样落盘

    stamp = dt.datetime.now(SHANGHAI).strftime("%Y%m%dT%H%M%S%f")
    capture_dir = Path(request.app.state.settings.debug_capture_dir)
    capture_dir.mkdir(parents=True, exist_ok=True)
    capture_path = capture_dir / f"ingest_debug_{stamp}.json"
    capture_path.write_text(
        json.dumps(
            {
                "captured_at": dt.datetime.now(SHANGHAI).isoformat(timespec="seconds"),
                "headers": dict(request.headers),
                "content_type": request.headers.get("content-type"),
                "raw_text": text,
                "parsed_json": payload,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    articles, notes = parse_payload(payload if payload is not None else text)
    logger.info("已捕获原始载荷 → %s（识别出 %s 篇文章）", capture_path, len(articles))

    return {
        "ok": True,
        "captured_to": str(capture_path),
        "raw_length": len(raw_bytes),
        "recognized_articles": len(articles),
        "notes": notes,
        "preview": [
            {
                "url": article.url,
                "title": article.title,
                "source": article.source,
                "publish_time": article.publish_time.isoformat() if article.publish_time else None,
                "text_length": len(article.text or ""),
                "links": len(article.links),
            }
            for article in articles[:5]
        ],
        "next": "把 captured_to 指向的文件拷进 eval/samples/，并在 docs/findings.md 记录 Q6 结论",
    }
