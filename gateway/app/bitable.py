"""飞书多维表格客户端 —— 模块二的数据存取。

## 为什么 gateway 要直接读写表格

决策 **D9**：飞书多维表格是**业务数据的事实源**，本地不再存业务数据。
模块二的闭环靠「状态字段」让两边解耦：

    gateway 轮询【组队需求】发现 状态=待匹配 → 调 GeniOS
    GeniOS 写回推荐队友/理由 → 状态=已匹配
    gateway 读回 → 推飞书卡片 → 状态=已确认
    学生点「邀请」→ 卡片回调 → gateway 写【邀请】表

## 身份：**应用身份**（tenant_access_token）

⚠️ 因此自建应用必须 ① 开通 bitable 权限；② 被加为表格协作者。
没开通时飞书返回 `99991672`，本模块会把申请链接一并抛出来，别让人去猜。

## ⚠️ v1 接口的字段值写法（和 v3 不一样，实测）

| 字段类型 | 写法 |
| --- | --- |
| **单选** | **字符串** `"已匹配"` —— 写成数组会被拒（code 1254062） |
| 多选 | 字符串数组 |
| 人员 | `[{"id": "ou_…"}]` |
| 文本 | 字符串 |

依据：`docs/findings.md` S7 实测记录。
"""

from __future__ import annotations

import datetime as dt
import json
from typing import Any

import httpx

from .config import Settings
from .feishu_app import FEISHU_BASE, FeishuAppClient

# 单次最多拉 500 条（v1 上限）；翻页由 list_records 负责
PAGE_SIZE = 500


class BitableError(RuntimeError):
    """多维表格调用失败。消息里尽量带**可操作**的信息（要开哪个权限）。"""


def flatten_text(value: Any) -> str:
    """把飞书返回的字段值压成字符串。

    ⚠️ 实测（docs/findings.md S7）：**文本字段**回来的是**富文本分段**
        `[{"text": "王五", "type": "text"}]`
    而单选/多选是普通字符串 / 字符串数组。不处理分段就会把
    `{'text': '王五', 'type': 'text'}` 当成姓名，**而且不报错**。
    """
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        for key in ("text", "name", "id"):
            inner = value.get(key)
            if isinstance(inner, str) and inner.strip():
                return inner.strip()
        return ""
    if isinstance(value, list):
        parts = []
        for item in value:
            text = flatten_text(item)
            if text and text not in parts:
                parts.append(text)
        return "、".join(parts)
    return str(value).strip()


def identity_open_ids(row: dict[str, Any]) -> list[str]:
    """这一行的**身份**：优先系统字段 `创建人`。

    ## 为什么不是直接信 `飞书账号` / `发起人`

    飞书表单**没有只读字段** —— 只要题目可见，人就能改。
    但 `创建人` 是系统字段（type 1003），**提交时由飞书自动填、谁都改不了**。

    ⇒ 身份认 `创建人`，用户填的人员字段只当**展示 + 兜底**。

    > ⚠️ **只对「表单提交出来的行」成立**。通过 API（应用身份）建的行，
    > `创建人` 会是**应用所有者**，不是业务上那个人 —— 所以调用方要结合画像表判断。
    """
    for key in ("创建人", "发起人", "飞书账号"):
        ids = open_ids_of(row.get(key))
        if ids:
            return ids
    return []


def open_ids_of(value: Any) -> list[str]:
    """从人员字段里取 open_id。

    ⚠️ 人员字段是 `[{"id": "ou_…", "name": "谢国辉", …}]` ——
    **要 `id`，不是 `name`**。按名字取会把展示名当账号，且不报错。
    """
    if value in (None, ""):
        return []
    items = value if isinstance(value, list) else [value]
    out: list[str] = []
    for item in items:
        candidate = item.get("id") if isinstance(item, dict) else item
        text = str(candidate).strip() if candidate is not None else ""
        if text.startswith("ou_") and text not in out:
            out.append(text)
    return out


def split_record(record: dict[str, Any]) -> dict[str, Any]:
    """把 v1 的一条记录拆成「字段字典 + record_id」。

    v1 返回 `{"fields": {…}, "record_id": "rec…"}`；本函数把它摊平，
    并把 `record_id` 一并带上（写回时要它）。
    """
    fields = record.get("fields")
    if not isinstance(fields, dict):
        fields = record
    flat = dict(fields)
    record_id = record.get("record_id") or record.get("id")
    if record_id:
        flat["record_id"] = record_id
    return flat


