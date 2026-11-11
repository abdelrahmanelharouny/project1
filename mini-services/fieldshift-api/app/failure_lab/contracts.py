"""Stress-pack contracts for the Rotation Failure Lab (P2.D).

A stress pack is a NAMED, PARAMETERIZED stress specification applied to a
candidate rotation: every pack carries explicit parameters, a documented
assumption note and provenance (preset vs user-defined) so a downstream
reader can always tell WHICH approximation produced a number.

Packs are deliberately narrow:

- `climate` packs perturb the month-of-year climatology (precipitation
  multiplier, growing-season mean temperature shift) and recompute the
  candidate water numbers through the versioned water engine paths.
- `operational` packs act on farmer-supplied operational inputs only (water
  allocation multiplier, margin-index penalty). They never invent an
  allocation or economics: a missing input makes the dimension
  `not_evaluated`, never zero.
- `timing` packs shift the season start for CALENDAR-WINDOW feasibility
  screening only — no other criterion is re-evaluated under the shift.
- `combined_climate_operational` stacks one climate and two operational
  dimensions; the effects are additive per dimension and recorded per pack.

Validation refuses unknown pack codes and out-of-bounds parameters with the
structured `ValidationFailed` error — a silently clamped parameter would make
a stress result uninterpretable.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.core.errors import ValidationFailed

FAILURE_LAB_ENGINE_VERSION = "failure-lab-1.0.0"
STRESS_PACKS_VERSION = "stress-packs-1.0.0"

# Candidate rotation keys (the exact set the lab evaluates; any other key is
# refused before a run is created).
CANDIDATE_KEYS = ("baseline", "recommended", "alternative")

PACK_KINDS = ("climate", "operational", "timing", "economic", "combined")

# Parameter bounds (inclusive on both ends). A parameter outside its bounds
# is refused — never clamped — so the requested stress is always the applied
# stress.
PRECIPITATION_MULTIPLIER_BOUNDS = (0.0, 1.5)
WATER_ALLOCATION_MULTIPLIER_BOUNDS = (0.0, 1.5)
TEMPERATURE_DELTA_C_BOUNDS = (-10.0, 10.0)
PLANTING_WINDOW_SHIFT_DAYS_BOUNDS = (0, 30)
MARGIN_INDEX_PENALTY_BOUNDS = (0.0, 100.0)

PARAMETER_BOUNDS: dict[str, tuple[float, float]] = {
    "precipitation_multiplier": PRECIPITATION_MULTIPLIER_BOUNDS,
    "water_allocation_multiplier": WATER_ALLOCATION_MULTIPLIER_BOUNDS,
    "temperature_delta_c": TEMPERATURE_DELTA_C_BOUNDS,
    "planting_window_shift_days": PLANTING_WINDOW_SHIFT_DAYS_BOUNDS,
    "margin_index_penalty": MARGIN_INDEX_PENALTY_BOUNDS,
}

MAX_PACKS_PER_RUN = 12
MAX_PACK_CODE_LENGTH = 64


@dataclass(frozen=True)
class StressPack:
    """One named stress specification (preset or user-defined)."""

    code: str
    label: str
    kind: str
    parameters: dict[str, Any] = field(default_factory=dict)
    assumption_note: str = ""
    provenance: dict[str, str] = field(default_factory=dict)

    def document(self) -> dict[str, Any]:
        """BY-VALUE pin of the pack (stored on the run; checksum input)."""
        return {
            "code": self.code,
            "label": self.label,
            "kind": self.kind,
            "parameters": dict(sorted(self.parameters.items())),
            "assumption_note": self.assumption_note,
            "provenance": dict(sorted(self.provenance.items())),
        }


PRESET_PACKS: dict[str, StressPack] = {
    "severe_drought": StressPack(
        code="severe_drought",
        label="Severe drought",
        kind="combined",
        parameters={
            "precipitation_multiplier": 0.25,
            "water_allocation_multiplier": 0.6,
        },
        assumption_note=(
            "Climatology-based water stress: monthly precipitation scaled to "
            "25% of the evidence climatology (a historical proxy, not a "
            "forecast) and the farmer-supplied seasonal allocation scaled to "
            "60%. Water REQUIREMENT coefficients are recomputed from the "
            "stressed climatology; only the ALLOCATION side is a direct "
            "multiplier."
        ),
        provenance={
            "source": "preset",
            "basis": (
                "Named screening scenario (stress-packs-1.0.0): a severe "
                "growing-season drought approximated by a precipitation "
                "climatology multiplier plus a reduced irrigation allocation."
            ),
        },
    ),
    "heatwave": StressPack(
        code="heatwave",
        label="Heatwave (+6 degC growing-season mean)",
        kind="climate",
        parameters={"temperature_delta_c": 6.0},
        assumption_note=(
            "Growing-season MEAN temperature shift of +6 degC applied to the "
            "season aggregate and crop temperature screening; ET0 follows the "
            "'temperature-ET0 screening sensitivity' (+1 degC ≈ +3.5% ET0, "
            "applied multiplicatively per degree) — a documented "
            "approximation, not a physical model. Hot-day counts are NOT "
            "shifted (a stated limitation)."
        ),
        provenance={
            "source": "preset",
            "basis": (
                "Named screening scenario (stress-packs-1.0.0): a hot "
                "growing season approximated by a uniform mean-temperature "
                "shift."
            ),
        },
    ),
    "water_restriction": StressPack(
        code="water_restriction",
        label="Water restriction (allocation × 0.5)",
        kind="operational",
        parameters={"water_allocation_multiplier": 0.5},
        assumption_note=(
            "Halves the farmer-supplied seasonal water allocation. Water "
            "REQUIREMENT coefficients are climatology-based and unstressed — "
            "only the ALLOCATION side is stressed. Without a farmer-supplied "
            "allocation the dimension is not_evaluated (never invented)."
        ),
        provenance={
            "source": "preset",
            "basis": (
                "Named screening scenario (stress-packs-1.0.0): a 50% cut of "
                "the seasonal irrigation allocation."
            ),
        },
    ),
    "delayed_planting": StressPack(
        code="delayed_planting",
        label="Delayed planting (+14 days)",
        kind="timing",
        parameters={"planting_window_shift_days": 14},
        assumption_note=(
            "Shifts the season start date by 14 days for CALENDAR-WINDOW "
            "feasibility screening only: crops whose planting windows no "
            "longer overlap the delayed season are reported as "
            "timing_infeasible_crops. No other criterion is re-evaluated "
            "under the shift."
        ),
        provenance={
            "source": "preset",
            "basis": (
                "Named screening scenario (stress-packs-1.0.0): a two-week "
                "planting delay screened against the knowledge-base calendar "
                "windows."
            ),
        },
    ),
    "nutrient_price_shock": StressPack(
        code="nutrient_price_shock",
        label="Nutrient price shock (margin index −25)",
        kind="economic",
        parameters={"margin_index_penalty": 25.0},
        assumption_note=(
            "Subtracts 25 from every farmer-supplied margin index (floored "
            "at 0). Applies ONLY to the farmer-supplied index: without "
            "farmer margin data the dimension is not_evaluated — the "
            "platform never estimates prices, yields or margins."
        ),
        provenance={
            "source": "preset",
            "basis": (
                "Named screening scenario (stress-packs-1.0.0): a fertilizer "
                "price shock approximated as a flat penalty on the "
                "farmer-supplied relative margin index."
            ),
        },
    ),
    "combined_climate_operational": StressPack(
        code="combined_climate_operational",
        label="Combined climate + operational stress",
        kind="combined",
        parameters={
            "precipitation_multiplier": 0.5,
            "temperature_delta_c": 3.0,
            "water_allocation_multiplier": 0.7,
        },
        assumption_note=(
            "Stacks one climate dimension (precipitation × 0.5, temperature "
            "+3 degC with the temperature-ET0 screening sensitivity) and one "
            "operational dimension (allocation × 0.7). Effects combine per "
            "dimension; every recomputed number carries the same basis "
            "strings as the single-dimension packs."
        ),
        provenance={
            "source": "preset",
            "basis": (
                "Named screening scenario (stress-packs-1.0.0): concurrent "
                "climate and irrigation-supply stress."
            ),
        },
    ),
}

PRESET_PACK_CODES = tuple(sorted(PRESET_PACKS))


def _validate_parameter(code: str, value: Any) -> float:
    """Bounds-check one stress parameter. Refuses (never clamps) non-numeric
    or out-of-bounds values with a structured error."""
    bounds = PARAMETER_BOUNDS.get(code)
    if bounds is None:
        raise ValidationFailed(
            f"Unknown stress parameter '{code}' "
            f"(known: {', '.join(sorted(PARAMETER_BOUNDS))}).",
            details=[{"field": "packs", "reason": code}],
        )
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValidationFailed(
            f"Stress parameter '{code}' must be a number.",
            details=[{"field": "packs", "reason": code}],
        )
    numeric = float(value)
    lo, hi = bounds
    if numeric < lo or numeric > hi:
        raise ValidationFailed(
            f"Stress parameter '{code}' must be within [{lo}, {hi}] (got {numeric}) — "
            "out-of-bounds stresses are refused, never clamped.",
            details=[{"field": "packs", "reason": code}],
        )
    return numeric


def _pack_from_override(code: str, item: dict[str, Any]) -> StressPack:
    """Resolve one request entry: a preset code with optional parameter
    overrides, or a fully user-defined pack (new code)."""
    overrides = item.get("parameters") or {}
    if not isinstance(overrides, dict):
        raise ValidationFailed(
            f"Pack '{code}': 'parameters' must be an object.",
            details=[{"field": "packs", "reason": code}],
        )
    preset = PRESET_PACKS.get(code)
    if preset is not None:
        parameters = {**preset.parameters, **overrides}
        for name, value in overrides.items():
            _validate_parameter(name, value)
        overridden = sorted(overrides)
        return StressPack(
            code=preset.code,
            label=preset.label,
            kind=preset.kind,
            parameters=parameters,
            assumption_note=preset.assumption_note,
            provenance={
                "source": "user_defined",
                "basis": (
                    f"preset '{preset.code}' with overridden parameter(s): "
                    f"{', '.join(overridden) if overridden else 'none'}; "
                    f"{preset.provenance['basis']}"
                ),
            },
        )

    # user-defined pack: new code, explicit kind, known bounded parameters.
    if not code or len(code) > MAX_PACK_CODE_LENGTH or not code.strip() == code:
        raise ValidationFailed(
            f"User-defined pack code must be 1-{MAX_PACK_CODE_LENGTH} characters "
            "without leading/trailing whitespace.",
            details=[{"field": "packs", "reason": str(code)[:80]}],
        )
    kind = item.get("kind")
    if kind not in PACK_KINDS:
        raise ValidationFailed(
            f"User-defined pack '{code}' needs a kind from: {', '.join(PACK_KINDS)}.",
            details=[{"field": "packs", "reason": str(kind)[:80]}],
        )
    label = item.get("label") or code.replace("_", " ")
    if not isinstance(label, str) or not label.strip():
        raise ValidationFailed(
            f"User-defined pack '{code}' label must be a non-empty string.",
            details=[{"field": "packs", "reason": code}],
        )
    if not overrides:
        raise ValidationFailed(
            f"User-defined pack '{code}' carries no parameters — an empty "
            "stress would silently masquerade as a result.",
            details=[{"field": "packs", "reason": code}],
        )
    parameters = {name: _validate_parameter(name, value) for name, value in overrides.items()}
    return StressPack(
        code=code,
        label=label.strip(),
        kind=kind,
        parameters=parameters,
        assumption_note=str(
            item.get("assumption_note")
            or "User-defined stress pack; parameters are applied by the "
            "failure-lab engine exactly as documented per dimension."
        ),
        provenance={
            "source": "user_defined",
            "basis": str(item.get("basis") or "user-defined parameters supplied in the request"),
        },
    )


def resolve_packs(entries: list[str | dict[str, Any]] | None) -> list[StressPack]:
    """Resolve the request's pack entries into validated `StressPack` docs.

    Accepts preset codes (str) or objects (`{"code": ..., "parameters": ...}`
    — a preset with overrides, or a new user-defined pack with kind/label/
    parameters). Missing/None defaults to ALL preset packs; an explicit empty
    list is refused. Unknown codes, unknown parameters and out-of-bounds
    values raise `ValidationFailed`. The resolved list is sorted by code so
    downstream iteration (and the run checksum) is order-independent.
    """
    if entries is None:
        return [PRESET_PACKS[c] for c in PRESET_PACK_CODES]
    if not isinstance(entries, list) or not entries:
        raise ValidationFailed(
            "packs must be a non-empty list of preset codes or pack objects.",
            details=[{"field": "packs"}],
        )
    if len(entries) > MAX_PACKS_PER_RUN:
        raise ValidationFailed(
            f"At most {MAX_PACKS_PER_RUN} stress packs per run.",
            details=[{"field": "packs"}],
        )
    resolved: dict[str, StressPack] = {}
    for item in entries:
        if isinstance(item, str):
            code = item
            payload: dict[str, Any] = {"code": code}
        elif isinstance(item, dict):
            code = str(item.get("code") or "")
            payload = item
        else:
            raise ValidationFailed(
                "Each pack entry must be a preset code (string) or an object.",
                details=[{"field": "packs", "reason": str(item)[:80]}],
            )
        if code not in PRESET_PACKS and code in resolved:
            raise ValidationFailed(
                f"Duplicate stress pack code '{code}'.",
                details=[{"field": "packs", "reason": code}],
            )
        if isinstance(item, str) and code not in PRESET_PACKS:
            raise ValidationFailed(
                f"Unknown stress pack '{code}' "
                f"(known presets: {', '.join(PRESET_PACK_CODES)}).",
                details=[{"field": "packs", "reason": code}],
            )
        resolved[code] = _pack_from_override(code, payload)
    return [resolved[c] for c in sorted(resolved)]


def pack_catalog() -> dict[str, Any]:
    """The preset pack catalog served by GET /failure-lab/packs."""
    return {
        "version": STRESS_PACKS_VERSION,
        "packs": [PRESET_PACKS[c].document() for c in PRESET_PACK_CODES],
        "parameter_bounds": {
            name: {"min": bounds[0], "max": bounds[1]}
            for name, bounds in sorted(PARAMETER_BOUNDS.items())
        },
        "candidate_keys": list(CANDIDATE_KEYS),
        "note": (
            "Presets are named screening scenarios, not forecasts. Every "
            "pack records its assumptions and provenance; requests may "
            "override preset parameters (within the documented bounds) or "
            "supply user-defined packs with a new code."
        ),
    }
