"""Application configuration.

Values are read from environment variables with sandbox-safe defaults.
Production deployments must provide real values via their secret manager
(see docs/implementation/DECISIONS_AND_ASSUMPTIONS.md, ADR-0002).
"""

from functools import lru_cache
import re
from urllib.parse import urlsplit

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


_SAFE_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _csv_items(value: str, *, field_name: str, allow_empty: bool = False) -> list[str]:
    """Split a comma-separated setting and reject blank entries."""
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a comma-separated string")
    items = [item.strip() for item in value.split(",") if item.strip()]
    if not items and not allow_empty:
        raise ValueError(f"{field_name} must contain at least one value")
    return items


def parse_search_path(value: str) -> list[str]:
    """Return safe PostgreSQL schema identifiers for ``search_path``.

    Search paths are passed to libpq as a connection option.  Only plain
    identifiers (plus PostgreSQL's ``$user`` token) are accepted so an
    operator cannot inject arbitrary SQL through a deployment environment
    variable.  Quoted identifiers are intentionally not supported.
    """
    items = _csv_items(value, field_name="database_search_path")
    for item in items:
        if item != "$user" and not _SAFE_IDENTIFIER.fullmatch(item):
            raise ValueError(
                "database_search_path entries must be simple SQL identifiers "
                "or $user"
            )
    return items


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="CROPTWIST_", env_file=".env", extra="ignore")

    # Service identity
    service_name: str = "croptwist-api"
    api_version: str = "v1"
    environment: str = "development"  # development | test | production

    # Database (PostgreSQL + PostGIS). Conda-forge user-space cluster in the sandbox.
    database_url: str = "postgresql+psycopg2://postgres@127.0.0.1:5433/croptwist"
    # libpq/SQLAlchemy deployment knobs. Empty SSL values preserve the local
    # sandbox behavior; hosted deployments should set verify-full and a CA.
    database_sslmode: str = ""
    database_sslrootcert: str = ""
    database_connect_timeout_seconds: int = 5
    database_pool_size: int = 5
    database_max_overflow: int = 5
    database_pool_timeout_seconds: int = 10
    database_pool_recycle_seconds: int = 300
    database_health_timeout_seconds: int = 3
    database_search_path: str = "public,extensions"
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
    # A running job is recoverable only after this much inactivity; progress
    # commits refresh the durable background row's updated_at timestamp.
    job_stale_after_seconds: int = 6 * 60 * 60

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
    # Host allowlist. ``*`` preserves local/test behavior; hosted deployments
    # should provide explicit hostnames (for example, api.example.com).
    trusted_hosts: str = "*"
    # Staging and production are secure-by-default. The explicit flag can
    # apply the same safety checks to other environment labels; it is not
    # an opt-out for hosted environments.
    enforce_production_safety: bool = False

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

    # P07 — server-side tile rendering for the map experience. Rendered
    # tiles are cached in a bounded in-process LRU keyed by asset checksum
    # (no external cache dependency; safe for Vercel/API deployment where
    # each instance caches independently).
    raster_tile_cache_max_entries: int = 512
    raster_tile_cache_max_mb: int = 128

    # P3 — billing (W2). Only the sandbox provider is wired; a real provider
    # adapter must supply verified credentials via the secret manager before
    # any live processing is claimed. The webhook secret signs/verifies
    # provider callbacks; rotation restarts acceptance (replay window).
    billing_provider: str = "sandbox"
    billing_webhook_secret: str = ""
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

    @model_validator(mode="after")
    def _production_must_not_use_sandbox_billing(self) -> "Settings":
        if self.environment.lower() == "production":
            if self.dev_mode:
                raise ValueError("CROPTWIST_DEV_MODE must be false in production.")
            if self.billing_provider == "sandbox":
                raise ValueError(
                    "The sandbox billing provider is not permitted in production; "
                    "a verified production billing adapter is not available in this build."
                )
            if (
                not self.billing_webhook_secret
                or len(self.billing_webhook_secret) < 32
            ):
                raise ValueError(
                    "Production requires an explicitly configured billing webhook secret "
                    "of at least 32 characters."
                )
            raise ValueError(
                "No production billing adapter is implemented; refusing production startup."
            )
        return self

    @field_validator("database_sslmode")
    @classmethod
    def validate_database_sslmode(cls, value: str) -> str:
        value = value.strip().lower()
        allowed = {"", "disable", "allow", "prefer", "require", "verify-ca", "verify-full"}
        if value not in allowed:
            raise ValueError("database_sslmode must be a supported libpq sslmode")
        return value

    @field_validator("database_search_path")
    @classmethod
    def validate_database_search_path(cls, value: str) -> str:
        return ",".join(parse_search_path(value))

    @field_validator("cors_allow_origins")
    @classmethod
    def validate_cors_allow_origins(cls, value: str) -> str:
        origins = _csv_items(value, field_name="cors_allow_origins", allow_empty=True)
        for origin in origins:
            if "*" in origin:
                raise ValueError(
                    "cors_allow_origins must list explicit origins; '*' is not "
                    "allowed when credentials are enabled"
                )
            parsed = urlsplit(origin)
            if (
                parsed.scheme not in {"http", "https"}
                or not parsed.netloc
                or parsed.path not in {"", "/"}
                or parsed.query
                or parsed.fragment
                or parsed.username is not None
                or parsed.password is not None
            ):
                raise ValueError(
                    "cors_allow_origins entries must be explicit http(s) origins "
                    "without paths, queries, fragments, or credentials"
                )
            try:
                parsed.port
            except ValueError as exc:
                raise ValueError("cors_allow_origins contains an invalid port") from exc
        return ",".join(origins)

    @field_validator("trusted_hosts")
    @classmethod
    def validate_trusted_hosts(cls, value: str) -> str:
        hosts = _csv_items(value, field_name="trusted_hosts")
        for host in hosts:
            if host == "*" or host.startswith("*."):
                continue
            if (
                any(character.isspace() for character in host)
                or "/" in host
                or "\\" in host
                or host.startswith(".")
                or host.endswith(".")
            ):
                raise ValueError("trusted_hosts entries must be hostnames or IP addresses")
        return ",".join(hosts)

    @model_validator(mode="after")
    def validate_deployment_safety(self) -> "Settings":
        environment = self.environment.strip().lower()
        enforce = self.enforce_production_safety or environment in {"staging", "production"}
        if enforce and self.dev_mode:
            raise ValueError("dev_mode must be false for staging/hosted production")
        if enforce and any("*" in host for host in self.trusted_host_list):
            raise ValueError("trusted_hosts must be explicit for staging/hosted production")
        if enforce:
            if self.database_sslmode != "verify-full" or not self.database_sslrootcert:
                raise ValueError("hosted databases require verify-full and a trusted CA certificate")
            if any(not origin.startswith("https://") for origin in self.cors_origins):
                raise ValueError("hosted CORS origins must use HTTPS")
        if self.database_pool_size < 1 or self.database_max_overflow < 0:
            raise ValueError("database pool size must be positive and overflow bounded")
        if min(self.database_pool_timeout_seconds, self.database_connect_timeout_seconds,
               self.database_health_timeout_seconds) <= 0:
            raise ValueError("database timeouts must be positive")
        return self

    @property
    def cors_origins(self) -> list[str]:
        return _csv_items(self.cors_allow_origins, field_name="cors_allow_origins", allow_empty=True)

    @property
    def trusted_host_list(self) -> list[str]:
        return _csv_items(self.trusted_hosts, field_name="trusted_hosts")

    @property
    def search_path_list(self) -> list[str]:
        return parse_search_path(self.database_search_path)


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
