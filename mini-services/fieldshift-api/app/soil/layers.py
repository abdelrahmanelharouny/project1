"""Depth intervals and layer validation (Milestone 6B — Step 3, ADR-0022).

Canonical depth unit is CENTIMETRES. Every layer keeps its original unit and
values; conversions are explicit and one-way recorded. The supported standard
SoilGrids/GlobalSoilMap intervals are convenience knowledge only — field lab
depths are preserved verbatim and are NEVER snapped to a standard interval
(a 0-5 cm sample is never silently promoted to a 0-30 cm claim).
"""

from __future__ import annotations

from dataclasses import dataclass

from app.soil.contracts import SoilValidationError

CANONICAL_DEPTH_UNIT = "cm"

# SoilGrids 2.0 / GlobalSoilMap standard depth intervals (cm). Informational:
# the platform does NOT require measurements to use them.
STANDARD_DEPTH_INTERVALS_CM: tuple[tuple[int, int], ...] = (
    (0, 5), (5, 15), (15, 30), (30, 60), (60, 100), (100, 200),
)

_DEPTH_UNIT_TO_CM: dict[str, float] = {
    "cm": 1.0,
    "mm": 0.1,
    "m": 100.0,
}

MAX_PLAUSIBLE_DEPTH_CM = 300.0  # sane field-profile bound; deeper rows are refused


@dataclass(frozen=True)
class DepthInterval:
    """[top_cm, bottom_cm) with provenance of the original declaration."""

    top_cm: float
    bottom_cm: float
    original_unit: str = "cm"
    original_top: float | None = None
    original_bottom: float | None = None

    @property
    def thickness_cm(self) -> float:
        return self.bottom_cm - self.top_cm


def to_cm(value: float, unit: str) -> float:
    """Convert a depth value to cm; unknown units are refused, never guessed."""
    factor = _DEPTH_UNIT_TO_CM.get((unit or "").strip().lower())
    if factor is None:
        raise SoilValidationError(
            f"unknown depth unit '{unit}' (supported: {', '.join(sorted(_DEPTH_UNIT_TO_CM))})"
        )
    return float(value) * factor


def make_depth_interval(
    top: float,
    bottom: float,
    unit: str = "cm",
) -> DepthInterval:
    """Validate and normalize a depth interval.

    Refusals (never silent fixes): non-finite, negative, bottom <= top,
    deeper than the plausible profile bound. Unit conversion is explicit and
    the original declaration is preserved on the interval."""
    top_f, bottom_f = float(top), float(bottom)
    if top_f != top_f or bottom_f != bottom_f:  # NaN
        raise SoilValidationError("depth values must be finite numbers")
    top_cm = to_cm(top_f, unit)
    bottom_cm = to_cm(bottom_f, unit)
    if top_cm < 0:
        raise SoilValidationError(f"top depth must be ≥ 0 (got {top_cm} cm)")
    if bottom_cm <= top_cm:
        raise SoilValidationError(
            f"bottom depth must be greater than top depth (got {top_cm}–{bottom_cm} cm)"
        )
    if bottom_cm > MAX_PLAUSIBLE_DEPTH_CM:
        raise SoilValidationError(
            f"bottom depth {bottom_cm} cm exceeds the plausible profile bound "
            f"({MAX_PLAUSIBLE_DEPTH_CM:.0f} cm) — refusing rather than guessing"
        )
    return DepthInterval(
        top_cm=round(top_cm, 4),
        bottom_cm=round(bottom_cm, 4),
        original_unit=unit,
        original_top=top_f,
        original_bottom=bottom_f,
    )


def validate_layer_set(intervals: list[DepthInterval]) -> dict[str, object]:
    """Validate a set of layers for overlaps and gaps.

    Returns {"overlaps": [...], "gaps": [...], "coverage": (min, max) | None}.
    Overlaps make aggregation REFUSED upstream (never deduplicated silently);
    gaps are reported and block whole-profile totals while per-layer stocks
    remain evaluable."""
    ordered = sorted(intervals, key=lambda i: (i.top_cm, i.bottom_cm))
    overlaps: list[dict[str, float]] = []
    gaps: list[dict[str, float]] = []
    for prev, cur in zip(ordered, ordered[1:]):
        if cur.top_cm < prev.bottom_cm - 1e-9:
            overlaps.append({
                "a": f"{prev.top_cm}-{prev.bottom_cm}",
                "b": f"{cur.top_cm}-{cur.bottom_cm}",
                "overlap_cm": round(prev.bottom_cm - cur.top_cm, 4),
            })
        elif cur.top_cm > prev.bottom_cm + 1e-9:
            gaps.append({
                "from_cm": prev.bottom_cm,
                "to_cm": cur.top_cm,
                "gap_cm": round(cur.top_cm - prev.bottom_cm, 4),
            })
    coverage = (
        (ordered[0].top_cm, ordered[-1].bottom_cm) if ordered else None
    )
    return {"overlaps": overlaps, "gaps": gaps, "coverage": coverage}


def depth_weighted_mean(
    values: list[tuple[DepthInterval, float]],
) -> tuple[float, float]:
    """Thickness-weighted mean over DISJOINT intervals.

    Returns (weighted_mean, total_thickness_cm). Overlapping intervals raise —
    aggregation over double-counted depth would fabricate precision."""
    intervals = [iv for iv, _v in values]
    check = validate_layer_set(intervals)
    if check["overlaps"]:
        raise SoilValidationError(
            "depth intervals overlap — aggregation refused (never deduplicated silently)"
        )
    total = sum(iv.thickness_cm for iv in intervals)
    if total <= 0:
        raise SoilValidationError("empty depth coverage")
    acc = sum(v * iv.thickness_cm for iv, v in values)
    return acc / total, total
