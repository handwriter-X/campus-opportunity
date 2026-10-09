# 交接文档 · 校园机会搭子

> 给接手这个项目的人看的。目标：**读完之后你能把它跑起来、改得动、知道哪里是坑。**
>
> 最后更新：2026-10-09

---

## 一、这是什么（30 秒版）

**南开大学的校园机会发现智能体**，要拿去做大赛作品，必须基于**南开大学 GeniOS 平台**搭建。

它做的事：

> 公众号发新文章 → 自动采集 → GeniOS 判断「这是不是学生能报名的机会」并抽成结构化字段
> → 落库 → 推送飞书

**核心约束（来自赛制，不能改）**：

> **判断、抽取、校验这些"智能逻辑"必须留在 GeniOS 平台内。**
> 我们自己写的那个服务（`campus-gateway`）**只负责搬运、排队、持久化，不做任何理解和判断**。

这条约束解释了这个项目里几乎所有的设计选择。看到任何"为什么这里绕了一下"的疑问，先回来读这条。

---

## 二、现在到哪了

### ✅ 已经跑通的

**完整的闭环，用真实文章验证过**：

```
公众号文章 → We-MP-RSS → /ingest → worker → GeniOS(Start→大模型→End)
                                              ↓ 轮询取回结果
                                        落库 + 推飞书
```

实测日志（每一步都有时间戳，可在 `docs/findings.md` 查到）：
接口调用成功、worker 真派发（非 dry-run）、结果被正确解析、入库 0.05 秒、飞书收到消息。

### 🔄 做了但还没接上的

| 东西 | 状态 |
| --- | --- |
| **三层校验**（`genios/code_nodes/parse_and_validate.py`） | 写好了、本地验过，但**当前链路没接** —— 模型编造的字段现在会直接入库 |
| **飞书卡片** | 卡片 JSON 已有（`genios/feishu_cards/`），但推送目前发的是**纯文本** |
| **多机会文章的处理** | 现在一篇文章只出一批结果；「本周活动一览」这类含多个机会的汇总推文处理不完整 |
| **评测集** | `eval/samples/` 有 3 份样本，`labels/` 是空的，`run_eval.py` 没写 |

### ⛔ 还没做的

- 组队匹配、用户画像、个性化推荐、隐私处理（`PLAN.md` §0 明确排除在阶段 1 之外）

---

## 三、架构与数据通路

### 一张图

```
┌──────────────────┐
│ 微信公众号        │
└────────┬─────────┘
         │ 每 5 分钟轮询
         ▼
┌──────────────────┐
│ We-MP-RSS        │  Docker 容器，6.35GB，端口 8001
│ （第三方开源项目） │  通过微信读书通道抓文章
└────────┬─────────┘
         │ POST /ingest  （带 X-Ingest-Secret 请求头）
         ▼
┌──────────────────────────────────────────────┐
│ campus-gateway（本仓库的代码，FastAPI）        │
│                                              │
│  ① /ingest   校验密钥 → 规范化 → 幂等去重      │
│              → 历史过滤 → 入库(状态=queued)    │
│  ② worker    取队列 → 调 GeniOS → 轮询结果     │
│              → 入库 → 推飞书                  │
│  ③ /opportunities  机会的查询接口              │
└────────┬─────────────────────────┬───────────┘
         │ POST run_app_workflow    │ POST im/v1/messages
         │ （我们主动调它）           │ （我们主动推）
         ▼                          ▼
┌──────────────────┐       ┌──────────────────┐
│ GeniOS（南开平台）│       │ 飞书              │
│ 底层是 HiAgent    │       │ （自建应用）       │
│                  │       └──────────────────┘
│ Start→大模型→End │
│ 判断+抽取+校验    │
└──────────────────┘
```

**关键点：全部是出站连接。** gateway 主动往外连 GeniOS 和飞书，**不需要任何人能反向访问它**。
这一点很重要，见下面「关键决策」。

### 走一遍：一篇竞赛通知的一生

