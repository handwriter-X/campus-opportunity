# 探针实验结果与待确认项

> 本文件是「用实验消灭猜测」的账本。每条 ❓ 关闭时必须写：**做了什么、看到什么、结论、证据（真实响应片段/截图路径）**。
> 状态：`❓未决` / `🔄进行中` / `✅已关闭` / `⚠️降级方案`

最后更新：2026-10-09

---

## 进度总览

| 探针 | 内容 | 状态 | 阻塞了谁 |
| --- | --- | --- | --- |
| S1 | GeniOS 流程编排型智能体 API | ✅**已关闭**（2026-10-07，三级实测 + worker 真派发） | — |
| S2-a | 大模型节点能否约束 JSON 输出 | ✅**已关闭**（2026-10-07，节点自带「输出格式」可 JSON） | — |
| S2-b | 代码节点语言/库/超时/出网 | ✅**已关闭**（2026-10-07，Python 3.10；json/re/datetime/zoneinfo 全可用） | — |
| S2-c | HTTP 请求节点出网能力 | ✅**已关闭**（Q4），2026-10-05 | — |
| S3 | We-MP-RSS 真实 Webhook 载荷 | ✅**已关闭**（源码 + 真实载荷双重确认，2026-10-05） | — |
| S4 | 飞书群自定义机器人 | ⬜未做（**已被 S6 自建应用通道替代**，见下） | 阶段 4 卡片版式 |
| S5 | 网络连通矩阵 | ✅**已关闭**（2026-10-05） | — |
| S6 | 飞书自建应用长连接（新增，非原方案） | ✅**已打通**（2026-10-06），推送也走它 | — |
| **S7** | **飞书多维表格能力**（阶段 6 前置，新增） | **🔄 部分完成**（2026-10-14，见文末 S7 实测记录） | 关键项已通，剩按钮/视图/upsert 与 GeniOS 侧 |

> **阶段 0–5 的探针均已关闭或有了替代方案。** 剩下的不是「未知」，而是「还没做」——
> 见文末的「待决 / 待办」。S4 原计划用群自定义机器人 Webhook，
> 但因为服务要跑在被飞连挡着的校内网，改用了自建应用（S6），**S4 不再必要**。
>
> **S7 是阶段 6 的新增探针**，见文末「功能模块二」一节与 `docs/probe_checklist.md`。

---

## Q1 · GeniOS 流程编排型智能体的 API

**问题**：接口地址、鉴权头、请求体格式、异步任务如何查询结果。

**现状**：平台文档在南开飞书知识库「NK-GeniOS知识库 › 智能体发布管理与 API 接入」内，需登录，无公开页面。已知有 APPID 与 API 密钥（永久/限期），但示例是**对话类**智能体，对流程编排型是否适用未知。

**实验步骤**：[人] 见 `docs/probe_checklist.md` S1；[CC] `scripts/probe_genios.py`。

### 🔎 初步勘察（2026-10-05 夜）—— 已拿到凭据，但**还差一个路由名**

用户提供：APPID、API 密钥、配置网址 `https://coze.nankai.edu.cn/api/proxy/api/v1`（凭据只进 `.env`，不写本文件）。

| 发现 | 证据 |
| --- | --- |
| ✅ **GeniOS 底层是 Coze（扣子）** | 域名为 `coze.nankai.edu.cn`；ID 形如 `db26…`（真实 APPID 已脱敏）；S5 里 GeniOS 带来的 `x-trace-*` 请求头格式吻合 |
| ✅ **本 VM 能直连该域名** | `coze.nankai.edu.cn` → `222.30.38.25`（校内 IP），37ms |
| ⚠️ **站点挂在飞连零信任网关后** | 未认证请求 `302` 到 `https://iam.nankai.edu.cn/api/oidc/authorize?...`，响应头 `server: feilian-agw`，且清空 `corplink_at`/`corplink_it` cookie |
| ✅ **但 `/api/proxy/api/v1/*` 不受飞连拦截** | 这些路径返回的是**后端的** `404 page not found`（而非 302），说明 API 前缀能穿过网关 |
| ❌ **路由名未对上** | 试过 `workflow/run`、`workflow_run`、`run`、`chat`、`bots`、`workflows`、`openapi.json`、`swagger.json` —— 全部后端 404。**没有 OpenAPI 描述文件可捞。** |

**当前卡点**：只差「**具体 API 路径 + 请求体结构**」。
**需要用户提供**：飞书知识库「智能体发布管理与 API 接入」下**同层级的「调用说明 / 请求示例」页面全文**
（curl 示例、请求体 JSON、响应 JSON 最关键）。有了它 Q1 基本直接关闭。

> ⚠️ 还没验证的一点：这些 `/api/proxy/**` 调用**是否真的免飞连认证**。
> 404 只说明「路由不存在」，不等于「带正确路由就能通过」。**等拿到真实调用示例再下结论。**

**结论**：_（待用户提供「调用说明」页面）_

### 🎯 已拿到真实调用样本（2026-10-06）—— Q1 的一半关闭，但撞上**架构级硬墙**

用户在浏览器 DevTools 里抓到 GeniOS 控制台的真实请求，**API 约定彻底清楚了**：

```
POST https://coze.nankai.edu.cn/api/app?Action=SubmitWorkflowDebug&Version=2023-08-01
body: {"ID":"db113054shhbpg8v86og", "InputData":"{\"text\":\"gd\"}", "WorkspaceID":"personal-12602"}
      → 返回 RunId（如 01M47P105SE7Y9B60RX1DCCGT0）

POST https://coze.nankai.edu.cn/api/app?Action=QueryDebugProcess&Version=2023-08-01
body: {"RunId":"01M47P105SE7Y9B60RX1DCCGT0", "WorkflowId":"db113054shhbpg8v86og", "WorkspaceID":"personal-12602"}
```

| Q1 的问题 | 答案 |
| --- | --- |
| 接口风格 | **字节系「`?Action=X&Version=2023-08-01`」查询参数约定**（Coze 系） |
| 请求体格式 | **`InputData` 是「字符串化的 JSON」**（`"{\"text\":\"gd\"}"`），**不是嵌套对象** —— 最易踩的坑 |
| 异步怎么查结果 | **提交返回 `RunId`，再用 `QueryDebugProcess` 轮询**（Q1 的「异步任务如何查询」有答案了） |
| 工作流 ID | `db113054shhbpg8v86og` —— **与 S5 中 GeniOS 打过来时带的 `x-trace-resource-id` 完全一致**，交叉验证成立 |
| 控制台鉴权 | 会话 Cookie + `x-csrf-token` + `workspaceid` 头（个人凭据，会过期） |
| `x-top-region` | `cn-north-1` |

### 🔴🔴 硬墙：**GeniOS 整个域名都在飞连零信任网关后面，API 密钥也进不去**

实测（本 VM，直连）：

```
POST /api/app?Action=GetWorkflow&Version=2023-08-01   （带 API 密钥，无 cookie）→ 302
POST /api/proxy/api/v1?Action=RunWorkflow&...          （带 API 密钥）          → 302
POST /api/proxy/api/v1                                 （带 API 密钥）          → 302

响应：302 → location: https://iam.nankai.edu.cn/api/oidc/authorize?...
      server: feilian-agw
```

**结论**：
- `/api/proxy/**` 那批「后端 404」我之前判读错了——那其实是**飞连网关自己的 Go 风格 404**，
  不是后端应答。**`coze.nankai.edu.cn` 上没有任何路径能在未认证的情况下到达应用层。**
- 拦在**网络/设备层**，跟应用鉴权（API 密钥）**无关**。飞连是企业级零信任客户端
  （装在设备上、由客户端透明完成身份认证），**这台 VM 没装飞连客户端，所以一律 302**。

**对架构的影响（重要）**：方案 §2/§6 假设「gateway 后台 worker **主动调用** GeniOS 流程编排型智能体 API」。
**在当前环境下这条路走不通**，除非：
1. 装飞连客户端到运行 gateway 的机器（需确认学校是否提供 Linux 版、是否允许）；
2. gateway 跑在用户那台已装飞连的 Windows 机器上；
3. **把方向倒过来**：不做「我们调 GeniOS」，改成「**GeniOS 定时拉我们**」——
   由 GeniOS 工作流用**定时触发** + HTTP 节点 `GET` 我们 gateway 的待处理队列，处理完再 `POST` 回写。
   这条路**不需要我们能访问 GeniOS**，只需 GeniOS 能访问我们（**S5 已证明可行**）。

**附带**：控制台那套 API 用的是**个人会话 Cookie**，有效期约 7 天，**不适合做生产依赖**；
且用户本次不慎把真实会话凭据贴进了对话（已提醒其重新登录作废）。**凭据不落盘、不入库。**

**结论**：Q1 的「请求体格式 / 异步查询方式」✅ 已关闭；**「谁来调用、从哪里调用」出现架构级分岔，待用户决策。**

### 🎉 Q1 关闭（2026-10-07）—— 端点、鉴权、请求体、异步查询全部实测确认

**关键突破来自一次「平台身份」的确认**：用户提到 GeniOS 的文档讲的是 **HiAgent**，
且抓包里带着 `I18nextLngHiagent` cookie —— 说明南开的 GeniOS 底层是**火山引擎 HiAgent**
（不是标准 Coze）。顺着 HiAgent 找，拿到了它公开的 SDK 源码（第三个搜索结果的 `hiagent-sdk` 包），
里面有确切的端点拼接代码：

```python
# hiagent_sdk/client.py
def _get_run_workflow_url(self):   return f"{self.base_url}run_app_workflow"
def _get_query_workflow_url(self): return f"{self.base_url}query_run_app_process"
# headers: {'Content-Type': 'application/json', 'Apikey': self.api_key}
```

#### ✅ 实测确认的完整调用方式

```
基址：  https://coze.nankai.edu.cn/api/proxy/api/v1/

提交：  POST {基址}run_app_workflow
        Apikey: <API密钥>
        Content-Type: application/json
        {"InputData": "{\"text\":\"hello\"}", "UserID": "campus-gateway", "NoDebug": true}
        → {"runId": "..."}

查询：  POST {基址}query_run_app_process
        {"RunID": "<runId>", "UserID": "campus-gateway"}
```

| 要点 | 结论 | 证据 |
| --- | --- | --- |
| 鉴权头 | **`Apikey: <密钥>`**（不是 `Authorization: Bearer`） | 第三方 SDK 源码 `client.py:107-112`；无密钥时后端明确回「header:Apikey is empty」 |
| 备用鉴权 | 另有 ak/sk 模式，用 **`X-APP-ID`** 头 | 无密钥时的原始报错原文 |
| **`InputData` 必须是字符串** | 传对象会报 `Mismatch type string with value object`；传 `"{\"text\":\"x\"}"` 才通过 | 两次实测报错对比 |
| 端点路径 | `/api/proxy/api/v1/run_app_workflow`（**带尾斜杠拼接**） | 调用返回结构化 JSON 错误码，证明已到达应用层 |
| 免飞连 | `/api/proxy/**` 前缀**不需要飞连认证** | 对照实验：`/zzz` → 302 到 IAM；`/api/proxy/api/v1/xxx` → 应用层响应 |
| 异步 | 提交返回 `runId`，用 `query_run_app_process` 轮询；响应含 `status`/`nodes`/`steps`/`output`/`costToken` | `models/workflow.py` |

#### 🔴 唯一剩余阻塞：**流程编排型智能体的「API 服务」没开启**

| 用哪个密钥试 | HTTP | 报错 |
| --- | --- | --- |
| 流程编排型（`db26…`） | 401 | `NotEnabled.Warning: Not enabled: API service is disabled` |
| 对话型（`db2t…`，用户新建） | 400 | `only support workflow type app` |

两条拼起来意思很明确：
- 端点只服务**流程编排型**应用（对话型被拒，符合 HiAgent 的设计）；
- 而流程编排型那个应用**当前的 API 服务是关闭状态** —— 需要在 GeniOS 里把它打开。

**下一步（[人]）**：在 GeniOS 里打开那个流程编排型智能体 → 概览 /「后端服务API」→
把 **API 服务开关打开**（或重新生成一次密钥）。然后重跑 `scripts/probe_genios.py`。

#### 对代码的影响

`gateway/app/genios_client.py` 本来就设计成**全部由 `.env` 驱动、不用改代码**。现在只需填：

```
GENIOS_API_BASE_URL=https://coze.nankai.edu.cn
GENIOS_API_PATH=run_app_workflow            # 由实测确定
GENIOS_APP_ID=<流程编排型的 APPID>
GENIOS_API_KEY=<对应密钥>
GENIOS_AUTH_MODE=header
GENIOS_API_KEY_HEADER=Apikey
GENIOS_API_KEY_PREFIX=                      # 空：Apikey 头不带 "Bearer " 前缀
GENIOS_REQUEST_TEMPLATE={"InputData": {payload_json}, "UserID": "campus-gateway", "NoDebug": true}
GENIOS_TASK_ID_FIELD=runId
GENIOS_STATUS_PATH=query_run_app_process
GENIOS_TASK_ID_PATH=RunID
GENIOS_DRY_RUN=0
```

> ⚠️ `InputData` 要的是**字符串**，而 `.env` 模板里 `{payload_json}` 会被替换成**已转义的 JSON 字面量**。
> 所以模板应写成 `{"InputData": {payload_json}, ...}`（不加引号）——这样占位符会渲染成
> `"{\"text\":\"...\"}"` 这个字符串，正好符合要求。**填完必须实跑验证一次。**

#### ✅✅ Q1 正式关闭（2026-10-07）—— 实测三级验证全部通过

用户重新生成了流程编排型智能体的 API 密钥后，**三级验证全通**：

**① 手工 curl —— 提交**
```
POST /api/proxy/api/v1/run_app_workflow     Apikey: <新密钥>
{"InputData":"{\"text\":\"hello from campus-gateway\"}","UserID":"campus-gateway","NoDebug":true}
→ HTTP 200  {"runId":"01M4ABT1PB2VFGSA0M4N7P1V6P","nodes":{},"steps":[],"output":"null"}
```

**② 手工 curl —— 查询异步结果**
```
POST /api/proxy/api/v1/query_run_app_process
{"RunID":"01M4ABT1PB2VFGSA0M4N7P1V6P","UserID":"campus-gateway"}
→ HTTP 200  {"runId":"…","status":"success","steps":["db113054shhbpg8v86p0","db113054shhbpg8v86pg"],
             "costMs":18,"output":"{\"output\":\"hello from campus-gateway\"}"}
```
→ **异步闭环成立**：提交拿 `runId`，查询拿 `status` 与 `output`。工作流 Start→End 原样回显，值正确。

**③ 走我们自己的代码 —— `scripts/probe_genios.py`**
```
→ POST https://coze.nankai.edu.cn/api/proxy/api/v1/run_app_workflow
  headers: {"Content-Type":"application/json","Apikey":"…"}
  body:    {"InputData":"{…}","UserID":"campus-gateway","NoDebug":true}
← HTTP 200  {"runId":"01M4ABYB8RB5KHJZ7DD86TD0AS",…}
```
→ **一行代码没改，只改 `.env`** —— 当初刻意留的「全部由 .env 驱动」的设计奏效了。

**④ 端到端：gateway worker 真派发**
```
GET /health → {"genios_configured":true,"genios_dry_run":false, …}
campus.worker | 已派发文章 #3（task_id=01M4ABZ2VC0ZCJ27ZHDDHMJP9H, dry_run=False）
```
→ 冒烟测试全过，worker **不再是 dry-run**。**阶段 1 至此实质完成。**

**最终 `.env` 配置**（值见 `.env`，此处不记密钥）：
```
GENIOS_API_BASE_URL=https://coze.nankai.edu.cn
GENIOS_API_PATH=/api/proxy/api/v1/run_app_workflow
GENIOS_AUTH_MODE=header
GENIOS_API_KEY_HEADER=Apikey
GENIOS_API_KEY_PREFIX=          # Apikey 头不带 Bearer 前缀
GENIOS_REQUEST_TEMPLATE={"InputData": {payload_json}, "UserID": "campus-gateway", "NoDebug": true}
GENIOS_TASK_ID_FIELD=runId
GENIOS_STATUS_PATH=             # 见下方遗留项，暂空
GENIOS_DRY_RUN=0
```

#### ⚠️ 遗留项（不阻塞，但要知道）

1. **`gateway/app/genios_client.py::_poll` 与实测不符**：它发的是 **GET**，
   而 HiAgent 的 `query_run_app_process` 需要 **POST + `{"RunID":…,"UserID":…}`**。
   所以 `GENIOS_STATUS_PATH` 暂留空 —— 这也**符合 PLAN §9 的设计**：
   「worker 不依赖 GeniOS 返回值，看到 2xx 就算派发成功，机会数据一律等 `/opportunities` 回写」。
   **若将来想要网关侧确认工作流真的跑完**，需要把 `_poll` 改成 POST 带 body（小改动）。
2. **飞连网关有限速**：连续快速请求会被拒（连接直接失败）。探测与压测时要放慢。
3. `run_app_workflow` **只服务流程编排型应用**，对话型会被拒（`only support workflow type app`）。
   这正是 PLAN.md 一直写「发布为流程编排型」的原因。

**对代码的影响**：`gateway/app/genios_client.py` 的 `build_request()` 与 `parse_response()`。填 `.env` 的 `GENIOS_*` 即可，无需改代码。

---

## Q2 · 大模型节点能力（S2-a）—— 🔄 实验 A-1 已通过，A-2/A-3 待做

**问题**：能否约束 JSON 输出；可选哪些模型；单次超时与长度限制。

**实验**：`docs/genios_s2_experiments.md` 实验 A。

**结果（2026-10-07，实验 A-1）**：用户按 A-1 的提示词跑通，节点原始输出：

```json
{"raw_output":"{\"is_opportunity\": true, \"confidence\": 0.98, \"reason\": \"南开大学程序设计竞赛面向全校本科生开放报名，含报名时间和方式，是学生可参加的竞赛机会。\"}"}
```

