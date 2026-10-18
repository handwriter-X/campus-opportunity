# 模块二 · 组队匹配工作流 —— GeniOS 搭建说明

> **给 [人]**：本文是把「校园组队匹配」工作流搭进 GeniOS 的说明。
> 设计见 `docs/module2_team_matching.md`，决策见 `docs/findings.md` D9。
>
> **本版目标**：**先把智能链路打通**。数据从 Start 进、从 End 出，
> 工作流**不碰多维表格**——这样今天就能跑起来，等飞书多维表格 OAuth2 插件验证通过后，
> 只需在两端各加一个插件节点，中间三个节点原样不动。

---

## 0. 前置

| 项 | 状态 |
| --- | --- |
| GeniOS API 可被调用（提交 + 异步查询） | ✅ `docs/findings.md` Q1 |
| 大模型节点支持 JSON 输出 | ✅ Q2 |
| 代码节点 = Python 3.10，支持 json/re/datetime/zoneinfo | ✅ Q3 |
| 代码节点契约：必须 `def handler(inputs): ... return {...}` | ✅ Q3 |
| 多维表格插件（可选，本版不用） | ❓ 见 `docs/probe_checklist.md` S7 |

---

## 1. 怎么建：**优先用导入文件**，不要手工点

仓库里已经生成了可导入的工作流文件：

```
genios/workflows/campus_team_match.import.json     ← 上传这个
genios/workflows/campus_team_match.graph.json      ← 同一份内容的副本（不用传）
```

**步骤**：

1. 打开 NK-GeniOS 的工作流管理页 → **导入工作流**
2. 选择 `genios/workflows/campus_team_match.import.json`
3. 工作流名称填 **校园组队匹配**
4. 导入后打开画布，**确认大模型节点的模型在当前租户可用**（见第 4 节）
5. 检查依赖连线（第 2 节），然后**发布**

> ⚠️ 导入用的原生结构是**从真实导出文件反推**的（见 `docs/genios_workflow_import.md`）。
> **如果导入被拒**，先在 GeniOS 里导出一个「只有 Start→End」的空工作流，
> 用它校准当前租户的字段；**不要**改成画布剪贴板格式或公开 DSL 的小写节点类型——
> 那两条路都试过，会被拒。

### 改了提示词或代码节点之后怎么更新

三个源文件是**单一事实源**，改完重新生成再导入：

```bash
python scripts/create_genios_match_workflow.py --check    # 先校验
python scripts/create_genios_match_workflow.py --force    # 再生成
```

| 源文件 | 对应节点 |
| --- | --- |
| `genios/prompts/step2_match.md` | 大模型01（系统提示词） |
| `genios/code_nodes/match_hard_filter.py` | 代码01 |
| `genios/code_nodes/match_validate.py` | 代码02 |

> ⚠️ **平台里已存在的旧版本不会自动更新**，改完必须**重新导入并发布**。

---

## 2. 节点清单与连线

```
┌─────────┐
│  Start  │  接收 match_id / request_json / candidates_json / top_n / min_score
└────┬────┘
     ▼
┌──────────────────┐
│ 代码01（硬筛）    │  用枚举字段把候选从几百人压到几十人 + 拼成自然语言
│                  │  代码见 genios/code_nodes/match_hard_filter.py
└────┬─────────────┘
     ▼
┌──────────────────┐
│ 大模型01（精排）  │  挑最互补的人 + 打分 + 生成理由，**只回传编号 idx**
│                  │  提示词见 genios/prompts/step2_match.md
└────┬─────────────┘
     ▼
┌──────────────────┐
│ 代码02（校验）    │  校验 + **把 idx 映射回真实 open_id**（防幻觉）
│   ▲              │  代码见 genios/code_nodes/match_validate.py
│   └── 代码01 也连进来（要 candidate_ids）
└────┬─────────────┘
     ▼
┌─────────┐
│   End   │  返回 ok / match_id / matches[] / match_count / issues
└─────────┘
```

**依赖（`Depends`）**：

| 节点 | 依赖 |
| --- | --- |
| Start | — |
| 代码01 | Start |
| 大模型01 | 代码01 |
| 代码02 | **大模型01 + 代码01**（两个都要） |
| End | Start + 代码02 |

