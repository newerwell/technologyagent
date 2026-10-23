"""集中配置加载与校验（P00）。

所有运行参数来自环境变量或项目根目录的 .env，不把密钥写入代码或响应。
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Literal, Mapping

from dotenv import load_dotenv
from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MONGODB_URI = (
    "mongodb://127.0.0.1:27027/?replicaSet=ta-rs&directConnection=true"
)
DEFAULT_LOCAL_SESSION_SECRET = "technologyagent-local-dev-only-secret"


def _env(environ: Mapping[str, str], name: str, default: str | None = None) -> str | None:
    value = environ.get(name)
    if value is None or value.strip() == "":
        return default
    return value.strip()


class Settings(BaseModel):
    """P00 运行配置。SecretStr 保证 repr/JSON 输出不会泄露密钥。"""

    model_config = ConfigDict(frozen=True, extra="ignore")

    app_mode: Literal["local", "prod"] = "local"
    app_name: str = "TechnologyAgent"
    frontend_port: int = Field(default=3030, ge=1, le=65535)
    api_port: int = Field(default=8030, ge=1, le=65535)
    mcp_port: int = Field(default=9030, ge=1, le=65535)

    mongodb_uri: SecretStr = SecretStr(DEFAULT_MONGODB_URI)
    mongodb_database: str = "technologyagent_dev"

    model_mode: Literal["fake", "live"] = "fake"
    model_base_url: str = "http://127.0.0.1:11434/v1"
    model_name: str = ""
    model_api_key: SecretStr | None = None

    local_session_secret: SecretStr = SecretStr(DEFAULT_LOCAL_SESSION_SECRET)
    session_ttl_hours: int = Field(default=24, ge=1, le=24 * 30)
    storage_root: Path = Path("storage")

    @field_validator("app_mode", "model_mode", mode="before")
    @classmethod
    def _lower_mode(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip().lower()
        return value

    @field_validator("mongodb_database")
    @classmethod
    def _valid_database(cls, value: str) -> str:
        value = value.strip()
        if not value or any(ch in value for ch in ' /\\."$*<>:|?'):
            raise ValueError("MONGODB_DATABASE contains invalid characters")
        return value

    @property
    def model_configured(self) -> bool:
        return self.model_mode == "live" and bool(
            self.model_api_key and self.model_api_key.get_secret_value() and self.model_name
        )

    @property
    def resolved_storage_root(self) -> Path:
        root = self.storage_root
        return root if root.is_absolute() else (PROJECT_ROOT / root)

    def safe_summary(self) -> dict[str, object]:
        """可安全写入日志/响应的配置摘要，不含任何密钥。"""
        return {
            "app_mode": self.app_mode,
            "frontend_port": self.frontend_port,
            "api_port": self.api_port,
            "mcp_port": self.mcp_port,
            "mongodb_database": self.mongodb_database,
            "model_mode": self.model_mode,
            "model_configured": self.model_configured,
            "session_ttl_hours": self.session_ttl_hours,
        }


def load_settings(environ: Mapping[str, str] | None = None) -> Settings:
    """从 env 映射或进程环境（含 .env）加载配置。"""
    if environ is None:
        load_dotenv(PROJECT_ROOT / ".env", override=False)
        source: Mapping[str, str] = os.environ
    else:
        source = environ

    raw_key = _env(source, "MODEL_API_KEY")
    return Settings(
        app_mode=_env(source, "APP_MODE", "local") or "local",
        app_name=_env(source, "APP_NAME", "TechnologyAgent") or "TechnologyAgent",
        frontend_port=int(_env(source, "FRONTEND_PORT", "3030") or "3030"),
        api_port=int(_env(source, "API_PORT", "8030") or "8030"),
        mcp_port=int(_env(source, "MCP_PORT", "9030") or "9030"),
        mongodb_uri=SecretStr(_env(source, "MONGODB_URI", DEFAULT_MONGODB_URI) or DEFAULT_MONGODB_URI),
        mongodb_database=_env(source, "MONGODB_DATABASE", "technologyagent_dev") or "technologyagent_dev",
        model_mode=_env(source, "MODEL_MODE", "fake") or "fake",
        model_base_url=_env(source, "MODEL_BASE_URL", "http://127.0.0.1:11434/v1")
        or "http://127.0.0.1:11434/v1",
        model_name=_env(source, "MODEL_NAME", "") or "",
        model_api_key=SecretStr(raw_key) if raw_key else None,
        local_session_secret=SecretStr(
            _env(source, "LOCAL_SESSION_SECRET", DEFAULT_LOCAL_SESSION_SECRET)
            or DEFAULT_LOCAL_SESSION_SECRET
        ),
        session_ttl_hours=int(_env(source, "SESSION_TTL_HOURS", "24") or "24"),
        storage_root=Path(_env(source, "STORAGE_ROOT", "storage") or "storage"),
    )
