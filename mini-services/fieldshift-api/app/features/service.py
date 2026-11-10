"""Feature-run orchestration (Milestone 4).

A feature run is a reproducible computation: the run row records the resolved
source selection (ONE dataset product per variable — synthetic and real data
are never blended), the calendar basis, the window, the engine and catalog
versions, and every warning. Values are written once by the run; comparison
across runs is the supported way to observe change.

Honesty rules enforced here:
- Source selection never mixes providers for the same variable inside a run.
- Runs over synthetic data are flagged `is_synthetic` end to end.
- Missing source variables drop the dependent features with an explicit
  reason — they are never silently skipped nor computed from substitutes.
- Crop-season windows are user-supplied; no crop calendar knowledge is
  invented here (the sourced knowledge base arrives in a later milestone).
"""

import logging
import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import Boolean, Integer, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import InsufficientData, NotFound, ValidationFailed
from app.data_platform.contracts.variables import VARIABLE_CATALOG
from app.db.models import (
    DatasetProduct,
    DataSource,
    FeatureDefinition,
    FeatureRun,
    FeatureValue,
    Field,
    Observation,
)
from app.features import engine as fengine
from app.features.calendar import resolve_timezone
from app.features.catalog import (
    FEATURE_CATALOG,
    FEATURE_CATALOG_VERSION,
    FEATURE_ENGINE_VERSION,
)

logger = logging.getLogger("croptwist.features")

ALLOWED_AGGREGATION_LEVELS = ("daily", "monthly", "seasonal", "crop_season")
MAX_WINDOW_YEARS = 31
MAX_DAILY_WINDOW_DAYS = 1100  # ~3 years, protects the daily-value volume
MAX_CROP_SEASONS = 20


def ensure_feature_definitions(db: Session) -> None:
    """Seed the versioned feature definitions table from the code catalog."""
    from app.features.catalog import catalog_payload

    existing = {
        (row.feature_code, row.definition_version)
        for row in db.scalars(
            select(FeatureDefinition).where(
                FeatureDefinition.definition_version == FEATURE_CATALOG_VERSION
            )
        ).all()
    }
    created = False
    for item in catalog_payload():
        key = (item["feature_code"], item["definition_version"])
        if key in existing:
            continue
        db.add(
            FeatureDefinition(
                feature_code=item["feature_code"],
                name=item["name"],
                description=item["description"],
                unit=item["unit"],
                category=item["category"],
                aggregation_levels=item["aggregation_levels"],
                required_variables=item["required_variables"],
                min_coverage_ratio=item["min_coverage_ratio"],
                definition_version=item["definition_version"],
                formula_reference=item["formula_reference"],
                is_active=True,
            )
        )
        created = True
    if created:
        db.commit()


