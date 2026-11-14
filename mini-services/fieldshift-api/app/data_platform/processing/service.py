"""Satellite preprocessing orchestration (P05 Workstreams B+C).

Turns cataloged NASA HLS scenes (`satellite_scenes`, acquisition_status
'ready') into derived index products:

    validate scene -> windowed COG read (CRS-correct) -> scale + Fmask mask
    -> per-pixel indices -> zonal stats -> COG + preview PNG into object
    storage -> raster_assets rows + honest observation upsert.

Job model (Workstream B):

- Domain row `raster_processing_jobs` + companion `background_jobs` row
  (kind='raster_processing', ref_id = raster_processing_job.id). The
  executor rebuilds everything from the persisted rows — API requests only
  enqueue/inspect; workers do all raster work (independently deployable via
  `python -m app.worker`).
- Idempotency layers:
  1. one ACTIVE job per field, scene, processing_version, and index set —
     the field-scoped digest fits the existing partial unique index, and
     same-field re-submission replays the same job;
  2. natural-key uniqueness on `raster_assets` — a fully processed
     scene/version is skipped, never duplicated;
  3. observation natural key with honest upgrade semantics — a computed
     value never silently duplicates or overwrites an existing valid
     observation (missing rows are upgraded; supersession only when the
     processing version changes, with the full chain recorded).
- Restart recovery: jobs re-discovered 'queued' after a restart are replayed
  via `register_kind`; stale 'running' work is marked failed by the core
  executor (never half-replayed). All writes are single-transaction at the
  end of processing, so a crash mid-derivation leaves no partial products.
"""

from __future__ import annotations

import hashlib
import logging
import re
import tempfile
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import func
from sqlalchemy import or_ as sa_or
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.models import BackgroundJob, Field, Observation
from app.db.models_p2 import (
    RasterAsset,
    RasterProcessingJob,
    SatelliteScene,
)
from app.geospatial import preprocessing as pre
from app.geospatial.objectstore import (
    KeyConflictError,
    get_raster_storage,
    raster_key,
)

logger = logging.getLogger("croptwist.processing")

PROCESSING_JOB_KIND = "raster_processing"
PROVIDER_CODE = "nasa_hls"
# The pipeline processes REAL nasa_hls scenes and — explicitly labeled —
# fixture_demo synthetic scenes (demo/verification only; observations carry
# evidence_class=synthetic_test_data and is_synthetic=true so they can never
# pass as satellite evidence). Any other provider is refused.
FIXTURE_PROVIDER_CODE = "fixture_demo"
PROCESSING_VERSION = settings.raster_processing_default_version
MAP_SUPPORTED_INDICES = ("ndvi", "evi", "ndmi", "ndwi", "bsi")
_replay_registered = False


class ProcessingRequestError(Exception):
    """Invalid processing request (400-class)."""


class SceneNotProcessableError(Exception):
    """Scene cannot be processed (validation rejection)."""


class ProcessingOwnershipLostError(RuntimeError):
    """The raster executor no longer holds its persisted background-job fence."""


def _safe_processing_error(exc: BaseException) -> str:
    """Keep GIS/storage failures useful without exposing paths or credentials."""
    message = " ".join(str(exc).split())[:2000]
    message = re.sub(r"https?://[^\s)]+", "<redacted-url>", message)
    message = re.sub(
        r"(?i)(password|secret|token|access[_ -]?key|authorization)\s*[:=]\s*[^\s,;]+",
        r"\1=<redacted>",
        message,
    )
    message = re.sub(
        r"(?<![\w.])/(?:home|tmp|var|mnt|workspace|app|srv|run)/[^\s)]+",
        "<redacted-path>",
        message,
    )
    return f"{type(exc).__name__}: {message}"[:2000]


def _assert_processing_job_owner(db: Session, rp: RasterProcessingJob) -> None:
    """Lock and validate the live owner row before raster DB or artifact writes.

    The lock serializes this transaction against lease recovery/takeover. The
    queued/unowned branch is limited to legacy synchronous invocations (used
    by local/dev callers); actual background workers always carry core context.
    """
    if rp.background_job_id is None:
        raise ProcessingOwnershipLostError("raster job has no background ownership row")

    from app.core.jobs import current_job_execution

    execution = current_job_execution()
    if execution is None:
        # Keep explicit synchronous invocations usable only before any worker
        # has claimed the queued row and in-process workers are disabled. A
        # running/expired/replayed job fails closed.
        if settings.job_workers > 0 or settings.job_queue_only:
            raise ProcessingOwnershipLostError("raster executor has no active worker context")
        queued = db.scalar(
            select(BackgroundJob.id)
            .where(
                BackgroundJob.id == rp.background_job_id,
                BackgroundJob.status == "queued",
                BackgroundJob.owner_id.is_(None),
                BackgroundJob.lease_expires_at.is_(None),
            )
            .with_for_update()
        )
        if queued is not None:
            return
        raise ProcessingOwnershipLostError("raster executor has no active worker context")

    job_id, owner_id, fencing_token = execution
    if job_id != rp.background_job_id:
        raise ProcessingOwnershipLostError("executor context belongs to a different job")
    current = db.scalar(
        select(BackgroundJob.id)
        .where(
            BackgroundJob.id == rp.background_job_id,
            BackgroundJob.status == "running",
            BackgroundJob.owner_id == owner_id,
            BackgroundJob.fencing_token == fencing_token,
            BackgroundJob.lease_expires_at > func.clock_timestamp(),
        )
        .with_for_update()
    )
    if current is None:
        raise ProcessingOwnershipLostError(
            "raster owner, fencing generation, or lease is no longer current"
        )


