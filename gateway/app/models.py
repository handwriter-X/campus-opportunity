"""数据模型：articles / opportunities / opportunity_sources（方案阶段 1「表」一节）。"""

from __future__ import annotations

import datetime as dt
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    TypeDecorator,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from .tz import UTC


class UTCDateTime(TypeDecorator):
    """SQLite 不保存时区。统一按 UTC 存、取出时补回 UTC，避免 naive/aware 混用。

    入口强制要求 aware datetime —— naive 一律报错，防止「8 小时前/后」这类静默错误。
    """

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value: dt.datetime | None, dialect) -> dt.datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("拒绝 naive datetime：上游必须带时区（见 app/tz.py）")
        return value.astimezone(UTC).replace(tzinfo=None)

    def process_result_value(self, value: dt.datetime | None, dialect) -> dt.datetime | None:
        if value is None:
            return None
        return value.replace(tzinfo=UTC)


class Base(DeclarativeBase):
    pass


# ---- 枚举（与方案 7.2 一致）----
# 枚举值逐字取自 docs/校园机会信息整合_最终业务字段体系.docx 第二节「固定四分类」，
# 方案 §7.2 要求文档约束原样落到 prompt 与校验里，不要在别处另起简称。
OPPORTUNITY_TYPES = ("竞赛", "学术与学习交流", "志愿活动与社会实践", "校园文体活动")
GONGNENG_PRACTICE = ("是", "否", "未说明", "不适用")
PUSH_STATUS = ("未推送", "已即时推送", "已入周报")
OPPORTUNITY_STATUS = ("未开始", "可参与", "已截止")

ARTICLE_MODES = ("live", "backfill")
ARTICLE_STATUS = ("queued", "dispatched", "done", "failed")


class Article(Base):
    """一篇公众号文章。`article_id = sha256(原文链接)`，全局唯一，承载幂等。"""

    __tablename__ = "articles"

    id: Mapped[int] = mapped_column(primary_key=True)
    article_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    source: Mapped[str | None] = mapped_column(String(255))
    title: Mapped[str | None] = mapped_column(Text)
    url: Mapped[str] = mapped_column(Text)
    publish_time: Mapped[dt.datetime | None] = mapped_column(UTCDateTime)
    publish_weekday: Mapped[str | None] = mapped_column(String(16))
    text: Mapped[str | None] = mapped_column(Text)
    links: Mapped[list[str]] = mapped_column(JSON, default=list)

    # live | backfill —— backfill 仍送工作流抽取，但工作流据此不推送
    mode: Mapped[str] = mapped_column(String(16), default="live", index=True)
    # queued | dispatched | done | failed
    status: Mapped[str] = mapped_column(String(16), default="queued", index=True)

    attempts: Mapped[int] = mapped_column(Integer, default=0)
    next_attempt_at: Mapped[dt.datetime | None] = mapped_column(UTCDateTime)
    last_error: Mapped[str | None] = mapped_column(Text)
    genios_task_id: Mapped[str | None] = mapped_column(String(255))
    genios_response: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    raw_payload: Mapped[dict[str, Any] | None] = mapped_column(JSON)

    created_at: Mapped[dt.datetime] = mapped_column(
        UTCDateTime, default=lambda: dt.datetime.now(UTC)
    )
    updated_at: Mapped[dt.datetime] = mapped_column(
        UTCDateTime, default=lambda: dt.datetime.now(UTC), onupdate=lambda: dt.datetime.now(UTC)
    )

    @property
    def pushes(self) -> bool:
        """本篇文章是否有资格触发实时推送。backfill 一律不推。"""
        return self.mode == "live"


class Opportunity(Base):
    """一条机会记录。字段体系见方案 7.2。"""

    __tablename__ = "opportunities"

    id: Mapped[int] = mapped_column(primary_key=True)
    dedup_key: Mapped[str] = mapped_column(String(64), unique=True, index=True)

    # ---- 通用字段（沿用「最终业务字段体系」）----
    name: Mapped[str] = mapped_column(Text)
    type: Mapped[str] = mapped_column(String(32), index=True)
    summary: Mapped[str | None] = mapped_column(Text)
    event_time_raw: Mapped[str | None] = mapped_column(Text)
    signup_deadline_raw: Mapped[str | None] = mapped_column(Text)
    location: Mapped[str | None] = mapped_column(Text)
    audience: Mapped[str | None] = mapped_column(Text)
    quota: Mapped[str | None] = mapped_column(Text)
    signup_method: Mapped[str | None] = mapped_column(Text)
    signup_url: Mapped[str | None] = mapped_column(Text)
    gongneng_practice: Mapped[str] = mapped_column(String(16), default="未说明")
    source_url: Mapped[str | None] = mapped_column(Text)
    tags: Mapped[list[str]] = mapped_column(JSON, default=list)

    # ---- 新增字段（推送与去重必需）----
    publish_time: Mapped[dt.datetime | None] = mapped_column(UTCDateTime)
    source_account: Mapped[str | None] = mapped_column(String(255))
    signup_start: Mapped[dt.datetime | None] = mapped_column(UTCDateTime)
    event_start: Mapped[dt.datetime | None] = mapped_column(UTCDateTime)
    event_end: Mapped[dt.datetime | None] = mapped_column(UTCDateTime)
    signup_deadline: Mapped[dt.datetime | None] = mapped_column(UTCDateTime, index=True)
    status: Mapped[str] = mapped_column(String(16), default="可参与", index=True)
    confidence: Mapped[float | None] = mapped_column(Float)
    low_confidence: Mapped[bool] = mapped_column(Boolean, default=False)
    evidence: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    push_status: Mapped[str] = mapped_column(String(16), default="未推送", index=True)
    extra: Mapped[dict[str, Any] | None] = mapped_column(JSON)  # 类型专属字段

    first_seen_at: Mapped[dt.datetime] = mapped_column(
        UTCDateTime, default=lambda: dt.datetime.now(UTC)
    )
    created_at: Mapped[dt.datetime] = mapped_column(
        UTCDateTime, default=lambda: dt.datetime.now(UTC)
    )
    updated_at: Mapped[dt.datetime] = mapped_column(
        UTCDateTime, default=lambda: dt.datetime.now(UTC), onupdate=lambda: dt.datetime.now(UTC)
    )

    sources: Mapped[list["OpportunitySource"]] = relationship(
        back_populates="opportunity", cascade="all, delete-orphan", lazy="selectin"
    )


class OpportunitySource(Base):
    """机会 ↔ 来源文章，多对多。同一活动被两个公众号转发时，合并来源而不是新增记录。"""

    __tablename__ = "opportunity_sources"
    __table_args__ = (UniqueConstraint("opportunity_id", "article_id", name="uq_opp_article"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    opportunity_id: Mapped[int] = mapped_column(
        ForeignKey("opportunities.id", ondelete="CASCADE"), index=True
    )
    article_id: Mapped[str | None] = mapped_column(String(64), index=True)
    source_url: Mapped[str | None] = mapped_column(Text)
    source_account: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[dt.datetime] = mapped_column(
        UTCDateTime, default=lambda: dt.datetime.now(UTC)
    )

    opportunity: Mapped[Opportunity] = relationship(back_populates="sources")
