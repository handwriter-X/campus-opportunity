# 校园机会搭子 · 项目手册

> 这份手册讲**这套系统是怎么运转的**：每一层在干什么、一次请求的数据怎么流、以及
> **鉴权为什么会出问题**（机制层面）。
>
> 采集端（We-MP-RSS）按你的要求跳过 —— 只把它当成"往 `/ingest` 投文章的东西"。
>
> 相关文档：`HANDOVER.md`（交接）、`AGENTS.md`（给 agent 的规则）、
> `docs/findings.md`（实测账本）、`docs/module2_team_matching.md`（模块二设计）

---

# 一、这个项目是什么

一句话：**把校园公众号里的机会变成结构化数据，并帮学生组队。**

分成两块业务：

| 模块 | 干什么 | 终点 |
| --- | --- | --- |
| **模块一 · 机会发现** | 公众号文章 → 判断是不是机会 → 抽取字段 → 推送 | 学生收到飞书卡片 |
| **模块二 · 组队匹配** | 学生发组队需求 → AI 找队友并说明理由 → 双方确认 | 学生收到「推荐队友」卡片 |

**三个角色，边界很清楚：**

```
┌──────────────────────────────────────────────────────────────────┐
│  飞书多维表格 —— 业务数据的**唯一事实源**（决策 D9）              │
│  机会汇总 · 队友画像 · 组队需求 · 邀请                            │
└──────────────────────────────────────────────────────────────────┘
        ▲ 读写                                  ▲ 表单/视图/按钮
        │                                        │
┌───────┴────────┐                    ┌──────────┴─────────┐
│    GeniOS      │                    │       学生         │
│  **智能层**     │                    │     （飞书）        │
│  判断·抽取·校验  │                    └────────────────────┘
│  匹配·生成理由   │
└───────▲────────┘
        │ 提交 / 轮询
┌───────┴──────────────────────────────────────────────────────────┐
│  campus-gateway —— **搬运层**（不做任何判断）                     │
│  收文章 · 派发 · 轮询取回 · 收发飞书消息 · 轮询表格状态            │
└──────────────────────────────────────────────────────────────────┘
```

**一句话记住三条边界：**

1. **智能在 GeniOS**（铁律 1）—— 判断、抽取、校验、匹配、生成理由
2. **数据在飞书多维表格**（D9）—— 业务数据不在本地
3. **gateway 只搬运** —— 它**不做**"这是不是机会""该推给谁"这类判断

---

# 二、gateway 是什么（结合代码）

**gateway 是一台"传送带"**，不是大脑。它有三类职责：

```
gateway/app/
├── main.py            FastAPI 装配 + lifespan（谁在启动时被创建）
├── ingest.py          POST /ingest        ← 接收文章
├── worker.py          后台循环：派发 → 轮询 → 落库 → 推送
├── genios_client.py   打 GeniOS 的**流程编排型**接口
├── genios_chat.py     打 GeniOS 的**对话型**接口（另一族 API）
├── feishu_app.py      飞书自建应用：tenant token + 发消息
├── bitable.py         飞书多维表格：读写记录 + 字段映射
├── match_flow.py      模块二的编排：轮询需求 → 派发匹配 → 发卡片 → 处理回调
├── match_cards.py     卡片 A / 卡片 B 的构造
├── chat_flow.py       对话编排：收消息 → 调对话智能体 → 回消息
├── store.py           SQLite：文章队列 + 状态机
└── models.py          SQLAlchemy 模型
```

## 2.1 对外接口只有 4 个（+2 个调试用）

| 路由 | 谁调 | 鉴权 |
| --- | --- | --- |
| `POST /ingest` | 采集端（We-MP-RSS） | `X-Ingest-Secret` |
| `POST /opportunities` | （**历史遗留**）GeniOS 旧方案的回写端点 | `X-Internal-Secret` |
| `GET /opportunities` | 内部只读 | 默认免鉴权（`REQUIRE_AUTH_FOR_GET=1` 可收紧） |
| `POST /push` | 内部触发推送 | `X-Internal-Secret` |
| `GET /health` | 运维 | 无 |
| `POST /_debug/echo`、`/ingest/_debug` | 探针 | 无（`DEBUG_ENDPOINTS_ENABLED` 控制） |