> ⚠️ **代码02 必须连两个上游**。它要 `candidate_ids` 才能把编号映射回 open_id；
> 只连大模型节点，`candidate_ids` 是空的，会直接返回
> 「没拿到候选编号表」——**这个失败是显式的，不会静默写错数据**。

---

## 3. Start 节点的输入契约

**所有参数都是字符串**（刻意选的：模块一 的 Start 曾因为把数组字段声明成对象而在启动时就失败）。

| 变量名 | 类型 | 必须 | 说明 |
| --- | --- | --- | --- |
| `match_id` | 字符串 | ✅ | 本次匹配的幂等键，一般用需求的记录 ID |
| `request_json` | 字符串 | ✅ | **组队需求 + 发起人画像**的 JSON 字符串 |
| `candidates_json` | 字符串 | ✅ | 候选队友画像数组的 JSON 字符串 |
| `top_n` | 字符串 | 否 | 最多推荐几人，默认 `"3"` |
| `min_score` | 字符串 | 否 | 低于此分不推荐，默认 `"70"` |

### `request_json` 的结构

```json
{
  "match_id": "req-001",
  "owner_open_id": "ou_xxx",
  "owner_name": "张三",
  "title": "找队友参加数学建模",
  "project_type": "竞赛",
  "goal": "参加校内选拔，冲击国赛",
  "skills_needed": ["编程", "设计"],
  "campus": "津南",
  "weekly_hours": "10-20h",
  "major_pref": "计算机相关",
  "schedule": "周末",
  "owner_profile": {
    "name": "张三", "grade": "大二", "college": "计算机学院", "campus": "津南",
    "skills": ["编程"], "weekly_hours": "10-20h",
    "experience": "ACM 校赛二等奖，做过校园二手交易小程序"
  }
}
```

> ⚠️ **`owner_profile` 不能省。** 没有「发起人自己会什么」，大模型就只能找
> 「和需求描述像的人」，而不是「补发起人短板的人」——这正是设计里最关键的一条
> （见 `docs/module2_team_matching.md` §5.1）。

### `candidates_json` 的结构

```json
[
  {
    "open_id": "ou_a", "name": "王五", "grade": "大二", "college": "软件学院",
    "campus": "津南", "skills": ["编程", "设计"], "weekly_hours": "10-20h",
    "direction": ["竞赛"],
    "experience": "做过前端外包，会用 Figma",
    "intro": "想做点真东西"
  }
]
```

字段名兼容两种写法：英文键（`campus`/`skills`/`weekly_hours`）和表头中文
（`所在校区`/`技能标签`/`每周可投入`）。**选填字段可以缺**——缺了不会被误杀，
会交给大模型判断。

---

## 4. 大模型节点

| 配置项 | 值 |
| --- | --- |
| 系统提示词 | `genios/prompts/step2_match.md` 的「系统提示词」整段（生成器已内置） |
| 用户提示词 | 生成器已内置，引用 `{{request_text}}` / `{{candidate_count}}` / `{{candidate_text}}` |
| 输出格式 | **JSON** |
| 温度 | **0.05**（最低） |

⚠️ **如果租户里没有 `deepseek v4.1 flash`**，用参数覆盖再重新生成：

```bash
python scripts/create_genios_match_workflow.py --force \
  --model-name "当前模型显示名" --model-type "当前模型 ID"
```

---

## 5. 怎么测

### 5.1 先在本地验两个代码节点

```bash
cd gateway && ../.venv/bin/pytest tests/test_match_workflow.py -q
```

16 个用例覆盖了硬筛的每种淘汰、防幻觉、分数越界、空理由、阈值截断。
**这套测试是本地跑得动的**，改代码节点前先跑它。

### 5.2 在 GeniOS 里试运行

用下面这份 payload 直接试（**已按当前链路构造好，可整段粘贴**）：

