"""后台 worker：认领文章 → 调 GeniOS → 记录结果（→ 可选：把结果推到飞书）。

## 关于「要不要依赖 GeniOS 的返回值」

原设计**刻意不依赖**：方案风险备忘写着「GeniOS API 为异步，且 Q1 未确认：若无法查询结果，
则不得依赖返回值，所有结果都应由工作流通过 HTTP 节点回写 gateway」。

**那个前提已经在 2026-10-07 消失了** —— Q1 关闭后实测确认：提交拿 `runId`、
`query_run_app_process` 能查到 `status` 与 `output`（见 `docs/findings.md` Q1）。
所以现在**可以**用返回值。

但仍然遵守一条边界：**机会数据仍然由 `/opportunities` 回写落库**，worker 不自己写业务表。
返回值只用来做**推送**（这是飞连环境下唯一可行的通知路径）。

## 推送目标可配

`FEISHU_APP_PUSH_ENABLED=0`（默认）时完全不推，避免误发。
"""

from __future__ import annotations

import asyncio
import datetime as dt
import json
import logging
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from .config import Settings
from .feishu_app import FeishuAppClient, FeishuAppError
from .genios_client import GeniosClient, GeniosNotConfigured
from .models import Article
from .push import Alerter
from .store import (
    claim_articles,
    mark_dispatched,
    mark_failed,
    schedule_retry,
    upsert_opportunity,
)
from .tz import UTC, iso_shanghai, weekday_cn

logger = logging.getLogger("campus.worker")

_MAX_BACKOFF_SECONDS = 300.0


def build_article_payload(article: Article) -> dict[str, Any]:
    """gateway → GeniOS 的入参契约（方案 7.1）。字段稳定，不依赖 We-MP-RSS 格式。"""
    return {
        "article_id": article.article_id,
        "mode": article.mode,
        "source": article.source,
        "title": article.title,
        "url": article.url,
        "publish_time": iso_shanghai(article.publish_time),
        "publish_weekday": article.publish_weekday or weekday_cn(article.publish_time),
        "text": article.text,
        "links": list(article.links or []),
    }


def extract_llm_payload(response: Any) -> dict[str, Any] | None:
    """从 GeniOS 的查询响应里挖出大模型输出的那个 JSON 对象。

    实测的层层信封（见 docs/findings.md Q1/Q2）：
        查询响应              {"status": "success", "output": "…"}
          └─ output 是字符串   {"output": "<大模型的 raw_output>"}
               └─ raw_output    '{"is_opportunity": true, "items": [...]}'

    每层都可能是「字符串里套 JSON」，所以这里递归剥，直到找到含
    `is_opportunity` 或 `items` 的对象为止。
    """
    seen: set[int] = set()

    def walk(node: Any) -> dict[str, Any] | None:
        if isinstance(node, dict):
            if id(node) in seen:
                return None
            seen.add(id(node))
            if "is_opportunity" in node or "items" in node:
                return node
            for value in node.values():
                found = walk(value)
                if found is not None:
                    return found
        elif isinstance(node, list):
            for value in node:
                found = walk(value)
                if found is not None:
                    return found
        elif isinstance(node, str):
            text = node.strip()
            if text[:1] in "{[":
                try:
                    return walk(json.loads(text))
                except (ValueError, TypeError):
                    return None
        return None

    return walk(response)


# 大模型输出（提示词里的字段名）→ gateway 数据库字段名。
# 原来这一步由 GeniOS 的代码节点做（genios/code_nodes/parse_and_validate.py 的
# `_to_gateway_shape`）。既然改成「worker 拿到结果直接入库」，映射就搬到这里来。
_ITEM_FIELD_MAP = {"event_time_text": "event_time_raw", "signup_method_text": "signup_method"}
# 其余同名字段直接透传
_ITEM_PASSTHROUGH = (
    "name", "type", "summary", "location", "audience", "quota", "signup_url",
    "gongneng_practice", "tags", "evidence", "confidence",
    "event_start", "event_end", "signup_start", "signup_deadline",
)


