"""CropTwist API application factory (FastAPI, Master §9-10)."""

import logging
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from app import __version__
from app.api.v1.router import api_router
from app.core.config import settings
from app.core.errors import install_error_handlers
from app.core.logging import configure_logging, request_id_var

logger = logging.getLogger("croptwist.main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    if settings.dev_mode:
        # Auth hardening P0-2: surface insecure sandbox configuration loudly.
        logger.warning(
            "DEV_MODE enabled — /dev endpoints and auto-verified registration are exposed."
        )
    # Async jobs (P0-3): start the in-process worker pool (no-op when
    # settings.job_workers <= 0) with crash-orphan recovery.
    from app.core import jobs as background_jobs

    started = background_jobs.start_workers()
    # Ensure the source/product registry rows exist (idempotent).
    from app.core.database import SessionLocal
    from app.data_platform.registry.seed_sources import seed_data_registry

    db = SessionLocal()
    try:
        seed_data_registry(db)
        # Milestone 5: bootstrap the bundled seed knowledge pack (idempotent).
        from app.knowledge.import_service import seed_default_packs

        seed_default_packs(db)
        # P3 §4.1: seed the commercial plan catalog (idempotent, insert-
        # missing-only — never clobbers operator adjustments).
        from app.billing.catalog import ensure_plan_catalog

        ensure_plan_catalog(db)
        db.commit()
    finally:
        db.close()
    # P3 W5/W6: periodic maintenance scheduler (report queue, webhook
    # retries, subscription expiry, retention sweeps).
    from app.core import scheduler as maintenance_scheduler

    maintenance_scheduler.start_scheduler()
    yield
    maintenance_scheduler.stop_scheduler()
    background_jobs.shutdown_workers()


def create_app() -> FastAPI:
    app = FastAPI(
        title="CropTwist API",
        version=__version__,
        description=(
            "CropTwist agricultural decision-support platform — first vertical slice. "
            "Farm/field management with PostGIS geometry, canonical observation contracts, "
            "a deterministic synthetic provider, and the Field Data Passport. "
            "NASA connectors are intentionally NOT implemented (future adapter)."
        ),
        lifespan=lifespan,
    )

    origins = [o for o in settings.cors_allow_origins.split(",") if o]
    if origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    @app.middleware("http")
    async def request_id_middleware(request: Request, call_next):
        request_id = request.headers.get("x-request-id") or str(uuid.uuid4())
        request.state.request_id = request_id
        token = request_id_var.set(request_id)
        try:
            response = await call_next(request)
        finally:
            request_id_var.reset(token)
        response.headers["x-request-id"] = request_id
        return response

    install_error_handlers(app)
    app.include_router(api_router)
    return app


app = create_app()
