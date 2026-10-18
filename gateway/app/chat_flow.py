"""对话路由：学生在飞书发的消息 → 对话智能体 → 回复。

## 为什么单独一层

飞书消息进来是**飞书的事件形状**，而 GeniOS 那边要的是**它自己的入参形状**。
这一层就是把前者翻译成后者、再把结果发回去 —— 和 `match_flow` 对卡片回调做的事一样。

## 通道已验证（不需要再探）

`im.message.receive_v1` 的**真实载荷**（S6 探针落盘，`data/captures/feishu_events.jsonl`）：

```json
{"event_type": "im.message.receive_v1",
 "chat_id": "oc_…", "chat_type": "p2p", "message_type": "text",
 "sender_open_id": "ou_…", "sender_union_id": "on_…",
 "content": "{\"text\":\"hi\"}"}          ← content 是 JSON **字符串**，要再解析一次
```

## ⚠️ 现在这里是个**骨架**

GeniOS 那边的**对话流型智能体还没建**，所以 `_respond()` 先用固定回复顶着。
建好之后**只改 `_respond` 一个方法** —— 通道、路由、防重都在这一层。
"""

from __future__ import annotations

import json
import logging
import re
from typing import TYPE_CHECKING, Any

import httpx
from sqlalchemy import select

from .card_kit import build_opportunity_card, row_to_item
from .config import Settings
from .forms import personalize_links
from .genios_chat import GeniosChatError
from .match_flow import REAUTH_RE
from .bitable import flatten_text
from .models import ChatSession
from .richtext import markdown_to_post

if TYPE_CHECKING:  # 只为类型标注，避免和 genios_chat 互相 import
    from .genios_chat import GeniosChatClient
from .feishu_app import FeishuAppClient, FeishuAppError

logger = logging.getLogger("gateway.chat")

# ⚠️ **只在单聊里回话。**
# 群里每来一条消息都回一句会把人烦死 —— 正确的做法是只在被 @ 时回，
# 但那要先设计"群里怎么用"，现在没想清楚，所以先单聊。
ALLOWED_CHAT_TYPES = ("p2p",)

# 模型推荐机会时吐的标记：`[[reczz28NvViIdJTk]]`。
# 只认 **record_id** —— 名字是模型可以编的，record_id 编不出来（编了也查不到）。
CARD_MARKER_RE = re.compile(r"\[\[\s*(rec[0-9A-Za-z]{6,})\s*\]\]")
MAX_CARDS_PER_REPLY = 5


def extract_card_markers(text: str) -> tuple[list[str], str]:
    """从回复里拆出要发卡片的 record_id，并把这些标记从正文里删掉。"""
    body = text or ""
    ids: list[str] = []
    for record_id in CARD_MARKER_RE.findall(body):
        if record_id not in ids:
            ids.append(record_id)
    cleaned = re.sub(r"\n{3,}", "\n\n", CARD_MARKER_RE.sub("", body)).strip()
    return ids[:MAX_CARDS_PER_REPLY], cleaned

PLACEHOLDER_REPLY = (
    "我是**校园机会搭子** 🌱\n\n"
    "现在还没接上智能体（`GENIOS_CHAT_*` 没配），只能先报个到。\n"
    "接上之后你可以这样问我：\n"
    "- 有哪些适合我的比赛？\n"
    "- 我想给 CANN 大赛找队友"
)


def _as_open_ids(value: Any) -> list[str]:
    """人员字段 → open_id 列表（**取 `id`，不是 `name`**）。"""
    if value in (None, ""):
        return []
    items = value if isinstance(value, list) else [value]
    out = []
    for item in items:
        candidate = item.get("id") if isinstance(item, dict) else item
        text = str(candidate).strip() if candidate is not None else ""
        if text.startswith("ou_") and text not in out:
            out.append(text)
    return out


