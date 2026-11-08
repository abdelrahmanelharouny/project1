"""Integration: clean-database migration runs (Master protocol step 3).

Runs alembic in a subprocess against a scratch database:
drop -> create -> upgrade head -> downgrade base -> upgrade head again.
"""

import os
import subprocess
import sys

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
    # Prefer an in-project virtualenv when present; otherwise run alembic from
    # the CURRENT interpreter (works when the suite runs from any venv path,
    # e.g. /home/z/fieldshift-api-venv in the sandbox or the CI runner).
    local_alembic = os.path.join(ROOT, ".venv", "bin", "alembic")
    if os.path.exists(local_alembic):
        cmd = [local_alembic, *args]
    else:
        cmd = [sys.executable, "-m", "alembic", *args]
    return subprocess.run(
        cmd,
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


M7_2_EXPECTED_TABLES = {"scenarios", "scenario_validation_records"}
M7_2_EXPECTED_COLUMNS = {
    "scenarios": {
        "parent_field_state_id", "parent_snapshot_checksum", "boundary_version",
        "canonical_configuration", "configuration_checksum", "evidence_classification",
        "scenario_status", "lineage_kind", "scenario_version", "finalized_at",
    },
}


class TestM7_2ScenarioDomain:
    """Migration 0008: scenarios + validation records + immutability trigger."""

    def test_upgrade_creates_scenario_schema_and_trigger(self, scratch_db):
        assert _alembic("upgrade", "head").returncode == 0
        engine = create_engine(SCRATCH_URL)
        with engine.connect() as conn:
            tables = {r[0] for r in conn.execute(text(
                "SELECT table_name FROM information_schema.tables WHERE table_schema='public'"
            ))}
            assert M7_2_EXPECTED_TABLES.issubset(tables)
            for table, columns in M7_2_EXPECTED_COLUMNS.items():
                present = {r[0] for r in conn.execute(text(
                    f"SELECT column_name FROM information_schema.columns "
                    f"WHERE table_name='{table}'"
                ))}
                assert columns.issubset(present), f"{table}: missing {columns - present}"
            indexes = {r[0] for r in conn.execute(text(
                "SELECT indexname FROM pg_indexes WHERE tablename='scenarios'"
            ))}
            assert {"uq_scenario_idempotency", "ix_scenarios_field"} <= indexes
            trigger = conn.execute(text(
                "SELECT tgname FROM pg_trigger WHERE tgrelid = 'scenarios'::regclass "
                "AND NOT tgisinternal"
            )).scalars().all()
            assert "trg_scenario_immutability" in trigger
            # type↔evidence binding check exists (C2 at the database level)
            checks = conn.execute(text(
                "SELECT conname FROM pg_constraint WHERE conrelid='scenarios'::regclass "
                "AND contype='c'"
            )).scalars().all()
            assert "ck_scenario_type_evidence_binding" in checks
            assert "ck_scenario_unavailable_types_never_finalized" in checks
        engine.dispose()

    def test_trigger_freezes_finalized_rows(self, scratch_db):
        import uuid as _uuid

        assert _alembic("upgrade", "head").returncode == 0
        engine = create_engine(SCRATCH_URL)
        org, user, farm, field, state, scenario = (
            _uuid.uuid4(), _uuid.uuid4(), _uuid.uuid4(), _uuid.uuid4(), _uuid.uuid4(), _uuid.uuid4(),
        )
        with engine.begin() as conn:
            conn.execute(text(
                "INSERT INTO organizations (id, name) VALUES (:i, 'org')",
            ),
            {"i": org})
            conn.execute(text(
                "INSERT INTO users (id, email, password_hash, display_name) "
                "VALUES (:i, 't@t.local', 'x', 'T')",
            ),
            {"i": user})
            conn.execute(text(
                "INSERT INTO farms (id, organization_id, name, country_code, timezone, currency_code) "
                "VALUES (:i, :o, 'f', 'EG', 'UTC', 'EGP')",
            ),
            {"i": farm, "o": org})
            conn.execute(text(
                "INSERT INTO fields (id, farm_id, name, area_ha, boundary, boundary_version) "
                "VALUES (:i, :f, 'fd', 1.0, ST_GeomFromText('POLYGON((31 30,31.01 30,31.01 30.01,31 30.01,31 30))',4326), 1)",
            ),
            {"i": field, "f": farm})
            conn.execute(text(
                "INSERT INTO field_boundary_versions (id, field_id, version_number, boundary, area_ha, change_reason) "
                "VALUES (:i, :fid, 1, ST_GeomFromText('POLYGON((31 30,31.01 30,31.01 30.01,31 30.01,31 30))',4326), 1.0, 'init')",
            ), {"i": _uuid.uuid4(), "fid": field})
            conn.execute(text(
                "INSERT INTO field_states (id, field_id, status, boundary_version, "
                "state_reference_time, period_start, period_end, manifest_format_version, "
                "checksum_sha256) VALUES (:i, :fid, 'succeeded', 1, now(), now(), now(), "
                "'field-observation-manifest-1', :ck)",
            ), {"i": state, "fid": field, "ck": "c" * 64})
            conn.execute(text(
                "INSERT INTO scenarios (id, field_id, name, scenario_type, scenario_status, "
                "parent_field_state_id, parent_snapshot_checksum, boundary_version, "
                "configuration_schema_version, canonical_configuration, configuration_checksum, "
                "period_start, period_end, evidence_classification, finalized_at) "
                "VALUES (:i, :fid, 's', 'user_defined_stress', 'finalized', :sid, :ck, 1, "
                "'scenario-config-1.0', '{}', :cc, now(), now(), 'hypothetical', now())",
            ), {"i": scenario, "fid": field, "sid": state, "ck": "c" * 64, "cc": "a" * 64})
        # any content change must be rejected by the trigger
        from sqlalchemy.exc import DBAPIError

        tamper_attempts = [
            (
                "UPDATE scenarios SET canonical_configuration = :cfg WHERE id = :sid",
                {"sid": scenario, "cfg": '{"tampered": true}'},
            ),
            (
                "UPDATE scenarios SET configuration_checksum = :new WHERE id = :sid",
                {"sid": scenario, "new": "b" * 64},
            ),
            (
                "UPDATE scenarios SET scenario_status = 'draft' WHERE id = :sid",
                {"sid": scenario},
            ),
        ]
        rejections = 0
        for statement, params in tamper_attempts:
            try:
                with engine.begin() as conn:
                    conn.execute(text(statement), params)
            except DBAPIError:
                rejections += 1
        assert rejections == 3, f"trigger rejected {rejections}/3 tamper attempts"

        # the ONLY allowed transition: finalized → archived
        with engine.begin() as conn:
            conn.execute(text(
                "UPDATE scenarios SET scenario_status = 'archived' WHERE id = :sid",
            ), {"sid": scenario})
            status = conn.execute(text(
                "SELECT scenario_status FROM scenarios WHERE id = :sid",
            ), {"sid": scenario}).scalar()
        assert status == "archived"

        # archived is terminal
        try:
            with engine.begin() as conn:
                conn.execute(text(
                    "UPDATE scenarios SET scenario_status = 'finalized' WHERE id = :sid",
                ), {"sid": scenario})
            raised = False
        except DBAPIError:
            raised = True
        assert raised, "archived rows must be terminal"
        engine.dispose()

    def test_downgrade_to_0007_reverses_scenario_schema(self, scratch_db):
        assert _alembic("upgrade", "head").returncode == 0
        down = _alembic("downgrade", "0007_field_state_foundation")
        assert down.returncode == 0, down.stderr
        engine = create_engine(SCRATCH_URL)
        with engine.connect() as conn:
            tables = {r[0] for r in conn.execute(text(
                "SELECT table_name FROM information_schema.tables WHERE table_schema='public'"
            ))}
            assert tables.isdisjoint(M7_2_EXPECTED_TABLES)
            fn = conn.execute(text(
                "SELECT COUNT(*) FROM pg_proc WHERE proname='enforce_scenario_immutability'"
            )).scalar()
            assert fn == 0
        engine.dispose()
        again = _alembic("upgrade", "head")
        assert again.returncode == 0, again.stderr