> ⚠️ **`POST /opportunities` 现在其实已经用不上了** —— 决策 D9 之后，
> 机会数据由 worker **直接写多维表格**，不再需要 GeniOS 回写 gateway。
> 留着是为了兼容旧方案，可以在清理时删掉。

## 2.2 三个常驻循环

`main.py` 的 lifespan 里创建、`scripts/match_service.py` 里也创建同类对象：

### ① 文章 worker（`worker.py::ArticleWorker`）

```
while True:
    article = claim_next()          # SQLite: status queued → dispatched
    dispatch(article)               # 调 GeniOS 流程编排型
    poll 结果                       # query_run_app_process
    _deliver(): 写表 + 推飞书
```

**状态机在 SQLite 的 `articles` 表**（`store.py`）：

```
queued ──认领──▶ dispatched ──成功──▶ done
   ▲                  │
   └──失败重试────────┘（指数退避，超次 → failed）
```

> **注意**：这里的 SQLite 存的是**管道状态**（队列、重试、任务 id），
> **不是业务数据** —— 业务数据在多维表格。这条边界别混。

### ② 匹配轮询（`match_flow.py::MatchFlow`）

```
每 45 秒：
  list_records(【组队需求】)         # 读全表
  筛出 状态 ∈ {"", 待匹配}
  逐行: update(状态=匹配中) → 派发 GeniOS 匹配工作流 → 读回 → 发卡片 A
```

**状态机在多维表格里**（`【组队需求】` 的两个字段）：

| 字段 | 谁写 | 流转 |
| --- | --- | --- |
| `状态` | gateway 认领 + **GeniOS 定结果** | 待匹配 → 匹配中 → 已匹配 / 已结束 |
| `通知状态` | **只有 gateway** | 未通知 → 已通知（幂等，防重复推卡） |

> ⚠️ **空状态也算"待匹配"** —— 因为表单里把「状态」这道题拿掉了，
> 新提交的行状态是空的。**别改成只认 `"待匹配"`**，否则新需求永远等不到匹配。

### ③ 飞书长连接（`scripts/match_service.py`）

**一个进程、一条 WebSocket，同时收两种事件：**

```
飞书 → 我们（出站 WebSocket，零 inbound）
   ├── card.action.trigger     → MatchFlow.handle_card_action
   └── im.message.receive_v1   → ChatFlow.handle_message
```

> **为什么必须在一个进程里**：飞书一个应用只允许一条长连接。
> 两个进程抢同一个应用的长连接会互相顶掉。

---

# 三、三个智能体长什么样

## 3.1 模块一 · 机会抽取（**流程编排型**）

```
Start ──▶ 大模型节点（判断 + 抽取）──▶ 代码节点（三层校验）──▶ End
```

| 节点 | 干什么 | 文件 |
| --- | --- | --- |
| 大模型 | 判断是不是机会 + 抽字段，输出 JSON | `genios/prompts/step1_extract.md` |
| 代码 | **三层校验**：格式层 / 逻辑层 / 依据层（字段的原文片段必须真在原文里出现） | `genios/code_nodes/parse_and_validate.py` |

**输入**：文章（`article_id` / `text` / `title` / `url` / `publish_time` …）
**输出**：`{"is_opportunity": bool, "items": [...], "issues": [...]}`

## 3.2 模块二 · 组队匹配（**流程编排型**）

```
Start
  │
  ├─▶ 插件 search_records（读【队友画像】）
  │        │
  ▼        ▼
代码01 硬筛（校区 ∧ 投入 ∧ 技能交集）
  │
  ▼
大模型01 精排 + **生成两个视角的理由**
  │
  ▼
代码02 校验 + **防幻觉映射**（idx → open_id）
  │
  ▼
代码03 组装 `update_records` 的入参
  │
  ▼
插件 update_records（写回【组队需求】行）
  │
  ▼
End
```

| 节点 | 关键设计 | 文件 |
| --- | --- | --- |
| 代码01 | **硬筛**用枚举字段（校区/投入/技能）—— 这是**查询不是判断**，且能把 500 人压到 25 人 | `genios/code_nodes/match_hard_filter.py` |
| 大模型01 | **匹配的本质是"互补"不是"相似"** —— 输入必须带"发起人自己会什么"，否则只会找"和需求描述像的人" | `genios/prompts/step2_match.md` |
| 代码02 | **大模型只回编号 `idx`，由代码映射回真实 open_id** —— 否则它会编造用户账号，而且不报错 | `genios/code_nodes/match_validate.py` |
| 代码03 | 把 `matches` 数组变成表格的一行（含「匹配理由」和「邀请理由」两个字段） | `genios/code_nodes/build_update_payload.py` |

