"""Ensure the PostgreSQL cluster is running and the fieldshift DB exists.

Sandbox-specific helper: the conda-forge PostgreSQL cluster in db/pgdata is
started on demand. In production, use a managed PostgreSQL + PostGIS service
instead (see docs/architecture/deployment.md).
"""

import os
import subprocess
import sys

PGDATA = os.environ.get("FIELDSHIFT_DB_PGDATA", "/home/z/my-project/db/pgdata")
PGPORT = os.environ.get("FIELDSHIFT_DB_PORT", "5433")
PGSOCKDIR = os.environ.get("FIELDSHIFT_DB_SOCKET_DIR", "/tmp")
PGUSER = "postgres"
DBNAME = os.environ.get("FIELDSHIFT_DB_NAME", "fieldshift")
PGBIN = os.path.join(os.path.dirname(PGDATA), "pgenv", "bin")


def _run(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env["PATH"] = PGBIN + os.pathsep + env.get("PATH", "")
    return subprocess.run(cmd, env=env, capture_output=True, text=True, **kw)


def ensure_postgres() -> None:
    status = _run(["pg_ctl", "-D", PGDATA, "status"])
    if status.returncode == 0:
        return
    print(f"[ensure_db] starting postgres on port {PGPORT} ...", flush=True)
    start = _run([
        "pg_ctl", "-D", PGDATA,
        "-o", f"-p {PGPORT} -c listen_addresses=127.0.0.1 -c unix_socket_directories={PGSOCKDIR}",
        "-l", os.path.join(os.path.dirname(PGDATA), "pg.log"),
        "start",
    ], timeout=90)
    if start.returncode != 0:
        # Might already be running from another process; verify with ping.
        ping = _run(["pg_isready", "-h", "127.0.0.1", "-p", PGPORT, "-U", PGUSER], timeout=30)
        if ping.returncode != 0:
            sys.stderr.write(start.stderr)
            raise RuntimeError("Failed to start PostgreSQL cluster.")


def ensure_database() -> None:
    exists = _run(
        ["psql", "-h", "127.0.0.1", "-p", PGPORT, "-U", PGUSER, "-d", "postgres", "-tAc",
         f"SELECT 1 FROM pg_database WHERE datname='{DBNAME}'"],
        timeout=30,
    )
    if exists.stdout.strip() != "1":
        print(f"[ensure_db] creating database {DBNAME} ...", flush=True)
        created = _run(
            ["psql", "-h", "127.0.0.1", "-p", PGPORT, "-U", PGUSER, "-d", "postgres",
             "-c", f"CREATE DATABASE {DBNAME} ENCODING 'UTF8'"],
            timeout=60,
        )
        if created.returncode != 0:
            sys.stderr.write(created.stderr)
            raise RuntimeError("Failed to create database.")
    # PostGIS must be present in the target DB (idempotent).
    ext = _run(
        ["psql", "-h", "127.0.0.1", "-p", PGPORT, "-U", PGUSER, "-d", DBNAME, "-tAc",
         "CREATE EXTENSION IF NOT EXISTS postgis"],
        timeout=120,
    )
    if ext.returncode != 0:
        sys.stderr.write(ext.stderr)
        raise RuntimeError("Failed to ensure PostGIS extension.")


if __name__ == "__main__":
    ensure_postgres()
    ensure_database()
    print(f"[ensure_db] postgresql://127.0.0.1:{PGPORT}/{DBNAME} ready (postgis enabled)")
