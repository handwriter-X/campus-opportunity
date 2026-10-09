"""持久化层：幂等入库、去重 upsert、状态派生、worker 认领。

刻意保持「薄」——这里不判断一篇文章是不是机会，也不判断该不该推送。
那些是 GeniOS 工作流的职责（方案设计要点）。
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Any, Iterable, Sequence

from sqlalchemy import Engine, create_engine, event, select
from sqlalchemy.orm import Session, sessionmaker

from .models import (
    ARTICLE_MODES,
    Article,
    Base,
    Opportunity,
    OpportunitySource,
)
from .normalize import make_dedup_key
from .tz import SHANGHAI, UTC, parse_iso


def make_engine(database_url: str, *, echo: bool = False) -> Engine:
    connect_args = {"check_same_thread": False} if database_url.startswith("sqlite") else {}
    engine = create_engine(database_url, echo=echo, future=True, connect_args=connect_args)

    if database_url.startswith("sqlite"):

        @event.listens_for(engine, "connect")
        def _set_pragma(dbapi_connection, _record):  # pragma: no cover - 驱动层
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    return engine


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False, future=True)


def init_db(engine: Engine) -> None:
    Base.metadata.create_all(engine)


# --------------------------------------------------------------------------
# Article
# --------------------------------------------------------------------------


@dataclass(slots=True)
class IngestOutcome:
    article: Article
    created: bool          # 本次是否新建
    duplicate: bool        # 是否命中幂等（此前已存在）
    mode: str
    push_eligible: bool    # 是否允许触发实时推送


def get_article(session: Session, article_id: str) -> Article | None:
    return session.scalar(select(Article).where(Article.article_id == article_id))


def ingest_article(
    session: Session,
    *,
    article_id: str,
    url: str,
    title: str | None,
    source: str | None,
    text: str | None,
    publish_time: dt.datetime | None,
    publish_weekday: str | None,
    links: Sequence[str],
    mode: str,
    raw_payload: dict[str, Any] | None = None,
) -> IngestOutcome:
    """幂等入库。已存在则直接返回，**不改动既有状态**（避免重发把已完成的文章打回 queued）。"""
    if mode not in ARTICLE_MODES:
        raise ValueError(f"非法 mode: {mode}")

    existing = get_article(session, article_id)
    if existing is not None:
        return IngestOutcome(
            article=existing,
            created=False,
            duplicate=True,
            mode=existing.mode,
            push_eligible=existing.pushes,
        )

    article = Article(
        article_id=article_id,
        url=url,
        title=title,
        source=source,
        text=text,
        publish_time=publish_time,
        publish_weekday=publish_weekday,
        links=list(links),
        mode=mode,
        status="queued",
        next_attempt_at=dt.datetime.now(UTC),
        raw_payload=raw_payload,
    )
    session.add(article)
    session.flush()
    return IngestOutcome(
        article=article, created=True, duplicate=False, mode=mode, push_eligible=article.pushes
    )


def claim_articles(session: Session, limit: int) -> list[Article]:
    """认领待处理文章：置为 dispatched，返回给 worker。

    单进程 worker 是唯一认领者，所以不需要行锁。崩溃恢复靠 `requeue_stale_dispatched`。
    """
    now = dt.datetime.now(UTC)
    stmt = (
        select(Article)
        .where(Article.status == "queued")
        .where((Article.next_attempt_at.is_(None)) | (Article.next_attempt_at <= now))
        .order_by(Article.id)
        .limit(limit)
    )
    articles = list(session.scalars(stmt))
    for article in articles:
        article.status = "dispatched"
    session.flush()
    return articles


def requeue_stale_dispatched(session: Session, older_than_minutes: int = 15) -> int:
    """把卡在 dispatched 的文章打回 queued（进程崩溃/重启恢复）。"""
    cutoff = dt.datetime.now(UTC) - dt.timedelta(minutes=older_than_minutes)
    stmt = select(Article).where(Article.status == "dispatched").where(Article.updated_at < cutoff)
    count = 0
    for article in session.scalars(stmt):
        _schedule_retry(article, "worker 重启：状态回滚为 queued", 0.0)
        count += 1
    session.flush()
    return count


def mark_dispatched(session: Session, article: Article, task_id: str | None, response: Any) -> None:
    article.status = "done"       # 已交给 GeniOS；后续结果由工作流经 /opportunities 回写
    article.genios_task_id = task_id
    article.genios_response = _jsonable(response)
    article.last_error = None
    session.flush()


def _schedule_retry(article: Article, error: str, backoff_seconds: float) -> None:
    article.status = "queued"
    article.attempts += 1
    article.last_error = error
    article.next_attempt_at = dt.datetime.now(UTC) + dt.timedelta(seconds=backoff_seconds)
    article.updated_at = dt.datetime.now(UTC)


def mark_failed(session: Session, article: Article, error: str) -> None:
    article.status = "failed"
    article.attempts += 1
    article.last_error = error
    article.next_attempt_at = None
    session.flush()


def schedule_retry(session: Session, article: Article, error: str, backoff_seconds: float) -> None:
    _schedule_retry(article, error, backoff_seconds)
    session.flush()


def _jsonable(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    return str(value)


# --------------------------------------------------------------------------
# Opportunity
# --------------------------------------------------------------------------

# GeniOS 工作流回写时可以带的字段。未列出的键落到 extra。
_OPPORTUNITY_FIELDS = (
    "name",
    "type",
    "summary",
    "event_time_raw",
    "signup_deadline_raw",
    "location",
    "audience",
    "quota",
    "signup_method",
    "signup_url",
    "gongneng_practice",
    "source_url",
    "source_account",
    "confidence",
    "low_confidence",
)

_DATETIME_FIELDS = ("publish_time", "signup_start", "event_start", "event_end", "signup_deadline")


@dataclass(slots=True)
class UpsertOutcome:
    opportunity: Opportunity
    created: bool
    duplicate: bool   # 命中去重键 → 工作流据此不重复推送


def derive_status(opportunity: Opportunity, now: dt.datetime | None = None) -> str:
    """机会状态（代码派生）：未开始 / 可参与 / 已截止。"""
    now = now or dt.datetime.now(UTC)
    if opportunity.signup_deadline is not None and now > opportunity.signup_deadline:
        return "已截止"
    if opportunity.signup_deadline is None and opportunity.event_end is not None and now > opportunity.event_end:
        return "已截止"
    if opportunity.signup_start is not None and now < opportunity.signup_start:
        return "未开始"
    return "可参与"


def upsert_opportunity(session: Session, data: dict[str, Any]) -> UpsertOutcome:
    """按去重键 upsert。

    命中已有记录时：**只补空缺、不覆盖已有值**，并把来源并进去，返回 duplicate=True。
    这样「同一活动被两个公众号转发」只会有一条记录、只推一次（验收清单第 4 条）。
    """
    name = (data.get("name") or "").strip()
    if not name:
        raise ValueError("opportunity.name 必填")

    event_start = _coerce_dt(data.get("event_start"))
    event_end = _coerce_dt(data.get("event_end"))
    signup_start = _coerce_dt(data.get("signup_start"))
    signup_deadline = _coerce_dt(data.get("signup_deadline"))
    publish_time = _coerce_dt(data.get("publish_time"))

    dedup_key = data.get("dedup_key") or make_dedup_key(
        name, event_start, data.get("location"), data.get("event_time_raw")
    )

    existing = session.scalar(select(Opportunity).where(Opportunity.dedup_key == dedup_key))
    article_id = data.get("article_id")

    if existing is not None:
        _merge_missing(existing, data)
        _attach_source(session, existing, article_id, data)
        existing.status = derive_status(existing)
        session.flush()
        return UpsertOutcome(opportunity=existing, created=False, duplicate=True)

    opportunity = Opportunity(
        dedup_key=dedup_key,
        name=name,
        type=data.get("type") or "校园文体活动",
        event_start=event_start,
        event_end=event_end,
        signup_start=signup_start,
        signup_deadline=signup_deadline,
        publish_time=publish_time,
    )
    for field in _OPPORTUNITY_FIELDS:
        if field == "name":
            continue
        if field in data and data[field] is not None:
            setattr(opportunity, field, data[field])
    if opportunity.gongneng_practice not in ("是", "否", "未说明", "不适用"):
        opportunity.gongneng_practice = "未说明"
    opportunity.tags = list(data.get("tags") or [])
    opportunity.evidence = _jsonable(data.get("evidence"))
    opportunity.extra = _jsonable(data.get("extra"))
    if opportunity.confidence is not None:
        threshold = float(data.get("confidence_threshold") or 0.6)
        opportunity.low_confidence = bool(
            data.get("low_confidence") or opportunity.confidence < threshold
        )
    opportunity.status = derive_status(opportunity)
    opportunity.push_status = "未推送"
    session.add(opportunity)
    session.flush()
    _attach_source(session, opportunity, article_id, data)
    session.flush()
    return UpsertOutcome(opportunity=opportunity, created=True, duplicate=False)


def _merge_missing(opportunity: Opportunity, data: dict[str, Any]) -> None:
    """只补空缺，不覆盖。已有人工/AI 认定的值优先。"""
    for field in _OPPORTUNITY_FIELDS:
        if field == "name":
            continue
        incoming = data.get(field)
        if incoming in (None, "", []):
            continue
        if getattr(opportunity, field) in (None, "", []):
            setattr(opportunity, field, incoming)
    for field in _DATETIME_FIELDS:
        if getattr(opportunity, field) is None:
            coerced = _coerce_dt(data.get(field))
            if coerced is not None:
                setattr(opportunity, field, coerced)
    if not opportunity.tags and data.get("tags"):
        opportunity.tags = list(data["tags"])
    if not opportunity.evidence and data.get("evidence"):
        opportunity.evidence = _jsonable(data["evidence"])
    if not opportunity.extra and data.get("extra"):
        opportunity.extra = _jsonable(data["extra"])
    # 证据与类型专属字段做浅合并，保留两侧信息
    elif isinstance(opportunity.extra, dict) and isinstance(data.get("extra"), dict):
        merged = dict(opportunity.extra)
        for key, value in data["extra"].items():
            merged.setdefault(key, value)
        opportunity.extra = merged


def _attach_source(
    session: Session, opportunity: Opportunity, article_id: str | None, data: dict[str, Any]
) -> None:
    if not article_id:
        return
    exists = session.scalar(
        select(OpportunitySource)
        .where(OpportunitySource.opportunity_id == opportunity.id)
        .where(OpportunitySource.article_id == article_id)
    )
    if exists is not None:
        return
    session.add(
        OpportunitySource(
            opportunity_id=opportunity.id,
            article_id=article_id,
            source_url=data.get("source_url"),
            source_account=data.get("source_account"),
        )
    )


def _coerce_dt(value: Any) -> dt.datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, dt.datetime):
        return value if value.tzinfo else value.replace(tzinfo=SHANGHAI)
    if isinstance(value, str):
        return parse_iso(value)
    return None


def set_push_status(session: Session, opportunity: Opportunity, status: str) -> None:
    opportunity.push_status = status
    session.flush()


def refresh_statuses(session: Session) -> int:
    """批量重算机会状态（供定时任务/周报前调用）。"""
    count = 0
    now = dt.datetime.now(UTC)
    for opportunity in session.scalars(select(Opportunity)):
        new_status = derive_status(opportunity, now)
        if new_status != opportunity.status:
            opportunity.status = new_status
            count += 1
    session.flush()
    return count


@dataclass(slots=True)
class OpportunityQuery:
    status: str | None = None
    type: str | None = None
    deadline_from: dt.datetime | None = None
    deadline_to: dt.datetime | None = None
    week: str | None = None
    push_status: str | None = None
    limit: int = 100
    offset: int = 0


def query_opportunities(session: Session, query: OpportunityQuery) -> list[Opportunity]:
    stmt = select(Opportunity)
    if query.status:
        stmt = stmt.where(Opportunity.status == query.status)
    if query.type:
        stmt = stmt.where(Opportunity.type == query.type)
    if query.deadline_from is not None:
        stmt = stmt.where(Opportunity.signup_deadline >= query.deadline_from)
    if query.deadline_to is not None:
        stmt = stmt.where(Opportunity.signup_deadline <= query.deadline_to)
    if query.push_status:
        stmt = stmt.where(Opportunity.push_status == query.push_status)
    if query.week == "current":
        stmt = _apply_current_week(stmt)
    stmt = stmt.order_by(Opportunity.signup_deadline.is_(None), Opportunity.signup_deadline)
    stmt = stmt.offset(query.offset).limit(query.limit)
    return list(session.scalars(stmt))


def _apply_current_week(stmt):
    """本周仍可参与 —— 周报卡片的数据源（方案阶段 4）。

    三条同时满足才纳入：
      1. **还没截止**：截止时间未过；没有截止时间的也纳入
      2. **活动尚未结束**：不把「上周就办完了」的长期活动再推一遍
      3. **报名已经或即将开始**：报名开始时间不晚于本周日，避免把远期活动提前倒进来

    注意这里**不限**活动必须在本周内举办 —— 下周办但本周还在报名的，正是周报最该提醒的。

    ⚠️ 这是初始启发式，按方案要求需用评测集调参。
    """
    now = dt.datetime.now(UTC)
    week_start = now.astimezone(SHANGHAI).replace(hour=0, minute=0, second=0, microsecond=0)
    week_start -= dt.timedelta(days=week_start.weekday())
    week_end_utc = (week_start + dt.timedelta(days=7)).astimezone(UTC)
    week_start_utc = week_start.astimezone(UTC)

    not_expired = (Opportunity.signup_deadline.is_(None)) | (Opportunity.signup_deadline >= now)
    not_finished_before_week = (Opportunity.event_end.is_(None)) | (
        Opportunity.event_end >= week_start_utc
    )
    signup_open_by_week_end = (Opportunity.signup_start.is_(None)) | (
        Opportunity.signup_start <= week_end_utc
    )
    return stmt.where(not_expired).where(not_finished_before_week).where(signup_open_by_week_end)


def iter_all(session: Session, model: type) -> Iterable[Any]:
    return session.scalars(select(model))
