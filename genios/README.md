# genios/ —— 可直接粘贴到 GeniOS 的内容

这个目录里的每一样东西，都是给你**复制粘贴**到 GeniOS 平台里的，不是拿来运行的。

**逐节点的搭建手册在 `docs/genios_workflow_spec.md`** —— 先看那个。

## 现状（2026-10-14 更新）

| 子目录 | 内容 | 状态 |
| --- | --- | --- |
| `schemas/` | 抽取结果的 JSON Schema（`opportunity.schema.json`） | ✅ **已就绪** |
| `prompts/` | `intent_gate.md`（意图门控）与 `step1_extract.md`（机会抽取） | ✅ **已就绪**；Intent schema 已按真实租户 YAML 接入 |
| `code_nodes/` | `empty_result.py`（非机会分支）与 `parse_and_validate.py`（三层校验） | ✅ **已就绪**；两条分支汇合到同一 End |
| `feishu_cards/` | 飞书卡片 JSON | ✅ 已就绪（阶段 4 再接） |

### 阻塞是怎么解开的

| 原来缺什么 | 现在 |
| --- | --- |
| 两份 .docx 没放进 `docs/` | ✅ 已到位，枚举值已按文档原文对齐（Q8） |
| 不知道大模型节点能不能约束 JSON（Q2） | ✅ 实测：节点自带「输出格式」，可选 JSON |
| 不知道代码节点支持什么（Q3） | ✅ 实测：Python 3.10.19，`json`/`re`/`datetime`/`zoneinfo` 全可用 |
| 不知道代码节点的接口契约 | ✅ 实测：**必须定义 `def handler(inputs): … return {…}`**，不能用顶层 `return` |
| 不知道大模型输出的形状 | ✅ 实测：信封是 `{"raw_output": "<字符串>"}`，内部 JSON 要再解析一次 |

## 节点的配合关系

```
prompts/intent_gate.md → 粘进「意图识别节点」
       ├─ 机会文章 → prompts/step1_extract.md → code_nodes/parse_and_validate.py
       │                                      → 清洗后的 items → End → gateway worker
       └─ 非机会文章 → code_nodes/empty_result.py
                                      → items=[] → End → gateway worker

schemas/opportunity.schema.json → 两条提示词与机会校验共用的字段字典
```

## 门控分支的职责

- **意图识别**：只回答文章是否是学生可参与的四类机会；不抽取字段。
- **抽取 LLM**：只在“机会文章”分支执行，继续使用 `step1_extract.md`。
- **`parse_and_validate.py`**：校验机会字段并输出完整 `items`。
- **`empty_result.py`**：在“非机会文章”分支输出 `is_opportunity=false`、`items=[]`，让 worker 正常结束但不入机会库。

当前生成器和 `*.import.json` 已生成 `Start → Intent → 分支 → End` 的六节点结构。
Intent 节点字段、`class01`/`class_other` 分支和 `Start.text` 查询引用来自真实租户 YAML。由于当前租户拒绝
`VariableAggregator` 节点类型，两个 Code 节点都额外输出对象字段 `result`，End 直接接收
`opportunity_result` 与 `non_opportunity_result`；worker 会递归找到实际执行分支中的 `is_opportunity/items`。

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

卡片里的内容现在是**写死的样例值**。在飞书插件或后续推送节点里要把这些位置换成上游变量：

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