def resolve_source_selection(
    db: Session,
    *,
    field_id: uuid.UUID,
    variables: list[str],
    overrides: dict[str, str] | None = None,
    window_start: datetime | None = None,
    window_end: datetime | None = None,
) -> tuple[dict[str, dict[str, Any]], list[str], bool]:
    """Pick ONE dataset product per variable for the run.

    Preference (window-aware): real (non-synthetic) products first, then the
    product with the most valid observations INSIDE the run window, then the
    best overall valid ratio, then the most recent retrieval. A real product
    with no data in the window is therefore not preferred over a synthetic
    fixture that actually covers the window — the fallback is warned about and
    the run is flagged `is_synthetic`. Overrides pin a specific product and
    are validated against the field's actual observations.
    """
    overrides = overrides or {}
    stmt = (
        select(
            Observation.variable_code,
            Observation.dataset_product_id,
            func.count().label("n"),
            func.sum(func.cast(Observation.value.is_not(None), Integer)).label("valid_n"),
            func.max(Observation.retrieved_at).label("last_retrieval"),
            func.cast(func.bool_or(Observation.is_synthetic), Boolean).label("has_synthetic"),
        )
        .where(Observation.field_id == field_id, Observation.variable_code.in_(variables))
        .group_by(Observation.variable_code, Observation.dataset_product_id)
    )
    if window_start is not None and window_end is not None:
        # in-window counts drive the preference; keep a margin of one day on
        # both sides for daily periods that straddle the window boundary
        margin = timedelta(days=1)
        stmt = stmt.where(
            Observation.observed_at >= window_start - margin,
            Observation.observed_at <= window_end + margin,
        )
    rows = db.execute(stmt).all()

    if not rows:
        raise InsufficientData(
            "No observations are available for the requested variables on this field.",
            details=[{"field": "variables", "reason": ", ".join(sorted(variables))}],
        )

    products = {
        p.id: p
        for p in db.scalars(
            select(DatasetProduct).where(
                DatasetProduct.id.in_([r.dataset_product_id for r in rows])
            )
        ).all()
    }

    grouped: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        product = products.get(r.dataset_product_id)
        if product is None:
            continue
        meta = product.metadata or {}
        grouped.setdefault(r.variable_code, []).append(
            {
                "dataset_product_id": str(product.id),
                "product_code": product.product_code,
                "product_version": product.product_version,
                "is_synthetic": bool(meta.get("is_synthetic")) or bool(r.has_synthetic),
                "n": int(r.n),
                "valid_n": int(r.valid_n or 0),
                "last_retrieval": r.last_retrieval,
            }
        )

    selection: dict[str, dict[str, Any]] = {}
    warnings: list[str] = []
    for variable in variables:
        candidates = grouped.get(variable) or []
        if not candidates:
            continue
        override_id = overrides.get(variable)
        if override_id:
            chosen = next(
                (c for c in candidates if c["dataset_product_id"] == str(override_id)), None
            )
            if chosen is None:
                raise ValidationFailed(
                    f"Source override for '{variable}' does not match any product with "
                    "observations on this field.",
                    details=[{"field": "source_overrides", "reason": variable}],
                )
        else:
            chosen = sorted(
                candidates,
                key=lambda c: (
                    c["is_synthetic"],
                    -(c["valid_n"]),
                    -(c["valid_n"] / max(1, c["n"])),
                    -(c["last_retrieval"].timestamp() if c["last_retrieval"] else 0),
                ),
            )[0]
        selection[variable] = {
            "dataset_product_id": chosen["dataset_product_id"],
            "product_code": chosen["product_code"],
            "product_version": chosen["product_version"],
            "is_synthetic": chosen["is_synthetic"],
        }
        skipped = [c for c in candidates if c["dataset_product_id"] != chosen["dataset_product_id"]]
        for c in skipped:
            if chosen["is_synthetic"] and not c["is_synthetic"]:
                warnings.append(
                    f"{variable}: real product '{c['product_code']}' ({c['product_version']}) has no "
                    "observations inside the run window; the synthetic fixture was selected instead "
                    "(the run is flagged synthetic). Products are never blended."
                )
            else:
                warnings.append(
                    f"{variable}: observations from product '{c['product_code']}' "
                    f"({c['product_version']}) were not selected for this run; one source per "
                    "variable is used so products are never blended."
                )

    is_synthetic = any(s["is_synthetic"] for s in selection.values())
    return selection, warnings, is_synthetic