**两个理由，视角不同：**

| 字段 | 「你」指谁 | 给谁看 |
| --- | --- | --- |
| `匹配理由` | **发起人** | 发起人的卡片 A |
| `邀请理由` | **候选人** | 被邀请人的卡片 B |

> 只给一个理由的话，被邀请人会读到「你缺的正是设计」——说的是别人，一头雾水。

## 3.3 对话智能体（**对话流型**）

```
Start（query / user_id / conversation_id / chat_histories —— 平台内置只读）
  │
  ▼
意图识别（开【对话历史】）
  │
  ▼
选择器 ─┬─「查机会」→ 插件读【机会汇总】+ 插件读【队友画像】→ 代码拼上下文 → 大模型作答 → End
        ├─「找队友」→ 大模型：回一个表单链接 → End
        └─「其他」  → 大模型闲聊兜底（**不读任何表**）→ End
```

**为什么是"对话流型"而不是"对话型"或"流程编排型"：**

| | 自主思考 | 多轮+记忆 | 编排工作流 | 用途 |
| --- | --- | --- | --- | --- |
| 对话型 | ✅ | ✅ | ✅ | 开放式场景 |
| **对话流型** | ❌（严格按画布） | ✅ | ✅ | ⭐ **我们的对话入口** |
| 流程编排型 | ❌ | ❌（单轮异步） | ✅ | 批处理（模块一/二） |

**两个硬理由**：
1. 开始节点**白给 `user_id`（飞书 open_id）和 `conversation_id`** —— 身份和多轮都不用自己维护
2. 每轮**严格按画布走** —— 可控、可解释、答辩时能指着讲

**代码节点 `chat_context.py` 干两件事**：
- 把表格行拼成人话（大模型看不懂 `{"报名截止": 1792915199000}`）
- 按字段特征认出"哪是机会表、哪是画像表"（**不靠变量名** —— 变量名是人随手起的）

---

# 四、完整业务流程

## 4.1 流程 A：公众号文章 → 机会入库 → 推飞书

**这是一次完整请求的数据流，逐步带函数名。**

```
① 公众号发新文章
        │
        ▼
② 采集端 POST /ingest          （Header: X-Ingest-Secret）
   { "articles": [ {"url", "title", "mp_name", "content", "publish_time"} ] }
        │
        ▼
③ gateway: ingest.py
   ├─ parse_payload()              适配成统一形状（adapters/wemp_rss.py）
   ├─ article_id = sha256(url)     文章级幂等键
   ├─ is_backfill(publish_time)   早于 ENABLE_PUSH_AFTER → backfill（不推送）
   └─ ingest_article()            写 SQLite articles 表，status=queued
        │
        ▼
④ worker.run_forever()
   ├─ claim_next()                 status: queued → dispatched
   └─ _process(article_id, payload)
        │
        ▼
⑤ GeniosClient.dispatch(payload)
   POST https://coze.nankai.edu.cn/api/proxy/api/v1/run_app_workflow
   Header: Apikey: <GENIOS_API_KEY>
   Body:   { "InputData": "<payload 的 JSON 字符串>",
             "UserID": "campus-gateway",
             "NoDebug": true }
   ← { "runId": "01M4..." }
        │
        ▼
⑥ GeniOS 执行：Start → 大模型(判断+抽取) → 代码(三层校验) → End
   ← { "is_opportunity": true,
       "items": [ {"name", "type", "signup_deadline", "evidence", ...} ] }
        │
        ▼
⑦ worker 轮询
   POST /api/proxy/api/v1/query_run_app_process
   Body: { "RunID": "01M4...", "UserID": "campus-gateway" }
   ← { "status": "success", "output": "<JSON 字符串>" }
        │
        ▼
⑧ worker._deliver()
   ├─ extract_llm_payload()        递归剥信封（output 是字符串，里面还有字符串）
   ├─ _store_opportunities()
   │    └─ opportunity_row()       字段映射 + 类型转换（见 §5.3）
   │         └─ BitableClient.create_records()
   │              POST /open-apis/bitable/v1/apps/{app}/tables/{tbl}/records/batch_create
   │              Header: Authorization: Bearer <tenant_access_token>
   │              Body: { "records": [ { "fields": {...} } ] }
   └─ FeishuAppClient.send_text()  推卡片/文本
         POST /open-apis/im/v1/messages
         Header: Authorization: Bearer <tenant_access_token>
         Body: { "receive_id": "ou_…", "msg_type": "interactive", "content": "<卡片 JSON>" }
```

