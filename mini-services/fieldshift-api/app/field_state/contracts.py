"""Field state domain contracts (Milestone 7.1).

Versions and the honest per-dimension availability vocabulary. A field state
is an ASSEMBLY of existing artifacts — it introduces no scientific computation
of its own, so its contract surface is deliberately small and versioned:

- FIELD_STATE_ASSEMBLY_VERSION — bumped when assembly semantics change in a
  way that could change a checksum.
- MANIFEST_FORMAT_VERSION — the observation-manifest document format
  (see app.field_state.manifest).

Availability vocabulary (per dimension, never collapsed into a score):

- available          — a pinned artifact exists and qualifies for the period
- missing            — the domain is implemented but no artifact was pinned
- period_mismatch    — a pinned artifact exists but does not cover the state
                       period (recorded, never silently mixed)
- not_evaluated      — assembly could not judge the dimension
- not_implemented    — the domain does not exist in this repository (M6B/M6C)
"""

from typing import Any

FIELD_STATE_ASSEMBLY_VERSION = "field-state-assembly-1.0.0"

STATE_LABEL_MAX = 120

# Per-dimension availability statuses.
AVAILABLE = "available"
MISSING = "missing"
PERIOD_MISMATCH = "period_mismatch"
NOT_EVALUATED = "not_evaluated"
NOT_IMPLEMENTED = "not_implemented"

# Domains a field state tracks. soil/management are absent from this
# repository (M6B/M6C NOT_IMPLEMENTED — verified by the M7.0 inspection);
# they are ALWAYS reported as not_implemented with the reason below.
SOIL_NOT_IMPLEMENTED_REASON = (
    "Soil health & nutrient cycling (M6B) is not implemented in this "
    "repository — no soil assessment engine or tables exist (M7.0 finding H-03)."
)
MANAGEMENT_NOT_IMPLEMENTED_REASON = (
    "Field management intelligence (M6C) is not implemented in this "
    "repository — no management engine or tables exist (M7.0 finding H-03)."
)

# Period-compatibility statuses recorded per dimension (F-02).
COVERS_PERIOD = "covers_period"
PARTIAL_COVER = "partial_cover"
OUTSIDE_PERIOD = "outside_period"


def not_implemented_domain(reason: str) -> dict[str, Any]:
    return {
        "status": NOT_IMPLEMENTED,
        "reason": reason,
        "snapshot_id": None,
    }


def baseline_domain_availability() -> dict[str, Any]:
    """Availability map at assembly start: every implemented domain starts
    as not_evaluated; absent domains start as not_implemented."""
    return {
        "environmental": {"status": NOT_EVALUATED, "reason": None, "snapshot_id": None},
        "water": {"status": NOT_EVALUATED, "reason": None, "snapshot_id": None},
        "rotation": {"status": NOT_EVALUATED, "reason": None, "snapshot_id": None},
        "crop_history": {"status": NOT_EVALUATED, "reason": None, "snapshot_id": None},
        "soil": not_implemented_domain(SOIL_NOT_IMPLEMENTED_REASON),
        "management": not_implemented_domain(MANAGEMENT_NOT_IMPLEMENTED_REASON),
    }


def period_overlap_fraction(
    start: Any, end: Any, period_start: Any, period_end: Any
) -> float | None:
    """Fraction of [period_start, period_end] covered by [start, end].

    Inputs are tz-aware datetimes (or None → returns None). Instants are
    half-open-ish: a zero-day artifact window at the exact period boundary is
    still an overlap only if start <= period_end and end >= period_start.
    """
    if start is None or end is None:
        return None
    overlap_start = max(start, period_start)
    overlap_end = min(end, period_end)
    if overlap_end < overlap_start:
        return 0.0
    span = (period_end - period_start).total_seconds()
    if span <= 0:
        return 1.0 if overlap_end >= overlap_start else 0.0
    return round(min(1.0, (overlap_end - overlap_start).total_seconds() / span), 6)
