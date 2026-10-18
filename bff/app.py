"""小程序 BFF —— **无状态**，可以直接扔到云上。

## 它是什么

飞书小程序要的是 REST 接口，而我们的数据在**多维表格**里。
这一层只做搬运：飞书开放接口 ←→ 小程序 JSON。**没有任何判断、没有状态、没有数据库。**

```
小程序 ──HTTPS──▶ BFF（云端） ──HTTPS──▶ 飞书开放平台 ──▶ 多维表格
```

⇒ **和 gateway 完全解耦**。gateway 继续待在校内网跑长连接和轮询；
BFF 单独部署，本机关掉也不影响评委点链接。

## 为什么单独一个进程

gateway 上有 `/_debug`、`/opportunities` 这些接口，**不适合直接对公网开放**。
BFF 只暴露 `/v1/*` 四个接口，用一对共享密钥兜住。

## 环境变量

| 变量 | 说明 |
| --- | --- |
| `FEISHU_APP_ID` / `FEISHU_APP_SECRET` | 飞书自建应用（**和小程序同一个 appid**） |
| `BITABLE_APP_TOKEN` | 多维表格 base |
| `BITABLE_OPPORTUNITY_TABLE_ID` | 【机会汇总】 |
| `BITABLE_REQUEST_TABLE_ID` | 【组队需求】 |
| `BITABLE_INVITE_TABLE_ID` | 【邀请】 |
| `BFF_AGENT_ID` / `BFF_API_KEY` | 小程序请求头里带的那一对（`X-Agent-Id` / `Bearer`） |

## 跑法

```bash
uvicorn bff.app:app --host 0.0.0.0 --port 8100
```
"""

from __future__ import annotations

import json
import os
import re
import time
import logging
from typing import Any

import httpx
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse

try:                                    # 本地：uvicorn bff.app:app（按包导入）
    from .cards import build_apply_card
except ImportError:                     # 容器里：uvicorn app:app（平铺目录）
    from cards import build_apply_card

FEISHU_BASE = "https://open.feishu.cn/open-apis"
TOKEN_MARGIN = 300.0

logger = logging.getLogger("bff")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s | %(message)s")


# ============================================================
# 配置 / 凭据
# ============================================================


class Config:
    app_id = os.environ.get("FEISHU_APP_ID", "")
    app_secret = os.environ.get("FEISHU_APP_SECRET", "")
    app_token = os.environ.get("BITABLE_APP_TOKEN", "")
    opportunity_table = os.environ.get("BITABLE_OPPORTUNITY_TABLE_ID", "")
    request_table = os.environ.get("BITABLE_REQUEST_TABLE_ID", "")
    invite_table = os.environ.get("BITABLE_INVITE_TABLE_ID", "")
    profile_table = os.environ.get("BITABLE_PROFILE_TABLE_ID", "")
    agent_id = os.environ.get("BFF_AGENT_ID", "")
    api_key = os.environ.get("BFF_API_KEY", "")


