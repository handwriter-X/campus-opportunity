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

> **本轮所有探针均已关闭或有了替代方案。** 剩下的不是「未知」，而是「还没做」——
> 见文末的「待决 / 待办」。S4 原计划用群自定义机器人 Webhook，
> 但因为服务要跑在被飞连挡着的校内网，改用了自建应用（S6），**S4 不再必要**。

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

### 🆕 待决（2026-10-07）：三层校验现在无处安放

改成「worker 直接入库」之后，`genios/code_nodes/parse_and_validate.py` 里那套
**格式层 / 逻辑层 / 依据层**校验**暂时没有接进任何一条链路**：

- 原本设计：跑在 GeniOS 的代码节点里（大模型节点 → 代码节点 → 回写）
- 现在的链路：大模型节点 → End → worker 入库，**中间没有校验**

后果：**模型编造的字段、原文里没有依据的字段，现在会被直接写进库**。
提示词里的约束会降低概率，但没有代码兜底。

三个选项（待用户定）：
1. **把校验搬进 gateway**（worker 入库前跑一遍）—— 改动小，且和「worker 直接入库」的新架构一致
2. **接回 GeniOS 代码节点**（大模型 → 代码节点 → End）—— 符合 PLAN §6，但要在 GeniOS 里加节点
3. 暂时不做

> 备注：代码节点里那两条实测教训（`T24:00` 归一化、星期一致性校验）在选项 1 时要一起搬过来。

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
