"""FastAPI 依赖：配置、会话、鉴权。"""

from __future__ import annotations

import secrets
from typing import Iterator

from fastapi import Header, HTTPException, Request, status
from sqlalchemy.orm import Session

from .config import Settings


def get_settings_dep(request: Request) -> Settings:
    return request.app.state.settings


def get_session(request: Request) -> Iterator[Session]:
    factory = request.app.state.session_factory
    with factory() as session:
        yield session


def _check(provided: str | None, expected: str, header_name: str) -> None:
    # 常量时间比较，避免按字符逐位泄漏
    if not provided or not secrets.compare_digest(provided, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"{header_name} 缺失或不匹配",
        )


def require_ingest_secret(
    request: Request,
    x_ingest_secret: str | None = Header(default=None, alias="X-Ingest-Secret"),
) -> None:
    """We-MP-RSS 打 /ingest 时的共享密钥。"""
    _check(x_ingest_secret, request.app.state.settings.ingest_shared_secret, "X-Ingest-Secret")


def require_internal_secret(
    request: Request,
    x_internal_secret: str | None = Header(default=None, alias="X-Internal-Secret"),
) -> None:
    """GeniOS 工作流的 HTTP 节点打 /opportunities、/push 时的共享密钥。"""
    _check(x_internal_secret, request.app.state.settings.internal_shared_secret, "X-Internal-Secret")


def optional_internal_secret(
    request: Request,
    x_internal_secret: str | None = Header(default=None, alias="X-Internal-Secret"),
) -> None:
    """GET 用：默认放行（校内只读），可用 REQUIRE_AUTH_FOR_GET=1 收紧。"""
    if not request.app.state.settings.require_auth_for_get:
        return
    require_internal_secret(request, x_internal_secret)
