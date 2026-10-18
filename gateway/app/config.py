"""配置。全部来自环境变量 / .env —— 密钥绝不写进代码（铁律 1）。"""

from __future__ import annotations

import datetime as dt
from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from .tz import SHANGHAI


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ---------- 服务 ----------
    gateway_host: str = "0.0.0.0"
    gateway_port: int = 8000
    gateway_public_base_url: str = "http://127.0.0.1:8000"

    # ---------- 鉴权 ----------
    ingest_shared_secret: str = "change-me-ingest-secret"
    internal_shared_secret: str = "change-me-internal-secret"

    # ---------- 存储 ----------
    database_url: str = "sqlite:///./data/campus.db"

    # ---------- 历史过滤 ----------
    enable_push_after: dt.datetime = Field(
        default_factory=lambda: dt.datetime(2026, 10, 4, tzinfo=SHANGHAI)
    )

    # ---------- GeniOS ----------
    genios_api_base_url: str = ""
    genios_api_path: str = ""
    genios_app_id: str = ""
    genios_api_key: str = ""
    genios_auth_mode: str = "bearer"  # bearer | header | body
    genios_api_key_header: str = "Authorization"
    genios_api_key_prefix: str = "Bearer"
    genios_request_template: str = ""
    # 提交时用的用户标识（HiAgent 要求每次调用带 UserID，查询时也要带同一个）
    genios_user_id: str = "campus-gateway"
    # 查询异步结果的请求体模板。实测 HiAgent 的 query_run_app_process 要 **POST + body**，
    # 不是 GET。可用 {task_id} {user_id} 占位（会被替换成带引号转义的 JSON 字面量）。
    genios_query_template: str = '{"RunID": {task_id}, "UserID": {user_id}}'
    genios_task_id_field: str = ""
    genios_status_path: str = ""
    genios_task_id_path: str = ""
    genios_poll_interval_seconds: float = 3.0
    genios_poll_max_seconds: float = 180.0
    genios_timeout_seconds: float = 120.0
    genios_dry_run: bool = True

    # ---------- worker ----------
    worker_enabled: bool = True
    worker_concurrency: int = 2
    worker_max_attempts: int = 4
    worker_backoff_base_seconds: float = 2.0
    worker_poll_interval_seconds: float = 5.0

    # ---------- 飞书 ----------
    feishu_opportunity_webhook_url: str = ""
    feishu_opportunity_webhook_secret: str = ""
    feishu_alert_webhook_url: str = ""
    feishu_alert_webhook_secret: str = ""
    feishu_rate_limit_per_minute: int = 80

    # ---------- 飞书自建应用（推送通道）----------
    # 为什么用自建应用而不是群自定义机器人 Webhook：本服务最终跑在校内网、被飞连挡着，
    # 自建应用这条通道已经验证过（docs/findings.md S6），不必再维护第二套密钥。
    feishu_app_id: str = ""
    feishu_app_secret: str = ""
    # 推送目标：open_id（ou_…，发给某个人）或 chat_id（oc_…，发给某个群）
    feishu_notify_target: str = ""
    # 关掉它就不会推（默认关，避免误发）
    feishu_app_push_enabled: bool = False

    # ---------- 存活监控 ----------
    alert_if_no_ingest_minutes: int = 180

    # ---------- 调试 ----------
    debug_capture_dir: str = "./data/captures"
    # /_debug/echo 与 /ingest/_debug 无需鉴权（探针 S3/S5 要用）。
    # ⚠️ 对外长期暴露前必须置 0。
    debug_endpoints_enabled: bool = True
    # GET /opportunities 是否也要 X-Internal-Secret
    require_auth_for_get: bool = False

    # ---------- 多维表格（功能模块二）----------
    # 决策 D9：**飞书多维表格是业务数据的事实源**，本地不再存业务数据。
    # gateway 用它来轮询【组队需求】、写【邀请】。详见 docs/module2_team_matching.md。
    #
    # ⚠️ 走的是**应用身份**（tenant_access_token），所以自建应用必须：
    #   ① 开通 bitable 相关权限；② 被加为目标多维表格的协作者。
    #   没开通时报 99991672，错误信息里会带申请链接。
    bitable_enabled: bool = False
    bitable_app_token: str = ""
    bitable_request_table_id: str = ""   # 组队需求
    bitable_profile_table_id: str = ""   # 队友画像
    bitable_invite_table_id: str = ""    # 邀请
    bitable_opportunity_table_id: str = ""  # 机会汇总（模块一的产出，决策 D9 后只写这里）

    # ---------- 匹配工作流（模块二的第二个 GeniOS 智能体）----------
    # 模块一那个工作流的配置在 `genios_*` 里。这一个不走 `genios_*`，
    # 而是由 `MatchGeniosProfile` 翻译成同名属性后喂给**同一个** GeniosClient。
    genios_match_enabled: bool = False
    genios_match_api_key: str = ""
    genios_match_api_path: str = "/api/proxy/api/v1/run_app_workflow"
    genios_match_status_path: str = "/api/proxy/api/v1/query_run_app_process"
    genios_match_task_id_field: str = "runId"
    genios_match_user_id: str = "campus-gateway"
    genios_match_request_template: str = (
        '{"InputData": {payload_json}, "UserID": {user_id}, "NoDebug": true}'
    )
    genios_match_query_template: str = '{"RunID": {task_id}, "UserID": {user_id}}'
    genios_match_dry_run: bool = True
    # ---------- 对话智能体（对话型 / 对话流型）----------
    # ⚠️ 和上面的 `genios_*` 是**两族完全不同的 API**：
    #   `genios_*`       → 流程编排型：`run_app_workflow`，单轮、异步
    #   `genios_chat_*`  → 对话型：`create_conversation` + `chat_query`，多轮、SSE 流式
    # 端点全是探出来的，见 `docs/findings.md` Q11。
    genios_chat_enabled: bool = False
    genios_chat_api_key: str = ""
    # ⚠️ **必须是固定的服务身份，不能传学生的 open_id。**
    #
    # 实测（2026-10-17，`docs/findings.md` Q17）：飞书多维表格插件的 OAuth 授权
    # 是**按「运行时的 userID」一对一绑定的** —— 同一个问题，
    #   userID = 授权时那个 id  → 正常读表
    #   userID = 任何一个新 id   → 「使用工具 search_records 需要授权」
    # 传学生 open_id 的后果是**每来一个新同学就要授权一次**，等于跑不通。
    # 所以对话智能体和模块一/二一样，统一跑在 `campus-gateway` 这个服务身份下；
    # 学生是谁走 `【我的画像】`（`chat_flow._with_profile`）和按 open_id 存的会话 id。
    genios_chat_user_id: str = "campus-gateway"

    # ---------- 表单链接（发出去之前会按人预填姓名，见 `forms.py`）----------
    feishu_profile_form_url: str = "https://nankai.feishu.cn/share/base/shrcnrNj3Dh5T7ce4OxZUO3huBf"
    feishu_request_form_url: str = "https://nankai.feishu.cn/share/base/shrcnH1oQRYtBvm1y7WYAj38gne"
    # 表单视图 id —— `scripts/reorder_form_fields.py` 调顺序要用
    bitable_profile_form_id: str = "vew7DJ6XWV"
    bitable_request_form_id: str = "vewKiZYw3f"

    # 轮询【组队需求】的间隔
    match_poll_interval_seconds: float = 30.0
    # 匹配结果按分数取前几名写回（和卡片展示一致）
    match_top_n: int = 3
    # 「插件授权过期」这类失败**不能每轮都推**（否则 90 秒一条，把人烦死）。
    # 同一类告警在这个冷却时间内只推一次；冷却过后再失败会重推（起提醒作用）。
    match_reauth_alert_cooldown_seconds: float = 1800.0
    # 授权失败后**停止派发**多久（避免每轮生成新 state，把推送出去的链接刷失效）
    match_auth_pause_seconds: float = 1800.0

    @field_validator("enable_push_after")
    @classmethod
    def _ensure_tz(cls, value: dt.datetime) -> dt.datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=SHANGHAI)
        return value

    @property
    def genios_configured(self) -> bool:
        return bool(self.genios_api_base_url and self.genios_api_path and self.genios_api_key)

    @property
    def genios_url(self) -> str:
        return self.genios_api_base_url.rstrip("/") + "/" + self.genios_api_path.lstrip("/")


