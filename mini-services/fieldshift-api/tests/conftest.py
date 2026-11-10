"""Pytest fixtures: isolated test database (real PostgreSQL + PostGIS), API client.

The test database is `croptwist_test` on the local sandbox cluster. All env
overrides happen BEFORE any app import so cached settings pick them up.
"""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

TEST_DB_URL = os.environ.get(
    "CROPTWIST_TEST_DB_URL",
    "postgresql+psycopg2://postgres@127.0.0.1:5433/croptwist_test",
)
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

import psycopg2  # noqa: E402
import pytest  # noqa: E402


def _ensure_test_database() -> None:
    conn = psycopg2.connect(host="127.0.0.1", port=5433, user="postgres", dbname="postgres")
    conn.autocommit = True
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM pg_database WHERE datname = 'croptwist_test'")
    if cur.fetchone() is None:
        cur.execute("CREATE DATABASE croptwist_test ENCODING 'UTF8'")
    conn.close()
    conn = psycopg2.connect(host="127.0.0.1", port=5433, user="postgres", dbname="croptwist_test")
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
    # Existence-filtered, retrying truncate. Two failure modes observed on
    # this sandbox (both intermittent, order/timing dependent):
    #  1. UndefinedTable — Base.metadata can know a table the test DB has not
    #     got yet (metadata grows as tests lazily import model modules).
    #     TRUNCATE now references ONLY tables that actually exist.
    #  2. Deadlock — the single-statement TRUNCATE takes ~81 AccessExclusive
    #     locks one by one and can cross-lock with a lazy seeder running on
    #     another pooled connection (load_knowledge -> seed_default_packs).
    #     PostgreSQL resolves the deadlock in ~1s (deadlock_timeout); the
    #     victim's transaction aborts, so a short retry on a FRESH
    #     transaction reliably completes the cleanup.
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
                tables = ", ".join(f'"{row[0]}"' for row in rows)
                # One statement for ALL tables: TRUNCATE of the full set needs
                # no CASCADE (every referencing table is included) and issues
                # one relation-lock cycle instead of ~80.
                if tables:
                    conn.exec_driver_sql(f"TRUNCATE TABLE {tables}")
            return
        except Exception as exc:  # noqa: BLE001 — any DB error: back off, retry
            last_exc = exc
            import time as _time

            _time.sleep(1.0 + attempt)
    assert last_exc is None, f"clean_tables truncate failed after retries: {last_exc}"


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
