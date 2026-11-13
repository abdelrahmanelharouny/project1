"""Grounding envelope assembly for existing deterministic field evidence."""
from __future__ import annotations

import json
from collections.abc import Iterable
from typing import Any

from app.intelligence.orchestration.contracts import EvidenceItem, EvidenceSourceReference


_DOMAIN_CAPABILITIES = {
    "field": "field_profile",
    "climate": "climate_intelligence",
    "water": "water_intelligence",
    "soil": "soil_intelligence",
    "rotation": "crop_rotation_explanation",
    "management": "stress_anomaly_screening",
    "vegetation": "vegetation_intelligence",
    "data_gaps": "field_data_availability",
}
MAX_EVIDENCE_CONTEXT_BYTES = 16_000


def select_evidence_domains(pack: dict[str, Any], domains: Iterable[str]) -> dict[str, Any]:
    """Keep only a server-approved selection before any provider call."""
    selected = set(domains)
    allowed = set(_DOMAIN_CAPABILITIES)
    selected &= allowed
    selected.update({"field", "data_gaps"})
    result: dict[str, Any] = {}
    for key in ("field", "climate", "water", "soil", "rotation", "management", "vegetation"):
        if key in selected and key in pack:
            result[key] = pack[key]
    # Data-gap labels are small field-level availability metadata, not domain
    # result payloads; returning them lets the response state what is missing.
    result["data_gaps"] = list(pack.get("data_gaps") or [])
    encoded = json.dumps(result, ensure_ascii=False, default=str, separators=(",", ":")).encode("utf-8")
    if len(encoded) > MAX_EVIDENCE_CONTEXT_BYTES:
        raise ValueError("Selected field evidence exceeds the AI Core context budget.")
    return result


def _source_references(value: Any) -> list[EvidenceSourceReference]:
    found: list[EvidenceSourceReference] = []
    seen: set[tuple[str, str | None, str | None]] = set()

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            source = node.get("source")
            if isinstance(source, dict):
                kind = source.get("kind") or source.get("provider_code") or "stored_engine_result"
                source_id = source.get("id") or source.get("scene_id")
                provider = source.get("provider_code")
                acquired = source.get("acquired_at") or source.get("observed_at")
                key = (str(kind), str(source_id) if source_id is not None else None, str(provider) if provider else None)
                if key not in seen:
                    seen.add(key)
                    found.append(EvidenceSourceReference(
                        source_kind=key[0], source_id=key[1], provider=key[2], acquired_at=acquired
                    ))
            for child in node.values():
                walk(child)
        elif isinstance(node, list):
            for child in node:
                walk(child)

    walk(value)
    return found[:12]


def _period(label: str, value: dict[str, Any]) -> dict[str, str | None] | None:
    period = value.get("period")
    if isinstance(period, dict) and (period.get("start") or period.get("end")):
        return {"start": period.get("start"), "end": period.get("end")}
    observed = (value.get("latest_observation") or {}).get("observed_at")
    if observed:
        return {"start": str(observed), "end": str(observed)}
    return None


def _quality(value: dict[str, Any]) -> dict[str, Any]:
    latest = value.get("latest_observation") or {}
    keys = (
        "is_synthetic", "fresh", "freshness_days_since_last", "valid_observations",
        "excluded_no_value", "valid_pixel_fraction", "supports_subfield_claims",
        "insufficient_evidence", "spatial_anomalies",
    )
    result = {key: value[key] for key in keys if key in value}
    if latest:
        for key in ("cloud_cover_pct", "valid_pixel_fraction", "evidence_class"):
            if key in latest:
                result[f"latest_{key}"] = latest[key]
    return result


def normalize_evidence(
    pack: dict[str, Any], *, field_id: str, cited_labels: Iterable[str] | None = None
) -> list[EvidenceItem]:
    """Map evidence sections to a stable envelope without inventing scores."""
    labels = set(cited_labels or [])
    use_filter = bool(labels)
    items: list[EvidenceItem] = []
    for label, capability in _DOMAIN_CAPABILITIES.items():
        if use_filter and label not in labels and label != "data_gaps":
            continue
        if label == "data_gaps":
            gaps = pack.get("data_gaps") or []
            if not gaps:
                continue
            items.append(EvidenceItem(
                evidence_id=f"data_gaps:{field_id}",
                capability="field_data_availability",
                entity_scope="field",
                entity_id=field_id,
                result_type="domain_data_gaps",
                claim_class="missing_information",
                value={"domains": list(gaps)},
                limitations=["A data gap means no qualifying stored evidence was available; it is not a zero measurement."],
                status="insufficient",
            ))
            continue
        section = pack.get(label)
        if not isinstance(section, dict):
            continue
        if label == "field":
            sources = [EvidenceSourceReference(source_kind="field_record", source_id=field_id)]
            claim_class = "verified_fact"
        else:
            sources = _source_references(section)
            latest = section.get("latest_observation") or {}
            if label == "vegetation" and latest.get("scene_id"):
                candidate = EvidenceSourceReference(
                    source_kind="satellite_scene",
                    source_id=str(latest["scene_id"]),
                    provider=(section.get("source") or {}).get("provider_code"),
                    acquired_at=latest.get("observed_at"),
                )
                if candidate not in sources:
                    sources.insert(0, candidate)
            claim_class = "derived_result"
        quality = _quality(section)
        raw_limitations: list[str] = []
        not_claims = section.get("not_claims")
        if isinstance(not_claims, str) and not_claims:
            raw_limitations.append(not_claims)
        if section.get("insufficient_evidence"):
            raw_limitations.append("The source explicitly marks evidence as insufficient.")
        if label == "vegetation":
            quality["provider"] = (section.get("source") or {}).get("provider_code")
            quality["index_formula"] = section.get("index_formula")
        status = "partial" if section.get("insufficient_evidence") else "available"
        items.append(EvidenceItem(
            evidence_id=f"{label}:{field_id}",
            capability=capability,
            entity_scope="field",
            entity_id=field_id,
            result_type=f"{label}_evidence",
            claim_class=claim_class,
            value=section,
            observation_period=_period(label, section),
            source_references=sources,
            spatial_resolution_m=(section.get("latest_observation") or {}).get("spatial_resolution_m"),
            processing_version=(section.get("latest_observation") or {}).get("processing_version"),
            evidence_quality=quality,
            limitations=raw_limitations,
            status=status,
        ))
    return items[:40]
