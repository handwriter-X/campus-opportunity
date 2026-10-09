# 校园机会搭子 · campus-opportunity

面向南开大学学生的校园机会发现智能体。基于**南开大学 GeniOS 平台**（底层是火山引擎 HiAgent）搭建。

**已跑通的最小闭环**：

```
公众号发新文章 → We-MP-RSS 采集 → campus-gateway 搬运 → GeniOS 判断与抽取
              → gateway 取回结果 → 落库 → 推送飞书
```

> 📖 **接手这个项目？先看 [`HANDOVER.md`](HANDOVER.md)** —— 里面有架构图、数据通路、从零跑起来的步骤、以及所有踩过的坑。
> 🤖 **让 AI 接手？看 [`AGENTS.md`](AGENTS.md)** —— 铁律、目录导航、不变量、已知陷阱。
> 📋 **原始需求与施工方案？看 [`PLAN.md`](PLAN.md)**（唯一事实来源）。
> 🔬 **每个技术结论的证据？看 [`docs/findings.md`](docs/findings.md)**（最详细的账本）。

## 当前进度

| 阶段 | 状态 |
| --- | --- |
| 0 · 探针 | ✅ **全部关闭**（S1/S2/S3/S5/Q4/Q6/Q8 + 飞书长连接）。S4 被 S6 替代，不再需要 |
| 1 · campus-gateway | ✅ **完成**：**109 项测试** + 端到端冒烟全过，worker 真调 GeniOS |
| 2 · 采集端稳定性 | ✅ 自动重启、持久化卷、存活告警已就位 |
| 3 · GeniOS 工作流 | 🔄 **简化版闭环已跑通**（Start→大模型→End）。两段式、代码节点、三层校验的材料已备好，待接上 → `docs/genios_workflow_spec.md` |
| 4 · 飞书推送 | 🔄 **自建应用推送已打通**；卡片版式待接 |
| 5 · 评测集 | ⛔ 待阶段 3 稳定后开始（`eval/` 已备样本，`run_eval.py` 未写） |

**下一步**见 `HANDOVER.md` 的「接下来做什么」——当前优先级是：**补三层校验**、**接飞书卡片**、**评测集**。

## 快速开始

```bash
cp .env.example .env                          # 然后填凭据（见 HANDOVER.md「凭据清单」）
python3 -m venv .venv
.venv/bin/pip install -r gateway/requirements.txt
cd gateway && ../.venv/bin/pytest -q && cd ..  # 期望 109 passed
```

起服务：

```bash
PYTHONUTF8=1 .venv/bin/python -m uvicorn app.main:app --app-dir gateway --reload
```

自检（服务起着时另开一个终端，走完整条链路）：

```bash
PYTHONUTF8=1 .venv/bin/python scripts/smoke_test.py --base http://127.0.0.1:8000
```

> ⚠️ 两个环境坑（都踩过，详见 `HANDOVER.md`）：
> 1. shell 里若设了 `ALL_PROXY=socks5://...`，`requirements.txt` 里的 `httpx[socks]` 是必需的，否则服务起不来。
> 2. **`uvicorn --workers` 必须是 1** —— 后台 worker、限流器、告警去重都是单进程假设。

## 仓库结构

```
campus oppor/
├─ HANDOVER.md                     # ⭐ 交接文档（人看）
├─ AGENTS.md                       # ⭐ 给 AI agent 看的说明
├─ PLAN.md                         # 施工方案（唯一事实来源）
├─ README.md                       # 本文件
├─ gateway/                        # campus-gateway（FastAPI）：搬运 + 记账
│  ├─ app/                         # 见 HANDOVER.md「代码导航」
│  ├─ tests/                       # 109 项
│  └─ Dockerfile
├─ genios/                         # 可直接粘贴到 GeniOS 平台的内容
│  ├─ prompts/step1_extract.md     # 大模型节点提示词
│  ├─ code_nodes/parse_and_validate.py   # 代码节点：解析 + 三层校验
│  ├─ schemas/opportunity.schema.json    # 字段字典
│  └─ feishu_cards/                # 飞书卡片 JSON
├─ scripts/                        # 探针 / 冒烟 / 发送脚本
├─ docs/
│  ├─ findings.md                  # 探针实测账本（最详细）
│  ├─ genios_workflow_spec.md      # 阶段 3 逐节点搭建手册
│  ├─ probe_checklist.md           # 探针操作清单（已完成）
│  ├─ genios_s2_experiments.md     # S2 实验内容与判定标准
│  └─ *.docx                       # 产品需求 + 业务字段体系（字段枚举的权威来源）
├─ eval/                           # 评测集（samples 已有，labels 空）
└─ docker-compose.yml              # we-mp-rss + gateway
```

## 铁律

1. **密钥只放 `.env`**，不入代码、日志、仓库。
2. **遇到 ❓ 不许猜**：先做探针，把实测结果写进 `docs/findings.md` 再往下写。
3. **不自行扩大范围**：判断/抽取/校验等**智能逻辑全部留在 GeniOS 内**，gateway 只做搬运、排队、持久化，不做理解与判断。