## 4.2 流程 B：组队需求 → 匹配 → 邀请 → 接受

```
① 学生填【发布组队需求】表单
   → 【组队需求】表多一行（状态为空 / 待匹配）
        │
        ▼  每 45 秒
② match_service → MatchFlow.poll_once()
   ├─ BitableClient.list_records(【组队需求】)
   └─ is_pending(row)               状态 ∈ {"", 待匹配}
        │
        ▼
③ _process_row(row)
   ├─ update_record(状态=匹配中)     ← **认领**，防下一轮重复派发
   ├─ _build_request_json()          需求字段 + **发起人画像**（关键：算"互补"要用）
   └─ GeniosClient(MatchGeniosProfile).dispatch()
     POST .../run_app_workflow  （body 结构同流程 A，但用的是**匹配工作流的 key**）
        │
        ▼
④ GeniOS 匹配工作流（六个节点，见 §3.2）
   读画像 → 硬筛 → 精排 → 校验 → 组装 → **写回【组队需求】这一行**
        │
        ▼
⑤ gateway 读回该行
   → build_match_card()   卡片 A：列候选人 + 每人一个「邀请 TA」按钮
   → FeishuAppClient.send_card(target=发起人 open_id)
   → update_record(通知状态=已通知)   ← 幂等
        │
        ▼
⑥ 发起人点「邀请 TA」
   飞书 → 长连接 card.action.trigger
   value = {"action":"invite","request_record_id":"rec…",
            "candidate_open_id":"ou_…","candidate_index":0}
   operator.open_id = **点按钮的人**（飞书给的，不可伪造）
        │
        ▼
⑦ MatchFlow.handle_card_action()
   ├─ **幂等**：同一个人对同一条需求，重复点不会建第二行
   ├─ 读该行的「邀请理由」第 N 条（**给候选人看的那份**）
   ├─ create_records(【邀请】表, 状态=待回应)
   └─ build_invite_card()  卡片 B → 发给被邀请人
        │
        ▼
⑧ 被邀请人点「我想加入」
   → 长连接回调 → **校验 operator 确实是被邀请人**
   → update(邀请.状态=已接受)
   → 发卡片给发起人「🎉 谢国辉 接受了你的组队邀请」
```

## 4.3 流程 C：飞书对话

```
① 学生给机器人发消息
        │
        ▼
② 长连接 im.message.receive_v1
   { "sender_open_id": "ou_…", "chat_id": "oc_…",
     "chat_type": "p2p", "content": "{\"text\":\"有哪些适合我的比赛\"}" }
        │
        ▼
③ ChatFlow.handle_message()
   ├─ parse_message_event()      摊平事件（content 是 JSON 字符串，再解析一次）
   ├─ **只回单聊**（p2p）        群里逐条回话会把人烦死
   └─ _respond(open_id, text)
        │
        ▼
④ _conversation_id(open_id)
   ├─ 查 SQLite chat_sessions    open_id → AppConversationID
   └─ 没有就 create_conversation   POST /api/proxy/api/v1/create_conversation
                                    Body: {"userID": "ou_…"}
                                    ← {"Conversation": {"AppConversationID": "db8o…"}}
        │
        ▼
⑤ _with_profile(open_id, text)      ← **关键一步，见 §5.2**
   读【队友画像】→ 按 open_id 找到本人 → 拼成
   "【我的画像】大三 · 计算机学院 · 津南 · 技能：设计、编程\n\n" + 原问题
        │
        ▼
⑥ GeniosChatClient.chat()
   POST /api/proxy/api/v1/chat_query
   Body: { "userID": "ou_…", "AppConversationID": "db8o…", "Query": "<带画像的问题>" }
   ← text/event-stream（SSE）
        │
        ▼
⑦ parse_sse() + reply_of()
   事件序列：message_start → flow_start → flow_end → message_output_start
            → **message（正文在这帧的 answer 里）** → message_cost → message_end
   ⚠️ answer 是**双重编码**的字符串，要递归剥
        │
        ▼
⑧ FeishuAppClient.send_text(target=chat_id)
```