**结论（部分）**：✅ **大模型节点能吐出纯 JSON**：
- 没有被 ```json 代码块包裹，没有前后废话 —— 提示词约束（「只输出 JSON」）**有效**；
- 内容正确：`is_opportunity: true`、`confidence: 0.98`、理由切题。

⚠️ **一个对阶段 3 很关键的结构事实**：节点的输出信封是 `{"raw_output": "<字符串>"}`，
**里面的 JSON 是「字符串」而不是对象**（转义过的）。所以**下游必须显式解析**：
代码节点要 `json.loads(raw_output)`，或让 HTTP 节点把字符串原样传走。
**这直接决定了阶段 3 的连线方式**——大模型节点后面必须跟一个「解析 JSON」的动作。

**✅ 补充确认（2026-10-07，实验 A-2）**：用户反馈**节点自带「输出格式」设置，且可以选 JSON**
→ **不依赖提示词硬约束，有硬开关**，可靠性有保障。**Q2 关闭。**

**仍未确认**：温度参数能否设到 0/最低；可选模型清单。
（不阻塞阶段 3 —— 提示词里可以要求低温，实际选型等搭工作流时看界面。）

### ⚠️ 关于「一篇文章是否含多个机会」——用户判断与验收条款冲突，待确认

用户反馈：「文章里一般只有一个机会，不会嵌套」。

**但这与方案的两处硬性要求冲突**：
- PLAN §6 节点流程：「一篇文章可含多个机会，所以 `items` 是数组」；
- 验收清单第 3 条：「含多个机会的汇总推文被拆成多条」。

**用户决定（2026-10-07）：保留 `items: [...]` 数组形状**（「先保留，以后可以加」）。
→ 阶段 3 的提示词按数组输出，并注明「通常只有 1 项」。验收第 3 条得以保留。

---

## ✅ 端到端闭环实测（2026-10-07）—— 采集 → 抽取 → 飞书，全链路打通

**链路**：`公众号文章 → /ingest → worker → GeniOS(Start→大模型→End) → 轮询取结果 → 飞书自建应用推送`

**新增的代码**（都是之前 Q1 关闭后解锁的）：

| 改动 | 位置 | 说明 |
| --- | --- | --- |
| `_poll` 从 GET 改成 **POST + body** | `gateway/app/genios_client.py` | HiAgent 的 `query_run_app_process` 要 POST，原实现发 GET 是错的 |
| 新增 `genios_query_template` / `genios_user_id` | `config.py` | 查询体也做成 .env 可配（渲染 {task_id} {user_id}） |
| 新增**飞书自建应用**推送通道 | `gateway/app/feishu_app.py` | 因为服务最终在校内网、公网打不进来，自建应用是唯一可行通道 |
| worker 取回结果后推送 | `gateway/app/worker.py::_notify` | 抽出 `extract_llm_payload` / `format_notification` |
| 推送开关与目标 | `.env` 的 `FEISHU_APP_PUSH_ENABLED` / `FEISHU_NOTIFY_TARGET` | 默认关，避免误发 |

> **关于「worker 要不要依赖 GeniOS 返回值」**：PLAN §9 原本规定不依赖，理由是「Q1 未确认、不知道能否查结果」。
> **该前提已在 2026-10-07 消失**（Q1 关闭，实测可查）。所以现在用返回值做推送。
> 但边界不变：**机会数据仍由 `/opportunities` 回写落库，worker 不写业务表**，返回值只用于通知。

**实测日志（真实文章走完全程）**：

```
18:07:23  campus.ingest | 入库 1 篇（新建 1，重复 0）
18:07:27  POST run_app_workflow      → 200   提交
18:07:30  POST query_run_app_process → 200   3 秒后轮询 ✅
18:07:31  POST im/v1/messages        → 200   飞书消息发出 ✅
```

### 🔴 但发现 Start 节点的参数类型会导致真实文章全部失败

用三组对照载荷直调工作流，结果非常明确：

| 用例 | 结果 | 报错 |
| --- | --- | --- |
| `links` 是数组 | ❌ failed | `input validate failed, err=['https://a.b/c'] is not of type 'object'` |
| **不带 `links`** | ✅ **success**，`steps=[Start, db2t9…（节点 ID 已脱敏）, End]` | — |
| `links` 是空数组 | ❌ failed | `[] is not of type 'object', 'null'` |

→ **Start 节点把 `links` 声明成了 `Obj`，而 gateway 发的是数组**（连空数组也报错）。
**真实文章每条都会在 Start 就挂掉。** 修法：把 `links` 的类型改成**数组**，并关掉「必填」。

**顺带证实**：那条成功的用例证明**大模型节点是连通的**，返回
`{"is_opportunity": false, "confidence": 0.0, "items": []}`（输入是「测试正文」这种无意义串，
判为非机会是对的），`costToken: 1239` 说明模型真的调用了。

### ✅✅ 闭环最终打通（2026-10-07 18:19）—— 含一次真实的机会推送

修掉下面两个坑之后，用一篇**构造的南开竞赛通知**（`eval/samples/webhook_payload_synthetic_nankai_cpc.json`，
标注为测试数据）跑通了正向路径：

```
18:19:39  POST run_app_workflow       → 200   提交
18:19:42  POST query_run_app_process  → 200   第 1 次轮询（任务还在跑 → 继续等）
18:19:45  POST query_run_app_process  → 200   第 2 次轮询 → 拿到结果 ✅
18:19:46  POST im/v1/messages         → 200   飞书推送 ✅
18:19:46  已推送到飞书：文章 #8（is_opportunity=True）
```

**大模型抽取质量很好**（`costToken 2095`，`steps` 三节点全跑）：

```json
{"is_opportunity": true, "confidence": 0.98, "items": [{
  "name": "南开大学第十六届程序设计竞赛", "type": "竞赛",
  "event_start": "2026-11-07T09:00:00+08:00", "event_end": "2026-11-07T14:00:00+08:00",
  "signup_start": "2026-10-10T00:00:00+08:00", "signup_deadline": "2026-10-24T24:00:00+08:00",
  "location": "津南校区计算机学院楼A305机房", "audience": "全校本科生，不限年级与专业",
  "signup_url": "https://example.nankai.edu.cn/cpc-signup", "gongneng_practice": "是",
  "tags": ["竞赛","编程","算法"],
  "type_specific": {"level":"校级","field":"算法设计与程序设计","participation_form":"个人参赛"}}]}
```

- `gongneng_practice` 正确判成「是」（原文写了「可计入公能实践」）
- `signup_deadline` 是 `24:00` 写法，模型原样保留 —— 由代码节点归一化

### 🏛️ 架构调整：**取消「GeniOS HTTP 节点回写」，改由 worker 直接入库**（2026-10-07，用户决定）

**原设计**（PLAN §2/§6）：GeniOS 工作流的 HTTP 节点 `POST gateway /opportunities` 回写落库。

**改成**：worker 轮询拿到 GeniOS 结果后，**自己把机会写进数据库**。

**理由（用户提出，评估后同意）**：

1. 那个 HTTP 节点要传的 JSON，**我们本来就已经从轮询里拿到了** —— 再让它反向递一次是多余的。
   既然 Q1 关闭后确认能查到结果，这条「回写」路径就没有存在价值了。
2. **它带来一个很贵的硬要求**：gateway 必须能被 GeniOS **反向访问到**。
   而这台 VM 在 `192.168.190.128`（VMware NAT 私有网段，出网 IP 是天津电信的 `221.238.245.16`），
   校内根本够不到，只能靠 cloudflared 隧道 —— 而那条隧道**今天已经死了三次**（进程活着、公网不通）。
   去掉回写，**隧道、端口映射、桥接全都不需要了**。
3. **不违反赛制**：判断/抽取/校验仍然全在 GeniOS 内完成；「把结果搬进数据库」是搬运不是理解，
   本来就是 gateway 的职责。

**实现要点**：

- `worker._deliver()`：**先同步入库，再把推送丢到后台异步做**。
  - 入库是本地操作、毫秒级、数据不能丢 → **同步**（实测入库耗时 0.05s）
  - 推送是网络调用、可能慢或失败 → **`asyncio.create_task` 异步**，不占 worker 的并发槽，
    下一篇文章马上能被处理；推送失败也不影响已落库的数据
- 字段名对齐（`event_time_text→event_time_raw`、`signup_method_text→signup_method`、
  `type_specific→extra`…）原本在代码节点里做，现在搬到 `worker.to_opportunity_data()`。
- **`12-10-25` 那条 `10月24日24:00` 被正确归一化成次日 00:00 落库**（实测）。
- 验收第 4 条仍在守：所有 item 都 `duplicate` 时**不重复推送**。
- 关服务时 `worker.drain()` 等后台推送跑完，避免半路掐断。

**实测（合成竞赛通知，标为测试数据）**：

```
23:00:36  POST run_app_workflow      → 200
23:00:39  POST query_run_app_process → 200   轮询 1
23:00:42  POST query_run_app_process → 200   轮询 2 → 拿到结果
23:00:37  入库：第 1 条「南开大学第十六届程序设计竞赛」→ 新建    ← 0.05s
23:00:38  已推送到飞书                                          ← 后台任务，未阻塞
```

落库结果：`status=未开始`（派生正确）、`signup_deadline=2026-10-25T00:00:00+08:00`（24:00 归一化）、
`gongneng_practice=是`、`publish_time=2026-10-08T10:00:00+08:00`、`confidence=0.98`、
`extra.type_specific` 四个字段完整。

**顺带修掉**：第一版漏了 `publish_time`（snapshot 里没带），已补。

**新增测试**：`gateway/tests/test_worker_result.py`（7 项，锁住「剥信封」与「字段名对齐」）。
全套 **109 passed**。

> ⚠️ **代价**：`genios/code_nodes/parse_and_validate.py` 里那套**三层校验暂时没接**——
> 它原本设计成跑在代码节点里。现在的链路是「大模型节点直接出结果 → worker 入库」，
> 所以**格式/逻辑/依据三层校验目前是缺位的**。要不要把它也搬进 gateway、还是接回 GeniOS，
> 待定（见下方待决项）。

---

### 又抓到一个隐蔽 bug：轮询把「还在跑」当成了「已完成」

`_looks_finished` 原本有一条「响应里有 `output` 字段就算完成」的兜底判断。
**但 HiAgent 的 `query_run_app_process` 无论跑没跑完都会返回 `output`**（没跑完是 `null`）——
于是耗时超过 3 秒的任务会在**第一次轮询时被提前取走**，拿到一个空的 output，
表现是日志里的 `is_opportunity=未识别`（**不报错，只是静默拿到空结果**，极难排查）。

修法：**只要有 `status` 字段就一律以 status 为准**，不再看 output 在不在
（`genios_client.py::_looks_finished`）。修完后日志里能看到它**轮询了两次**才取结果。

> 这个 bug 和上面「`runId`/`RunID` 填串」是同一类：**都是静默失败**——
> 不抛异常、日志看着正常，只是结果不对。所以账本里必须记清楚特征，下次一眼能认出来。

### 另一个踩到的坑：两个 `runId` 大小写不是一回事

`GENIOS_TASK_ID_PATH` 我一开始填了 `RunID`，导致取不到任务 ID、轮询被跳过。
**两个名字要分清**：
- 提交**响应**里的字段是 `runId`（小写 r）→ `.env` 的 `GENIOS_TASK_ID_FIELD`
- 查询**请求体**里的字段是 `RunID`（大写 R）→ `.env` 的 `GENIOS_QUERY_TEMPLATE`

---

## 🔴 实测抓到的第一个真实抽取错误：**模型按「当前年份」推断，日期整体错一年**（2026-10-07）

用户在 GeniOS 里跑出的第一份真实大模型输出（「秋日读书会」，学术与学习交流）里发现：

| 模型输出 | 原文标注的星期 | 2026 年实际星期 | 2025 年实际星期 |
| --- | --- | --- | --- |
| `2026-10-18` | 星期六 | 星期日 ❌ | **星期六 ✅** |
| `2026-10-15` | 星期三 | 星期四 ❌ | **星期三 ✅** |

→ **这篇通知是 2025 年的，模型按当前年份推成了 2026，整个日期错了一年。**

**为什么原来的校验抓不到**：逻辑层原有「年份与发布时间相差 ≤ 1 年」的检查，
而 2025↔2026 恰好是 1 年，**正好落在容差内**。

**处置（两处都改了）**：

1. **代码节点新增「星期一致性」校验**（`parse_and_validate.py`）：
   中文通知普遍写「10月18日（星期六）」，**这个星期是原文自带的免费校验锚点**。
   抽取证据片段里的星期标注与规范化日期的真实星期不符 → 记入 `issues`、
   写 `date_conflict` 字段、**降置信度**（实测 0.95 → 0.50，触发 `low_confidence`）。
   ⚠️ 这里**不静默置空**：日期可能仍有用，但必须让人知道它可疑。
2. **提示词新增规则**（`genios/prompts/step1_extract.md` 铁律第 5 条）：
   年份从【发布时间】取；用原文标注的星期去验证；对不上就前后调一年；都对不上就填 `null`，
   **不许硬凑**。

**另一处修复**：`T24:00:00` —— 中文通知里「10月15日24:00 截止」很常见，而
**平台代码节点是 Python 3.10，`fromisoformat` 不接受 `24:00`**（3.11+ 才放宽，所以本地测不出来）。
已在 `_parse_dt` 里手工归一化为次日 `00:00`。

> 这两条都说明：**提示词里「别编造」是不够的，必须有代码层的交叉校验兜底。**

---

## Q3 · 代码节点能力（S2-b）

**问题**：语言（Python/JS）；可用库（`datetime`/`re`/`json`）；超时；能否出网。

**实验**：`docs/genios_s2_experiments.md` 实验 B。

**结果（2026-10-07，首次尝试失败但很有价值）**：用 `return {...}` 作返回值时报错：

```
Exception: run code failed: File "/mnt/code", line 17
    return {"count": len(d.get("items", [])), "ok": True}
    ^^^^^^^^^^
SyntaxError: 'return' outside function
{"level":"error","source":"/go/src/code.byted.org/epscp/codebox/cmd/exec/exec.go:47",
 "message":"exec error: run /usr/local/bin/python3 [/mnt/code]: exit status 1"}
```

**已从报错中确认的事实**：

| 事实 | 证据 |
| --- | --- |
| 代码节点**是 Python 3** | `run /usr/local/bin/python3 [/mnt/code]` |
| 沙箱是**字节自研 codebox** | `/go/src/code.byted.org/epscp/codebox/...`（与「GeniOS 底层是 HiAgent」一致） |
| **脚本在模块层执行，不支持顶层 `return`** | `SyntaxError: 'return' outside function` |
| 输出机制**疑似 stdout** | 实验文档的写法用的是 `print(json.dumps(result))`，且报错提示的是语法而非输出方式 |

→ **写代码节点时必须用 `print(...)` 输出，不能用 `return`。** 这条对阶段 3 的三层校验代码是硬约束。

**结论（2026-10-07，重跑后）**：✅ **能力全部满足，代码节点可以放三层校验。** 实测输出：

```json
{"json_ok": {"a": 1, "b": [2, 3]}, "re_ok": true, "re_groups": ["2026","10","20"],
 "datetime_ok": "2026-10-07T13:29:17.976266", "zoneinfo_ok": true,
 "shanghai": "2026-10-07 13:29:17.976249+08:00",
 "python": "3.10.19 (main, Feb 13 2026, 17:54:39) [GCC 12.2.0]"}
```

| 能力 | 结果 |
| --- | --- |
| Python 版本 | **3.10.19** |
| `import json` | ✅ |
| `import re`（含分组捕获） | ✅ `re_groups = ["2026","10","20"]` |
| `import datetime` | ✅ |
| **`from zoneinfo import ZoneInfo` + `Asia/Shanghai`** | ✅ **可用**，正确得到 `+08:00` |

→ **方案 §6 的三层校验完全可以放在代码节点里**，不需要降级到 gateway `POST /validate`。

**🔴 又一个 codebox 约束（2026-10-07 实测）**：粘贴的代码**不能包含 `from __future__ import …`**：

```
File "/mnt/code", line 16
    from __future__ import annotations
SyntaxError: from __future__ imports must occur at the beginning of the file
```

报错在**第 16 行** → **codebox 会在用户代码前面插入约 15 行**。
所以任何「必须位于文件最开头」的语句（`from __future__`）都不能用。
**我们的代码实际从第 16 行开始。** 已从 `parse_and_validate.py` 移除该行并本地复验通过。

**🔴 接口契约（已解决）**：脚本跑完后仍报错 ——

```
NameError: name 'handler' is not defined
  File "/mnt/code", line 42, in main
    outputs = await call_function(handler, inputs)
