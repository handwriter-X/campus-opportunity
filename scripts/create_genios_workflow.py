"""Create NK-GeniOS workflow import artifacts from repository sources.

The upload endpoint accepts the native workflow document emitted by GeniOS.
The checked-in generator therefore follows the real export shape: ``Nodes``
use the native node type names and dependencies are stored as
``Depends``/``NodeCode`` references. The prompt and code-node files remain
the single source of truth for executable content. Intent fields and ports
come from the supplied tenant export. The two branch results are wrapped as
objects and connected directly to the single End node because this tenant
rejects the VariableAggregator node type.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Iterable


WORKFLOW_ID = "db5igk54shhas0als37g"
START_ID = "db5igk54shhas0als380"
END_ID = "db5igk54shhas0als38g"
LLM_ID = "db5iont4shhbpg90ho1g"
CODE_ID = "db5j46d4shhas0alssag"
INTENT_ID = "db7q18d4shhbpg91ndfg"
EMPTY_CODE_ID = "db7q1sd4shhbpg91ndm0"

START_FIELDS = [
    ("article_id", "string", True),
    ("mode", "string", False),
    ("source", "string", False),
    ("title", "string", False),
    ("url", "string", False),
    ("publish_time", "string", False),
    ("publish_weekday", "string", False),
    ("text", "string", True),
    ("links", "list", False),
]

CODE_OUTPUTS = [
    ("ok", "boolean"),
    ("is_opportunity", "boolean"),
    ("article_id", "string"),
    ("items", "list_object"),
    ("issues", "list"),
    ("item_count", "integer"),
]

END_OUTPUTS = [
    ("ok", "boolean"),
    ("is_opportunity", "boolean"),
    ("article_id", "string"),
    ("items", "list_object"),
    ("issues", "list"),
    ("item_count", "integer"),
]

# GeniOS serializes list-object values according to the nested SubParameters
# declaration.  Leaving only the historical ``first_item`` placeholder makes
# a valid runtime item come back as ``{}`` at End, so declare the fields the
# gateway consumes explicitly.
ITEM_OUTPUT_FIELDS = [
    ("name", "string"),
    ("type", "string"),
    ("summary", "string"),
    ("event_time_raw", "string"),
    ("event_start", "string"),
    ("event_end", "string"),
    ("signup_start", "string"),
    ("signup_deadline", "string"),
    ("signup_deadline_raw", "string"),
    ("location", "string"),
    ("audience", "string"),
    ("quota", "string"),
    ("signup_method", "string"),
    ("signup_url", "string"),
    ("gongneng_practice", "string"),
    ("source_url", "string"),
    ("source_account", "string"),
    ("confidence", "number"),
    ("low_confidence", "boolean"),
    ("evidence", "object"),
    ("tags", "list"),
    ("extra", "object"),
    ("article_id", "string"),
    ("publish_time", "string"),
    ("date_conflict", "list"),
]

TYPE_CODES = {
    "string": 0,
    "integer": 1,
    "boolean": 2,
    "number": 3,
    "object": 4,
    "list": 5,
    "list_object": 9,
}

DEFAULT_MODEL_ID = "d9a3s2qldp7us4m2uc6g"
DEFAULT_MODEL_NAME = "deepseek v4.1 flash"
DEFAULT_MODEL_DESC = (
    "DeepSeek-V4.1是深度求索全新推出的旗舰混合推理模型，"
    "支持自适应深度思考与通用对话双模式。"
)
INTENT_MODEL_ID = "db46nhqldp7id25nc970"
INTENT_MODEL_NAME = "doubao-seed-2-1-lite"
INTENT_MODEL_DESC = "意图识别节点使用的租户模型（来自真实导出示例）"
WORKFLOW_UPDATED_AT = "1970-01-01T00:00:00Z"
MODEL_FEATURES = [
    "streaming",
    "tool-call",
    "vision",
    "reasoning",
    "reasoning-effort",
    "reasoning-switch",
]
INTENT_MODEL_FEATURES = [
    "streaming",
    "tool-call",
    "vision",
    "vision-video",
    "audio",
    "reasoning",
    "reasoning-switch",
]

# The current NK-GeniOS importer deserializes Workflow.Icon as up.ObjInfo.
# This object shape was verified by a successful upload in the target tenant.
WORKFLOW_ICON = {"uri": "plugin_icon/workflow.png"}


def _extract_fenced_section(markdown: str, heading: str) -> str:
    try:
        heading_pos = markdown.index(heading)
        fence_start = markdown.index("```", heading_pos) + 3
        if markdown[fence_start : fence_start + 1] == "\n":
            fence_start += 1
        fence_end = markdown.index("```", fence_start)
    except ValueError as exc:
        raise ValueError(f"prompt file is missing fenced section: {heading}") from exc
    return markdown[fence_start:fence_end].strip()


def _user_prompt() -> str:
    return """【发布时间】{{publish_time}}