---

# 五、鉴权：六种凭据 + 五个机制级陷阱

## 5.1 六种凭据，各管一段

| # | 凭据 | 谁 → 谁 | 载体 | 有效期 |
| --- | --- | --- | --- | --- |
| 1 | `X-Ingest-Secret` | 采集端 → gateway | HTTP 头 | 静态（`.env`） |
| 2 | `X-Internal-Secret` | （旧方案）GeniOS → gateway | HTTP 头 | 静态 |
| 3 | **GeniOS API Key（流程编排型）** | gateway → GeniOS | `Apikey` 头 | 平台生成，永久/限期 |
| 4 | **GeniOS API Key（对话型）** | gateway → GeniOS | `Apikey` 头 | 同上 |
| 5 | **飞书 tenant_access_token** | gateway → 飞书 OpenAPI | `Authorization: Bearer` | **2 小时**，自动刷新 |
| 6 | **飞书 OAuth2 用户授权（多维表格插件）** | GeniOS 插件 → 飞书 OpenAPI | 平台内部 | **按智能体，1~2 天；重新发布会失效** |

> **1/2/3/4 是"我们自己的静态凭据"** —— 配好就一直有效。
> **5/6 是"会过期的授权"** —— 这才是麻烦的来源。

**存储原则**：全部只在 `.env`，不进代码、不进日志、不进 git（`.gitignore` 已忽略 `.env`）。

---

## 5.2 陷阱一：**飞书 open_id 是「按应用」算的**

### 机制

`open_id` 不是"人的身份证"，而是**"这个人 + 这个应用"的组合标识**。
同一个人，在 A 应用下是 `ou_aaa…`，在 B 应用下是 `ou_bbb…`。

### 我们踩的

```
【自建应用 cli_aa4ede…】（gateway 读表 + 飞书消息事件给出）
   谢国辉 → ou_87ad1db716acb0bc2b2d815bbc12dbfc
【探针应用 cli_aa45a6…】（对话智能体通过插件读同一张表）
   谢国辉 → ou_1b6553300df5973e7cef352cba7cf49a
```

对话收到的 `user_id` 是**自建应用视角**的，
而代码节点通过插件读到的是**探针应用视角**的 —— **永远对不上**。

**表现**：`「还没找到你的画像信息（可能你还没填过）」` —— **而且不报错**，看起来像用户没填。

### 处置

**别让两个应用去对同一个 ID。** 让**同一个应用**完成"查 + 用"：

```
gateway（自建应用，天然对得上）读画像 → 拼成【我的画像】… 放进 Query
对话智能体：看到【我的画像】直接用，不再自己去表里匹配
```

代码：`chat_flow.py::_with_profile` + `chat_context.py`（表里匹配只作兜底）

> **通用规则**：跨应用传 `open_id` 一定会踩这个坑。
> （`union_id` 在同租户内是一致的，本该用它 —— 但多维表格的人员字段不返回它。）

---

## 5.3 陷阱二：**多维表格插件的 OAuth2 授权是「按智能体」的，而且会过期**

### 机制

GeniOS 的「飞书多维表格_OAuth2 工具授权插件」用的是 **OAuth2 用户授权**
（`grant_type=Authentication Code`）。它拿到的是一份**用户级 access_token**。

实测的两条规律：

| | |
| --- | --- |
| **① 按智能体分开** | 模块二那个智能体授权过 ≠ 对话流这个智能体也授权过。**每个智能体各要一次** |
| **② 会过期** | 实测约 **1~2 天**；**重新发布画布后也会失效** |
| **③ 按「运行时 userID」绑定** | 同一句提问，换成另一个 `userID` 就报"需要授权"。**这是最隐蔽的一条，见下面 5.3.1** |

### 两种"过期"的长相完全不同

| 智能体类型 | 表现 |
| --- | --- |
| **流程编排型** | `status: interrupted` + `msg` 里**直接给授权链接** |
| **对话流型** | `HTTP 500` + `LarkApiException[91403]: Forbidden` ← **完全看不出是授权问题** |

> ⚠️ **`91403` 的官方含义是"没有云文档权限"**，但在这里是被"授权缺失"触发的。
> **在对话流画布里看到 91403，先怀疑授权过期，别去查表格权限。**

### 为什么这是个大问题