class Feishu:
    """只做两件事：换 tenant token、读写多维表格。"""

    def __init__(self, config: Config) -> None:
        self.config = config
        self._token = ""
        self._expires_at = 0.0

    async def token(self, client: httpx.AsyncClient) -> str:
        if self._token and time.time() < self._expires_at:
            return self._token
        response = await client.post(
            f"{FEISHU_BASE}/auth/v3/tenant_access_token/internal",
            json={"app_id": self.config.app_id, "app_secret": self.config.app_secret},
            timeout=20.0,
        )
        data = response.json()
        token = data.get("tenant_access_token")
        if not token:
            raise RuntimeError(f"换 token 失败：{data.get('code')} {data.get('msg')}")
        self._token = token
        self._expires_at = time.time() + max(float(data.get("expire") or 7200) - TOKEN_MARGIN, 60.0)
        return token

    async def list_records(self, client: httpx.AsyncClient, table_id: str) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        page_token = ""
        for _ in range(20):                      # 最多 20 页，防跑飞
            params: dict[str, Any] = {"page_size": 500}
            if page_token:
                params["page_token"] = page_token
            response = await client.get(
                f"{FEISHU_BASE}/bitable/v1/apps/{self.config.app_token}/tables/{table_id}/records",
                params=params,
                headers={"Authorization": f"Bearer {await self.token(client)}"},
                timeout=20.0,
            )
            data = response.json()
            if data.get("code") != 0:
                raise RuntimeError(f"读表失败：{data.get('code')} {data.get('msg')}")
            payload = data.get("data") or {}
            for item in payload.get("items") or []:
                row = dict(item.get("fields") or {})
                row["record_id"] = item.get("record_id") or item.get("id") or ""
                rows.append(row)
            if not payload.get("has_more"):
                break
            page_token = payload.get("page_token") or ""
        return rows

    async def create_record(
        self, client: httpx.AsyncClient, table_id: str, fields: dict[str, Any]
    ) -> str:
        response = await client.post(
            f"{FEISHU_BASE}/bitable/v1/apps/{self.config.app_token}/tables/{table_id}/records",
            headers={"Authorization": f"Bearer {await self.token(client)}"},
            json={"fields": fields},
            timeout=20.0,
        )
        data = response.json()
        if data.get("code") != 0:
            raise RuntimeError(f"写表失败：{data.get('code')} {data.get('msg')}")
        record = (data.get("data") or {}).get("record") or {}
        return record.get("record_id") or ""

    async def send_card(
        self, client: httpx.AsyncClient, open_id: str, card: dict[str, Any]
    ) -> None:
        """给某个 open_id 发一张交互卡片。"""
        if not open_id:
            return
        response = await client.post(
            f"{FEISHU_BASE}/im/v1/messages",
            params={"receive_id_type": "open_id"},
            headers={"Authorization": f"Bearer {await self.token(client)}"},
            json={
                "receive_id": open_id,
                "msg_type": "interactive",
                "content": json.dumps(card, ensure_ascii=False),
            },
            timeout=20.0,
        )
        data = response.json()
        if data.get("code") not in (0, None):
            raise RuntimeError(f"发卡片失败：{data.get('code')} {data.get('msg')}")

    async def name_of(self, client: httpx.AsyncClient, open_id: str) -> str:
        """open_id → 姓名。查不到就返回空串（卡片上写"一位同学"）。"""
        if not open_id or not self.config.profile_table:
            return ""
        try:
            rows = await self.list_records(client, self.config.profile_table)
        except Exception:
            return ""
        for row in rows:
            if open_id in _ids_of(row.get("飞书账号")) or open_id in _ids_of(row.get("创建人")):
                return flat(row.get("姓名"))
        return ""

    async def open_id_of_login_code(self, client: httpx.AsyncClient, code: str) -> str:
        """小程序 `Taro.login()` 的 code → open_id。

        ⚠️ 这个 open_id 和 gateway 读表用的**是同一个**（同一个 appid），
        所以能和画像表里的 `飞书账号` 直接对上。
        """
        response = await client.post(
            f"{FEISHU_BASE}/mina/v2/tokenLoginValidate",
            headers={"Authorization": f"Bearer {await self.token(client)}"},
            json={"code": code},
            timeout=20.0,
        )
        data = response.json()
        if data.get("code") != 0:
            raise RuntimeError(f"登录校验失败：{data.get('code')} {data.get('msg')}")
        return ((data.get("data") or {}).get("open_id")) or ""


# ============================================================
# 值转换（飞书 v1 的字段形状 → 小程序要的标量）
# ============================================================

_MS_THRESHOLD = 10 ** 11          # 大于这个数当毫秒时间戳


def flat(value: Any) -> str:
    """富文本分段 / 人员 / 多选 → 字符串。"""
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, dict):
        for key in ("text", "name", "id"):
            inner = value.get(key)
            if isinstance(inner, str) and inner.strip():
                return inner.strip()
        return ""
    if isinstance(value, list):
        parts = [flat(v) for v in value]
        return "、".join(p for p in parts if p)
    return str(value).strip()


def as_ms(value: Any) -> int | None:
    """飞书的日期字段是**毫秒时间戳**；文本日期原样返回不了，就放弃。"""
    if isinstance(value, (int, float)) and value > _MS_THRESHOLD:
        return int(value)
    return None


_CJK_SPACE = re.compile(r"\s+")


def clean(text: str) -> str:
    return _CJK_SPACE.sub(" ", (text or "").strip())


# ============================================================
# 映射：表 → 小程序契约
# ============================================================


def to_activity(row: dict[str, Any]) -> dict[str, Any]:
    """【机会汇总】一行 → 小程序 `Activity`。"""
    return {
        "id": row.get("record_id", ""),
        "name": clean(flat(row.get("机会名称"))),
        "type": clean(flat(row.get("类型"))) or "其他",
        "activityTime": as_ms(row.get("活动开始")),
        "deadline": as_ms(row.get("报名截止")),
        "location": clean(flat(row.get("地点"))) or "待定",
        "source": clean(flat(row.get("来源公众号"))) or "未知来源",
        "description": clean(flat(row.get("简介"))) or "暂无介绍",
        "url": clean(flat(row.get("报名链接"))) or clean(flat(row.get("原文链接"))),
        "audience": clean(flat(row.get("参与对象"))),
        "quota": clean(flat(row.get("名额"))),
    }


