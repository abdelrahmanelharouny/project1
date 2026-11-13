"""Satellite acquisition orchestration (P04 Workstream C/D).

The service layer between the CMR STAC catalog and CropTwist's existing
ingestion pipeline:

- `discover_scenes`: STAC metadata-only discovery; discovered scenes are
  persisted idempotently on the `satellite_scenes` natural key
  (field, provider, scene_id) with acquisition_status='discovered'. Existing
  rows are NEVER overwritten or downgraded.
- `list_field_scenes`: paginated catalog listing with status filtering;
  legacy P2 rows (NULL status) surface as 'ready' via COALESCE semantics.
- `create_acquisitions`: groups scenes by HLS collection (one ingestion job
  per collection keeps result provenance unambiguous), creates idempotent
  ingestion jobs on the existing background-job infrastructure, and moves
  scenes to 'queued'. Ingestion then drives queued -> running -> ready |
  failed through the hooks in ingestion.service.
- `cancel_ingestion_job`: cancels a still-queued acquisition job (both the
  BackgroundJob row and the IngestionJob row) and returns its scenes to
  'discovered'. Running jobs are rejected honestly — in-process workers
  cannot be forcibly interrupted.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.errors import Conflict, NotFound, ProviderRequestError, ValidationFailed
from app.data_platform.ingestion.service import (
    set_scene_acquisition_status,
    start_ingestion_job,
    submit_ingestion_job,
)
from app.db.models import BackgroundJob, Field, IngestionJob
from app.db.models_p2 import SatelliteScene

logger = logging.getLogger("croptwist.acquisition")

PROVIDER_CODE = "nasa_hls"
ACQUISITION_STATUSES = ("discovered", "queued", "running", "ready", "failed")


# ------------------------------------------------------------------ discovery
def discover_scenes(
    db: Session,
    *,
    field: Field,
    geometry_geojson: dict[str, Any],
    start: datetime,
    end: datetime,
    max_cloud_cover: float | None = None,
    limit: int = 240,
) -> dict[str, Any]:
    """Run CMR STAC discovery for a field and persist discovered scenes.

    Metadata only — no scene assets are downloaded here. Returns the catalog
    outcome with per-scene payloads; provider errors propagate as structured
    CropTwist errors (502/503) after retries, never as fabricated results.
    """
    from app.data_platform.registry.provider_registry import get_provider_registry

    provider = get_provider_registry().get(PROVIDER_CODE)
    page_size = min(limit, settings.nasa_hls_search_page_size)
    max_pages = max(1, -(-min(limit, 500) // max(1, page_size)))
    records, warnings = provider.search_scenes(
        geometry_geojson=geometry_geojson,
        start=start,
        end=end,
        max_cloud_cover=max_cloud_cover,
        page_size=page_size,
        max_pages=min(max_pages, settings.nasa_hls_max_pages),
    )

    new = 0
    unchanged = 0
    now = datetime.now(UTC)
    persisted: list[SatelliteScene] = []
    for record in records:
        exists = db.scalar(
            select(SatelliteScene.id).where(
                SatelliteScene.field_id == field.id,
                SatelliteScene.provider_code == PROVIDER_CODE,
                SatelliteScene.scene_id == record.scene_id[:255],
            )
        )
        if exists is not None:
            unchanged += 1
            continue
        row = SatelliteScene(
            field_id=field.id,
            provider_code=PROVIDER_CODE,
            product_code=record.collection,
            scene_id=record.scene_id[:255],
            acquired_at=record.acquired_at,
            cloud_cover_pct=record.cloud_cover_pct,
            spatial_resolution_m=record.spatial_resolution_m,
            band_mapping=dict(record.band_mapping),
            asset_refs=dict(record.asset_refs),
            coverage_fraction=None,
            is_synthetic=False,
            processing_version=record.processing_version,
            metadata_json={
                "platform": record.platform,
                "collection_id": record.collection_id,
                "footprint_bbox": record.bbox,
                "provider_code": PROVIDER_CODE,
                "discovery_catalog": settings.nasa_hls_stac_base_url,
            },
            acquisition_status="discovered",
            acquisition_detail={},
            discovered_at=now,
            acquisition_updated_at=now,
        )
        db.add(row)
        persisted.append(row)
        new += 1
    db.commit()

    scenes_payload = [(_scene_row_payload(db, field.id, r.scene_id) or {}) for r in records]
    return {
        "field_id": str(field.id),
        "provider_code": PROVIDER_CODE,
        "catalog": {
            "base_url": settings.nasa_hls_stac_base_url,
            "collections": [
                settings.nasa_hls_l30_collection_id,
                settings.nasa_hls_s30_collection_id,
            ],
            "products": [r.collection for r in records],
        },
        "discovered": len(records),
        "new": new,
        "unchanged": unchanged,
        "scenes": scenes_payload,
        "warnings": warnings[:50],
    }


# ------------------------------------------------------------------- listing
def list_field_scenes(
    db: Session,
    *,
    field_id: Any,
    provider_code: str | None = None,
    status: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> dict[str, Any]:
    """Paginated scene catalog for a field with optional status filtering.

    `status` matches the COALESCED lifecycle status (legacy NULL rows count
    as 'ready' because the P2 path ingested on arrival).
    """
    if status is not None and status not in ACQUISITION_STATUSES:
        raise ValidationFailed(
            f"Unknown scene status '{status}'.",
            details=[{"field": "status", "reason": f"expected one of {ACQUISITION_STATUSES}"}],
        )
    conditions = [SatelliteScene.field_id == field_id]
    if provider_code:
        conditions.append(SatelliteScene.provider_code == provider_code)
    if status:
        conditions.append(
            func.coalesce(SatelliteScene.acquisition_status, "ready") == status
        )
    base = select(SatelliteScene).where(*conditions)
    total = db.scalar(
        select(func.count()).select_from(SatelliteScene).where(*conditions)
    ) or 0
    rows = db.scalars(
        base.order_by(SatelliteScene.acquired_at.desc(), SatelliteScene.scene_id)
        .offset(offset)
        .limit(limit)
    ).all()
    return {
        "field_id": str(field_id),
        "total": int(total),
        "limit": limit,
        "offset": offset,
        "scenes": [_scene_payload(row) for row in rows],
    }


def get_scene_row(db: Session, field_id: Any, scene_id: str) -> SatelliteScene | None:
    return db.scalar(
        select(SatelliteScene).where(
            SatelliteScene.field_id == field_id,
            SatelliteScene.provider_code == PROVIDER_CODE,
            SatelliteScene.scene_id == scene_id[:255],
        )
    )


# --------------------------------------------------------------- acquisitions
def create_acquisitions(
    db: Session,
    *,
    field: Field,
    scene_ids: list[str],
    variables: list[str],
    created_by: Any,
) -> dict[str, Any]:
    """Queue acquisition of specific discovered scenes (idempotent, bounded).

    - Scenes must exist (discovered first) — unknown ids are a 404.
    - Scenes already 'ready' are rejected (re-acquisition is a data-jobs
      concern, not a duplicate acquisition).
    - Scenes 'queued'/'running' are rejected — one lifecycle at a time.
    - Failed/discovered scenes are (re)queued; failed retries get a fresh
      job idempotency key so a previously failed job can never swallow a
      retry.
    - Scenes are grouped per HLS collection: one ingestion job per collection
      keeps the result-level provenance (product identity) unambiguous.
    """
    from app.data_platform.registry.provider_registry import get_provider_registry

    registry = get_provider_registry()
    provider = registry.get(PROVIDER_CODE)
    provider.validate_request(variables=variables, options={})

    unique_ids = list(dict.fromkeys(scene_ids))
    if len(unique_ids) > settings.nasa_hls_max_scenes_per_job:
        raise ValidationFailed(
            f"Too many scenes requested (limit {settings.nasa_hls_max_scenes_per_job}).",
            details=[{
                "field": "scene_ids",
                "reason": f"nasa_hls_max_scenes_per_job={settings.nasa_hls_max_scenes_per_job}",
            }],
        )
    rows: dict[str, SatelliteScene] = {}
    for scene_id in unique_ids:
        row = get_scene_row(db, field.id, scene_id)
        if row is None:
            raise NotFound(
                f"Scene '{scene_id}' has not been discovered for this field.",
                details=[{"field": "scene_ids", "reason": "run discovery first"}],
            )
        rows[scene_id] = row

    # Replay-first: an identical request while a job is still queued/running
    # returns the SAME job (double-submit safety) instead of a busy conflict.
    from app.db.models import IngestionJob as _IngestionJob

    def _find_active_job(group: list[SatelliteScene]) -> IngestionJob | None:
        key = _acquisition_idempotency_key(field.id, group[0].product_code, group)
        job = db.scalar(
            select(_IngestionJob).where(
                _IngestionJob.idempotency_key == key,
                _IngestionJob.field_id == field.id,
            )
        )
        if job is not None and job.status in ("queued", "running"):
            return job
        return None

    groups: dict[str, list[SatelliteScene]] = {}
    for r in rows.values():
        groups.setdefault(r.product_code, []).append(r)
    replayed: dict[str, IngestionJob] = {}
    for collection, group in groups.items():
        active = _find_active_job(group)
        if active is not None:
            replayed[collection] = active

    busy = [
        r.scene_id
        for r in rows.values()
        if (r.acquisition_status or "") in ("queued", "running")
        and (r.product_code not in replayed)
    ]
    if busy:
        raise Conflict(
            "Scenes already have an acquisition in flight.",
            details=[{"field": "scene_ids", "reason": f"in flight: {busy[:10]}"}],
        )

    ready = [r.scene_id for r in rows.values() if (r.acquisition_status or "ready") == "ready"]
    if ready:
        raise ValidationFailed(
            "Scenes already ingested cannot be re-acquired via the acquisition API.",
            details=[{"field": "scene_ids", "reason": f"ready: {ready[:10]}"}],
        )

    jobs: list[dict[str, Any]] = []
    queued_scenes: list[str] = []
    for collection in sorted({r.product_code for r in rows.values()}):
        group = [r for r in rows.values() if r.product_code == collection]
        group.sort(key=lambda r: r.acquired_at)
        replay_job = replayed.get(collection)
        if replay_job is not None:
            jobs.append(
                {
                    "job_id": str(replay_job.id),
                    "provider_code": replay_job.provider_code,
                    "product_code": collection,
                    "status": replay_job.status,
                    "scene_ids": [r.scene_id for r in group],
                    "status_url": f"/api/v1/jobs/{replay_job.id}",
                    "replayed": True,
                }
            )
            continue
        scene_records: dict[str, dict[str, Any]] = {}
        for r in group:
            asset_refs = dict(r.asset_refs or {})
            assets = {k: v for k, v in asset_refs.items() if k != "fmask"}
            scene_records[r.scene_id] = {
                "scene_id": r.scene_id,
                "collection": r.product_code,
                "acquired_at": r.acquired_at.isoformat() if r.acquired_at else None,
                "cloud_cover_pct": r.cloud_cover_pct,
                "platform": (r.metadata_json or {}).get("platform"),
                "processing_version": r.processing_version,
                "assets": assets,
            }
        start = group[0].acquired_at - timedelta(seconds=1)
        end = group[-1].acquired_at + timedelta(seconds=1)
        idempotency_key = _acquisition_idempotency_key(field.id, collection, group)
        job = start_ingestion_job(
            db,
            field=field,
            provider_code=PROVIDER_CODE,
            variables=list(variables),
            start=start,
            end=end,
            options={
                "scene_ids": [r.scene_id for r in group],
                "scene_records": scene_records,
            },
            idempotency_key=idempotency_key,
            created_by=created_by,
            execute=settings.job_workers <= 0,
        )
        if job.status == "failed":
            # A previously failed replay must never swallow a retry — create a
            # fresh job with a retry-salted key instead (uuid salt: two
            # retries can land in the same wall-clock second).
            import uuid as _uuid

            retry_key = f"{idempotency_key}:retry:{_uuid.uuid4().hex[:12]}"
            job = start_ingestion_job(
                db,
                field=field,
                provider_code=PROVIDER_CODE,
                variables=list(variables),
                start=start,
                end=end,
                options={
                    "scene_ids": [r.scene_id for r in group],
                    "scene_records": scene_records,
                },
                idempotency_key=retry_key,
                created_by=created_by,
                execute=settings.job_workers <= 0,
            )
        if job.status == "queued" and settings.job_workers > 0:
            submit_ingestion_job(job.id)
        job_scene_ids = [r.scene_id for r in group]
        if job.status == "queued":
            set_scene_acquisition_status(
                db, field.id, PROVIDER_CODE, job_scene_ids, "queued", {"job_id": str(job.id)}
            )
            queued_scenes.extend(job_scene_ids)
        db.commit()
        jobs.append(
            {
                "job_id": str(job.id),
                "provider_code": job.provider_code,
                "product_code": collection,
                "status": job.status,
                "scene_ids": job_scene_ids,
                "status_url": f"/api/v1/jobs/{job.id}",
            }
        )
    db.commit()
    logger.info(
        "satellite acquisition requested",
        extra={
            "field_id": str(field.id),
            "jobs": len(jobs),
            "queued_scenes": len(queued_scenes),
        },
    )
    return {
        "field_id": str(field.id),
        "provider_code": PROVIDER_CODE,
        "jobs": jobs,
        "queued_scenes": queued_scenes,
        "warnings": [],
    }


def _acquisition_idempotency_key(
    field_id: Any, collection: str, group: list[SatelliteScene]
) -> str:
    import hashlib

    digest = hashlib.sha256(
        "|".join(sorted(r.scene_id for r in group)).encode("utf-8")
    ).hexdigest()[:16]
    return f"nasa_hls:{field_id}:{collection}:{digest}"


# --------------------------------------------------------------------- cancel
def cancel_ingestion_job(db: Session, *, job: IngestionJob) -> dict[str, Any]:
    """Cancel a still-queued ingestion job and return its scenes to discovery.

    Only queued jobs can be cancelled: once a worker has started, in-process
    execution cannot be safely interrupted (documented limitation of the
    single-process executor — the same trade-off as app/core/jobs.py).
    """
    if job.status != "queued":
        raise Conflict(
            f"Job {job.id} is {job.status}; only queued acquisitions can be cancelled.",
            details=[{"field": "job_id", "reason": f"status={job.status}"}],
        )
    bg = db.scalar(
        select(BackgroundJob).where(
            BackgroundJob.ref_kind == "ingestion",
            BackgroundJob.ref_id == job.id,
            BackgroundJob.status == "queued",
        )
    )
    now = datetime.now(UTC)
    if bg is not None:
        bg.status = "cancelled"
        bg.finished_at = now
    job.status = "cancelled"
    job.completed_at = now
    options = (job.request_parameters or {}).get("options") or {}
    scene_ids = [str(s) for s in options.get("scene_ids") or []]
    if scene_ids:
        set_scene_acquisition_status(
            db,
            job.field_id,
            job.provider_code,
            scene_ids,
            "discovered",
            {"cancelled": True, "job_id": str(job.id)},
        )
    db.commit()
    logger.info("satellite acquisition cancelled", extra={"job_id": str(job.id)})
    return {
        "job_id": str(job.id),
        "status": job.status,
        "scenes_released": scene_ids,
    }


# ---------------------------------------------------------------- serializers
def _scene_payload(row: SatelliteScene) -> dict[str, Any]:
    metadata = row.metadata_json or {}
    return {
        "id": str(row.id),
        "provider_code": row.provider_code,
        "product_code": row.product_code,
        "scene_id": row.scene_id,
        "acquired_at": row.acquired_at.isoformat() if row.acquired_at else None,
        "cloud_cover_pct": row.cloud_cover_pct,
        "spatial_resolution_m": row.spatial_resolution_m,
        "platform": metadata.get("platform"),
        "coverage_fraction": row.coverage_fraction,
        "acquisition_status": row.acquisition_status or "ready",
        "acquisition_detail": row.acquisition_detail or {},
        "is_synthetic": row.is_synthetic,
        "processing_version": row.processing_version,
        "asset_refs": row.asset_refs,
        "band_mapping": row.band_mapping,
        "discovered_at": row.discovered_at.isoformat() if row.discovered_at else None,
        "acquisition_updated_at": (
            row.acquisition_updated_at.isoformat() if row.acquisition_updated_at else None
        ),
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def _scene_row_payload(db: Session, field_id: Any, scene_id: str) -> dict[str, Any] | None:
    row = get_scene_row(db, field_id, scene_id)
    return _scene_payload(row) if row is not None else None


def ensure_provider_available() -> None:
    """Fail fast with a clear error when the provider is not registered."""
    from app.data_platform.registry.provider_registry import get_provider_registry

    get_provider_registry().get(PROVIDER_CODE)


def validate_acquisition_request(
    *, start: datetime, end: datetime, max_cloud_cover: float | None
) -> None:
    """Shared request validation for discovery calls (date range + cloud)."""
    if start >= end:
        raise ValidationFailed(
            "Discovery window must have start before end.",
            details=[{"field": "start_date", "reason": "start >= end"}],
        )
    span_days = (end - start).total_seconds() / 86400
    if span_days > settings.nasa_hls_max_discovery_span_days:
        raise ValidationFailed(
            f"Discovery window exceeds {settings.nasa_hls_max_discovery_span_days} days.",
            details=[{
                "field": "end_date",
                "reason": f"span {int(span_days)}d > {settings.nasa_hls_max_discovery_span_days}d",
            }],
        )
    if end > datetime.now(UTC) + timedelta(days=1):
        raise ValidationFailed(
            "Discovery window extends into the future.",
            details=[{"field": "end_date", "reason": "end beyond now+1d"}],
        )
    if max_cloud_cover is not None and not (0 <= max_cloud_cover <= 100):
        raise ProviderRequestError(
            "max_cloud_cover must be within [0, 100].",
            details=[{"field": "max_cloud_cover", "reason": f"got {max_cloud_cover}"}],
        )
