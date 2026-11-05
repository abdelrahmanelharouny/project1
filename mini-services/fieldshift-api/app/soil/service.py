"""Soil service — the DB bridge for the soil intelligence engine (M6B Step 3).

Mirrors `app.water.service`'s responsibilities: validate request payloads,
normalize to the canonical contracts, persist, and assemble read-models
(profile, indicators). Honesty rules: measured vs mapped stay distinct
(ADR-0022), method metadata is mandatory for chemical comparisons
(ADR-0023), and every read-model is engine-version-pinned.
"""

from __future__ import annotations

import uuid
from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import NotFound, ValidationFailed
from app.db import models as dbm
from app.soil import contracts as sc
from app.soil.layers import DepthInterval, make_depth_interval, validate_layer_set
from app.soil.physical import classify_usda_texture, layer_awc
from app.soil.chemistry import validate_ph_measurement

ALLOWED_EVIDENCE_CLASSES = {
    "direct_field_measurement", "farmer_reported_record", "global_soil_prediction",
    "synthetic_test_data", "curated_agronomic_reference",
}
ALLOWED_SOURCE_KINDS = {"lab_analysis", "farmer_report", "soilgrids_profile", "synthetic_fixture"}


def _require(payload: dict[str, Any], key: str) -> Any:
    value = payload.get(key)
    if value is None or (isinstance(value, str) and not value.strip()):
        raise ValidationFailed(
            f"'{key}' is required.",
            details=[{"field": key}],
        )
    return value


def _parse_date(value: Any, field_name: str) -> date:
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError):
        raise ValidationFailed(
            f"'{field_name}' must be an ISO date (YYYY-MM-DD).",
            details=[{"field": field_name}],
        ) from None


def _org_id_for_field(db: Session, field: dbm.Field) -> uuid.UUID:
    """The tenant (organization) of a field via its farm membership chain."""
    farm = db.get(dbm.Farm, field.farm_id)
    if farm is None:
        raise NotFound("Farm not found.")
    return farm.organization_id


# ------------------------------------------------------------- registries

def get_or_create_laboratory(db: Session, organization_id: uuid.UUID, name: str, **kw: Any) -> dbm.SoilLaboratory:
    row = db.scalar(
        select(dbm.SoilLaboratory).where(
            dbm.SoilLaboratory.organization_id == organization_id,
            dbm.SoilLaboratory.name == name,
        )
    )
    if row is not None:
        return row
    row = dbm.SoilLaboratory(organization_id=organization_id, name=name, **kw)
    db.add(row)
    db.flush()
    return row


def get_or_create_method(db: Session, organization_id: uuid.UUID, descriptor: dict[str, Any]) -> dbm.SoilAnalyticalMethod:
    code = str(_require(descriptor, "code"))
    row = db.scalar(
        select(dbm.SoilAnalyticalMethod).where(
            dbm.SoilAnalyticalMethod.organization_id == organization_id,
            dbm.SoilAnalyticalMethod.code == code,
        )
    )
    if row is not None:
        return row
    row = dbm.SoilAnalyticalMethod(
        organization_id=organization_id,
        code=code,
        property_family=str(_require(descriptor, "property_family")),
        analytical_method=descriptor.get("analytical_method"),
        extraction_method=descriptor.get("extraction_method"),
        extractant=descriptor.get("extractant"),
        soil_solution_ratio=descriptor.get("soil_solution_ratio"),
        temperature_note=descriptor.get("temperature_note"),
        reporting_basis=descriptor.get("reporting_basis"),
        reference_text=descriptor.get("reference_text"),
    )
    db.add(row)
    db.flush()
    return row


# ---------------------------------------------------------- sampling write path

