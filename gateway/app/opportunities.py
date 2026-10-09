"""`/opportunities`：GeniOS 工作流的回写入口 + 查询接口。

这是「GeniOS 数据库节点只能查询、不能写入」的绕行方案（方案设计要点）。
"""

from __future__ import annotations

import datetime as dt
import logging
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session

from .config import Settings
from .deps import (
    get_session,
    optional_internal_secret,
    require_internal_secret,
)
from .models import Opportunity
from .store import (
    OpportunityQuery,
    query_opportunities,
    refresh_statuses,
    set_push_status,
    upsert_opportunity,
)
from .tz import iso_shanghai, parse_iso

logger = logging.getLogger("campus.opportunities")
router = APIRouter(tags=["opportunities"])


def _serialize(opportunity: Opportunity) -> dict[str, Any]:
    return {
        "id": opportunity.id,
        "dedup_key": opportunity.dedup_key,
        "name": opportunity.name,
        "type": opportunity.type,
        "summary": opportunity.summary,
        "event_time_raw": opportunity.event_time_raw,
        "event_start": iso_shanghai(opportunity.event_start),
        "event_end": iso_shanghai(opportunity.event_end),
        "signup_start": iso_shanghai(opportunity.signup_start),
        "signup_deadline": iso_shanghai(opportunity.signup_deadline),
        "signup_deadline_raw": opportunity.signup_deadline_raw,
        "location": opportunity.location,
        "audience": opportunity.audience,
        "quota": opportunity.quota,
        "signup_method": opportunity.signup_method,
        "signup_url": opportunity.signup_url,
        "gongneng_practice": opportunity.gongneng_practice,
        "source_url": opportunity.source_url,
        "source_account": opportunity.source_account,
        "publish_time": iso_shanghai(opportunity.publish_time),
        "tags": list(opportunity.tags or []),
        "status": opportunity.status,
        "confidence": opportunity.confidence,
        "low_confidence": opportunity.low_confidence,
        "push_status": opportunity.push_status,
        "evidence": opportunity.evidence,
        "extra": opportunity.extra,
    }


@router.post("/opportunities", dependencies=[Depends(require_internal_secret)])
async def create_opportunity(
    request: Request,
    session: Session = Depends(get_session),
    data: dict[str, Any] = Body(...),
) -> dict[str, Any]:
    """upsert。`duplicate=true` 时工作流**不要推送**（验收清单第 4、5 条）。"""
    try:
        outcome = upsert_opportunity(session, data)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    session.commit()

    if outcome.duplicate:
        logger.info("机会已存在（去重命中）：%s", outcome.opportunity.name)
    else:
        logger.info("新建机会：%s（%s）", outcome.opportunity.name, outcome.opportunity.type)

    return {
        "ok": True,
        "id": outcome.opportunity.id,
        "created": outcome.created,
        "duplicate": outcome.duplicate,
        "push_status": outcome.opportunity.push_status,
        "low_confidence": outcome.opportunity.low_confidence,
        "status": outcome.opportunity.status,
        "dedup_key": outcome.opportunity.dedup_key,
        "opportunity": _serialize(outcome.opportunity),
    }


@router.get("/opportunities", dependencies=[Depends(optional_internal_secret)])
async def list_opportunities(
    request: Request,
    session: Session = Depends(get_session),
    status: str | None = Query(default=None, description="未开始 / 可参与 / 已截止"),
    type: str | None = Query(default=None, description="四类之一"),
    deadline_from: str | None = Query(default=None, description="ISO 时间"),
    deadline_to: str | None = Query(default=None, description="ISO 时间"),
    week: str | None = Query(default=None, description="填 current 取本周仍可参与的（阶段 4 周报）"),
    push_status: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> dict[str, Any]:
    settings: Settings = request.app.state.settings
    if week == "current":
        # 周报前先把状态刷一遍，避免「已截止」还挂在待参与列表里
        refresh_statuses(session)
        session.commit()

    query = OpportunityQuery(
        status=status,
        type=type,
        deadline_from=parse_iso(deadline_from),
        deadline_to=parse_iso(deadline_to),
        week=week,
        push_status=push_status,
        limit=limit,
        offset=offset,
    )
    opportunities = query_opportunities(session, query)
    return {
        "ok": True,
        "count": len(opportunities),
        "generated_at": iso_shanghai(dt.datetime.now(dt.timezone.utc)),
        "filters": {
            "status": status,
            "type": type,
            "deadline_from": deadline_from,
            "deadline_to": deadline_to,
            "week": week,
            "push_status": push_status,
        },
        "internal_base_url": settings.gateway_public_base_url,
        "items": [_serialize(item) for item in opportunities],
    }


@router.post("/opportunities/{opportunity_id}/push-status", dependencies=[Depends(require_internal_secret)])
async def update_push_status(
    request: Request,
    opportunity_id: int,
    session: Session = Depends(get_session),
    body: dict[str, Any] = Body(...),
) -> dict[str, Any]:
    """工作流推送成功后回填推送状态，供周报去重与阶段 5 评测统计。"""
    new_status = body.get("push_status")
    if new_status not in ("未推送", "已即时推送", "已入周报"):
        raise HTTPException(status_code=422, detail="push_status 只能是 未推送/已即时推送/已入周报")
    opportunity = session.get(Opportunity, opportunity_id)
    if opportunity is None:
        raise HTTPException(status_code=404, detail="机会不存在")
    set_push_status(session, opportunity, new_status)
    session.commit()
    return {"ok": True, "id": opportunity_id, "push_status": new_status}
