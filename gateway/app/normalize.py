"""正文清洗、链接提取、去重键计算。

去重键公式来自方案阶段 1：`normalize(名称) + 开始日期 + 规范化地点`。
"""

from __future__ import annotations

import datetime as dt
import hashlib
import re
import unicodedata

from .tz import SHANGHAI

# 中英文标点、空白统一抹掉，只保留实义字符
_PUNCT_RE = re.compile(r"[\s　]+")
_DROP_RE = re.compile(r"[!-/:-@\[-`{-~ -⁯、-〿！-／：-＠［-｀｛-･]+")
_URL_RE = re.compile(r"https?://[^\s<>\"'）)】\]，,。；;]+", re.IGNORECASE)
_HTML_TAG_RE = re.compile(r"<[^>]+>")
_HTML_SCRIPT_RE = re.compile(r"<(script|style)[^>]*>.*?</\1>", re.IGNORECASE | re.DOTALL)
_WS_RE = re.compile(r"[ \t　]+")
_MULTI_NL_RE = re.compile(r"\n{3,}")


def normalize_text(value: str | None) -> str:
    """用于比较的规范化：NFKC（全角→半角）→ 去标点空白 → 小写。"""
    if not value:
        return ""
    text = unicodedata.normalize("NFKC", value)
    text = _PUNCT_RE.sub("", text)
    text = _DROP_RE.sub("", text)
    return text.casefold()


def normalize_location(value: str | None) -> str:
    """地点规范化。额外去掉「校区/室/楼」这类不影响同一性判断的后缀噪音？——不去。

    保守起见只做 NFKC + 去标点空白：多去掉一个字就可能把两个不同地点合并。
    宁可漏合并（产生两条记录），也不要错合并（丢失一个机会）。
    """
    return normalize_text(value)


def make_dedup_key(
    name: str | None,
    event_start: dt.datetime | None,
    location: str | None,
    event_time_raw: str | None = None,
) -> str:
    """去重键。

    「开始日期」优先取规范化后的活动开始日期；没有则退化为原文时间表达（如「11月2日」）。
    ⚠️ 两者都缺时，同名的两个不同活动会撞键 —— 此时会合并来源而不是新增。
    这是**有意选择的偏向**：漏推送一个机会可以人工补，重复推送会让人退群。
    评测阶段若发现误合并，再补字段进键。
    """
    if event_start is not None:
        day = event_start.astimezone(SHANGHAI).date().isoformat()
    else:
        day = normalize_text(event_time_raw)
    raw = "|".join([normalize_text(name), day, normalize_location(location)])
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def sha256_hex(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def canonical_url(url: str | None) -> str:
    """链接规范化：去首尾空白、去掉尾部的 `#fragment`。

    保留 query —— 很多公众号链接靠 query 区分文章。
    """
    if not url:
        return ""
    text = url.strip()
    if "#" in text:
        text = text.split("#", 1)[0]
    return text.rstrip("/")


def article_id_for(url: str) -> str:
    """`article_id = sha256(原文链接)`（方案阶段 1）。"""
    return sha256_hex(canonical_url(url) or url or "")


def extract_links(*texts: str | None) -> list[str]:
    """从正文里提取全部链接，保序去重。"""
    seen: dict[str, None] = {}
    for text in texts:
        if not text:
            continue
        for match in _URL_RE.findall(text):
            cleaned = canonical_url(match)
            if cleaned:
                seen.setdefault(cleaned, None)
    return list(seen)


def clean_body(html_or_text: str | None) -> str:
    """把 html 正文压成可读纯文本。已是纯文本时会原样（略微规整）返回。

    只做机械清洗（去标签、压空白），不做理解 —— 理解是 GeniOS 的事。
    """
    if not html_or_text:
        return ""
    text = _HTML_SCRIPT_RE.sub(" ", html_or_text)
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"</(p|div|li|tr|h[1-6])>", "\n", text, flags=re.IGNORECASE)
    text = _HTML_TAG_RE.sub("", text)
    text = (
        text.replace("&nbsp;", " ")
        .replace("&amp;", "&")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&quot;", '"')
        .replace("&#39;", "'")
    )
    text = _WS_RE.sub(" ", text)
    text = _MULTI_NL_RE.sub("\n\n", text)
    return text.strip()


def is_backfill(publish_time: dt.datetime | None, enable_push_after: dt.datetime) -> bool:
    """发布时间早于阈值 → backfill（仍抽取、不推送）。

    发布时间未知时**保守判为 backfill**：宁可漏推一条新的，也不要在首次启动时
    把历史文章倒灌进飞书群（端到端验收清单第 7 条）。
    """
    if publish_time is None:
        return True
    return publish_time < enable_push_after