def create_sampling_event(
    db: Session, field: dbm.Field, payload: dict[str, Any]
) -> dbm.SoilSamplingEvent:
    gps_lat = payload.get("gps_lat")
    gps_lon = payload.get("gps_lon")
    if gps_lat is not None and not -90 <= float(gps_lat) <= 90:
        raise ValidationFailed("gps_lat must be within [-90, 90].", details=[{"field": "gps_lat"}])
    if gps_lon is not None and not -180 <= float(gps_lon) <= 180:
        raise ValidationFailed("gps_lon must be within [-180, 180].", details=[{"field": "gps_lon"}])
    event = dbm.SoilSamplingEvent(
        field_id=field.id,
        sampling_date=_parse_date(_require(payload, "sampling_date"), "sampling_date"),
        purpose=payload.get("purpose"),
        sampling_method=payload.get("sampling_method"),
        sampling_depth_note=payload.get("sampling_depth_note"),
        management_zone=payload.get("management_zone"),
        gps_lat=payload.get("gps_lat"),
        gps_lon=payload.get("gps_lon"),
        composite=bool(payload.get("composite", False)),
        subsample_count=payload.get("subsample_count"),
        equipment=payload.get("equipment"),
        sample_handling=payload.get("sample_handling"),
        sample_preparation=payload.get("sample_preparation"),
        collected_by=payload.get("collected_by"),
        quality_status=payload.get("quality_status") or "valid",
        notes=payload.get("notes"),
        metadata=dict(payload.get("metadata") or {}),
    )
    db.add(event)
    db.flush()
    return event


def create_sample(
    db: Session, field: dbm.Field, payload: dict[str, Any]
) -> dbm.SoilSample:
    event_id = _require(payload, "event_id")
    event = db.get(dbm.SoilSamplingEvent, uuid.UUID(str(event_id)))
    if event is None or event.field_id != field.id:
        raise NotFound("Sampling event not found for this field.")

    laboratory = None
    if payload.get("laboratory_name"):
        organization_id = _org_id_for_field(db, field)
        laboratory = get_or_create_laboratory(db, organization_id, str(payload["laboratory_name"]))

    sample = dbm.SoilSample(
        event_id=event.id,
        field_id=field.id,
        sample_code=str(_require(payload, "sample_code")),
        composite_parent_id=uuid.UUID(str(payload["composite_parent_id"])) if payload.get("composite_parent_id") else None,
        laboratory_id=laboratory.id if laboratory else None,
        report_reference=payload.get("report_reference"),
        received_date=_parse_date(payload["received_date"], "received_date") if payload.get("received_date") else None,
        reported_date=_parse_date(payload["reported_date"], "reported_date") if payload.get("reported_date") else None,
        notes=payload.get("notes"),
        metadata=dict(payload.get("metadata") or {}),
    )
    db.add(sample)
    db.flush()
    return sample


def add_sample_layer(
    db: Session, sample: dbm.SoilSample, payload: dict[str, Any]
) -> dbm.SoilSampleLayer:
    top = payload.get("top_depth")
    bottom = payload.get("bottom_depth")
    unit = str(payload.get("depth_unit") or "cm")
    if top is None or bottom is None:
        raise ValidationFailed(
            "layer needs top_depth and bottom_depth.",
            details=[{"field": "depths"}],
        )
    try:
        interval: DepthInterval = make_depth_interval(float(top), float(bottom), unit)
    except sc.SoilValidationError as exc:
        raise ValidationFailed(str(exc), details=[{"field": "depths"}]) from None
    layer = dbm.SoilSampleLayer(
        sample_id=sample.id,
        top_depth_cm=interval.top_cm,
        bottom_depth_cm=interval.bottom_cm,
        original_depth_unit=interval.original_unit,
        original_top=interval.original_top,
        original_bottom=interval.original_bottom,
        layer_label=payload.get("layer_label"),
        notes=payload.get("notes"),
    )
    db.add(layer)
    db.flush()
    return layer


