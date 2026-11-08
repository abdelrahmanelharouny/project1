"""Application configuration.

Values are read from environment variables with sandbox-safe defaults.
Production deployments must provide real values via their secret manager
(see docs/implementation/DECISIONS_AND_ASSUMPTIONS.md, ADR-0002).
"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="FIELDSHIFT_", env_file=".env", extra="ignore")

    # Service identity
    service_name: str = "fieldshift-api"
    api_version: str = "v1"
    environment: str = "development"  # development | test | production

    # Database (PostgreSQL + PostGIS). Conda-forge user-space cluster in the sandbox.
    database_url: str = "postgresql+psycopg2://postgres@127.0.0.1:5433/fieldshift"
    db_pgdata_dir: str = "/home/z/my-project/db/pgdata"
    db_port: int = 5433
    db_socket_dir: str = "/tmp"

    # Security
    # Token lifetime in seconds (default 12h).
    auth_token_ttl_seconds: int = 60 * 60 * 12
    # PBKDF2 work factor for password hashing. The iteration count is EMBEDDED
    # in every stored hash string (pbkdf2_sha256$<iters>$<salt>$<digest>), so
    # raising this default keeps old hashes verifiable while new hashes are
    # created at the stronger work factor.
    password_pbkdf2_iterations: int = 600_000
    # Refresh token lifetime (30 days). Refresh tokens rotate on every use;
    # reuse of a rotated token revokes the whole token family.
    auth_refresh_ttl_seconds: int = 60 * 60 * 24 * 30
    # Account lockout: number of consecutive failed logins before the account
    # is locked, and the lockout window in seconds (15 minutes default).
    auth_max_failed_logins: int = 5
    auth_lockout_seconds: int = 900
    # Sliding-window rate limit for auth endpoints (per client IP per minute).
    # 0 disables the limiter entirely (tests; dedicated sandboxes).
    auth_rate_limit_per_minute: int = 10
    # Single-use credential challenge TTLs: password reset (1h) and email
    # verification (24h). Plaintext tokens are delivered out-of-band only.
    password_reset_ttl_seconds: int = 3600
    email_verification_ttl_seconds: int = 86400

    # Async jobs (P0-3): number of in-process worker threads executing
    # background tasks (provider ingestion today). 0 disables the executor
    # and keeps the legacy inline-in-request execution (used by tests).
    job_workers: int = 2

    # Dev conveniences. Secure-by-default: false unless explicitly enabled.
    # The sandbox runs with FIELDSHIFT_DEV_MODE=true via .env (gitignored);
    # docker-compose and production set false. MUST be false in production
    # (seed endpoint disabled, registration auto-verifies emails when true).
    dev_mode: bool = False

    # Pagination guards
    default_page_size: int = 50
    max_page_size: int = 500

    # CORS: the frontend is served behind the same gateway in the sandbox; in
    # production this must be restricted to approved origins only.
    cors_allow_origins: str = ""

    # External providers (Milestone 3). Base URL overridable for testing/proxying.
    open_meteo_base_url: str = "https://archive-api.open-meteo.com/v1/archive"
    open_meteo_timeout_seconds: float = 25.0
    open_meteo_max_years_per_request: int = 10
    soilgrids_wcs_base_url: str = "https://maps.isric.org/mapserv"
    soilgrids_timeout_seconds: float = 45.0
    provider_probe_timeout_seconds: float = 6.0
    provider_probe_cache_seconds: int = 120
    max_import_file_bytes: int = 32_000_000  # 32 MB upload guard for CSV/GeoTIFF imports


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
