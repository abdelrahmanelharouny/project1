"""SQLAlchemy engine/session management (sync engine; FastAPI runs sync endpoints in a threadpool)."""

from collections.abc import Generator

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings

engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,
    pool_recycle=300,
    pool_size=5,
    max_overflow=5,
    future=True,
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency yielding a scoped session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def check_database() -> dict:
    """Health probe: connectivity + PostGIS availability."""
    with engine.connect() as conn:
        version = conn.execute(text("SHOW server_version")).scalar_one()
        row = conn.execute(
            text("SELECT extversion FROM pg_extension WHERE extname = 'postgis'")
        ).first()
        postgis_version = row[0] if row else None
        return {
            "database": "ok",
            "server_version": version,
            "postgis_version": postgis_version,
        }
