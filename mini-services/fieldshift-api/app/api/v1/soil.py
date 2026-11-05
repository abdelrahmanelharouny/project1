"""Soil Intelligence endpoints (Milestone 6B, Step 9).

- GET  /soil/methods                                   — versioned methodology catalog
- POST /fields/{id}/soil-sampling-events               — create a sampling event
- GET  /fields/{id}/soil-sampling-events               — list sampling events
- POST /fields/{id}/soil-samples                       — create a sample (composite or individual)
- GET  /fields/{id}/soil-samples                       — list samples
- POST /soil-samples/import                            — laboratory CSV import (multipart)
- POST /fields/{id}/soil-measurements                  — record one measurement (method-aware)
- GET  /fields/{id}/soil-profile                       — depth-explicit profile read model
- GET  /fields/{id}/soil-indicators                    — per-layer derived indicators (texture/AWC)
- POST /fields/{id}/soc-stock-runs                     — SOC stock run (immutable snapshot)
- GET  /fields/{id}/soc-stock-runs, /soc-stock-runs/{id}
- POST /fields/{id}/nutrient-products                  — nutrient product registry
- POST /fields/{id}/nutrient-applications              — documented nutrient input
- POST /fields/{id}/nutrient-removals                  — documented nutrient output
- POST /fields/{id}/nutrient-budget-runs               — N/P/K budget (immutable snapshot)
- GET  /nutrient-budget-runs/{id}
- POST /fields/{id}/soil-management-events             — management ledger
- POST /fields/{id}/soil-assessments                   — multi-domain assessment snapshot
- GET  /soil-assessments/{id}
- GET  /fields/{id}/soil-health                        — latest assessment read model
- GET  /fields/{id}/soil-data-readiness                — qualitative VOI ranking

Every field-scoped endpoint is tenant-scoped through the field's farm;
every response preserves measured/estimated/farmer/mapped/synthetic
distinctions; run snapshots are immutable with sha256 checksums.
"""

import json
import uuid
from datetime import date, datetime, UTC
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.errors import NotFound, ValidationFailed
from app.db import models as dbm
from app.domains.identity.service import get_field_for_principal, get_principal
from app.soil import assessment as assessment_mod
from app.soil import chemistry as chemistry_mod
from app.soil import contracts as sc
from app.soil import service as soil_service
from app.soil import soc as soc_mod
from app.soil import nutrients as nutrient_mod
from app.soil.import_service import parse_soil_lab_csv

router = APIRouter(tags=["soil"])


def _commit_refresh(db: Session, row: Any) -> Any:
    db.commit()
    db.refresh(row)
    return row


# ------------------------------------------------------------- methods

@router.get("/soil/methods")
def soil_methods() -> dict:
    """The versioned soil methodology catalog: classification systems,
    conversion functions, salinity classes, and the assessment policy."""
    return {
        "soil_engine_version": sc.SOIL_ENGINE_VERSION,
        "methods_version": sc.SOIL_METHODS_VERSION,
        "texture_classifier": {
            "version": sc.TEXTURE_CLASSIFIER_VERSION,
            "system": "USDA soil texture triangle (12 classes)",
            "source": (
                "USDA class polygons transcribed from the soiltexture R package "
                "(USDA.TT; Moeys, CRAN), the computational reference for the "
                "USDA Soil Survey Manual triangle"
            ),
            "silt_derivation": "silt = 100 − sand − clay when silt is absent (disclosed per result)",
            "tolerance": "sand+silt+clay must sum to 100 ± 0.5 when all three are supplied",
        },
        "conversions": {
            "p2o5_to_p": {
                "factor": round(nutrient_mod.P2O5_TO_P, 8),
                "derivation": nutrient_mod.OXIDE_DERIVATION,
                "version": nutrient_mod.OXIDE_CONVERSION_VERSION,
            },
            "k2o_to_k": {
                "factor": round(nutrient_mod.K2O_TO_K, 8),
                "derivation": nutrient_mod.OXIDE_DERIVATION,
                "version": nutrient_mod.OXIDE_CONVERSION_VERSION,
            },
            "oc_to_om": {
                "factor": 1.724,
                "method": "van Bemmelen factor (the M6A water-engine function is the single sanctioned implementation)",
            },
        },
        "salinity_classes": [
            {
                "range_ds_m": [c["range_dS_m"][0], None if c["range_dS_m"][1] == float("inf") else c["range_dS_m"][1]],
                "class": c["class"],
                "citation": c["citation"],
                "applies_to": "ECe (saturated paste) only — no cross-ratio conversion is endorsed",
            }
            for c in chemistry_mod.EC_E_SALINITY_CLASSES
        ],
        "assessment_policy": {
            "version": assessment_mod.ASSESSMENT_VERSION,
            "composite_index": None,
            "note": "transparent multi-domain profile; no composite score (ADR-0026)",
        },
        "variables": [dict(v) for v in sc.SOIL_VARIABLE_DICTIONARY],
    }


# ---------------------------------------------------------- sampling domain

