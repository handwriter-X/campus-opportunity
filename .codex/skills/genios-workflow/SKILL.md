---
name: genios-workflow
description: Create, update, inspect, and manually import this project's NK-GeniOS workflow from its repository prompt and code-node sources.
---

# NK-GeniOS 工作流技能

用于本项目的校园机会信息抽取工作流。它覆盖工作流 JSON 生成、结构检查和人工导入准备，
不负责替用户登录、点击页面、发布工作流或写入远程平台。

## 什么时候使用

- 修改 `genios/prompts/step1_extract.md` 后需要重建工作流文件。
- 修改 `genios/code_nodes/parse_and_validate.py` 后需要把代码同步进 Code 节点。
- 需要检查 Start → Intent → 分支 → End 的节点和依赖是否完整。
- 需要准备 NK-GeniOS 的手动导入文件或排查导入格式问题。
- 需要在字段抽取前增加“机会文章/非机会文章”的意图门控。

## 单一事实来源

不要直接编辑生成的 JSON。工作流内容来自：

- `genios/prompts/step1_extract.md`：LLM 系统提示词和抽取规则。
- `genios/code_nodes/parse_and_validate.py`：代码节点的 `handler(inputs)` 和输出字段。
- `genios/prompts/intent_gate.md`：意图识别节点的分类边界与两个意图描述。
- `genios/code_nodes/empty_result.py`：非机会分支的统一空结果。
- `docs/genios_workflow_spec.md`：节点输入、输出和连线契约。
- `docs/genios_workflow_import.md`：NK-GeniOS 文档证据与人工导入步骤。

## 标准操作

从仓库根目录执行：

```powershell
python scripts/create_genios_workflow.py --check
python scripts/create_genios_workflow.py --force
```

需要逐步执行浏览器里的人工导入时，运行：

```bash
bash scripts/wizard_genios_import.sh
```

`--check` 只读取源文件并检查生成图结构；`--force` 才会覆盖已有生成文件。默认生成：

- `genios/workflows/campus_opportunity_extract_gated.import.json`：当前租户可导入的门控工作流文件。
- `genios/workflows/campus_opportunity_extract_gated.graph.json`：同一份原生结构的检查副本。

生成器默认沿用已验证导出 YAML 中的模型；租户模型不同或模型已下线时显式传入：

```powershell
python scripts/create_genios_workflow.py `
  --model-name "当前模型显示名" `
  --model-type "当前模型 ID" `
  --force
```

## 当前工作流契约

### v3 当前接线

```text
Start → 意图识别
          ├─ 机会文章 → 抽取 LLM → parse_and_validate.py ─┐
          └─ 非机会文章 → empty_result.py ────────────────┤
                                                           ↓
                                                  两路结果对象 → End
```

用户已选择使用意图识别先分流。机会定义为四类学生可参与机会；非机会分支返回
`is_opportunity=false`、`items=[]`。Intent 的 `QueryVariable`、输出字段和 `class01`/`class_other` 端口已经按
用户提供的真实租户 YAML 接入生成器。当前租户拒绝 `VariableAggregator` 节点类型，因此两个 Code 节点输出对象字段
`result`，由 End 直接接收 `opportunity_result` 与 `non_opportunity_result`。

### 当前生成结构

生成的画布应包含七个节点：

```text
Start ──→ Intent ──→ (class01) LLM ──→ Code ──┐
                    ╲ (class_other) Code ────┤
                                               ↓
                                      两路 result 对象 → End
```

- Start 提供 `article_id`、`mode`、`source`、`title`、`url`、`publish_time`、
  `publish_weekday`、`text`、`links`。
- Intent 查询变量引用 `Start.text`；机会端口为 `class01`，兜底端口为 `class_other`。
- 机会分支的 LLM 输出使用 `raw_output`；输出格式设为 JSON，温度设为 0.05。
- 机会 Code 必须同时引用 Start 原始字段和 LLM `raw_output`；非机会 Code 只引用
  `Start.article_id`，入口都是 `handler(inputs)`。
- 两个 Code 都输出 `result` 对象；End 直接接收两路对象，worker 递归查找实际执行分支中的
  `is_opportunity/items`。

## 导入边界

用户已从当前 NK-GeniOS 租户导出真实 YAML，并成功上传生成的 JSON。当前生成器的字段、节点
类型、依赖、`Icon` 对象和 `UpdatedAt` 时间格式均以该租户的导出与成功上传结果为依据。

- 使用 `*.import.json`，工作流名称使用“校园机会信息抽取”。
- 顶层 `Icon` 使用 `{"uri":"plugin_icon/workflow.png"}` 对象，以兼容当前租户把
  `Workflow.Icon` 解码为 `up.ObjInfo` 的接口；Intent 节点和分支依赖按真实导出结构使用，
  End 采用两路对象变量直连，不使用被租户拒绝的 `VariableAggregator`。
- 导入后确认模型在当前租户可用，并检查输出格式和温度。
- 如果后续版本再次提示结构错误，再让用户从同一租户导出一个最小 Start → End 工作流，更新字段证据。
- 不要把画布剪贴板包装层或其他平台的 ZIP/YAML 导出格式直接改名为 NK-GeniOS JSON。

## 结果报告

说明生成了哪个文件、是否通过 `--check`、是否执行了 `codegraph sync`。当前租户的 JSON
上传已由用户验证成功；后续仍需在页面完成节点核对、试运行和发布。
