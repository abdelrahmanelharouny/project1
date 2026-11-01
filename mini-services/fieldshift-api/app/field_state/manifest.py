"""Deterministic observation manifest (Milestone 7.1 — H-02 / F-31).

The manifest preserves, BY VALUE, the exact resolved environmental input set
of a feature run — the observations actually handed to the engine — so that:

- re-runs cannot silently absorb newly ingested rows (the M7.0 finding: the
  observation set was previously pinned only through per-value provenance,
  capped at 400 ids);
- checksums stay verifiable years later (the document is stored next to its
  hash, not recomputed from a mutable query);
- synthetic and real evidence remain distinguishable end-to-end.

Determinism rules (all enforced here, regression-tested):

- Canonical JSON: `sort_keys=True`, `separators=(",", ":")`, UTF-8.
- Timestamps: ISO-8601, UTC, always with an explicit `+00:00` offset. Naive
  datetimes are interpreted as UTC (the platform stores TIMESTAMPTZ; naive
  values can only come from JSON round-trips).
- Ordering: observations sorted by (observed_at UTC, id) — independent of the
  query that produced them. Context lists are sorted too.
- Nulls: explicit `null` (never omitted, never coerced to zero).
- The hash covers the ENTIRE document including format version and context —
  a manifest without its context is not interpretable, so it is not hashed.
"""

import hashlib
import json
from datetime import datetime, timezone
from typing import Any

MANIFEST_FORMAT_VERSION = "field-observation-manifest-1"

# Keys copied from an observation's metadata JSONB into the manifest entry's
# `asset_refs` (original asset references). The metadata dict itself can hold
# arbitrary provider content; only these stable, asset-identifying keys are
# promoted so the manifest stays compact and its hash stable.
ASSET_REF_KEYS = ("asset", "asset_id", "raster_url", "source_url", "file_name", "granule_id")


def canonical_json(document: Any) -> str:
    """Canonical serialization: sorted keys, tight separators, UTF-8."""
    return json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def sha256_of_document(document: Any) -> str:
    return hashlib.sha256(canonical_json(document).encode("utf-8")).hexdigest()


def iso_utc(value: datetime | str | None) -> str | None:
    """Serialize a timestamp deterministically: ISO-8601 UTC with +00:00."""
    if value is None:
        return None
    if isinstance(value, str):
        value = datetime.fromisoformat(value)
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


def _asset_refs(metadata: dict[str, Any] | None) -> dict[str, Any]:
    refs = {}
    for key in ASSET_REF_KEYS:
        if metadata and metadata.get(key) is not None:
            refs[key] = metadata[key]
    return refs


def manifest_entry(observation: Any) -> dict[str, Any]:
    """One compact, deterministic observation entry.

    Accepts an ORM Observation or an equivalent mapping (the feature service
    resolves rows before handing them to the engine). Explicit None for
    missing values — nulls are information, never zeros.
    """
    def _get(name: str, default: Any = None) -> Any:
        if isinstance(observation, dict):
            return observation.get(name, default)
        return getattr(observation, name, default)

    metadata = _get("metadata") or {}
    if isinstance(metadata, str):  # defensive: JSONB round-trips
        try:
            metadata = json.loads(metadata)
        except (TypeError, ValueError):
            metadata = {}
    uncertainty_value = _get("uncertainty_value")
    uncertainty_type = _get("uncertainty_type")
    return {
        "id": str(_get("id")),
        "variable_code": _get("variable_code"),
        "dataset_product_id": str(_get("dataset_product_id")),
        "observed_at": iso_utc(_get("observed_at")),
        "period_start": iso_utc(_get("period_start")),
        "period_end": iso_utc(_get("period_end")),
        "time_support": _get("time_support"),
        "value": _get("value"),
        "unit": _get("unit"),
        "quality_status": _get("quality_status"),
        "spatial_support_type": _get("spatial_support_type"),
        "spatial_resolution_m": _get("spatial_resolution_m"),
        "evidence_class": _get("evidence_class"),
        "is_synthetic": bool(_get("is_synthetic", False)),
        "uncertainty": (
            None
            if uncertainty_value is None and uncertainty_type is None
            else {"value": uncertainty_value, "type": uncertainty_type}
        ),
        "asset_refs": _asset_refs(metadata),
        "processing_version": _get("processing_version"),
    }


def build_manifest(
    observations: list[Any],
    *,
    field_id: str,
    purpose: str,
    window_start: datetime | str | None = None,
    window_end: datetime | str | None = None,
    variables: list[str] | None = None,
    source_products: list[dict[str, Any]] | None = None,
    processing_configuration: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the versioned manifest document from a resolved input set.

    The document carries its own format version and the resolution context,
    so the stored hash is self-describing and independently re-verifiable.
    """
    entries = [manifest_entry(o) for o in observations]
    entries.sort(key=lambda e: (e["observed_at"] or "", e["id"]))
    return {
        "format_version": MANIFEST_FORMAT_VERSION,
        "context": {
            "field_id": str(field_id),
            "purpose": purpose,
            "window_start": iso_utc(window_start),
            "window_end": iso_utc(window_end),
            "variables": sorted(set(variables or [])),
            "source_products": sorted(
                source_products or [], key=lambda p: json.dumps(p, sort_keys=True)
            ),
            "processing_configuration": processing_configuration or {},
        },
        "observation_count": len(entries),
        "synthetic_observation_count": sum(1 for e in entries if e["is_synthetic"]),
        "observations": entries,
    }
