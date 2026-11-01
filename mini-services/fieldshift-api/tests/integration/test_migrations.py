"""Integration: clean-database migration runs (Master protocol step 3).

Runs alembic in a subprocess against a scratch database:
drop -> create -> upgrade head -> downgrade base -> upgrade head again.
"""

import os
import subprocess

import psycopg2
import pytest
from sqlalchemy import create_engine, text

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SCRATCH_DB = "fieldshift_mig_test"
SCRATCH_URL = f"postgresql+psycopg2://postgres@127.0.0.1:5433/{SCRATCH_DB}"


def _psql(dbname: str, sql: str) -> None:
    conn = psycopg2.connect(host="127.0.0.1", port=5433, user="postgres", dbname=dbname)
    conn.autocommit = True
    conn.cursor().execute(sql)
    conn.close()


def _alembic(*args: str) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env["FIELDSHIFT_DATABASE_URL"] = SCRATCH_URL
    return subprocess.run(
        [os.path.join(ROOT, ".venv", "bin", "alembic"), *args],
        cwd=ROOT, env=env, capture_output=True, text=True, timeout=180,
    )


@pytest.fixture()
def scratch_db():
    conn = psycopg2.connect(host="127.0.0.1", port=5433, user="postgres", dbname="postgres")
    conn.autocommit = True
    cur = conn.cursor()
    cur.execute(f"DROP DATABASE IF EXISTS {SCRATCH_DB} WITH (FORCE)")
    cur.execute(f"CREATE DATABASE {SCRATCH_DB} ENCODING 'UTF8'")
    conn.close()
    yield SCRATCH_DB
    conn = psycopg2.connect(host="127.0.0.1", port=5433, user="postgres", dbname="postgres")
    conn.autocommit = True
    conn.cursor().execute(f"DROP DATABASE IF EXISTS {SCRATCH_DB} WITH (FORCE)")
    conn.close()


class TestMigrations:
    def test_clean_upgrade_creates_postgis_schema(self, scratch_db):
        result = _alembic("upgrade", "head")
        assert result.returncode == 0, result.stderr

        engine = create_engine(SCRATCH_URL)
        with engine.connect() as conn:
            tables = {r[0] for r in conn.execute(text(
                "SELECT table_name FROM information_schema.tables WHERE table_schema='public'"
            ))}
            expected = {
                "users", "organizations", "memberships", "auth_tokens", "farms", "fields",
                "field_boundary_versions", "data_sources", "dataset_products", "ingestion_jobs",
                "observations", "observation_quality_flags", "audit_events", "farm_constraints",
                "alembic_version",
            }
            assert expected.issubset(tables)

            geom = conn.execute(text(
                "SELECT type, srid FROM geometry_columns WHERE f_table_name='fields'"
            )).fetchall()
            assert geom == [("MULTIPOLYGON", 4326)]

            ext = conn.execute(text("SELECT extname FROM pg_extension WHERE extname='postgis'")).scalar()
            assert ext == "postgis"
        engine.dispose()

    def test_downgrade_and_reupgrade_roundtrip(self, scratch_db):
        assert _alembic("upgrade", "head").returncode == 0
        down = _alembic("downgrade", "base")
        assert down.returncode == 0, down.stderr
        engine = create_engine(SCRATCH_URL)
        with engine.connect() as conn:
            tables = {r[0] for r in conn.execute(text(
                "SELECT table_name FROM information_schema.tables WHERE table_schema='public'"
            ))}
            assert "users" not in tables and "fields" not in tables
        engine.dispose()
        again = _alembic("upgrade", "head")
        assert again.returncode == 0, again.stderr


M7_1_EXPECTED_TABLES = {"field_states"}
M7_1_EXPECTED_COLUMNS = {
    "feature_runs": {"boundary_version", "observation_manifest", "observation_manifest_sha256"},
    "water_plans": {"boundary_version", "started_at", "completed_at"},
}


class TestM7_1FieldStateFoundation:
    """Migration 0007: field_states + H-01/H-02 columns + F-30 index."""

    def test_upgrade_creates_field_state_schema(self, scratch_db):
        assert _alembic("upgrade", "head").returncode == 0
        engine = create_engine(SCRATCH_URL)
        with engine.connect() as conn:
            tables = {r[0] for r in conn.execute(text(
                "SELECT table_name FROM information_schema.tables WHERE table_schema='public'"
            ))}
            assert M7_1_EXPECTED_TABLES.issubset(tables)

            for table, columns in M7_1_EXPECTED_COLUMNS.items():
                present = {r[0] for r in conn.execute(text(
                    f"SELECT column_name FROM information_schema.columns "
                    f"WHERE table_name='{table}'"
                ))}
                assert columns.issubset(present), f"{table}: missing {columns - present}"

            indexes = {r[0] for r in conn.execute(text(
                "SELECT indexname FROM pg_indexes WHERE tablename='ingestion_jobs'"
            ))}
            assert "uq_ingestion_idempotency_v2" in indexes
            assert "uq_ingestion_idempotency" not in indexes

            state_indexes = {r[0] for r in conn.execute(text(
                "SELECT indexname FROM pg_indexes WHERE tablename='field_states'"
            ))}
            assert {"uq_field_state_idempotency", "ix_field_states_field"} <= state_indexes
        engine.dispose()

    def test_downgrade_to_0006_reverses_m7_1_schema(self, scratch_db):
        assert _alembic("upgrade", "head").returncode == 0
        down = _alembic("downgrade", "0006_water_intelligence")
        assert down.returncode == 0, down.stderr
        engine = create_engine(SCRATCH_URL)
        with engine.connect() as conn:
            tables = {r[0] for r in conn.execute(text(
                "SELECT table_name FROM information_schema.tables WHERE table_schema='public'"
            ))}
            assert "field_states" not in tables
            for table, columns in M7_1_EXPECTED_COLUMNS.items():
                present = {r[0] for r in conn.execute(text(
                    f"SELECT column_name FROM information_schema.columns "
                    f"WHERE table_name='{table}'"
                ))}
                assert columns.isdisjoint(present), f"{table}: {columns & present} not dropped"

            indexes = {r[0] for r in conn.execute(text(
                "SELECT indexname FROM pg_indexes WHERE tablename='ingestion_jobs'"
            ))}
            assert "uq_ingestion_idempotency" in indexes, "legacy key-only index restored"
            assert "uq_ingestion_idempotency_v2" not in indexes
        engine.dispose()
        again = _alembic("upgrade", "head")
        assert again.returncode == 0, again.stderr
