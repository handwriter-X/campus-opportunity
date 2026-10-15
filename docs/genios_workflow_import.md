# NK-GeniOS 工作流导入文件

## 文件

- `genios/workflows/campus_opportunity_extract_gated_v2.import.json`：当前租户门控工作流的首选导入文件。
- `genios/workflows/campus_opportunity_extract_gated_v2.graph.json`：同一份原生结构的检查副本，不是另一种导入格式。
- `scripts/create_genios_workflow.py`：项目级生成入口，从当前提示词和代码节点重新生成上述两个文件。
- `scripts/build_genios_workflow_import.py`：旧入口，保留为兼容包装；新命令请使用 `create_genios_workflow.py`。
- `scripts/wizard_genios_import.sh`：逐步引导人工登录、上传、核对和试运行。

## 依据与边界

项目旁边保存的 NK-GeniOS 登录后文档明确说明，工作流支持导入/导出，导入时上传
Json 文件并填写工作流名称；文档还明确了大模型默认输出变量 `raw_output`、代码节点的
输入变量/代码/输出变量配置，以及 Python 和 JavaScript 两种语言。

之前的文件使用了画布剪贴板包装层和数字节点类型，导入器因此报“Workflow should have
exactly one start node and one end node”。随后使用公开 DSL 的小写节点类型又报
`node type: start is not support`。用户从当前 NK-GeniOS 租户导出的真实 YAML 证明，导入
结构应使用 `DLVersion`、`Nodes` 等原生字段；节点类型必须是 `Start`、`End`、`LLM`、`Code`，
节点依赖写在 `Depends: [{NodeCode: ...}]` 中。生成器现在按该原生结构输出 JSON，并保留
模型、提示词、代码节点的完整配置。

当前 NK-GeniOS 租户的错误信息表明其 Go 解码器把顶层 `Workflow.Icon` 声明为
`up.ObjInfo`，因此生成文件使用 `{"uri":"plugin_icon/workflow.png"}` 对象，而不是公开
工作流 DSL 示例中的字符串。原生导出结构不在节点上写 `icon` 字段。这个兼容字段来自当前
租户的错误反馈，并已与真实导出 YAML 的节点字段和依赖结构对照；用户已确认该 JSON
成功上传。

真实 YAML 中的 `UpdatedAt: 0` 是 YAML 导出表示；JSON 导入端把该字段解码成 `time.Time`，
所以生成文件将其写成带引号的 RFC3339 值 `1970-01-01T00:00:00Z`。

## 手动导入

也可以从仓库根目录启动文字向导：

```bash
bash scripts/wizard_genios_import.sh
```

向导不会代替登录、点击导入或发布；它只打开登录页并逐步提示你操作。

1. 打开 NK-GeniOS 的工作流管理页面，选择“导入工作流”。
2. 首先选择 `genios/workflows/campus_opportunity_extract_gated_v2.import.json`。
3. 工作流名称填写 `校园机会信息抽取`，导入后打开画布。
4. 在“大模型节点”确认当前租户可用的模型，确认输出格式为 JSON、温度为 0.05。
5. 检查六节点依赖：Start→Intent；`class01`→LLM→机会 Code；`class_other`→空结果 Code；
   两个 Code 的 `result` 对象均连接到唯一 End。机会 Code 必须同时收到 Start 原始字段和 LLM 的 `raw_output`。
6. 如果仍然提示结构错误，不要继续改名或套用剪贴板包装；从同一租户导出一个只有 Start→End
   的工作流，用它校准当前租户的原生字段。

导入器再次拒绝文件时，需要在 NK-GeniOS 中临时导出一个只有 Start→End 的空工作流；该
导出文件才是当前租户的权威 schema。当前 JSON 已按该导出文件生成，并由用户完成上传、
发布和 API 试运行验证。

### 试运行时的两个 Schema 要求

- `Code` 输出中的 `issues` 必须是字符串数组（`Type: 5`），因为
  `parse_and_validate.py` 返回的是 `list[str]`。
- `items` 是列表对象，必须在 `SubParameters` 中声明机会对象字段；只保留旧的
  `first_item` 占位字段会导致工作流虽然成功，但 End 返回 `items: [{}]`。

生成器已包含这两项修正。修改后要重新导入并发布工作流，平台中已存在的旧版本不会自动更新。

## 重新生成

从仓库根目录执行：

```powershell
python scripts/create_genios_workflow.py --check
python scripts/create_genios_workflow.py --force
```

如果当前租户的模型不同，可显式覆盖导出样例中的模型名称和 ID：

```powershell
python scripts/create_genios_workflow.py `
  --model-name "当前模型显示名" `
  --model-type "当前模型 ID" `
  --force
```