def to_team(row: dict[str, Any]) -> dict[str, Any]:
    """【组队需求】一行 → 小程序 `TeamRequest`。

    ⚠️ 小程序那边**没有 deadline 会整条丢掉** —— 所以 `deadline` 给 `None`，
    前端必须改成"缺就当长期有效"（`mini/src/services/team.ts`）。
    """
    return {
        "id": row.get("record_id", ""),
        "name": clean(flat(row.get("需求标题"))),
        "roles": clean(flat(row.get("需要什么技能"))) or "待定",
        "deadline": as_ms(row.get("截止时间")),
        "status": clean(flat(row.get("状态"))),
        "closed": clean(flat(row.get("状态"))) in ("已结束",),
        "publisherName": clean(flat(row.get("发起人"))),
        "description": clean(flat(row.get("预期目标"))),
        "campus": clean(flat(row.get("所在校区"))),
        "weeklyHours": clean(flat(row.get("期望每周投入"))),
        "projectType": clean(flat(row.get("项目类型"))),
    }


# ============================================================
# 应用
# ============================================================

config = Config()
feishu = Feishu(config)
app = FastAPI(title="校园机会搭子 BFF", docs_url=None, redoc_url=None)


def _ok(data: Any) -> dict[str, Any]:
    """小程序约定：`{code: 0, data}`，非 0 会当错误抛出。"""
    return {"code": 0, "data": data}


def _require_headers(x_agent_id: str | None, authorization: str | None) -> None:
    """共享密钥。**不是身份认证** —— 只挡住随手扫接口的人。"""
    if config.agent_id and x_agent_id != config.agent_id:
        raise HTTPException(status_code=401, detail="X-Agent-Id 不对")
    if config.api_key:
        expected = f"Bearer {config.api_key}"
        if (authorization or "") != expected:
            raise HTTPException(status_code=401, detail="API Key 不对")