1. **采集**：We-MP-RSS 每 5 分钟扫一次订阅的公众号，发现新文章
2. **通知**：它把文章（标题、链接、正文、发布时间）POST 到 gateway 的 `/ingest`
3. **搬运**：gateway 校验密钥、算指纹去重（同一篇发两次只处理一次）、判断是不是历史文章、存进 SQLite，状态标为"排队中"
4. **派发**：gateway 里的后台 worker 取一条出来，把文章打包成 JSON，调用 GeniOS 的 `run_app_workflow`
5. **理解**：GeniOS 跑工作流 —— 大模型判断"是不是机会"，并抽出结构化字段（名称/类型/时间/地点/名额/报名链接/原文依据…）
6. **取回**：worker 每 3 秒问一次 GeniOS"跑完了吗"，直到拿到结果
7. **落地**：worker 把结果**写进数据库**（同步，毫秒级），并**推送飞书**（异步，不阻塞）

---

## 四、从零把它跑起来

### 前置

| 需要什么 | 怎么弄 |
| --- | --- |
| Python 3.11+ | 本机验证过 3.14 |
| Docker | 跑 We-MP-RSS 用 |
| 一个微信号 | We-MP-RSS 要扫码授权（**必须是某个公众号的管理员**） |

### 步骤

```bash
# 1. 依赖
cp .env.example .env          # 然后按「凭据清单」填
python3 -m venv .venv
.venv/bin/pip install -r gateway/requirements.txt

# 2. 验收：应该 109 passed
cd gateway && ../.venv/bin/pytest -q && cd ..

# 3. 起 gateway
PYTHONUTF8=1 .venv/bin/python -m uvicorn app.main:app --app-dir gateway --host 0.0.0.0 --port 8000

# 4. 另开一个终端，跑端到端冒烟
PYTHONUTF8=1 .venv/bin/python scripts/smoke_test.py --base http://127.0.0.1:8000
```

### 采集端（We-MP-RSS）

```bash
docker run -d --name we-mp-rss --restart unless-stopped \
  -p 8001:8001 \
  -v "<仓库绝对路径>/data/we-mp-rss:/app/data" \
  -e TZ=Asia/Shanghai -e DB=sqlite:///data/we_mp_rss.db \
  -e USERNAME=admin -e PASSWORD=<自定> \
  -e WEBHOOK.CONTENT_FORMAT=text \
  -e GATHER.CONTENT=True \
  --add-host=host.docker.internal:host-gateway \
  ghcr.io/rachelos/we-mp-rss:latest
```

然后浏览器开 `http://<机器IP>:8001`，登录后**依次做两次授权**：

1. **公众号授权**（顶栏「扫码授权」）—— 用**公众号管理员**的微信扫。这一步只用于**搜索公众号**。
2. **微信读书授权**（顶栏书本图标）—— 用**你的个人微信**扫。**采集文章靠的是这一步。**

> ⚠️ **这两个都是必需的前提，不是可选项。** 这个版本的 We-MP-RSS 把所有公众号都强制走微信读书通道采集
> （`apis/mps.py` 把 Feed.id 写成 `MP_WXS_*`，而 `jobs/mps.py` 看到这个前缀就切到 weread_mp 采集器）。
> 没有微信读书 Cookie，采集一条都不会成功。

再新建一个**消息任务**：

| 字段 | 值 |
| --- | --- |
| 类型 | 调用 webhook |
| Webhook 地址 | `http://host.docker.internal:8000/ingest` |
| Headers (JSON) | `{"X-Ingest-Secret": "<你的 INGEST_SHARED_SECRET>"}` |
| 消息模板 | 默认模板**不够用**，见下方 |
| Cron | `*/5 * * * *` |

**消息模板必须自定义**，因为默认模板**不含正文**，只发摘要：

