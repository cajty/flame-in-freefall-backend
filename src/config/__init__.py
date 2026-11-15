from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    """Runtime configuration. Secrets are never logged or returned."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore", populate_by_name=True)

    gemini_api_key: SecretStr | None = Field(default=None, validation_alias="GEMINI_API_KEY")
    gemini_model: str = Field(default="gemini-2.5-flash", validation_alias="GEMINI_MODEL")

    generated_json_path: Path = Field(
        default=REPO_ROOT / "generated.json", validation_alias="FLAME_GENERATED_JSON_PATH"
    )
    data_processed_dir: Path = Field(
        default=REPO_ROOT / "data" / "processed", validation_alias="FLAME_DATA_PROCESSED_DIR"
    )
    reference_dir: Path = Field(
        default=REPO_ROOT / "data" / "reference", validation_alias="FLAME_REFERENCE_DIR"
    )
    psi_catalog_path: Path = Field(
        default=REPO_ROOT / "data" / "reference" / "psi_catalog.json",
        validation_alias="FLAME_PSI_CATALOG_PATH",
    )
    reranker_enabled: bool = Field(
        default=False, validation_alias="FLAME_RERANKER_ENABLED"
    )
    reranker_model_dir: Path = Field(
        default=REPO_ROOT / "models" / "reranker-onnx",
        validation_alias="FLAME_RERANKER_MODEL_DIR",
    )
    reranker_pool_size: int = Field(
        default=30, ge=1, le=200, validation_alias="FLAME_RERANKER_POOL_SIZE"
    )

    cors_origins: str = Field(
        default="http://localhost:5173,http://127.0.0.1:5173",
        validation_alias="FLAME_CORS_ORIGINS",
    )

    max_request_body_bytes: int = Field(default=65_536, validation_alias="FLAME_MAX_BODY_BYTES")
    investigations_limit_max: int = 200
    query_limit_default: int = 500
    query_limit_max: int = 5_000
    compare_max_ids: int = 5
    export_max_rows: int = 10_000
    question_max_chars: int = 2_000
    tool_timeout_seconds: float = 5.0
    analyze_timeout_seconds: float = 60.0
    export_ttl_seconds: int = 900
    conversation_ttl_seconds: int = 1_800
    conversation_max_entries: int = 100
    conversation_max_turns: int = 8
    tool_calls_limit: int = 20
    model_request_limit: int = 20

    auth_enabled: bool = Field(default=False, validation_alias="FLAME_AUTH_ENABLED")
    api_token: SecretStr | None = Field(default=None, validation_alias="FLAME_API_TOKEN")
    rate_limit_enabled: bool = Field(
        default=False, validation_alias="FLAME_RATE_LIMIT_ENABLED"
    )
    analyze_rate_limit_per_minute: int = Field(
        default=10, validation_alias="FLAME_ANALYZE_RATE_LIMIT_PER_MINUTE"
    )

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def model_configured(self) -> bool:
        return self.gemini_api_key is not None and bool(
            self.gemini_api_key.get_secret_value()
        )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