def indices_digest(indices: list[str], *, field_id: uuid.UUID) -> str:
    """Digest an index set in its field scope.

    The existing partial unique index does not include ``field_id``. Including
    it in this stable digest lets distinct fields process the same external
    scene independently without changing the schema or migration history.
    """
    canonical_indices = "|".join(sorted(set(indices)))
    scoped_request = f"{field_id}\0{canonical_indices}"
    return hashlib.sha256(scoped_request.encode("utf-8")).hexdigest()[:32]


def _preferred_processing_scene(scenes: list[SatelliteScene]) -> SatelliteScene | None:
    """Prefer the supported provider when external scene IDs collide.

    The natural key includes provider_code, while processing requests contain
    only scene_id. NASA HLS is the production processor; falling back to the
    first row when it is absent preserves the existing unsupported-provider
    and demo-fixture handling.
    """
    return next(
        (scene for scene in scenes if scene.provider_code == PROVIDER_CODE),
        scenes[0] if scenes else None,
    )


# ----------------------------------------------------------------- create
def create_processing_jobs(
    db: Session,
    *,
    field: Field,
    scene_ids: list[str],
    indices: list[str],
    processing_version: str = PROCESSING_VERSION,
    created_by: uuid.UUID | None = None,
) -> dict[str, Any]:
    """Enqueue one preprocessing job per scene (202 pattern).

    - Scenes must belong to the field, be cataloged for the real NASA HLS
      provider (`is_synthetic=False`), be acquisition-'ready' and carry band
      asset refs.
    - Active duplicates replay the SAME job (replay-safe double submit).
    - Each scene/version only queues requested indices not already stored or
      covered by an active job; already-complete requests are skipped.
    """
    from app.core.config import settings as cfg
    global _replay_registered
    from app.core import jobs as background_jobs
    from app.core.jobs import submit

    if not _replay_registered:
        background_jobs.register_kind(PROCESSING_JOB_KIND, replay_processing_job)
        _replay_registered = True
    from app.data_platform.providers.nasa_hls import registry_info as hls

    if not scene_ids:
        raise ProcessingRequestError("scene_ids must not be empty")
    if len(scene_ids) > cfg.nasa_hls_max_scenes_per_job:
        raise ProcessingRequestError(
            f"at most {cfg.nasa_hls_max_scenes_per_job} scenes per processing batch"
        )
    clean_indices = list(dict.fromkeys(i.strip().lower() for i in indices if i and i.strip()))
    if not clean_indices:
        raise ProcessingRequestError("indices must not be empty")
    unknown = [i for i in clean_indices if i not in pre._SUPPORTED_INDICES]
    if unknown:
        raise ProcessingRequestError(f"unsupported index code(s): {', '.join(unknown)}")

    scene_rows = db.scalars(
        select(SatelliteScene).where(
            SatelliteScene.field_id == field.id,
            SatelliteScene.scene_id.in_(scene_ids),
        )
    ).all()
    scenes_by_id: dict[str, list[SatelliteScene]] = {}
    for scene in scene_rows:
        scenes_by_id.setdefault(scene.scene_id, []).append(scene)
    by_id = {
        scene_id: preferred
        for scene_id, candidates in scenes_by_id.items()
        if (preferred := _preferred_processing_scene(candidates)) is not None
    }
    missing = [sid for sid in scene_ids if sid not in by_id]
    if missing:
        raise ProcessingRequestError(f"unknown scene(s) for this field: {', '.join(missing[:5])}")

    jobs: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []
    warnings: list[str] = []
    for sid in scene_ids:
        scene = by_id[sid]
        if scene.is_synthetic:
            if scene.provider_code != FIXTURE_PROVIDER_CODE or not (
                scene.metadata_json or {}
            ).get("demo_fixture"):
                skipped.append(
                    {"scene_id": sid, "reason": "synthetic scene; not processable"}
                )
                continue
        elif scene.provider_code != PROVIDER_CODE:
            skipped.append(
                {"scene_id": sid, "reason": f"provider '{scene.provider_code}' not supported"}
            )
            continue
        status = scene.acquisition_status or "ready"  # legacy rows are ready
        if status != "ready":
            skipped.append({"scene_id": sid, "reason": f"acquisition status is '{status}'"})
            continue
        if not (scene.asset_refs or {}):
            skipped.append({"scene_id": sid, "reason": "no band assets recorded"})
            continue

        requested = set(clean_indices)
        existing_indices = set(
            db.scalars(
                select(RasterAsset.index_code).where(
                    RasterAsset.field_id == field.id,
                    RasterAsset.scene_id == sid,
                    RasterAsset.processing_version == processing_version,
                    RasterAsset.asset_kind == "derived",
                )
            ).all()
        )
        pending = requested - existing_indices
        # (1) already-complete request -> honest idempotent skip
        if not pending:
            skipped.append(
                {
                    "scene_id": sid,
                    "reason": f"already processed at version {processing_version}",
                }
            )
            continue

        # Active work is scoped to the same field, scene and processing version.
        active = db.scalars(
            select(RasterProcessingJob).where(
                RasterProcessingJob.field_id == field.id,
                RasterProcessingJob.scene_id == sid,
                RasterProcessingJob.processing_version == processing_version,
                RasterProcessingJob.status.in_(("queued", "running")),
            )
        ).all()
        # Replay a matching full request, or an active job that exactly covers
        # the still-unmaterialized portion of this request.
        exact_active = next(
            (
                job
                for job in active
                if set(job.indices or []) in (requested, pending)
            ),
            None,
        )
        if exact_active is not None:
            jobs.append(_job_payload(exact_active, replayed=True))
            continue

        active_indices = {index for job in active for index in (job.indices or [])}
        missing_indices = [
            index for index in clean_indices if index in pending and index not in active_indices
        ]
        if not missing_indices:
            # The pending request is covered by one or more active jobs. Return
            # those jobs as replays instead of creating an empty/duplicate job.
            uncovered = set(pending)
            for job in active:
                covered_here = uncovered.intersection(job.indices or [])
                if covered_here:
                    jobs.append(_job_payload(job, replayed=True))
                    uncovered.difference_update(covered_here)
                if not uncovered:
                    break
            continue

        digest = indices_digest(missing_indices, field_id=field.id)
        rp = RasterProcessingJob(
            field_id=field.id,
            scene_id=sid,
            product_code=scene.product_code,
            indices=list(missing_indices),
            indices_digest=digest,
            processing_version=processing_version,
            status="queued",
            warnings=[],
            created_by=created_by,
        )
        db.add(rp)
        db.flush()
        bg = submit(
            PROCESSING_JOB_KIND,
            lambda bg_id, progress, rp_id=rp.id: execute_processing_job(rp_id, progress),
            db=db,
            ref_kind=PROCESSING_JOB_KIND,
            ref_id=rp.id,
            label=f"Preprocess HLS scene {sid} ({','.join(missing_indices)})",
            created_by=created_by,
        )
        rp.background_job_id = bg.id
        db.flush()
        jobs.append(_job_payload(rp))
        warnings.extend([])

    db.commit()
    if skipped:
        warnings.extend(f"{s['scene_id']}: {s['reason']}" for s in skipped)
    return {
        "field_id": str(field.id),
        "provider_code": PROVIDER_CODE,
        "indices": clean_indices,
        "processing_version": processing_version,
        "jobs": jobs,
        "skipped": skipped,
        "queued_scenes": sum(1 for j in jobs if not j.get("replayed")),
        "warnings": warnings[:50],
    }