```json
{
  "match_id": "req-001",
  "request_json": "{\"match_id\":\"req-001\",\"owner_open_id\":\"ou_owner\",\"owner_name\":\"张三\",\"title\":\"找队友参加数学建模\",\"project_type\":\"竞赛\",\"goal\":\"参加校内选拔，冲击国赛\",\"skills_needed\":[\"编程\",\"设计\"],\"campus\":\"津南\",\"weekly_hours\":\"10-20h\",\"owner_profile\":{\"name\":\"张三\",\"grade\":\"大二\",\"college\":\"计算机学院\",\"campus\":\"津南\",\"skills\":[\"编程\"],\"weekly_hours\":\"10-20h\",\"experience\":\"ACM 校赛二等奖\"}}",
  "candidates_json": "[{\"open_id\":\"ou_a\",\"name\":\"李四\",\"grade\":\"大三\",\"college\":\"文学院\",\"campus\":\"八里台\",\"skills\":[\"设计\",\"文案\"],\"weekly_hours\":\"5-10h\",\"experience\":\"校刊美编，负责过三届毕业季海报设计\"},{\"open_id\":\"ou_b\",\"name\":\"王五\",\"grade\":\"大二\",\"college\":\"软件学院\",\"campus\":\"津南\",\"skills\":[\"编程\",\"设计\"],\"weekly_hours\":\"10-20h\",\"experience\":\"做过前端外包，会用 Figma\"},{\"open_id\":\"ou_c\",\"name\":\"赵六\",\"grade\":\"研一\",\"college\":\"金融学院\",\"campus\":\"泰达\",\"skills\":[\"数据分析\"],\"weekly_hours\":\"<5h\",\"experience\":\"在券商实习过\"},{\"open_id\":\"ou_owner\",\"name\":\"张三\",\"campus\":\"津南\",\"skills\":[\"编程\"],\"weekly_hours\":\"10-20h\",\"experience\":\"ACM 校赛二等奖\"},{\"open_id\":\"ou_d\",\"name\":\"孙七\",\"grade\":\"大二\",\"college\":\"计算机学院\",\"campus\":\"津南\",\"skills\":[\"编程\"],\"weekly_hours\":\">20h\",\"experience\":\"开源社区贡献者，主攻 Rust\"}]",
  "top_n": "3",
  "min_score": "70"
}
```

**期望结果**（**已用本机跑过，下面是实测值**）：

| 检查点 | 期望 |
| --- | --- |
| 代码01 `dropped` | `{"本人":1, "校区不符":2, "投入不足":0, "技能不匹配":0}` |
| 代码01 `input_count → candidate_count` | **5 → 2** |
| 代码01 `candidate_ids` | `["ou_b", "ou_d"]`（王五、孙七）；李四（八里台）、赵六（泰达）、张三本人被淘汰 |
| 代码01 `candidate_text` 首行 | `[0] 大二 · 软件学院 · 技能：编程、设计 · 校区：津南 · 每周可投入：10-20h` |
| End `matches[].open_id` | **真实存在的 open_id**（`ou_b` / `ou_d`），不是大模型编的 |
| End `matches[].reason` | 具体的、引用候选人信息的句子 |
| End `match_count` | ≥ 1 |

### 5.3 反向样例（应该推荐不出人）

把 `skills_needed` 改成 `["实验操作"]`，`campus` 改成 `"泰达"`，`weekly_hours` 改成 `">20h"`，
再跑一次 —— 期望 `matches: []`，`match_count: 0`。
**如果这时它硬凑出一个 60 分的推荐，说明提示词里的分档铁律没生效。**

---

## 6. 已知坑（都是踩过的）

| 坑 | 说明 |
| --- | --- |
| 大模型输出是字符串 | 信封 `{"raw_output": "…"}`，必须解析（代码02 已处理） |
| 代码节点不能顶层 `return` | 必须 `def handler(inputs): … return {…}` |
| 代码节点**不能有 `from __future__ import`** | 前面会被插入约 16 行代码 |
| `list_object` 必须声明 `SubParameters` | 否则 `matches` 会退化成 `[{}]`（模块一踩过） |
| **`{{request_text}}` 选错** | 传成空串 → 结果是「没有合适的队友」，**静默失败** |
| **不要改成让大模型回传 open_id** | 它会编造账号，而且不报错 —— 只能往库里写脏数据 |
| 把 `_ITEM_*` 常量改成覆盖 | 别动去重语义（`store.py::_merge_missing`，见 D4） |

---

## 6.5 接多维表格插件（2026-10-14 新增）

> **插件已授权完成**（Scope `bitable:app`，实测通）。见 `docs/findings.md` S7。
>
> ⚠️ **插件节点进不了导入文件**——它们是平台资源（要绑定已授权的插件），
> 只能在画布上手工加。中间三个节点不用动。

目标形态（**两个插件节点，一前一后**）：

