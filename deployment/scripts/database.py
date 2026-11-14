#!/usr/bin/env python3
"""Plan/probe by default. Apply only a reviewed digest to an approved target.

No schema reset, downgrade, stamp, extension drop, or restore command exists.
Run with the backend virtualenv; see SUPABASE_SETUP.md for owner approval.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "mini-services/fieldshift-api"
sys.path.insert(0, str(BACKEND))


def is_disposable(url) -> bool:
    return url.host in {"127.0.0.1", "localhost", "::1"} and bool(
        url.database and url.database.startswith("croptwist_deploy_")
    )


def target_id(url) -> str:
    """Bind approval to endpoint/login/database, never include a password."""
    return hashlib.sha256(json.dumps({
        "host": url.host, "port": url.port, "database": url.database,
        "username": url.username,
    }, sort_keys=True).encode()).hexdigest()


def configured_url():
    from app.core.config import settings
    from app.core.database import get_database_connect_args
    from sqlalchemy.engine import make_url
    url = make_url(settings.database_url)
    if url.drivername != "postgresql+psycopg2":
        raise ValueError("Use postgresql+psycopg2; no SQLite or implicit driver fallback")
    # Alembic's frozen env.py builds its own engine. Put the same connection
    # options into the URL rather than changing the migration environment.
    args = {key: str(value) for key, value in get_database_connect_args().items()}
    url = url.update_query_dict(args)
    if not is_disposable(url):
        if url.query.get("sslmode") != "verify-full" or not url.query.get("sslrootcert"):
            raise ValueError("Non-disposable targets require verify-full and the dashboard CA")
        if url.port == 6543:
            raise ValueError("Migration tooling must not use transaction pooling")
    return url


def alembic_config(url, output):
    from alembic.config import Config
    class SafeConfig(Config):
        def set_main_option(self, name, value):
            # Preserve migrations/env.py. ConfigParser interpolation treats
            # encoded URL '%' specially, so escape it only at this boundary.
            super().set_main_option(name, value.replace("%", "%%") if name == "sqlalchemy.url" else value)
    config = SafeConfig(str(BACKEND / "alembic.ini"), output_buffer=output)
    config.set_main_option("script_location", str(BACKEND / "migrations"))
    config.set_main_option("sqlalchemy.url", url.render_as_string(hide_password=False))
    from app.core.config import settings
    settings.database_url = url.render_as_string(hide_password=False)
    return config


def migration_plan(url):
    from alembic import command
    output = io.StringIO()
    config = alembic_config(url, output)
    command.upgrade(config, "head", sql=True)
    sql = output.getvalue()
    # Frozen seed migrations can embed defaults but must never contain a DSN
    # or credential. The plan is schema/seed SQL only, not a settings dump.
    # Migration 0020 emits random UUIDs/timestamps. Bind approval to the exact
    # source bytes and target/options, not freshly regenerated seed values.
    source = hashlib.sha256()
    for path in sorted((BACKEND / "migrations").rglob("*.py")):
        source.update(str(path.relative_to(BACKEND)).encode())
        source.update(path.read_bytes())
    source.update(Path(__file__).read_bytes())
    source.update(json.dumps(dict(url.query), sort_keys=True).encode())
    digest = hashlib.sha256((target_id(url) + source.hexdigest()).encode()).hexdigest()
    return sql, digest


def probe(url):
    from sqlalchemy import create_engine, text
    from sqlalchemy.pool import NullPool
    engine = create_engine(url, poolclass=NullPool)
    try:
        with engine.connect() as conn, conn.begin():
            conn.exec_driver_sql("SET TRANSACTION READ ONLY")
            conn.exec_driver_sql("SET LOCAL statement_timeout = 5000")
            version = conn.exec_driver_sql("SHOW server_version").scalar_one()
            search_path = conn.exec_driver_sql("SHOW search_path").scalar_one()
            extension = conn.execute(text("SELECT extversion,nspname FROM pg_extension JOIN pg_namespace ON pg_namespace.oid=extnamespace WHERE extname='postgis'")).first()
            if not extension:
                raise ValueError("PostGIS is missing; provision the dedicated schema before migrations")
            spatial = conn.exec_driver_sql("SELECT ST_SRID(ST_GeomFromText('POINT(31 30)',4326)), ST_Area(ST_GeomFromText('POLYGON((31 30,31.01 30,31.01 30.01,31 30.01,31 30))',4326)::geography)>0").first()
            has_version = conn.exec_driver_sql("SELECT to_regclass('public.alembic_version')").scalar_one()
            heads = list(conn.exec_driver_sql("SELECT version_num FROM public.alembic_version").scalars()) if has_version else []
            return {"target_id": target_id(url), "postgresql": version, "postgis": extension[0], "extension_schema": extension[1], "search_path": search_path, "srid": spatial[0], "geodesic_area_positive": spatial[1], "applied_heads": heads, "database_bytes": conn.exec_driver_sql("SELECT pg_database_size(current_database())").scalar_one()}
    finally:
        engine.dispose()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["plan", "probe", "upgrade"])
    parser.add_argument("--output", type=Path, help="SQL plan path, plan only")
    parser.add_argument("--approved-plan-sha256", default="")
    parser.add_argument("--owner-approved", action="store_true", help="Operator assertion of prior explicit owner approval, not approval by itself")
    parser.add_argument("--disposable", action="store_true", help="Only loopback croptwist_deploy_* database")
    args = parser.parse_args(argv)
    output_path = args.output.resolve() if args.output else None
    try:
        os.chdir(BACKEND)
        url = configured_url()
        if args.command == "probe":
            print(json.dumps(probe(url), indent=2))
            return 0
        sql, digest = migration_plan(url)
        if args.command == "plan":
            if output_path:
                output_path.write_text(sql, encoding="utf-8")
            else:
                print(sql)
            print(json.dumps({"plan_sha256": digest, "sql_sha256": hashlib.sha256(sql.encode()).hexdigest(), "target_id": target_id(url), "note": "Approval binds exact migration/tool source, connection options and target. SQL seed UUIDs/timestamps vary. Full base-to-head artifact; upgrade applies pending revisions only."}), file=sys.stderr)
            return 0
        if not args.approved_plan_sha256 or args.approved_plan_sha256 != digest:
            raise ValueError("Upgrade refused: reviewed plan digest missing or stale")
        if args.disposable:
            if not is_disposable(url):
                raise ValueError("--disposable requires a loopback croptwist_deploy_* target")
        elif not args.owner_approved:
            raise ValueError("Remote upgrade refused: obtain explicit owner approval first")
        # A digest and assertion are technical gates, not authority to apply a
        # destructive migration. Owner must review the full SQL and data impact.
        print(json.dumps(probe(url), indent=2))
        from alembic import command
        command.upgrade(alembic_config(url, io.StringIO()), "head")
        print(json.dumps(probe(url), indent=2))
        return 0
    except Exception:
        # Do not echo database exceptions: psycopg/SQLAlchemy can print DSNs,
        # bound parameters or tenant data. Local operator can inspect privately.
        print("Database operation failed/refused. Verify target, TLS/CA, PostGIS, plan digest and approval. No credentials are logged.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
