# 探针操作清单（阶段 0）

> 这份是**给你（人）**的操作手册。每一步都写了「在哪做、点什么、把什么贴回来」。
> 做完一步，把结果贴给 Claude Code，我写进 `docs/findings.md` 并继续。
>
> **优先级**：S1 > S5 > S3 > S2 > S4。S1 和 S5 决定架构，先做这两个。

---

## ⚠️ 开工前先办两件事

### 1. ✅ 放入两份文档 —— 已完成（2026-10-05）

`docs/` 下已有 `产品需求文档.docx` 与 `校园机会信息整合_最终业务字段体系.docx`。
已提取核对：**Q8 关闭**（确认 4 类），枚举值已按文档原文对齐代码。详见 `docs/findings.md` 的 Q8。

### 2. ✅ 确认 Docker —— 已完成（2026-10-05）

Linux VM 上是 Docker 29.1.3，**免 sudo 可用**。S3 可以直接做。

---

## S1 · GeniOS API（最高优先级）

**目标**：拿到流程编排型智能体的真实调用方式，关闭 Q1。

### 步骤 1.1 —— 建最小工作流 [人]

> 💡 你刚才是拿一个带 HTTP 请求节点的工作流做的 S5 测试——**直接复用那个就行**，
> 把 HTTP 节点删掉，换成「Start → End」，比新建省事。

在 GeniOS 里准备一个工作流，只放两个节点：

```
Start（入参：一个字符串，例如 input_text / query / 你看到的名字）
   ↓
End（输出：把 Start 的入参原样输出）
```

> 📌 **贴回来**：Start 节点的**入参配置界面截图**。我要知道它到底支持几个参数、叫什么名字、是不是只能收一个 JSON 字符串。

### 步骤 1.2 —— 发布为「流程编排型智能体」 [人]

选择发布 → 智能体类型选**流程编排型** → 关联刚建的工作流。

> 📌 **贴回来**：发布成功后「概览 / 后端服务 API」页面的截图，**把密钥打码**，但保留：
> - 接口 URL 的**形状**（域名 + 路径，如 `https://xxx.nankai.edu.cn/api/v1/agent/chat`）
> - 鉴权请求头的**名字**（如 `Authorization`、`X-API-Key`）
> - APPID 和密钥放在**哪里**（请求头？请求体？query？）

### 步骤 1.3 —— 找文档 [人]

在飞书知识库里，打开「NK-GeniOS知识库 › 智能体发布管理与 API 接入」，看**同一层级的兄弟页面**，找「调用说明」「API 文档」「请求示例」「错误码」这类页面。

> 📌 **贴回来**：把「调用说明 / 请求示例」页面**整页文字**复制给我（curl 示例、请求体 JSON、响应 JSON 最重要）。
>
> 🔴 **这是本次探针里信息量最大的一步**。有它，Q1 基本直接关闭，`scripts/probe_genios.py` 不用猜。

### 步骤 1.4 —— 跑探针脚本 [CC]

文档和凭据到手后，我填 `.env` 并跑：

```bash
python scripts/probe_genios.py --dry-run    # 先看要发什么
python scripts/probe_genios.py              # 真发
```

**验收**：脚本能触发一次工作流执行、看到 End 节点返回的字符串，异步任务 ID 与查询方式有明确结论。

---

## S5 · 网络连通矩阵（与 S1 并列最高优先级）

**目标**：确认 GeniOS 能不能主动访问我们的服务器。**这是关键分岔点。**

### 步骤 5.1 —— 起 gateway [CC]（Linux VM 上）

```bash
python3 -m venv .venv
.venv/bin/pip install -r gateway/requirements.txt
PYTHONUTF8=1 .venv/bin/python -m uvicorn app.main:app --app-dir gateway --host 0.0.0.0 --port 8000
```

> 📌 本 VM 的内网地址是 `192.168.190.128`（VMware NAT），**云端 GeniOS 够不着**，必须走隧道。
> cloudflared 已装在 `~/.local/bin/cloudflared`。

### 步骤 5.2 —— 本机自测 [人]

浏览器打开 `http://127.0.0.1:8000/health`，应返回 `{"status":"ok",...}`。

### 步骤 5.3 —— 让外网能访问到 [人] ⚠️ 关键

GeniOS 在云端，`127.0.0.1` 它够不着。三选一：

| 方案 | 做法 | 适用 |
| --- | --- | --- |
| A. 内网穿透（最快） | `cloudflared tunnel --url http://localhost:8000` 或 ngrok | 探针阶段推荐 |
| B. 校园服务器 | 部署到有公网 IP 的机器 | 长期 |
| C. 内网地址 | 若 GeniOS 与你的机器同网段，直接用内网 IP | 需确认 |

> 📌 **贴回来**：拿到的公网 URL（如 `https://xxx.trycloudflare.com`）。

### 步骤 5.4 —— 在 GeniOS 里测回连 [人]