class MatchGeniosProfile:
    """把「匹配工作流」的配置**伪装成 `genios_*`**，喂给同一个 `GeniosClient`。

    为什么这么做：`GeniosClient` 只认 `settings.genios_*` 这套属性名
    （含 `genios_configured` / `genios_url` 两个 property）。
    与其为了第二个工作流去改它、冒风险影响模块一，不如在这里做一层名字映射
    —— **鸭子类型，GeniosClient 一行都不用动。**

    共享的项（base_url / auth_mode / 轮询参数 / 超时）直接透传 `settings`，
    只有"这个工作流是谁、怎么调"那几项换成 `genios_match_*`。
    """

    def __init__(self, settings: Settings) -> None:
        self._s = settings

    # —— 换掉的：这个工作流是谁 ——
    @property
    def genios_api_path(self) -> str:
        return self._s.genios_match_api_path

    @property
    def genios_api_key(self) -> str:
        return self._s.genios_match_api_key

    @property
    def genios_status_path(self) -> str:
        return self._s.genios_match_status_path

    @property
    def genios_task_id_field(self) -> str:
        return self._s.genios_match_task_id_field

    @property
    def genios_user_id(self) -> str:
        return self._s.genios_match_user_id

    @property
    def genios_request_template(self) -> str:
        return self._s.genios_match_request_template

    @property
    def genios_query_template(self) -> str:
        return self._s.genios_match_query_template

    @property
    def genios_dry_run(self) -> bool:
        return self._s.genios_match_dry_run

    # —— 透传的：两者的公共参数 ——
    @property
    def genios_api_base_url(self) -> str:
        return self._s.genios_api_base_url

    @property
    def genios_app_id(self) -> str:
        return self._s.genios_app_id

    @property
    def genios_auth_mode(self) -> str:
        return self._s.genios_auth_mode

    @property
    def genios_api_key_header(self) -> str:
        return self._s.genios_api_key_header

    @property
    def genios_api_key_prefix(self) -> str:
        return self._s.genios_api_key_prefix

    @property
    def genios_task_id_path(self) -> str:
        return self._s.genios_task_id_path

    @property
    def genios_poll_interval_seconds(self) -> float:
        return self._s.genios_poll_interval_seconds

    @property
    def genios_poll_max_seconds(self) -> float:
        return self._s.genios_poll_max_seconds

    @property
    def genios_timeout_seconds(self) -> float:
        return self._s.genios_timeout_seconds

    # —— GeniosClient 依赖的两个派生属性 ——
    @property
    def genios_configured(self) -> bool:
        return bool(
            self.genios_api_base_url and self.genios_api_path and self.genios_api_key
        )

    @property
    def genios_url(self) -> str:
        return self.genios_api_base_url.rstrip("/") + "/" + self.genios_api_path.lstrip("/")


@lru_cache
def get_settings() -> Settings:
    return Settings()
