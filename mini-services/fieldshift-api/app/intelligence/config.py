"""Intelligence-layer settings.

Mirrors the central pattern (app/core/config.py: pydantic-settings with the
CROPTWIST_ env prefix and a .env file) without modifying the frozen central
module. The AI variables:

- CROPTWIST_LLM_BRIDGE_URL — base URL of the LLM bridge mini-service
  (default http://127.0.0.1:3035). The bridge exposes POST /chat.
- CROPTWIST_LLM_ENABLED — master switch (default true). When false every
  intelligence function runs rules-only; the bridge is never called.
- CROPTWIST_LLM_TIMEOUT_SECONDS — per-request timeout (default 20s).
- CROPTWIST_LLM_TEMPERATURE — default sampling temperature (low = factual).
- CROPTWIST_LLM_BRIDGE_TOKEN — shared secret for bridge service-to-service
  auth (A9). Empty disables the header locally (bridge binds 127.0.0.1 only).
- CROPTWIST_LLM_CONNECT_TIMEOUT_SECONDS — connection timeout budget (A2).
- CROPTWIST_LLM_MAX_RETRIES — retry attempts for TRANSIENT failures
  (connection errors) with exponential backoff (A2). Total latency of a
  failing request stays bounded: retries only apply to instant connect
  failures, never to timeouts.
- CROPTWIST_LLM_MAX_TOKENS — per-request output token budget (A2).
- CROPTWIST_LLM_MAX_CONCURRENT — maximum concurrent bridge requests (A2).
- CROPTWIST_LLM_LATENCY_BUDGET_SECONDS — soft latency budget; a call that
  would exceed it (timeout config) is still attempted once, but the
  circuit breaker records the latency breach.
- Circuit breaker (A2): CROPTWIST_LLM_CB_FAILURE_THRESHOLD (failures before
  opening), CROPTWIST_LLM_CB_RECOVERY_SECONDS (open -> half-open delay),
  CROPTWIST_LLM_CB_HALF_OPEN_ATTEMPTS (probes allowed while half-open).
- Narrative cache (A3): CROPTWIST_NARRATIVE_CACHE_TTL_SECONDS,
  CROPTWIST_NARRATIVE_CACHE_MAX_ENTRIES (0 disables the cache).
- Advisor (A8): CROPTWIST_ADVISOR_HISTORY_TURNS — recent turns replayed in
  the multi-turn advisor prompt.

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

    # --- A9: bridge service-to-service authentication -----------------------
    # Shared secret sent as `X-Bridge-Token`. Never hardcoded; empty disables
    # the header (local development: the bridge binds 127.0.0.1 only).
    llm_bridge_token: str = ""

    # --- A2: budgets --------------------------------------------------------
    llm_connect_timeout_seconds: float = 5.0
    llm_max_retries: int = 1
    llm_max_tokens: int = 1200
    llm_max_concurrent: int = 4
    llm_latency_budget_seconds: float = 20.0

    # --- A2: circuit breaker ------------------------------------------------
    llm_cb_failure_threshold: int = 3
    llm_cb_recovery_seconds: float = 30.0
    llm_cb_half_open_attempts: int = 1

    # --- A3: narrative cache ------------------------------------------------
    narrative_cache_ttl_seconds: float = 24 * 3600.0
    narrative_cache_max_entries: int = 256

    # --- A8: advisor sessions -----------------------------------------------
    advisor_history_turns: int = 6

    # --- A10: locales understood by the intelligence layer ------------------
    supported_locales: tuple[str, ...] = ("en", "ar")


@lru_cache
def get_ai_settings() -> AISettings:
    return AISettings()


ai_settings = get_ai_settings()