def _scope_hint(payload: dict[str, Any]) -> str:
    """把 `99991672`（权限没开）翻译成一句人话 + 申请链接。"""
    if payload.get("code") != 99991672:
        return ""
    return (
        "\n⇒ 自建应用没有开通多维表格的**应用身份**权限。去开放平台开通"
        "（`bitable:app` 或 `base:table:read` + `base:record:retrieve`），"
        "并把应用加为目标表格的协作者。"
    )


class BitableClient:
    def __init__(
        self,
        settings: Settings,
        http: httpx.AsyncClient,
        app: FeishuAppClient,
    ) -> None:
        self.settings = settings
        self.http = http
        self._app = app

    @property
    def configured(self) -> bool:
        return bool(self.settings.bitable_enabled and self.settings.bitable_app_token)

    # ---------------- 底层 ----------------

    def _records_url(self, table_id: str, suffix: str = "") -> str:
        # ⚠️ FEISHU_BASE 已经含 `/open-apis`，别再拼一次
        #（第一次跑冒烟就在这多拼了一层，结果 404 —— 见 findings）
        app_token = self.settings.bitable_app_token
        return (
            f"{FEISHU_BASE}/bitable/v1/apps/{app_token}"
            f"/tables/{table_id}/records{suffix}"
        )

    async def _call(
        self, method: str, url: str, *, json_body: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not self.configured:
            raise BitableError(
                "多维表格未配置：需要 BITABLE_ENABLED=1 与 BITABLE_APP_TOKEN"
            )
        async def _once() -> tuple[httpx.Response, dict[str, Any]]:
            token = await self._app.tenant_token()
            resp = await self.http.request(
                method, url,
                headers={"Authorization": f"Bearer {token}"},
                json=json_body, params=params, timeout=30.0,
            )
            try:
                return resp, resp.json()
            except ValueError as exc:  # 非 JSON，通常是网关或代理问题
                raise BitableError(
                    f"多维表格返回了非 JSON：HTTP {resp.status_code}"
                ) from exc

        response, payload = await _once()
        if payload.get("code") == 99991663:
            # token 失效（休眠/时钟跳变）→ 清缓存重来一次
            self._app.invalidate_token()
            response, payload = await _once()
        if payload.get("code") not in (0, None):
            raise BitableError(
                f"多维表格调用失败：code={payload.get('code')} "
                f"msg={payload.get('msg')}{_scope_hint(payload)}"
            )
        return payload.get("data") or {}

    # ---------------- 读 ----------------

    async def list_records(
        self,
        table_id: str,
        *,
        page_size: int = PAGE_SIZE,
        max_pages: int = 10,
    ) -> list[dict[str, Any]]:
        """拉全一张表（自动翻页）。

        ⚠️ v1 单次上限 500 条。校园规模够用，但**候选人多了必须翻页**，
        否则会静默漏人（`has_more` 为真时只拿到第一页）。
        """
        records: list[dict[str, Any]] = []
        page_token = ""
        for _ in range(max_pages):
            params: dict[str, Any] = {"page_size": page_size}
            if page_token:
                params["page_token"] = page_token
            data = await self._call("GET", self._records_url(table_id), params=params)
            records.extend(split_record(item) for item in (data.get("items") or []))
            page_token = data.get("page_token") or ""
            if not data.get("has_more"):
                break
        return records

    async def get_record(self, table_id: str, record_id: str) -> dict[str, Any]:
        data = await self._call("GET", self._records_url(table_id, f"/{record_id}"))
        return split_record(data.get("record") or {})

    # ---------------- 写 ----------------

    async def update_record(
        self, table_id: str, record_id: str, fields: dict[str, Any]
    ) -> None:
        """更新一条记录。`fields` 按 **v1 的写法** 构造（单选传字符串）。"""
        if not record_id:
            raise BitableError("update_record 需要 record_id")
        await self._call(
            "PUT", self._records_url(table_id, f"/{record_id}"), json_body={"fields": fields}
        )

    async def create_records(
        self, table_id: str, rows: list[dict[str, Any]]
    ) -> list[str]:
        """批量新增，返回新建的 record_id 列表。单批最多 200 条。"""
        if not rows:
            return []
        data = await self._call(
            "POST",
            self._records_url(table_id, "/batch_create"),
            json_body={"records": [{"fields": row} for row in rows]},
        )
        created = data.get("records") or []
        return [item.get("record_id", "") for item in created]


def fields_json_preview(fields: dict[str, Any], limit: int = 400) -> str:
    """日志用：把字段打个短预览。**不打印完整正文**，避免日志里堆长文本。"""
    text = json.dumps(fields, ensure_ascii=False)
    return text if len(text) <= limit else text[:limit] + "…"


# ============================================================ 机会 → 表格行
#
# 决策 D9：**机会数据只进【机会汇总】表，不再进 SQLite**。
# 这里把 gateway 的字段名映射成表头，并处理类型（实测出来的写法）：
#
# | 表里的类型 | 写法 |
# | --- | --- |
# | 单选 | **列表** `["竞赛"]` |
# | 日期 | **Unix 毫秒**（这个表存的就是毫秒，实测） |
# | 数字 | float |
# | 勾选 | bool |
# | 文本 | 字符串（嵌套结构序列化成 JSON 文本） |
OPPORTUNITY_TEXT = {
    "机会名称": "name",
    "简介": "summary",
    "活动时间原文": "event_time_raw",
    "地点": "location",
    "参与对象": "audience",
    "名额": "quota",
    "报名方式": "signup_method",
    "报名链接": "signup_url",
    "来源公众号": "source_account",
    "原文链接": "source_url",
    "去重键": "dedup_key",
}
OPPORTUNITY_SINGLE = {
    "类型": "type",
    "公能实践": "gongneng_practice",
    "推送状态": "push_status",
    "状态": "status",
}
OPPORTUNITY_DATE = {
    "活动开始": "event_start",
    "活动结束": "event_end",
    "报名开始": "signup_start",
    "报名截止": "signup_deadline",
    "原文发布时间": "publish_time",
}
OPPORTUNITY_JSON_TEXT = {"依据": "evidence", "类型专属字段": "extra"}

SHANGHAI = dt.timezone(dt.timedelta(hours=8))


def to_ms(value: Any) -> int | None:
    """时间 → Unix 毫秒。空值返回 None（**不写这一格**，而不是写 0）。"""
    if not value:
        return None
    if isinstance(value, dt.datetime):
        moment = value
    else:
        try:
            moment = dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=SHANGHAI)
    return int(moment.timestamp() * 1000)


