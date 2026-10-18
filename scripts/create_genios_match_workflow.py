"""Generate the NK-GeniOS **模块二 · 组队匹配** workflow import artifact.

Five nodes, one more than the 模块一 extraction workflow:

    Start ──▶ Code01(硬筛+拼文本) ──▶ LLM01(精排+理由) ──▶ Code02(校验+映射) ──▶ End
      └────────────────────────────────────────────────────────────────────┘

The data rides **in through Start and out through End** — the workflow does not
touch the multi-dimensional table itself. That keeps it runnable both ways:

* today, with whoever supplies the candidates (gateway, or a manual试运行)
* later, once the 飞书多维表格 OAuth2 plugin is verified, by adding plugin
  nodes at the two ends; the three middle nodes do not change.

Node shapes mirror ``create_genios_workflow.py`` (which produced an
upload-verified artifact); the shared constants and helpers are imported from
it rather than duplicated, so the native export shape stays in one place.

Sources of truth (edit these, then re-run with ``--force``):

* ``genios/prompts/step2_match.md``            → LLM 节点的系统提示词
* ``genios/code_nodes/match_hard_filter.py``   → Code01
* ``genios/code_nodes/match_validate.py``      → Code02
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Iterable

from create_genios_workflow import (  # shared native-export shape
    DEFAULT_MODEL_DESC,
    DEFAULT_MODEL_ID,
    DEFAULT_MODEL_NAME,
    MODEL_FEATURES,
    TYPE_CODES,
    WORKFLOW_ICON,
    WORKFLOW_UPDATED_AT,
    _depends,
    _error_config,
    _extract_fenced_section,
    _node_ref,
    _resolve_path,
    _schema_field,
    _write_json,
)

WORKFLOW_ID = "db5igk54shhas0als37h"
START_ID = "db5igk54shhas0als382"
FILTER_ID = "db5j46d4shhas0alssai"
LLM_ID = "db5iont4shhbpg90ho1h"
VALIDATE_ID = "db5j46d4shhas0alssaj"
BUILD_ID = "db5j46d4shhas0alssak"
END_ID = "db5igk54shhas0als383"

# Everything crosses the Start/End boundary as a **string** on purpose.
# 模块一 的 Start 曾因为把数组字段声明成对象而在启动时就失败
# （docs/findings.md），字符串没有这个风险。
START_FIELDS = [
    ("match_id", "string", True),
    ("request_json", "string", True),
    ("candidates_json", "string", False),
    ("request_record_id", "string", False),
    ("top_n", "string", False),
    ("min_score", "string", False),
]

START_DESCRIPTIONS = {
    "match_id": "本次匹配的幂等键（一般用需求的记录 ID）",
    "request_json": "组队需求 + 发起人画像的 JSON 字符串",
    "candidates_json": "候选队友画像数组的 JSON 字符串；接了多维表格插件后留空即可",
    "request_record_id": "【组队需求】里那一行的 record_id —— 匹配结果要写回它",
    "top_n": "最多推荐几人，默认 3",
    "min_score": "低于此分不推荐，默认 70",
}

BUILD_OUTPUTS = [
    ("ok", "boolean"),
    ("code_version", "integer"),
    ("match_id", "string"),
    ("will_update", "boolean"),
    ("record_id", "string"),
    ("fields_json", "string"),
    ("recommended_count", "integer"),
    ("matches", "list_object"),
    ("match_count", "integer"),
    ("issues", "list"),
]

FILTER_OUTPUTS = [
    ("ok", "boolean"),
    ("code_version", "integer"),
    ("match_id", "string"),
    ("request_text", "string"),
    ("candidate_text", "string"),
    ("candidate_ids", "list"),
    ("candidate_count", "integer"),
    ("input_count", "integer"),
    ("dropped", "object"),
    ("top_n", "integer"),
    ("min_score", "integer"),
    ("issues", "list"),
]

VALIDATE_OUTPUTS = [
    ("ok", "boolean"),
    ("code_version", "integer"),
    ("match_id", "string"),
    ("matches", "list_object"),
    ("match_count", "integer"),
    ("candidate_count", "integer"),
    ("min_score", "number"),
    ("top_n", "integer"),
    ("issues", "list"),
]

# End 的输出 = 校验结果 + **代码01 的诊断信息**。
#
# 加诊断是有原因的：2026-10-14 第一次跑通链路时只拿到
# `candidate_ids 为空`，但**看不到 代码01 到底收到了什么**，只能猜是"读表没接上"
# 还是"平台跑的是旧版代码节点"。把 代码01 的输入规模、淘汰明细、节点版本号
# 一并吐到 End，**一次运行就能定位断在哪一段**，不用来回猜。
# (输出名, 类型, 来源节点, 来源路径)
END_OUTPUTS = [
    ("ok", "boolean", BUILD_ID, "ok"),
    ("match_id", "string", BUILD_ID, "match_id"),
    ("matches", "list_object", BUILD_ID, "matches"),
    ("match_count", "integer", BUILD_ID, "match_count"),
    ("issues", "list", BUILD_ID, "issues"),
    # —— 写回诊断 ——
    ("will_update", "boolean", BUILD_ID, "will_update"),
    ("record_id", "string", BUILD_ID, "record_id"),
    ("recommended_count", "integer", BUILD_ID, "recommended_count"),
    # —— 硬筛诊断：用来一眼看出断在哪一段 ——
    ("candidate_ids", "list", FILTER_ID, "candidate_ids"),
    ("candidate_count", "integer", FILTER_ID, "candidate_count"),
    ("input_count", "integer", FILTER_ID, "input_count"),
    ("dropped", "object", FILTER_ID, "dropped"),
    ("candidate_text", "string", FILTER_ID, "candidate_text"),
    ("filter_version", "integer", FILTER_ID, "code_version"),
    ("validate_version", "integer", VALIDATE_ID, "code_version"),
    ("build_version", "integer", BUILD_ID, "code_version"),
]

# ⚠️ `matches` 是 list_object：**必须声明 SubParameters**，否则平台会把它序列化成
# `[{}]` —— 模块一 已经踩过这个坑（见 create_genios_workflow.py 里同名的注释）。
def _match_item_fields() -> list[tuple[str, str]]:
    return [
        ("open_id", "string"),
        ("idx", "integer"),
        ("score", "number"),
        # 两个理由，**视角不同**：reason 对发起人说话，invite_reason 对被邀请人说话。
        # 只给一个的话，被邀请人会看到「你缺的正是设计」这种对他毫无意义的话。
        ("reason", "string"),
        ("invite_reason", "string"),
    ]


def _start_node() -> dict:
    schema = [
        _schema_field(name, value_type, required=required, description=START_DESCRIPTIONS[name])
        for name, value_type, required in START_FIELDS
    ]
    return {
        "Code": START_ID,
        "Configs": {"Start": {"InputSchema": schema, "OutputSchema": schema}},
        "ErrorConfig": _error_config(),
        "ID": START_ID,
        "Layout": {"X": 493.0, "Y": 246.0},
        "Name": "Start",
        "Type": "Start",
    }


def _filter_node(code: str) -> dict:
    return {
        "Code": FILTER_ID,
        "Configs": {
            "Code": {
                "Code": code,
                "InputVariables": [
                    _node_ref(name, START_ID, name)
                    for name, _value_type, _required in START_FIELDS
                ],
                "Language": 1,
                "OutputSchema": [
                    _schema_field(name, value_type) for name, value_type in FILTER_OUTPUTS
                ],
                "Retries": 0,
                "TimeoutSeconds": 120,
            }
        },
        "Depends": _depends(START_ID),
        "ErrorConfig": _error_config(),
        "ID": FILTER_ID,
        "Layout": {"X": 770.0, "Y": 120.0},
        "Name": "代码01",
        "Type": "Code",
    }


def _llm_node(system_prompt: str, model_name: str, model_type: str) -> dict:
    model_id = model_type.strip() or DEFAULT_MODEL_ID
    selected_model_name = model_name.strip() or DEFAULT_MODEL_NAME
    user_prompt = (
        "【组队需求】\n{{request_text}}\n\n"
        "【候选队友】共 {{candidate_count}} 人\n{{candidate_text}}\n\n"
        "请从上面这些候选人里挑出最适合和发起人组队的，按契合度从高到低给出编号、分数和理由。"
    )
    return {
        "Code": LLM_ID,
        "Configs": {
            "LLM": {
                "CurrentTimeEnabled": False,
                "EnableChatHistories": False,
                "InputVariables": [
                    _node_ref("request_text", FILTER_ID, "request_text"),
                    _node_ref("candidate_count", FILTER_ID, "candidate_count"),
                    _node_ref("candidate_text", FILTER_ID, "candidate_text"),
                ],
                "MaxTokens": 2048,
                "ModelFeatureList": list(MODEL_FEATURES),
                "ModelID": model_id,
                "ModelInteractiveMode": "direct",
                "ModelName": selected_model_name,
                "OutputFormat": "json",
                "OutputSchema": [
                    _schema_field("raw_output", "string"),
                    _schema_field("reasoning_content", "string"),
                ],
                "Prompt": user_prompt,
                "PromptConfig": None,
                "ReasoningEffortType": "medium",
                "ReasoningMode": True,
                "ReasoningSwitch": None,
                "ReasoningSwitchType": "enabled",
                "Retries": 0,
                "SystemPrompt": system_prompt,
                "SystemPromptConfig": None,
                "Temperature": 0.05,
                "TimeoutSeconds": 120,
                "TopP": 0.9,
            }
        },
        "Depends": _depends(FILTER_ID),
        "ErrorConfig": _error_config(),
        "ID": LLM_ID,
        "Layout": {"X": 1090.0, "Y": 120.0},
        "Name": "大模型01",
        "Type": "LLM",
    }


def _validate_node(code: str) -> dict:
    output_schema = []
    for name, value_type in VALIDATE_OUTPUTS:
        if value_type == "list_object":
            output_schema.append(
                {
                    "Name": name,
                    "SubParameters": [
                        _schema_field(item_name, item_type)
                        for item_name, item_type in _match_item_fields()
                    ],
                    "Type": TYPE_CODES["list_object"],
                }
            )
        else:
            output_schema.append(_schema_field(name, value_type))
    return {
        "Code": VALIDATE_ID,
        "Configs": {
            "Code": {
                "Code": code,
                "InputVariables": [
                    _node_ref("candidate_ids", FILTER_ID, "candidate_ids"),
                    _node_ref("candidate_count", FILTER_ID, "candidate_count"),
                    _node_ref("match_id", FILTER_ID, "match_id"),
                    _node_ref("top_n", FILTER_ID, "top_n"),
                    _node_ref("min_score", FILTER_ID, "min_score"),
                    _node_ref("raw_output", LLM_ID, "raw_output"),
                ],
                "Language": 1,
                "OutputSchema": output_schema,
                "Retries": 0,
                "TimeoutSeconds": 120,
            }
        },
        "Depends": _depends(LLM_ID, FILTER_ID),
        "ErrorConfig": _error_config(),
        "ID": VALIDATE_ID,
        "Layout": {"X": 1420.0, "Y": 120.0},
        "Name": "代码02",
        "Type": "Code",
    }


def _build_node(code: str) -> dict:
    output_schema = []
    for name, value_type in BUILD_OUTPUTS:
        if value_type == "list_object":
            output_schema.append({
                "Name": name,
                "SubParameters": [
                    _schema_field(item_name, item_type)
                    for item_name, item_type in _match_item_fields()
                ],
                "Type": TYPE_CODES["list_object"],
            })
        else:
            output_schema.append(_schema_field(name, value_type))
    return {
        "Code": BUILD_ID,
        "Configs": {
            "Code": {
                "Code": code,
                "InputVariables": [
                    _node_ref("matches", VALIDATE_ID, "matches"),
                    _node_ref("match_id", VALIDATE_ID, "match_id"),
                    _node_ref("request_record_id", START_ID, "request_record_id"),
                ],
                "Language": 1,
                "OutputSchema": output_schema,
                "Retries": 0,
                "TimeoutSeconds": 120,
            }
        },
        # 依赖 Start 是为了拿 request_record_id（决定写回哪一行）
        "Depends": _depends(VALIDATE_ID, START_ID),
        "ErrorConfig": _error_config(),
        "ID": BUILD_ID,
        "Layout": {"X": 1740.0, "Y": 120.0},
        "Name": "代码03",
        "Type": "Code",
    }


def _end_node() -> dict:
    input_variables = []
    for name, value_type, node_id, path in END_OUTPUTS:
        if value_type == "list_object":
            input_variables.append(
                {
                    "Name": name,
                    "SubParameters": [
                        _schema_field(item_name, item_type)
                        for item_name, item_type in _match_item_fields()
                    ],
                    "Type": TYPE_CODES["list_object"],
                    "NodeCode": node_id,
                    "Path": path,
                    "RefType": "node_field",
                }
            )
        else:
            input_variables.append(_node_ref(name, node_id, path))
    return {
        "Code": END_ID,
        "Configs": {
            "End": {"InputVariables": input_variables, "OutputType": "Variable"}
        },
        # End 依赖 代码01 也要连上，否则诊断字段取不到
        "Depends": _depends(START_ID, FILTER_ID, VALIDATE_ID, BUILD_ID),
        "ErrorConfig": _error_config(),
        "ID": END_ID,
        "Layout": {"X": 1740.0, "Y": 340.0},
        "Name": "End",
        "Type": "End",
    }


def _canonical_workflow(
    workflow_name: str,
    workflow_id: str,
    system_prompt: str,
    filter_code: str,
    validate_code: str,
    build_code: str,
    model_name: str,
    model_type: str,
) -> dict:
    model_id = model_type.strip() or DEFAULT_MODEL_ID
    model_display_name = model_name.strip() or DEFAULT_MODEL_NAME
    return {
        "DLVersion": "v2",
        "Depends": {
            "AppMap": {},
            "DataSourceMap": {},
            "DatabaseMap": {},
            "KnowledgeMap": {},
            "ModelMap": {
                model_id: {
                    "Desc": DEFAULT_MODEL_DESC,
                    "ID": model_id,
                    "LogoPath": "",
                    "Name": model_display_name,
                }
            },
            "PluginMap": {},
            "QADataSetMap": {},
            "TermDatasetMap": {},
            "ToolMap": {},
            "WorkflowMap": {},
        },
        "Desc": "组队匹配：插件读画像 → Code 硬筛 → LLM 精排与理由 → Code 校验与防幻觉映射 → Code 组装写回",
        "DisplayName": workflow_name,
        "FlowType": "Workflow",
        "ID": workflow_id,
        "Icon": dict(WORKFLOW_ICON),
        "LogoPath": "",
        "MetaType": "Workflow",
        "Nodes": [
            _start_node(),
            _end_node(),
            _filter_node(filter_code),
            _llm_node(system_prompt, model_name, model_type),
            _validate_node(validate_code),
            _build_node(build_code),
        ],
        "UniqueName": workflow_id,
        "UpdatedAt": WORKFLOW_UPDATED_AT,
        "VersionCode": "-",
        "VersionName": "-",
    }


def _validate_graph(graph: dict) -> None:
    if graph.get("DLVersion") != "v2":
        raise ValueError("generated workflow must use DLVersion v2")
    if graph.get("FlowType") != "Workflow" or graph.get("MetaType") != "Workflow":
        raise ValueError("generated workflow must use Workflow metadata")
    if not isinstance(graph.get("UpdatedAt"), str) or not graph["UpdatedAt"].endswith("Z"):
        raise ValueError("generated workflow UpdatedAt must be an RFC3339 string")
    icon = graph.get("Icon")
    if not isinstance(icon, dict) or icon.get("uri") != WORKFLOW_ICON["uri"]:
        raise ValueError("generated workflow icon must be an ObjInfo-compatible object")

    nodes = graph.get("Nodes")
    if not isinstance(nodes, list) or len(nodes) != 6:
        raise ValueError("generated graph must contain exactly five nodes")

    expected_depends = {
        START_ID: [],
        FILTER_ID: [START_ID],
        LLM_ID: [FILTER_ID],
        VALIDATE_ID: [LLM_ID, FILTER_ID],
        BUILD_ID: [VALIDATE_ID, START_ID],
        END_ID: [START_ID, FILTER_ID, VALIDATE_ID, BUILD_ID],
    }
    ids = {node.get("ID") for node in nodes}
    if ids != set(expected_depends):
        raise ValueError(f"generated node IDs differ from expected: {ids}")
    for node in nodes:
        actual = [item.get("NodeCode") for item in node.get("Depends", [])]
        if actual != expected_depends[node["ID"]]:
            raise ValueError(f"node {node['ID']} dependencies differ from expected: {actual}")

    types = [node.get("Type") for node in nodes]
    if types.count("Start") != 1 or types.count("End") != 1:
        raise ValueError("generated graph must contain exactly one start node and one end node")
    if sorted(types) != sorted(["Start", "End", "LLM", "Code", "Code", "Code"]):
        raise ValueError(f"unexpected node types: {types}")

    # list_object 没有 SubParameters 会在运行时退化成 [{}]（模块一踩过），这里提前拦住
    for node in nodes:
        configs = node.get("Configs", {})
        for section in configs.values():
            if not isinstance(section, dict):
                continue
            for field in section.get("OutputSchema", []) or []:
                if field.get("Type") == TYPE_CODES["list_object"] and not field.get("SubParameters"):
                    raise ValueError(f"node {node['ID']} 的 list_object 字段缺少 SubParameters")


def build_workflow(args: argparse.Namespace) -> tuple[Path, Path]:
    repo_root = Path(args.repo_root).resolve()
    prompt_path = repo_root / "genios" / "prompts" / "step2_match.md"
    filter_path = repo_root / "genios" / "code_nodes" / "match_hard_filter.py"
    validate_path = repo_root / "genios" / "code_nodes" / "match_validate.py"
    build_path = repo_root / "genios" / "code_nodes" / "build_update_payload.py"
    output_dir = _resolve_path(repo_root, args.output_dir)

    prompt_markdown = prompt_path.read_text(encoding="utf-8")
    system_prompt = _extract_fenced_section(prompt_markdown, "## 系统提示词（整段复制）")
    filter_code = filter_path.read_text(encoding="utf-8")
    validate_code = validate_path.read_text(encoding="utf-8")
    build_code = build_path.read_text(encoding="utf-8")
    if (not system_prompt or not filter_code.strip() or not validate_code.strip()
            or not build_code.strip()):
        raise ValueError("source prompt or code node is empty")

    graph = _canonical_workflow(
        args.workflow_name,
        args.workflow_id,
        system_prompt,
        filter_code,
        validate_code,
        build_code,
        args.model_name,
        args.model_type,
    )
    _validate_graph(graph)

    import_path = output_dir / f"{args.workflow_stem}.import.json"
    graph_path = output_dir / f"{args.workflow_stem}.graph.json"
    if not args.check:
        existing = [path for path in (import_path, graph_path) if path.exists()]
        if existing and not args.force:
            names = ", ".join(str(path) for path in existing)
            raise FileExistsError(f"refusing to overwrite {names}; pass --force")
        _write_json(import_path, graph, args.force)
        _write_json(graph_path, graph, args.force)
    return import_path, graph_path


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Create the 模块二 组队匹配 workflow import JSON from repository sources."
    )
    parser.add_argument("--repo-root", default=str(Path(__file__).resolve().parents[1]))
    parser.add_argument("--output-dir", default="genios/workflows")
    parser.add_argument("--workflow-stem", default="campus_team_match")
    parser.add_argument(
        "--workflow-name",
        default="校园组队匹配",
        help="导入后显示在工作流列表里的名字",
    )
    parser.add_argument(
        "--workflow-id",
        default=WORKFLOW_ID,
        help="export-compatible workflow ID; override when importing as a new workflow",
    )
    parser.add_argument("--model-name", default=DEFAULT_MODEL_NAME)
    parser.add_argument("--model-type", default=DEFAULT_MODEL_ID)
    parser.add_argument("--force", action="store_true", help="overwrite existing generated files")
    parser.add_argument("--check", action="store_true", help="validate sources and graph without writing")
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        import_path, graph_path = build_workflow(args)
    except (OSError, ValueError, FileExistsError) as exc:
        print(f"error: {exc}")
        return 2
    if args.check:
        print("workflow sources and graph shape are valid")
    else:
        print(f"wrote {import_path}")
        print(f"wrote {graph_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
