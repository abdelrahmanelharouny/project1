"""Portfolio request contracts (P2.F) — vocabulary, validation, checksums.

Pure module: no ORM, no HTTP, no solver (the same independence rule as
`app/rotation/problem.py`). Every client-facing knob of the farm portfolio
engine is declared and validated HERE so the optimizer and the service can
never drift apart on what is admissible.

Honesty contract (inherits the deepening rules):
- Objective weights are an EXPLICIT, disclosed vocabulary. Weights are NOT
  forced to sum to 1 — the raw sum is reported and the normalized shares are
  computed and echoed, so "equal weights" and "weights summing to 6" are
  distinguishable in the pinned request.
- The weighted-mode objective is a DISCLOSED weighted sum of normalized 0-1
  sub-scores — a steering device for the solver, never an agronomic claim
  (the same rule as the rotation engine). Per-criterion values are always
  reported separately alongside it.
- Shared constraints that are absent from the request are reported as
  not_evaluated — never silently treated as unlimited.
- Labor and machinery capacities are RECORDED but never enforced: no sourced
  per-crop labor/machinery coefficient exists anywhere in the platform
  (operation templates deliberately carry no durations), and coefficients are
  never invented.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from app.core.errors import ValidationFailed

PORTFOLIO_ENGINE_VERSION = "portfolio-1.0.0"

# ------------------------------------------------------------------ vocabulary

OBJECTIVE_KEYS: tuple[str, ...] = (
    "water_efficiency",
    "soil_health",
    "rotation_diversity",
    "operational_feasibility",
    "risk_diversification",
    "resource_utilization",
)

DEFAULT_OBJECTIVE_WEIGHTS: dict[str, float] = {k: 1.0 for k in OBJECTIVE_KEYS}

MODE_WEIGHTED = "weighted"
MODE_LEXICOGRAPHIC = "lexicographic"
OBJECTIVE_MODES: tuple[str, ...] = (MODE_WEIGHTED, MODE_LEXICOGRAPHIC)

CONSTRAINT_KEYS: tuple[str, ...] = (
    "water_allocation_m3",
    "labor_capacity_person_days_per_season",
    "machinery_hours_per_season",
    "max_family_share",
)

MAX_FAMILY_SHARE_MIN = 0.1
MAX_FAMILY_SHARE_MAX = 1.0

MAX_SEASON_COUNT = 3
DEFAULT_SEASON_COUNT = 1

SCENARIO_MULTIPLIER_MIN = 0.0
SCENARIO_MULTIPLIER_MAX = 1.5


# ------------------------------------------------------------- objective weights


def validate_objective_weights(raw: Any) -> dict[str, float]:
    """Validate the disclosed weight vocabulary.

    Rules: keys must come from OBJECTIVE_KEYS, values must be numeric and
    >= 0, and at least one weight must be > 0. Weights are NOT normalized
    here — the raw dict is echoed and the shares are computed separately so
    the pinned request keeps the farmer's own numbers.
    """
    if raw is None:
        return dict(DEFAULT_OBJECTIVE_WEIGHTS)
    if not isinstance(raw, dict):
        raise ValidationFailed(
            "objective_weights must be an object of criterion -> weight.",
            details=[{"field": "objective_weights"}],
        )
    weights: dict[str, float] = {}
    for key, value in raw.items():
        if key not in OBJECTIVE_KEYS:
            raise ValidationFailed(
                f"Unknown objective weight key '{key}'.",
                details=[{"field": "objective_weights", "reason": key}],
            )
        if not isinstance(value, (int, float)) or isinstance(value, bool) or value < 0:
            raise ValidationFailed(
                f"Weight for '{key}' must be a non-negative number.",
                details=[{"field": "objective_weights", "reason": key}],
            )
        weights[key] = float(value)
    if not weights or all(w <= 0 for w in weights.values()):
        raise ValidationFailed(
            "At least one objective weight must be greater than zero.",
            details=[{"field": "objective_weights"}],
        )
    # every vocabulary key present (absent keys default to 0 — disclosed via
    # the echoed weights document)
    return {k: float(weights.get(k, 0.0)) for k in OBJECTIVE_KEYS}


def normalized_shares(weights: dict[str, float]) -> dict[str, float]:
    """Normalized shares (weight / total). The raw sum is NOT forced to 1 —
    the shares are a REPORTING device; the raw weights stay pinned verbatim."""
    total = sum(weights.values())
    if total <= 0:
        return {k: 0.0 for k in weights}
    return {k: round(v / total, 6) for k, v in weights.items()}


def validate_mode(raw: Any) -> str:
    if raw is None:
        return MODE_WEIGHTED
    if raw not in OBJECTIVE_MODES:
        raise ValidationFailed(
            f"mode must be one of {list(OBJECTIVE_MODES)}.",
            details=[{"field": "mode", "reason": str(raw)}],
        )
    return str(raw)


def lexicographic_priority(weights: dict[str, float]) -> list[str]:
    """Ordered priority list for lexicographic mode: descending weight, ties
    broken alphabetically for determinism. Zero-weight criteria are NOT
    prioritized (a zero weight means "not prioritized" in both modes)."""
    return [
        k
        for k, w in sorted(weights.items(), key=lambda kv: (-kv[1], kv[0]))
        if w > 0
    ]


# ----------------------------------------------------------------- constraints


def validate_constraints(
    raw: Any,
    *,
    has_labor_resources: bool,
    has_machinery_resources: bool,
) -> tuple[dict[str, float | None], list[dict[str, Any]]]:
    """Validate the optional shared-constraint set.

    Returns the canonical constraint dict (absent -> None) plus honesty notes
    for constraints that are recorded but CANNOT be enforced with sourced
    data (labor / machinery — no per-crop coefficients exist platform-wide;
    see the module docstring). Absent constraints are simply None — the
    service reports them as not_evaluated.
    """
    canonical: dict[str, float | None] = {k: None for k in CONSTRAINT_KEYS}
    if raw is None:
        return canonical, []
    if not isinstance(raw, dict):
        raise ValidationFailed(
            "constraints must be an object of constraint -> value.",
            details=[{"field": "constraints"}],
        )
    notes: list[dict[str, Any]] = []
    for key, value in raw.items():
        if key not in CONSTRAINT_KEYS:
            raise ValidationFailed(
                f"Unknown shared constraint '{key}'.",
                details=[{"field": "constraints", "reason": key}],
            )
        if value is None:
            continue
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            raise ValidationFailed(
                f"Constraint '{key}' must be a number.",
                details=[{"field": "constraints", "reason": key}],
            )
        value = float(value)
        if key == "water_allocation_m3":
            # 0 is meaningful (a farm can genuinely receive no water) and is
            # reported as infeasibility-with-named-constraint, not rejected.
            if value < 0:
                raise ValidationFailed(
                    "water_allocation_m3 must be >= 0.",
                    details=[{"field": "constraints", "reason": key}],
                )
        elif key in ("labor_capacity_person_days_per_season", "machinery_hours_per_season"):
            if value < 0:
                raise ValidationFailed(
                    f"{key} must be >= 0.",
                    details=[{"field": "constraints", "reason": key}],
                )
        elif key == "max_family_share":
            if not (MAX_FAMILY_SHARE_MIN <= value <= MAX_FAMILY_SHARE_MAX):
                raise ValidationFailed(
                    f"max_family_share must be between {MAX_FAMILY_SHARE_MIN} "
                    f"and {MAX_FAMILY_SHARE_MAX}.",
                    details=[{"field": "constraints", "reason": key}],
                )
        canonical[key] = value

    if canonical["labor_capacity_person_days_per_season"] is not None:
        reason = (
            "recorded but not enforced: no sourced per-crop labor coefficient "
            "exists in any active knowledge pack (operation templates "
            "deliberately carry no durations), and coefficients are never "
            "invented"
        )
        if not has_labor_resources:
            reason += "; the farm also has no labor_crew resource registered"
        notes.append(
            {
                "code": "labor_capacity_person_days_per_season",
                "reason": reason,
            }
        )
    if canonical["machinery_hours_per_season"] is not None:
        reason = (
            "recorded but not enforced: no sourced per-crop machinery-hours "
            "coefficient exists in any active knowledge pack (operation "
            "templates deliberately carry no durations), and coefficients are "
            "never invented"
        )
        if not has_machinery_resources:
            reason += "; the farm also has no tractor/implement resource registered"
        notes.append(
            {
                "code": "machinery_hours_per_season",
                "reason": reason,
            }
        )
    return canonical, notes


# -------------------------------------------------------------------- scenario


def validate_scenario(raw: Any) -> dict[str, Any] | None:
    """Validate the resilience scenario. None (absent) means baseline."""
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise ValidationFailed(
            "scenario must be an object.",
            details=[{"field": "scenario"}],
        )

    def _multiplier(key: str, default: float) -> float:
        value = raw.get(key, default)
        if value is None:
            return default
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            raise ValidationFailed(
                f"scenario.{key} must be a number.",
                details=[{"field": f"scenario.{key}", "reason": str(value)}],
            )
        if not (SCENARIO_MULTIPLIER_MIN <= float(value) <= SCENARIO_MULTIPLIER_MAX):
            raise ValidationFailed(
                f"scenario.{key} must be between {SCENARIO_MULTIPLIER_MIN} "
                f"and {SCENARIO_MULTIPLIER_MAX}.",
                details=[{"field": f"scenario.{key}", "reason": str(value)}],
            )
        return float(value)

    label = raw.get("label")
    if label is not None and (not isinstance(label, str) or len(label) > 120):
        raise ValidationFailed(
            "scenario.label must be a string of at most 120 characters.",
            details=[{"field": "scenario.label"}],
        )
    return {
        "water_allocation_multiplier": _multiplier("water_allocation_multiplier", 1.0),
        "labor_capacity_multiplier": _multiplier("labor_capacity_multiplier", 1.0),
        "label": label,
    }


# --------------------------------------------------------------------- seasons


def validate_season_count(raw: Any) -> int:
    if raw is None:
        return DEFAULT_SEASON_COUNT
    if not isinstance(raw, int) or isinstance(raw, bool) or not (
        1 <= raw <= MAX_SEASON_COUNT
    ):
        raise ValidationFailed(
            f"season_count must be an integer between 1 and {MAX_SEASON_COUNT}.",
            details=[{"field": "season_count", "reason": str(raw)}],
        )
    return raw


# ------------------------------------------------------------------- checksums


def canonical_checksum(payload: dict[str, Any]) -> str:
    """sha256 over a canonical (sort_keys, tight separators) JSON document —
    the reproducibility contract shared with the rotation/water engines."""
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def run_checksum_payload(
    *,
    engine_version: str,
    request_parameters: dict[str, Any],
    result: dict[str, Any] | None,
    allocations: list[dict[str, Any]],
) -> dict[str, Any]:
    """The canonical document a portfolio run's checksum covers. Used at
    write time AND by the /verify endpoint (independent recomputation from
    the persisted rows) — one shape, two call sites, no drift."""
    return {
        "engine": engine_version,
        "request_parameters": request_parameters,
        "result": result or {},
        "allocations": sorted(
            (
                {
                    "field_id": str(a.get("field_id")),
                    "season_index": int(a.get("season_index", 0)),
                    "crop_code": str(a.get("crop_code")),
                    # fixed 2-decimal formatting: the ORM column is
                    # NUMERIC(10,2) (Decimal on read) while the in-memory
                    # value is a float — one canonical string at both sites.
                    "area_ha": f"{float(a.get('area_ha')):.2f}",
                }
                for a in allocations
            ),
            key=lambda row: (
                row["field_id"],
                row["season_index"],
                row["crop_code"],
            ),
        ),
    }