```
{"feed":{"id":"{{ feed.id }}","name":"{{ feed.mp_name }}"},"articles":[{% if articles %}{% for article in articles %}{"id":"{{ article.id }}","mp_id":"{{ article.mp_id }}","title":"{{ article.title }}","url":"{{ article.url }}","description":"{{ article.description }}","publish_time":"{{ article.publish_time }}","content":"{{ article.content }}"}{% if not loop.last %},{% endif %}{% endfor %}{% endif %}],"now":"{{ now }}"}
```

---

## 五、凭据清单

**全部放 `.env`，绝不进代码、日志、仓库**（`.gitignore` 已挡，但别依赖它）。

| 类别 | 键名 | 从哪来 |
| --- | --- | --- |
| gateway 内部 | `INGEST_SHARED_SECRET` | 自己随机生成，We-MP-RSS 和 gateway 双方约定 |
| gateway 内部 | `INTERNAL_SHARED_SECRET` | 自己随机生成 |
| GeniOS | `GENIOS_APP_ID` / `GENIOS_API_KEY` | GeniOS 平台「后端服务 API」页面（**流程编排型**智能体才有） |
| GeniOS | `GENIOS_API_BASE_URL` / `GENIOS_API_PATH` | 见 `.env` 里已填的实测值 |
| 飞书 | `FEISHU_APP_ID` / `FEISHU_APP_SECRET` | 飞书开放平台 → 自建应用 |
| 飞书 | `FEISHU_NOTIFY_TARGET` | 收消息的人（`ou_…`）或群（`oc_…`） |

获取 `ou_`/`oc_` 的办法：让目标用户/群给机器人发一条消息，长连接探针会把事件（含 `open_id`）打到
`data/captures/feishu_events.jsonl`。

```bash
env -u ALL_PROXY -u all_proxy -u HTTPS_PROXY -u https_proxy \
  .venv/bin/python scripts/feishu_longconn_probe.py
```

> ⚠️ `.env` 里存的是**真实凭据**。别提交、别截图、别贴进聊天记录。

---

## 六、代码导航

### gateway（我们写的服务）

| 文件 | 职责 | 想改什么来这里 |
| --- | --- | --- |
| `app/main.py` | 应用装配、lifespan、`/health` | 加路由、改启动逻辑 |
| `app/config.py` | 所有配置项（全部来自 `.env`） | 加配置 |
| `app/ingest.py` | `POST /ingest`：We-MP-RSS 入口 | 改入站逻辑 |
| `app/adapters/wemp_rss.py` | 把 We-MP-RSS 格式翻译成内部格式 | **换了采集工具就来这** |
| `app/normalize.py` | 正文清洗、链接提取、去重键 | 改去重规则 |
| `app/store.py` | 数据库读写、状态派生 | 改表结构、改去重/合并策略 |
| `app/worker.py` | 后台工人：派发 → 取结果 → 入库 → 推送 | 改链路顺序、改推送内容 |
| `app/genios_client.py` | 跟 GeniOS 说话（请求怎么拼、响应怎么读） | **换了平台/接口变了就来这** |
| `app/feishu_app.py` | 跟飞书说话（自建应用） | 改推送方式 |
| `app/push.py` | 飞书群自定义机器人（备用通道）+ 告警 | — |
| `app/debug.py` | `/_debug/echo`、`/ingest/_debug` 探针端点 | — |

### 必须理解的三个不变量

1. **时区一律 `Asia/Shanghai`**，代码里**拒绝 naive datetime**（会直接抛错）。这是刻意的。
2. **`uvicorn --workers` 必须是 1**：后台 worker、限流器、告警去重都是单进程假设，多 worker 会重复派发。
3. **`gateway` 不做判断**：`store.py` 刻意保持"薄"，不判断是否机会/是否推送。别把智能逻辑写进来。

### genios/（粘到平台里的内容，不是拿来跑的）

