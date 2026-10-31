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
    # Token lifetime in seconds (default 12h). PBKDF2 iterations kept moderate for
    # sandbox CPUs; production should raise (>=600_000) — see KNOWN_LIMITATIONS.md.
    auth_token_ttl_seconds: int = 60 * 60 * 12
    password_pbkdf2_iterations: int = 120_000

    # Dev conveniences. MUST be false in production (seed endpoint disabled).
    dev_mode: bool = True

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
