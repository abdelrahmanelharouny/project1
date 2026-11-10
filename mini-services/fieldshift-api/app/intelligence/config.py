"""Intelligence-layer settings.

Mirrors the central pattern (app/core/config.py: pydantic-settings with the
CROPTWIST_ env prefix and a .env file) without modifying the frozen central
module. The AI variables:

- CROPTWIST_LLM_BRIDGE_URL — base URL of the LLM bridge mini-service
  (default http://127.0.0.1:3035). The bridge exposes POST /chat.
- CROPTWIST_LLM_ENABLED — master switch (default true). When false every
  intelligence function runs rules-only; the bridge is never called.
- CROPTWIST_LLM_TIMEOUT_SECONDS — per-request timeout (default 20s).

Environment variables take precedence over the .env file (pydantic-settings
semantics, same as the central Settings).
"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class AISettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="CROPTWIST_", env_file=".env", extra="ignore")

    llm_bridge_url: str = "http://127.0.0.1:3035"
    llm_enabled: bool = True
    llm_timeout_seconds: float = 20.0
    # Default sampling temperature for advisory narration (low = factual).
    llm_temperature: float = 0.3


@lru_cache
def get_ai_settings() -> AISettings:
    return AISettings()


ai_settings = get_ai_settings()