| 文件 | 粘到哪 |
| --- | --- |
| `prompts/step1_extract.md` | 大模型节点（含系统提示词、用户提示词、few-shot） |
| `code_nodes/parse_and_validate.py` | 代码节点（解析 + 三层校验）——**当前未接入** |
| `schemas/opportunity.schema.json` | 字段字典，提示词与校验共用 |
| `feishu_cards/*.json` | 飞书卡片版式 |

搭建步骤见 `docs/genios_workflow_spec.md`。

---

## 七、关键决策与理由

这些是方案里没写死、我们**替后来人做过的判断**。改之前请先读懂理由。

| # | 决策 | 理由 |
| --- | --- | --- |
| D1 | 发布时间未知 → 判为 backfill（不推送） | 防止首次启动倒灌历史文章刷屏 |
| D2 | 去重键在两个日期都缺时退化为原文时间表达 | 偏向"漏推可人工补，重复推会让人退群" |
| D3 | `week=current` = 未截止 ∧ 活动未结束 ∧ 报名已开始/本周内开始 | 解读为「本周快照里仍可参与的」 |
| D4 | 命中重复时只补空缺、不覆盖已有值 | 已认定的值优先，也避免重发打回推送状态 |
| D5 | `GET /opportunities` 默认免鉴权 | 校内只读；`REQUIRE_AUTH_FOR_GET=1` 可收紧 |
| D6 | `/_debug/*` 免鉴权 | GeniOS 的 HTTP 节点不带我们的密钥，探针必须能打到。**对外长期暴露前必须关** |
| D7 | 机会类型按 4 类施工 | 字段体系文档的原文枚举 |
| D8 | 发布时间不精确 → **稳态下不特殊处理** | 每 5 分钟轮询只交付增量，没有"首次倒灌"场景；误差上界就是轮询间隔 |

### 一次重要的架构调整（2026-10-07）

**原设计**：GeniOS 工作流用 **HTTP 节点回写** `POST /opportunities` 落库。

**改成**：worker 拿到 GeniOS 结果后**自己入库**。

**为什么**：那个 HTTP 节点要传的 JSON，我们**本来就从轮询里拿到了**；而它带来一个很贵的硬要求——
**gateway 必须能被 GeniOS 反向访问到**。但这台机器在 VMware NAT 私有网段里（`192.168.190.128`，
出网 IP 是天津电信），校内根本够不到，只能靠内网穿透隧道，而那条隧道**一天之内死了三次**
（进程活着、公网不通）。

去掉回写之后，**整个系统只需要出站连接**，隧道、端口映射、校园网入站策略全都不需要了。

**这不违反赛制**：判断/抽取/校验仍然全在 GeniOS 内；「把结果搬进数据库」是搬运不是理解。

---

## 八、踩过的坑（都是真实花过时间的）

### 环境类

| 坑 | 症状 | 解法 |
| --- | --- | --- |
| **`ALL_PROXY=socks5://…`** | httpx 建 client 时直接崩（5 个测试模块全 ERROR，看着像代码坏了） | `requirements.txt` 里用 `httpx[socks]`；跑长连接/cloudflared 时要**清掉代理变量** |
| **Windows 搬来的 `.venv`** | `pip`/`pytest` 以奇怪的方式失败 | 删掉重建（Windows 是 `Scripts\python.exe`，Linux 是 `bin/python`） |
| **`.env` 是 CRLF 行尾** | 密钥读进来带 `\r`，鉴权永远失败且报错看着正常 | `sed -i 's/\r$//' .env` |
| **Docker Hub 被墙** | `docker compose build` 拉不到 `python:3.11-slim` | 配国内 registry mirror，或换镜像源（ghcr.io 是通的） |
| **飞连零信任网关** | GeniOS 的域名从这台机器访问会被 302 到 IAM | **只用于结论**：我们调 GeniOS 的 API 反而是通的（`/api/proxy/**` 是豁免路径） |

### 静默失败类（最危险——不报错、日志正常、结果就是不对）