【星期几】{{publish_weekday}}
【来源公众号】{{source}}
【标题】{{title}}
【原文链接】{{url}}

【正文】
{{text}}"""


def _schema_field(
    name: str,
    value_type: str,
    *,
    required: bool = False,
    description: str = "",
) -> dict:
    """Return a field in the native GeniOS InputSchema/OutputSchema shape."""
    field = {"Name": name, "Type": TYPE_CODES[value_type]}
    if description:
        field["Desc"] = description
    if required:
        field["Required"] = True
    return field


def _node_ref(name: str, node_code: str, path: str) -> dict:
    """Return a native GeniOS node-field reference."""
    return {
        "Name": name,
        "NodeCode": node_code,
        "Path": path,
        "RefType": "node_field",
    }


def _depends(*node_codes: str) -> list[dict]:
    return [{"NodeCode": node_code} for node_code in node_codes]


def _branch_dep(node_code: str, port_id: str) -> dict:
    """Return the native dependency form for an Intent branch port."""
    return {"NodeCode": node_code, "PortID": port_id}


def _error_config() -> dict:
    return {"ErrorConfigType": "None"}


def _canonical_start_node() -> dict:
    descriptions = {
        "article_id": "文章指纹",
        "mode": "live 或 backfill",
        "source": "来源公众号",
        "title": "原文标题",
        "url": "原文链接",
        "publish_time": "发布时间",
        "publish_weekday": "中文星期",
        "text": "清洗后的正文",
        "links": "正文中的链接列表",
    }
    return {
        "Code": START_ID,
        "Configs": {
            "Start": {
                "InputSchema": [
                    _schema_field(
                        name,
                        value_type,
                        required=required,
                        description=descriptions[name],
                    )
                    for name, value_type, required in START_FIELDS
                ],
                "OutputSchema": [
                    _schema_field(
                        name,
                        value_type,
                        required=required,
                        description=descriptions[name],
                    )
                    for name, value_type, required in START_FIELDS
                ],
            }
        },
        "ErrorConfig": _error_config(),
        "ID": START_ID,
        "Layout": {"X": 494.6740614088, "Y": 247.2943046358},
        "Name": "Start",
        "Type": "Start",
    }


def _canonical_llm_node(system_prompt: str, model_name: str, model_type: str) -> dict:
    model_id = model_type.strip() or DEFAULT_MODEL_ID
    selected_model_name = model_name.strip() or DEFAULT_MODEL_NAME
    return {
        "Code": LLM_ID,
        "Configs": {
            "LLM": {
                "CurrentTimeEnabled": True,
                "EnableChatHistories": False,
                "InputVariables": [
                    _node_ref(name, START_ID, name)
                    for name, _value_type, _required in START_FIELDS
                ],
                "MaxTokens": 1024,
                "ModelFeatureList": list(MODEL_FEATURES),
                "ModelID": model_id,
                "ModelInteractiveMode": "direct",
                "ModelName": selected_model_name,
                "OutputFormat": "json",
                "OutputSchema": [
                    _schema_field("raw_output", "string"),
                    _schema_field("reasoning_content", "string"),
                ],
                "Prompt": _user_prompt(),
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
        # The extraction LLM is reachable only from the positive Intent port.
        "Depends": [_branch_dep(INTENT_ID, "class01"), {"NodeCode": START_ID}],
        "ErrorConfig": _error_config(),
        "ID": LLM_ID,
        "Layout": {"X": 767.8683821155, "Y": -20.8930962947},
        "Name": "大模型01",
        "Type": "LLM",
    }


def _code_output_schema() -> list[dict]:
    fields = [
        _schema_field("ok", "boolean"),
        _schema_field("is_opportunity", "boolean"),
        _schema_field("article_id", "string"),
        {
            "Name": "items",
            "SubParameters": [
                _schema_field(name, value_type)
                for name, value_type in ITEM_OUTPUT_FIELDS
            ],
            "Type": TYPE_CODES["list_object"],
        },
        _schema_field("issues", "list"),
        _schema_field("item_count", "integer"),
    ]
    return fields + [
        {
            "Name": "result",
            "SubParameters": [
                _schema_field("ok", "boolean"),
                _schema_field("is_opportunity", "boolean"),
                _schema_field("article_id", "string"),
                {
                    "Name": "items",
                    "SubParameters": [
                        _schema_field(name, value_type)
                        for name, value_type in ITEM_OUTPUT_FIELDS
                    ],
                    "Type": TYPE_CODES["list_object"],
                },
                _schema_field("issues", "list"),
                _schema_field("item_count", "integer"),
            ],
            "Type": TYPE_CODES["object"],
        }
    ]


def _canonical_code_node(code: str) -> dict:
    return {
        "Code": CODE_ID,
        "Configs": {
            "Code": {
                "Code": code,
                "InputVariables": [
                    _node_ref(name, START_ID, name)
                    for name, _value_type, _required in START_FIELDS
                ]
                + [_node_ref("raw_output", LLM_ID, "raw_output")],
                "Language": 1,
                "OutputSchema": _code_output_schema(),
                "Retries": 0,
                "TimeoutSeconds": 120,
            }
        },
        "Depends": [
            _branch_dep(INTENT_ID, "class01"),
            {"NodeCode": LLM_ID},
            {"NodeCode": START_ID},
        ],
        "ErrorConfig": _error_config(),
        "ID": CODE_ID,
        "Layout": {"X": 1130.5280264347, "Y": 123.8514492921},
        "Name": "代码01",
        "Type": "Code",
    }


def _canonical_empty_code_node(code: str) -> dict:
    return {
        "Code": EMPTY_CODE_ID,
        "Configs": {
            "Code": {
                "Code": code,
                "InputVariables": [_node_ref("article_id", START_ID, "article_id")],
                "Language": 1,
                "OutputSchema": _code_output_schema(),
                "Retries": 0,
                "TimeoutSeconds": 120,
            }
        },
        "Depends": [
            _branch_dep(INTENT_ID, "class_other"),
            {"NodeCode": START_ID},
        ],
        "ErrorConfig": _error_config(),
        "ID": EMPTY_CODE_ID,
        "Layout": {"X": 1130.5280264347, "Y": 500.0},
        "Name": "代码02（非机会空结果）",
        "Type": "Code",
    }


def _canonical_intent_node(system_prompt: str, model_name: str, model_type: str) -> dict:
    model_id = model_type.strip() or INTENT_MODEL_ID
    selected_model_name = model_name.strip() or INTENT_MODEL_NAME
    return {
        "Code": INTENT_ID,
        "Configs": {
            "Intent": {
                "EnableChatHistories": False,
                "Intentions": [
                    {
                        "Description": (
                            "学生现在或之后可以报名、申请、招募、预约或参与的竞赛、"
                            "学术与学习交流、志愿活动与社会实践、校园文体活动。"
                        ),
                        "Name": "机会文章",
                        "PortID": "class01",
                    },
                    {
                        "Description": (
                            "纯新闻、表彰喜报、获奖结果、活动回顾总结、已结束活动、"
                            "招生或政策说明，或没有明确学生参与行动的文章。"
                        ),
                        "Name": "Others",
                        "PortID": "class_other",
                    },
                ],
                "MaxTokens": 1024,
                "ModelFeatureList": list(INTENT_MODEL_FEATURES),
                "ModelID": model_id,
                "ModelInteractiveMode": "direct",
                "ModelName": selected_model_name,
                "OutputSchema": [
                    _schema_field("classificationId", "integer", required=True),
                    _schema_field("classificationName", "string", required=True),
                    _schema_field("reason", "string", required=True),
                ],
                "QueryVariable": _node_ref("query", START_ID, "text"),
                "ReasoningMode": False,
                "ReasoningSwitchType": "disabled",
                "Retries": 0,
                "SystemPrompt": system_prompt,
                "Temperature": 0.7,
                "TimeoutSeconds": 360,
                "TopP": 0.9,
            }
        },
        "Depends": _depends(START_ID),
        "ErrorConfig": _error_config(),
        "ID": INTENT_ID,
        "Layout": {"X": 760.0, "Y": 247.2943046358},
        "Name": "意图识别01",
        "Type": "Intent",
    }


def _canonical_end_node() -> dict:
    return {
        "Code": END_ID,
        "Configs": {
            "End": {
                "InputVariables": [
                    _node_ref("opportunity_result", CODE_ID, "result"),
                    _node_ref("non_opportunity_result", EMPTY_CODE_ID, "result"),
                ],
                "OutputType": "Variable",
            }
        },
        "Depends": _depends(CODE_ID, EMPTY_CODE_ID),
        "ErrorConfig": _error_config(),
        "ID": END_ID,
        "Layout": {"X": 1456.5760080065, "Y": 373.5885313047},
        "Name": "End",
        "Type": "End",
    }


def _canonical_workflow(
    workflow_name: str,
    workflow_id: str,
    intent_system_prompt: str,
    system_prompt: str,
    code: str,
    empty_code: str,
    model_name: str,
    model_type: str,
    intent_model_name: str,
    intent_model_type: str,
) -> dict:
    model_id = model_type.strip() or DEFAULT_MODEL_ID
    model_display_name = model_name.strip() or DEFAULT_MODEL_NAME
    intent_model_id = intent_model_type.strip() or INTENT_MODEL_ID
    intent_model_display_name = intent_model_name.strip() or INTENT_MODEL_NAME
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
                },
                intent_model_id: {
                    "Desc": INTENT_MODEL_DESC,
                    "ID": intent_model_id,
                    "LogoPath": "",
                    "Name": intent_model_display_name,
                },
            },
            "PluginMap": {},
            "QADataSetMap": {},
            "TermDatasetMap": {},
            "ToolMap": {},
            "WorkflowMap": {},
        },
        "Desc": "校园机会信息抽取：Intent 门控，LLM 抽取，Code 三层校验，分支结果直连 End",
        "DisplayName": workflow_name,
        "FlowType": "Workflow",
        "ID": workflow_id,
        "Icon": dict(WORKFLOW_ICON),
        "LogoPath": "",
        "MetaType": "Workflow",
        "Nodes": [
            _canonical_start_node(),
            _canonical_end_node(),
            _canonical_intent_node(intent_system_prompt, intent_model_name, intent_model_type),
            _canonical_llm_node(system_prompt, model_name, model_type),
            _canonical_code_node(code),
            _canonical_empty_code_node(empty_code),
        ],
        "UniqueName": workflow_id,
        # The YAML exporter writes this zero value as numeric 0, but the JSON
        # importer decodes Workflow.UpdatedAt with time.Time and requires a
        # quoted RFC3339 value.
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
        raise ValueError("generated graph must contain exactly six nodes")
    ids = {node.get("ID") for node in nodes}
    expected = {START_ID, LLM_ID, CODE_ID, EMPTY_CODE_ID, INTENT_ID, END_ID}
    if ids != expected:
        raise ValueError(f"generated node IDs differ from expected: {ids}")
    types = [node.get("Type") for node in nodes]
    if types.count("Start") != 1 or types.count("End") != 1:
        raise ValueError("generated graph must contain exactly one start node and one end node")
    if set(types) != {"Start", "LLM", "Intent", "Code", "End"}:
        raise ValueError(f"generated graph contains unsupported node types: {types}")
    expected_depends = {
        START_ID: [],
        INTENT_ID: [START_ID],
        LLM_ID: [INTENT_ID, START_ID],
        CODE_ID: [INTENT_ID, LLM_ID, START_ID],
        EMPTY_CODE_ID: [INTENT_ID, START_ID],
        END_ID: [CODE_ID, EMPTY_CODE_ID],
    }
    for node in nodes:
        actual = [item.get("NodeCode") for item in node.get("Depends", [])]
        if actual != expected_depends[node["ID"]]:
            raise ValueError(
                f"node {node['ID']} dependencies differ from expected: {actual}"
            )


def _resolve_path(repo_root: Path, value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else repo_root / path


def _write_json(path: Path, payload: dict, force: bool) -> None:
    if path.exists() and not force:
        raise FileExistsError(f"refusing to overwrite {path}; pass --force")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def build_workflow(args: argparse.Namespace) -> tuple[Path, Path]:
    repo_root = Path(args.repo_root).resolve()
    prompt_path = repo_root / "genios" / "prompts" / "step1_extract.md"
    intent_prompt_path = repo_root / "genios" / "prompts" / "intent_gate.md"
    code_path = repo_root / "genios" / "code_nodes" / "parse_and_validate.py"
    empty_code_path = repo_root / "genios" / "code_nodes" / "empty_result.py"
    output_dir = _resolve_path(repo_root, args.output_dir)
    prompt_markdown = prompt_path.read_text(encoding="utf-8")
    intent_prompt_markdown = intent_prompt_path.read_text(encoding="utf-8")
    system_prompt = _extract_fenced_section(prompt_markdown, "## 系统提示词（整段复制）")
    intent_system_prompt = _extract_fenced_section(
        intent_prompt_markdown, "## 节点指令（粘贴到意图识别节点的说明/提示区域）"
    )
    code = code_path.read_text(encoding="utf-8")
    empty_code = empty_code_path.read_text(encoding="utf-8")
    if not system_prompt or not intent_system_prompt or not code.strip() or not empty_code.strip():
        raise ValueError("source prompt or code node is empty")

    graph = _canonical_workflow(
        args.workflow_stem,
        args.workflow_id,
        intent_system_prompt,
        system_prompt,
        code,
        empty_code,
        args.model_name,
        args.model_type,
        args.intent_model_name,
        args.intent_model_type,
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
        description="Create NK-GeniOS workflow import JSON from repository sources."
    )
    parser.add_argument("--repo-root", default=str(Path(__file__).resolve().parents[1]))
    parser.add_argument("--output-dir", default="genios/workflows")
    parser.add_argument("--workflow-stem", default="campus_opportunity_extract_gated")
    parser.add_argument(
        "--workflow-id",
        default=WORKFLOW_ID,
        help="export-compatible workflow ID; override when importing as a new workflow",
    )
    parser.add_argument("--model-name", default=DEFAULT_MODEL_NAME)
    parser.add_argument("--model-type", default=DEFAULT_MODEL_ID)
    parser.add_argument("--intent-model-name", default=INTENT_MODEL_NAME)
    parser.add_argument("--intent-model-type", default=INTENT_MODEL_ID)
    parser.add_argument("--force", action="store_true", help="overwrite existing generated files")
    parser.add_argument("--check", action="store_true", help="validate sources and graph without writing files")
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
