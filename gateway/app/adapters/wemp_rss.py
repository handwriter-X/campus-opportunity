"""We-MP-RSS → 内部 Article 的适配层。

✅ Q6 已于 2026-10-05 由**读上游源码**关闭（见 docs/findings.md）：
真实载荷的信封是 `{feed:{id,name}, articles:[...], task:{...}, now}`，
文章对象字段为 `id/mp_id/title/pic_url/url/description/publish_time`，
`publish_time` 是 `"YYYY-MM-DD HH:MM:SS"` 的 naive 字符串（按 Asia/Shanghai 解释）。

仍然**保留宽容解析**：按候选键名依次尝试，找不到就记进 `notes`，而不是猜一个字段名写死
然后线上静默丢数据。理由是自定义模板可以改结构（用户很可能要往模板里加 `article.content`），
且上游 `description` 不做 JSON 转义，畸形载荷总会有。

若用户实际用的不是 We-MP-RSS（Q7），只需新增一个同签名的模块，`/ingest` 主流程不动。
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Any

from ..normalize import canonical_url, clean_body, extract_links
from ..tz import parse_iso

# 候选键名，按「实测可能性」排序。探针 S3 之后收窄。
_URL_KEYS = ("url", "link", "content_url", "original_url", "source_url", "mp_url", "href")
_TITLE_KEYS = ("title", "name", "article_title", "subject")
_TEXT_KEYS = ("content", "text", "body", "html", "description", "digest", "summary", "desc")
_TIME_KEYS = (
    "publish_time",
    "publishTime",
    "pub_time",
    "create_time",
    "createTime",
    "update_time",
    "updateTime",
    "date",
    "time",
    "published_at",
)
_SOURCE_KEYS = ("mp_name", "account", "source", "author", "nickname", "mp_nickname", "feed_name")
_LIST_KEYS = ("articles", "article", "data", "list", "items", "results", "records", "posts")


@dataclass(slots=True)
class ArticleIn:
    """规范化后的文章。字段与方案 7.1 的 gateway → GeniOS 契约对齐。"""

    url: str
    title: str | None = None
    source: str | None = None
    text: str | None = None
    publish_time: dt.datetime | None = None
    links: list[str] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)


def _first(item: dict[str, Any], keys: tuple[str, ...]) -> Any:
    for key in keys:
        if key in item and item[key] not in (None, ""):
            return item[key]
    # 再试一次大小写不敏感
    lowered = {str(k).lower(): v for k, v in item.items()}
    for key in keys:
        value = lowered.get(key.lower())
        if value not in (None, ""):
            return value
    return None


def _flatten_candidates(raw: Any) -> list[dict[str, Any]]:
    """把各种可能的载荷形状摊平成「一篇文章一个 dict」。

    覆盖：单篇 flat dict、`{articles:[...]}`、`{data:[...]}`、嵌套一层 `{data:{list:[...]}}`、
    以及 `data.type/data.content` 这种 JSON 字符串包一层的情况。
    """
    if isinstance(raw, str):
        import json

        try:
            return _flatten_candidates(json.loads(raw))
        except (ValueError, TypeError):
            return []
    if isinstance(raw, list):
        out: list[dict[str, Any]] = []
        for entry in raw:
            out.extend(_flatten_candidates(entry))
        return out
    if not isinstance(raw, dict):
        return []

    for key in _LIST_KEYS:
        value = raw.get(key)
        if isinstance(value, list) and value:
            out: list[dict[str, Any]] = []
            for entry in value:
                out.extend(_flatten_candidates(entry))
            return out
        if isinstance(value, dict):
            nested = _flatten_candidates(value)
            if nested:
                return nested

    # 看起来像一篇文章本身
    if any(key in raw for key in _URL_KEYS) or any(key in raw for key in _TITLE_KEYS):
        return [raw]
    return []


def _envelope_source(raw: Any) -> str | None:
    """从信封层取公众号名。

    ✅ Q6 已关闭（2026-10-05 读 we-mp-rss 源码 `jobs/webhook.py:72-98`）：默认模板把
    公众号名放在**信封层** `feed.name`（值取自 `feed.mp_name`），文章对象里只有 `mp_id`。
    所以文章级找不到 source 时回退到这里——否则 `source` 恒为 None。
    """
    if isinstance(raw, str):
        import json

        try:
            raw = json.loads(raw)
        except (ValueError, TypeError):
            return None
    if not isinstance(raw, dict):
        return None
    feed = raw.get("feed")
    if isinstance(feed, dict):
        value = feed.get("mp_name") or feed.get("name")
        if value:
            return str(value).strip()
    value = _first(raw, _SOURCE_KEYS)  # 兜底：有些自定义模板会把来源平铺在顶层
    return str(value).strip() if value else None


def parse_payload(raw: Any) -> tuple[list[ArticleIn], list[str]]:
    """返回 (文章列表, 备注列表)。

    备注会写进 `/ingest/_debug` 的落盘文件，方便探针 S3 一眼看出「哪个字段没认出来」。
    """
    notes: list[str] = []
    envelope_source = _envelope_source(raw)
    candidates = _flatten_candidates(raw)
    if not candidates:
        notes.append(
            "未能从载荷中摊平出文章列表。请检查 _LIST_KEYS / _URL_KEYS，"
            "并把原始载荷保存到 eval/samples/（探针 S3）。"
        )
        return [], notes

    articles: list[ArticleIn] = []
    missing_url = 0
    missing_time = 0
    missing_text = 0
    missing_source = 0

    for index, item in enumerate(candidates):
        url = _first(item, _URL_KEYS)
        if not url:
            missing_url += 1
            notes.append(f"第 {index} 条没有可用链接（试过 {_URL_KEYS}），已跳过")
            continue
        url = canonical_url(str(url))

        title = _first(item, _TITLE_KEYS)
        raw_text = _first(item, _TEXT_KEYS)
        text = clean_body(str(raw_text)) if raw_text else None
        if not text:
            missing_text += 1

        source = _first(item, _SOURCE_KEYS) or envelope_source
        if not source:
            missing_source += 1

        time_value = _first(item, _TIME_KEYS)
        publish_time = None
        if isinstance(time_value, (int, float)):
            # 10 位秒 / 13 位毫秒
            seconds = time_value / 1000 if time_value > 1e11 else float(time_value)
            publish_time = dt.datetime.fromtimestamp(seconds, tz=dt.timezone.utc)
        elif time_value:
            publish_time = parse_iso(str(time_value))
        if publish_time is None:
            missing_time += 1

        links = extract_links(text, str(raw_text) if raw_text else None, str(url))

        articles.append(
            ArticleIn(
                url=url,
                title=str(title).strip() if title else None,
                source=str(source).strip() if source else None,
                text=text,
                publish_time=publish_time,
                links=links,
                raw=item,
            )
        )

    if missing_url:
        notes.append(f"{missing_url} 条缺少链接")
    if missing_time:
        notes.append(f"{missing_time} 条缺少发布时间（将被判为 backfill，不会推送）")
    if missing_text:
        notes.append(f"{missing_text} 条缺少正文（抽取质量会受影响）")
    if missing_source:
        notes.append(f"{missing_source} 条缺少公众号名")
    return articles, notes
