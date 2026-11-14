"""Pytest fixtures: isolated test database (real PostgreSQL + PostGIS), API client.

The test database is `croptwist_test` on the local sandbox cluster. All env
overrides happen BEFORE any app import so cached settings pick them up.
"""

import os
import sys
import tempfile
from urllib.parse import urlsplit

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

TEST_DB_URL = os.environ.get(
    "CROPTWIST_TEST_DB_URL",
    "postgresql+psycopg2://postgres@127.0.0.1:5433/croptwist_test",
)
_test_dsn = urlsplit(TEST_DB_URL)
_test_db_name = _test_dsn.path.lstrip("/")
if (
    _test_dsn.scheme not in {"postgresql", "postgresql+psycopg2"}
    or _test_dsn.hostname not in {"127.0.0.1", "localhost", "::1"}
    or not _test_db_name.startswith("croptwist_")
    or not _test_db_name.endswith("test")
    or not _test_db_name.replace("_", "").isalnum()
):
    raise RuntimeError("Refusing destructive fixtures: use a local disposable croptwist_*test database.")
os.environ["CROPTWIST_DATABASE_URL"] = TEST_DB_URL
os.environ["CROPTWIST_ENVIRONMENT"] = "test"
# Sandbox parity (auth hardening P0-2): registration auto-verifies emails,
# matching the dev server which runs with CROPTWIST_DEV_MODE=true via .env.
os.environ.setdefault("CROPTWIST_DEV_MODE", "true")
# The per-IP auth rate limiter would count ALL tests against the shared
# "testclient" key; disable it suite-wide. Dedicated hardening tests
# monkeypatch settings.auth_rate_limit_per_minute and reset the store.
os.environ.setdefault("CROPTWIST_AUTH_RATE_LIMIT_PER_MINUTE", "0")
# Async jobs (P0-3): keep legacy inline ingestion suite-wide (existing tests
# assert synchronous completion). Dedicated background-job tests start the
# executor explicitly via start_workers() + wait_for_job().
os.environ.setdefault("CROPTWIST_JOB_WORKERS", "0")
# Filesystem-backed raster/report integration tests must never depend on a
# developer-specific /home/z path or write outside a disposable temp root.
_TEST_ARTIFACTS_TMP = tempfile.TemporaryDirectory(prefix="croptwist-test-artifacts-")
_TEST_ARTIFACT_ROOT = _TEST_ARTIFACTS_TMP.name
os.environ["CROPTWIST_RASTER_STORAGE_ROOT"] = os.path.join(_TEST_ARTIFACT_ROOT, "rasters")
os.environ["CROPTWIST_REPORTS_DIR"] = os.path.join(_TEST_ARTIFACT_ROOT, "reports")

import psycopg2  # noqa: E402
import pytest  # noqa: E402


def run_raster_job_through_worker(
    raster_job_id, db=None, *, simulate_process_restart: bool = False
):
    """Execute a queued raster job through the real owned worker claim path.

    Tests keep the suite-wide worker count at zero for determinism, but raster
    jobs still require the same claim, execution context, lease and finalizer
    used by production workers. This helper calls the core worker entrypoint
    synchronously instead of bypassing its fencing contract.
    """
    import uuid

    from app.core import jobs
    from app.db.models_p2 import RasterProcessingJob

    raster_job_id = uuid.UUID(str(raster_job_id))
    if db is None:
        from app.core.database import SessionLocal

        with SessionLocal() as lookup:
            raster_job = lookup.get(RasterProcessingJob, raster_job_id)
            if raster_job is None or raster_job.background_job_id is None:
                raise AssertionError("Raster job must have a persisted background job.")
            background_job_id = raster_job.background_job_id
    else:
        db.expire_all()
        raster_job = db.get(RasterProcessingJob, raster_job_id)
        if raster_job is None or raster_job.background_job_id is None:
            raise AssertionError("Raster job must have a persisted background job.")
        background_job_id = raster_job.background_job_id

    if simulate_process_restart:
        # A restarted process has no in-memory submitted callback; dispatch
        # through the registered durable-kind executor instead.
        with jobs._registry_lock:
            jobs._pending_fns.pop(background_job_id, None)

    jobs._run_job(background_job_id)
    background_job = jobs.wait_for_job(background_job_id, timeout=120.0)
    if background_job.status not in jobs._TERMINAL_BACKGROUND_STATUSES:
        raise AssertionError("Raster background job did not reach a terminal state.")

    if db is not None:
        db.expire_all()
        return db.get(RasterProcessingJob, raster_job_id)

    with SessionLocal() as lookup:
        raster_job = lookup.get(RasterProcessingJob, raster_job_id)
        if raster_job is not None:
            lookup.expunge(raster_job)
        return raster_job