def _job_payload(rp: RasterProcessingJob, *, replayed: bool = False) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "job_id": str(rp.id),
        "background_job_id": str(rp.background_job_id) if rp.background_job_id else None,
        "scene_id": rp.scene_id,
        "product_code": rp.product_code,
        "indices": list(rp.indices),
        "processing_version": rp.processing_version,
        "status": rp.status,
        "status_url": f"/api/v1/jobs/background/{rp.background_job_id}"
        if rp.background_job_id
        else None,
    }
    if replayed:
        payload["replayed"] = True
    return payload


# ---------------------------------------------------------------- execute
def execute_processing_job(rp_job_id: uuid.UUID, progress: Any) -> None:
    """Worker entrypoint for one preprocessing job (own session)."""
    from app.core.database import SessionLocal

    with SessionLocal() as db:
        rp = db.get(RasterProcessingJob, rp_job_id)
        if rp is None or rp.status not in ("queued",):
            return  # cancelled/unknown/duplicate — do not execute
        try:
            _run_processing(db, rp, progress)
        except ProcessingOwnershipLostError:
            db.rollback()
            logger.info(
                "raster executor stopped after ownership loss",
                extra={"job_id": str(rp_job_id)},
            )
        except Exception as exc:
            db.rollback()
            rp = db.get(RasterProcessingJob, rp_job_id)
            if rp is None:
                return
            _assert_processing_job_owner(db, rp)
            rp.status = "failed"
            safe_error = _safe_processing_error(exc)
            rp.error = safe_error
            rp.finished_at = datetime.now(UTC)
            db.add(rp)
            if rp.background_job_id:
                bg = db.get(BackgroundJob, rp.background_job_id)
                if bg is not None and bg.status == "running":
                    bg.status = "failed"
                    bg.error = safe_error
                    db.add(bg)
            db.commit()
            logger.warning(
                "raster processing failed",
                extra={"job_id": str(rp_job_id), "error": safe_error[:500]},
            )


