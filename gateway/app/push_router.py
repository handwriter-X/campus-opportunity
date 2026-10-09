"""`POST /push`：飞书推送的降级通道（方案阶段 4）。

优先级是：GeniOS 飞书插件 → GeniOS HTTP 节点直连飞书 Webhook → 本端点。
只有在工作流那边处理不了签名和限流时才走这里 —— gateway 负责签名、排队、限流。
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Request

from .deps import require_internal_secret
from .models import Opportunity
from .push import FeishuError
from .store import set_push_status

logger = logging.getLogger("campus.push")
router = APIRouter(tags=["push"])


@router.post("/push", dependencies=[Depends(require_internal_secret)])
async def push(request: Request, body: dict[str, Any] = Body(...)) -> dict[str, Any]:
    """body 两种形态：
      - `{"text": "..."}`                  → 发文本
      - `{"card": {...}}`                  → 发交互卡片
    可选 `{"opportunity_id": 123, "mark": "已即时推送"}` 在成功后回填推送状态。
    """
    webhook = request.app.state.opportunity_webhook
    if not webhook.configured:
        raise HTTPException(
            status_code=503,
            detail="FEISHU_OPPORTUNITY_WEBHOOK_URL 未配置（探针 S4）",
        )

    try:
        if body.get("card"):
            result = await webhook.send_card(body["card"])
        elif body.get("text"):
            result = await webhook.send_text(str(body["text"]))
        else:
            raise HTTPException(status_code=422, detail="需要 text 或 card 之一")
    except FeishuError as exc:
        logger.error("飞书推送失败：%s", exc)
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    marked = None
    opportunity_id = body.get("opportunity_id")
    mark = body.get("mark")
    if opportunity_id and mark in ("未推送", "已即时推送", "已入周报"):
        marked = await _mark(request, int(opportunity_id), mark)

    return {"ok": True, "feishu": result, "push_status": marked}


async def _mark(request: Request, opportunity_id: int, status: str) -> str | None:
    factory = request.app.state.session_factory
    with factory() as session:
        opportunity = session.get(Opportunity, opportunity_id)
        if opportunity is None:
            return None
        set_push_status(session, opportunity, status)
        session.commit()
    return status
