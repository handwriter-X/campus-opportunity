# AGENTS.md

给接手这个仓库的 AI agent 看的。人请读 [`HANDOVER.md`](HANDOVER.md)。

---

## 这个项目是什么

南开大学校园机会发现智能体，参赛作品，**必须基于南开 GeniOS 平台**（底层是火山引擎 HiAgent）。

闭环：`公众号文章 → We-MP-RSS 采集 → campus-gateway 搬运 → GeniOS 判断+抽取 → 回传入库 → 推飞书`

---

## 铁律（违反即返工）

1. **判断/抽取/校验等智能逻辑必须留在 GeniOS 内。**
   `gateway/` 里**不许**出现"这是不是机会""要不要推送"这类判断。
   `store.py` 刻意保持"薄"，别往里加业务智能。这条来自赛制，不是偏好。

2. **遇到 ❓ 不许猜。** 方案里标 ❓ 的都是没有公开资料、必须靠实验或问用户的。
   先做探针 → 把**实测结果**（做了什么/看到什么/结论/证据）写进 `docs/findings.md` → 再继续。
   **不要凭合理推测写死一个值然后往下走。**

3. **密钥只放 `.env`。** 不进代码、不进日志、不进 `docs/`、不进提交。
   明文密钥出现在任何被提交的文件里 = 严重事故。

4. **不要自行扩大范围。** 阶段 1 不做：组队匹配、用户画像、个性化推荐、隐私处理、飞书自建应用。

5. **改行为前先读 `docs/findings.md`。** 里面记着 8 条替用户做过的判断（D1–D8），
   它们是深思熟虑的取舍，**不是 bug**。要改先问用户。

---

## 事实层级（冲突时按这个顺序信）

| 优先级 | 文件 | 是什么 |
| --- | --- | --- |
| 1 | `docs/findings.md` | **实测账本**。每个技术结论的证据（真实响应、报错原文） |
| 2 | 代码本身 | 行为的事实 |
| 3 | `PLAN.md` | 原始需求与施工方案（**权威，但 §4 的许多 ❓ 已被 findings 关闭**） |
| 4 | `README.md` / `HANDOVER.md` | 概览，可能滞后 |

`docs/findings.md` 是**持续更新的**。改代码前先在里面搜关键词，很可能有人已经踩过。

---

## 命令

```bash
# 测试（期望 109 passed）
cd gateway && ../.venv/bin/pytest -q

# 起服务（--workers 必须是 1，见「不变量」）
PYTHONUTF8=1 .venv/bin/python -m uvicorn app.main:app --app-dir gateway --host 0.0.0.0 --port 8000

# 端到端冒烟（服务起着时另开终端）
PYTHONUTF8=1 .venv/bin/python scripts/smoke_test.py --base http://127.0.0.1:8000

# 探针：GeniOS API
.venv/bin/python scripts/probe_genios.py --dry-run

# 飞书长连接（收事件；必须清代理变量）
env -u ALL_PROXY -u all_proxy -u HTTPS_PROXY -u https_proxy \
  .venv/bin/python scripts/feishu_longconn_probe.py

# 飞书发消息
.venv/bin/python scripts/feishu_send.py --to ou_xxx --text "..."
```

---

## 不变量（改代码时不能破坏）

1. **时区一律 `Asia/Shanghai`。** 代码里**拒绝 naive datetime**（`models.UTCDateTime` 直接抛错）。
   这是刻意的，别"修"它。
2. **`uvicorn --workers` 必须是 1。** 后台 worker、飞书限流器、告警去重都是单进程假设。
   多 worker 会**重复派发**。`gateway/Dockerfile` 已固定，别改。
3. **`/ingest` 必须幂等。** 同一篇发两次只处理一次（`article_id = sha256(原文链接)`）。
4. **去重语义是"只补空缺、不覆盖"**（`store.py::_merge_missing`）。
   别改成覆盖已有值——会把人已经确认的字段冲掉，也会把 `push_status` 打回"未推送"导致重复推送。
