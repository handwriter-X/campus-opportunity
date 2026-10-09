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


@lru_cache
def get_settings() -> Settings:
    return Settings()