```
3 个智能体 × 每个 1~2 天过期 × 每次改画布重新发布都要重来
```

**⇒ 对"无人值守"是硬伤。** 目前的兜底只有一条：
- `match_service` 检测到 `interrupted` 时，**把授权链接推到飞书**（`match_flow._alert_if_reauth_needed`，30 分钟冷却）

**答辩建议**：前一小时把三个智能体都授权一遍，**然后别动画布**。

---

## 5.3.1 陷阱二之三：**授权是发给「某个 userID」的，不是发给「这个智能体」的**

### 机制

插件的 OAuth 凭据，平台存成一条 **`(插件, 运行时 userID)`** 的记录。

授权链接是**某次运行在某个 userID 下**产生的 —— 点完之后，
平台只把凭据发给**那一个 userID**。换一个 `userID` 再跑，平台认不出来，重新要授权。

### 我们踩的

对话层一开始把**每个学生的 `open_id`** 当 `userID` 传给 GeniOS（看起来最自然：
"谁在说话就是谁"）。结果是：

| `userID` | 结果 |
| --- | --- |
| `ou_auth_check`（授权时那一个） | ✅ 正常读表 |
| `ou_probe_chat`（另一个 id） | ❌ 使用工具 search_records 需要授权 |
| `campus-gateway`（第三个 id） | ❌ 同上 |

**⇒ 每个新同学第一次提问，都会收到一条授权链接。模块三等于不可用。**

### 处置

对话智能体统一跑在**固定的服务身份** `campus-gateway` 下（`GENIOS_CHAT_USER_ID`），
和模块一/二一样。学生是谁由另外两样东西承载：

| 要表达什么 | 靠什么 |
| --- | --- |
| 「我知道这个同学的背景」 | `【我的画像】…` 拼进 Query（`chat_flow._with_profile`，见 5.2） |
| 「多轮记忆各是各的」 | `ChatSession.open_id → conversation_id` |

> ⚠️ **自检脚本必须用同一个 userID**（`scripts/check_auth.py` 已改为读同一个配置）。
> 拿一个"测试专用 id"去自检，结果是**自检绿、线上红** —— 我们确实这样错过一次。

---

## 5.4 陷阱三：**`time.monotonic()` 不计系统休眠**

### 机制

`tenant_access_token` 的过期缓存是用 `time.monotonic()` 比的。

Linux 的 `CLOCK_MONOTONIC` **不计算系统休眠/挂起的时间**。

### 我们踩的

```
02:44  服务启动，换 token（有效期 2 小时）
  ↓ VM 休眠一整夜
10:34  所有飞书调用 99991663 Invalid access token
```

**日志证据**：8 小时里**只有一次换 token 的请求** —— 就是启动那一刻。
缓存以为 token 还新鲜，一直返回那个**早就过期**的。

**表现**：`99991663`，读表、发消息、推卡片**全部失败**。
而同一时刻用 `.env` 凭据新建客户端一切正常 —— 说明**凭据没坏，缓存坏了**。

### 处置

1. **改用墙钟 `time.time()`** —— token 过期是**真实的墙钟时刻**
2. **遇到 `99991663` 清缓存重取一次** —— 不管什么原因都能自愈
   （`FeishuAppClient.invalidate_token()` + `send()` / `BitableClient._call()` 各重试一次）

> **通用规则**：跨度超过几分钟的"过期"，别用 `monotonic()`。
> 它是给"超时"用的，不是给"过期"用的。

---

## 5.5 陷阱四：**飞连零信任网关**（为什么我们没有 inbound）

### 机制

`coze.nankai.edu.cn` 整个域名在飞连后面 —— 外部访问会被 **302 到 IAM 登录页**。

### 关键事实（实测）

| 路径 | 外部可达？ |
| --- | --- |
| `GET /api/proxy/**` | ❌ 302 到 IAM（**GET 不豁免**） |
| `POST /api/proxy/api/v1/**` | ✅ **豁免，API 调用通** |

**⇒ 我们调 GeniOS 是通的；但反过来 GeniOS 打我们的服务，需要公网 —— 做不到。**

这直接决定了整个架构：**所有数据交换都必须由我们主动发起**。

**三条由此推出的设计：**