```
                     ┌──────────────────────────────────────────┐
   【读】             │        飞书多维表格（事实源）             │
search_records ─────▶│  队友画像 · 组队需求 · 匹配记录          │
   │                 └──────────────────────────────────────────┘
   │                                   ▲
   ▼                                   │ 【写】create_records
┌───────┐   ┌──────────┐   ┌──────────┐   ┌──────────┐   ┌─────┐
│ Start │──▶│ 代码01    │──▶│ 大模型01  │──▶│ 代码02    │──▶│ End │
│       │   │ (硬筛)    │   │ (精排)    │   │ (校验)    │   └─────┘
└───────┘   └──────────┘   └──────────┘   └────┬─────┘
                                                └──▶ create_records
```

**两端插件节点是"数据进出口"，中间三个节点是"智能"，一行都不用改。**

### A. `search_records` —— 读候选

> ⚠️ **`table_id` 是顶层参数，不在 `search` 里面**（这一条一开始读错了，
> 是平台校验报错把 schema 原文吐出来才纠正的，见 `docs/findings.md` S7）。
> **`search` 本身是必填的**，不用也要传空对象 `{}`，否则报 `'search' is a required property`。

| 参数 | 层级 | 填什么（**用探针表就能立刻测**） |
| --- | --- | --- |
| `app_token` | 顶层 · 必填 | `<BITABLE_APP_TOKEN>` |
| **`table_id`** | **顶层 · 必填** | **`tblbUBezczIB54Th`**（队友画像表） |
| **`search`** | **顶层 · 必填** | **空对象 `{}`** |
| `page_size` | 顶层 | `500` |
| `page_token` | 顶层 | **留空**（首次请求） |
| `search` → `filter` | 嵌套 · 可选 | 留空（见下） |
| `search` → `sort` / `field_names` / `view_id` / `automatic_fields` | 嵌套 · 可选 | 留空 |

**连线**：把这个节点的输出接到 **代码01**。

代码节点**两种上游形状都能吃**（已实测 + 已锁进测试）：
- 插件的结构化输出（记录在 `items` / `records` 里）
- `candidates_json` 那种 JSON 字符串（gateway 供数 / 手工试运行时）

#### 要不要在插件里筛？

`search` **确实支持 `filter`**（实测确认，详见 `docs/findings.md` S7）。语法：

```jsonc
"filter": {
  "conjunction": "and",                       // ⚠️ 必填
  "conditions": [
    { "field_name": "技能标签", "operator": "contains", "value": ["编程"] },
    { "field_name": "所在校区", "operator": "is",       "value": ["津南"] }
  ]
}
```

| 字段类型 | operator | 语义 |
| --- | --- | --- |
| **多选** | `contains` | **包含任一** ← 技能要用这个 |
| 多选 | `is` | **完全相等**（不是包含！用错会静默返回空） |
| 单选 | `is` | 等于 |

**建议：插件里先不筛**（整表读回来），把筛选全交给**代码01**。理由：
- 代码01 的筛选逻辑**有测试锁着**，插件里配的没有
- 同一套逻辑还兼容 gateway 供数，不用维护两份
- 校园规模（几百条）整表读没问题

> ⚠️ **`page_size` 上限 500**，超过要翻页（判 `has_more` + `page_token`）。
> 探针期先不管，但**候选人多了会漏**——正式上线前必须处理。

### B. `create_records` —— 写回匹配结果（**读通了再做**）

| 参数 | 填什么 |
| --- | --- |
| `app_token` | 同上 |
| `table_id` | **匹配记录表**的 ID（还没建） |
| `fields_json` | ❓ **需要你点开看看格式** |

**连线**：`代码02 → create_records → End`。

⚠️ **这一步有个真实的接线难点**：代码02 输出的是 `matches` **数组**，
而 `create_records` 要的是**记录对象**。中间大概率还要加一个代码节点，
把数组转成 `{"records":[{"fields":{…}}]}`。**等你把 `fields_json` 的格式截图给我，
我再定怎么接（可能要再生成一个节点）。**

**所以建议：先把 A 做完并试运行，B 等 A 通了再说。**

---

## 7. 下一步

本版跑通后，按顺序：

1. **加两端插件节点**（读表供候选、写回匹配结果）—— 前置是 S7 里的插件验证
2. 接**飞书推送**（把 `matches` 渲染成卡片发给发起人和候选人）
3. 接**对话入口**（Agent 调这个工作流：「帮我找队友」）

设计见 `docs/module2_team_matching.md` §5.6 / §10。