def _ensure_test_database() -> None:
    from psycopg2 import sql

    connection_options = {
        "host": _test_dsn.hostname,
        "port": _test_dsn.port or 5432,
        "user": _test_dsn.username or "postgres",
        "password": _test_dsn.password,
    }
    conn = psycopg2.connect(**connection_options, dbname="postgres")
    conn.autocommit = True
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (_test_db_name,))
    if cur.fetchone() is None:
        cur.execute(sql.SQL("CREATE DATABASE {} ENCODING 'UTF8'").format(sql.Identifier(_test_db_name)))
    conn.close()
    conn = psycopg2.connect(**connection_options, dbname=_test_db_name)
    conn.autocommit = True
    conn.cursor().execute("CREATE EXTENSION IF NOT EXISTS postgis")
    conn.close()


_ensure_test_database()

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import text  # noqa: E402

from app.core.database import SessionLocal, engine  # noqa: E402
from app.db.models import Base  # noqa: E402
from app.main import app  # noqa: E402


def _migrate_test_database() -> None:
    """Bring an EXISTING test database up to head (create_all alone cannot
    change indexes/constraints on tables that already exist — deepening F-3/F-18
    rely on migration 0005's index definitions)."""
    import os as _os

    from alembic import command
    from alembic.config import Config

    cfg = Config(_os.path.join(ROOT, "alembic.ini"))
    cfg.set_main_option("script_location", _os.path.join(ROOT, "migrations"))
    # A database previously built by create_all has tables but no alembic
    # bookkeeping — stamp it to the pre-deepening revision, then migrate.
    with engine.connect() as conn:
        has_version = conn.execute(
            text("SELECT to_regclass('alembic_version')")
        ).scalar() is not None
        has_users = conn.execute(text("SELECT to_regclass('users')")).scalar() is not None
    if not has_version and has_users:
        command.stamp(cfg, "0004_knowledge_rotation")
    command.upgrade(cfg, "head")


_migrate_test_database()
Base.metadata.create_all(bind=engine)

# P3 §4.1: databases built via create_all + stamp never ran migration
# 0020's frozen plan-catalog seeder (croptwist_test is exactly that case).
# Ensure the catalog exists here with the same insert-missing-only module
# the app lifespan uses at startup.
from app.billing.catalog import ensure_plan_catalog as _ensure_plan_catalog  # noqa: E402

with SessionLocal() as _seed_db:
    try:
        _ensure_plan_catalog(_seed_db)
        _seed_db.commit()
    finally:
        _seed_db.close()


# ---------------------------------------------------------------------------
# P0 determinism (audit Phase 2): intercept OUTBOUND provider transport
# suite-wide. The provider contract suites already mock httpx ("the suite
# never needs a network" — see tests/contract docstrings); integration tests
# must obey the same rule. Live Open-Meteo made the suite nondeterministic:
# a shared-IP HTTP 429 from archive-api.open-meteo.com failed
# test_data_passport (job → 'ProviderUnavailable' → 1 passport entry instead
# of 2). This fixture fakes the Open-Meteo archive deterministically from
# the request params, delegates INTERNAL hosts (LLM bridge on 127.0.0.1) to
# the real transport, and fails LOUDLY on any other external host so new
# live dependencies cannot silently creep into ordinary tests.
# ---------------------------------------------------------------------------
import datetime as _dt  # noqa: E402
from urllib.parse import urlsplit as _urlsplit  # noqa: E402

import httpx as _httpx  # noqa: E402

_REAL_HTTPX_GET = _httpx.get