def start_feature_run(
    db: Session,
    *,
    field: Field,
    payload: dict[str, Any],
    created_by: Any = None,
) -> FeatureRun:
    """Validate the request, create (or return) the run, execute it inline."""
    ensure_feature_definitions(db)

    idempotency_key = payload.get("idempotency_key")
    if idempotency_key:
        # Deepening F-3: the replay lookup is scoped to THIS field — a global
        # key lookup could return another tenant's run if a key collided or
        # was guessed (cross-tenant information disclosure).
        existing = db.scalar(
            select(FeatureRun).where(
                FeatureRun.idempotency_key == idempotency_key,
                FeatureRun.field_id == field.id,
            )
        )
        if existing is not None:
            return existing

    start_date: date = payload["start_date"]
    end_date: date = payload["end_date"]
    if start_date > end_date:
        raise ValidationFailed(
            "start_date must be on or before end_date.",
            details=[{"field": "start_date", "reason": str(start_date)}],
        )
    if (end_date - start_date).days > MAX_WINDOW_YEARS * 366:
        raise ValidationFailed(
            f"Feature run window exceeds {MAX_WINDOW_YEARS} years.",
            details=[{"field": "end_date", "reason": "window too long"}],
        )

    levels = payload.get("aggregation_levels") or ["monthly"]
    unknown_levels = [l for l in levels if l not in ALLOWED_AGGREGATION_LEVELS]
    if unknown_levels:
        raise ValidationFailed(
            "Unknown aggregation levels.",
            details=[{"field": "aggregation_levels", "reason": ", ".join(unknown_levels)}],
        )
    if "daily" in levels and (end_date - start_date).days > MAX_DAILY_WINDOW_DAYS:
        raise ValidationFailed(
            f"Daily aggregation is limited to {MAX_DAILY_WINDOW_DAYS} days per run.",
            details=[{"field": "end_date", "reason": "window too long for daily level"}],
        )

    hemisphere = payload.get("hemisphere") or "north"
    if hemisphere not in ("north", "south"):
        raise ValidationFailed(
            "hemisphere must be 'north' or 'south'.",
            details=[{"field": "hemisphere", "reason": hemisphere}],
        )

    calendar_timezone = payload.get("calendar_timezone") or field.farm.timezone or "UTC"
    try:
        tz = resolve_timezone(calendar_timezone)
    except ValueError as exc:
        raise ValidationFailed(str(exc), details=[{"field": "calendar_timezone"}]) from None

    crop_seasons_raw = payload.get("crop_seasons") or []
    if crop_seasons_raw and "crop_season" not in levels:
        raise ValidationFailed(
            "crop_seasons supplied but the 'crop_season' aggregation level is not requested.",
            details=[{"field": "aggregation_levels", "reason": "add 'crop_season'"}],
        )
    if len(crop_seasons_raw) > MAX_CROP_SEASONS:
        raise ValidationFailed(
            f"Too many crop-season windows (max {MAX_CROP_SEASONS}).",
            details=[{"field": "crop_seasons"}],
        )
    crop_seasons: list[dict[str, Any]] = []
    seen_labels: set[str] = set()
    for cs in crop_seasons_raw:
        label = str(cs.get("label") or "").strip()
        if not label or len(label) > 40:
            raise ValidationFailed(
                "Crop-season labels must be 1-40 characters.",
                details=[{"field": "crop_seasons", "reason": str(cs)[:80]}],
            )
        if label in seen_labels:
            raise ValidationFailed(
                f"Duplicate crop-season label '{label}'.",
                details=[{"field": "crop_seasons", "reason": label}],
            )
        seen_labels.add(label)
        try:
            cs_start = date.fromisoformat(str(cs["start_date"]))
            cs_end = date.fromisoformat(str(cs["end_date"]))
        except (KeyError, ValueError):
            raise ValidationFailed(
                "Crop seasons need start_date and end_date (ISO dates).",
                details=[{"field": "crop_seasons", "reason": label}],
            ) from None
        if cs_start > cs_end:
            raise ValidationFailed(
                f"Crop season '{label}' start_date is after end_date.",
                details=[{"field": "crop_seasons", "reason": label}],
            )
        crop_seasons.append({"label": label, "start_date": cs_start, "end_date": cs_end})

    # Feature specs to compute.
    requested_codes = payload.get("feature_codes")
    if requested_codes:
        unknown = [c for c in requested_codes if c not in FEATURE_CATALOG]
        if unknown:
            raise ValidationFailed(
                "Unknown feature codes.",
                details=[{"field": "feature_codes", "reason": ", ".join(sorted(unknown))}],
            )
        specs = [FEATURE_CATALOG[c] for c in sorted(set(requested_codes))]
    else:
        specs = [
            s
            for s in FEATURE_CATALOG.values()
            if any(level in s.aggregation_levels for level in levels)
        ]
    if not specs:
        raise ValidationFailed(
            "No features match the requested aggregation levels.",
            details=[{"field": "feature_codes"}],
        )

    variables = payload.get("variables")
    required_vars = sorted({v for spec in specs for v in spec.required_variables})
    if variables:
        unknown_vars = [v for v in variables if v not in VARIABLE_CATALOG]
        if unknown_vars:
            raise ValidationFailed(
                "Unknown variable codes in request.",
                details=[{"field": "variables", "reason": ", ".join(unknown_vars)}],
            )
        # Restrict features to what the requested variables can supply.
        allowed = set(variables)
        specs = [s for s in specs if set(s.required_variables) <= allowed]
        if not specs:
            raise ValidationFailed(
                "None of the catalog features can be computed from the requested variables.",
                details=[{"field": "variables", "reason": ", ".join(sorted(variables))}],
            )
        required_vars = sorted({v for spec in specs for v in spec.required_variables})

    window_start = (
        datetime(start_date.year, start_date.month, start_date.day, tzinfo=tz).astimezone(UTC)
    )
    window_end = (
        datetime(end_date.year, end_date.month, end_date.day, tzinfo=tz) + timedelta(days=1)
    ).astimezone(UTC) - timedelta(seconds=1)

    overrides = payload.get("source_overrides") or {}
    selection, selection_warnings, is_synthetic = resolve_source_selection(
        db,
        field_id=field.id,
        variables=required_vars,
        overrides=overrides,
        window_start=window_start,
        window_end=window_end,
    )

    missing_vars = [v for v in required_vars if v not in selection]
    resolvable_specs = [s for s in specs if set(s.required_variables) <= set(selection)]
    not_evaluated: dict[str, str] = {
        f"variable:{v}": "Required input variable has no observations on this field."
        for v in missing_vars
    }
    dropped_codes = sorted({s.feature_code for s in specs} - {s.feature_code for s in resolvable_specs})

    request_parameters = {
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "aggregation_levels": levels,
        "hemisphere": hemisphere,
        "calendar_timezone": calendar_timezone,
        "crop_seasons": [
            {"label": cs["label"], "start_date": cs["start_date"].isoformat(), "end_date": cs["end_date"].isoformat()}
            for cs in crop_seasons
        ],
        "feature_codes": sorted(s.feature_code for s in specs),
        "source_overrides": {k: str(v) for k, v in overrides.items()},
    }

    run = FeatureRun(
        field_id=field.id,
        status="queued",
        calendar_timezone=calendar_timezone,
        hemisphere=hemisphere,
        period_start=window_start,
        period_end=window_end,
        aggregation_levels=levels,
        requested_variables=required_vars,
        source_selection=selection,
        crop_seasons=request_parameters["crop_seasons"],
        feature_engine_version=FEATURE_ENGINE_VERSION,
        feature_catalog_version=FEATURE_CATALOG_VERSION,
        is_synthetic=is_synthetic,
        request_parameters=request_parameters,
        warnings=list(selection_warnings),
        not_evaluated_reasons=not_evaluated,
        idempotency_key=idempotency_key,
        created_by=created_by,
        # M7.1 H-01: pin the boundary version in effect at run time. Raster
        # extraction and aggregation are geometry-dependent; without this pin
        # a later boundary edit would silently recontextualize the run.
        boundary_version=field.boundary_version,
    )
    db.add(run)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        # Deepening F-3: race recovery is ALSO field-scoped — a duplicate-key
        # collision with another field's run must never serialize that run.
        if idempotency_key:
            existing = db.scalar(
                select(FeatureRun).where(
                    FeatureRun.idempotency_key == idempotency_key,
                    FeatureRun.field_id == field.id,
                )
            )
            if existing is not None:
                return existing
        raise

    if not resolvable_specs:
        run.status = "failed"
        run.error_summary = "None of the requested features have their input variables available."
        run.completed_at = datetime.now(UTC)
        db.commit()
        return run

    _execute_run(
        db,
        run,
        specs=resolvable_specs,
        tz=tz,
        window_start=window_start,
        window_end=window_end,
        crop_seasons=crop_seasons,
        not_evaluated=not_evaluated,
        dropped_codes=dropped_codes,
    )
    return run


