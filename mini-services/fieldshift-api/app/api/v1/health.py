"""Health and readiness endpoints (Master §51)."""

from datetime import UTC, datetime

from fastapi import APIRouter, Response, status
from sqlalchemy import text

from app import __version__
from app.core.config import settings
from app.core.database import check_database

router = APIRouter(prefix="/health", tags=["health"])


@router.get("")
def health() -> dict:
    return {
        "status": "ok",
        "service": settings.service_name,
        "version": __version__,
        "environment": settings.environment,
        "time": datetime.now(UTC).isoformat(),
    }


@router.get("/ready")
def readiness(response: Response) -> dict:
    try:
        info = check_database()
        if not info.get("postgis_version"):
            response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
            return {"status": "unavailable", "reason": "PostGIS unavailable"}
        if not info.get("alembic_ok"):
            response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
            return {"status": "unavailable", "reason": "database schema is not ready"}
        return {"status": "ok", **info}
    except Exception:  # noqa: BLE001 — readiness must not leak internals
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        # Keep connection strings, hostnames, and driver details out of the
        # public probe. The exception is available to normal application logs.
        return {"status": "unavailable", "reason": "database unavailable"}
