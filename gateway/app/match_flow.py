"""模块二 · 组队匹配的编排流程。

## 它在整条链路里的位置

```
① gateway 轮询【组队需求】发现 状态=待匹配
② 认领该行（状态=匹配中）→ 调 GeniOS 匹配工作流，等结果
③ GeniOS 已把推荐队友/理由/状态写回那一行
④ gateway 读回该行 → 发卡片 A（含「邀请 TA」）→ 通知状态=已通知
⑤ A 点「邀请」→ 卡片回调 → 写【邀请】表 → 发卡片 B 给 B
⑥ B 点「接受/婉拒」→ 卡片回调 → 更新【邀请】表 → 通知 A
```

**gateway 不做任何判断**：谁合适是 GeniOS 算的（铁律 1）。
这里只做「搬运 + 状态机 + 通知」。

## 状态机（靠【组队需求】的两个字段驱动，两边解耦）

| 字段 | 谁写 | 值 |
| --- | --- | --- |
| `状态` | gateway 认领 + **GeniOS 定结果** | 待匹配 → 匹配中 → 已匹配 / 已结束 |
| `通知状态` | **只有 gateway** | 未通知 → 已通知（幂等，防重复推卡） |
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from typing import Any

import httpx

from .bitable import BitableClient, BitableError, flatten_text, open_ids_of
from .card_kit import card, div, note, plain
from .config import Settings
from .feishu_app import FeishuAppClient, FeishuAppError
from .genios_client import GeniosClient
from .match_cards import (
    ACTION_ACCEPT,
    ACTION_DECLINE,
    ACTION_INVITE,
    build_invite_card,
    build_match_card,
    split_reasons,
)

logger = logging.getLogger("gateway.match")

STATUS_PENDING = "待匹配"
STATUS_RUNNING = "匹配中"
STATUS_MATCHED = "已匹配"
STATUS_CLOSED = "已结束"
NOTIFY_DONE = "已通知"

INVITE_PENDING = "待回应"
INVITE_ACCEPTED = "已接受"
INVITE_DECLINED = "已婉拒"

# 【邀请】表的 `来源` —— 同一张表装两种方向，必须能从数据上分开
#   · 匹配邀请：gateway 算完匹配 → 推给**被邀请人** → 由被邀请人决定
#   · 小程序申请：用户在小程序里挑需求 → 推给**发起人** → 由发起人决定
SOURCE_MATCH_INVITE = "匹配邀请"
SOURCE_MINI_APPLY = "小程序申请"

# 平台在"插件授权过期"时会把重新授权链接塞在 msg 里。抓出来推给人用。
# ⚠️ 这个链接**每次都带新的 `state`**，所以不能按链接内容去重 —— 得按时间冷却。
# ⚠️ **不能写 `\S+`** —— 平台给的 msg 是
#     `请点击[这里](https://…&state=xxx)进行授权`
# `)进行授权` 后面没有空格，`\S+` 会把它一起吃掉，
# 结果 state 变成 `xxx)进行授权` → 用户点开永远 **state expired**。
# 实测踩过（2026-10-17）：我从日志里抠链接用的是 `[^)"]*`（对的），
# 但代码里用了 `\S+`（错的）—— 于是**我给的链接都能用、卡片上的都不能用**。
REAUTH_RE = re.compile(
    r"https://accounts\.feishu\.cn/open-apis/authen/v1/authorize[^\s)\]\"'<>]+"
)


def parse_card_action(payload: Any) -> tuple[dict[str, Any], str]:
    """从飞书卡片回调里取出 `(action.value, operator_open_id)`。

    **逐层确认类型** —— 回调里任何一个字段形状变了，都不该把整条链路打断。
    实测踩过（README 里那条"回调没反应"）：`lark.JSON.marshal()` 返回的是
    **JSON 字符串**而不是 dict，直接 `.get()` 就 `'str' object has no attribute 'get'`，
    按钮点下去**毫无反应**，而且看起来像"没收到回调"。
    """
    if not isinstance(payload, dict):
        return {}, ""
    event = payload.get("event") if isinstance(payload.get("event"), dict) else {}
    action = event.get("action") if isinstance(event.get("action"), dict) else {}
    value = action.get("value") if isinstance(action.get("value"), dict) else {}
    operator = event.get("operator") if isinstance(event.get("operator"), dict) else {}
    return value, (operator.get("open_id") or "")


def is_pending(row: dict[str, Any]) -> bool:
    """这一行是不是「等着被匹配」。

    ⚠️ **空状态也算**：为了让表单干净，我们把「状态」这道题从表单里拿掉了，
    新提交的行状态是空的。只认 `== 待匹配` 会永远漏掉新需求 ——
    系统不该依赖"表单帮我们填默认值"。
    """
    return flatten_text(row.get("状态")) in ("", STATUS_PENDING)


def _as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    return [str(value).strip()] if str(value).strip() else []


class MatchFlow:
    def __init__(
        self,
        settings: Settings,
        http: httpx.AsyncClient,
        app: FeishuAppClient,
        bitable: BitableClient,
        genios: GeniosClient,
    ) -> None:
        self.settings = settings
        self.http = http
        self.app = app
        self.bitable = bitable
        self.genios = genios
        # ⚠️ 初值必须是 None，**不能用 0.0** —— `time.monotonic()` 是"开机以来的秒数"，
        # 机器刚启动时它小于冷却时间，会把 0.0 误判成"刚推过"，
        # 于是**开机后头 30 分钟的告警被静默吞掉**（而那正是最该报警的时候）。
        self._last_reauth_alert_at: float | None = None
        # 授权失败后**暂停派发**到这面墙钟时刻。
        #
        # ⚠️ 为什么必须暂停（实测，2026-10-17）：平台给的重授权链接里带一次性 `state`，
        # 而**每次未授权的运行都会生成一个新的** —— 我们每 45 秒重试一次，
        # 就等于每 45 秒把上一条链接作废。用户点开永远 "state expired"。
        # 停下来不再重试，推出去的那条链接才一直是有效的。
        self._auth_paused_until: float = 0.0
        # **卡片动作串行化**。
        #
        # ⚠️ 「先查有没有、再写」这种幂等写法，在 `await` 处会被打断 ——
        # 用户连点两下（或飞书重试回调）时，两个协程可能**同时通过检查**，
        # 于是建出两行一模一样的邀请、发两张卡。表里没有 UNIQUE 约束挡不住。
        # 一把锁把"查 + 写 + 通知"包成一次原子操作，代价是卡片动作排队，
        # 而这个场景本来就只有零星几下，完全无所谓。
        self._card_lock = asyncio.Lock()

    # ================= 读 =================

    async def _profiles_by_open_id(self) -> dict[str, dict[str, Any]]:
        """把【队友画像】读成 `open_id → 画像` 的索引。

        卡片 A 要显示候选人的年级/学院/技能，而【组队需求】行里只有 open_id，
        所以每次轮询把画像表拉一次建索引。校园规模（几百条）没问题。
        """
        if not self.settings.bitable_profile_table_id:
            return {}
        rows = await self.bitable.list_records(self.settings.bitable_profile_table_id)
        # ⚠️ **两遍，顺序很重要。**
        #
        # `创建人` 只有在「加字段之后新提交」的行上才准 —— 加字段那一刻，
        # 飞书会把**历史行**全部回填成字段创建者（实测：7 行全变成谢国辉）。
        # 所以：
        #   第一遍按 `飞书账号`（用户显式声明的）建索引；
        #   第二遍用 `创建人` **只补空缺**（`setdefault`），绝不覆盖。
        index: dict[str, dict[str, Any]] = {}
        for row in rows:
            for open_id in open_ids_of(row.get("飞书账号")):
                index[open_id] = row
                break  # 一个人一行，取第一个账号即可
        for row in rows:
            for open_id in open_ids_of(row.get("创建人")):
                index.setdefault(open_id, row)
                break
        return index

    def _build_request_json(
        self, row: dict[str, Any], profiles: dict[str, dict[str, Any]]
    ) -> dict[str, Any]:
        """把【组队需求】的一行 + 发起人画像，拼成工作流要的 `request_json`。

        ⚠️ **`owner_profile` 不能省**：没有「发起人自己会什么」，
        大模型就只能找「和需求描述像的人」，而不是「补发起人短板的人」。
        """
        # 发起人 = 用户在表单里选的那个人；创建人 = 系统自动记的**真实提交人**。
        # 表单没有只读题目，所以用户选的可能不是自己 —— **以创建人为准**。
        # 但 API 建的行创建人会变成应用所有者，所以只在"创建人确实有画像"时采用。
        picked = open_ids_of(row.get("发起人"))
        creator = open_ids_of(row.get("创建人"))
        owner_ids = [i for i in creator if i in profiles] or picked or creator
        owner_open_id = owner_ids[0] if owner_ids else ""
        owner = profiles.get(owner_open_id, {}) if owner_open_id else {}

        return {
            "match_id": row.get("record_id", ""),
            "owner_open_id": owner_open_id,
            "owner_name": flatten_text(owner.get("姓名")),
            "title": flatten_text(row.get("需求标题")),
            "project_type": flatten_text(row.get("项目类型")),
            "goal": flatten_text(row.get("预期目标")),
            "skills_needed": _as_list(row.get("需要什么技能")),
            "campus": flatten_text(row.get("所在校区")),
            "weekly_hours": flatten_text(row.get("期望每周投入")),
            "owner_profile": {
                "name": flatten_text(owner.get("姓名")),
                "grade": flatten_text(owner.get("年级")),
                "college": flatten_text(owner.get("学院")),
                "campus": flatten_text(owner.get("所在校区")),
                "skills": _as_list(owner.get("技能标签")),
                "weekly_hours": flatten_text(owner.get("每周可投入")),
                "experience": flatten_text(owner.get("过往经历")),
            },
        }

    # ================= 轮询 =================

    async def poll_once(self) -> dict[str, Any]:
        """扫一遍【组队需求】，处理「待匹配」的行。返回统计，便于日志与测试。"""
        summary = {"scanned": 0, "dispatched": 0, "matched": 0, "empty": 0, "errors": 0}
        # 授权失败后的暂停期：**什么都不派发**（见 _auth_paused_until 的注释）
        if time.time() < self._auth_paused_until:
            summary["paused"] = True
            return summary
        if not self.bitable.configured or not self.settings.bitable_request_table_id:
            return summary
        try:
            rows = await self.bitable.list_records(self.settings.bitable_request_table_id)
        except BitableError as exc:
            logger.warning("读【组队需求】失败：%s", exc)
            summary["errors"] += 1
            return summary

        summary["scanned"] = len(rows)
        # ⚠️ **空状态也算「待匹配」**。
        # 起因：为了让表单干净，我们把「状态」这道题从表单里拿掉了，
        # 于是新提交的行状态是空的 —— 只认 `== 待匹配` 的话会永远漏掉新需求。
        # 系统不该依赖"表单帮我们填默认值"。
        pending = [r for r in rows if is_pending(r)]
        if not pending:
            return summary

        profiles = await self._profiles_by_open_id()
        for row in pending:
            try:
                outcome = await self._process_row(row, profiles)
            except (BitableError, FeishuAppError, httpx.HTTPError) as exc:
                logger.warning("处理需求 %s 失败：%s", row.get("record_id"), exc)
                summary["errors"] += 1
                continue
            summary["dispatched"] += 1
            summary[outcome] = summary.get(outcome, 0) + 1
        return summary

    async def _process_row(
        self, row: dict[str, Any], profiles: dict[str, dict[str, Any]]
    ) -> str:
        """认领一行 → 调 GeniOS → 读回 → 发卡片。返回 "matched" 或 "empty"。"""
        record_id = row.get("record_id", "")
        table_id = self.settings.bitable_request_table_id

        # ① 认领：先写「匹配中」，避免下一轮重复派发
        await self.bitable.update_record(table_id, record_id, {"状态": STATUS_RUNNING})

        # ② 调 GeniOS（它会把推荐队友/理由/状态写回这一行）
        payload = {
            "match_id": record_id,
            "request_json": json.dumps(
                self._build_request_json(row, profiles), ensure_ascii=False
            ),
            "candidates_json": "",  # 候选由工作流里的多维表格插件自己读
            "request_record_id": record_id,
            "top_n": str(self.settings.match_top_n),
            "min_score": "70",
        }
        result = await self.genios.dispatch(payload)
        if not result.ok:
            # 失败就放回「待匹配」，下一轮重试。**不静默吞掉。**
            logger.warning("派发失败（%s）：%s", record_id, result.error)
            await self._alert_if_reauth_needed(result.error or "")
            await self.bitable.update_record(table_id, record_id, {"状态": STATUS_PENDING})
            raise BitableError(result.error or "GeniOS 派发失败")

        # ③ 读回 GeniOS 写好的那一行
        fresh = await self.bitable.get_record(table_id, record_id)
        await self._notify_requester(fresh, profiles)
        return "matched" if open_ids_of(fresh.get("推荐队友1")) else "empty"

    async def notify(self, open_id: str, headline: str, detail: str) -> None:
        """给人发一张朴素的结果卡（成功/失败都走它）。

        为什么需要：卡片回调改成**后台异步**之后（飞书回调 3 秒就超时），
        用户点完当场只看到「已收到，正在处理…」。**成败必须另外告诉他**，
        否则失败就变成"点了没反应" —— 那是最差的体验。
        """
        if not open_id:
            return
        await self.app.send_card(
            card(template="blue", title=headline,
                 elements=[div(detail), note("校园机会搭子 · 点完按钮的处理结果")]),
            target=open_id,
        )

    async def _alert_if_reauth_needed(self, error: str) -> None:
        """插件授权过期时，**把重新授权链接推给人**。

        为什么必须做：这种失败是「静默的」—— 工作流只是没结果，
        没人点链接的话匹配会一直停着。平台把链接放在了 error 里，转发一下就能救活。

        去重**按时间冷却**，不按链接内容：链接每次带的 `state` 都不同。
        """
        matched = REAUTH_RE.search(error or "")
        if not matched:
            return
        now = time.monotonic()
        cooldown = self.settings.match_reauth_alert_cooldown_seconds
        if (self._last_reauth_alert_at is not None
                and now - self._last_reauth_alert_at < cooldown):
            return
        target = self.settings.feishu_notify_target
        if not target:
            logger.warning("检测到需要重新授权，但没配 FEISHU_NOTIFY_TARGET，推不出去")
            return
        self._last_reauth_alert_at = now
        # 暂停派发：**别再生成新的 state 把这条链接作废**
        pause = self.settings.match_auth_pause_seconds
        self._auth_paused_until = time.time() + pause
        link = matched.group(0)
        alert = card(
            template="orange",
            title="🔑 需要重新授权",
            elements=[
                div("多维表格插件的授权**已过期**，组队匹配已暂停 —— "
                    "这期间新提交的组队需求**不会被处理**。"),
                div("**复制下面整条链接**，在浏览器里打开并授权。"
                    "授权完不用重启服务，下一轮会自动恢复。"),
                # ⚠️ **故意不做成按钮、也不做成超链接** ——
                # 实测（用户反馈）：卡片按钮里的 `url` 会被飞书**重新编码**，
                # `redirect_uri` 里的 `%2F` 一旦变成 `/`，这个查询参数就会被截断，
                # 结果报「重定向 URL 有误」（飞书错误码 20029）。
                # 而**纯文本**（plain_text，不是 lark_md）不会被转成链接，复制出去是原样的。
                plain(link),
                note(f"校园机会搭子 · 每 {int(cooldown // 60)} 分钟最多提醒一次"),
            ],
        )
        try:
            await self.app.send_card(alert, target=target)
            logger.info("已推送「需要重新授权」告警到 %s", target)
        except FeishuAppError as exc:
            logger.warning("推送重新授权告警失败：%s", exc)

    # ================= 发卡片 A =================

    async def _notify_requester(
        self, row: dict[str, Any], profiles: dict[str, dict[str, Any]]
    ) -> None:
        """给发起人发匹配结果卡片。**幂等**：通知过的行跳过。"""
        table_id = self.settings.bitable_request_table_id
        record_id = row.get("record_id", "")
        if flatten_text(row.get("通知状态")) == NOTIFY_DONE:
            return

        owner_ids = open_ids_of(row.get("发起人"))
        if not owner_ids:
            logger.warning("需求 %s 没有发起人，跳过通知", record_id)
            await self.bitable.update_record(table_id, record_id, {"通知状态": NOTIFY_DONE})
            return

        candidates: list[dict[str, Any]] = []
        for key in ("推荐队友1", "推荐队友2", "推荐队友3"):
            for open_id in open_ids_of(row.get(key)):
                candidates.append({"open_id": open_id, "profile": profiles.get(open_id, {})})
                break

        card = build_match_card(
            request=row,
            candidates=candidates,
            reason_text=flatten_text(row.get("匹配理由")),
        )
        await self.app.send_card(card, target=owner_ids[0])
        # 发完立刻标记，避免 worker 重启后重复推
        await self.bitable.update_record(table_id, record_id, {"通知状态": NOTIFY_DONE})
        logger.info("已通知发起人：需求 %s（推荐 %d 人）", record_id, len(candidates))

    # ================= 卡片回调 =================

    async def handle_card_action(
        self, value: dict[str, Any], operator_open_id: str
    ) -> tuple[str, dict[str, Any] | None]:
        """处理一次卡片点击。返回 `(toast 文案, 要原地更新的卡片或 None)`。

        `operator_open_id` 来自飞书回调的 `event.operator.open_id` ——
        **是飞书给的，不能伪造**，所以我们不需要问"你是谁"。
        """
        kind = value.get("action")
        if kind == ACTION_INVITE:
            async with self._card_lock:
                return await self._handle_invite(value, operator_open_id)
        if kind in (ACTION_ACCEPT, ACTION_DECLINE):
            async with self._card_lock:
                return await self._handle_invite_response(kind, value, operator_open_id)
        return "未知操作", None

    async def _handle_invite(
        self, value: dict[str, Any], operator_open_id: str
    ) -> tuple[str, dict[str, Any] | None]:
        """A 点了「邀请 TA」：写【邀请】表 + 给 B 发卡片。"""
        record_id = value.get("request_record_id", "")
        candidate_open_id = value.get("candidate_open_id", "")
        if not (record_id and candidate_open_id):
            return "参数不完整", None
        if candidate_open_id == operator_open_id:
            return "不能邀请自己", None

        table_id = self.settings.bitable_request_table_id
        row = await self.bitable.get_record(table_id, record_id)
        index = int(value.get("candidate_index") or 0)

        # ⚠️ 给被邀请人的理由要用**「邀请理由」**那份 —— 它的「你」指候选人。
        # 用「匹配理由」的话，对方会读到「你缺的正是设计」（说的其实是发起人）。
        invite_reasons = split_reasons(flatten_text(row.get("邀请理由")))
        fallback = split_reasons(flatten_text(row.get("匹配理由")))
        if index < len(invite_reasons):
            reason = invite_reasons[index]
        elif index < len(fallback):
            reason = fallback[index]  # 老数据没有「邀请理由」字段时兜底
        else:
            reason = ""

        # **幂等**：同一个人对同一条需求重复点「邀请」不该建第二行、也不该再发一次卡片。
        # （实测踩过：连点两下，【邀请】表出现两行一模一样的记录，对方收到两张卡。）
        existing = await self.bitable.list_records(self.settings.bitable_invite_table_id)
        for item in existing:
            if (open_ids_of(item.get("被邀请人"))[:1] == [candidate_open_id]
                    and open_ids_of(item.get("发起人"))[:1] == [operator_open_id]
                    and flatten_text(item.get("需求标题")) == flatten_text(row.get("需求标题"))):
                logger.info("重复邀请，忽略：%s → %s", operator_open_id, candidate_open_id)
                # 对方其实是**在小程序里申请过** —— 别回"已经邀请过 TA 了"，
                # 那会让发起人以为自己点过，实际是 TA 主动找上门的。
                if flatten_text(item.get("来源")) == SOURCE_MINI_APPLY:
                    return "TA 已经申请加入了，去【邀请】表处理就行", None
                return "已经邀请过 TA 了", None

        requester_name = "有同学"
        profiles = await self._profiles_by_open_id()
        requester_name = (
            flatten_text((profiles.get(operator_open_id) or {}).get("姓名")) or requester_name
        )

        invite_row = {
            "需求标题": flatten_text(row.get("需求标题")),
            # ⚠️ v1 的**单向关联字段要「字符串数组」**：`["rec…"]`
            # （`[{"id": …}]` 和 `[{"record_ids": […]}]` 都实测被拒，
            #  错误信息：`the value of 'One-way Link' must be a list of strings`）
            "关联需求": [record_id],
            "发起人": [{"id": operator_open_id}],
            "被邀请人": [{"id": candidate_open_id}],
            "邀请理由": reason,
            "状态": INVITE_PENDING,  # ⚠️ v1 的单选是**字符串**，不是数组
            # 这条界限要落进数据里：同一张表还装着小程序来的申请，
            # **光看行分不出方向**，回调时也得靠它决定"谁该按按钮"。
            "来源": SOURCE_MATCH_INVITE,
        }

        created = await self.bitable.create_records(
            self.settings.bitable_invite_table_id, [invite_row]
        )
        invite_record_id = created[0] if created else ""

        card = build_invite_card(
            invite={"record_id": invite_record_id},
            requester_name=requester_name,
            request=row,
            reason=reason,
        )
        await self.app.send_card(card, target=candidate_open_id)
        logger.info("邀请已发出：%s → %s", operator_open_id, candidate_open_id)
        return "已通知对方", None

    async def _handle_invite_response(
        self, kind: str, value: dict[str, Any], operator_open_id: str
    ) -> tuple[str, dict[str, Any] | None]:
        """有人在卡片上按了「同意 / 不了」。

        ## ⚠️ 两种方向，角色是**反的**

        | 来源 | 卡片发给谁 | 谁在按按钮 | 按完通知谁 |
        | --- | --- | --- | --- |
        | 模块二匹配（`invite`） | 被邀请人 B | B | 发起人 A |
        | 小程序申请（`apply`） | 发起人 A | A | 申请人 B |

        用 `value["source"]` 区分。**发错方向的话，按了会被自己这条规则挡下来**
        （"这条邀请不是发给你的"），表现为"点了没反应"。

        ⚠️ 无论哪个方向，**只有该按的那个人能按** —— 否则知道 `invite_record_id`
        的人都能替别人答应。
        """
        invite_record_id = value.get("invite_record_id", "")
        if not invite_record_id:
            return "找不到这条邀请", None

        table_id = self.settings.bitable_invite_table_id
        invite = await self.bitable.get_record(table_id, invite_record_id)

        # ⚠️ **已经有结论的就别再处理一次**。
        # 连点两下 / 飞书重试回调 / 先同意又点婉拒，都会走到这里；
        # 不拦的话每点一次就**再发一张「🎉 有人答应了」**，对方收到一串重复通知。
        current = flatten_text(invite.get("状态"))
        if current in (INVITE_ACCEPTED, INVITE_DECLINED):
            logger.info("邀请 %s 已有结论（%s），忽略重复点击", invite_record_id, current)
            return "这条已经处理过了", None

        # **以表里的 `来源` 为准**（卡片上的 value 可能过期或被伪造）；
        # 老数据没有这一列时，退回卡片带的方向。
        row_source = flatten_text(invite.get("来源"))
        is_apply = row_source == SOURCE_MINI_APPLY or (
            not row_source and (value.get("source") or "").strip() == "apply"
        )
        if is_apply:
            responders_key, notify_key = "发起人", "被邀请人"
        else:
            responders_key, notify_key = "被邀请人", "发起人"

        responders = open_ids_of(invite.get(responders_key))
        if responders and operator_open_id not in responders:
            logger.warning("非 %s 试图回应：%s", responders_key, operator_open_id)
            return ("这条申请不是发给你的" if is_apply else "这条邀请不是发给你的"), None

        accepted = kind == ACTION_ACCEPT
        new_status = INVITE_ACCEPTED if accepted else INVITE_DECLINED
        await self.bitable.update_record(table_id, invite_record_id, {"状态": new_status})

        notify_ids = open_ids_of(invite.get(notify_key))
        profiles = await self._profiles_by_open_id()
        who = flatten_text((profiles.get(operator_open_id) or {}).get("姓名")) or "对方"
        title = flatten_text(invite.get("需求标题"))

        if notify_ids:
            if is_apply:
                headline = "🎉 对方同意了" if accepted else "申请有回应了"
                body = [
                    div(f"**{who}** 同意了你的加入申请。" if accepted
                        else f"**{who}** 这次没有同意。"),
                    div(f"需求：**{title}**"),
                    div("👉 去飞书多维表格的【邀请】表找到 TA，私聊约时间。"
                        if accepted else "👉 没关系，再看看其他的组队需求。"),
                ]
            else:
                headline = "🎉 有人答应了" if accepted else "邀请有回应了"
                body = [
                    div(f"**{who}** 接受了你的组队邀请。" if accepted
                        else f"**{who}** 这次先不了。"),
                    div(f"需求：**{title}**"),
                    div("👉 下一步：去飞书多维表格的【邀请】表找到 TA，私聊约时间就行。"
                        if accepted else "👉 不用气馁，可以继续邀请卡片里的其他候选人。"),
                ]
            body.append(note("校园机会搭子 · 这条通知不需要回复"))
            try:
                await self.app.send_card(
                    card(template="green" if accepted else "grey",
                         title=headline, elements=body),
                    target=notify_ids[0],
                )
            except FeishuAppError as exc:
                logger.warning("通知对方失败：%s", exc)

        toast = "已告诉对方" if accepted else "已婉拒"
        return toast, None