def _json_text(value: Any) -> str | None:
    if value in (None, "", [], {}):
        return None
    return json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else str(value)


def opportunity_row(data: dict[str, Any]) -> dict[str, Any]:
    """gateway 的机会字典 → 【机会汇总】表的一行。

    空值**直接不写那一格** —— 写 `""` 会把表格里已有的值冲掉（人工补的也算）。
    """
    row: dict[str, Any] = {}
    for column, key in OPPORTUNITY_TEXT.items():
        text = _json_text(data.get(key))
        if text:
            row[column] = text
    for column, key in OPPORTUNITY_SINGLE.items():
        value = data.get(key)
        if value:
            # ⚠️ **v1 的单选要字符串，v3 要数组** —— 又一次踩到两代 API 写法不同。
            # 写成数组 v1 会拒：`SingleSelectFieldConvFail`，
            # 而且它**用 HTTP 200 返回这个错误**（错误在 body 的 code 里），只看状态码会以为成功。
            row[column] = str(value)
    for column, key in OPPORTUNITY_DATE.items():
        moment = to_ms(data.get(key))
        if moment is not None:
            row[column] = moment
    if data.get("confidence") is not None:
        row["置信度"] = float(data["confidence"])
    row["低置信"] = bool(data.get("low_confidence"))
    tags = data.get("tags")
    if isinstance(tags, str):          # SQLite 里存的是 JSON 字符串，先解析
        try:
            tags = json.loads(tags)
        except ValueError:
            tags = [tags]
    if tags:
        row["标签"] = "、".join(str(t) for t in tags)
    for column, key in OPPORTUNITY_JSON_TEXT.items():
        text = _json_text(data.get(key))
        if text:
            row[column] = text
    return row