5. **机会类型是固定 4 类**，枚举值逐字取自 `docs/*最终业务字段体系.docx`：
   `竞赛` / `学术与学习交流` / `志愿活动与社会实践` / `校园文体活动`。**不要用简称。**
6. **测试必须保持全绿。** 改了行为就补测试。

---

## 目录导航：想改什么去哪

| 想改 | 去 |
| --- | --- |
| 入站逻辑（收到文章后干什么） | `gateway/app/ingest.py` |
| **换了采集工具**（不再是 We-MP-RSS） | `gateway/app/adapters/` —— 新增一个同签名模块，`/ingest` 主流程不动 |
| 去重规则 / 历史过滤 | `gateway/app/normalize.py` |
| 数据库表结构 / 合并策略 | `gateway/app/store.py` + `models.py` |
| **链路顺序**（派发→取结果→入库→推送） | `gateway/app/worker.py::_process` / `_deliver` |
| **GeniOS 接口变了** | `gateway/app/genios_client.py`（设计上全部由 `.env` 驱动，优先改配置） |
| 推送方式 / 推送内容 | `gateway/app/feishu_app.py`、`worker.py::format_notification` |
| 加配置项 | `gateway/app/config.py` + **同步 `.env.example`** |
| 提示词 / 抽取字段 | `genios/prompts/step1_extract.md` + `genios/schemas/opportunity.schema.json` |
| 三层校验 | `genios/code_nodes/parse_and_validate.py`（**当前未接入链路**） |

---

## 已知陷阱

### 静默失败（最危险：不报错、日志正常、结果就是不对）

| 陷阱 | 特征 |
| --- | --- |
| `runId`（提交响应，小写）vs `RunID`（查询请求体，大写） | 填错 → 轮询被静默跳过，`task_id=None` |
| 轮询把"还在跑"当"已完成" | HiAgent **无论跑完没跑完都返回 `output` 字段**（没跑完是 `null`）。判完成必须看 `status`，不能看有没有 `output` |
| We-MP-RSS 默认模板不含正文 | 载荷里 `content` 是空串 |
| We-MP-RSS 默认 `GATHER.CONTENT=False` | 采集时根本不取正文 |

### 环境

- **`ALL_PROXY=socks5://…`**：httpx 建 client 会崩。靠 `httpx[socks]` 解决；
  cloudflared / 飞书长连接必须**清掉代理变量**才能连上。
- **Docker Hub 被墙**：`registry-1.docker.io` 不可达（ghcr.io 可达）。
- **飞连零信任网关**：`coze.nankai.edu.cn` 从外部访问会被 302 到 IAM；
  但 `/api/proxy/**` 是豁免路径，**我们调 GeniOS 的 API 是通的**。

### GeniOS 平台

- 大模型节点输出信封是 `{"raw_output": "<字符串>"}` —— 里面的 JSON 要**再解析一次**。
- 代码节点必须 `def handler(inputs): ... return {...}`；**不能顶层 `return`**，也不能只靠 `print`。
- 代码节点**前面会被插入约 16 行**，所以 `from __future__ import` 之类不能用。
- Start 节点的 `links` 必须是**数组**类型，否则整个工作流在 Start 就失败。

---

## 当前状态与下一步

**已跑通**：完整闭环（真实文章验证过）。

**写了但没接上**：
- 三层校验（`genios/code_nodes/parse_and_validate.py`）—— **现在模型编造的字段会直接入库**
- 飞书卡片（现在推纯文本）

**没做**：评测集（`eval/` 有样本，`run_eval.py` 未写）、两段式工作流、多机会文章处理。

详细任务清单见 `HANDOVER.md` 第九节。

---

## 工作方式

- **改完了要能证明。** 跑了测试贴结果；跑了端到端贴日志。不要只说"已完成"。
- **每个技术结论写进 `docs/findings.md`**：做了什么、看到什么、结论、证据。
  这是给用户看的账本，也是给下一个 agent 看的。**这个项目的工作纪律就是它。**
- **卡住了就说。** 尤其是涉及架构分岔的（比如"GeniOS 能不能访问我们"这类），
  停下来汇报比绕过去更省事。