_OPEN_METEO_UNITS = {
    "temperature_2m_mean": "degC",
    "temperature_2m_min": "degC",
    "temperature_2m_max": "degC",
    "precipitation_sum": "mm",
    "et0_fao_evapotranspiration": "mm",
    "soil_moisture_0_to_7cm_mean": "m3/m3",
    "wind_speed_10m_mean": "km/h",
}
_INTERNAL_HOSTS = {"127.0.0.1", "localhost", "testserver", "::1"}


class _FakeResponse:
    """Minimal httpx.Response stand-in for the provider's sync calls."""

    def __init__(self, payload: dict, url: str):
        self.status_code = 200
        self._payload = payload
        self.text = ""
        self._url = url

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self._payload


def _fake_open_meteo_archive(params: dict) -> dict:
    # Forecast-style requests (api.open-meteo.com/v1/forecast) carry
    # `forecast_days` and no start/end — synthesize a deterministic window
    # from today so the P2 forecast provider contract stays network-free.
    if "start_date" not in params:
        forecast_days = int(params.get("forecast_days") or 7)
        start = _dt.date.today()
        end = start + _dt.timedelta(days=max(1, forecast_days) - 1)
        params = dict(params)
        params["start_date"] = start.isoformat()
        params["end_date"] = end.isoformat()
    start = _dt.date.fromisoformat(str(params["start_date"]))
    end = _dt.date.fromisoformat(str(params["end_date"]))
    days: list[str] = []
    cursor = start
    while cursor <= end:
        days.append(cursor.isoformat())
        cursor += _dt.timedelta(days=1)
    daily_codes = str(params.get("daily", "")).split(",") if params.get("daily") else []

    def _value(day_index: int, code: str) -> float:
        n = day_index * 7 + len(code)
        if code.startswith("temperature_2m"):
            return round(10 + (n % 15) / 2, 2)
        if code == "precipitation_sum":
            return round((n % 30) / 4, 2)
        if code == "et0_fao_evapotranspiration":
            return round(1 + (n % 8) / 2, 2)
        if code.startswith("soil_moisture"):
            return round(0.10 + (n % 20) / 100, 3)
        return round(2 + (n % 14) / 3, 2)

    daily: dict = {"time": days}
    for code in daily_codes:
        daily[code] = [_value(i, code) for i in range(len(days))]
    return {
        "latitude": params.get("latitude"),
        "longitude": params.get("longitude"),
        "elevation": 3.0,
        "utc_offset_seconds": 0,
        "timezone": "GMT",
        "daily_units": {c: _OPEN_METEO_UNITS.get(c, "unit") for c in daily_codes},
        "daily": daily,
    }


def _fake_httpx_get(url, params=None, **kwargs):  # noqa: ANN001, ANN002
    host = (_urlsplit(str(url)).hostname or "").lower()
    if host in _INTERNAL_HOSTS or host.endswith(".local"):
        return _REAL_HTTPX_GET(url, params=params, **kwargs)
    if host in ("archive-api.open-meteo.com", "api.open-meteo.com"):
        return _FakeResponse(_fake_open_meteo_archive(dict(params or {})), str(url))
    # geocoding or any other external host: loud, deterministic failure
    raise RuntimeError(
        "test hit external network host "
        f"'{host}' — ordinary tests must not need the network. If this is a "
        "new provider, add a deterministic fake to tests/conftest.py or mock "
        "at the provider boundary (see tests/contract/)."
    )


_httpx.get = _fake_httpx_get  # type: ignore[assignment]