def _execute_run(
    db: Session,
    run: FeatureRun,
    *,
    specs: list,
    tz,
    window_start: datetime,
    window_end: datetime,
    crop_seasons: list[dict[str, Any]],
    not_evaluated: dict[str, str],
    dropped_codes: list[str],
) -> None:
    run.status = "running"
    run.started_at = datetime.now(UTC)
    db.commit()

    try:
        selected_ids = [s["dataset_product_id"] for s in run.source_selection.values()]
        margin = timedelta(days=2)
        obs_rows = db.execute(
            select(Observation)
            .where(
                Observation.field_id == run.field_id,
                Observation.dataset_product_id.in_(selected_ids),
                Observation.observed_at >= run.period_start - margin,
                Observation.observed_at <= run.period_end + margin,
            )
            .order_by(Observation.period_start, Observation.variable_code)
        ).scalars().all()

        observations = [
            {
                "id": str(o.id),
                "variable_code": o.variable_code,
                "value": o.value,
                "unit": o.unit,
                "quality_status": o.quality_status,
                "observed_at": o.observed_at,
                "period_start": o.period_start,
                "period_end": o.period_end,
                "time_support": o.time_support,
                "is_synthetic": o.is_synthetic,
                "processing_version": o.processing_version,
                "evidence_class": o.evidence_class,
                "dataset_product_id": str(o.dataset_product_id),
                "spatial_support_type": o.spatial_support_type,
                "spatial_resolution_m": o.spatial_resolution_m,
                "uncertainty_value": o.uncertainty_value,
                "uncertainty_type": o.uncertainty_type,
                "metadata": o.metadata,
            }
            for o in obs_rows
        ]

        # M7.1 H-02/F-31: preserve the EXACT resolved input set — the full,
        # uncapped observation list handed to the engine — as a versioned
        # manifest document plus deterministic hash. Built here, at the
        # resolution site, so the manifest cannot drift from what the engine
        # actually received. Stored on the run at completion below.
        from app.field_state.manifest import build_manifest, sha256_of_document

        observation_manifest = build_manifest(
            observations,
            field_id=str(run.field_id),
            purpose="feature_run_resolved_inputs",
            window_start=run.period_start,
            window_end=run.period_end,
            variables=[
                spec.strategy_params.get("variable")
                for spec in specs
                if spec.strategy_params.get("variable")
            ],
            source_products=[
                {
                    "variable": variable,
                    "dataset_product_id": sel.get("dataset_product_id"),
                    "product_code": sel.get("product_code"),
                    "product_version": sel.get("product_version"),
                }
                for variable, sel in sorted((run.source_selection or {}).items())
            ],
            processing_configuration={
                "feature_engine_version": run.feature_engine_version,
                "feature_catalog_version": run.feature_catalog_version,
                "calendar_timezone": run.calendar_timezone,
                "hemisphere": run.hemisphere,
                "resolution_window_margin_days": 2,
            },
        )
        observation_manifest_sha256 = sha256_of_document(observation_manifest)

        crop_windows = [
            {
                "label": cs["label"],
                "start": datetime(
                    cs["start_date"].year, cs["start_date"].month, cs["start_date"].day, tzinfo=tz
                ).astimezone(UTC),
                "end": (
                    datetime(
                        cs["end_date"].year, cs["end_date"].month, cs["end_date"].day, tzinfo=tz
                    )
                    + timedelta(days=1)
                ).astimezone(UTC)
                - timedelta(seconds=1),
            }
            for cs in crop_seasons
        ]

        drafts, engine_not_evaluated, engine_warnings = fengine.compute_feature_drafts(
            observations=observations,
            specs=specs,
            tz=tz,
            hemisphere=run.hemisphere,
            window_start=window_start,
            window_end=window_end,
            aggregation_levels=list(run.aggregation_levels),
            crop_seasons=crop_windows,
            engine_version=run.feature_engine_version,
            definition_version=run.feature_catalog_version,
        )

        all_warnings = list(run.warnings) + list(engine_warnings)
        if dropped_codes:
            all_warnings.append(
                "Features without their required inputs were not computed: "
                + ", ".join(dropped_codes)
                + "."
            )
        if run.is_synthetic:
            all_warnings.insert(
                0,
                "This feature run is computed from SYNTHETIC fixture data — values are for "
                "pipeline demonstration and testing only, never for real-world conclusions.",
            )

        written = 0
        for draft in drafts:
            row = draft.to_row()
            db.add(
                FeatureValue(
                    run_id=run.id,
                    field_id=run.field_id,
                    feature_code=row["feature_code"],
                    aggregation_level=row["aggregation_level"],
                    period_label=row["period_label"],
                    period_start=row["period_start"],
                    period_end=row["period_end"],
                    value=row["value"],
                    unit=row["unit"],
                    coverage_ratio=row["coverage_ratio"],
                    n_input=row["n_input"],
                    n_missing=row["n_missing"],
                    quality_status=row["quality_status"],
                    uncertainty_value=row["uncertainty_value"],
                    uncertainty_type=row["uncertainty_type"],
                    baseline_reference=row["baseline_reference"],
                    provenance=row["provenance"],
                )
            )
            written += 1
            if written % 500 == 0:
                db.flush()

        merged_reasons = dict(not_evaluated)
        for code, reason in engine_not_evaluated.items():
            merged_reasons.setdefault(code, reason)

        run.status = "succeeded"
        run.records_written = written
        run.warnings = all_warnings[:100]
        run.not_evaluated_reasons = merged_reasons
        run.completed_at = datetime.now(UTC)
        # M7.1 H-02: persist the resolved-input manifest + its hash on the run
        # itself — the manifest survives as long as the run does and cannot be
        # recomputed from mutable queries later.
        run.observation_manifest = observation_manifest
        run.observation_manifest_sha256 = observation_manifest_sha256
        db.commit()
    except Exception as exc:  # noqa: BLE001 — run lifecycle must capture failures
        db.rollback()
        run.status = "failed"
        run.error_summary = f"{type(exc).__name__}: {exc}"
        run.completed_at = datetime.now(UTC)
        db.commit()
        logger.exception("feature run failed", extra={"run_id": str(run.id)})