| 坑 | 症状 | 解法 |
| --- | --- | --- |
| **`runId` vs `RunID`** | 轮询被静默跳过，`task_id=None` | 提交**响应**里是小写 `runId`；查询**请求体**里是大写 `RunID` |
| **轮询把「还在跑」当「已完成」** | 耗时超 3 秒的任务被提前取走，拿到空结果，日志显示「结果未识别」 | HiAgent **无论跑没跑完都返回 `output` 字段**；改成**有 `status` 就以 status 为准** |
| **We-MP-RSS 默认模板不含正文** | 收到载荷里 `content` 是空串，抽取无从谈起 | 必须自定义消息模板加 `{{ article.content }}` |
| **We-MP-RSS 默认 `GATHER.CONTENT=False`** | 采集时根本不取正文 | 启动容器时加 `-e GATHER.CONTENT=True` |

### GeniOS 平台细节类

| 坑 | 症状 | 解法 |
| --- | --- | --- |
| **大模型输出是字符串** | 输出信封是 `{"raw_output": "<字符串>"}`，里面的 JSON 要再解析一次 | 下游显式 `json.loads` |
| **代码节点契约** | 用顶层 `return` 报 `SyntaxError`；只用 `print` 节点判失败 | 必须 `def handler(inputs): ... return {...}` |
| **代码节点前面有插入行** | `from __future__ import` 报「必须在文件开头」 | 我们的代码实际从第 16 行开始，不能用任何"必须最前"的语句 |
| **`links` 类型填错导致全部失败** | 三组对照：数组 → `input validate failed`；不带 → 成功 | Start 节点的 `links` 必须是**数组**类型 |
| **模型按当前年份推日期** | 2025 年的通知被推成 2026，日期错一年 | 用原文标注的**星期**做交叉校验（`parse_and_validate.py` 已实现） |
| **`24:00` 在 Python 3.10 解析失败** | 「10月24日24:00截止」这种常见写法在代码节点里报错 | 手工归一化成次日 `00:00`（3.11+ 才原生支持，所以本地测不出来） |

---

## 九、接下来做什么

按优先级：

### 1. 补上三层校验（最该先做）

现在**模型编造的字段会直接入库**。`genios/code_nodes/parse_and_validate.py` 已经写好并本地验过，
但它原本设计成跑在 GeniOS 的代码节点里，而当前链路绕过了代码节点。

**两个选择**：
- **搬进 gateway**（在 `worker` 入库前跑一遍）—— 改动小，和"worker 直接入库"的新架构一致
- **接回 GeniOS 代码节点**（大模型 → 代码节点 → End）—— 符合原方案，但要在 GeniOS 里加节点并重新发布

### 2. 飞书卡片

现在推的是纯文本。`genios/feishu_cards/instant.json` 有现成版式，`scripts/probe_feishu_webhook.py --card` 能预览。

### 3. 评测集（`PLAN.md` 阶段 5）

需要 50–100 篇标注样本。`eval/README.md` 列了必须凑齐的 6 类样本。
**这是答辩时最能证明"智能是真的"的东西**——能拿出准确率数字，比说"我们用了大模型"有说服力得多。

### 4. 多机会文章 / 两段式工作流

现在一篇文章只调一次大模型。「本周活动一览」这类含多个机会的汇总推文处理不完整。
`PLAN.md` §6 设计的两段式（分类 → 循环 → 按类型抽取）能解决，`docs/genios_workflow_spec.md` 第 4 节写了怎么演进。

---

## 十、去哪看更多

| 想知道什么 | 看哪 |
| --- | --- |
| 每个技术结论的**证据**（真实响应片段、报错原文） | `docs/findings.md` —— **最详细的账本，遇到疑问先查这里** |
| 原始需求、施工方案、验收标准 | `PLAN.md` |
| GeniOS 工作流怎么搭 | `docs/genios_workflow_spec.md` |
| 字段体系（枚举值的权威来源） | `docs/校园机会信息整合_最终业务字段体系.docx` |
| 产品需求 | `docs/产品需求文档.docx` |
| 让 AI 接手 | `AGENTS.md` |