def add_measurement(
    db: Session,
    field: dbm.Field,
    payload: dict[str, Any],
) -> dbm.SoilMeasurement:
    """Create one soil measurement with the mandatory method identity.

    ADR-0023: chemical measurements (pH, EC, extractable nutrients) MUST carry
    method metadata (method descriptor inline or method_id) — measurements
    without an identity are rejected, not silently 'defaulted'."""
    variable_code = str(_require(payload, "variable_code"))
    vdef = sc.soil_variable_definition(variable_code)
    if vdef is None:
        raise ValidationFailed(
            f"Unknown soil variable '{variable_code}'.",
            details=[{"field": "variable_code", "reason": "not in the canonical soil dictionary"}],
        )

    layer_id = payload.get("layer_id")
    top = payload.get("top_depth_cm")
    bottom = payload.get("bottom_depth_cm")
    if layer_id:
        layer = db.get(dbm.SoilSampleLayer, uuid.UUID(str(layer_id)))
        if layer is None:
            raise NotFound("Sample layer not found.")
        sample = db.get(dbm.SoilSample, layer.sample_id)
        if sample is None or sample.field_id != field.id:
            raise NotFound("Layer does not belong to this field.")
        top, bottom = layer.top_depth_cm, layer.bottom_depth_cm
    else:
        if top is None or bottom is None:
            raise ValidationFailed(
                "measurement needs layer_id or explicit top_depth_cm/bottom_depth_cm.",
                details=[{"field": "depths"}],
            )
        try:
            interval = make_depth_interval(float(top), float(bottom), "cm")
        except sc.SoilValidationError as exc:
            raise ValidationFailed(str(exc), details=[{"field": "depths"}]) from None
        top, bottom = interval.top_cm, interval.bottom_cm

    evidence_class = str(payload.get("evidence_class") or "farmer_reported_record")
    if evidence_class not in ALLOWED_EVIDENCE_CLASSES:
        raise ValidationFailed(
            f"unknown evidence_class '{evidence_class}'.",
            details=[{"field": "evidence_class"}],
        )
    source_kind = str(payload.get("source_kind") or ("lab_analysis" if layer_id else "farmer_report"))
    if source_kind not in ALLOWED_SOURCE_KINDS:
        raise ValidationFailed(
            f"unknown source_kind '{source_kind}'.",
            details=[{"field": "source_kind"}],
        )
    if source_kind == "soilgrids_profile" and evidence_class != "global_soil_prediction":
        raise ValidationFailed(
            "soilgrids_profile rows must carry evidence_class 'global_soil_prediction' "
            "(mapped ≠ measured is enforced structurally).",
            details=[{"field": "evidence_class"}],
        )

    value = payload.get("value")
    if value is not None:
        try:
            value = float(value)
        except (TypeError, ValueError):
            raise ValidationFailed("value must be a number.", details=[{"field": "value"}]) from None

    method_params = dict(payload.get("method_params") or {})
    method_id = None
    if payload.get("method"):
        organization_id = _org_id_for_field(db, field)
        method_row = get_or_create_method(db, organization_id, dict(payload["method"]))
        method_id = method_row.id
        method_params.setdefault("code", method_row.code)
    elif payload.get("method_params"):
        # inline identity only — still recorded
        pass
    if vdef["family"] in ("ph", "salinity", "nitrogen", "phosphorus", "potassium", "cec") and not method_params and method_id is None:
        raise ValidationFailed(
            f"variable '{variable_code}' ({vdef['family']}) requires method metadata "
            "(method descriptor or method_params) — analytically unidentified "
            "measurements are not accepted (ADR-0023).",
            details=[{"field": "method"}],
        )

    if vdef["family"] == "ph" and value is not None:
        medium = str(method_params.get("medium") or "other")
        try:
            validate_ph_measurement(value, medium, method_params.get("soil_solution_ratio"))
        except sc.SoilValidationError as exc:
            raise ValidationFailed(str(exc), details=[{"field": "value"}]) from None

    measurement = dbm.SoilMeasurement(
        field_id=field.id,
        layer_id=layer_id,
        variable_code=variable_code,
        value=value,
        unit=str(payload.get("unit") or vdef["unit"]),
        top_depth_cm=top,
        bottom_depth_cm=bottom,
        evidence_class=evidence_class,
        spatial_support_type=payload.get("spatial_support_type") or ("lab_sample" if layer_id else "field_intersection"),
        source_kind=source_kind,
        method_id=method_id,
        method_params=method_params,
        detection_limit=payload.get("detection_limit"),
        quantification_limit=payload.get("quantification_limit"),
        result_qualifier=payload.get("result_qualifier"),
        uncertainty_value=payload.get("uncertainty_value"),
        uncertainty_type=payload.get("uncertainty_type"),
        quality_status=payload.get("quality_status") or "valid",
        is_synthetic=bool(payload.get("is_synthetic", False)),
        observed_at=_parse_date(_require(payload, "observed_at"), "observed_at"),
        processing_version=payload.get("processing_version") or "v1",
        metadata=dict(payload.get("metadata") or {}),
    )
    db.add(measurement)
    db.flush()
    return measurement