@pytest.fixture()
def db():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture(autouse=True)
def clean_tables():
    yield
    # Keep production immutability triggers enabled. Trigger-protected
    # result tables use disposable-only TRUNCATE; other tables use FK-ordered
    # DELETE to avoid regenerating dozens of relation files on every test.
    from tests.db_cleanup import child_first_tables

    postgis_internal = (
        "'alembic_version', 'spatial_ref_sys', 'geography_columns', 'geometry_columns'"
    )
    last_exc: Exception | None = None
    for attempt in range(3):
        try:
            with engine.begin() as conn:
                # Fail fast instead of hanging the suite: lock waits cap at
                # 10s and any single statement at 120s (a stuck smgr truncate
                # on this storage previously blocked runs indefinitely).
                conn.exec_driver_sql("SET lock_timeout = '10s'")
                conn.exec_driver_sql("SET statement_timeout = '120s'")
                rows = conn.exec_driver_sql(
                    "SELECT tablename FROM pg_tables WHERE schemaname = 'public' "
                    f"AND tablename NOT IN ({postgis_internal}) ORDER BY tablename"
                ).fetchall()
                names = [row[0] for row in rows]
                if not names:
                    return
                # Probe only actual public tables, preserving PostGIS and
                # Alembic bookkeeping; empty tables need no row deletion.
                union_sql = " UNION ALL ".join(
                    f"SELECT '{name}' AS t, EXISTS(SELECT 1 FROM \"{name}\") AS dirty"
                    for name in names
                )
                dirty = [
                    row[0]
                    for row in conn.exec_driver_sql(union_sql).fetchall()
                    if row[1]
                ]
                if not dirty:
                    return
                edges = conn.exec_driver_sql(
                    "SELECT confrelid::regclass::text AS parent, "
                    "conrelid::regclass::text AS child FROM pg_constraint "
                    "WHERE contype = 'f'"
                ).fetchall()
                protected = {
                    row[0] for row in conn.exec_driver_sql(
                        "SELECT DISTINCT tgrelid::regclass::text FROM pg_trigger "
                        "WHERE NOT tgisinternal AND POSITION('DELETE' IN pg_get_triggerdef(oid)) > 0"
                    ).fetchall()
                }
                truncate_set = set(dirty) & protected
                frontier = list(truncate_set)
                while frontier:
                    parent = frontier.pop()
                    for known_parent, child in edges:
                        if known_parent == parent and child in names and child not in truncate_set:
                            truncate_set.add(child)
                            frontier.append(child)
                if truncate_set:
                    table_sql = ', '.join('"' + name.replace('"', '""') + '"' for name in sorted(truncate_set))
                    conn.exec_driver_sql(f"TRUNCATE TABLE {table_sql}")
                for name in child_first_tables(names, list(edges)):
                    if name in dirty and name not in truncate_set:
                        quoted = name.replace('"', '""')
                        conn.exec_driver_sql(f'DELETE FROM "{quoted}"')
            return
        except Exception as exc:  # noqa: BLE001 — any DB error: back off, retry
            last_exc = exc
            import time as _time

            _time.sleep(1.0 + attempt)
    assert last_exc is None, f"clean_tables row cleanup failed after retries: {last_exc}"


@pytest.fixture(scope="session", autouse=False)
def purge_stale_rows_before_session_DISABLED():
    """Wipe rows left behind by killed previous runs BEFORE any test runs.

    Killed pytest processes can leave BackgroundJob rows in 'queued' — a new
    session's worker-pool startup (crash recovery) would re-enqueue and
    execute them on worker threads concurrently with this session's TRUNCATE
    cleanup, deadlocking on table locks. Purging first makes recovery a
    no-op for this session.
    """
    with engine.begin() as conn:
        for table in reversed(Base.metadata.sorted_tables):
            conn.execute(text(f'TRUNCATE TABLE "{table.name}" CASCADE'))


@pytest.fixture()
def auth_headers(client):
    """Register a fresh user, return (headers, user_json)."""
    import uuid

    email = f"user-{uuid.uuid4().hex[:10]}@test.local"
    resp = client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "test-password-1", "display_name": "Test Farmer"},
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    return {"Authorization": f"Bearer {data['token']}"}, data


@pytest.fixture()
def farm_with_field(client, auth_headers):
    """Register user + farm + one square field; return dict of ids/headers."""
    headers, user = auth_headers
    farm_resp = client.post(
        "/api/v1/farms",
        headers=headers,
        json={"name": "Test Farm", "country_code": "EG", "timezone": "Africa/Cairo", "currency_code": "EGP"},
    )
    assert farm_resp.status_code == 201, farm_resp.text
    farm = farm_resp.json()
    field_resp = client.post(
        f"/api/v1/farms/{farm['id']}/fields",
        headers=headers,
        json={
            "name": "North Field",
            "geometry": {
                "type": "Polygon",
                "coordinates": [[[31.40, 31.10], [31.42, 31.10], [31.42, 31.12], [31.40, 31.12], [31.40, 31.10]]],
            },
        },
    )
    assert field_resp.status_code == 201, field_resp.text
    field = field_resp.json()
    return {"headers": headers, "user": user, "farm": farm, "field": field}