```

说明 **codebox 的运行时期望代码里定义一个叫 `handler` 的函数**，并调用 `call_function(handler, inputs)`。
纯 `print` 虽然 stdout 被捕获了，但节点最终判定为失败。
→ **阶段 3 的代码节点要用 `def handler(inputs): ... return {...}` 的形式写，不能用顶层 `print`/`return`。**
（待用户再跑一次确认签名是 `def handler(inputs)` 还是 `async def handler(inputs)`。）

**降级方案**：若代码节点不满足三层校验 → 在 gateway 增加 `POST /validate`，工作流用 HTTP 节点调用。**代码节点无法出网不影响校验**（校验是纯计算），只影响它能否直接回写。

---

## Q4 · HTTP 请求节点出网（S2-c）—— ✅ 已关闭（2026-10-05）

**问题**：能否访问我们的服务器与 `open.feishu.cn`。

**做法**：在 GeniOS 工作流里加 HTTP 请求节点，分别 POST 到我们的隧道 URL 和飞书 Webhook。实测见下方 S5 一节。

**结论**：

| 方向 | 结论 | 证据 |
| --- | --- | --- |
| GeniOS → 我们的服务器 | ✅ **能** | gateway 日志 `222.30.38.86 - "POST /_debug/echo HTTP/1.1" 200 OK`（17:02:17） |
| GeniOS → `open.feishu.cn` | ✅ **能** | 返回 `{"code":19001,"data":{},"msg":"param invalid: incoming webhook access token invalid"}`，`Server: Tengine`、`X-Tt-Logid`、`Via: ens-cache35.cn8519` —— 是**飞书真实 API 的响应**，不是超时 |
| GeniOS → 公网（泛指） | ✅ **能** | 首次失败时拿到 Cloudflare 边缘的完整 530 错误页（带 Ray ID） |

**推论**：HTTP 节点具备完整出网能力，**阶段 3 的「HTTP 节点回写 gateway」与「HTTP 节点直接调飞书 Webhook」两条路都可行**。
飞书那条 19001 是「假 token」的预期报错，说明连通性与 DNS 都正常。

---

## S6 · 飞书自建应用「长连接」事件订阅 —— ✅ 通道已打通（2026-10-06）

**这一项不在原方案里**，是用户提出的：他的服务将来要跑在校内网、被飞连零信任网关挡着，
**公网打不进来**，所以飞书的「事件订阅 → 请求地址」模式不可用。

**为什么必须用长连接**（[人] 实测）：飞书后台保存事件订阅地址时会**先发 `url_verification` 校验、
要求 3 秒内回显 `challenge`**。用户填了地址后**显示 3 秒超时**。
> 补充判断：超时本身不等于「这条路不通」——我们的 gateway 压根没有这个校验端点，
> 而当时的隧道地址可能也已失效。**但对本项目而言长连接才是正确选择**：它是我们**主动连出去**的
> WebSocket，**不需要任何公网地址**，天然绕开飞连的入站限制。

**做法**：飞书官方 Python SDK `lark-oapi 1.7.3` 的 `lark.ws.Client`，
脚本 `scripts/feishu_longconn_probe.py`（只做「收到并打印」，不接业务逻辑——PLAN.md §0 阶段 1 不做飞书自建应用）。

**实测结果（2026-10-06 11:54:12）**：

```
[Lark] connected to wss://msg-frontier.feishu.cn/ws/v2?...
← 收到事件: im.message.receive_v1
{"chat_id":"oc_…（已脱敏）","chat_type":"p2p",
 "message_type":"text","message_id":"om_…（已脱敏）",
 "content":"{\"text\":\"hi\"}"}
```

→ ✅ **「本地服务 ↔ 飞书」接收通道验证通过**，且全程不需要公网地址。
事件落盘 `data/captures/feishu_events.jsonl`。

**踩到的坑**：本机设了 `ALL_PROXY=socks5://...`，**长连接必须清掉代理环境变量**
（`env -u ALL_PROXY -u all_proxy -u HTTPS_PROXY ...`），否则 WebSocket 连不上。
与 cloudflared 那次是同一类问题。

---

## Q5 · 「外部直连数据库」支持的库类型

**现状**：❓ 阶段 1 **不依赖**（读取一律走 gateway `GET`）。将来需要再探测。

---

## Q6 · We-MP-RSS 真实 Webhook 载荷 —— ✅ 已关闭（2026-10-05，读源码）

**问题**：载荷结构、模板可用变量、`webhook.content_format` 实际生效的正文格式。

**做法**：没有部署实测，而是 `git clone --depth 1 https://github.com/rachelos/we-mp-rss`（commit
`126993c81a00466e9a6bbab041eef34ab27abe9c`，2026-09-24），直接读构造请求体的源码。
**构造 payload 的代码就是权威答案**，比「部署 + 点测试」更快也更完整。

### 结论

**请求形态**（`jobs/webhook.py:174-201`）：`POST`，`Content-Type: application/json`，
body 是**渲染后的字符串**（`requests.post(url, data=payload, ...)`，不是 `json=`，所以不自动转义），超时 30s。
自定义请求头从任务的 `headers` 字段读（存 JSON 字符串，`headers.update()` 可覆盖 Content-Type）；
另有 `cookies` 字段。

**默认请求体模板**（`jobs/webhook.py:72-98`，任务模板留空时使用）—— 逐字：

```json
{
  "feed": { "id": "{{ feed.id }}", "name": "{{ feed.mp_name }}" },
  "articles": [
    { "id": "...", "mp_id": "...", "title": "...", "pic_url": "...",
      "url": "...", "description": "...", "publish_time": "..." }
  ],
  "task": { "id": "{{ task.id }}", "name": "{{ task.name }}" },
  "now": "{{ now }}"
}
```

模板上下文顶层只有 4 个键（`jobs/webhook.py:134-139`）：`feed`、`articles`、`task`、`now`。
模板引擎是**自研的 Jinja 子集**（`core/lax/template_parser.py`），**不是 Jinja2**，没有 `|` 过滤器管道；
支持 `{{ var }}` / `{% if %}` / `{% for %}` / `{% set %}` / `loop.last` 等。

### 🔴 三个会直接影响我们采集质量的事实

1. **默认模板里没有 `content` 字段**，只有 `description`（摘要）。也就是说，**照默认模板收，我们只拿得到摘要，拿不到正文**——而报名截止、地点、名额这些恰恰在正文里。
   → 必须在 We-MP-RSS 里**自定义 `message_template`**，显式带上 `{{ article.content }}`。
   注意：只有模板字符串里出现 `"content"` 时才会触发 `content_format` 转换（`jobs/webhook.py:100-101,127-129`）。
2. **`publish_time` 是 `"YYYY-MM-DD HH:MM:SS"` 的 naive 字符串**（`jobs/webhook.py:230-243` 归一化），不带时区。我们是校内服务，按 `Asia/Shanghai` 解释即可（`tz.parse_iso` 已这么做）。
3. **`description` 不做 JSON 转义**（`jobs/webhook.py:152-158` 只处理 `content`）。摘要里出现 `"` 或换行时，请求体是**非法 JSON**。采集端侧要有容错，不能一崩就整条丢。

### 已用源码推导的载荷做实测（`gateway/app/adapters/wemp_rss.py`）

用「源码默认模板 + 真实字段名」构造一份载荷喂给现有适配层，结果：

| 字段 | 结果 |
| --- | --- |
| `url` | ✅ `https://mp.weixin.qq.com/s/abc` |
| `title` | ✅ |
| `publish_time` | ✅ `2026-10-05 09:30:00+08:00`（naive 正确落到上海时区） |
| `text` | ⚠️ 只拿到 `description`（见事实 1） |
| `source` | ❌ **`None`**，notes 报「1 条缺少公众号名」 |

**`source` 取不到的原因**：真实载荷把公众号名放在**信封层** `feed.name`，文章对象里只有 `mp_id`；
而 `_SOURCE_KEYS` 只在文章对象里找 `mp_name`，没有回退到 `feed.name`。
→ 适配层需要加一条「信封 `feed.name` → source」的回退（改动很小，纯增量）。

**对代码的影响**：`gateway/app/adapters/wemp_rss.py`。
**尚未做的**：按方案原意，S3 实测一次（真实 We-MP-RSS 打到 `/ingest/_debug`）复核本页结论，
并把载荷存到 `eval/samples/webhook_payload_*.json`。

### S3 环境准备（2026-10-05）—— 已就绪，等用户扫码

**先回答一个关键问题：需不需要装微信客户端？→ 不需要，任何机器上都不需要。**
读源码确认（`driver/wx.py:308-340,555-567`、`driver/weread_qr.py`、`driver/wx_api.py:337-342`）：
所有登录路径都是「服务端拿到二维码图片 → 用户用**手机微信**扫」，浏览器（Playwright webkit/chromium）
**打包在容器镜像里**，不需要宿主机浏览器、不需要图形界面、不碰桌面版微信。

⚠️ **但「扫码授权」用的微信号，必须是某个公众号（订阅号/服务号）的管理员**——因为它本质是登录
`mp.weixin.qq.com` 后台。源码 UI 也直说了（`web_ui/src/components/WechatAuthQrcode.vue:18-22`）：
「扫码请选择公众号或者服务号，如果没有帐号，请点击下方注册」。
→ 用户决定**注册一个个人订阅号**（免费，身份证+人脸）。**这是采集路线的前提，不是可选项。**

**环境事实**：

| 项 | 结果 |
| --- | --- |
| 镜像 | `ghcr.io/rachelos/we-mp-rss:latest`，**6.35GB**，拉取成功 |
| 容器 | `we-mp-rss` 已起，`0.0.0.0:8001->8001/tcp`，`--restart unless-stopped` |
| Web UI | `http://127.0.0.1:8001/` → 200；VM 地址 `http://192.168.190.128:8001/`（VM 防火墙 inactive） |
| 容器出网 | `mp.weixin.qq.com` 200 ✅ / `weread.qq.com` 200 ✅ |
| 容器 → 宿主机 gateway | `http://host.docker.internal:8000/health` → 200 ✅ |

> 本轮**没有**用 `docker compose up` 起整套，而是单独 `docker run` 了 we-mp-rss、gateway 继续跑在宿主机上。

**🔴 新发现的环境阻塞：Docker Hub 不可达**

```
docker compose build gateway
→ failed to resolve source metadata for docker.io/library/python:3.11-slim:
  dial tcp 65.49.26.97:443: connect: connection refused
```

`registry-1.docker.io` 被墙，**`gateway/Dockerfile` 的 `FROM python:3.11-slim` 拉不到**，
所以 `docker compose up`（含 gateway 服务）目前跑不起来。ghcr.io 反而是通的（we-mp-rss 就是这么拉的）。
**阶段 2 部署前必须先解决**：配国内 registry mirror，或把基础镜像换成可达的源
（上游自己就在用 `docker.1ms.run/...` 这类镜像源，可参考 `compose/docker-compose.dev.yaml`）。

### ✅ 实测载荷 #1：结构与源码推断**逐字吻合**（2026-10-05 23:10）

第一次「测试」送进来的载荷是字面的 `message_type=1`（14 字节，非 JSON）——原因是把
`message_type=1` 填进了「**消息模板**」文本框（它其实是「类型」单选栏的标注）。改正模板后重测，
拿到真实载荷（存 `data/captures/ingest_debug_20261005T231012815965.json`）：

```json
{"feed":{"id":"MP_WXS_3936219608","name":"NKU计算机"},
 "articles":[{"id":"test-article-001","mp_id":"MP_WXS_3936219608","title":"测试文章标题",
   "pic_url":"https://via.placeholder.com/300x200","url":"https://example.com/test-article",
   "description":"这是一篇测试文章的描述内容，用于测试webhook功能是否正常。",
   "publish_time":"2026-10-05 22:40:12","content":"<p>这是测试文章的正文内容。</p>"}],
 "task":{"id":"e7d12436-...","name":"example"},"now":"2026-10-05 23:10:12"}
```

**→ 与 Q6 从源码推出的结构 100% 一致**（含 `feed.name` 在信封层、`publish_time` 是 naive 字符串）。
适配层解析结果：`url/title/source=NKU计算机/text/publish_time(+08:00)` 全部正确，**`notes` 为空**。
信封 `feed.name` 回退实测生效。

**另外两个实测事实**：

1. **「测试」按钮的载荷永远是 HTML 正文、且与 `content_format` 无关。**
   因为 `jobs/webhook.py:108-121` 的测试分支直接塞 mock，`format_content` 只在**非测试**分支
   （`128-129`）调用。（我们设了 `WEBHOOK.CONTENT_FORMAT=text`，日志确认「Content将以text格式发送」，
   但测试载荷的 content 仍是 `<p>…</p>`——正因如此。）
   不过 **我们的 `clean_body` 本来就会去 HTML 标签**，实测 `text` 拿到了干净的「这是测试文章的正文内容。」，
   所以 `content_format` 对我们只是省流量，不是必需。
2. **`content_format` 的配置方式**：`core/config.py:95-99` 把 `config.yaml` 里的
   `${WEBHOOK.CONTENT_FORMAT:-html}` 解析成 `os.getenv("WEBHOOK.CONTENT_FORMAT")`，
   所以 `docker run -e WEBHOOK.CONTENT_FORMAT=text` 即可覆盖（已实测生效）。

### 🔴 实测载荷 #2 之前撞上的硬性路由：**所有采集都要微信读书 Cookie**

「立即运行」真跑了一次，3 个公众号**全部失败**：

```
采集模式:web
[NKU计算机] 微信读书 Cookie 未配置，跳过采集
总计: 3 个公众号   成功: 0 个   失败: 4 个
```

读源码后确认这不是配置问题，而是**这个版本的强制路由**：

- `apis/mps.py:494-505`：**每个**加了前缀的公众号，其 `Feed.id` 都被写成 `f"MP_WXS_{fakeid}"`
  （真正的 mp fakeid 存在 `faker_id` 字段）。
- `jobs/mps.py:70-81`：只要 `mp.id.startswith("MP_WXS_")` 就**强制换成 `weread_mp` 采集器**，
  没有微信读书 Cookie 就 `raise RuntimeError`。

**两条一拼 → 结论：本版本所有公众号采集都依赖微信读书 Cookie；公众号后台扫码只用于「搜索公众号」。**
前端也把两条通道分得很清楚（`App.vue:312` 注释：「微信读书通道独立授权状态（与公众号 haswxLogined 完全区分）」）。

**好消息**：`weread_mp` 的主路径是**分页增量补抓**，不是只能取最新一篇
（`core/wx/model/weread_mp.py:447-453` 的 docstring：「从最新一页开始翻页，采集所有尚未入库的文章，
遇到已入库文章即停止……漏采的文章会一并补齐」）。只有列表接口报 `-2012/-2041` 时才回退到
`/api/mp/cover` 只取最新一篇。→ **阶段 5 的历史文章回补仍然有指望**（`docs/weread-mp.md` 那段
「只返回最新一篇」的描述是**过时的**，与当前代码不符）。

**下一步**：用户在 We-MP-RSS 里做**微信读书授权**（顶栏书本图标 `App.vue:12,187`，或「微信读书管理」
页的「扫码授权」按钮 `WereadManagement.vue:58-61`），用**个人微信**扫，然后重跑「立即运行」。

### 🎉 真实文章载荷实测成功（2026-10-05 23:20）—— Q6 正式关闭

用户完成微信读书授权后重跑，3 个真实公众号（NKU计算机 / 南开大学法学院 / 南开大学哲学院）
各采到 1 篇，**3 篇全部成功，0 失败**。

⚠️ **但第一轮正文是空的**——需要额外打开一个开关：

> `gather.content`（`config.example.yaml:126`→`core/wx/base.py:116`）**默认为 `False`**，
> 意味着**采集时根本不取正文**，webhook 发出去的 `content` 是空串。
> → `docker run -e GATHER.CONTENT=True` 后，`weread_mp.py:488` 的
> `gather_content = bool(Gather_Content or self.Gather_Content)` 生效，正文随采集一起抓。

真实载荷样例已存 `eval/samples/webhook_payload_20261005_real_nku_cs.json`：

```json
{"feed":{"id":"MP_WXS_3936219608","name":"NKU计算机"},
 "articles":[{"id":"MP_WXS_3936219608_MHwM3hJ1-SIl7rWUG1dEfw",
   "mp_id":"MP_WXS_3936219608","title":"遇见未来的自己｜学院邀请2003级校友向乔教授举办新生研讨课",
   "pic_url":"https://mmbiz.qpic.cn/...","url":"https://mp.weixin.qq.com/s/MHwM3hJ1-SIl7rWUG1dEfw",
   "description":"","publish_time":"2026-10-05 23:20:01","content":"9月16日，计算机学院…（642字全文）"}],
 "task":{"id":"e7d12436-…","name":"example"},"now":"2026-10-05 23:20:01"}
```

**适配层实测：`notes` 为空，全字段正确。** `text` 拿到 642 字干净中文全文（库里存的是 22040 字带样式
HTML，`content_format=text` 洗干净了），`source=NKU计算机`（信封回退），`pub_time` 落了 `+08:00`，
`links` 抽出原文链接。

### 🔴 两个必须处理的问题

**问题 1：`publish_time` 不是真实发布时间，而是「采集那一刻」。**

三篇文章的 `publish_time` 分别等于各自被采集的那一秒（`1791213290/92/93`，即 23:14:50/52/53），
`create_time` 也一样。根因：`weread_mp.py:386` 取的是 `mp_info.time`
（= 微信读书把这篇文章索引进该公众号列表的时刻），**不是公众号的发布时刻**。

**影响很大**：
- 我们靠 `publish_time` 判 `mode=live|backfill`（`normalize.py::is_backfill`）会**全部判成 live**，
  首次采集倒灌历史文章时**会真的推送出去**——这正是验收清单第 7 条明令禁止的。
- 方案 §6 要求把「发布时间 + 星期几」放进提示词来解析「本周五」「下周三」，时间错了这个机制就废了。

**问题 2：`description` 恒为空串**，正文只能走 `content`（已打开 `GATHER.CONTENT` 解决）。

### 其他实测观察

- **Headers 字段格式错误**：日志报 `解析headers失败: Expecting value: line 1 column 1 (char 0)`，
  说明「Headers (JSON)」栏的内容不是合法 JSON，**`X-Ingest-Secret` 根本没发出去**
  （捕获到的请求头里确实没有）。这次打的是免鉴权的 `/ingest/_debug` 所以没事，
  但**将来打真正的 `/ingest` 会 401**。需要让用户改成合法 JSON：`{"X-Ingest-Secret": "bf50…"}`
- **微信读书列表接口会 `-2041` 风控**：采集成功几分钟后，我在容器里手工调
  `/web/mp/articles` 连续返回 `-2041`（即使先 `get_token()` 刷新也没用）。
  与 Q10 的风控担忧吻合——**采集频率必须保守**。
- 首轮每个公众号只采到 **1 篇**（`jobs/mps.py:83` 传 `MaxPage=1`）。
  所以「补历史」的能力现在还没被真正验证过，阶段 5 的语料量需要另做打算。

**结论（Q6 最终）**：✅ 载荷结构、字段语义、模板变量全部实测确认，与源码推断逐字一致；
采集链路已跑通到能拿到**带正文的真实文章**。
**遗留**：真实发布时间缺失（问题 1）、历史回补能力未验证。

### ✅ D8 · 关于「发布时间不可靠」的处置 —— 用户判断：稳态下不处理（2026-10-05）

上面「问题 1」看似严重，但用户指出：**We-MP-RSS 常驻 + 每 5 分钟轮询，每次只交付增量，
根本不存在「首次倒灌」场景**，所以每篇文章确实都是新的，标 `live` 是对的。评估后同意，理由比原判断更稳：