def _run_processing(db: Session, rp: RasterProcessingJob, progress: Any) -> None:
    _assert_processing_job_owner(db, rp)
    rp.status = "running"
    rp.started_at = datetime.now(UTC)
    rp.progress = 5
    rp.stage = "loading scene record"
    db.add(rp)
    if rp.background_job_id:
        bg = db.get(BackgroundJob, rp.background_job_id)
        if bg is not None:
            bg.status = "running"
            bg.started_at = datetime.now(UTC)
            db.add(bg)
    db.commit()

    def _prog(pct: int, stage: str) -> None:
        _assert_processing_job_owner(db, rp)
        rp.progress = max(0, min(int(pct), 100))
        rp.stage = stage[:200]
        db.add(rp)
        db.commit()
        try:
            if progress:
                progress(rp.progress, rp.stage)
        except Exception:  # noqa: BLE001 — progress is best-effort
            pass

    field = db.get(Field, rp.field_id)
    scene_rows = db.scalars(
        select(SatelliteScene).where(
            SatelliteScene.field_id == rp.field_id, SatelliteScene.scene_id == rp.scene_id
        )
    ).all()
    scene = _preferred_processing_scene(scene_rows)
    if field is None or scene is None:
        raise SceneNotProcessableError("field or scene row missing")

    geometry_geojson = _field_geometry(db, field.id)
    boundary_version = _field_boundary_version(db, field.id)

    scene_record = {
        "scene_id": scene.scene_id,
        "assets": dict(scene.asset_refs or {}),
        "band_mapping": dict(scene.band_mapping or {}),
        "acquired_at": scene.acquired_at.isoformat() if scene.acquired_at else None,
        "cloud_cover_pct": scene.cloud_cover_pct,
        "platform": (scene.metadata_json or {}).get("platform"),
        "collection_id": (scene.metadata_json or {}).get("collection_id"),
        "collection": scene.product_code,
        "processing_version": scene.processing_version or "2.0",
        "resolution_m": scene.spatial_resolution_m,
    }

    _prog(10, "validating scene inputs")
    surfaces = pre.required_surfaces_for_indices(list(rp.indices))
    validation = pre.validate_scene_for_processing(
        scene_record=scene_record,
        required_surfaces=surfaces,
        indices=list(rp.indices),
        processing_version=rp.processing_version,
    )
    if not validation.ok:
        raise SceneNotProcessableError("; ".join(validation.reasons))
    all_warnings = list(validation.warnings)

    _prog(20, "reading scene window")
    from app.data_platform.providers.nasa_hls.provider import (
        NasaHlsProvider,
        _gdal_env_options,
    )

    provider = NasaHlsProvider()
    gdal_env = _gdal_env_options(provider._earthdata_auth())
    reading = pre.read_scene_window(
        assets=scene_record["assets"],
        surfaces=surfaces,
        geometry_geojson=geometry_geojson,
        gdal_env=gdal_env,
        max_window_mb=settings.raster_max_field_window_mb,
    )

    _prog(45, "deriving index products")
    from app.vegetation.indices import INDEX_FORMULAS

    from app.data_platform.providers.nasa_hls.registry_info import (
        FMASK_EXCLUDE_MASK,
        HLS_REFLECTANCE_SCALE,
        PRODUCT_VERSION,
    )

    products, pipeline_provenance = pre.derive_index_products(
        reading=reading,
        geometry_geojson=geometry_geojson,
        indices=list(rp.indices),
        reflectance_scale=HLS_REFLECTANCE_SCALE,
        fmask_exclude_mask=FMASK_EXCLUDE_MASK,
    )

    _prog(65, "writing derived products to object storage")
    storage = get_raster_storage()
    org_id = _org_id_of_field(db, field)
    stored: list[dict[str, Any]] = []
    for product in products:
        asset_name = f"{rp.scene_id}_{product.index_code}.tif"
        key = raster_key(
            org_id=org_id,
            field_id=field.id,
            kind="derived",
            provider_code=scene.provider_code,
            scene_id=rp.scene_id,
            index_code=product.index_code,
            processing_version=rp.processing_version,
            asset_name=asset_name,
        )
        with tempfile.TemporaryDirectory(prefix="ct-proc-") as tmpdir:
            cog_path = str(Path(tmpdir) / "product.tif")
            cog_meta = pre.write_index_cog(
                array=product.array,
                transform=reading.transform,
                crs_string=reading.crs,
                path=cog_path,
            )
            data = Path(cog_path).read_bytes()
            stored_obj = _put_asset_owned(
                db, rp, storage, key, data, "image/tiff", allow_overwrite=True
            )
            preview_name = f"{rp.scene_id}_{product.index_code}.png"
            preview_key = raster_key(
                org_id=org_id,
                field_id=field.id,
                kind="preview",
                provider_code=scene.provider_code,
                scene_id=rp.scene_id,
                index_code=product.index_code,
                processing_version=rp.processing_version,
                asset_name=preview_name,
            )
            png = pre.render_preview_png(
                index_array=product.array,
                index_code=product.index_code,
                max_px=settings.raster_preview_max_px,
            )
            preview_obj = _put_asset_owned(
                db, rp, storage, preview_key, png, "image/png", allow_overwrite=True
            )

        bbox_wgs84 = _window_bounds_wgs84(reading.crs, reading.window_bounds)
        provenance = pre.product_provenance(
            product_code=scene.product_code,
            product_version=PRODUCT_VERSION,
            scene_id=rp.scene_id,
            provider_code=scene.provider_code,
            index_code=product.index_code,
            index_formula=INDEX_FORMULAS.get(product.index_code, ""),
            band_mapping={
                "surface_assets": dict(scene.band_mapping or {}),
                "surfaces_used": list(reading.arrays.keys()),
            },
            processing_version=rp.processing_version,
            pipeline_provenance={
                **pipeline_provenance,
                "cog_layout": cog_meta,
                "scene_acquired_at": scene_record["acquired_at"],
                "scene_cloud_cover_pct": scene.cloud_cover_pct,
                "window_bounds_wgs84": bbox_wgs84,
                "boundary_version": boundary_version,
            },
            derived_at=datetime.now(UTC),
        )
        stored.append(
            {
                "index_code": product.index_code,
                "key": stored_obj.key,
                "checksum": stored_obj.checksum_sha256,
                "size": stored_obj.byte_size,
                "preview_key": preview_obj.key,
                "preview_checksum": preview_obj.checksum_sha256,
                "preview_size": preview_obj.byte_size,
                "valid_pixel_fraction": product.valid_pixel_fraction,
                "zonal": product.zonal,
                "zone_summary": product.zone_summary,
                "provenance": provenance,
            }
        )

    _prog(85, "persisting product registry")
    _persist_products(
        db,
        field=field,
        scene=scene,
        rp=rp,
        stored=stored,
        reading=reading,
        boundary_version=boundary_version,
    )

    _prog(95, "recording observations")
    warnings_obs = _persist_observations(
        db,
        field=field,
        scene=scene,
        rp=rp,
        stored=stored,
        scene_record=scene_record,
    )
    all_warnings.extend(warnings_obs)

    _assert_processing_job_owner(db, rp)
    rp.status = "succeeded"
    rp.progress = 100
    rp.stage = "completed"
    rp.warnings = all_warnings[:50]
    rp.finished_at = datetime.now(UTC)
    db.add(rp)
    if rp.background_job_id:
        bg = db.get(BackgroundJob, rp.background_job_id)
        if bg is not None:
            bg.status = "succeeded"
            bg.progress = 100
            bg.finished_at = datetime.now(UTC)
            bg.result = {
                "derived_indices": [s["index_code"] for s in stored],
                "scene_id": rp.scene_id,
                "processing_version": rp.processing_version,
            }
            db.add(bg)
    db.commit()
    logger.info(
        "raster processing succeeded",
        extra={
            "job_id": str(rp.id),
            "scene_id": rp.scene_id,
            "indices": rp.indices,
        },
    )