@app.exception_handler(Exception)
async def _on_error(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("未处理异常：%s", exc)
    return JSONResponse(status_code=500, content={"code": 1, "message": "服务暂时不可用"})


@app.get("/health")
async def health() -> dict[str, Any]:
    return {"ok": True, "configured": bool(config.app_token and config.app_id)}


@app.post("/v1/activities/list")
async def activities_list(
    x_agent_id: str | None = Header(default=None, alias="X-Agent-Id"),
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    _require_headers(x_agent_id, authorization)
    async with httpx.AsyncClient(timeout=30.0) as client:
        rows = await feishu.list_records(client, config.opportunity_table)
    items = [a for a in (to_activity(r) for r in rows) if a["name"]]
    return _ok(items)


@app.post("/v1/opportunities/detail")
async def opportunity_detail(
    payload: dict[str, Any],
    x_agent_id: str | None = Header(default=None, alias="X-Agent-Id"),
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    _require_headers(x_agent_id, authorization)
    wanted = str(payload.get("id") or "")
    async with httpx.AsyncClient(timeout=30.0) as client:
        rows = await feishu.list_records(client, config.opportunity_table)
    for row in rows:
        if row.get("record_id") == wanted:
            return _ok(to_activity(row))
    raise HTTPException(status_code=404, detail="没有这条机会")


@app.post("/v1/teams/list")
async def teams_list(
    x_agent_id: str | None = Header(default=None, alias="X-Agent-Id"),
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    _require_headers(x_agent_id, authorization)
    async with httpx.AsyncClient(timeout=30.0) as client:
        rows = await feishu.list_records(client, config.request_table)
    items = [t for t in (to_team(r) for r in rows) if t["name"]]
    return _ok(items)


@app.post("/v1/teams/detail")
async def team_detail(
    payload: dict[str, Any],
    x_agent_id: str | None = Header(default=None, alias="X-Agent-Id"),
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    _require_headers(x_agent_id, authorization)
    wanted = str(payload.get("id") or "")
    async with httpx.AsyncClient(timeout=30.0) as client:
        rows = await feishu.list_records(client, config.request_table)
    for row in rows:
        if row.get("record_id") == wanted:
            return _ok(to_team(row))
    raise HTTPException(status_code=404, detail="没有这条需求")


@app.post("/v1/teams/apply")
async def team_apply(
    payload: dict[str, Any],
    x_agent_id: str | None = Header(default=None, alias="X-Agent-Id"),
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    """小程序里点「申请」→ 在【邀请】表写一行，等发起人处理。

    **幂等**：同一条需求 + 同一个人，只写一次。
    """
    _require_headers(x_agent_id, authorization)
    team_id = str(payload.get("teamId") or "")
    message = clean(str(payload.get("message") or ""))[:500]
    login_code = str(payload.get("userCode") or "")
    if not team_id:
        raise HTTPException(status_code=400, detail="缺少 teamId")

    async with httpx.AsyncClient(timeout=30.0) as client:
        open_id = ""
        if login_code:
            try:
                open_id = await feishu.open_id_of_login_code(client, login_code)
            except Exception as exc:  # 登录校验失败不该把申请吞掉
                logger.warning("login code 校验失败：%s", exc)

        rows = await feishu.list_records(client, config.request_table)
        request_row = next((r for r in rows if r.get("record_id") == team_id), None)
        if request_row is None:
            raise HTTPException(status_code=404, detail="没有这条需求")

        default_message = "我在小程序里看到这条需求，想加入"

        # **幂等**：同一需求 + 同一个人只写一行。
        # 没有这一步，连点两下就在表里堆两行，对方收到两张卡。
        invites = await feishu.list_records(client, config.invite_table)
        for invite in invites:
            # ⚠️ 必须用 `linked_record_ids` —— 关联字段读回来是对象，不是字符串数组
            if team_id not in linked_record_ids(invite.get("关联需求")):
                continue
            status = clean(flat(invite.get("状态")))
            if open_id and open_id in _ids_of(invite.get("被邀请人")):
                return _ok({"message": "TA 已经同意了你的申请" if status == "已接受"
                            else "你已经申请过了，等 TA 回复就行"})
            # ⚠️ **开发者工具里拿不到 open_id**（`Taro.login()` 失效），
            # 这时只能拿"留言内容"当兜底键 —— 不完美，但比连点两下堆两行强。
            # 真机上 open_id 一定有，走的是上面那条精确判断。
            if not open_id and clean(flat(invite.get("邀请理由"))) == (message or default_message):
                return _ok({"message": "你已经申请过了，等 TA 回复就行"})

        fields: dict[str, Any] = {
            "需求标题": clean(flat(request_row.get("需求标题"))),
            "关联需求": [team_id],
            "邀请理由": message or default_message,
            "状态": "待回应",
            # 和小程序↔机器人的分工绑在一起：这行是"用户主动申请"，
            # 不是"AI 匹配后邀请"。回调时靠它决定**谁该按按钮、通知谁**。
            "来源": "小程序申请",
        }
        owner_ids = _ids_of(request_row.get("发起人"))
        if owner_ids:
            fields["发起人"] = [{"id": owner_ids[0]}]
        if open_id:
            fields["被邀请人"] = [{"id": open_id}]

        invite_id = await feishu.create_record(client, config.invite_table, fields)

        # ⚠️ **光写表是不够的** —— 发起人不会去看表格。必须推一张卡，
        # 而且要把申请人写的「想说的话」放进去（那才是 TA 做决定的信息）。
        if owner_ids:
            who = await feishu.name_of(client, open_id) if open_id else ""
            apply_card = build_apply_card(
                title=clean(flat(request_row.get("需求标题"))) or "你的组队需求",
                who=who or "一位同学",
                message=message,
                invite_record_id=invite_id,
                campus=clean(flat(request_row.get("所在校区"))),
                hours=clean(flat(request_row.get("期望每周投入"))),
            )
            try:
                await feishu.send_card(client, owner_ids[0], apply_card)
            except Exception as exc:  # 通知失败不能把申请吞掉
                logger.warning("申请通知卡片发送失败（申请已写入）：%s", exc)

    return _ok({"message": "申请已发送，TA 会在飞书里收到通知"})


def linked_record_ids(value: Any) -> list[str]:
    """单向关联字段 → 被关联的 record_id 列表。

    ⚠️ **写进去是 `["rec…"]`，读回来却是对象**（实测）：

    ```json
    [{"record_ids": ["rec…"], "table_id": "tbl…", "text": "需求标题", "type": "text"}]
    ```

    按字符串比较会**永远不相等** —— 幂等检查于是一次都不生效，
    表现就是"同一个申请点两次，表里两行"。
    """
    if value in (None, ""):
        return []
    items = value if isinstance(value, list) else [value]
    out: list[str] = []
    for item in items:
        if isinstance(item, str):
            candidates = [item]
        elif isinstance(item, dict):
            candidates = item.get("record_ids") or ([item["id"]] if item.get("id") else [])
        else:
            candidates = []
        for candidate in candidates:
            text = str(candidate).strip()
            if text.startswith("rec") and text not in out:
                out.append(text)
    return out


def _ids_of(value: Any) -> list[str]:
    if value in (None, ""):
        return []
    items = value if isinstance(value, list) else [value]
    out = []
    for item in items:
        candidate = item.get("id") if isinstance(item, dict) else item
        text = str(candidate).strip() if candidate else ""
        if text.startswith("ou_") and text not in out:
            out.append(text)
    return out
