"""Application configuration.

Values are read from environment variables with sandbox-safe defaults.
Production deployments must provide real values via their secret manager
(see docs/implementation/DECISIONS_AND_ASSUMPTIONS.md, ADR-0002).
"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="CROPTWIST_", env_file=".env", extra="ignore")

    # Service identity
    service_name: str = "croptwist-api"
    api_version: str = "v1"
    environment: str = "development"  # development | test | production

    # Database (PostgreSQL + PostGIS). Conda-forge user-space cluster in the sandbox.
    database_url: str = "postgresql+psycopg2://postgres@127.0.0.1:5433/croptwist"
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

    # P3 W5/W6: periodic maintenance scheduler (report queue, webhook
    # retries, subscription expiry, retention sweeps). Disable in unit
    # tests via CROPTWIST_SCHEDULER_ENABLED=false.
    scheduler_enabled: bool = True

    # Dev conveniences. Secure-by-default: false unless explicitly enabled.
    # The sandbox runs with CROPTWIST_DEV_MODE=true via .env (gitignored);
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

    # P2.A — Sentinel-2 via STAC (Copernicus Data Space Ecosystem).
    # Credentials are optional: without them, anonymous STAC search is tried
    # and protected asset reads fail loudly (never fabricated).
    sentinel2_stac_base_url: str = "https://catalogue.dataspace.copernicus.eu/stac"
    sentinel2_timeout_seconds: float = 30.0
    sentinel2_default_max_cloud_cover: float = 80.0
    cdse_username: str = ""
    cdse_password: str = ""
    cdse_token_url: str = "https://identity.dataspace.copernicus.eu/auth/realms/CDSE/protocol/openid-connect/token"

    # P2.B — Open-Meteo forecast API (free, no key; separate from archive).
    open_meteo_forecast_base_url: str = "https://api.open-meteo.com/v1/forecast"
    open_meteo_forecast_timeout_seconds: float = 20.0
    open_meteo_forecast_days: int = 16
    forecast_freshness_max_age_hours: float = 12.0

    # P04 — NASA HLS (Harmonized Landsat Sentinel-2) via CMR STAC / LP DAAC.
    # CMR STAC discovery is unauthenticated; asset reads require a free NASA
    # Earthdata Login. Credentials arrive ONLY via env/secret manager and are
    # never hardcoded. With no credentials configured, discovery still works
    # and protected asset reads fail loudly (never fabricated).
    nasa_hls_stac_base_url: str = "https://cmr.earthdata.nasa.gov/stac/LPCLOUD"
    nasa_hls_l30_collection_id: str = "HLSL30_2.0"
    nasa_hls_s30_collection_id: str = "HLSS30_2.0"
    nasa_hls_timeout_seconds: float = 30.0
    nasa_hls_default_max_cloud_cover: float = 80.0
    nasa_hls_search_page_size: int = 100
    nasa_hls_max_pages: int = 5
    nasa_hls_max_scenes_per_job: int = 30
    nasa_hls_max_discovery_span_days: int = 730
    earthdata_username: str = ""
    earthdata_password: str = ""
    earthdata_bearer_token: str = ""
    earthdata_token_url: str = "https://urs.earthdata.nasa.gov/api/users/token"

    # P05 — geospatial raster storage + processing workers.
    # Object storage backend for raster assets: 'local' (development) or
    # 's3' (any S3-compatible store). Credentials/endpoint ONLY via env or
    # secret manager — never code, never the database.
    raster_storage_backend: str = "local"
    raster_storage_root: str = "/home/z/my-project/raster_storage"
    s3_endpoint_url: str = ""
    s3_region: str = ""
    s3_bucket: str = ""
    s3_access_key_id: str = ""
    s3_secret_access_key: str = ""
    s3_kms_key_id: str = ""
    raster_url_secret: str = ""
    # Derived-product processing: index codes a processing job may request,
    # default processing version stamp, and per-scene window read cap.
    raster_processing_default_version: str = "hls-derivation-1.0.0"
    raster_max_field_window_mb: float = 256.0
    raster_preview_max_px: int = 512

    # P3 — billing (W2). Only the sandbox provider is wired; a real provider
    # adapter must supply verified credentials via the secret manager before
    # any live processing is claimed. The webhook secret signs/verifies
    # provider callbacks; rotation restarts acceptance (replay window).
    billing_provider: str = "sandbox"
    billing_webhook_secret: str = "sandbox-billing-webhook-secret-change-me"
    billing_grace_seconds: int = 3 * 24 * 3600  # past_due → grace window
    billing_max_webhook_payload_bytes: int = 262_144

    # P3 — public API keys (W6). Plaintext keys are shown once at creation.
    api_key_prefix: str = "ctk_"

    # P3 — outgoing webhooks (W6): signing secret rotation and delivery.
    webhook_max_attempts: int = 5
    webhook_backoff_seconds: list[int] = [30, 120, 600, 3600, 21600]
    webhook_max_endpoints_per_org: int = 20

    # P3 — reports (W5): storage root for generated artifacts + retention.
    reports_dir: str = "/home/z/my-project/mini-services/fieldshift-api/reports_storage"
    report_retention_days: int = 30
    report_max_per_month_free: int = 3


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