| 设计 | 原因 |
| --- | --- |
| GeniOS 不通过 HTTP 回写 gateway | GeniOS 打不到我们（要用 cloudflared 隧道，但隧道不稳、URL 每次变） |
| worker 用"提交 + 轮询"拿结果 | 我们主动发起，不需要 inbound |
| 飞书用**长连接**而不是"事件订阅回调" | 长连接是我们**主动连出去**的 WebSocket |

---

## 5.6 陷阱五：**v1 / v3 两代多维表格 API 的写法不同**（不是鉴权，但同属接口契约）

同一张表，两代 API 的字段写法**不一样**：

| 字段类型 | **v1**（gateway/worker/插件用） | **v3**（CLI 回填用） |
| --- | --- | --- |
| **单选** | **字符串** `"竞赛"` | 数组 `["竞赛"]` |
| **关联字段** | **字符串数组** `["rec…"]` | 对象数组 `[{"id": …}]` |
| 人员字段 | `[{"id": "ou_…"}]` | 同 |
| **日期** | **Unix 毫秒** | 毫秒或 ISO 都行 |

**而且 v1 有个阴的**：

```
HTTP 200
{"code": 1254062, "msg": "SingleSelectFieldConvFail"}
```

**状态码是 200，错误在 body 的 `code` 里。** 只看 HTTP 状态会以为成功了。

> **规则**：凡是要写表，先问一句"这是 v1 还是 v3"。
> `BitableClient._call` 一直检查 body 里的 `code`；**调用处还必须 catch 并记日志**，否则失败会被静默咽掉。

---

# 六、一次排查的"套路"（这几轮总结的）

| 症状 | 先查什么 |
| --- | --- |
| 飞书没收到任何消息 | **服务在跑吗** → 长连接还连着吗 → 日志里有 `收到消息` 吗 |
| 收到了但没回复 | 日志里有 `回复失败` 吗 → **`.env` 的 app 凭据还在吗** → token 是不是 `99991663` |
| 回复是「刚才没处理过来」 | 日志里的 stack trace → 通常是 GeniOS 返回无正文（**429 限流**最常见） |
| 画布答"列表是空的" | **代码节点没拿到数据** —— 插件连上了吗？变量名/字段特征对得上吗？ |
| 画布报 `91403 Forbidden` | **插件授权过期**（不是表格权限！） |
| 画布报 `429 TPM` | 模型限流 —— **一次问一句、间隔半分钟** |
| GeniOS 返回 `interrupted` | 插件授权过期，`msg` 里有授权链接 |
| 表格写不进去 | 单选/关联/日期的**写法**对不对（v1 vs v3） |

---

# 七、一页速查

## 关键地址

| 项 | 值 |
| --- | --- |
| GeniOS API base | `https://coze.nankai.edu.cn` |
| 流程编排型端点 | `/api/proxy/api/v1/run_app_workflow` + `/api/proxy/api/v1/query_run_app_process` |
| 对话型端点 | `/api/proxy/api/v1/create_conversation` + `/api/proxy/api/v1/chat_query` |
| 飞书 OpenAPI | `https://open.feishu.cn` |

## 多维表格（base：`<BITABLE_APP_TOKEN>`）

| 表 | table_id |
| --- | --- |
| 机会汇总 | `tblIA4VlukcpQNE7` |
| 队友画像 | `tblbUBezczIB54Th` |
| 组队需求 | `tblvOY1UxwcsHSK9` |
| 邀请 | `tbloPpPgRSmeSk72` |

## 常用命令

```bash
# 测试（期望 209 passed）
cd gateway && ../.venv/bin/pytest

# 起 gateway（HTTP 接口 + 文章 worker）
PYTHONUTF8=1 .venv/bin/python -m uvicorn app.main:app --app-dir gateway --host 0.0.0.0 --port 8000

# 起常驻服务（长连接 + 匹配轮询）
env -u ALL_PROXY -u all_proxy -u HTTPS_PROXY -u https_proxy \
  .venv/bin/python scripts/match_service.py

# 只跑一轮匹配轮询（排查用）
env -u ALL_PROXY -u all_proxy -u HTTPS_PROXY -u https_proxy \
  .venv/bin/python scripts/match_service.py --once --no-listen
```

> **两条环境铁律**：
> 1. **`uvicorn --workers` 必须是 1** —— 后台 worker、限流器、告警去重都是单进程假设
> 2. **所有飞书/GeniOS 调用都要清代理变量** —— 本机有 `ALL_PROXY=socks5://…`，
>    长连接和部分 HTTPS 调用走它容易连不上