def _put_asset(storage: Any, key: str, data: bytes, content_type: str, *, allow_overwrite: bool) -> Any:
    try:
        return storage.put_bytes(key, data, content_type=content_type)
    except KeyConflictError:
        if not allow_overwrite:
            raise
        # Deterministic regeneration of the same processing-version artifact:
        # deliberate overwrite (retry-safety), never an accidental clobber.
        return storage.put_bytes(key, data, content_type=content_type, overwrite=True)


def _put_asset_owned(
    db: Session,
    rp: RasterProcessingJob,
    storage: Any,
    key: str,
    data: bytes,
    content_type: str,
    *,
    allow_overwrite: bool,
) -> Any:
    """Check ownership immediately before an external artifact write.

    The persisted-row lock is held through the put and released immediately
    afterward; external storage itself has no transactional fencing primitive.
    """
    _assert_processing_job_owner(db, rp)
    stored = _put_asset(storage, key, data, content_type, allow_overwrite=allow_overwrite)
    db.commit()
    return stored


# ------------------------------------------------------------ persistence
def _persist_products(
    db: Session,
    *,
    field: Field,
    scene: SatelliteScene,
    rp: RasterProcessingJob,
    stored: list[dict[str, Any]],
    reading: Any,
    boundary_version: int | None,
) -> None:
    """Insert raster_assets rows (idempotent per natural key)."""
    _assert_processing_job_owner(db, rp)
    for s in stored:
        key = s["key"]
        existing = db.scalar(
            select(RasterAsset.id).where(
                RasterAsset.field_id == field.id,
                RasterAsset.asset_kind == "derived",
                RasterAsset.scene_id == rp.scene_id,
                RasterAsset.index_code == s["index_code"],
                RasterAsset.processing_version == rp.processing_version,
                RasterAsset.asset_name == key.rsplit("/", 1)[-1],
            )
        )
        if existing is None:
            db.add(
                RasterAsset(
                    field_id=field.id,
                    scene_id=rp.scene_id,
                    provider_code=scene.provider_code,
                    product_code=scene.product_code,
                    index_code=s["index_code"],
                    asset_kind="derived",
                    asset_name=key.rsplit("/", 1)[-1],
                    processing_version=rp.processing_version,
                    storage_backend=storage_backend_of(),
                    storage_key=key,
                    content_type="image/tiff",
                    byte_size=s["size"],
                    checksum_sha256=s["checksum"],
                    crs=reading.crs,
                    spatial_resolution_m=scene.spatial_resolution_m,
                    bbox_json=list(reading.window_bounds),
                    transform_json=_transform_dict(reading.transform),
                    valid_pixel_fraction=s["valid_pixel_fraction"],
                    boundary_version=boundary_version,
                    stats_json={
                        "zonal": s["zonal"],
                        "zone_summary": s["zone_summary"],
                        "index_code": s["index_code"],
                    },
                    provenance_json=s["provenance"],
                    acquired_at=scene.acquired_at,
                )
            )
        preview_existing = db.scalar(
            select(RasterAsset.id).where(
                RasterAsset.field_id == field.id,
                RasterAsset.asset_kind == "preview",
                RasterAsset.scene_id == rp.scene_id,
                RasterAsset.index_code == s["index_code"],
                RasterAsset.processing_version == rp.processing_version,
                RasterAsset.asset_name == s["preview_key"].rsplit("/", 1)[-1],
            )
        )
        if preview_existing is None:
            db.add(
                RasterAsset(
                    field_id=field.id,
                    scene_id=rp.scene_id,
                    provider_code=scene.provider_code,
                    product_code=scene.product_code,
                    index_code=s["index_code"],
                    asset_kind="preview",
                    asset_name=s["preview_key"].rsplit("/", 1)[-1],
                    processing_version=rp.processing_version,
                    storage_backend=storage_backend_of(),
                    storage_key=s["preview_key"],
                    content_type="image/png",
                    byte_size=s["preview_size"],
                    checksum_sha256=s["preview_checksum"],
                    crs="EPSG:4326",
                    bbox_json=(s["provenance"]["pipeline"].get("window_bounds_wgs84") or [None] * 4),
                    transform_json=None,
                    valid_pixel_fraction=s["valid_pixel_fraction"],
                    boundary_version=boundary_version,
                    stats_json=None,
                    provenance_json=s["provenance"],
                    acquired_at=scene.acquired_at,
                )
            )
    db.flush()


