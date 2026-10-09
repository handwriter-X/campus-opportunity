"""`POST /ingest`：We-MP-RSS 的 Webhook 入口。

职责（方案阶段 1 第 1 条）：
  校验共享密钥 → 规范化 → 幂等去重 → 历史过滤（live/backfill）→ 入队。
理解与判断不在这里。
"""

from __future__ import annotations

import datetime as dt
import logging
from typing import Any

from fastapi import APIRouter, Body, Depends, Request
from sqlalchemy.orm import Session

from .adapters import parse_payload
from .deps import get_session, require_ingest_secret
from .normalize import article_id_for, is_backfill
from .store import ingest_article
from .tz import SHANGHAI, weekday_cn

logger = logging.getLogger("campus.ingest")
router = APIRouter(tags=["ingest"])


@router.post("/ingest", dependencies=[Depends(require_ingest_secret)])
async def ingest(
    request: Request,
    session: Session = Depends(get_session),
    payload: Any = Body(default=None),
) -> dict[str, Any]:
    settings = request.app.state.settings
    articles, notes = parse_payload(payload)

    if not articles:
        logger.warning("载荷里没解析出文章：%s", notes)
        return {
            "ok": False,
            "received": 0,
            "created": 0,
            "duplicates": 0,
            "notes": notes,
            "hint": "载荷结构可能不是预期的样子。用 POST /ingest/_debug 抓一次真实载荷（探针 S3）",
        }

    results: list[dict[str, Any]] = []
    created = duplicates = 0

    for article in articles:
        article_id = article_id_for(article.url)
        mode = "backfill" if is_backfill(article.publish_time, settings.enable_push_after) else "live"

        outcome = ingest_article(
            session,
            article_id=article_id,
            url=article.url,
            title=article.title,
            source=article.source,
            text=article.text,
            publish_time=article.publish_time,
            publish_weekday=weekday_cn(article.publish_time) if article.publish_time else None,
            links=article.links,
            mode=mode,
            raw_payload=article.raw,
        )
        if outcome.created:
            created += 1
        if outcome.duplicate:
            duplicates += 1

        results.append(
            {
                "article_id": article_id,
                "title": article.title,
                "url": article.url,
                "mode": outcome.mode,
                "duplicate": outcome.duplicate,
                "status": outcome.article.status,
                "push_eligible": outcome.push_eligible,
            }
        )

    session.commit()
    request.app.state.last_ingest_at = dt.datetime.now(SHANGHAI)

    logger.info("入库 %s 篇（新建 %s，重复 %s）", len(results), created, duplicates)
    return {
        "ok": True,
        "received": len(articles),
        "created": created,
        "duplicates": duplicates,
        "articles": results,
        "notes": notes,
    }
