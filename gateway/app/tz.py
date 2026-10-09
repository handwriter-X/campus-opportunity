"""时区工具。

中国无夏令时，所以 `ZoneInfo("Asia/Shanghai")` 不可用时退化为固定 +08:00 是**安全**的
（见 docs/genios_s2_experiments.md 实验 B-2 的判定分支）。
Windows 上 `zoneinfo` 依赖 `tzdata` 包；requirements.txt 已固定它，但仍保留兜底。
"""

from __future__ import annotations

import datetime as dt

try:  # pragma: no cover - 取决于运行环境
    from zoneinfo import ZoneInfo

    SHANGHAI: dt.tzinfo = ZoneInfo("Asia/Shanghai")
    TZ_SOURCE = "zoneinfo"
except Exception:  # pragma: no cover
    SHANGHAI = dt.timezone(dt.timedelta(hours=8), "CST")
    TZ_SOURCE = "fixed+08:00"

UTC = dt.timezone.utc

WEEKDAY_CN = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]


def to_shanghai(value: dt.datetime) -> dt.datetime:
    """把任意 aware datetime 转到上海时区。"""
    if value.tzinfo is None:
        raise ValueError("naive datetime not allowed; 上游必须带时区")
    return value.astimezone(SHANGHAI)


def weekday_cn(value: dt.datetime) -> str:
    """返回「星期日」这样的中文星期，按**上海时区**的那一天算。"""
    return WEEKDAY_CN[to_shanghai(value).weekday()]


def iso_shanghai(value: dt.datetime | None) -> str | None:
    """输出 `2026-10-04T09:30:00+08:00` 形式。"""
    if value is None:
        return None
    return to_shanghai(value).isoformat(timespec="seconds")


def parse_iso(value: str | None) -> dt.datetime | None:
    """解析 ISO 8601。无时区的输入按上海时区理解（我们只服务校内）。"""
    if not value:
        return None
    text = value.strip()
    if not text:
        return None
    try:
        parsed = dt.datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        try:
            parsed = dt.date.fromisoformat(text)
            return dt.datetime.combine(parsed, dt.time.min, tzinfo=SHANGHAI)
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=SHANGHAI)
    return parsed


def now_shanghai() -> dt.datetime:
    return dt.datetime.now(SHANGHAI)