def get_run_for_principal(db: Session, run_id: uuid.UUID, principal) -> FeatureRun:
    run = db.get(FeatureRun, run_id)
    if run is None:
        raise NotFound("Feature run not found.")
    from app.domains.identity.service import get_field_for_principal

    get_field_for_principal(db, principal, run.field_id)
    return run


def run_payload(run: FeatureRun, *, include_manifest: bool = False) -> dict[str, Any]:
    # Display the period in the run's calendar basis, not UTC: the farmer chose
    # local dates, so "2015-01-01" must not drift back to "2014-12-31".
    try:
        run_tz = resolve_timezone(run.calendar_timezone)
        period_start_date = run.period_start.astimezone(run_tz).date().isoformat()
        period_end_date = run.period_end.astimezone(run_tz).date().isoformat()
    except Exception:  # noqa: BLE001 — display fallback only
        period_start_date = run.period_start.date().isoformat()
        period_end_date = run.period_end.date().isoformat()
    data = {
        "run_id": str(run.id),
        "field_id": str(run.field_id),
        "status": run.status,
        "calendar_timezone": run.calendar_timezone,
        "hemisphere": run.hemisphere,
        "period": {
            "start": period_start_date,
            "end": period_end_date,
        },
        "aggregation_levels": run.aggregation_levels,
        "requested_variables": run.requested_variables,
        "source_selection": run.source_selection,
        "crop_seasons": run.crop_seasons,
        "feature_engine_version": run.feature_engine_version,
        "feature_catalog_version": run.feature_catalog_version,
        "is_synthetic": run.is_synthetic,
        "warnings": run.warnings,
        "not_evaluated_reasons": run.not_evaluated_reasons,
        "records_written": run.records_written,
        "error_summary": run.error_summary,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "completed_at": run.completed_at.isoformat() if run.completed_at else None,
        # M7.1 provenance surfacing (F-09) + H-01/H-02 pins:
        "created_by": str(run.created_by) if run.created_by else None,
        "boundary_version": run.boundary_version,
        "observation_manifest_sha256": run.observation_manifest_sha256,
        "status_url": f"/api/v1/feature-runs/{run.id}",
    }
    if include_manifest:
        # H-02: the manifest document rides only on the DETAIL payload —
        # list payloads stay small; ?include_manifest=true retrieves it.
        data["observation_manifest"] = run.observation_manifest
    return data