def _profile_line(row: dict[str, Any]) -> str:
    """画像行 → 一句话（年级 · 学院 · 校区 · 技能）。"""
    bits = []
    for key in ("年级", "学院", "所在校区"):
        text = flatten_text(row.get(key))
        if text:
            bits.append(text)
    for key, label in (("技能标签", "技能"), ("每周可投入", "每周")):
        text = flatten_text(row.get(key))
        if text:
            bits.append(f"{label}：{text}")
    return " · ".join(bits)


def message_text(content: Any) -> str:
    """从飞书消息事件里取出纯文本。

    `content` 是 **JSON 字符串**（形如 `{"text":"hi"}`），要再解析一次。
    不是文本消息（图片/文件…）就返回空串 —— 后面的逻辑按"没听懂"处理。
    """
    if isinstance(content, dict):
        return str(content.get("text") or "").strip()
    if not isinstance(content, str):
        return ""
    raw = content.strip()
    if raw[:1] == "{":
        try:
            parsed = json.loads(raw)
        except (ValueError, TypeError):
            return ""
        if isinstance(parsed, dict):
            return str(parsed.get("text") or "").strip()
    return raw


def strip_mention(text: str) -> str:
    """去掉 @机器人 留下的占位符。

    飞书在群里会用 `@_user_1` 这种占位符替换 @，直接送进模型会干扰理解。
    """
    return re.sub(r"@_user_\d+", "", text).strip()


def parse_message_event(payload: Any) -> dict[str, Any]:
    """把飞书的消息事件摊平成我们要的几个字段。

    **逐层确认类型** —— 事件形状变了不该把整条链路打断（卡片回调那边就吃过这个亏）。
    """
    if not isinstance(payload, dict):
        return {}
    event = payload.get("event") if isinstance(payload.get("event"), dict) else {}
    message = event.get("message") if isinstance(event.get("message"), dict) else {}
    sender = event.get("sender") if isinstance(event.get("sender"), dict) else {}
    sender_id = sender.get("sender_id") if isinstance(sender.get("sender_id"), dict) else {}

    open_id = sender_id.get("open_id") or event.get("sender_open_id") or ""
    return {
        "chat_id": message.get("chat_id") or event.get("chat_id") or "",
        "chat_type": message.get("chat_type") or event.get("chat_type") or "",
        "message_type": message.get("message_type") or event.get("message_type") or "",
        "message_id": message.get("message_id") or event.get("message_id") or "",
        "open_id": open_id,
        "text": strip_mention(message_text(message.get("content") or event.get("content"))),
    }