1. `backfill` 机制的唯一目的是防验收第 7 条那个「首次启动倒灌历史」。稳态下 `weread_mp`
   每次只给「上一轮之后新出现的」文章，**没有倒灌可防**。
2. **「发布时间」进提示词的问题也一并消解**：采集时刻与真实发布时刻的偏差**上界就是轮询间隔
   （≤5 分钟）**，而提示词要用它解析的是「本周五/下周三」这种粒度，5 分钟误差可忽略。
   → 问题 1 的两个危害其实是同一个，一起消失。
3. **不新增代码，也不改 D1**（D1 是「发布时间缺失→backfill」，这里发布时间不缺失，只是不精确）。

⚠️ **边界条件（阶段 5 必须回头处理）**：一旦为积累评测语料而**大规模补历史**
（调大 `MaxPage`、或长时间停机后一次性补齐几十篇），那批文章会被全部标成 `live` **一起推送**。
**届时必须加保险**（届时首选方案：以「该 `source` 是否首次出现」判定首批为 backfill）。


---

## Q6-附 · 上游部署参数核实（同时关闭 docker-compose.yml 上的 TODO）

对照上游 `compose/docker-compose-sqlite.yaml` 与 `Dockerfile`，`docker-compose.yml` 原有三处错误，已修：

| 项 | 原（TODO/猜测） | 实际（上游源码） |
| --- | --- | --- |
| 镜像 | `ghcr.io/rachelos/we-mp-rss:latest` | ✅ 猜对了 |
| 容器端口 | `8000` | **`8001`**（Dockerfile `EXPOSE 8001`） |
| 数据库环境变量 | `DB_PATH` | **`DB=sqlite:///data/we_mp_rss.db`**（SQLAlchemy URL） |
| Web UI 账号 | 无 | `USERNAME` / `PASSWORD`（上游示例 `admin` / `admin@123`） |

---

## Q7 · 实际选用的爬取项目是否就是 We-MP-RSS

**现状**：❓ 用户未回答。**暂按「是」施工**；若不是，只替换 `gateway/app/adapters/` 下的适配器，`/ingest` 主流程不变。

---

## Q8 · 机会类型 4 类还是 5 类 —— ✅ 已关闭（2026-10-05，读 `docs/` 里的字段体系文档）

**结论**：**4 类**，文档原文是「固定四分类」：

> 竞赛 / 学术与学习交流 / **志愿活动与社会实践** / **校园文体活动**

文档明确写了「该类别（学术与学习交流）不仅包含狭义学术讲座，还覆盖经验分享、**课程辅导**、考前突击、
技能培训、企业分享和交流活动等」→ 你口头提的「课程类信息」确实并入该类，不是第 5 类。

### 🔴 顺带发现：代码里的枚举值与文档**不一致**

| 文档（权威，要求「原样落到 prompt 与校验」） | 代码现值 |
| --- | --- |
| 志愿**活动**与社会实践 | 志愿与社会实践 |
| 校园文体**活动** | 校园文体 |

出现位置：`gateway/app/models.py:OPPORTUNITY_TYPES`、`scripts/probe_feishu_webhook.py`、
`gateway/tests/test_opportunities.py`、`docs/genios_s2_experiments.md`。
按方案 §7.2「文档中的约束要原样落到 prompt 与校验里，尤其是枚举值」，**建议统一改成文档原文**，
否则阶段 3 的 schema/prompt 与文档对不上，评测阶段会全是假失败。**改动会波及测试与卡片脚本，等用户点头再动。**

### 文档通用字段核对（`docs/…最终业务字段体系.docx` 第二节）

机会名称 / 机会类型 / 活动简介 / 活动时间 / 报名截止时间 / 活动地点 / 参与对象 /
人数-名额要求 / 报名-参与方式 / 报名链接 / 是否计入公能实践 / 原始通知链接 / 标签
→ 与方案 §7.2 一致；「是否计入公能实践」文档建议取值 **是 / 否 / 未说明 / 不适用**，
与 `models.GONGNENG_PRACTICE` **完全一致** ✅。

类型专属字段也逐条核过（竞赛 4 项、学术与学习交流 6 项、志愿与社会实践 5 项、校园文体 3 项），
与方案 §7.2 列出的项目一致，细则见文档第三~六节。其中两条**硬约束**要写进 prompt 与校验：
「不得生成原文没有依据的事实」「相关学院/专业**不得由主讲人单位反推**」。

---

## Q9 · 学校飞书租户是否允许创建自建应用

**现状**：❓ 阶段 1 不需要，不阻塞。

---

## Q10 · 公众号抓取稳定性与合规风险

**现状**：⚠️ We-MP-RSS 有「授权过期提醒」功能，但稳定性未验证。首期只订阅少量校内公开账号，阶段 2 做存活监控。

**待办**：确认订阅账号清单与轮询间隔（写进 `.env`，默认保守）。

---

## 环境勘察

### Linux VM（2026-10-05，当前环境）

| 项 | 结果 |
| --- | --- |
| 路径 | `/home/guohui/Desktop/campus oppor`（含空格；**尚未 `git init`**） |
| Python | 只有 `/usr/bin/python3.14`（3.14.4）。依赖全部有 cp314 wheel，实测可用 |
| Docker | ✅ 29.1.3，**免 sudo 可用**（用户在 docker 组）→ S3 可做 |
| cloudflared | ✅ 已装到 `~/.local/bin/cloudflared`（2026.9.3），快速隧道实测可用 |
| 网络 | ✅ 直连出网正常：baidu 200 / weixin 200 / github 200 / **open.feishu.cn 404（可达）** |
| ⚠️ 代理 | shell 里设了 Clash 代理 `ALL_PROXY=socks5://192.168.190.1:7897`。httpx 会读它，缺 `socksio` 就**建 client 时直接崩**（表现为 5 个测试模块全 ERROR，看着像代码坏了）。→ 已把依赖改成 `httpx[socks]` 并写进 `gateway/requirements.txt` |
| 两份 .docx | ✅ **已在 `docs/`**（本次从 Windows 复制过来了），阶段 3 的硬阻塞解除 |
| VM 地址 | `192.168.190.128/24`（VMware NAT）。**GeniOS 在云端，够不着这个内网地址** → 必须内网穿透 |

### 搬家验收（2026-10-05）✅

| 步骤 | 结果 |
| --- | --- |
| 删 Windows `.venv`、重建 | ✅ 原 `.venv` 是 `D:\pycharm\python3.11.0` 的，`Scripts\python.exe` 二进制不兼容 |
| 修 `.env` 行尾 CRLF | ✅ 原为 CRLF（82 行），`sed -i 's/\r$//'` 后 CR 计数 0 |
| 清 `data/` | ✅ 原内容确认是 Windows 冒烟测试产物（User-Agent `Python-urllib/3.11`），无保留价值 |
| `cd gateway && ../.venv/bin/pytest -q` | ✅ **97 passed in 5.07s** |
| `scripts/smoke_test.py` 真实进程端到端 | ✅ **全部通过**（幂等/worker 派发/回写/去重/查询/week=current 全绿） |

> 第一次跑测试是 **25 ERROR + 2 FAIL**，全部由上面的代理/socksio 问题引起，与代码无关。装 `socksio` 后即 97 passed。

### Windows（2026-10-04，历史记录）

| 项 | 结果 |
| --- | --- |
| Python | ✅ 3.11.0（Anaconda）；另有 3.13 |
| git | ✅ 2.55.0.windows.5。**仓库尚未 `git init`** |
| Docker | ❌ 未安装 → 当时只影响探针 S3 |
| 仓库根目录 | 📌 `C:\Users\guohui\Desktop\campus oppor`，不是方案里写的 `campus-opportunity/` |

---

## S5 · 网络连通矩阵（🔄 通道已就绪，2026-10-05）

**已完成（[CC]）**：

1. gateway 起在 `0.0.0.0:8000`（`uvicorn --workers 1`）。
2. `cloudflared tunnel --url http://localhost:8000` 起快速隧道，拿到公网 URL。
3. **已自测隧道真能打到 gateway**：从公网 `curl` 该 URL 的 `/health` 与 `/_debug/echo`，
   gateway 日志出现 `47.178.59.74 - "POST /_debug/echo HTTP/1.1" 200 OK`（源 IP 是 Cloudflare 侧）。
   → 「我们的服务能否被公网访问」这一段**已确认可行**。

> ⚠️ 快速隧道 URL 是临时的：每次重启 cloudflared 都会变，且只要进程停掉就失效。
> 长期方案见 `docs/probe_checklist.md` 步骤 5.3（校园服务器 / 命名隧道）。
> 本次会话当前有效的 URL：`https://obtained-solutions-unique-therapy.trycloudflare.com`（仅当次有效；
> 早先的 `leone-...` 那条已因 QUIC 掉线作废，见下方「第一次尝试」）。

### ✅ 最终结果（2026-10-05 17:02）—— 关键分岔判为「架构不变」

[人] 用修好的隧道 URL 重测，**成功**：

```
gateway 侧日志：  2026-10-05 17:02:17,206 INFO  campus.debug | 收到 GeniOS 探针请求：POST /_debug/echo
                  INFO:  222.30.38.86:0 - "POST /_debug/echo HTTP/1.1" 200 OK
GeniOS 侧响应：   status_code 200，body 是 gateway 的回显
                  {"ok":true,...,"body":{"from":"genios","ts":"test"},...}
```

**两侧证据互相咬合**：GeniOS 响应里 `cf-connecting-ip` 是 `222.30.38.86`，gateway 日志里记录的源 IP
也是 `222.30.38.86` —— 同一个请求，两端都看到了。另外 GeniOS 带来的请求头里有
`x-trace-resource-type: workflow`、`x-trace-run-mode: workflow_debug`、`x-trace-tenant-id: 1000000000`，
确认是**流程编排型工作流的 HTTP 节点**发出的。

> ## 🟢 结论：GeniOS 能主动访问我们的服务器。**落库仍走 `POST /opportunities`，架构不变。**
> 不需要改成「写飞书多维表格」的备选方案；阶段 1 已写好的写入接口全部有效。

**顺带确认的[CC]侧出网**（直连）：`mp.weixin.qq.com` ✅ / `open.feishu.cn` ✅ / github ✅ / baidu ✅。

### 🎯 第一次尝试：GeniOS 打通了「出网」，但隧道当时断了（2026-10-05 16:58）

[人] 在 GeniOS 的 HTTP 节点 POST 到 `.../ _debug/echo`，返回 **HTTP 530** + 一页 Cloudflare 错误页，
标题「Cloudflare Tunnel error」，错误码 **1033**（「Cloudflare is currently unable to resolve it…
Ensure that cloudflared is running」）。Ray ID `a45b3a2f3b38dd4d`，`CF-Ray: ...-HKG`，响应头 `Server: cloudflare`。

**判定：这不是 GeniOS 的问题，是我们隧道的 QUIC 连接掉了。但这一次失败顺带关闭了 Q4 的一半：**

> ✅ **GeniOS 的 HTTP 请求节点能出公网。** 证据：请求真的到达了 Cloudflare 香港边缘并拿回一个完整的
> HTTP 响应（含 Ray ID、CF-Ray、Content-Type 等边缘生成的响应头）。如果是出网被限制，看到的会是
> **连接超时/无法解析**，而不是一个带着 Ray ID 的 530 页面。

**隧道掉线的根因**：cloudflared 日志显示它反复 `Failed to dial a quic connection ... timeout:
no recent network activity`，目标 IP 是 **`198.18.2.110/111`** —— 这是 **Clash 的 fake-IP 段
（198.18.0.0/15）**。本机设了 `ALL_PROXY=socks5://192.168.190.1:7897`，cloudflared 走了代理那条路，
QUIC(UDP) 经 fake-IP 极不稳。

**处置**：改用 `--protocol http2 --edge-ip-version 4`，并**清空代理环境变量**让 cloudflared 直连。
重启后 precheck 全 pass，连到真实 Cloudflare 边缘 IP `198.41.192.77`（lax08），协议 http2。

📌 **教训：cloudflared 要直连、不要走这台机器的 Clash 代理。** 重启命令：

```bash
env -u ALL_PROXY -u all_proxy -u HTTPS_PROXY -u https_proxy -u HTTP_PROXY -u http_proxy \
  ~/.local/bin/cloudflared tunnel --url http://localhost:8000 --no-autoupdate \
  --protocol http2 --edge-ip-version 4
```

### Q4 状态

| 方向 | 结论 | 证据 |
| --- | --- | --- |
| GeniOS HTTP 节点 → 公网 | ✅ **能出网** | 上面那次 530 + Ray ID |
| GeniOS HTTP 节点 → 我们的服务器 | ⏳ 待复测（隧道已换，URL 变了） | — |
| GeniOS HTTP 节点 → `open.feishu.cn` | ⏳ 待测（可顺手关掉 Q4 剩余部分） | — |

---

## 阶段 1 自检（2026-10-04）

**gateway 已建成并跑通端到端**（单元测试 97 项全过 + 真实 uvicorn 进程冒烟测试全过）。

已验证的行为：

| 验收项（方案阶段 1） | 状态 | 验证方式 |
| --- | --- | --- |
| 幂等：同一篇发两次只处理一次 | ✅ | `test_ingest.py::TestIngest::test_idempotent_on_repeat` + 冒烟第 6 步 |
| 历史过滤：backfill 不产生推送标记 | ✅ | `test_ingest.py::TestHistoryFilter` |
| 去重：同一活动两个来源只留一条 | ✅ | `test_opportunities.py::TestDedup` + 冒烟第 9 步 |
| 重试：失败指数退避、超次标 failed | ✅ | `test_worker.py::TestRetry` |
| 鉴权：`/ingest` 与 `/opportunities` 校验共享密钥 | ✅ | `test_ingest.py::TestAuth`、`test_opportunities.py::TestAuth` |
| 时间一律带时区、无 naive datetime | ✅ | `models.UTCDateTime` 对 naive 直接抛错 |
| 中文日志在 Windows 控制台不乱码 | ✅ | 起服务时带 `PYTHONUTF8=1`（README 已写） |

### ⚠️ 我替你做的判断，需要你点头

这些方案里没写死、我按「最不容易出错」的原则定了，**如果你想要别的行为请说**：

| # | 判断 | 理由 | 位置 |
| --- | --- | --- | --- |
| D1 | **发布时间未知 → 判为 backfill（不推送）** | 首次启动倒灌历史文章是验收清单第 7 条明令禁止的。宁可漏推一条，也不能刷屏 | `normalize.py::is_backfill` |
| D2 | **去重键在两个日期都缺时退化为原文时间表达** | 两者都缺时同名不同活动会撞键，此时**合并而非新增**。偏向「漏推可人工补，重复推会让人退群」 | `normalize.py::make_dedup_key` |
| D3 | **`week=current` = 未截止 ∧ 活动未结束 ∧ 报名已开始/本周内开始** | 解读为「本周快照里仍可参与的」。**不限**活动必须在本周内办 —— 下周办但本周还在报名的正是周报该提醒的 | `store.py::_apply_current_week` |
| D4 | **命中重复时只补空缺、不覆盖已有值** | 已有人工/AI 认定的值优先；也避免重发把 `push_status` 打回「未推送」而重复推送 | `store.py::_merge_missing` |
| D5 | **`GET /opportunities` 默认免鉴权** | 校内只读；一个开关 `REQUIRE_AUTH_FOR_GET=1` 即可收紧 | `deps.py::optional_internal_secret` |
| D6 | **`/_debug/echo` 与 `/ingest/_debug` 免鉴权** | GeniOS 的 HTTP 节点不会带我们的密钥，探针 S5 必须能打到。由 `DEBUG_ENDPOINTS_ENABLED` 控制，**对外长期暴露前必须关** | `config.py` |
| D7 | **机会类型按 4 类施工** | 方案 Q8 的默认。四类：竞赛 / 学术与学习交流 / 志愿活动与社会实践 / 校园文体活动（枚举值已于 2026-10-05 按字段体系文档原文对齐） | `models.py::OPPORTUNITY_TYPES` |

### 刻意的设计取舍

- **`/_debug` 端点不写业务库**：只落盘 + 回显。这样探针 S3 反复点「测试」不会污染数据。
- **worker 不依赖 GeniOS 返回值**：看到 2xx 就算派发成功，机会数据一律等 `/opportunities` 回写。
  这直接对应的风险备忘——「若无法查询结果，则不得依赖返回值」。
- **`uvicorn --workers 1`**：后台 worker、限流器、告警去重都是单进程假设，多 worker 会重复派发。
- **采集适配层写成宽容解析**（`adapters/wemp_rss.py`）：Q6 没关闭，所以按候选键名依次试、
  找不到就记进 `notes` 报出来，而不是猜一个字段名写死然后静默丢数据。
  （Q6 已于 2026-10-05 从源码关闭，但**宽容解析先保留**——它没有坏处，且能兜住 `description` 不转义导致的畸形 JSON。）

---

## 待决 / 待办（2026-10-05 新增）

### ✅ 已决（2026-10-11）：三层校验接回 GeniOS 代码节点

改成「worker 直接入库」之后，`genios/code_nodes/parse_and_validate.py` 里那套
**格式层 / 逻辑层 / 依据层**校验**暂时没有接进任何一条链路**：

- 原本设计：跑在 GeniOS 的代码节点里（大模型节点 → 代码节点 → 回写）
- 现在的链路：大模型节点 → End → worker 入库，**中间没有校验**

后果：**模型编造的字段、原文里没有依据的字段，现在会被直接写进库**。
提示词里的约束会降低概率，但没有代码兜底。

用户已确认采用选项 2：**接回 GeniOS 代码节点**（大模型 → 代码节点 → End）。
不把校验搬到 gateway；代码节点里的 `T24:00` 归一化和星期一致性校验随工作流执行。
worker 只消费 End 返回的清洗结果并完成字段搬运、持久化、去重和推送。

### 0. ✅ 已按用户确认落地的两处改动（2026-10-05）