# --------------------------------------------------------------- read models

def list_measurements(db: Session, field_id: uuid.UUID) -> list[dbm.SoilMeasurement]:
    return list(
        db.execute(
            select(dbm.SoilMeasurement)
            .where(dbm.SoilMeasurement.field_id == field_id)
            .order_by(dbm.SoilMeasurement.observed_at.desc(), dbm.SoilMeasurement.top_depth_cm)
            .limit(500)
        ).scalars().all()
    )


def measurement_payload(m: dbm.SoilMeasurement) -> dict[str, Any]:
    return {
        "id": str(m.id),
        "field_id": str(m.field_id),
        "layer_id": str(m.layer_id) if m.layer_id else None,
        "variable_code": m.variable_code,
        "value": m.value,
        "unit": m.unit,
        "top_depth_cm": m.top_depth_cm,
        "bottom_depth_cm": m.bottom_depth_cm,
        "evidence_class": m.evidence_class,
        "spatial_support_type": m.spatial_support_type,
        "source_kind": m.source_kind,
        "method_params": m.method_params,
        "detection_limit": m.detection_limit,
        "quantification_limit": m.quantification_limit,
        "result_qualifier": m.result_qualifier,
        "uncertainty_value": m.uncertainty_value,
        "uncertainty_type": m.uncertainty_type,
        "quality_status": m.quality_status,
        "is_synthetic": m.is_synthetic,
        "observed_at": m.observed_at.isoformat(),
        "processing_version": m.processing_version,
    }


def build_profile(db: Session, field: dbm.Field) -> dict[str, Any]:
    """The depth-explicit soil profile read model (engine-version-pinned).

    Layers come from sample layers + their measurements; gridded
    (soilgrids_profile) measurements appear as field-attached depth rows.
    Overlaps/gaps are VALIDATED and reported — never silently merged."""
    measurements = list_measurements(db, field.id)
    by_layer: dict[uuid.UUID, list[dbm.SoilMeasurement]] = {}
    field_attached: list[dbm.SoilMeasurement] = []
    for m in measurements:
        if m.layer_id is not None:
            by_layer.setdefault(m.layer_id, []).append(m)
        else:
            field_attached.append(m)

    layer_rows: list[dict[str, Any]] = []
    intervals: list[DepthInterval] = []
    for layer_id, items in by_layer.items():
        top = min(m.top_depth_cm for m in items if m.top_depth_cm is not None)
        bottom = max(m.bottom_depth_cm for m in items if m.bottom_depth_cm is not None)
        intervals.append(make_depth_interval(top, bottom, "cm"))
        layer_rows.append({
            "top_cm": top,
            "bottom_cm": bottom,
            "source_kinds": sorted({m.source_kind for m in items}),
            "evidence_classes": sorted({m.evidence_class for m in items}),
            "measurements": [measurement_payload(m) for m in items],
            "sample_id": str(db.get(dbm.SoilSampleLayer, layer_id).sample_id),
        })

    field_groups: dict[tuple[float, float], list[dbm.SoilMeasurement]] = {}
    for m in field_attached:
        if m.top_depth_cm is None or m.bottom_depth_cm is None:
            continue
        field_groups.setdefault((m.top_depth_cm, m.bottom_depth_cm), []).append(m)

    for (top, bottom), items in field_groups.items():
        intervals.append(make_depth_interval(top, bottom, "cm"))
        layer_rows.append({
            "top_cm": top,
            "bottom_cm": bottom,
            "source_kinds": sorted({m.source_kind for m in items}),
            "evidence_classes": sorted({m.evidence_class for m in items}),
            "measurements": [measurement_payload(m) for m in items],
            "sample_id": None,
        })

    check = validate_layer_set(intervals)
    return {
        "field_id": str(field.id),
        "engine_version": sc.SOIL_ENGINE_VERSION,
        "layers": sorted(layer_rows, key=lambda r: (r["top_cm"], r["bottom_cm"])),
        "integrity": {
            "overlaps": check["overlaps"],
            "gaps": check["gaps"],
            "coverage_cm": list(check["coverage"]) if check["coverage"] else None,
            "note": "overlapping layers are never merged; gaps are never interpolated",
        },
    }