def _persist_observations(
    db: Session,
    *,
    field: Field,
    scene: SatelliteScene,
    rp: RasterProcessingJob,
    stored: list[dict[str, Any]],
    scene_record: dict[str, Any],
) -> list[str]:
    """Upsert one index observation per derived product (honest semantics).

    - No row -> insert.
    - Row with NULL value (a failed ingestion attempt) -> upgraded in place,
      the supersede chain recorded in metadata.
    - Valid row from a DIFFERENT processing version -> value superseded with
      the previous value + version kept in the provenance chain.
    - Valid row from the SAME processing version -> kept (idempotent).
    """
    _assert_processing_job_owner(db, rp)
    from app.data_platform.ingestion.service import _product_for_provider
    from app.data_platform.providers.nasa_hls.registry_info import (
        HLS_SPATIAL_RESOLUTION_M,
        PRODUCT_VERSION,
    )
    from app.vegetation.indices import INDEX_FORMULAS

    from app.db.models import ObservationQualityFlag

    evidence_class = (
        "synthetic_test_data" if scene.is_synthetic else "satellite_derived_estimate"
    )
    product_version = scene.processing_version or PRODUCT_VERSION
    _source, product = _product_for_provider(
        db, scene.provider_code, product_code=scene.product_code, product_version=product_version
    )
    acquired_at = scene.acquired_at
    outcomes: list[str] = []
    warnings: list[str] = []

    for s in stored:
        index_code = s["index_code"]
        zonal = s["zonal"]
        value = zonal.get("mean")
        if value is None:
            warnings.append(
                f"{index_code}: no valid pixels after masking; no observation recorded"
            )
            continue
        metadata: dict[str, Any] = {
            "scene_id": scene.scene_id,
            "granule_id": scene.scene_id,
            "platform": scene_record.get("platform"),
            "collection": scene.product_code,
            "collection_id": scene_record.get("collection_id"),
            "processing_baseline": PRODUCT_VERSION,
            "cloud_cover_pct": scene.cloud_cover_pct,
            "spatial_resolution_m": HLS_SPATIAL_RESOLUTION_M,
            "processing_job_id": str(rp.id),
            "asset_refs": {
                "derived_key": s["key"],
                "preview_key": s["preview_key"],
                "checksum_sha256": s["checksum"],
            },
            "raster_asset_id": None,
            "zonal": zonal,
            "zone_summary": s["zone_summary"],
            "subfield_statistics_ok": (zonal.get("valid_pixels") or 0) >= 5,
            "index_formula": INDEX_FORMULAS.get(index_code, ""),
            "index_math": "app.vegetation.raster_indices",
            "pipeline": {
                "software_version": pre.PROCESSING_SOFTWARE_VERSION,
                "processing_version": rp.processing_version,
                "read_mode": "windowed_range_read",
                "crs": reading_crs(s),
            },
            "quality_flags": [
                {
                    "flag_code": "NASA_HLS_DERIVED",
                    "severity": "info",
                    "message": (
                        f"CRS-correct windowed derivation at {rp.processing_version}; "
                        f"{zonal.get('valid_pixels')} valid pixels "
                        f"({round((s['valid_pixel_fraction'] or 0) * 100)}% of field mask)."
                    ),
                }
            ],
        }

        existing = db.scalar(
            select(Observation).where(
                Observation.field_id == field.id,
                Observation.dataset_product_id == product.id,
                Observation.variable_code == index_code,
                Observation.observed_at == acquired_at,
                Observation.time_support == "instant",
                Observation.spatial_support_type == "polygon_average",
            )
        )
        outcome = "kept_existing"
        if existing is None:
            row = Observation(
                field_id=field.id,
                dataset_product_id=product.id,
                variable_code=index_code,
                value=float(value),
                unit="index",
                observed_at=acquired_at,
                period_start=acquired_at,
                period_end=acquired_at,
                time_support="instant",
                spatial_support_type="polygon_average",
                spatial_resolution_m=HLS_SPATIAL_RESOLUTION_M,
                quality_status="valid",
                evidence_class=evidence_class,
                uncertainty_value=None,
                uncertainty_type="not_quantified",
                is_synthetic=bool(scene.is_synthetic),
                ingestion_job_id=None,
                retrieved_at=datetime.now(UTC),
                processing_version=rp.processing_version,
                metadata=metadata,
            )
            db.add(row)
            db.flush()
            for flag in metadata["quality_flags"]:
                db.add(
                    ObservationQualityFlag(
                        observation_id=row.id,
                        flag_code=flag["flag_code"],
                        severity=flag["severity"],
                        message=flag["message"],
                        details=flag.get("details", {}),
                    )
                )
            outcome = "inserted"
        elif existing.value is None or existing.quality_status == "missing":
            chain = list((existing.metadata or {}).get("provenance_chain", []))
            chain.append(
                {
                    "previous_status": existing.quality_status,
                    "previous_value": None,
                    "previous_processing_version": existing.processing_version,
                    "superseded_by": rp.processing_version,
                    "superseded_at": datetime.now(UTC).isoformat(),
                    "reason": "missing ingestion attempt upgraded by CRS-correct processing",
                }
            )
            existing.value = float(value)
            existing.quality_status = "valid"
            existing.processing_version = rp.processing_version
            existing.retrieved_at = datetime.now(UTC)
            merged = dict(existing.metadata or {})
            merged.update(metadata)
            merged["provenance_chain"] = chain
            existing.metadata = merged
            db.add(existing)
            outcome = "upgraded_missing"
        elif existing.processing_version != rp.processing_version:
            chain = list((existing.metadata or {}).get("provenance_chain", []))
            chain.append(
                {
                    "previous_status": existing.quality_status,
                    "previous_value": existing.value,
                    "previous_processing_version": existing.processing_version,
                    "superseded_by": rp.processing_version,
                    "superseded_at": datetime.now(UTC).isoformat(),
                    "reason": "recomputation at a new processing version",
                }
            )
            existing.value = float(value)
            existing.processing_version = rp.processing_version
            existing.retrieved_at = datetime.now(UTC)
            merged = dict(existing.metadata or {})
            merged.update(metadata)
            merged["provenance_chain"] = chain
            existing.metadata = merged
            db.add(existing)
            outcome = "superseded_new_version"
        db.flush()
        outcomes.append(f"{index_code}:{outcome}")
    if outcomes:
        logger.info(
            "index observations recorded",
            extra={"scene_id": rp.scene_id, "outcomes": outcomes},
        )
    return warnings