| 改动 | 内容 | 涉及文件 |
| --- | --- | --- |
| 枚举对齐文档 | `志愿与社会实践`→**`志愿活动与社会实践`**；`校园文体`→**`校园文体活动`** | `gateway/app/models.py`、`store.py`、`tests/test_opportunities.py`、`scripts/probe_feishu_webhook.py`、`docs/genios_s2_experiments.md` |
| 适配层 source 回退 | 文章级找不到来源时，回退用信封层 `feed.mp_name`/`feed.name`（纯增量，宽容解析保留） | `gateway/app/adapters/wemp_rss.py::_envelope_source` |

- 新增回归测试 `gateway/tests/test_adapter_wemp_rss.py`（5 项），把 Q6 的源码结论固化。
- 全套测试 **102 passed**（原 97 + 5）；端到端冒烟重跑仍全过。
- `PLAN.md` 里的简称**未改**——它是你的原始方案文档，属于需求原文，不擅自改。若你要同步，说一声。

### 1. We-MP-RSS 里必须自定义 `message_template`

默认模板**不含 `content`**，只能收到摘要。抽取质量直接取决于正文，所以建消息任务时
要把模板内容改成至少包含 `{{ article.content }}`（参考默认模板结构，加上该字段）。
这一步等 S3 实测时一起做，做完把模板原文记到本文件。

### 2. 阶段 3 的阻塞变了

两份 .docx **已到 `docs/`** → 「缺文档」不再是阻塞。
**现在只剩 Q2（大模型节点能否约束 JSON）与 Q3（代码节点能力）** 需要 S2 实验解锁。
S2 实验的可粘贴内容已在 `docs/genios_s2_experiments.md` 备好，等 S1/S5 通了就能做。

### 3. 临时隧道不能当长期方案

`cloudflared` 快速隧道一停就失效、URL 每次变。S5 阶段够用，但阶段 4 验收（真实公众号 → 飞书推送）
需要一个稳定地址。建议尽早决定长期方案（校园服务器 / Cloudflare 命名隧道）。

### 4. ✅ 三层校验接回 GeniOS 代码节点（2026-10-11，用户确认）

用户选择了「接回 GeniOS 代码节点」，不把格式/逻辑/依据校验搬到 gateway。
当前约定为：

```text
Start + 大模型输出 → GeniOS 代码节点 parse_and_validate → End
                                                        ↓
                                      gateway worker 轮询并递归提取 items
```

证据与实现：

- `genios/code_nodes/parse_and_validate.py::handler` 同时收集 Start 原文和大模型输出，
  解析 `raw_output`，执行三层校验，并返回 `items`、`issues`、`confidence`、`low_confidence`。
- End 只需原样返回代码节点对象；worker 的字段适配兼容代码节点已经生成的
  `event_time_raw`、`signup_method`、`extra` 等 gateway 字段，但不执行智能判断。
- 这样校验仍在赛事要求的 GeniOS 工作流内，gateway 继续承担搬运、持久化、去重和推送。

工作流的逐节点配置见 `docs/genios_workflow_spec.md` v2。

### 5. ✅ 工作流导入 schema 以租户真实导出为准（2026-10-11）

用户从当前 NK-GeniOS 租户导出的 `给个机会-20261011-151125.yaml` 是目前最直接的导入
格式证据。对照生成文件和上传报错得到：

- 节点类型必须使用 `Start`、`End`、`LLM`、`Code`；公开 DSL 的小写 `start` 会触发
  `node type: start is not support`。
- 节点依赖保存在节点级 `Depends: [{NodeCode: ...}]`，不使用公开 DSL 的 `edges`、
  `source_node`、`target_node`。
- 顶层工作流采用 `DLVersion: v2`、`Nodes`、`Configs`、`InputVariables`、
  `OutputSchema` 等原生字段。
- 当前接口将顶层 `Workflow.Icon` 解码为 `up.ObjInfo`；生成 JSON 使用
  `Icon: {"uri":"plugin_icon/workflow.png"}`，避免字符串反序列化错误。
- 真实 YAML 的 `UpdatedAt: 0` 不能原样放进 JSON；当前 JSON 解码器把该字段当作
  `time.Time`，会报 `Time.UnmarshalJSON: input is not a JSON string`。生成器改用
  `1970-01-01T00:00:00Z` 这一带引号的 RFC3339 值。

生成器 `scripts/create_genios_workflow.py` 已按该 YAML 的字段集合和依赖结构重写，
并保留仓库中的提示词与代码节点作为内容来源。用户已确认生成的 JSON 在当前租户成功上传；
节点试运行和发布尚未由本次记录覆盖。

### 6. ⚠️ 本地 `.env` 配置已生效，但 GeniOS 后端服务 API 尚未启用（2026-10-11）

在仓库根目录 `.env` 填入当前租户的 API 地址、`Apikey` 鉴权、APPID、API Key、
`runId` 任务字段和异步查询路径后，执行 `python scripts/probe_genios.py`。
请求成功到达 `https://coze.nankai.edu.cn/api/proxy/api/v1/run_app_workflow`，
平台返回 HTTP 401：

```json
{
  "ResponseMetadata": {
    "Error": {
      "Code": "NotEnabled.Warning",
      "Message": "Not enabled: API service is disabled"
    }
  }
}
```

结论：当前 `.env` 的地址、请求体模板和鉴权头已被程序正确读取；下一步必须在 GeniOS
智能体的“后端服务 API”页面启用 API 服务，并确认已发布包含该工作流的流程编排型版本。
启用后重新运行同一探针，不应先修改 API 路径或密钥格式。

### 7. ⚠️ API 启用后首次运行暴露 Code 输出 Schema 类型错误（2026-10-11）

API 服务启用后，`python scripts/probe_genios.py` 返回 HTTP 200 和 `runId`，随后查询任务结果。
工作流成功执行到 Code 节点，但任务状态为 `failed`，平台报：

```text
output validate failed: issues=[] is not of type 'string', 'null'
```

原因是 `genios/code_nodes/parse_and_validate.py::handler` 的真实返回值是字符串数组，
而生成工作流的 Code 输出 Schema 仍把 `issues` 声明成字符串。生成器已修正为 `Type: 5`
（字符串列表），并重新生成：

- `genios/workflows/campus_opportunity_extract.import.json`
- `genios/workflows/campus_opportunity_extract.graph.json`

平台中已经导入的旧工作流不会自动更新，必须重新导入新 JSON，或在 Code 节点把 `issues`
输出变量改为“字符串数组”，再重新试运行。

### 8. ✅ 修正输出 Schema 后工作流端到端试运行成功（2026-10-11）

重新发布修正后的工作流后，真实探针提交返回 HTTP 200 和 `runId`：
`01M4NQSTB289BZQ9EX55YPWRRW`。异步查询结果为 `status: success`，执行步骤完整包含：

```text
Start → LLM → Code → End
```

最终输出为：

```json
{"article_id":"0000000000000000000000000000000000000000000000000000000000000000",
 "is_opportunity":false,"issues":[],"item_count":0,"items":[],"ok":false}
```

这证明当前 API 凭据、异步轮询、工作流节点连线、Code 输出 Schema 和 End 返回均已打通。
本次使用的是探针中的非机会文章，下一步应使用 `eval/samples/` 中的正向机会文章验证抽取字段。

### 9. ⚠️ `items` 的列表对象必须声明嵌套字段（2026-10-11）

正向样例在修正 `issues` 类型后，工作流状态虽然为 `success` 且 `item_count=1`，但 End
返回的 `items` 是 `[{}]`。原因是原始导出 Schema 只在 `items.SubParameters` 中保留了
历史占位字段 `first_item`；平台按 Schema 序列化时会丢弃未声明的机会字段。

生成器现在在 `items.SubParameters` 中声明 gateway 消费的完整字段集合，包括名称、类型、
时间、报名信息、依据、置信度、来源和 `extra`。其中 `confidence` 使用数字类型 `Type: 3`。
更新后的 JSON 需要重新导入并发布后，正向样例的 `items[0]` 才会保留完整对象。

### 10. ✅ 正向机会样例返回完整 `items`（2026-10-11）

重新导入并发布包含完整列表对象 Schema 的工作流后，程序设计竞赛正向样例提交返回
HTTP 200，任务 `01M4NSECM7SAMWZDPRJ4RDRZH5` 最终为 `status: success`，执行步骤仍为
`Start → LLM → Code → End`。

最终结果包含：

- `is_opportunity: true`
- `item_count: 1`
- `items[0]` 含 `name`、`type`、`event_start`、`signup_deadline`、`location`、
  `signup_url`、`evidence`、`confidence`、`source_account` 等字段
- `issues` 仅报告原文没有明确依据的 `event_end` 与 `signup_start`，对应字段被置空

这证明工作流导入、API 调用、异步轮询、代码节点三层校验和 End 的结构化输出已经打通。

---

# 功能模块二 · 项目组队匹配（设计阶段，2026-10-12）

> **本节是设计与决策记录，不是实测记录。** 实测结论要等探针 **S7** 做完再补。
> 完整设计见 **`docs/module2_team_matching.md`**，探针步骤见 `docs/probe_checklist.md` 的 S7。

需求来自赛事「功能模块二」六条：用户画像建立 / 组队需求发布 / 组队需求池展示 /
申请加入 / **AI 匹配队友**（语义匹配 + 生成理由）/ 组队需求管理。
前四条是**状态流转与展示**，只有第五条是智能点。

## ✅ D9 · 架构决定：飞书多维表格成为**业务数据的事实源**（用户决定，2026-10-12）

**用户原话（大意）**：「再加一个多维表格用来存取机会就可以了，本地就不存了。」

| # | 判断 | 理由 | 影响 |
| --- | --- | --- | --- |
| **D9** | **人员信息 / 组队需求 / 机会汇总全部存飞书多维表格，本地不再存业务数据** | ① 多维表格自带表单视图与筛选视图 → 需求 1/2/3 几乎零开发<br>② 自带按钮字段 + 自动化 → 需求 4/6 几乎零开发<br>③ GeniOS 有飞书多维表格 OAuth2 插件，可**直接读写**<br>④ ⇒ **GeniOS 从「被调用的函数」变成「掌握数据与行动的主体」**，符合赛制「在 GeniOS 空间内搭建完整智能体应用」 | SQLite 只保留 `Article`（管道状态）；`Opportunity`/`OpportunitySource` 不再存业务数据 |

**这正面回应了「GeniOS 的智能层体现在哪里」**：当 GeniOS 能自己读数据、自己判断、自己写回、自己推送，
它才是真正的智能体应用；此前它只是被 gateway 调用的一次性函数。

### ⚠️ 附带的**三处能力退化**（必须在施工时重新设计）

| 退化 | 原来靠什么 | 现在怎么办 |
| --- | --- | --- |
| **① 机会级去重** | SQLite `dedup_key UNIQUE` + `_merge_missing`（D4） | 多维表格**没有唯一约束**。改工作流内 `search_records` 查重 → `update_records` / `create_records`；**并把 `WORKER_CONCURRENCY` 降到 1 兜底**，否则并发会写出重复行 |
| **② 推送去重** | `push_status` + 数据库原子性 | 改成「查了再写」，**有窗口**。**验收第 4/5 条「重复文章不重复推送」必须重新实现、重新测** |
| **③ 字段形状** | `evidence` / `extra` 两个嵌套 JSON 列 | 多维表格**没有 JSON 字段类型**。需序列化成文本或拆成扁平字段 |

## 平台事实（2026-10-12 查证）

| 事实 | 来源 | 状态 |
| --- | --- | --- |
| 多维表格**按钮字段**点击可触发自动化流程 | 飞书官方帮助文档 | ✅ 文档 |
| 「点击按钮时」触发条件支持**数据表按钮 / 仪表盘按钮 / 卡片按钮** | 飞书官方帮助文档 | ✅ 文档 |
| 按钮字段执行操作含：打开链接 / 打开表单 / 发送飞书消息 / 新增记录 | 飞书官方帮助文档 | ✅ 文档 |
| 多维表格 API 频控 **50 次/秒**、单次新增 **≤500 条**、单表 **≤20,000 条**、**写入不支持并发**（`1254291 Write conflict`） | 飞书开放平台 API 文档 | ✅ 文档 |
| 写表 scope：`bitable:app` 或 `base:record:create`；应用须是表格**协作者** | 飞书开放平台 API 文档 | ✅ 文档 |
| 从其他数据源**同步的**数据表不支持增删改 | 飞书开放平台 API 文档 | ✅ 文档 |
| **GeniOS 能出网访问 `open.feishu.cn`** | 我们的 S5 实测（返回真实错误码 19001，非超时） | ✅ **实测** |
| 多维表格 OAuth2 插件提供 9 个工具：`create_base` / `create_table` / `delete_table` / `get_base_info` / `list_table` / `create_records` / `update_records` / `delete_records` / `search_records` | 用户提供（平台界面） | ✅ 用户 |
| **OAuth2 token 能否自动刷新** | — | ❓ **生死线，见 S7 步骤 7.4** |

> **上面最后一条是整件事的生死线**：飞书 `user_access_token` 通常 2 小时过期。
> 插件若不能自己刷新 token，稳态运行会断，这个架构就不成立。

## 🔑 三条设计结论（讨论得出，尚未实测）

1. **匹配是「互补」不是「相似」** ⇒ **不能用向量相似度当匹配度**。
   需求「找会设计的」+ 候选人「会编程」（而发起人会编程）才是最优解，但相似度会把它排到最后。
   相似度只能用于**召回**；真正的判断必须让大模型结合**「发起人自己会什么 + 需求缺什么」**推理。
2. **`search_records` 只能做「结构化筛选」，做不了「语义匹配」**。
   插件的 `filter` 是结构化条件表达式，大模型必须自己把自然语言翻译过去；
   「性格合得来」「时间不冲突」这类**表达不了**。⇒ **插件给的是取数能力，不是智能。**
3. **个性化推送要切成两段**：交集（`机会.type ∈ 学生.想看什么`，纯查询）在表格/代码层做；
   **细排、生成推荐语、长期记忆**归 GeniOS。且**必须批量**——逐个学生调用会到
   「100 学生 × 10 篇/天 = 1000 次调用/天」，跑不动。

## 待办

- [ ] **探针 S7**（`docs/probe_checklist.md`）—— 4 条判定，尤其 token 刷新
- [ ] 定四张表的 schema（`docs/module2_team_matching.md` §3）
- [ ] 改 GeniOS 工作流：模块一改为写表格；新增模块二匹配工作流
- [ ] 改 gateway：卸掉业务库与推送，只留采集 + 投递
- [ ] 补测试：尤其「重复文章不重复推送」

## 📌 S7 实测记录（2026-10-14）—— 飞书多维表格能力

**怎么测的**：飞书官方 CLI `@larksuite/cli` v1.0.98 装在 Linux VM 上，
新建探针应用 `cli_aa45a6…`，以**用户身份**（谢国辉）授权 `--recommend` 全量权限。
测试 Base：`https://nankai.feishu.cn/base/<BITABLE_APP_TOKEN>`（**南开租户**）。
按「队友画像」的真实设计建表，造了 5 条数据。

> 用 CLI 而不是 GeniOS 插件来测，是因为**两者调的是同一个飞书 OpenAPI**——
> 结论对插件同样成立。只有「token 刷新」那条是插件特有的，CLI 测不了。

### ✅ 已验证通过

| # | 验的是什么 | 结果 | 备注 |
| --- | --- | --- | --- |
| 1 | 一次调用建 Base + 首表 + 全部字段 | ✅ | `+base-create --table-name --fields` |
| 2 | 字段类型：text / select(单选) / select(**多选**) / user(人员) / **button** | ✅ | 9 个字段全建成 |
| 3 | **多选字段的服务端筛选** | ✅ | ⭐ **本条最关键** |
| 4 | 单选字段筛选、组合 AND | ✅ | |
| 5 | 批量写入记录 | ✅ | 返回 `record_id_list` |
| 6 | **表单视图**（画像/需求录入入口） | ✅ | `+form-create` → `vew7DJ6XWV`，`type=form` |
| 7 | 读取单个字段定义 | ✅ | `+field-get` |

**筛选实测明细**（用设计里的真实场景）：

```
条件 ["技能标签","intersects",["设计"]]                        → 2 条：李四、王五  ✅ 符合预期
条件 ["所在校区","intersects",["津南"]]                        → 3 条：张三、王五、孙七  ✅
条件 校区=津南 AND 技能含编程                                   → 3 条  ✅
条件 技能含编程 AND 校区=八里台                                 → 0 条  ✅
```

⇒ **❓生死线#2 关闭**：我们设计里的**硬筛**（技能交集 ∧ 校区 ∧ 投入）**完全可以在服务端表达**，
不需要把全表拉到本地筛。

### ❌ 发现一个真实阻塞：**自定义角色要求 advanced permission v2**

```
+advperm-enable        → ✅ 成功（is_advanced 由 false 变 true）
+role-create           → ❌ code 2: "create role failed: not support advanced permission v1"
                              hint: "please upgrade to advanced permission v2"
                              log_id: 202610141417269F8C0C14C99FB04821B8
```

**这说明**：本租户（或本 Base）的高级权限是 **v1**，而**字段级/记录级自定义角色需要 v2**。

⇒ **隐私方案（「画像只让本人看自己那行」）目前走不通这条 API 路径。**
需要先搞清 v2 怎么升级（大概率是飞书管理后台的开关，或只能在新版 Base 上生效）——
**这是一个新的 ❓，见下。**

### ⚠️ 环境注意事项（**别记成平台限制**）

- `+field-list` **稳定 EOF**，而 `+field-get`（单字段）正常。
  → 这是 **Linux VM 上 Clash 代理截断大响应**，**不是飞书 API 的限制**。
- 所有飞书调用**必须清掉代理变量**（`ALL_PROXY` / `HTTP_PROXY` / `HTTPS_PROXY` …），
  否则报 `unexpected EOF`。这与 `docs/findings.md` S6 一节的结论**同源**。

### ✅ v1 多维表格 API 实测（2026-10-14，接插件之后）

GeniOS 那个插件的工具名用的是 `app_token` —— 说明它走的是**老一代 v1 接口**，
而不是 CLI 默认的 v3。所以又用 `lark-cli api` 的裸接口补测了一遍 v1。

