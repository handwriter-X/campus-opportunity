# genios/ —— 可直接粘贴到 GeniOS 的内容

这个目录里的每一样东西，都是给你**复制粘贴**到 GeniOS 平台里的，不是拿来运行的。

**逐节点的搭建手册在 `docs/genios_workflow_spec.md`** —— 先看那个。

## 现状（2026-10-07 更新）

| 子目录 | 内容 | 状态 |
| --- | --- | --- |
| `schemas/` | 抽取结果的 JSON Schema（`opportunity.schema.json`） | ✅ **已就绪** |
| `prompts/` | 大模型节点提示词（`step1_extract.md`，含 few-shot） | ✅ **已就绪** |
| `code_nodes/` | 解析 + 三层校验（`parse_and_validate.py`） | ✅ **已就绪**，本地已验 |
| `feishu_cards/` | 飞书卡片 JSON | ✅ 已就绪（阶段 4 再接） |

### 阻塞是怎么解开的

| 原来缺什么 | 现在 |
| --- | --- |
| 两份 .docx 没放进 `docs/` | ✅ 已到位，枚举值已按文档原文对齐（Q8） |
| 不知道大模型节点能不能约束 JSON（Q2） | ✅ 实测：节点自带「输出格式」，可选 JSON |
| 不知道代码节点支持什么（Q3） | ✅ 实测：Python 3.10.19，`json`/`re`/`datetime`/`zoneinfo` 全可用 |
| 不知道代码节点的接口契约 | ✅ 实测：**必须定义 `def handler(inputs): … return {…}`**，不能用顶层 `return` |
| 不知道大模型输出的形状 | ✅ 实测：信封是 `{"raw_output": "<字符串>"}`，内部 JSON 要再解析一次 |

## 三个文件的配合关系

```
prompts/step1_extract.md   →  粘进「大模型节点」，输出 JSON 字符串
        ↓
code_nodes/parse_and_validate.py  →  粘进「代码节点」，
        解析那个字符串 + 跑三层校验（格式/逻辑/依据）
        输出键名已对齐 gateway 的 POST /opportunities，HTTP 节点可原样转发
        ↓
schemas/opportunity.schema.json   →  提示词与校验共用的「字段字典」，
        枚举值与字段名都取自 docs/校园机会信息整合_最终业务字段体系.docx
```

## 三层校验做了什么（`code_nodes/parse_and_validate.py`）

1. **格式层**：必填项（`name`/`type`/`confidence`/`evidence`）、四类枚举、`公能实践` 枚举。
2. **逻辑层**：日期可解析、开始 ≤ 结束、报名截止不早于发布时间、年份与发布时间相差 ≤ 1 年、
   链接是合法 URL。
3. **依据层**：关键字段的原文引用必须**真实出现在原文里**（做了空白与全半角归一化的子串匹配）。
   不满足 → **该字段置 `null` 并降低置信度**（方案 §6 规定的做法，不是丢弃整条）。

输出里的 `issues` 数组会写明每个字段为什么被置空，方便排查。

## feishu_cards/ 怎么用

卡片是**阶段 4 的推送版式**，由 `scripts/probe_feishu_webhook.py` 里的构造函数生成，
所以 JSON 一定合法、一定能渲染。**本版（打通链路）先不用它。**

- `instant.json` —— 即时推送卡片（单个机会）
- `weekly.json` —— 周报卡片（本周仍可参与汇总）

预览效果：

```bash
python scripts/probe_feishu_webhook.py --card                    # 看即时卡片
python scripts/probe_feishu_webhook.py --card --variant weekly   # 看周报卡片
```

### 粘贴到 GeniOS 时要改的地方

卡片里的内容现在是**写死的样例值**。在 HTTP 节点或飞书插件里要把这些位置换成上游变量：

| 卡片里的位置 | 换成 |
| --- | --- |
| 名称 / 类型 | 代码节点输出的 `name` / `type` |
| `🕐 活动时间` | `event_time_raw`（原文时间表达，给人看的） |
| `⏰ 报名截止` | `signup_deadline` |
| `action.actions[].url`（立即报名） | `signup_url` |
| `action.actions[].url`（查看原文） | `source_url` |

⚠️ **按钮的 `url` 必须是合法 URL**，否则整张卡片会被飞书拒收（返回业务错误码但 HTTP 200）。
代码节点已经会校验 `signup_url`，为空时**不要渲染那个按钮**。

⚠️ 卡片末尾「信息由 AI 从公众号原文抽取，请以原文为准」是**刻意保留**的 ——
方案的风险备忘和字段体系文档都要求不能让人误以为这是官方发布。