class ChatFlow:
    def __init__(
        self,
        settings: Settings,
        http: httpx.AsyncClient,
        app: FeishuAppClient,
        genios_chat: "GeniosChatClient | None" = None,
        session_factory: Any = None,
        bitable: Any = None,
    ) -> None:
        self.settings = settings
        self.http = http
        self.app = app
        self.genios_chat = genios_chat
        self.session_factory = session_factory
        self.bitable = bitable

    async def handle_message(self, payload: dict[str, Any]) -> None:
        """处理一条进来的消息。**永远不抛异常** —— 一条消息处理失败不该影响通道。"""
        parsed = parse_message_event(payload)
        chat_id = parsed.get("chat_id") or ""
        open_id = parsed.get("open_id") or ""
        text = parsed.get("text") or ""

        logger.info("收到消息：%s（%s）→ %r",
                    open_id or "?", parsed.get("chat_type") or "?", text[:80])

        if not chat_id:
            logger.warning("消息里没有 chat_id，无法回复")
            return
        if parsed.get("chat_type") not in ALLOWED_CHAT_TYPES:
            logger.info("非单聊（%s），暂不回复", parsed.get("chat_type"))
            return
        if not text:
            await self._safe_reply(chat_id, "我现在只能看懂**文字消息** 🙂 把想说的打成字发我就行。")
            return

        try:
            reply = await self._respond(open_id, text)
        except Exception as exc:  # noqa: BLE001 —— 兜住一切，别让通道断掉
            logger.exception("生成回复失败：%s", exc)
            reply = "刚才没处理过来，**稍后再发一次**就好。"

        # ⚠️ **别把原始报错当回复发出去。**
        # 画布在"插件需要授权"时，会把平台给的那段
        #   「使用工具 search_records 需要授权, 请点击[这里](https://accounts.feishu.cn/…)」
        # 当成正文返回 —— 直接发给用户既难看又点不动（state 很快失效）。
        if "authen/v1/authorize" in reply or "需要授权" in reply:
            # ⚠️ **别把链接一起吞掉。**
            # 对话这边每次提问都会重新跑一次工作流 → 平台给一个**新的、干净的**链接，
            # 所以这里正好是用户最容易拿到有效链接的地方。
            # 第一版把它整段替换成了"数据连接中断"，反倒把唯一能救命的东西藏了。
            link = REAUTH_RE.search(reply)
            logger.warning("对话返回的是授权提示，转成人话（保留链接）")
            if link:
                reply = ("我这边的**多维表格授权过期了** —— 现在查不到机会，也暂时不能帮你匹配。\n\n"
                         "点下面这条链接授权一下（**有时效，尽快点**）：\n\n"
                         + link.group(0))
            else:
                reply = ("我这边的数据连接暂时断了，正在恢复中 🙏\n\n"
                         "如果是想找队友，可以先填这个表单：\n"
                         "https://nankai.feishu.cn/share/base/shrcnH1oQRYtBvm1y7WYAj38gne")
        await self._safe_reply(chat_id, reply)

    async def _safe_reply(self, chat_id: str, text: str) -> None:
        # **把发出去的原文记下来** —— 之前只记"失败"，成功了反而没痕迹，
        # 结果用户说"还是有问题"时查不出到底发了什么。
        logger.info("回复 → %s：%s", chat_id, text[:120])

        # 模型在推荐机会时会吐出 `[[rec…]]` 标记（见画布提示词）。
        # 文字照发，**每条机会再补一张卡片** —— 卡片上有报名按钮和原文链接。
        card_ids, text = extract_card_markers(text)
        if text:
            try:
                # ⚠️ **带授权链接的回复必须走纯文本**。
                # 富文本里的链接会被飞书重新编码，`redirect_uri` 的 `%2F` 变 `/`
                # 就会截断查询串（错误码 20029）—— 详见 docs/findings.md Q15。
                post = None if "authen/v1/authorize" in text else markdown_to_post(text)
                sender = getattr(self.app, "send_post", None)
                if post is not None and sender is not None:
                    await sender(post, target=chat_id)
                else:
                    await self.app.send_text(text, target=chat_id)
            except FeishuAppError as exc:
                logger.warning("回复失败：%s", exc)

        if card_ids:
            await self._send_opportunity_cards(chat_id, card_ids)

    async def _send_opportunity_cards(self, chat_id: str, record_ids: list[str]) -> None:
        """按 `record_id` 从【机会汇总】取行，一条一张卡。

        ⚠️ **不在模型回复里拼卡片数据** —— 名字、截止时间、链接全部以**表里那一行**为准。
        模型只负责"推荐哪一条"，不负责"那一条长什么样"。
        """
        if self.bitable is None or not self.bitable.configured:
            return
        table_id = self.settings.bitable_opportunity_table_id
        if not table_id:
            return
        try:
            rows = await self.bitable.list_records(table_id)
        except Exception as exc:  # noqa: BLE001 —— 发不出卡片不能影响文字回复
            logger.warning("取机会卡片失败（文字已发出）：%s", exc)
            return
        index = {row.get("record_id"): row for row in rows}
        for record_id in record_ids:
            row = index.get(record_id)
            if row is None:
                logger.info("模型推荐了表里没有的记录 %s，跳过", record_id)
                continue
            built = build_opportunity_card(
                row_to_item(row), footer="由 AI 从机会库挑出 · 详情以原文为准"
            )
            if built is None:
                continue
            try:
                await self.app.send_card(built, target=chat_id)
            except FeishuAppError as exc:
                logger.warning("发机会卡片失败：%s", exc)
                return

    # ================= 对话智能体 =================

    @property
    def _api_user(self) -> str:
        """调 GeniOS 时用的**服务身份**，不是学生本人。

        ⚠️ **别改回 `open_id`**（实测，2026-10-17）：飞书多维表格插件的 OAuth
        授权**按「运行时的 userID」一对一绑定** ——
        传学生 open_id 的话，**每个新同学第一次提问都会收到"需要授权"**。

        "这个学生是谁"由两样东西承载，和平台侧的 userID 无关：
          - `【我的画像】`（`_with_profile`）→ 让模型知道 TA 的背景
          - 按 open_id 存的 `ChatSession.conversation_id` → 多轮记忆各是各的
        """
        return self.settings.genios_chat_user_id or self.settings.genios_user_id

    async def _conversation_id(self, open_id: str) -> str:
        """拿这个人的 GeniOS 会话 id；**第一次见到就替他开一个**。

        飞书消息事件只给 `open_id`（谁发的），而 `chat_query` **必须**带
        `AppConversationID` —— 多轮上下文就靠它续上。这一层把两者对起来。
        """
        if self.session_factory is not None:
            with self.session_factory() as session:
                row = session.execute(
                    select(ChatSession).where(ChatSession.open_id == open_id)
                ).scalar_one_or_none()
                if row is not None:
                    return row.conversation_id

        conversation = await self.genios_chat.create_conversation(self._api_user)
        await self._remember_conversation(open_id, conversation)
        return conversation

    async def _remember_conversation(self, open_id: str, conversation_id: str) -> None:
        """把这个人的会话 id 记下来（有就更新，没有就新增）。"""
        if self.session_factory is None:
            return
        with self.session_factory() as session:
            row = session.execute(
                select(ChatSession).where(ChatSession.open_id == open_id)
            ).scalar_one_or_none()
            if row is None:
                session.add(ChatSession(open_id=open_id, conversation_id=conversation_id))
            else:
                row.conversation_id = conversation_id
            session.commit()

    async def _profile_row(self, open_id: str) -> dict[str, Any] | None:
        """按 open_id 找到这个人的画像行；没有就返回 `None`。

        单独拆出来是因为**要读两次**：一次拼进 Query（给模型看），
        一次取姓名（给表单预填用）。读一次缓存下来，别打两遍表。
        """
        if self.bitable is None or not self.bitable.configured:
            return None
        if not self.settings.bitable_profile_table_id:
            return None
        try:
            rows = await self.bitable.list_records(self.settings.bitable_profile_table_id)
        except Exception as exc:  # 查不到画像不该挡住对话
            logger.warning("读画像表失败（对话继续，只是没有个性化）：%s", exc)
            return None
        for row in rows:
            # `飞书账号` 是用户自己选的；`创建人` 是系统自动记的提交人。
            # 后者只在"加字段之后新提交"的行上才准（历史行会被回填成字段创建者），
            # 所以这里**认其中一个即可**，不去纠结谁更权威。
            if open_id in _as_open_ids(row.get("飞书账号")):
                return row
        for row in rows:
            if open_id in _as_open_ids(row.get("创建人")):
                return row
        return None

    def _with_profile(self, profile: dict[str, Any] | None, text: str) -> str:
        """把**提问者本人的画像**拼在问题前面，一起送给对话智能体。

        ## ⚠️ 为什么必须由 gateway 来做（实测，2026-10-17）

        飞书的 **open_id 是「按应用」算的** —— 同一个人，两个应用下是两个 ID：

            gateway（自建应用）读画像表   → 谢国辉 = ou_87ad…
            飞书消息事件的 sender_open_id → 谢国辉 = ou_87ad…   ← 对得上 ✅
            对话智能体通过插件读画像表     → 谢国辉 = ou_1b65…   ← 另一个应用，对不上 ❌

        所以**不能指望对话自己去查"我是谁"** —— 它拿到的 ID 和表里的永远对不上，
        表现为「还没找到你的画像信息」，**而且不报错**。

        gateway 这边天然对得上（同一个应用读同一张表），所以由它查好、拼进去。
        """
        line = _profile_line(profile) if profile else ""
        if not line:
            logger.info("没有画像（对话走通用推荐）")
            return text
        return "【我的画像】" + line + "\n\n" + text

    async def _name_of(
        self, open_id: str, profile: dict[str, Any] | None
    ) -> str:
        """这个人的**姓名** —— 表单预填要用。

        顺序：画像表里的 `姓名` → 飞书通讯录。
        通讯录那条要 `contact:contact.base:readonly` 权限，**没开就返回空**，
        那就不预填 —— 别为了预填把回复发失败。
        """
        name = flatten_text((profile or {}).get("姓名"))
        if name:
            return name
        resolver = getattr(self.app, "resolve_user_name", None)
        if resolver is not None:
            try:
                return await resolver(open_id)
            except Exception as exc:  # noqa: BLE001 —— 预填失败不该影响回复
                logger.info("查通讯录姓名失败（不预填）：%s", exc)
        return ""

    async def _respond(self, open_id: str, text: str) -> str:
        """生成回复 —— **真调 GeniOS 对话型智能体**。

        没配 `GENIOS_CHAT_*` 时就退化成固定话术（本地开发/没凭据时也能跑通链路）。
        """
        if self.genios_chat is None or not self.genios_chat.configured:
            return PLACEHOLDER_REPLY
        profile = await self._profile_row(open_id)
        conversation = await self._conversation_id(open_id)
        prompt = self._with_profile(profile, text)
        try:
            reply = await self.genios_chat.chat(self._api_user, conversation, prompt)
        except GeniosChatError as exc:
            # ⚠️ 实测（2026-10-16）：某些**旧会话**上，工作流会跑完但 `message` 帧里没有正文，
            # 而**新建一个会话就正常**。这里换新会话重试一次 ——
            # **但日志照记**，别把问题掩盖掉（根因还没查清）。
            logger.warning("旧会话没出正文，换新会话重试一次：%s", exc)
            fresh = await self.genios_chat.create_conversation(self._api_user)
            await self._remember_conversation(open_id, fresh)
            reply = await self.genios_chat.chat(self._api_user, fresh, prompt)
        name = await self._name_of(open_id, profile)

        # ⚠️ **没画像的人去发组队需求，是白费劲** —— 匹配要靠画像里的技能/校区。
        # 所以在发需求链接的那条回复前面，补一条画像链接（决策：方案 B，2026-10-17）。
        #
        # 这里只做**一个机械判断**："这条回复里有没有需求表单的链接" +
        # "画像表里有没有这个人"。**不是**在判断"这个人合不合适" —— 那条铁律说的是智能逻辑。
        if profile is None and self._mentions_request_form(reply):
            reply = self._need_profile_note(name) + reply

        # 表单链接按人预填（`forms.py`）。**不管哪个分支发出来的，都在这里统一处理** ——
        # 画布上的提示词只写不带参数的干净链接，个性化是 gateway 的事。
        return personalize_links(
            reply,
            name=name,
            profile_form_url=self.settings.feishu_profile_form_url,
            request_form_url=self.settings.feishu_request_form_url,
        )

    def _mentions_request_form(self, text: str) -> bool:
        url = (self.settings.feishu_request_form_url or "").strip()
        return bool(url) and bool(text) and url in text

    def _need_profile_note(self, name: str) -> str:
        """"先去建画像"那条前置说明。名字已知时明说已经填好了。"""
        url = (self.settings.feishu_profile_form_url or "").strip()
        if not url:
            return ""
        prefilled = "姓名和飞书账号我已经帮你填好了，" if name else ""
        return (
            f"还差一步：先花 **30 秒**填个画像（{prefilled}你只要选一下技能和校区就行）：\n"
            f"{url}\n\n"
            "填完再发需求 👇\n\n"
        )