**权限**：v1 的记录读写要 `bitable:app` / `bitable:app:readonly` / `base:record:retrieve`。
探针应用**已启用 `bitable:app`**（授权后确认），所以插件的 `Scope=bitable:app` 配置是对的。
`GET .../records` 一开始报 `99991679 missing_scope`，补授后即通。

**v1 记录的返回格式（实测原文）**：

```json
{
  "has_more": true,
  "items": [
    {
      "fields": {
        "姓名": "张三",
        "年级": "大二",
        "所在校区": "津南",
        "技能标签": ["编程", "数据分析"],     // 多选 = 字符串数组
        "每周可投入": "10-20h",
        "过往经历": "ACM 校赛二等奖…",
        "飞书账号": [                          // 人员字段
          { "id": "ou_1b65…c49a", "name": "谢国辉",
            "email": "2411520@mail.nankai.edu.cn", "en_name": "谢国辉" }
        ]
      },
      "record_id": "rec…", "id": "rec…"
    }
  ],
  "page_token": "rec…", "total": 5
}
```

三条**必须记住**的事实：

1. **字段嵌在 `fields` 里**，不是平铺的。
2. **文本/单选是普通字符串，多选是字符串数组**（不用再解富文本分段）。
3. ⚠️ **人员字段的 open_id 在 `id` 里，不在 `name` 里。**
   按 `name` 取会把「谢国辉」这个**展示名**当成账号 —— **而且不报错**，
   一路错到飞书推送那一步才会暴露。代码节点里用 `ou_` 前缀兜底。

### ✅ 插件节点的参数（**权威 schema，来自平台校验报错原文**）

> ⚠️ 我一开始根据界面上的缩进把 `table_id` 读成了 `search` 的子字段 —— **错了**。
> 一次真实的校验失败把 schema 原文吐了出来，下面是**权威版本**：

```
顶层（三个都必填）：
  app_token   string    必填   多维表格 App 唯一标识
  table_id    string    必填   数据表唯一标识        ← 顶层！不在 search 里
  search      object    必填   查询条件容器          ← 就算不用也必须传
  page_size   integer          分页大小（默认 10）
  page_token  string           分页标记，首页留空

search 内部（都可选）：
  filter      object     ← conjunction / conditions / children
  sort        array      ← {field_name, desc}
  field_names array      只返回这些字段
  view_id     string     指向某个视图
  automatic_fields boolean
```

**踩到的坑**：只传 `{app_token, table_id, page_size}` 会报
`'search' is a required property` —— **`search` 必须存在**，不用就传空对象 `{}`。

⚠️ ~~没有 `filter` 字段~~ —— **这条也是错的，已更正。** 见下一节。

`search` **确实支持 `filter` / `sort` / `field_names` / `automatic_fields`**，
只是界面上只把 `table_id` 显示成必填。完整的 `search` schema 是从一次校验失败的
报错里拿到原文的（把字符串传给了 `search` 参数）。

### 🔴 插件返回的字段形状**和裸 API 不一样**（2026-10-14，真实插件输出）

**这是用真实插件返回才暴露出来的**，用 CLI 打裸接口看不到：

| 字段类型 | 裸 v1 API（CLI 测的） | **插件返回的** |
| --- | --- | --- |
| 文本 | `"张三"`（字符串） | **`[{"text":"张三","type":"text"}]`（富文本分段）** |
| 单选 | `"大二"` | `"大二"`（一样） |
| 多选 | `["编程","设计"]` | `["编程","设计"]`（一样） |
| 人员 | `[{"id":"ou_…","name":"…"}]` | 一样 |

**只有文本字段不一样**，但这一个就够致命：不压平就会把
`{'text': '张三', 'type': 'text'}` 当成姓名，**而且不报错**，
只是候选人画像文本变成一堆垃圾。

⇒ 代码节点加了 `_flatten_text()` 统一处理（字符串 / 富文本分段 / 多选数组 / 人员对象），
并用**逐字复制的真实返回**做了测试（`gateway/tests/test_match_workflow.py`）。

**教训**：**裸 API 的返回形状 ≠ 插件包装后的返回形状。** 接插件后一定要拿真实输出回跑一遍，
不能拿 CLI 的结果当准 —— 这一条写进 S7，供后来者参考。

### ✅ v1 **写回**的字段值写法（2026-10-14 实测确定）

`update_records` 要写回【组队需求】行。两种接口都试通了：

```
① PUT  /open-apis/bitable/v1/apps/{app}/tables/{tbl}/records/{record_id}
   body = {"fields": {…}}
② POST /open-apis/bitable/v1/apps/{app}/tables/{tbl}/records/batch_update
   body = {"records": [{"record_id": "rec…", "fields": {…}}]}
```

**⚠️ 字段值写法和 v3（创建用的）不一样**：

| 字段类型 | **v1（更新）** | v3（创建） |
| --- | --- | --- |
| **单选** | **字符串** `"已匹配"` | 数组 `["已匹配"]` |
| 多选 | 字符串数组 `["编程","设计"]` | 同 |
| 人员 | `[{"id": "ou_…"}]` | 同 |
| 文本 | 字符串 | 同 |

单选写成数组会被拒：

```
code 1254062
Invalid request parameter: 'fields.状态.fieldValue[已匹配].fieldName.状态'.
Correct format : the value of 'Single Option' must be a string.
```

⇒ **两代 API 的写法不同，不能混用。** 代码03（`build_update_payload.py`）
按 v1 的写法产出，并已用测试锁住（`TestBuildUpdatePayload`）。

### ✅ v1 筛选语法（2026-10-14 实测确定）

```jsonc
{
  "search": {
    "table_id": "tbl…",
    "filter": {
      "conjunction": "and",          // ⚠️ 必填！省掉会报 99992402 field validation failed
      "conditions": [
        { "field_name": "技能标签", "operator": "contains", "value": ["编程"] },
        { "field_name": "所在校区", "operator": "is",       "value": ["津南"] }
      ]
    }
  }
}
```

**实测定出来的语义**（在同一组真实数据上逐个试出来的）：

| 字段类型 | operator | 语义 | 实测 |
| --- | --- | --- | --- |
| **多选** | `contains` | **包含任一** | `[编程]` → 张三、王五、孙七（3 条）✅ |
| 多选 | `is` | **完全相等**（不是"包含"！） | `[设计]` → 0 条 ✅ |
| 单选 | `is` | 等于 | `津南` → 正确 ✅ |
| — | `isAnyOf` | ❌ 不存在 | `99992402` |

**三条要记住的**：
1. `conjunction` **必填**（`"and"`）
2. 多选用 **`contains`**、单选用 **`is`** —— 多选上用 `is` 会静默返回**空结果**（不是报错），很容易误判成"没人符合"
3. `value` **一律是数组**，即便单选也是 `["津南"]`

### ⬜ 尚未测

- **按钮绑工作流**（`+button-rule-bind --field-id --workflow-id` 参数已确认齐备，未实做）
- **视图筛选 / 分组**（需求池「按项目类型筛选」）
- **写回**（`create_records` / `update_records` 的插件节点跑一次）
- **GeniOS 侧：token 能否自动刷新** —— 但插件配置里**有 `refresh_token_url` 字段**，
  说明它支持续期（`docs/probe_checklist.md` S7 的生死线**大概率有解**）；仍需放 2 小时实测确认

### 🧹 善后事项

- 探针应用 `cli_aa45a6…` 授权了**全量权限**，探针结束后应**登出并删除应用**：
  `lark-cli auth logout` + 开放平台里删除应用。
- 测试 Base `<BITABLE_APP_TOKEN>` 用完可删。

---

## 🎉 功能模块二 · 智能链路 + 写回 —— **端到端打通（2026-10-14）**

**这是模块二从零到一的验收。** 链路：

```
Start ─▶ 插件 search_records ─▶ 代码01 ─▶ 大模型01 ─▶ 代码02 ─▶ 代码03 ─▶ 插件 update_records ─▶ End
         读【队友画像】        硬筛       精排+理由    校验+映射   组装修写入参   写回【组队需求】行
```

**实测证据**（真实运行，非构造）：

- End 返回：`{"ok": true, "issues": [], "match_count": 1, "matches": [{"open_id": "ou_1b65…c49a", "score": 92, "reason": "…"}]}`
- **表里那一行被真的改写了**（用 v1 接口读回核对）：
  - `状态` → `已匹配`
  - `推荐队友1` → 人员字段，写入了 open_id
  - `匹配理由` → 以「1. 」开头，格式与代码03 的产出一致

**生成的理由（原文）**：

> 发起人自己是编程背景、**缺的正是设计这一块**，而他会 Figma 并做过前端外包，
> 能直接承担建模论文的图表可视化与界面排版；同时校区同为津南、每周也能投入 10-20h…

⇒ **「互补不是相似」这条设计原则被真实数据验证了**：它推理了「发起人缺什么」，
选的是能补短板的人，而不是和需求描述相似的人。这是整个模块二最核心的智能点。

### 打通路上踩到的四个坑（都记下来，别再踩）

| # | 现象 | 根因 | 修法 |
| --- | --- | --- | --- |
| 1 | `search_records` 报 `'search' is a required property` | 把 `table_id` 当成 `search` 的子字段（界面缩进误导） | **`table_id` 是顶层**，`search` 是另一个必填对象 |
| 2 | 代码01 收到 `input_count: 1` 但 0 淘汰 0 留下 | `if not cand: continue` **没计数**（静默跳过） | 加 `无法解析` 计数 + 自诊断 |
| 3 | 同上，`原始值类型=str 预览='null'` | 输入变量引用的节点/字段没选对 | 重新选来源 |
| 4 | 同上，`预览='{}'` | 试运行时给 `candidates_json` 填了 `{}`，而 `_as_list("{}")` 返回**非空**列表，于是把插件的真数据挡住了 | 新增 `_has_records()` 判"有值但是空的"；**试运行时该留空的要留空** |
| 5 | `update_records` 报 `JSONDecodeError` | `record_id` 和 `fields_json` 两条输入**接反了** | 名字对齐：`record_id`←`record_id`，`fields_json`←`fields_json` |

> **一条方法论**：这四个坑里，**三个是靠"自诊断输出"当场定位的**
> （代码01 在没选出人时会把「候选来自哪个键、几个元素、原始值类型和预览」写进 `issues`）。
> 在节点里留自诊断，比来回猜快得多 —— 值得在所有代码节点里保持这个习惯。

### ⬜ 模块二还差的一半：gateway 侧

现在触发和通知都还没有，链路靠手工试运行。剩下：

1. **gateway 轮询【组队需求】**：发现 `状态=待匹配` 就调 GeniOS（传该行的 `record_id`）
2. **gateway 读回结果 → 推飞书给双方**：发起人 + 被推荐的人
3. 写回「状态=已通知」，让状态机收敛

设计见 `docs/module2_team_matching.md`。

---

## ⚠️ v1 写表接口的两个硬坑（2026-10-16，通路打通时踩的）

worker 改成**直接写【机会汇总】表**之后，连踩两个：

### ① **v1 的单选字段要字符串，v3 要数组**

| 表字段类型 | **v1**（gateway / worker 用） | v3（CLI 回填用） |
| --- | --- | --- |
| 单选 | **字符串** `"竞赛"` | 数组 `["竞赛"]` |
| 多选 | 字符串数组 | 同 |
| 人员 | `[{"id": "ou_…"}]` | 同 |
| **日期** | **Unix 毫秒** | 毫秒或 ISO 都行 |

同一个字段，**两代 API 写法不同** —— 回填（走 CLI/v3）用数组成功，
worker（走 v1）用数组就被拒：`1254062 SingleSelectFieldConvFail`。

> 这已经是**第三次**栽在 v1/v3 差异上了（前两次：单选值、关联字段）。
> **凡是要写表，先问一句"这是 v1 还是 v3"。**

### ② **v1 用 HTTP 200 返回业务错误**

```
HTTP 200
{"code": 1254062, "msg": "SingleSelectFieldConvFail", "error": {...}}
```

**状态码是 200，错误在 body 的 `code` 里。**
只看 HTTP 状态会以为写成功了 —— 当时表里没增加、日志也没打，白查一轮。

⇒ `BitableClient._call` 一直有检查 `code`，这没问题；
**但 worker 调用处必须 catch 并显式记日志**，否则失败会被静默咽掉（已修）。

### 顺带

`status` 字段**从来没人算过** —— 迁移前是 SQLAlchemy 的默认值 `可参与`。
worker 里补了同样的默认，保持迁移前后一致。
> 想筛"还能报名的"，**按 `报名截止` 比时间更准** —— 那才是原文里的真信息。

## 🔴 【机会汇总】表建好了，但**枚举值和代码不一致**（2026-10-16）

**表已经存在**（`tblIA4VlukcpQNE7`，26 字段，和 `models.py::Opportunity` 逐字对齐）。
**谁建的已不可考**（用户也不记得）。

**但回填时抓到一处不一致**：

```
models.py  OPPORTUNITY_STATUS = ("未开始", "可参与", "已截止")
表里的「状态」选项             =  ["可参与", "已结束"]
                                   ↑ 缺「未开始」   ↑ 「已结束」≠「已截止」
```

**后果**：状态为「未开始」的机会**写不进表**，而「已截止」根本没这个选项。
飞书返回的是 `800030005 not_found` —— **不看日志根本猜不到是选项对不上**。

**已修**：`+field-update` 把选项改成 `未开始 / 可参与 / 已截止`，对齐代码。

> ⚠️ **这正是 AGENTS.md 不变量 5 那类问题**："机会类型是固定 N 类，枚举值逐字取自字段体系文档，
> **不要用简称**"。**新建任何表时，枚举值都要拿代码里的常量对一遍**，别照着自己理解写。

### ✅ 回填完成

SQLite 里 **8 条机会**已灌入【机会汇总】表（字段映射天然对齐 —— 表结构就是照模型建的）。
日期一律转成 **Unix 毫秒**（实测这个表存的就是毫秒）。

### ⬜ 下一步

1. **worker 双写**：以后新处理的机会，SQLite 和表**两边都写**，跑一阵对比，验证一致后再停 SQLite
2. 画布上接【机会汇总】（插件节点）

## Q20 · ✅ **报名二维码可以"解"出来，而且解出来的 URL 比图片更有用**（2026-10-18）

### 问题

公众号常用「扫码报名」，没有可点的链接。卡片上的「立即报名」就没地方去。

### 先否掉一条路：**别让大模型猜哪张图是二维码**

实测（真实文章）：

| 检查 | 结果 |
| --- | --- |
| 微信 `<img>` 的 `alt` | **全为空**（抽查 25 张，无一例外） |
| 图片前后的文字 | 常常是空标签，或只有「供稿：某某」 |

模型只拿到 URL + 上下文，**没有任何可依据的信号**。

### 改走"解码"：`zxing-cpp`

`scripts/probe_qr_images.py` 跑了 **15 篇真实文章 / 115 张图**：

```
合计：图片 115 张，其中二维码 9 张，涉及 8 篇文章
```

### 关键发现①：绝大多数二维码是「关注公众号」，必须过滤

解码内容几乎全是：

```
http://weixin.qq.com/r/DhEtNUfEphrZrQNW90Qc
```

这是**文章末尾的公众号关注码**，每篇都有，和报名无关。
⇒ 过滤规则：**解出的文本以 `weixin.qq.com/r/` 开头的，一律丢掉。**

### 关键发现②：过滤后剩下的是**真·报名入口**，而且能直接拿到 URL

《职业规划沙龙第二十四期预告》里解出：

```
https://nankai.feishu.cn/share/base/form/shrcnFv6bZpQIAuTMKkEQRCKwfc?…
```

**这是飞书报名表单** —— 也就是我们自己的表单体系。

⇒ **解出 URL 之后根本不需要展示图片**，直接塞进 `signup_url`，
「立即报名」按钮就能用了。

### 关键发现②·补充：**只看前 12 张图不够**

拿用户给的 3 篇真实文章验证时，有一篇（22 张图）前 12 张全是海报和照片，
报名二维码排在**第 13 张之后**。上限调到 **20 张**后三篇全部命中：

| 文章 | 图片 | 解出的入口 |
| --- | --- | --- |
| ① | 8 | `nankai.feishu.cn/share/base/form/shrcnkzEL…` |
| ② | 22（看 20）| `nankai.feishu.cn/share/base/form/shrcnusy6…` |
| ③ | 5 | `v.wjx.cn/vm/Q4A68hI.aspx` |

> ⚠️ 顺带一个坑：**直接抓公众号文章时 UA 不能用 `Mozilla/5.0`** ——
> 会返回 18KB 的空壳页（正文 0 张图）；换成完整 UA 才是 3.4MB 的正文。
> 生产不受影响（正文是采集器给的），但探针和调试脚本要注意。

### 关键发现②·之二：多张表单时按标题取舍 —— **飞书的标题读不到**

一篇文章里可能同时有「报名表」和「调研表」。用户建议"取题目含报名的"，实测结果分域名：

| 来源 | 标题能不能读到 |
| --- | --- |
| **问卷星** `v.wjx.cn` | ✅ `<title>` 就是问卷名（如「…交流话题征集」）|
| **飞书表单** `nankai.feishu.cn/share/base/form/…` | ❌ `<title>` 是空的；页面里的「活动报名登记表」是**模板文案** —— 实测两个不同表单页面里**完全相同**，拿它打分会把任何表单都判成"报名" |

⇒ 规则：**只在候选 ≥2 时才去读标题**；读不到按 0 分（中性），
报名/登记/申请 +3，征集/调研/反馈/满意度/评价/投票/签到 −2；同分保持文章顺序。

绝大多数文章只有一个问卷 —— 那条路径**一次网络请求都不多发**。

### 关键发现③：**微信小程序码解不出来**

小程序码是圆形的「向日葵」码，不是标准 QR。`qr=0` **不等于**没有报名入口。

### 结论 / 设计

```
取 <img> → 下载（限张数/大小）→ zxing 解码
   ├─ 解出 http(s) URL  → 过滤掉 weixin.qq.com/r/ → 直接当 signup_url
   ├─ 解出非 URL 内容   → 当作「要扫码」，展示图片
   └─ 解不出来          → 保持现状（引导去原文）
```