在 S1 的工作流里加一个 **HTTP 请求节点**，配置：

```
方法：POST
URL：  <你的公网URL>/_debug/echo
Header：Content-Type: application/json
Body：  {"from":"genios","ts":"test"}
```

运行工作流。

**判定**：

- ✅ gateway 日志里看到这条请求 → **GeniOS 能访问我们**，落库走 gateway，架构不变
- ❌ 超时/连接失败 → **关键分岔触发**：落库必须改成写飞书多维表格，我立刻停下来重新设计，不写 `POST /opportunities`

再测一条：HTTP 节点 POST 到 `https://open.feishu.cn/open-apis/bot/v2/hook/<假路径>`，看返回的是 **404/权限错误**（说明能连通外网）还是**连接超时**（说明 HTTP 节点被限制出网）。

> 📌 **贴回来**：两次的结果（gateway 日志 / GeniOS 报错原文）。

### 步骤 5.5 —— 其他方向 [人]

确认服务器能否访问：微信（`mp.weixin.qq.com`）、飞书（`open.feishu.cn`）、GeniOS 平台。

---

## S3 · We-MP-RSS 真实载荷

**目标**：拿到真实 Webhook payload，关闭 Q6。

1. [CC] 我写好 `docker-compose.yml`（已就绪）
2. [人] `docker compose up -d`，浏览器打开 `http://127.0.0.1:8001`，**微信扫码授权**
3. [人] 添加 **2–3 个测试公众号**（校内公开号，先别多加，见 Q10 风控）
4. [人] 进「消息任务」，新建任务：
   - 类型选 **自定义 Webhook**（`message_type=1`）
   - Webhook 地址：`http://gateway:8000/ingest/_debug`（容器内互访）
   - 自定义请求头：`X-Ingest-Secret: <你 .env 里的 INGEST_SHARED_SECRET>`
   - 正文格式：先用 `markdown`，后面再试 `text`/`html`
   - 先**不要**开定时，手动点「测试」
5. [CC] 从 `data/captures/` 取出真实载荷，存成 `eval/samples/webhook_payload_*.json`，据此写适配器

> 📌 **贴回来**：如果「消息任务」界面和我描述的不一样，**直接截图给我**——这是我的假设（来自自动生成 wiki，⚠️ 非官方），很可能有出入。

---

## S2 · 工作流内能力（S1 通了再做）

详细的可粘贴内容和判定标准见 **`docs/genios_s2_experiments.md`**。三个实验：

- **A** 大模型节点能否约束 JSON 输出（关闭 Q2）
- **B** 代码节点的语言/库/超时/出网（关闭 Q3）
- **C** HTTP 请求节点出网（关闭 Q4，与 S5 重叠）

---

## S4 · 飞书 Webhook

**目标**：群里收到卡片。

1. [人] 建一个测试群 → 群设置 → 群机器人 → 添加**自定义机器人**
2. [人] 安全设置先选**最简单的一种**（「自定义关键词」填 `校园机会`，签名校验后面再加）
3. [人] 复制 Webhook URL 填进 `.env` 的 `FEISHU_OPPORTUNITY_WEBHOOK_URL`
4. [CC] 跑 `python scripts/probe_feishu_webhook.py --text` 和 `--card`

**验收**：群里先后收到一条文本和一张卡片。

> ⚠️ 建议**另建一个告警群**，Webhook 填 `FEISHU_ALERT_WEBHOOK_URL`。机会推送和运维告警混在一个群会很乱（阶段 2 要用来做存活告警）。

---

## 进度追踪

| # | 探针 | 负责 | 状态 |
| --- | --- | --- | --- |
| 0 | 放入两份 .docx | [人] | ✅ 2026-10-05 |
| 0 | 确认 Docker | [人] | ✅ 2026-10-05（免 sudo） |
| S1 | GeniOS API | [人]1.1–1.3 → [CC]1.4 | ✅ 2026-10-07 |
| S2-a | 大模型节点 JSON 输出 | [人] 搭 → [CC] 判 | ✅ 2026-10-07 |
| S2-b | 代码节点能力 | [人] 搭 → [CC] 判 | ✅ 2026-10-07 |
| S2-c / Q4 | HTTP 节点出网 | 随 S5 一起 | ✅ 2026-10-05 |
| S3 | We-MP-RSS 载荷 | [CC] 源码 + 真实载荷双重确认 | ✅ 2026-10-05 |
| S4 | 飞书 Webhook | — | ⬜ **不再需要**（改用 S6 自建应用） |
| S5 | 网络连通 | [CC]5.1 → [人]5.4 | ✅ 2026-10-05 |
| S6 | 飞书长连接 + 推送 | [人] 建应用 → [CC] | ✅ 2026-10-06 |

**本清单已全部走完。** 剩下的工作不在「探针」范畴，见 `docs/findings.md` 的「待决 / 待办」和 `HANDOVER.md` 的「下一步」。