def derive_texture_and_awc(profile: dict[str, Any]) -> dict[str, Any]:
    """Per-layer derived indicators: USDA texture class (with silt derivation
    disclosure) and layer AWC where both water contents exist. Refusals are
    per-layer with reasons."""
    derived: list[dict[str, Any]] = []
    for row in profile["layers"]:
        values = {m["variable_code"]: m for m in row["measurements"] if m["value"] is not None}
        entry: dict[str, Any] = {
            "top_cm": row["top_cm"],
            "bottom_cm": row["bottom_cm"],
        }
        sand = values.get("soil_sand_content")
        silt = values.get("soil_silt_content")
        clay = values.get("soil_clay_content")
        if sand is not None and clay is not None:
            try:
                result = classify_usda_texture(
                    sand_g_kg=sand["value"] if sand["unit"] == "g/kg" else None,
                    sand_pct=sand["value"] if sand["unit"] == "%" else None,
                    silt_g_kg=(silt["value"] if (silt and silt["unit"] == "g/kg") else None),
                    silt_pct=(silt["value"] if (silt and silt["unit"] == "%") else None),
                    clay_g_kg=clay["value"] if clay["unit"] == "g/kg" else None,
                    clay_pct=clay["value"] if clay["unit"] == "%" else None,
                )
                entry["texture"] = {
                    "class": result.texture_class,
                    "sand_pct": result.sand_pct,
                    "silt_pct": result.silt_pct,
                    "clay_pct": result.clay_pct,
                    "silt_basis": result.silt_basis,
                    "classifier_version": result.classifier_version,
                }
            except sc.SoilValidationError as exc:
                entry["texture"] = {"status": "not_evaluated", "reason": str(exc)}
        else:
            entry["texture"] = {"status": "not_evaluated", "reason": "sand+clay fractions required"}
        fc = values.get("soil_water_content_fc")
        wp = values.get("soil_water_content_pwp")
        if fc is not None and wp is not None:
            try:
                awc = layer_awc(
                    make_depth_interval(row["top_cm"], row["bottom_cm"], "cm"),
                    fc["value"], wp["value"],
                    fc_potential_kpa=(fc.get("method_params") or {}).get("matric_potential_kpa"),
                    pwp_potential_kpa=(wp.get("method_params") or {}).get("matric_potential_kpa"),
                )
                entry["awc"] = {
                    "awc_m3_m3": awc.awc_m3_m3,
                    "awc_mm": awc.awc_mm,
                    "fc_potential_kpa": awc.fc_potential_kpa,
                    "pwp_potential_kpa": awc.pwp_potential_kpa,
                }
            except sc.SoilValidationError as exc:
                entry["awc"] = {"status": "not_evaluated", "reason": str(exc)}
        else:
            entry["awc"] = {"status": "not_evaluated", "reason": "θFC and θWP required for the layer"}
        derived.append(entry)
    return {
        "engine_version": sc.SOIL_ENGINE_VERSION,
        "layers": derived,
        "note": "derived indicators never upgrade evidence class; refusals are per-layer reasons",
    }