解码是**测量**，不是语义判断；且 code 节点跑不了下载和解码。

### 证据

```
— 职业规划沙龙第二十四期预告丨选调校友返校专场｜图片 4 张｜二维码 2 张
     ✅ QRCode  https://nankai.feishu.cn/share/base/form/shrcnFv6bZpQIAuTMKkEQRCKwfc?…
     ✅ QRCode  http://weixin.qq.com/r/DhEtNUfEphrZrQNW90Qc
```

---

## Q19 · 🔴 **飞书表单没有只读字段 —— "可见但不可改"要靠系统字段「创建人」**（2026-10-17）

### 现象

需求："`飞书账号` 能看到，但不能自选。"

### 查到的

| 办法 | 结果 |
| --- | --- |
| 表单题目设"只读" | ❌ **不存在**。题目只有 `visible` / `required` 两个开关，可见就能改 |
| `hide_题目=1` | ✅ 能藏，但用户也**看不见**了 —— 不满足"能看到" |
| 多维表格**高级权限**的列权限 | 只管**表格协作者**，管不到匿名填表的人 |
| **系统字段 `创建人`（type 1003）** | ✅ **飞书自动填提交人，谁都改不了** |

### 结论

**表单层面做不到"可见且不可改"** —— 这是产品限制。

"=> 拆成两层：

| 层 | 谁负责 | 作用 |
| --- | --- | --- |
| **默认值** | `?prefill_飞书账号=<姓名>` | 用户不用选，默认就是自己 |
| **真值** | 系统字段 `创建人` | 用户就算改了，服务端也不认 |

`gateway/app/bitable.py::identity_open_ids`、`match_flow._build_request_json`
都已按这个改：**`创建人` 有画像就以它为准**，否则退回用户填的那个。

### ⚠️ 踩到的坑：新加 `创建人` 字段会**回填历史行**

在已有 7 行的【队友画像】上加了这个字段，结果**7 行全变成「谢国辉」**
（= 加字段的人），包括李培涛那行。

**⇒ 历史行不能用 `创建人` 建索引**，否则互相覆盖、把人认错。
`_profiles_by_open_id` 因此改成两遍：先按 `飞书账号`，`创建人` **只补空缺**（`setdefault`）。

> 新建的表 / 加字段之后新提交的行没有这个问题。

### 待验证

**新提交的行，`创建人` 记的是不是真的提交人**（而不是链接发送者/表所有者）。
验证方式：用另一个账号提交一条 → 看表里 `创建人`。

---

## Q18 · ✅ **飞书表单可以按人预填：`?prefill_题目=值`**（2026-10-17）

### 做了什么

想让「姓名」不用手填（手填会打错、会填成室友、和人员字段重复）。
查了飞书官方帮助中心，确认表单支持 URL 预填。

### 看到什么（官方文档）

```
[分享链接]?prefill_问题名称=默认值
```

| 要点 | 内容 |
| --- | --- |
| **题目名必须逐字一致** | 改了题干，预填参数就失效 |
| 支持的题型 | 文本 / 单选 / 多选 / 关联 / **人员** / 复选框 / 数字 / 日期… |
| **人员字段** | 填**完整姓名**（需是飞书联系人），**不是 open_id** |
| 特殊字符 | 必须 URL 编码（中文、空格、`&` 都算） |
| 隐藏问题 | `&hide_题目=1` |
| 链接上限 | 16,000 字符 |

### 结论 / 落地

`gateway/app/forms.py`

- `prefill_form(url, answers)` —— 拼参数（幂等、保留原有查询串、空值跳过）
- `personalize_links(text, name=…)` —— 把回复里的表单链接换成带姓名的版本
  - 画像表：题目 `姓名`
  - 组队需求表：题目 `发起人`（人员字段）
- `chat_flow._respond` 在**发出去之前**统一处理 —— 画布上的提示词只写干净链接，
  个性化是 gateway 的事（**不用改画布**）

### ⚠️ 两个限制

1. **预填不是只读**，用户仍能改。表单没有"字段锁定"。预填只是把"默认正确"变成常态。
2. **得先知道这个人叫什么**：
   - 画像表里已有 → ✅
   - 第一次用 → 要查通讯录，**需要 `contact:contact.base:readonly`**。
     实测没开权限时是 `99991672 Access denied`，此时**不预填**，链接原样发出。

### 证据

```
# 真实对话（`我想给CANN大赛找队友`）
https://nankai.feishu.cn/share/base/shrcnH1oQRYtBvm1y7WYAj38gne?prefill_%E5%8F%91%E8%B5%B7%E4%BA%BA=%E8%B0%A2%E5%9B%BD%E8%BE%89
                                                              └ prefill_发起人=谢国辉
```

---

## Q17 · 🔴 **插件 OAuth 是按「运行时 userID」绑定的** —— 对话不能传学生 open_id（2026-10-17）

### 怎么发现的

授权自检报「三个全绿」，但紧接着**真发一句对话**却回：

```
使用工具 search_records 需要授权, 请点击[这里](https://accounts.feishu.cn/...&state=g2h7lc79zn)进行授权
```

自检脚本和真实调用**唯一的差别是 `userID`**：
自检写死 `ou_auth_check`，`chat_flow` 传的是学生的 `open_id`。

### 做了什么

同一句话「有哪些适合我的比赛」，换三个 `userID` 各跑一次（同一个对话流智能体）：

| `userID` | 结果 |
| --- | --- |
| `ou_auth_check` | ✅ 正常读表、正常作答 |
| `campus-gateway` | ❌ 需要授权（`state=6dqrf4dn58`） |
| `ou_probe_chat` | ❌ 需要授权（`state=54n8nj8tzh`） |

### 结论

**飞书多维表格插件的 OAuth 授权是一条 `(插件, userID)` 的记录。**
授权链接是**某次运行在某个 userID 下**产生的，点完之后**只给那个 userID 发凭据**。
换一个 userID，平台就认不出来，重新要授权。

⇒ **对话智能体必须跑在一个固定的「服务身份」下**，不能把学生的 `open_id` 当 `userID` 传。
否则**每个新同学第一次提问都会收到一条授权链接** —— 功能等于不可用。

### 修法

`Settings.genios_chat_user_id`（默认 `campus-gateway`，和模块一/二一致），
`chat_flow._api_user` 用它；学生是谁由两样东西承载，**和平台侧的 userID 无关**：

| 学生身份 | 由谁承载 |
| --- | --- |
| 「我知道 TA 的背景」 | `【我的画像】…` 拼进 Query（`chat_flow._with_profile`，见 Q12） |
| 「多轮记忆各是各的」 | `ChatSession.open_id → conversation_id`（按 open_id 存） |

> ⚠️ **自检脚本也必须用同一个 userID** —— `check_auth.check_chat` 已改成读
> `settings.genios_chat_user_id`。用一个「测试专用 id」自检 = **自检绿、线上红**。

### 证据

```
# 2026-10-17 14:5x，同一句 query
[ou_auth_check]  ✅ 同学你好～系统这边没拿到你的画像…目前能报的比赛有这些：…
[campus-gateway] ❌ 使用工具 search_records 需要授权, 请点击[这里](…state=6dqrf4dn58)…
```

---

## Q16 · ✅ **插件 OAuth 每 2 小时过期 → 加 `offline_access` 就能续期**（2026-10-17）

**这是 Q13 之后最重要的一条** —— 它把「每 2 小时人工点一次」变成了「理论上 30 天不用管」。

### 现象与根因链

```
① 实测：插件授权约 2 小时就失效（12:15 授权 → 14:16 需要授权）
② 这个数字正好等于飞书 user_access_token 的标准 TTL
③ 查官方文档：
   · user_access_token   ≈ 2 小时
   · refresh_token       ≈ 30 天，**一次性使用**（每次刷新换新的，旧的立刻失效）
   · **前提：应用要开通 `offline_access`，且授权链接的 scope 里要带上它**
     否则飞书**根本不返回 refresh_token**
④ 我们的授权链接是 `scope=bitable:app` —— **没有 offline_access**
   ⇒ 插件配置里那个 `refresh_token_url` 永远没东西可刷
   ⇒ 2 小时必死
```

### 修法

1. **飞书开放平台 → 应用 `cli_aa45a6…` → 权限管理 → 开通 `offline_access` → 发布**
2. **GeniOS 插件 → `Scope` 那一栏改成 `bitable:app offline_access`**（空格分隔）
3. **重新授权一次**（旧的 token 里没有 refresh_token，必须重来）

> ⚠️ **`offline_access` 不包含 `bitable:app`** —— 两个是独立的：
> `bitable:app` 管**能做什么**，`offline_access` 只管**能不能拿到 refresh_token**。**两个都要。**

### 印证

改完之后插件生成的授权链接里能看到：

```
…&scope=bitable%3Aapp+offline_access&state=…
                         ↑ 两个都在了
```

### 验证状态

**⏳ 待验证**：重新授权后（2026-10-17 14:38 自检全绿），
**2.5 小时后**再跑一次 `scripts/check_auth.py`：

- **仍全绿** ⇒ 插件确实用上了 refresh_token，**问题解决** ✅
- **变红** ⇒ 插件没有用 refresh_token（平台侧问题，需要问管理员）

### 边界

即使刷新成功，**用户授权满 365 天后必须重新授权**（飞书硬限制）。
比赛周期远短于一年，不影响。

### 顺带

- **模块一不需要授权** —— 它的工作流只有 `Start/End/LLM/Code`，**没有插件节点**
- 自检脚本：`scripts/check_auth.py`（`--loop 600` 持续观察，`--report` 算过期间隔）

---

## Q15 · 🔴 **正则 `\S+` 把 `)进行授权` 吃进了 state** —— "授权永远过期"的真凶（2026-10-17）

**现象**：飞书告警卡片里的重授权链接，**点了永远报 `state expired`**：

```
{"Error": {"Code": "InternalErr.Unknown", "Message": "state expired"}}
```

而**同样一条链接，从日志里抠出来粘贴就完全正常**。

### 根因：正则多吃了 4 个字符

平台给的 `msg` 长这样（**markdown 链接**）：

```
使用工具 search_records 需要授权, 请点击[这里](https://accounts.feishu.cn/…&state=abc123)进行授权
```

代码里用的是：

```python
r"https://accounts\.feishu\.cn/open-apis/authen/v1/authorize\S+"   # ❌
```

`\S+` 一直吃到**空白**为止 —— 而 `)进行授权` 后面没有空格，
于是抓到的 URL 是：

```
…&state=abc123)进行授权        ← state 被污染成 "abc123)进行授权"
```

**飞书当然说 `state expired`。**

> **最讽刺的地方**：我从**日志**里抠链接给你时用的是 `[^)"]*`（正确），
> 所以"我给的链接都能用、卡片上的都不能用" —— 差别就在这一个字符。

### 修法

```python
r"…/authorize[^\s)\]\"'<>]+"     # 遇到 ) ] " ' < > 或空白就停
```

并加了测试：抓到之后断言 `state=abc123` 结尾干净、不带 `)进行授权`。

### 教训

**解析"人写的消息里的 URL"时，`\S+` 几乎总是错的。**
markdown、括号、引号、中文标点都可能紧贴 URL ——
**必须显式排除**，不能指望后面有空格。

---

## Q14 · 🔴 对话的 **End 输出字段名「按分支不同」**（2026-10-17）

**现象**：「找队友」在 GeniOS 画布调试里正常，**从飞书发就报「刚才没处理过来」**。

**根因**：`answer` 里同时有三格，其中一格是空的：

```json
{"other": "",
 "output": "",                    ← 空的
 "output_match": "{\"reply\": \"给智能体应用创新大赛找队友的话，填一下这个表单就行…\"}"}
```

| 分支 | 正文在哪个字段 |
| --- | --- |
| 查机会 | `response` |
| **找队友** | **`output_match`** |

而 `unwrap_text` 的字段优先级列表里 `output` 排在 `output_match` 前面 ——
**先撞上了那个空的 `output`**，虽然 `if got:` 会跳过空值，但**列表里根本没有 `output_match`**，
最后一路返回空串。

**⇒ GeniOS 里看着没问题，是因为它直接显示 `output_match`；是 gateway 挑错了字段。**

### 修法：**不再靠猜字段名**

```python
# 先按已知字段名猜（reply / response / answer / … / output / output_match）
# 猜不中 → 把所有值都剥一遍，取**最长**的那段文本
```

**这是降级方案，不是理想态** —— 万一画布输出的是结构化自述（`{"name": "校园机会助手", …}`），
就会把 `校园机会助手` 当正文发出去。

> **正确的做法**：画布的 **End 节点固定输出一个正文字段**（比如统一叫 `response`），
> 别让同一个智能体的不同分支用不同字段名。
> 代码里的"取最长"只是兜底 —— **别拿它当契约**。

---

## Q13 · 🔴 **VM 休眠会让 token 缓存"永远不过期"** —— 全链路 99991663（2026-10-17）

**现象**：服务跑了一夜，第二天所有飞书调用全挂：

```
code=99991663  Invalid access token for authorization
```

读表、发消息、推卡片**全部失败**。而**同一时刻用 `.env` 里的凭据新建一个客户端，一切正常** ——
说明**凭据没坏，是缓存坏了**。

### 根因：`time.monotonic()` 不计休眠时间

```python
now = time.monotonic()                     # ← 错
if self._token and now < self._token_expires_at:
    return self._token
```

Linux 的 `CLOCK_MONOTONIC` **不计系统休眠**。VM 睡了一夜，`monotonic()` 几乎没涨，
而真实时间过了 8 小时 —— 缓存一直以为 token 还新鲜，**返回了一个早就过期的 token**。

日志是最好的证据：**8 小时里只有一次换 token 的请求**（服务启动那一刻）。

### 两处都修了

1. **改用墙钟** `time.time()` —— token 的过期是一个**真实的墙钟时刻**，就该用墙钟比。
2. **遇到 `99991663` 就清缓存重取一次** —— 不管什么原因（休眠、时钟跳变、服务端提前作废），都能自愈。
   `FeishuAppClient.invalidate_token()` + `send()` / `BitableClient._call()` 里各重试一次。

> **一条通用教训**：**凡是"过期时间"跨的跨度超过几分钟，别用 `monotonic()`。**
> 它是给"超时"用的，不是给"过期"用的 —— 休眠/挂起会让它和时间脱节。

---

## Q12 · 🔴 **飞书 open_id 是「按应用」算的** —— 对话查画像永远查不到（2026-10-17）

**现象**：对话里问"有哪些适合我的比赛"，模型答
「**还没找到你的画像信息（可能你还没填过）**」—— 但这个人**明明填过**。
而且机会列表**是对的**（说明插件读表成功）。

### 根因（实测对照）

同一个人、同一张画像表，**两个应用读出来是两个不同的 ID**：

```
【自建应用视角】（gateway 读表、飞书消息事件）
   谢国辉 → ou_87ad1db716acb0bc2b2d815bbc12dbfc
   李培涛 → ou_eba32df0a742424a89d666defb217036

【探针应用视角】（对话智能体通过插件读表）
   谢国辉 → ou_1b6553300df5973e7cef352cba7cf49a
   李培涛 → ou_64bc597228f71debe5cb6e0411798625
```

**飞书的 open_id 是「按应用」分配的** —— 同一个人在不同应用下是不同的 ID。

对话收到的 `user_id` 是**自建应用视角的**（来自飞书消息事件），
而代码节点读到的画像表是**探针应用视角的** —— **两边永远对不上**。

⚠️ **而且它是静默的**：不报错，只表现为"没找到画像"。

### 处置：**由 gateway 查好画像、拼进 Query**

gateway 天然对得上（**同一个应用读同一张表**），所以别让对话自己去查：

```
gateway：读画像表 → 按 sender_open_id 找到本人 → 拼成【我的画像】… 放在问题前面
对话：看到【我的画像】就直接用，不再自己去表里匹配
```

代码：`gateway/app/chat_flow.py::_with_profile` +
`genios/code_nodes/chat_context.py`（优先读 `【我的画像】`，表里匹配只作兜底）。

> **一条通用教训**：**跨应用传 open_id 一定会踩这个坑。**
> 凡是要把「飞书消息里的人」和「多维表格里的人」对上，都得先问一句
> **"这两个 ID 是同一个应用视角吗"**。
> （顺带：`union_id` 在同一租户内是一致的，本该用它 —— 但多维表格的人员字段不返回它。）

---

## Q11 · **对话型/对话流型智能体的 API** —— ✅ 已关闭（2026-10-16）

**背景**：模块二之后要加"对话"—— 学生在飞书问"有哪些适合我的比赛"、"我想给 xx 比赛找队友"。

**没有文档，全靠探。** 先把平台已有的 API 凭据拿去打各种可能的端点，
**让报错把我们一步步教出来** —— 这是本项目一贯的做法（见 Q1/S5）。

### 端点（两族 API，别混）

| 族 | 端点 | 用于 |
| --- | --- | --- |
| 流程编排型 | `POST /api/proxy/api/v1/run_app_workflow` | 模块一/二（**单轮、异步、传 `InputData` 字符串**） |
| **对话型/对话流型** | `POST /api/proxy/api/v1/create_conversation` | **建会话** |
| | `POST /api/proxy/api/v1/chat_query` | **问一句（SSE 流式）** |

**猜过的名字全是 404**（`chat` / `run_app` / `create_message` / `send_message` / …）——
不要再试了。

### 参数是报错教出来的

```
空 body              → "userID is empty"
+ userID             → "BindAndValidate error: AppConversationID, missing required parameter"
+ AppConversationID  → "param Query, QueryExtends and UserMessage cannot be empty at the same time"
+ Query              → 200 🎉
```

| 端点 | 请求体 | 返回 |
| --- | --- | --- |
| `create_conversation` | `{"userID": "ou_…"}` | `{"Conversation": {"AppConversationID": "db8o…", "ConversationID": "01M5…"}}` |
| `chat_query` | `{"userID","AppConversationID","Query"}` | `text/event-stream` |

⚠️ **要用 `AppConversationID`**（`db8o…`），不是同一个响应里的 `ConversationID`（`01M5…`）。
两个名字太像，传错只会得到 400。