def value_payload(v: FeatureValue) -> dict[str, Any]:
    return {
        "id": str(v.id),
        "feature_code": v.feature_code,
        "aggregation_level": v.aggregation_level,
        "period_label": v.period_label,
        "period_start": v.period_start.date().isoformat(),
        "period_end": v.period_end.date().isoformat(),
        "value": v.value,
        "unit": v.unit,
        "coverage_ratio": v.coverage_ratio,
        "n_input": v.n_input,
        "n_missing": v.n_missing,
        "quality_status": v.quality_status,
        "uncertainty_value": v.uncertainty_value,
        "uncertainty_type": v.uncertainty_type,
        "baseline_reference": v.baseline_reference,
        "provenance": v.provenance,
    }


def compare_runs(
    db: Session, run: FeatureRun, against: FeatureRun
) -> dict[str, Any]:
    """Compare two runs on matching (feature_code, aggregation_level, period_label)."""
    left_rows = db.scalars(select(FeatureValue).where(FeatureValue.run_id == run.id)).all()
    right_rows = db.scalars(select(FeatureValue).where(FeatureValue.run_id == against.id)).all()
    right_by_key = {
        (v.feature_code, v.aggregation_level, v.period_label): v for v in right_rows
    }
    deltas: list[dict[str, Any]] = []
    matched = 0
    only_in_run = 0
    for left in left_rows:
        key = (left.feature_code, left.aggregation_level, left.period_label)
        right = right_by_key.get(key)
        if right is None:
            only_in_run += 1
            continue
        if left.value is None or right.value is None:
            continue
        matched += 1
        delta = round(left.value - right.value, 4)
        delta_pct = (
            round((left.value - right.value) / abs(right.value), 4) if right.value != 0 else None
        )
        deltas.append(
            {
                "feature_code": left.feature_code,
                "aggregation_level": left.aggregation_level,
                "period_label": left.period_label,
                "unit": left.unit,
                "run_value": left.value,
                "against_value": right.value,
                "delta": delta,
                "delta_pct": delta_pct,
                "quality_run": left.quality_status,
                "quality_against": right.quality_status,
            }
        )
    return {
        "run_id": str(run.id),
        "against_run_id": str(against.id),
        "matched_periods": matched,
        "only_in_run": only_in_run,
        "deltas": deltas,
        "note": (
            "Deltas compare two independent runs on matching periods. Runs may use different "
            "source selections, calendar bases or engine versions — check run metadata before "
            "interpreting deltas."
        ),
    }