def reading_crs(s: dict[str, Any]) -> str | None:
    prov = s.get("provenance") or {}
    pipe = prov.get("pipeline") or {}
    window = pipe.get("window") or {}
    return window.get("crs")


def _transform_dict(transform: Any) -> dict[str, float]:
    return {
        "a": transform.a,
        "b": transform.b,
        "c": transform.c,
        "d": transform.d,
        "e": transform.e,
        "f": transform.f,
    }


def _window_bounds_wgs84(crs_string: str, bounds: tuple[float, float, float, float]) -> list[float]:
    """Transform window bounds to EPSG:4326 for map overlay (best effort)."""
    try:
        from pyproj import CRS, Transformer

        src = CRS.from_string(crs_string)
        transformer = Transformer.from_crs(src, CRS.from_epsg(4326), always_xy=True)
        minx, miny, maxx, maxy = bounds
        corners = [
            transformer.transform(minx, miny),
            transformer.transform(minx, maxy),
            transformer.transform(maxx, miny),
            transformer.transform(maxx, maxy),
        ]
        xs = [c[0] for c in corners]
        ys = [c[1] for c in corners]
        return [min(xs), min(ys), max(xs), max(ys)]
    except Exception:  # noqa: BLE001 — overlay bounds are advisory metadata
        return []


# ------------------------------------------------------------- inspection
def list_field_products(db: Session, *, field_id: uuid.UUID) -> dict[str, Any]:
    """Per-scene processing state joined with derived assets (UI contract).

    Status vocabulary (honest, distinguishable):
    - 'unprocessed': raw scene only
    - 'processing': an active (queued|running) raster_processing job exists
    - 'partial': one or more, but not all, map-supported indices exist
    - 'processed': all map-supported indices exist for the requested version
    - 'failed': latest attempt failed (error surfaced)
    """
    scenes = db.scalars(
        select(SatelliteScene)
        .where(
            SatelliteScene.field_id == field_id,
            # real acquisition (nasa_hls) or the labeled fixture-demo provider
            SatelliteScene.provider_code.in_([PROVIDER_CODE, FIXTURE_PROVIDER_CODE]),
            sa_or(
                SatelliteScene.acquisition_status.is_(None),
                SatelliteScene.acquisition_status == "ready",
            ),
        )
        .order_by(SatelliteScene.acquired_at.desc())
    ).all()
    version = PROCESSING_VERSION
    items: list[dict[str, Any]] = []
    for scene in scenes:
        assets = db.scalars(
            select(RasterAsset).where(
                RasterAsset.field_id == field_id,
                RasterAsset.scene_id == scene.scene_id,
                RasterAsset.processing_version == version,
                RasterAsset.asset_kind.in_(("derived", "preview")),
            )
        ).all()
        derived = [a for a in assets if a.asset_kind == "derived"]
        derived_indices = {a.index_code for a in derived}
        available_indices = [
            index for index in MAP_SUPPORTED_INDICES if index in derived_indices
        ]
        missing_indices = [
            index for index in MAP_SUPPORTED_INDICES if index not in derived_indices
        ]
        previews = {a.index_code: a for a in assets if a.asset_kind == "preview"}
        active = db.scalars(
            select(RasterProcessingJob).where(
                RasterProcessingJob.field_id == field_id,
                RasterProcessingJob.scene_id == scene.scene_id,
                RasterProcessingJob.processing_version == version,
                RasterProcessingJob.status.in_(("queued", "running")),
            )
        ).all()
        latest_failed = db.scalar(
            select(RasterProcessingJob)
            .where(
                RasterProcessingJob.field_id == field_id,
                RasterProcessingJob.scene_id == scene.scene_id,
                RasterProcessingJob.processing_version == version,
                RasterProcessingJob.status == "failed",
            )
            .order_by(RasterProcessingJob.finished_at.desc())
            .limit(1)
        )
        if active:
            state = "processing"
            detail = {
                "job_ids": [str(j.id) for j in active],
                "indices": sorted({i for j in active for i in (j.indices or [])}),
                "stage": active[0].stage,
                "progress": active[0].progress,
                "available_indices": available_indices,
                "missing_indices": missing_indices,
            }
        elif not missing_indices:
            state = "processed"
            detail = None
        elif latest_failed is not None:
            state = "failed"
            detail = {
                "job_id": str(latest_failed.id),
                "error": (latest_failed.error or "")[:500],
                "available_indices": available_indices,
                "missing_indices": missing_indices,
            }
        elif available_indices:
            state = "partial"
            detail = {
                "available_indices": available_indices,
                "missing_indices": missing_indices,
            }
        else:
            state = "unprocessed"
            detail = None
        items.append(
            {
                "scene_id": scene.scene_id,
                "product_code": scene.product_code,
                "provider_code": scene.provider_code,
                "is_synthetic": bool(scene.is_synthetic),
                "acquired_at": scene.acquired_at.isoformat() if scene.acquired_at else None,
                "cloud_cover_pct": scene.cloud_cover_pct,
                "acquisition_status": scene.acquisition_status or "ready",
                "processing_state": state,
                "processing_detail": detail,
                "processing_version": version if derived else None,
                "products": [
                    {
                        "index_code": a.index_code,
                        "asset_id": str(a.id),
                        "valid_pixel_fraction": a.valid_pixel_fraction,
                        "zonal": (a.stats_json or {}).get("zonal"),
                        "zone_summary": (a.stats_json or {}).get("zone_summary"),
                        "preview_asset_id": str(previews[a.index_code].id)
                        if a.index_code in previews
                        else None,
                        "crs": a.crs,
                        "bbox_wgs84": (a.provenance_json or {})
                        .get("pipeline", {})
                        .get("window_bounds_wgs84"),
                        "spatial_resolution_m": a.spatial_resolution_m,
                        "processing_version": a.processing_version,
                        "derived_at": (a.provenance_json or {}).get("derived_at"),
                    }
                    for a in derived
                ],
            }
        )
    return {
        "field_id": str(field_id),
        "processing_version": version,
        "total": len(items),
        "scenes": items,
    }


