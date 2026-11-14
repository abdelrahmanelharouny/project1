"""SQLAlchemy engine/session management (sync engine; FastAPI runs sync endpoints in a threadpool)."""

from collections.abc import Generator
from functools import lru_cache
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings


def get_database_connect_args(settings_obj: Any = settings) -> dict[str, Any]:
    """Return safe libpq arguments shared by the API and deployment tooling.

    The values are deliberately separate from the URL so a deployment wrapper
    can apply the same SSL, connection-timeout, and search-path policy when it
    invokes Alembic.  ``database_search_path`` has already been validated by
    :class:`Settings`; this function never interpolates untrusted SQL.
    """
    if not str(settings_obj.database_url).lower().startswith("postgresql"):
        return {}

    args: dict[str, Any] = {}
    timeout = int(settings_obj.database_connect_timeout_seconds)
    if timeout > 0:
        args["connect_timeout"] = timeout
    sslmode = str(settings_obj.database_sslmode or "").strip()
    if sslmode:
        args["sslmode"] = sslmode
    sslrootcert = str(settings_obj.database_sslrootcert or "").strip()
    if sslrootcert:
        args["sslrootcert"] = sslrootcert
    search_path = getattr(settings_obj, "search_path_list", None)
    if search_path:
        args["options"] = "-csearch_path=" + ",".join(search_path)
    return args


_engine_kwargs: dict[str, Any] = {
    "pool_pre_ping": True,
    "pool_recycle": settings.database_pool_recycle_seconds,
    "future": True,
}
if str(settings.database_url).lower().startswith("postgresql"):
    _engine_kwargs.update(
        {
            "pool_size": settings.database_pool_size,
            "max_overflow": settings.database_max_overflow,
            "pool_timeout": settings.database_pool_timeout_seconds,
            "connect_args": get_database_connect_args(),
        }
    )

engine = create_engine(settings.database_url, **_engine_kwargs)

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency yielding a scoped session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@lru_cache(maxsize=1)
def expected_alembic_heads() -> tuple[str, ...]:
    """Load migration heads from the checked-in migration graph.

    This is read-only: readiness reports drift but never upgrades or stamps a
    database.  Keeping this lookup here avoids making the health router know
    the repository layout beyond this backend package.
    """
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    service_root = Path(__file__).resolve().parents[2]
    config = Config(str(service_root / "alembic.ini"))
    config.set_main_option("script_location", str(service_root / "migrations"))
    return tuple(sorted(ScriptDirectory.from_config(config).get_heads()))


def check_database() -> dict[str, Any]:
    """Bounded health probe: SELECT 1, PostGIS, and Alembic head parity."""
    timeout_ms = max(1, int(settings.database_health_timeout_seconds * 1000))
    expected_heads = expected_alembic_heads()
    with engine.connect() as conn:
        # SET LOCAL is scoped to this transaction and prevents a readiness
        # probe from leaving a pooled connection with a surprising timeout.
        with conn.begin():
            conn.exec_driver_sql(f"SET LOCAL statement_timeout = {timeout_ms}")
            conn.execute(text("SELECT 1")).scalar_one()
            version = conn.execute(text("SHOW server_version")).scalar_one()
            postgis_version = conn.execute(text("SELECT PostGIS_Lib_Version()")).scalar_one_or_none()
            applied_heads = tuple(
                row[0]
                for row in conn.execute(
                    text("SELECT version_num FROM alembic_version ORDER BY version_num")
                ).all()
            )
    migrations_ok = applied_heads == expected_heads
    migration_info = {
        "ok": migrations_ok,
        "expected_heads": list(expected_heads),
        "applied_heads": list(applied_heads),
    }
    return {
        "database": "ok",
        "server_version": version,
        "postgis_version": postgis_version,
        "alembic": migration_info,
        "alembic_ok": migrations_ok,
    }