def to_opportunity_data(
    item: dict[str, Any],
    *,
    source: str | None,
    url: str | None,
    article_id: str | None,
) -> dict[str, Any]:
    """把大模型抽出来的一条 item 转成 `upsert_opportunity` 认得的形状。"""
    data: dict[str, Any] = {}
    for key in _ITEM_PASSTHROUGH:
        if item.get(key) not in (None, "", [], {}):
            data[key] = item[key]
    for src_key, dst_key in _ITEM_FIELD_MAP.items():
        if item.get(src_key):
            data[dst_key] = item[src_key]
    # 类型专属字段整体塞进 extra（网关原样存 JSON），不为四类各开一批列
    if item.get("type_specific"):
        data["extra"] = {"type_specific": item["type_specific"]}
    data["source_account"] = source
    data["source_url"] = url
    data["article_id"] = article_id
    return data


def format_notification(
    source: str | None, title: str | None, url: str | None,
    payload: dict[str, Any] | None, raw: Any,
    stored: list[dict[str, Any]] | None = None,
) -> str:
    """把抽取结果排成一条给人看的飞书消息。"""
    header = f"【公众号】{source or '未知'}\n【标题】{title or '（无标题）'}\n"

    if payload is None:
        return (
            f"{header}\n⚠️ GeniOS 已执行，但没能从返回值里认出抽取结果。\n"
            f"原始返回（截断）：{str(raw)[:300]}"
        )

    if not payload.get("is_opportunity"):
        return f"{header}\n📭 判断为**非机会**文章，不推送。\n（置信度 {payload.get('confidence', '—')}）"

    items = payload.get("items") or []
    lines = [header, f"✅ 识别出 {len(items)} 个机会"]
    for index, item in enumerate(items, 1):
        lines.append(f"\n——— 第 {index} 条 ———")
        lines.append(f"名称：{item.get('name', '—')}")
        lines.append(f"类型：{item.get('type', '—')}")
        if item.get("event_time_raw") or item.get("event_time_text"):
            lines.append(f"活动时间：{item.get('event_time_raw') or item.get('event_time_text')}")
        for label, key in (("报名截止", "signup_deadline"), ("地点", "location"),
                           ("名额", "quota"), ("参与对象", "audience")):
            if item.get(key):
                lines.append(f"{label}：{item[key]}")
        if item.get("signup_url"):
            lines.append(f"报名链接：{item['signup_url']}")
        if item.get("date_conflict"):
            lines.append(f"⚠️ 日期可疑：{'；'.join(item['date_conflict'])}")
        if stored and index - 1 < len(stored) and stored[index - 1].get("duplicate"):
            lines.append("ℹ️ 这条活动之前已收录过，来源已合并")
        elif item.get("low_confidence"):
            lines.append(f"⚠️ 低置信度（{item.get('confidence')}）")
    lines.append("\n原文：" + (url or "—"))
    lines.append("（信息由 AI 从公众号原文抽取，请以原文为准）")
    return "\n".join(lines)


def backoff_seconds(base: float, attempts: int) -> float:
    """指数退避：base, 2·base, 4·base ...，封顶 5 分钟。"""
    return min(_MAX_BACKOFF_SECONDS, base * (2 ** max(0, attempts)))