# --------------------------------------------------------------- helpers
def storage_backend_of() -> str:
    from app.geospatial.objectstore import get_raster_storage

    return get_raster_storage().backend


def _org_id_of_field(db: Session, field: Field) -> uuid.UUID:
    from app.db.models import Farm

    farm = db.get(Farm, field.farm_id)
    if farm is None:
        raise ProcessingRequestError("field has no farm (tenant isolation violated)")
    return farm.organization_id


def _field_geometry(db: Session, field_id: uuid.UUID) -> dict[str, Any]:
    import json

    from sqlalchemy import text as sql_text

    row = db.execute(
        sql_text("SELECT ST_AsGeoJSON(boundary) AS g FROM fields WHERE id = :fid"),
        {"fid": str(field_id)},
    ).scalar_one_or_none()
    if not row:
        raise SceneNotProcessableError("field boundary missing")
    return json.loads(row)


def _field_boundary_version(db: Session, field_id: uuid.UUID) -> int | None:
    from sqlalchemy import text as sql_text

    return db.execute(
        sql_text("SELECT boundary_version FROM fields WHERE id = :fid"),
        {"fid": str(field_id)},
    ).scalar_one_or_none()


# ------------------------------------------------------------ cancellation
def cancel_processing_job(db: Session, *, job: BackgroundJob) -> dict[str, Any]:
    """Cancel a QUEUED preprocessing job (running work cannot be cancelled
    safely mid-derivation — the single-commit persistence model means a
    running job either completes or fails atomically)."""
    if job.ref_kind != PROCESSING_JOB_KIND or job.ref_id is None:
        raise ProcessingRequestError("not a raster_processing job")
    rp = db.get(RasterProcessingJob, job.ref_id)
    if rp is None:
        raise ProcessingRequestError("processing job row missing")
    if job.status == "queued" and rp.status == "queued":
        job.status = "cancelled"
        job.finished_at = datetime.now(UTC)
        rp.status = "cancelled"
        rp.finished_at = datetime.now(UTC)
        db.add(job)
        db.add(rp)
        db.commit()
        return {"cancelled": True, "job_id": str(rp.id), "scene_id": rp.scene_id}
    return {
        "cancelled": False,
        "job_id": str(rp.id),
        "reason": f"job status is '{job.status}' (only queued jobs can be cancelled)",
    }


# ------------------------------------------------------ replay registration
def replay_processing_job(bg_job_id: uuid.UUID, progress: Any) -> None:
    """Crash-recovery executor for kind='raster_processing'.

    Rebuilds the domain job id from the persisted BackgroundJob row and
    re-executes it if it is still queued (the core executor marks stale
    'running' rows failed before recovery runs).
    """
    from app.core.database import SessionLocal

    with SessionLocal() as db:
        job = db.get(BackgroundJob, bg_job_id)
        if job is None or job.ref_kind != PROCESSING_JOB_KIND or job.ref_id is None:
            return
        rp = db.get(RasterProcessingJob, job.ref_id)
        if rp is None or rp.status != "queued":
            return
    execute_processing_job(rp.id, progress)
