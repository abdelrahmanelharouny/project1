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