### ⚠️ 三个实测踩到的坑

1. **SSE 格式怪**：每帧是 `event:text\n` + **`data:data: {…}`** —— `data:` 字段的内容
   **本身又以 `data:` 开头**。标准 SSE 解析器会把它当成值为 `data: {…}` 的字符串，
   json 直接失败。**要剥两层。**
2. **回复双重编码**：正文在 `event == "message"` 那帧的 `answer` 里，而 `answer` 是字符串，
   里面还套着 `{"output": "{\"reply\": \"…\"}"}` —— **要递归剥**。
   （和 `worker.extract_llm_payload` 是同一个思路。）
3. **带引号的 JSON 字符串**：某一层可能是 `'"南开…"'`，只对 `{`/`[` 开头做解析会漏掉它，
   结果回复**原样带着引号**显示出来。

### 代码

`gateway/app/genios_chat.py` —— `create_conversation()` / `chat()` / `parse_sse()` / `reply_of()`。
多轮靠 `gateway/app/models.py::ChatSession`（`open_id → AppConversationID`）——
**这是"管道状态"不是业务数据**，所以放本地库不违反 D9。

### ⬜ 下一步

**画布还是空的** —— 现在智能体只能说"还在搭建中"。
搭上「意图识别 + 插件节点」之后，它才能真正去查机会表、建组队需求。

## 🎉 S8 · 飞书**卡片回传回调**走长连接 —— ✅ 已打通（2026-10-14）

**这条决定了模块二的两个"点按钮"动作能不能一下点完。**

背景：模块二有两处需要用户决策 —— ④ 发起人点「邀请」、⑥ 被推荐人点「接受/婉拒」。
如果只能"跳转到多维表格再点"，体验差一截；能走卡片回调就一步到位。

**怎么测的**：`scripts/feishu_card_callback_probe.py`
—— 发一张带回传按钮的测试卡，`lark.ws.Client` 注册 `register_p2_card_action_trigger`，
点一下，看长连接能否收到。

**结论：✅ 收到了。** 完整载荷（原文）：

```json
{
  "schema": "2.0",
  "header": { "event_type": "card.action.trigger", "app_id": "cli_aa4ede…",
              "tenant_key": "2eb96f195e8f1657" },
  "event": {
    "operator": { "open_id": "ou_87ad…c12dbfc", "union_id": "on_af86…" },
    "action": { "value": { "probe": "campus-card-callback-probe" }, "tag": "button" },
    "host": "im_message",
    "context": { "open_message_id": "om_x100b63…", "open_chat_id": "oc_77cd…" }
  }
}
```

**三个字段解锁了整个交互设计**：

| 字段 | 用途 |
| --- | --- |
| `event.operator.open_id` | **点按钮的人是谁** —— 飞书直接给，不用问、不能伪造 |
| `event.action.value` | **按钮里能塞任意业务参数** → `{"action":"invite","record_id":"rec…","candidate":"ou_…"}` |
| `event.context.open_message_id` | 哪张卡被点了 → **可以原地更新那张卡**（点完把按钮变成"已邀请"） |

**前提**：开放平台里要**开通卡片回调权限**（用户已开）。
SDK 侧：`lark.EventDispatcherHandler.builder(...).register_p2_card_action_trigger(...)`，
返回 `P2CardActionTriggerResponse({"toast": {...}})` 可以在飞书里弹个提示。

> ⚠️ 注意事件 `schema` 是 **2.0** —— 与我们已有的 1.0 卡片共存无碍，但**新卡片可以直接用 2.0**。

### ⚠️ gateway 读写多维表格：**卡在应用身份权限**（2026-10-14）

决策 D9 说表格是事实源，所以 gateway 要直接读写它。走的是**应用身份**
（`tenant_access_token`），实测**不通**：

```
GET /open-apis/bitable/v1/apps/{app}/tables/{tbl}/records
→ code=99991672 Access denied. One of the following scopes is required:
   [bitable:app:readonly, bitable:app, base:record:retrieve]
   应用尚未开通所需的应用身份权限：[…]
```

⇒ **自建应用 `cli_aa4ede…` 要在开放平台开通 bitable 权限，
并把自己加为目标多维表格的协作者。** 平台会把申请链接一并返回。

> 注意和 S7 那条区分开：**S7 是"用户身份"**（CLI 的 OAuth），
> **这条是"应用身份"**（网关常驻服务）。**两者要分别开通。**

> ### ✅ 已解除（2026-10-16 复测）
>
> **读权限已经通了** —— 用 `BitableClient.list_records` 打三张表，全部 200：
>
> | 表 | 结果 | 实测字段 |
> | --- | --- | --- |
> | 队友画像 | ✅ 7 行 | 姓名 / 学院 / 年级 / 所在校区 / 技能标签 / 每周可投入 / 过往经历 |
> | 组队需求 | ✅ 2 行 | 需求标题 / 发起人 / 项目类型 / 需要什么技能 / 所在校区 / 期望每周投入 / 预期目标 / 状态 / 匹配理由 / 推荐队友1 / 邀请理由 |
> | 邀请 | ✅ 1 行 | 需求标题 / 发起人 / 被邀请人 / 关联需求 / 邀请理由 / 状态 |
>
> ⇒ **`99991672` 那一步 [人] 已经办了**，应用身份可用。
> ⚠️ **但"写"这次没测**（`update_record` / `create_records`）—— 别把"读通"当成"写也通"，
> 权限 scope 是分开的。第一次要写表时先跑一次确认。
>
> 📌 顺带两条，给接手的人：
> - **【队友画像】表里没有「技能标签」以外的匹配字段缺项**，`match_hard_filter` 要的
>   `所在校区 / 技能标签 / 每周可投入` 都在，硬筛所需字段齐备。
> - **【组队需求】表当前只有 2 行**，做匹配演示前先确认里面有"待匹配"的行。

#### 踩到的一个 bug：URL 前缀拼重复了

第一次跑冒烟，请求打成了 `/open-apis/open-apis/bitable/...` → 404。
原因：`feishu_app.FEISHU_BASE` **已经含 `/open-apis`**，`bitable.py` 里又拼了一次。

**这个错任何单元测试都测不到**（构造 URL 的代码看起来完全正常），
只有真跑一次才暴露 —— 已经用 `TestBitableUrls` 锁住。

### 附：视图筛选**做不到「当前用户」**

想让【组队需求】表有个"我的需求"视图（筛选 发起人 = 当前登录人）——
**API 做不到**：`references/lark-base-filter-condition.md` 要求人员字段填具体的 `ou_xxx`，
**没有"当前用户"这个特殊值**（这类 UI-only 条件 OpenAPI 不支持读写）。

⇒ **要在飞书界面里手动配一次**（一次性的），或者视图按固定的人配。
不影响主流程。

---

## 🔴 S7 生死线**有了答案**：插件的 OAuth 授权**会过期，要人工重新授权**（2026-10-14）

这是从 S7 一开始就标着「生死线」的那一条（`docs/probe_checklist.md`）。
**当时没人能回答，现在实测出来了 —— 答案不好。**

**现象**：授权完成约两小时后，工作流再次运行时报：

```json
{
  "status": "interrupted",
  "steps": ["db5igk54shhas0als382", "db7jnvd4shhbpg91k6s0"],
  "lastInterruptedNodeId": "db7jnvd4shhbpg91k6s0",   // ← search_records 插件节点
  "msg": "使用工具 search_records 需要授权, 请点击[这里](https://accounts.feishu.cn/
          open-apis/authen/v1/authorize?client_id=…&scope=bitable%3Aapp&state=…)进行授权"
}
```

**⇒ 虽然插件配置里有 `refresh_token_url`，但实际并没有自动续期成功。**

### 这意味着什么

| 影响 | 说明 |
| --- | --- |
| **不能无人值守** | 常驻服务跑一段时间后，匹配会全部失败，直到有人重新点授权链接 |
| **但可自愈** | 平台会**在响应里直接给出授权链接**，只要把它转发给人就能恢复 |
| **必须做告警** | 否则失败是「静默的」——gateway 只会看到工作流失败，不知道要人点链接 |

**建议的处置（未做）**：
1. gateway 检测到 `interrupted` 且 msg 里含 `authen/v1/authorize` 时，**把链接推到运维告警群**（复用已有的告警通道）
2. 或者**定期（如每小时）主动探一次**，过期就告警，而不是等真匹配时才炸

> ⚠️ 还有一种可能没排除：**是不是只有"用户授权"这一条路**。
> 插件配置里 `grant_type=Authentication Code`，是**用户级**授权。
> 如果平台支持换成一个**应用级/长期**的凭据（或换用 `tenant_access_token` 那条路），
> 这个定时炸弹就拆了。**值得再查一次** —— 这是目前模块二最大的运维风险。

### ⚠️ 飞书卡片回调**约 3 秒超时** —— 处理必须异步（2026-10-15）

**现象**：点「邀请 TA」，飞书提示 **「目标回调服务超时未响应」**。

**实测**：回调 16:11:07 到达，邀请 16:11:15 发出 —— **中间 8 秒**。
飞书要求回调在 **约 3 秒**内响应，所以必然超时。

**为什么这么慢**：处理一次邀请要串 **5 次飞书 API** ——
查需求行 → 查重（读邀请表）→ 读画像表 → 写邀请行 → 发卡片，
每次约 1.5 秒（还叠了代理延迟）。

**修法**：**立刻回执，活儿丢后台**（飞书官方也是这个路子）：
`on_card_action` 马上返回 `{"toast": {"type": "info", "content": "已收到，正在处理…"}}`，
真正的处理用 `asyncio.run_coroutine_threadsafe` 丢到事件循环里跑。

⚠️ **异步之后必须补一条**：成败要**另外告诉用户**（`MatchFlow.notify`），
否则失败就退化成"点了没反应" —— 那是比原问题更差的体验。

> **一条通用教训**：凡是"用户点了要立刻反馈"的入口（卡片回调、Webhook 回调），
> **别在里面同步做业务**。先 ack，再异步。

### ⚠️ 卡片里的「重新授权按钮」是坏的 —— 必须给**纯文本**

**用户反馈**（2026-10-15）：告警卡片上的「重新授权」按钮点下去总是报
「重定向 URL 有误」；而**从聊天窗口复制粘贴**的同一串 URL 就能授权成功。

**原因**：卡片按钮的 `url` 会被飞书**重新编码**。
`redirect_uri` 里的 `%2F` 一旦被解成 `/`，这个查询参数就在第一个斜杠处被截断，
飞书于是判定 `redirect_uri` 不合法 → **错误码 20029**（`redirect_uri 请求不合法`）。

**处置**：告警卡片改成显示**纯文本 URL**（`plain_text`，不是 `lark_md` ——
后者会被自动转成超链接，同样有被处理的风险），提示用户**复制粘贴到浏览器**。
修在 `gateway/app/match_flow.py::_alert_if_reauth_needed`。

> 教训：**"能点"不等于"能用"。** 凡是靠 URL 查询串传参的链接，
> 都不要托付给平台去跳转 —— 它们大多会做一次编码/规范化。

### 顺带修掉的两个 bug（都在这条链路上）

| 现象 | 根因 |
| --- | --- |
| 轮询**一直空转**到超时 | `interrupted` **不在 `_TERMINAL_STATES` 里**，`_looks_finished` 永远返回 False |
| **把失败当成功** | `_poll` 超时返回 `None`，`dispatch` 却继续走 `ok=True` 的分支 |

第二条尤其危险 —— 失败会被当成成功咽下去。现在 `interrupted` 算终态，
且 `dispatch` 会把平台给的 `msg`（含授权链接）原样带进 `error` 字段。
测试锁在 `gateway/tests/test_match_flow.py::TestGeniosTerminalStates`。

---

## 🔴 S9 · 小程序前端的**入站可达性** —— 结论：**现在不成立，卡在「稳定域名」**（2026-10-16）

**为什么探这个**：外部仓库 `mers95395-lab/campus-opportunity-pool`（Taro 写的飞书小程序，
两个 Tab：校园活动 / 组队机会池）考虑合入。它的前提是「**小程序从学生手机直接访问我们的 HTTP 接口**」，
而 D9 选多维表格当界面的理由之一正是「全程飞书内部，**不需要公网**」。
**合之前先确认我们能不能给出一个能被白名单固定住的地址。**

**做了什么**

1. 起 gateway（`0.0.0.0:8000`，`--workers 1`），`/health` → 200。
2. 起 cloudflared 快速隧道（清代理变量 + `--protocol http2 --edge-ip-version 4`），**从公网 URL** 打 `/health`。
3. 杀隧道 → 重启 → 比对两次 URL；再测旧 URL 还活不活。
4. 查本机有没有公网 IP、有没有域名与 Cloudflare 凭据。

**看到什么**

| 检查 | 结果 | 证据 |
| --- | --- | --- |
| 公网 URL → gateway | ✅ **通** | `GET /health` → **200**；gateway 日志 `188.253.7.9 - "GET /health HTTP/1.1" 200 OK` |
| 重启后 URL | ❌ **变了** | `lauren-receivers-hung-union.trycloudflare.com` → `gained-peace-lending-argument.trycloudflare.com` |
| 隧道进程停掉后的旧 URL | ❌ **530** | Cloudflare 边缘回 `http=530`（与 S5 记的 1033 同类：源站不可达） |
| 本机网络 | ❌ **无公网 IP、无入站** | 只有 `ens33: 192.168.190.128/24`（VMware NAT，网关 `192.168.190.2`）+ `docker0`；默认路由走 NAT |
| 出口 IP | ⚠️ `188.253.7.9` | 这是 Clash 代理的出口，**不是本机地址** → 进一步说明我们没有任何自有入口 |
| 稳定域名条件 | ❌ **不具备** | `~/.cloudflared/` **不存在** → 没登录 Cloudflare、没有域名 → 命名隧道现在做不了 |

**⚠️ 顺带修正 S5 的一条旧结论**：S5 写「清掉代理变量，cloudflared 就能直连」。
这次**同样清了代理变量，第一次仍然失败**：

```
failed to request quick Tunnel: Post "https://api.trycloudflare.com/tunnel":
read tcp 192.168.190.128:33464->198.18.3.90:443: read: connection reset by peer
```

根因：**这台机器的 DNS 被 Clash 的 fake-IP 接管了** —— `getent hosts api.trycloudflare.com` → `198.18.3.90`，
连 `dig @8.8.8.8` 也被劫持返回同一个 fake-IP（`198.18.0.0/15` 正是 Clash 的 fake-IP 段）。
所以「清代理变量」只解决了**应用层代理**，**DNS 层仍在 Clash 手里**。
第二次重试成功（1 次 retry，`location=tpe01 protocol=http2`），第三次 0 次 retry —— **能通，但不稳。**

**结论**

1. **技术上通，工程上不成立。** 隧道确实把公网请求送到了 gateway，但快速隧道**URL 每次重启都变、
   进程一停就 530**；而飞书小程序的「服务器域名」是**预先白名单** ——
   **一个会变的域名根本加不进去**。
2. 合入小程序的**前置条件 = 一个稳定域名**，二选一（都在 [人] 手上）：
   - **命名隧道**：Cloudflare 账号 + **一个自有域名**（`cloudflared tunnel login` → `create` → 加 DNS 记录）；
   - **公网服务器**：把 gateway 部署到有公网 IP 的机器上（校内服务器若有公网 IP 也算）。
3. **还有一个未确认的硬条件：ICP 备案。** 这次**没拿到官方文档**：`open.feishu.cn` 的文档页是 JS 渲染，
   WebFetch 只抓到标题「开发文档 - 飞书开放平台」，没有正文；搜索命中的都是微信/阿里系平台的规则，
   **不能当飞书的规定用**。⇒ 需要 [人] **在控制台当场试加一个域名**，看是否要求备案主体/备案号。
   这直接决定**海外域名（trycloudflare / Cloudflare 托管域名）到底能不能用**。
4. **另有一条不随域名解决的硬约束**：前端仓库自带的 appid 是 `cli_aa4532d4c4f8dbe1`，
   我们的自建应用是 `cli_aa4ede…`。**`ou_` open_id 按应用隔离** —— 不统一的话，
   小程序 `Taro.login()` 换来的 open_id 与多维表格「人员字段」里存的**对不上，申请无法归因，而且不报错**。
   ⇒ 小程序与机器人**必须合并到同一个飞书应用**。

**对架构的影响**：合入小程序 = **必须给 gateway 一个稳定的公网 https 入口** ——
这**推翻了 D9「不需要公网」的前提**，应作为新决策（建议 **D10**）与「入口由谁提供、成本多少」一起定。

**[人] 下一步（按顺序）**

1. 打开飞书开放平台 →「开发配置 → 安全设置 → 服务器域名」，**试着加一个域名**，看它要求什么
   （https？备案？能否加二级域名/通配）。**把截图或报错原文贴回来** —— 这是关闭本探针唯一缺的证据。
2. 定公网入口：有自有域名 + Cloudflare 账号 → 命名隧道（脚本我来写）；有公网服务器 → 直接部署。
3. 决定小程序与机器人是否合并到同一个飞书应用。

**⬜ 本探针未覆盖（候选：S10）**

- **小程序能不能不经过我们的后端，直接读多维表格？** 若能，「公网入口」这个阻塞就绕开了。
  我的**判断**（**不是实测**）：大概率不行 —— 飞书 OpenAPI 换 token 需要 `app_secret`，
  而小程序包可以被反编译，密钥不能进包。
  但平台有没有「多维表格 JSAPI / 云函数」这类免后端能力，**我没有资料**，属 ❓，要查要问。

---

## ⚠️ 与其他文档的冲突（施工前须一并处理）

- **`AGENTS.md` 铁律 4** 现在写着「阶段 1 不做：组队匹配、用户画像、个性化推荐……」，
  与 D9 直接冲突。**开工前必须更新**，否则下一个 agent 会以为越界。
- **`docs/genios_workflow_spec.md`** 里「HTTP 请求节点回写 gateway」的节点图**已失效**。
- **`PLAN.md` §6** 原写「后续，本次不施工」，现已启动。
