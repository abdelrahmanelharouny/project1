"""Environment-driven intelligence and provider settings.

Provider secrets are optional until deployment supplies them. Field data is
never sent to an external model by default; operators must explicitly review
provider data-handling terms and enable the relevant privacy gates.
"""
from __future__ import annotations

from functools import lru_cache

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class AISettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="CROPTWIST_", env_file=".env", extra="ignore")

    # Legacy internal bridge remains an explicit opt-in compatibility adapter;
    # it is not part of the default provider priority.
    llm_bridge_url: str = "http://127.0.0.1:3035"
    llm_enabled: bool = True
    llm_timeout_seconds: float = Field(default=20.0, gt=0, le=120)
    llm_temperature: float = Field(default=0.3, ge=0, le=2)
    llm_bridge_token: SecretStr = SecretStr("")
    llm_connect_timeout_seconds: float = Field(default=5.0, gt=0, le=30)
    llm_max_retries: int = Field(default=1, ge=0, le=3)
    llm_max_tokens: int = Field(default=1200, ge=1, le=8192)
    llm_max_concurrent: int = Field(default=4, ge=1, le=64)
    llm_latency_budget_seconds: float = Field(default=20.0, gt=0, le=180)
    llm_cb_failure_threshold: int = Field(default=3, ge=1, le=20)
    llm_cb_recovery_seconds: float = Field(default=30.0, gt=0, le=3600)
    llm_cb_half_open_attempts: int = Field(default=1, ge=1, le=10)
    narrative_cache_ttl_seconds: float = Field(default=24 * 3600.0, ge=0, le=30 * 86400)
    narrative_cache_max_entries: int = Field(default=256, ge=0, le=10000)
    advisor_history_turns: int = Field(default=6, ge=0, le=20)
    ai_conversation_retention_days: int = Field(default=365, ge=0, le=3650)
    supported_locales: tuple[str, ...] = ("en", "ar")

    # Exact requested defaults. Keys are SecretStr and are never returned by
    # health/status endpoints or included in logs.
    gemini_api_key: SecretStr = SecretStr("")
    gemini_model: str = "gemini-3.6-flash"
    groq_api_key: SecretStr = SecretStr("")
    groq_model: str = "openai/gpt-oss-120b"
    openrouter_api_key: SecretStr = SecretStr("")
    openrouter_model: str = "nvidia/nemotron-3.5-super-vl:free"
    llm_provider_order: str = "gemini,groq,openrouter"

    ai_provider_timeout_seconds: float = Field(default=25.0, gt=0, le=120)
    ai_provider_connect_timeout_seconds: float = Field(default=5.0, gt=0, le=30)
    ai_provider_max_retries: int = Field(default=1, ge=0, le=3)
    ai_provider_max_concurrent: int = Field(default=4, ge=1, le=64)
    ai_provider_cb_failure_threshold: int = Field(default=3, ge=1, le=20)
    ai_provider_cb_recovery_seconds: float = Field(default=30.0, gt=0, le=3600)
    ai_provider_max_backoff_seconds: float = Field(default=2.0, ge=0, le=10)

    # A deployment owner must review provider privacy/retention terms before
    # allowing farm-sensitive content to leave the CropTwist boundary. The
    # OpenRouter free endpoint has an additional, provider-specific gate.
    ai_allow_field_data_to_providers: bool = False
    openrouter_allow_field_data: bool = False
    ai_knowledge_allow_documents_to_embedding_provider: bool = False
    ai_knowledge_allow_queries_to_embedding_provider: bool = False

    # Retrieval and feedback operational limits. No default corpus is bundled.
    ai_knowledge_max_document_chars: int = Field(default=200_000, ge=1000, le=2_000_000)
    ai_knowledge_chunk_chars: int = Field(default=1200, ge=200, le=4000)
    ai_knowledge_chunk_overlap_chars: int = Field(default=160, ge=0, le=1000)
    ai_knowledge_max_results: int = Field(default=5, ge=1, le=20)
    ai_feedback_retention_days: int = Field(default=365, ge=30, le=3650)
    ai_trace_retention_days: int = Field(default=90, ge=7, le=3650)

    @field_validator("llm_provider_order")
    @classmethod
    def validate_provider_order(cls, value: str) -> str:
        allowed = {"gemini", "groq", "openrouter", "legacy-llm-bridge"}
        names = [part.strip().lower() for part in value.split(",") if part.strip()]
        if not names or len(names) != len(set(names)) or any(name not in allowed for name in names):
            raise ValueError("llm_provider_order must be a unique comma-separated list of registered providers")
        return ",".join(names)

    @field_validator("gemini_model", "groq_model", "openrouter_model")
    @classmethod
    def validate_model_identifier(cls, value: str) -> str:
        value = value.strip()
        if not value or len(value) > 160 or any(ord(char) < 32 for char in value):
            raise ValueError("provider model identifier is invalid")
        return value

    @property
    def provider_order(self) -> tuple[str, ...]:
        return tuple(self.llm_provider_order.split(","))


@lru_cache
def get_ai_settings() -> AISettings:
    return AISettings()


ai_settings = get_ai_settings()
