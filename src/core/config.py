from functools import lru_cache

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="LLM_SHIELD_",
        case_sensitive=False,
        extra="ignore",
    )

    app_name: str = "LLM Shield & Observability Gateway"
    environment: str = "development"
    host: str = "127.0.0.1"
    port: int = 8080
    log_level: str = "INFO"

    api_keys: list[SecretStr] = Field(default_factory=lambda: [SecretStr("dev-proxy-key")])
    openai_api_key: SecretStr | None = None
    anthropic_api_key: SecretStr | None = None
    cohere_api_key: SecretStr | None = None

    primary_model: str = "openai/gpt-4o-mini"
    fallback_models: list[str] = Field(default_factory=lambda: ["openai/gpt-4.1-mini"])
    request_timeout_seconds: int = 60

    database_url: str = "sqlite+aiosqlite:///./llm_shield.db"
    enable_transformer_guard: bool = False
    prompt_injection_model: str = "protectai/deberta-v3-base-prompt-injection-v2"
    injection_threshold: float = 0.80
    enable_presidio: bool = True

    @field_validator("api_keys", mode="before")
    @classmethod
    def split_api_keys(
        cls,
        value: str | list[str] | list[SecretStr],
    ) -> list[str] | list[SecretStr]:
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    @field_validator("fallback_models", mode="before")
    @classmethod
    def split_fallback_models(cls, value: str | list[str]) -> list[str]:
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