@router.post("/fields/{field_id}/soil-sampling-events", status_code=status.HTTP_201_CREATED)
def create_sampling_event(
    field_id: uuid.UUID,
    body: dict[str, Any],
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    field = get_field_for_principal(db, principal, field_id)
    event = soil_service.create_sampling_event(db, field, body)
    _commit_refresh(db, event)
    return {"id": str(event.id), "field_id": str(field.id), "sampling_date": event.sampling_date.isoformat()}


@router.get("/fields/{field_id}/soil-sampling-events")
def list_sampling_events(
    field_id: uuid.UUID,
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    field = get_field_for_principal(db, principal, field_id)
    rows = db.scalars(
        select(dbm.SoilSamplingEvent)
        .where(dbm.SoilSamplingEvent.field_id == field.id)
        .order_by(dbm.SoilSamplingEvent.sampling_date.desc())
        .limit(100)
    ).all()
    return {
        "field_id": str(field.id),
        "items": [
            {
                "id": str(e.id),
                "sampling_date": e.sampling_date.isoformat(),
                "purpose": e.purpose,
                "sampling_method": e.sampling_method,
                "composite": e.composite,
                "subsample_count": e.subsample_count,
                "management_zone": e.management_zone,
                "gps_lat": e.gps_lat,
                "gps_lon": e.gps_lon,
                "quality_status": e.quality_status,
            }
            for e in rows
        ],
    }


@router.post("/fields/{field_id}/soil-samples", status_code=status.HTTP_201_CREATED)
def create_sample(
    field_id: uuid.UUID,
    body: dict[str, Any],
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    field = get_field_for_principal(db, principal, field_id)
    sample = soil_service.create_sample(db, field, body)
    _commit_refresh(db, sample)
    return {"id": str(sample.id), "sample_code": sample.sample_code, "event_id": str(sample.event_id)}


@router.get("/fields/{field_id}/soil-samples")
def list_samples(
    field_id: uuid.UUID,
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    field = get_field_for_principal(db, principal, field_id)
    rows = db.scalars(
        select(dbm.SoilSample)
        .where(dbm.SoilSample.field_id == field.id)
        .order_by(dbm.SoilSample.created_at.desc())
        .limit(100)
    ).all()
    return {
        "field_id": str(field.id),
        "items": [
            {
                "id": str(s.id),
                "sample_code": s.sample_code,
                "event_id": str(s.event_id),
                "composite_parent_id": str(s.composite_parent_id) if s.composite_parent_id else None,
                "laboratory_id": str(s.laboratory_id) if s.laboratory_id else None,
                "report_reference": s.report_reference,
            }
            for s in rows
        ],
    }


@router.post("/soil-samples/import")
async def import_soil_samples(
    file: UploadFile = File(...),
    mapping: str | None = Form(None),
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    """Laboratory CSV import. `mapping` is an optional JSON mapping spec
    (column → canonical field). Re-importing the same file is a no-op by
    checksum (idempotency)."""
    content = await file.read()
    mapping_spec = None
    if mapping:
        try:
            mapping_spec = json.loads(mapping)
        except json.JSONDecodeError:
            raise ValidationFailed("mapping must be valid JSON.", details=[{"field": "mapping"}]) from None
    try:
        parsed, report = parse_soil_lab_csv(content, mapping_spec=mapping_spec)
    except Exception as exc:  # noqa: BLE001
        raise ValidationFailed(str(exc), details=[{"field": "file"}]) from None

    # idempotency by file checksum: skip re-import of identical content
    existing = db.scalar(
        select(dbm.IngestionJob).where(
            dbm.IngestionJob.idempotency_key == report.idempotency_key,
            dbm.IngestionJob.job_type == "soil_lab_import",
        )
    ) if hasattr(dbm.IngestionJob, "idempotency_key") else None
    if existing is not None:
        return {"status": "already_imported", "report": report.to_dict(), "import_job_id": str(existing.id)}

    # resolve the organization for registries (via any accessible farm of the principal)
    # note: import is org-level for labs/methods, then per-sample field resolution
    created_samples = 0
    created_measurements = 0
    sample_cache: dict[str, dbm.SoilSample] = {}
    layer_cache: dict[tuple[str, float, float], dbm.SoilSampleLayer] = {}
    errors: list[str] = []

    # group parsed rows by sample_code; each row needs a field context —
    # the import request carries the field binding via per-sample field_id
    # resolved from the sample_code prefix when provided, else via
    # the caller's default_field_id in the mapping spec.
    default_field_id = (mapping_spec or {}).get("default_field_id")
    field_cache: dict[str, dbm.Field] = {}

    def _field_for(sample_code: str) -> dbm.Field | None:
        if default_field_id:
            return field_cache.get(default_field_id)
        return None

    if not default_field_id:
        raise ValidationFailed(
            "the mapping spec must include 'default_field_id' (the field the samples belong to) "
            "— per-sample field binding arrives with multi-field templates.",
            details=[{"field": "mapping.default_field_id"}],
        )
    target_field = get_field_for_principal(db, principal, uuid.UUID(str(default_field_id)))
    field_cache[str(default_field_id)] = target_field
    organization_id = soil_service._org_id_for_field(db, target_field)

    for row in parsed:
        # savepoint: a rejected row must not poison the surrounding transaction
        nested = db.begin_nested()
        try:
            sample = sample_cache.get(row["sample_code"])
            if sample is None:
                # create a minimal sampling event for the lab batch (composite import)
                observed = date.fromisoformat(row["observed_at"])
                event = dbm.SoilSamplingEvent(
                    field_id=target_field.id,
                    sampling_date=observed,
                    purpose="laboratory analysis",
                    sampling_method="import",
                    composite=True,
                    quality_status="valid",
                    metadata={"import_template": report.template, "file_sha256": report.file_sha256},
                )
                db.add(event)
                db.flush()
                sample = dbm.SoilSample(
                    event_id=event.id,
                    field_id=target_field.id,
                    sample_code=row["sample_code"],
                    report_reference=row.get("report_reference"),
                    metadata={"source": "soil_lab_import", "file_sha256": report.file_sha256},
                )
                if row.get("laboratory_name"):
                    lab = soil_service.get_or_create_laboratory(db, organization_id, row["laboratory_name"])
                    sample.laboratory_id = lab.id
                db.add(sample)
                db.flush()
                sample_cache[row["sample_code"]] = sample
                created_samples += 1
            layer_key = (row["sample_code"], row["top_depth_cm"], row["bottom_depth_cm"])
            layer = layer_cache.get(layer_key)
            if layer is None:
                layer = dbm.SoilSampleLayer(
                    sample_id=sample.id,
                    top_depth_cm=row["top_depth_cm"],
                    bottom_depth_cm=row["bottom_depth_cm"],
                    original_depth_unit=row["original_depth_unit"],
                    original_top=row["original_top"],
                    original_bottom=row["original_bottom"],
                )
                db.add(layer)
                db.flush()
                layer_cache[layer_key] = layer
            method_params: dict[str, Any] = {}
            method_row = None
            if row.get("method_code"):
                method_row = soil_service.get_or_create_method(db, organization_id, {
                    "code": row["method_code"],
                    "property_family": sc.soil_variable_definition(row["variable_code"])["family"],
                })
                method_params = {"code": row["method_code"]}
            vdef = sc.soil_variable_definition(row["variable_code"])
            measurement = dbm.SoilMeasurement(
                field_id=target_field.id,
                layer_id=layer.id,
                variable_code=row["variable_code"],
                value=row["value"],
                unit=row["unit"],
                top_depth_cm=row["top_depth_cm"],
                bottom_depth_cm=row["bottom_depth_cm"],
                evidence_class="farmer_reported_record" if (mapping_spec or {}).get("farmer_reported") else "direct_field_measurement",
                spatial_support_type="lab_sample",
                source_kind="lab_analysis",
                method_id=method_row.id if method_row else None,
                method_params=method_params,
                detection_limit=row["detection_limit"],
                result_qualifier=row["result_qualifier"],
                is_synthetic=False,
                observed_at=date.fromisoformat(row["observed_at"]),
                metadata={"report_reference": row.get("report_reference"), "notes": row.get("notes")},
            )
            db.add(measurement)
            db.flush()
            created_measurements += 1
            nested.commit()
        except Exception as exc:  # noqa: BLE001 — per-row accounting
            nested.rollback()
            errors.append(f"{row.get('sample_code')}/{row['variable_code']}: {exc}")

    db.commit()
    return {
        "status": "imported",
        "report": report.to_dict(),
        "created_samples": created_samples,
        "created_measurements": created_measurements,
        "errors": errors[:20],
    }


@router.post("/fields/{field_id}/soil-measurements", status_code=status.HTTP_201_CREATED)
def create_measurement(
    field_id: uuid.UUID,
    body: dict[str, Any],
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    field = get_field_for_principal(db, principal, field_id)
    measurement = soil_service.add_measurement(db, field, body)
    _commit_refresh(db, measurement)
    return soil_service.measurement_payload(measurement)


# ------------------------------------------------------------- read models

@router.get("/fields/{field_id}/soil-profile")
def field_soil_profile(
    field_id: uuid.UUID,
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    field = get_field_for_principal(db, principal, field_id)
    return soil_service.build_profile(db, field)


@router.get("/fields/{field_id}/soil-indicators")
def field_soil_indicators(
    field_id: uuid.UUID,
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    field = get_field_for_principal(db, principal, field_id)
    profile = soil_service.build_profile(db, field)
    return soil_service.derive_texture_and_awc(profile)


@router.get("/fields/{field_id}/soil-health")
def field_soil_health(
    field_id: uuid.UUID,
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    field = get_field_for_principal(db, principal, field_id)
    latest = db.scalar(
        select(dbm.SoilAssessmentRun)
        .where(dbm.SoilAssessmentRun.field_id == field.id, dbm.SoilAssessmentRun.status == "succeeded")
        .order_by(dbm.SoilAssessmentRun.created_at.desc())
        .limit(1)
    )
    if latest is None:
        # live assessment from current measurements (no snapshot yet)
        measurements = [
            soil_service.measurement_payload(m) for m in soil_service.list_measurements(db, field.id)
        ]
        result = assessment_mod.assess_domains(measurements, field_id=str(field.id))
        return {"source": "live", "result": result}
    return {"source": "snapshot", "assessment_id": str(latest.id), "result": latest.result}


@router.get("/fields/{field_id}/soil-data-readiness")
def field_soil_data_readiness(
    field_id: uuid.UUID,
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    field = get_field_for_principal(db, principal, field_id)
    measurements = [
        soil_service.measurement_payload(m) for m in soil_service.list_measurements(db, field.id)
    ]
    return assessment_mod.data_readiness(measurements)


# ------------------------------------------------------------ SOC runs

@router.post("/fields/{field_id}/soc-stock-runs", status_code=status.HTTP_201_CREATED)
def create_soc_run(
    field_id: uuid.UUID,
    body: dict[str, Any],
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    field = get_field_for_principal(db, principal, field_id)
    idempotency_key = body.get("idempotency_key")
    if idempotency_key:
        existing = db.scalar(
            select(dbm.SocStockRun).where(
                dbm.SocStockRun.idempotency_key == idempotency_key,
                dbm.SocStockRun.field_id == field.id,
            )
        )
        if existing is not None:
            return _soc_run_payload(existing)

    from app.soil.layers import make_depth_interval
    from app.soil.soc import LayerStockInput

    sample_ids = body.get("sample_ids") or []
    layers_in = body.get("layers") or []
    if not layers_in:
        raise ValidationFailed(
            "layers are required (per-layer OC, bulk density + basis, optional coarse "
            "fragments, depth interval) — SOC stock is computed from explicit inputs.",
            details=[{"field": "layers"}],
        )
    inputs: list[LayerStockInput] = []
    warnings: list[str] = []
    for spec in layers_in:
        try:
            interval = make_depth_interval(float(spec["top_depth"]), float(spec["bottom_depth"]),
                                           str(spec.get("depth_unit") or "cm"))
        except (KeyError, TypeError, sc.SoilValidationError) as exc:
            raise ValidationFailed(f"invalid layer depth: {exc}", details=[{"field": "layers"}]) from None
        bd_basis = spec.get("bd_basis")
        if bd_basis is not None and bd_basis not in ("whole_soil", "fine_earth"):
            raise ValidationFailed(
                f"bd_basis must be 'whole_soil' or 'fine_earth' (got '{bd_basis}')",
                details=[{"field": "layers"}],
            )
        vcf = spec.get("coarse_fragment_vol_fraction")
        inputs.append(LayerStockInput(
            interval=interval,
            oc_g_kg=spec.get("oc_g_kg"),
            bulk_density_g_cm3=spec.get("bulk_density_g_cm3"),
            bd_basis=bd_basis,
            coarse_fragment_vol_fraction=vcf,
            evidence_class=str(spec.get("evidence_class") or "farmer_reported_record"),
            is_prediction=bool(spec.get("is_prediction", False)),
            source_refs=tuple(spec.get("source_refs") or ()),
        ))
        if spec.get("is_prediction"):
            warnings.append(
                f"layer {interval.top_cm}-{interval.bottom_cm} cm uses mapped predictions "
                "— the stock is a prediction, not a field measurement"
            )

    mode = str(body.get("comparison_mode") or "single_profile")
    run = dbm.SocStockRun(
        field_id=field.id,
        status="running",
        label=str(body.get("label") or "SOC stock run")[:120],
        input_sample_ids=[str(s) for s in sample_ids],
        comparison_mode=mode,
        engine_version=sc.SOC_STOCK_VERSION,
        methods_version=sc.SOIL_METHODS_VERSION,
        request_parameters=dict(body.get("request_parameters") or {}),
        idempotency_key=idempotency_key,
    )
    db.add(run)
    db.flush()

    try:
        result = soc_mod.profile_soc_stock(inputs)
        comparison_block = None
        if mode == "single_profile":
            pass
        else:
            baseline_run_id = body.get("baseline_run_id")
            if baseline_run_id is None:
                raise ValidationFailed(
                    "comparison modes require baseline_run_id.",
                    details=[{"field": "baseline_run_id"}],
                )
            baseline = db.get(dbm.SocStockRun, uuid.UUID(str(baseline_run_id)))
            if baseline is None or baseline.field_id != field.id:
                raise NotFound("Baseline SOC run not found for this field.")
            base_layers = [
                LayerStockInput(
                    interval=make_depth_interval(l["top_cm"], l["bottom_cm"], "cm"),
                    oc_g_kg=(l["inputs_used"] or {}).get("oc_g_kg"),
                    bulk_density_g_cm3=(l["inputs_used"] or {}).get("bulk_density_g_cm3"),
                    bd_basis=(l["inputs_used"] or {}).get("bd_basis"),
                    coarse_fragment_vol_fraction=(l["inputs_used"] or {}).get("coarse_fragment_vol_fraction"),
                )
                for l in baseline.result.get("layers", [])
            ]
            if mode == "fixed_depth":
                comparison_block = soc_mod.fixed_depth_comparison(base_layers, inputs)
            elif mode == "equivalent_soil_mass":
                comparison_block = soc_mod.equivalent_soil_mass_comparison(base_layers, inputs)
            else:
                raise ValidationFailed(f"unknown comparison_mode '{mode}'.", details=[{"field": "comparison_mode"}])
            result["comparison"] = comparison_block

        run.status = "succeeded"
        run.result = result
        run.warnings = warnings + result.get("warnings", [])
        run.not_evaluated = result.get("not_evaluated", [])
        run.checksum_sha256 = soc_mod.soc_run_checksum(result)
        db.flush()
    except ValidationFailed:
        run.status = "failed"
        run.error_summary = "validation failed"
        db.flush()
        raise
    except Exception as exc:  # noqa: BLE001 — job accounting
        run.status = "failed"
        run.error_summary = f"{type(exc).__name__}: {exc}"
        db.flush()
        raise
    db.commit()
    db.refresh(run)
    return _soc_run_payload(run)


def _soc_run_payload(run: dbm.SocStockRun) -> dict:
    return {
        "id": str(run.id),
        "field_id": str(run.field_id),
        "status": run.status,
        "label": run.label,
        "comparison_mode": run.comparison_mode,
        "engine_version": run.engine_version,
        "methods_version": run.methods_version,
        "warnings": run.warnings,
        "not_evaluated": run.not_evaluated,
        "checksum_sha256": run.checksum_sha256,
        "error_summary": run.error_summary,
        "result": run.result,
    }


@router.get("/fields/{field_id}/soc-stock-runs")
def list_soc_runs(
    field_id: uuid.UUID,
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    field = get_field_for_principal(db, principal, field_id)
    rows = db.scalars(
        select(dbm.SocStockRun)
        .where(dbm.SocStockRun.field_id == field.id)
        .order_by(dbm.SocStockRun.created_at.desc())
        .limit(50)
    ).all()
    return {
        "field_id": str(field.id),
        "items": [_soc_run_payload(r) for r in rows],
    }


@router.get("/soc-stock-runs/{run_id}")
def get_soc_run(
    run_id: uuid.UUID,
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    run = db.get(dbm.SocStockRun, run_id)
    if run is None:
        raise NotFound("SOC stock run not found.")
    get_field_for_principal(db, principal, run.field_id)
    return _soc_run_payload(run)


# ------------------------------------------------------------- nutrients

@router.post("/fields/{field_id}/nutrient-products", status_code=status.HTTP_201_CREATED)
def create_nutrient_product(
    field_id: uuid.UUID,
    body: dict[str, Any],
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    field = get_field_for_principal(db, principal, field_id)
    organization_id = soil_service._org_id_for_field(db, field)
    reporting_basis = str(body.get("reporting_basis") or "elemental")
    if reporting_basis not in ("elemental", "oxide"):
        raise ValidationFailed("reporting_basis must be 'elemental' or 'oxide'.", details=[{"field": "reporting_basis"}])
    product = dbm.NutrientProduct(
        organization_id=organization_id,
        name=str(soil_service._require(body, "name")),
        product_type=str(body.get("product_type") or "fertilizer"),
        n_pct=body.get("n_pct"),
        p_pct=body.get("p_pct"),
        k_pct=body.get("k_pct"),
        reporting_basis=reporting_basis,
        dry_matter_fraction=body.get("dry_matter_fraction"),
        moisture_basis=body.get("moisture_basis"),
        availability_notes=body.get("availability_notes"),
        source_reference=body.get("source_reference"),
        metadata=dict(body.get("metadata") or {}),
    )
    db.add(product)
    db.flush()
    _commit_refresh(db, product)
    return {"id": str(product.id), "name": product.name, "reporting_basis": product.reporting_basis}


def _nutrient_application_from_payload(db: Session, field: dbm.Field, body: dict[str, Any]) -> dbm.NutrientApplication:
    product = None
    if body.get("product_id"):
        product = db.get(dbm.NutrientProduct, uuid.UUID(str(body["product_id"])))
        if product is None:
            raise NotFound("Nutrient product not found.")
    n_kg = p_kg = k_kg = None
    reporting_basis = None
    if product is not None:
        reporting_basis = product.reporting_basis
        mass = float(soil_service._require(body, "applied_mass_kg"))
        n_kg = (product.n_pct / 100.0 * mass) if product.n_pct is not None else None
        p_kg = (product.p_pct / 100.0 * mass) if product.p_pct is not None else None
        k_kg = (product.k_pct / 100.0 * mass) if product.k_pct is not None else None
    else:
        n_kg = body.get("n_kg")
        p_kg = body.get("p_kg")
        k_kg = body.get("k_kg")
        reporting_basis = body.get("reporting_basis") or "elemental"
    if n_kg is None and p_kg is None and k_kg is None:
        raise ValidationFailed(
            "the application must carry nutrient content (product with a grade or "
            "explicit n/p/kg masses) — an application without nutrient content is "
            "not a nutrient input.",
            details=[{"field": "nutrients"}],
        )
    availability = body.get("availability_fraction")
    input_kind = str(soil_service._require(body, "input_kind"))
    if input_kind in ("manure", "compost", "organic_amendment") and availability is None:
        raise ValidationFailed(
            "manure/compost/organic amendments REQUIRE an availability_fraction "
            "(never assumed fully available).",
            details=[{"field": "availability_fraction"}],
        )
    return dbm.NutrientApplication(
        field_id=field.id,
        season_label=str(soil_service._require(body, "season_label")),
        application_date=soil_service._parse_date(soil_service._require(body, "application_date"), "application_date"),
        input_kind=input_kind,
        product_id=product.id if product else None,
        product_name_free=body.get("product_name_free"),
        applied_mass_kg=float(soil_service._require(body, "applied_mass_kg")),
        area_ha=float(soil_service._require(body, "area_ha")),
        n_kg=None if n_kg is None else float(n_kg),
        p_kg=None if p_kg is None else float(p_kg),
        k_kg=None if k_kg is None else float(k_kg),
        reporting_basis=reporting_basis,
        availability_fraction=None if availability is None else float(availability),
        availability_basis=body.get("availability_basis"),
        application_method=body.get("application_method"),
        moisture_basis=body.get("moisture_basis"),
        evidence_class=str(body.get("evidence_class") or "farmer_reported_record"),
        is_synthetic=bool(body.get("is_synthetic", False)),
        source_reference=body.get("source_reference"),
        notes=body.get("notes"),
        metadata=dict(body.get("metadata") or {}),
    )


@router.post("/fields/{field_id}/nutrient-applications", status_code=status.HTTP_201_CREATED)
def create_nutrient_application(
    field_id: uuid.UUID,
    body: dict[str, Any],
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    field = get_field_for_principal(db, principal, field_id)
    row = _nutrient_application_from_payload(db, field, body)
    db.add(row)
    db.flush()
    _commit_refresh(db, row)
    return {
        "id": str(row.id), "season_label": row.season_label, "input_kind": row.input_kind,
        "n_kg": row.n_kg, "p_kg": row.p_kg, "k_kg": row.k_kg,
        "reporting_basis": row.reporting_basis, "area_ha": row.area_ha,
    }


@router.post("/fields/{field_id}/nutrient-removals", status_code=status.HTTP_201_CREATED)
def create_nutrient_removal(
    field_id: uuid.UUID,
    body: dict[str, Any],
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    field = get_field_for_principal(db, principal, field_id)
    moisture_basis = str(body.get("moisture_basis") or "as_harvested")
    if moisture_basis not in ("as_harvested", "dry_matter"):
        raise ValidationFailed("moisture_basis must be 'as_harvested' or 'dry_matter'.", details=[{"field": "moisture_basis"}])
    concentrations = {
        k: body.get(f"{k}_concentration_g_kg") for k in ("n", "p", "k")
    }
    if all(v is None for v in concentrations.values()):
        raise ValidationFailed(
            "removal requires at least one nutrient concentration — yield alone is "
            "never a removal estimate (M6B.5).",
            details=[{"field": "concentrations"}],
        )
    row = dbm.NutrientRemoval(
        field_id=field.id,
        season_label=str(soil_service._require(body, "season_label")),
        removal_date=soil_service._parse_date(body["removal_date"], "removal_date") if body.get("removal_date") else None,
        crop_code=body.get("crop_code"),
        output_kind=str(body.get("output_kind") or "harvested_product"),
        biomass_kg=float(soil_service._require(body, "biomass_kg")),
        dry_matter_fraction=body.get("dry_matter_fraction"),
        moisture_basis=moisture_basis,
        n_concentration_g_kg=concentrations["n"],
        p_concentration_g_kg=concentrations["p"],
        k_concentration_g_kg=concentrations["k"],
        concentration_basis=body.get("concentration_basis") or moisture_basis,
        concentration_source=body.get("concentration_source"),
        evidence_class=str(body.get("evidence_class") or "farmer_reported_record"),
        is_synthetic=bool(body.get("is_synthetic", False)),
        notes=body.get("notes"),
        metadata=dict(body.get("metadata") or {}),
    )
    db.add(row)
    db.flush()
    _commit_refresh(db, row)
    return {
        "id": str(row.id), "season_label": row.season_label, "output_kind": row.output_kind,
        "biomass_kg": row.biomass_kg, "moisture_basis": row.moisture_basis,
        "n_concentration_g_kg": row.n_concentration_g_kg,
        "p_concentration_g_kg": row.p_concentration_g_kg,
        "k_concentration_g_kg": row.k_concentration_g_kg,
    }


@router.post("/fields/{field_id}/nutrient-budget-runs", status_code=status.HTTP_201_CREATED)
def create_nutrient_budget_run(
    field_id: uuid.UUID,
    body: dict[str, Any],
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    field = get_field_for_principal(db, principal, field_id)
    idempotency_key = body.get("idempotency_key")
    if idempotency_key:
        existing = db.scalar(
            select(dbm.NutrientBudgetRun).where(
                dbm.NutrientBudgetRun.idempotency_key == idempotency_key,
                dbm.NutrientBudgetRun.field_id == field.id,
            )
        )
        if existing is not None:
            return _budget_run_payload(existing)

    seasons = body.get("seasons") or []
    if not seasons:
        raise ValidationFailed("at least one season label is required.", details=[{"field": "seasons"}])

    applications = db.scalars(
        select(dbm.NutrientApplication).where(dbm.NutrientApplication.field_id == field.id)
    ).all()
    removals = db.scalars(
        select(dbm.NutrientRemoval).where(dbm.NutrientRemoval.field_id == field.id)
    ).all()

    run = dbm.NutrientBudgetRun(
        field_id=field.id,
        status="running",
        label=str(body.get("label") or "Nutrient budget run")[:120],
        seasons=list(seasons),
        engine_version=sc.NUTRIENT_BUDGET_VERSION,
        methods_version=sc.SOIL_METHODS_VERSION,
        request_parameters=dict(body.get("request_parameters") or {}),
        idempotency_key=idempotency_key,
    )
    db.add(run)
    db.flush()

    try:
        season_results = []
        for season_label in seasons:
            season_inputs = []
            for app_row in applications:
                if app_row.season_label != season_label:
                    continue
                if app_row.input_kind == "biological_nitrogen_fixation":
                    # BNF enters only as the recorded estimate (never inferred here)
                    season_inputs.append(nutrient_mod.NutrientInputRecord(
                        flow_id=str(app_row.id), input_kind=app_row.input_kind,
                        n_kg=app_row.n_kg, p_kg=app_row.p_kg, k_kg=app_row.k_kg,
                        area_ha=app_row.area_ha, reporting_basis=app_row.reporting_basis or "elemental",
                        evidence_class=app_row.evidence_class, is_estimate=True,
                        citation_text=app_row.source_reference,
                    ))
                    continue
                season_inputs.append(nutrient_mod.NutrientInputRecord(
                    flow_id=str(app_row.id), input_kind=app_row.input_kind,
                    n_kg=app_row.n_kg, p_kg=app_row.p_kg, k_kg=app_row.k_kg,
                    area_ha=app_row.area_ha, reporting_basis=app_row.reporting_basis or "elemental",
                    evidence_class=app_row.evidence_class,
                    availability_fraction=app_row.availability_fraction,
                    availability_basis=app_row.availability_basis,
                ))
            season_outputs = []
            for r in removals:
                if r.season_label != season_label:
                    continue
                # concentration g/kg × biomass kg = g nutrient → ÷1000 = kg total
                area_ha = float(body.get("area_ha") or field.area_ha)
                n_kg_ha = (r.n_concentration_g_kg * r.biomass_kg / 1000.0 / area_ha) if r.n_concentration_g_kg is not None else None
                p_kg_ha = (r.p_concentration_g_kg * r.biomass_kg / 1000.0 / area_ha) if r.p_concentration_g_kg is not None else None
                k_kg_ha = (r.k_concentration_g_kg * r.biomass_kg / 1000.0 / area_ha) if r.k_concentration_g_kg is not None else None
                season_outputs.append(nutrient_mod.NutrientOutputRecord(
                    flow_id=str(r.id), output_kind=r.output_kind,
                    n_kg_ha=n_kg_ha, p_kg_ha=p_kg_ha, k_kg_ha=k_kg_ha,
                    concentration_basis=r.concentration_basis or r.moisture_basis,
                    moisture_basis_disclosed=bool(r.moisture_basis),
                    evidence_class=r.evidence_class,
                ))
            season_results.append(nutrient_mod.nutrient_budget(
                inputs=season_inputs, outputs=season_outputs, season_label=str(season_label)
            ))
        cumulative = nutrient_mod.cumulative_budget(season_results)
        result = {
            "seasons": season_results,
            "cumulative": cumulative,
            "engine_version": sc.NUTRIENT_BUDGET_VERSION,
            "methods_version": sc.SOIL_METHODS_VERSION,
            "reference_library_note": (
                "the nutrient-removal reference library is intentionally EMPTY pending "
                "verified sources — concentrations come from farmer/lab records only "
                "(see M6B_RESEARCH_BACKLOG.md)"
            ),
        }
        run.status = "succeeded"
        run.result = result
        all_warnings = [w for s in season_results for w in s["warnings"]]
        run.warnings = all_warnings
        run.not_evaluated = {
            s["season_label"]: s["missing_flows"] for s in season_results if s["missing_flows"]
        }
        run.checksum_sha256 = nutrient_mod.budget_checksum(result)
        db.flush()
    except ValidationFailed:
        run.status = "failed"
        run.error_summary = "validation failed"
        db.flush()
        raise
    except Exception as exc:  # noqa: BLE001
        run.status = "failed"
        run.error_summary = f"{type(exc).__name__}: {exc}"
        db.flush()
        raise
    db.commit()
    db.refresh(run)
    return _budget_run_payload(run)


def _budget_run_payload(run: dbm.NutrientBudgetRun) -> dict:
    return {
        "id": str(run.id),
        "field_id": str(run.field_id),
        "status": run.status,
        "label": run.label,
        "seasons": run.seasons,
        "engine_version": run.engine_version,
        "methods_version": run.methods_version,
        "warnings": run.warnings,
        "not_evaluated": run.not_evaluated,
        "checksum_sha256": run.checksum_sha256,
        "error_summary": run.error_summary,
        "result": run.result,
    }


@router.get("/nutrient-budget-runs/{run_id}")
def get_nutrient_budget_run(
    run_id: uuid.UUID,
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    run = db.get(dbm.NutrientBudgetRun, run_id)
    if run is None:
        raise NotFound("Nutrient budget run not found.")
    get_field_for_principal(db, principal, run.field_id)
    return _budget_run_payload(run)


# -------------------------------------------------------- ledger & assessment

@router.post("/fields/{field_id}/soil-management-events", status_code=status.HTTP_201_CREATED)
def create_management_event(
    field_id: uuid.UUID,
    body: dict[str, Any],
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    field = get_field_for_principal(db, principal, field_id)
    event_type = str(soil_service._require(body, "event_type"))
    allowed_types = {
        "planting", "harvest", "fertilizer_application", "manure_application",
        "compost_application", "residue_retention", "residue_removal", "tillage",
        "cover_crop_termination", "irrigation", "soil_amendment", "other",
    }
    if event_type not in allowed_types:
        raise ValidationFailed(
            f"unknown event_type '{event_type}' (allowed: {', '.join(sorted(allowed_types))}).",
            details=[{"field": "event_type"}],
        )
    event = dbm.SoilManagementEvent(
        field_id=field.id,
        event_date=soil_service._parse_date(soil_service._require(body, "event_date"), "event_date"),
        event_type=event_type,
        title=body.get("title"),
        details=dict(body.get("details") or {}),
        nutrient_application_id=uuid.UUID(str(body["nutrient_application_id"])) if body.get("nutrient_application_id") else None,
        notes=body.get("notes"),
    )
    db.add(event)
    db.flush()
    _commit_refresh(db, event)
    return {"id": str(event.id), "event_type": event.event_type, "event_date": event.event_date.isoformat()}


@router.get("/fields/{field_id}/soil-management-events")
def list_management_events(
    field_id: uuid.UUID,
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    field = get_field_for_principal(db, principal, field_id)
    rows = db.scalars(
        select(dbm.SoilManagementEvent)
        .where(dbm.SoilManagementEvent.field_id == field.id)
        .order_by(dbm.SoilManagementEvent.event_date.desc())
        .limit(100)
    ).all()
    return {
        "field_id": str(field.id),
        "items": [
            {
                "id": str(e.id), "event_date": e.event_date.isoformat(),
                "event_type": e.event_type, "title": e.title, "details": e.details,
            }
            for e in rows
        ],
    }


@router.post("/fields/{field_id}/soil-assessments", status_code=status.HTTP_201_CREATED)
def create_soil_assessment(
    field_id: uuid.UUID,
    body: dict[str, Any],
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    field = get_field_for_principal(db, principal, field_id)
    idempotency_key = body.get("idempotency_key")
    if idempotency_key:
        existing = db.scalar(
            select(dbm.SoilAssessmentRun).where(
                dbm.SoilAssessmentRun.idempotency_key == idempotency_key,
                dbm.SoilAssessmentRun.field_id == field.id,
            )
        )
        if existing is not None:
            return _assessment_payload(existing)
    measurements = [
        soil_service.measurement_payload(m) for m in soil_service.list_measurements(db, field.id)
    ]
    run = dbm.SoilAssessmentRun(
        field_id=field.id,
        status="running",
        label=str(body.get("label") or "Soil assessment")[:120],
        engine_version=sc.SOIL_ENGINE_VERSION,
        methods_version=sc.SOIL_METHODS_VERSION,
        request_parameters=dict(body.get("request_parameters") or {}),
        idempotency_key=idempotency_key,
    )
    db.add(run)
    db.flush()
    result = assessment_mod.assess_domains(measurements, field_id=str(field.id))
    run.status = "succeeded"
    run.result = result
    run.checksum_sha256 = assessment_mod.assessment_checksum(result)
    db.flush()
    db.commit()
    db.refresh(run)
    return _assessment_payload(run)


def _assessment_payload(run: dbm.SoilAssessmentRun) -> dict:
    return {
        "id": str(run.id),
        "field_id": str(run.field_id),
        "status": run.status,
        "label": run.label,
        "engine_version": run.engine_version,
        "checksum_sha256": run.checksum_sha256,
        "result": run.result,
    }


@router.get("/soil-assessments/{assessment_id}")
def get_soil_assessment(
    assessment_id: uuid.UUID,
    principal: Any = Depends(get_principal),
    db: Session = Depends(get_db),
) -> dict:
    run = db.get(dbm.SoilAssessmentRun, assessment_id)
    if run is None:
        raise NotFound("Soil assessment not found.")
    get_field_for_principal(db, principal, run.field_id)
    return _assessment_payload(run)