class ArticleWorker:
    def __init__(
        self,
        settings: Settings,
        session_factory: sessionmaker[Session],
        client: GeniosClient,
        alerter: Alerter,
        feishu_app: FeishuAppClient | None = None,
    ) -> None:
        self.settings = settings
        self.session_factory = session_factory
        self.client = client
        self.alerter = alerter
        self.feishu_app = feishu_app
        self._stop = asyncio.Event()
        # 后台推送任务。持着引用，否则 asyncio 可能在跑完前把它回收掉。
        self._pending: set[asyncio.Task[None]] = set()

    def stop(self) -> None:
        self._stop.set()

    async def drain(self) -> None:
        """等后台推送跑完（关闭时调用，避免推送半路被掐断）。"""
        if not self._pending:
            return
        await asyncio.gather(*list(self._pending), return_exceptions=True)

    # ---------------- 主循环 ----------------

    async def run_forever(self) -> None:
        logger.info("worker 启动：并发=%s", self.settings.worker_concurrency)
        monitor_task = asyncio.create_task(self._liveness_monitor())
        try:
            while not self._stop.is_set():
                processed = await self.run_once()
                if processed == 0:
                    await self._sleep(self.settings.worker_poll_interval_seconds)
        except asyncio.CancelledError:  # pragma: no cover - 关闭路径
            raise
        finally:
            monitor_task.cancel()

    async def _sleep(self, seconds: float) -> None:
        try:
            await asyncio.wait_for(self._stop.wait(), timeout=seconds)
        except asyncio.TimeoutError:
            pass

    async def run_once(self) -> int:
        """认领并处理一批。返回本批条数（0 表示当前没有待处理的）。"""
        with self.session_factory() as session:
            articles = claim_articles(session, self.settings.worker_concurrency)
            session.commit()
            payloads = [(article.id, build_article_payload(article)) for article in articles]

        if not payloads:
            return 0

        semaphore = asyncio.Semaphore(self.settings.worker_concurrency)

        async def guarded(article_id: int, payload: dict[str, Any]) -> None:
            async with semaphore:
                await self._process(article_id, payload)

        await asyncio.gather(*(guarded(aid, payload) for aid, payload in payloads))
        return len(payloads)

    async def _process(self, article_id: int, payload: dict[str, Any]) -> None:
        try:
            result = await self.client.dispatch(payload)
        except GeniosNotConfigured as exc:
            # 配置错误不是「文章的问题」，重试没有意义，直接判失败并告警
            self._record_failure(article_id, f"GeniOS 配置错误：{exc}", retryable=False)
            await self.alerter.alert(
                "GeniOS 配置错误",
                [f"文章 #{article_id} 无法派发", f"**{exc}**", "检查 .env 的 `GENIOS_*`"],
            )
            return

        if result.ok:
            with self.session_factory() as session:
                article = session.get(Article, article_id)
                if article is not None:
                    mark_dispatched(session, article, result.task_id, result.response)
                    session.commit()
                    # 推送与入库要用到文章字段，所以在 session 关掉之前就把要用的快照取出来
                    snapshot = (
                        article.source, article.title, article.url,
                        article.article_id, article.mode, iso_shanghai(article.publish_time),
                    )
                else:
                    snapshot = None
            logger.info("已派发文章 #%s（task_id=%s, dry_run=%s）", article_id, result.task_id, result.dry_run)

            if snapshot is not None:
                await self._deliver(article_id, snapshot, result)
            return

        self._record_failure(article_id, result.error or "未知错误", retryable=True)

    def _store_opportunities(
        self, article_id: int, payload: dict[str, Any],
        source: str | None, url: str | None, article_uid: str | None,
        publish_time: str | None = None,
    ) -> list[dict[str, Any]]:
        """把抽取出的机会写进数据库。**同步执行** —— 本地操作很快，且数据不能丢。

        原来这一步是设计成「GeniOS 工作流用 HTTP 节点回写 `/opportunities`」的。
        改成在这里落库的理由：那个 HTTP 节点要传的 JSON，我们**本来就已经从轮询里拿到了**，
        多绕一圈只是多一个「必须能被 GeniOS 反向访问到」的硬要求（在飞连环境下很贵）。
        判断/抽取/校验仍然全在 GeniOS 内完成，gateway 只负责搬运。
        """
        items = payload.get("items") or []
        stored: list[dict[str, Any]] = []
        if not items:
            return stored

        with self.session_factory() as session:
            for index, item in enumerate(items):
                if not isinstance(item, dict):
                    continue
                data = to_opportunity_data(item, source=source, url=url, article_id=article_uid)
                if publish_time:
                    data["publish_time"] = publish_time
                try:
                    outcome = upsert_opportunity(session, data)
                except ValueError as exc:
                    logger.warning("文章 #%s 第 %s 条机会入库失败：%s", article_id, index + 1, exc)
                    continue
                session.commit()
                record = {
                    "name": outcome.opportunity.name,
                    "duplicate": outcome.duplicate,
                    "low_confidence": outcome.opportunity.low_confidence,
                    "status": outcome.opportunity.status,
                }
                stored.append(record)
                logger.info(
                    "入库：文章 #%s 第 %s 条「%s」→ %s",
                    article_id, index + 1, record["name"],
                    "已存在（合并来源）" if outcome.duplicate else "新建",
                )
        return stored

    async def _deliver(self, article_id: int, snapshot: tuple, result: Any) -> None:
        """拿到 GeniOS 结果后：**先同步入库**，再把**推送丢到后台异步做**。

        为什么这么分：
        - 入库是本地操作、毫秒级、且数据不能丢 → 同步做，失败有日志
        - 推送是网络调用、可能慢或失败 → 异步做，**不占着 worker 的并发槽**，
          下一篇文章马上就能被处理。推送失败也不影响已经落库的数据。
        """
        payload = extract_llm_payload(result.response)
        if payload is None:
            logger.warning("文章 #%s：GeniOS 已执行，但返回值里没有可识别的抽取结果", article_id)
            return

        source, title, url, article_uid, mode, publish_time = snapshot

        stored = self._store_opportunities(
            article_id, payload, source, url, article_uid, publish_time
        )

        if mode == "backfill":
            logger.info("文章 #%s 是 backfill（历史文章），已入库但不推送", article_id)
            return

        if stored and all(record["duplicate"] for record in stored):
            # 验收清单第 4 条：同一活动被两个号转发，只推一次
            logger.info("文章 #%s 的机会全部已收录过（重复来源），不重复推送", article_id)
            return

        if not self.settings.feishu_app_push_enabled or self.feishu_app is None:
            return
        if not self.feishu_app.configured:
            logger.warning("开了推送但没配 FEISHU_APP_ID / FEISHU_APP_SECRET，跳过")
            return

        text = format_notification(source, title, url, payload, result.response, stored)
        task = asyncio.create_task(self._push(article_id, text))
        self._pending.add(task)
        task.add_done_callback(self._pending.discard)

    async def _push(self, article_id: int, text: str) -> None:
        try:
            await self.feishu_app.send_text(text)
            logger.info("已推送到飞书：文章 #%s", article_id)
        except FeishuAppError as exc:
            # 推送失败不改文章状态 —— 数据已经落库了，重试整篇反而会重复派发
            logger.warning("飞书推送失败（文章 #%s）：%s", article_id, exc)

    def _record_failure(self, article_id: int, error: str, *, retryable: bool) -> None:
        with self.session_factory() as session:
            article = session.get(Article, article_id)
            if article is None:  # pragma: no cover - 只可能在并发删除时发生
                return
            if retryable and article.attempts + 1 < self.settings.worker_max_attempts:
                delay = backoff_seconds(self.settings.worker_backoff_base_seconds, article.attempts)
                schedule_retry(session, article, error, delay)
                logger.warning(
                    "文章 #%s 派发失败（第 %s 次），%.0fs 后重试：%s",
                    article_id, article.attempts + 1, delay, error,
                )
            else:
                mark_failed(session, article, error)
                logger.error("文章 #%s 最终失败：%s", article_id, error)
            session.commit()

    # ---------------- 存活监控（阶段 2）----------------

    async def _liveness_monitor(self) -> None:
        """超过 N 分钟没有任何 /ingest 就告警。

        判定依据取数据库里最新一篇文章的入库时间，而不是内存计数 —— 重启后仍然准确。
        """
        interval = max(30.0, self.settings.alert_if_no_ingest_minutes * 60 / 10)
        while not self._stop.is_set():
            await self._sleep(interval)
            if self._stop.is_set():
                return
            try:
                await self.check_liveness()
            except Exception:  # pragma: no cover - 监控自身不能拖垮 worker
                logger.exception("存活检查异常")

    async def check_liveness(self) -> bool:
        """返回是否发出了告警。"""
        with self.session_factory() as session:
            latest = session.scalar(select(func.max(Article.created_at)))
        if latest is None:
            return False  # 全新部署，还没有过任何文章 —— 不告警
        if latest.tzinfo is None:
            latest = latest.replace(tzinfo=UTC)
        idle_minutes = (dt.datetime.now(UTC) - latest).total_seconds() / 60
        if idle_minutes < self.settings.alert_if_no_ingest_minutes:
            return False
        sent = await self.alerter.alert(
            "采集端疑似失效",
            [
                f"已 **{idle_minutes:.0f} 分钟**未收到任何 `/ingest`（阈值 {self.settings.alert_if_no_ingest_minutes} 分钟）",
                f"最后一次入库：{iso_shanghai(latest)}",
                "常见原因：We-MP-RSS 授权过期、容器挂了、公众号停更。",
            ],
        )
        if sent:
            logger.warning("已发出采集端存活告警（空闲 %.0f 分钟）", idle_minutes)
        return sent
