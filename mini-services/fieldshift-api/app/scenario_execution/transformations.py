"""Pure environmental transformation functions (Milestone 7.3).

Implements exactly two scientifically specified transformations (see
docs/m7/m7_3/M7_3_TRANSFORMATION_METHODOLOGY.md):

1. Uniform additive temperature shift (degrees Celsius).
2. Precipitation scaling by an explicit non-negative multiplier.

Design rules:

- PURE functions: no database, no HTTP, no randomness, no clock. Identical
  inputs always produce identical outputs.
- Native temporal support is preserved verbatim — never resampled, never
  re-dated, never disaggregated.
- Missing source values stay missing (null), never zero.
- Units are validated before transformation; incompatible units are excluded
  (reported by the caller), never converted.
- The original observation is never mutated; a derived record is produced.
"""

import math
from dataclasses import dataclass, field
from typing import Any

from app.scenario_execution.contracts import (
    EVIDENCE_SCENARIO_DERIVED,
    EVIDENCE_SYNTHETIC_TEST,
    TRANSFORMATION_ENGINE_VERSION,
    TransformationCode,
)

# ---------------------------------------------------------------------------
# Variable scope
# ---------------------------------------------------------------------------

TEMPERATURE_VARIABLES = frozenset(
    {"air_temperature_mean", "air_temperature_max", "air_temperature_min"}
)
PRECIPITATION_VARIABLES = frozenset({"precipitation"})

# ---------------------------------------------------------------------------
# Unit gates (validation before transformation; never conversion)
# ---------------------------------------------------------------------------

TEMPERATURE_UNITS = frozenset({"degc", "°c", "celsius", "degrees_celsius"})
PRECIPITATION_UNIT_PREFIX = "mm"  # mm, mm/day, mm/hr, mm/year …


def is_temperature_unit(unit: str | None) -> bool:
    return (unit or "").strip().lower() in TEMPERATURE_UNITS


def is_precipitation_unit(unit: str | None) -> bool:
    u = (unit or "").strip().lower()
    return u == "mm" or u.startswith("mm/") or u.startswith("mm ")


def targeted_variables(*, delta_c: float | None, multiplier: float | None) -> frozenset[str]:
    """Variables the configured transformations apply to."""
    targeted = frozenset()
    if delta_c is not None:
        targeted |= TEMPERATURE_VARIABLES
    if multiplier is not None:
        targeted |= PRECIPITATION_VARIABLES
    return targeted


# ---------------------------------------------------------------------------
# Derived record
# ---------------------------------------------------------------------------


@dataclass
class DerivedObservation:
    """One scenario-derived (transformed) observation record.

    ``value`` is the transformed value; ``baseline_value`` the source value.
    Missing source values produce value=None with baseline_value=None.
    ``evidence_class`` is the DERIVED class (scenario-derived / synthetic);
    the original observation's class travels in ``source_evidence_class``.
    """

    source_observation_id: str
    variable_code: str
    baseline_value: float | None
    value: float | None
    unit: str
    observed_at: Any  # preserved verbatim (datetime)
    period_start: Any
    period_end: Any
    time_support: str
    spatial_support_type: str
    spatial_resolution_m: float | None
    transformation_code: str
    transformation_parameter: dict[str, Any]
    evidence_class: str
    source_evidence_class: str | None
    quality_status: str
    is_synthetic: bool
    dataset_product_id: str
    processing_version: str
    source_metadata: dict[str, Any] = field(default_factory=dict)

    def to_checksum_row(self) -> dict[str, Any]:
        """Canonical row used in the output checksum document."""
        return {
            "source_observation_id": self.source_observation_id,
            "variable_code": self.variable_code,
            "baseline_value": self.baseline_value,
            "value": self.value,
            "unit": self.unit,
            "observed_at": str(self.observed_at),
            "period_start": str(self.period_start),
            "period_end": str(self.period_end),
            "time_support": self.time_support,
            "transformation_code": self.transformation_code,
            "transformation_parameter": self.transformation_parameter,
            "quality_status": self.quality_status,
            "is_synthetic": self.is_synthetic,
        }


# ---------------------------------------------------------------------------
# Transformations
# ---------------------------------------------------------------------------


class TransformationError(RuntimeError):
    """A transformation produced a non-finite value (numerical overflow)."""


def transform_temperature(
    value: float | None,
    delta_c: float,
    *,
    unit: str | None,
) -> float | None:
    """T_scenario = T_baseline + ΔT (validates unit; missing stays missing).

    Raises ValueError when the unit is not a temperature unit, or the delta is
    not finite. Non-finite results raise TransformationError (overflow).
    """
    if not is_temperature_unit(unit):
        raise ValueError(f"Unit '{unit}' is not a temperature unit; refusing to transform.")
    if not math.isfinite(delta_c):
        raise ValueError("Temperature delta must be finite.")
    if value is None:
        return None
    result = float(value) + float(delta_c)
    if not math.isfinite(result):
        raise TransformationError("Temperature transformation overflowed.")
    return result


def transform_precipitation(
    value: float | None,
    multiplier: float,
    *,
    unit: str | None,
) -> float | None:
    """P_scenario = P_baseline × M_p (validates unit; missing stays missing).

    - multiplier must be finite and >= 0 (negative is rejected, never clamped)
    - a negative *source* value is rejected as invalid (never silently clamped)
    - M_p = 1 reproduces the original value exactly
    - M_p = 0 maps valid rainfall to explicit 0.0 (hypothetical zeroing)
    """
    if not math.isfinite(multiplier) or multiplier < 0:
        raise ValueError("Precipitation multiplier must be finite and non-negative.")
    if not is_precipitation_unit(unit):
        raise ValueError(f"Unit '{unit}' is not a precipitation unit; refusing to transform.")
    if value is None:
        return None
    v = float(value)
    if v < 0:
        raise ValueError("Negative source precipitation is invalid and is never transformed.")
    result = v * float(multiplier)
    if not math.isfinite(result):
        raise TransformationError("Precipitation transformation overflowed.")
    return result


def _asset_metadata(obs: dict[str, Any]) -> dict[str, Any]:
    metadata = obs.get("metadata") or {}
    if isinstance(metadata, str):
        import json

        try:
            metadata = json.loads(metadata)
        except (TypeError, ValueError):
            metadata = {}
    return metadata if isinstance(metadata, dict) else {}


def transform_observation(
    obs: dict[str, Any],
    *,
    delta_c: float | None,
    multiplier: float | None,
) -> tuple[DerivedObservation | None, str | None]:
    """Transform ONE source observation dict.

    Returns ``(record, exclusion_reason)``:

    - ``(None, None)``                 — variable not targeted by the configured
                                          transformations (normal; the dependency
                                          graph explains untouched variables)
    - ``(None, reason)``               — targeted but refused (e.g. incompatible
                                          unit); caller surfaces the exclusion
    - ``(DerivedObservation, None)``   — transformed
    """
    variable = obs["variable_code"]
    unit = obs.get("unit")
    value = obs.get("value")
    quality = obs.get("quality_status") or "valid"
    is_synthetic = bool(obs.get("is_synthetic"))

    if delta_c is not None and variable in TEMPERATURE_VARIABLES:
        if not is_temperature_unit(unit):
            return None, (
                f"observation {obs.get('id')} ({variable}) has unit '{unit}', "
                "which is not a temperature unit; excluded from transformation"
            )
        # Missing / quality-missing values stay missing (never transformed to 0).
        missing = value is None or quality == "missing"
        new_value = None if missing else transform_temperature(value, delta_c, unit=unit)
        return (
            DerivedObservation(
                source_observation_id=str(obs["id"]),
                variable_code=variable,
                baseline_value=None if missing else float(value),
                value=new_value,
                unit=unit,
                observed_at=obs.get("observed_at"),
                period_start=obs.get("period_start"),
                period_end=obs.get("period_end"),
                time_support=obs.get("time_support") or "daily",
                spatial_support_type=obs.get("spatial_support_type") or "field_intersection",
                spatial_resolution_m=obs.get("spatial_resolution_m"),
                transformation_code=TransformationCode.TEMPERATURE_DELTA_C.value,
                transformation_parameter={"delta_c": float(delta_c)},
                evidence_class=EVIDENCE_SYNTHETIC_TEST if is_synthetic else EVIDENCE_SCENARIO_DERIVED,
                source_evidence_class=obs.get("evidence_class"),
                quality_status=quality,
                is_synthetic=is_synthetic,
                dataset_product_id=str(obs.get("dataset_product_id")),
                processing_version=obs.get("processing_version") or "unknown",
                source_metadata=_asset_metadata(obs),
            ),
            None,
        )

    if multiplier is not None and variable in PRECIPITATION_VARIABLES:
        if not is_precipitation_unit(unit):
            return None, (
                f"observation {obs.get('id')} ({variable}) has unit '{unit}', "
                "which is not a precipitation unit; excluded from transformation"
            )
        missing = value is None or quality == "missing"
        new_value = None if missing else transform_precipitation(value, multiplier, unit=unit)
        return (
            DerivedObservation(
                source_observation_id=str(obs["id"]),
                variable_code=variable,
                baseline_value=None if missing else float(value),
                value=new_value,
                unit=unit,
                observed_at=obs.get("observed_at"),
                period_start=obs.get("period_start"),
                period_end=obs.get("period_end"),
                time_support=obs.get("time_support") or "daily",
                spatial_support_type=obs.get("spatial_support_type") or "field_intersection",
                spatial_resolution_m=obs.get("spatial_resolution_m"),
                transformation_code=TransformationCode.PRECIPITATION_MULTIPLIER.value,
                transformation_parameter={"multiplier": float(multiplier)},
                evidence_class=EVIDENCE_SYNTHETIC_TEST if is_synthetic else EVIDENCE_SCENARIO_DERIVED,
                source_evidence_class=obs.get("evidence_class"),
                quality_status=quality,
                is_synthetic=is_synthetic,
                dataset_product_id=str(obs.get("dataset_product_id")),
                processing_version=obs.get("processing_version") or "unknown",
                source_metadata=_asset_metadata(obs),
            ),
            None,
        )

    return None, None


def apply_transformations(
    observations: list[dict[str, Any]],
    *,
    delta_c: float | None,
    multiplier: float | None,
) -> tuple[list[DerivedObservation], list[dict[str, Any]]]:
    """Apply the configured transformations to an observation set.

    Returns (derived_records, exclusion_reports). Observations of untouched
    variables are skipped silently (the dependency graph reports them as
    ``not_affected``); targeted observations with incompatible units are
    reported as exclusions (never silently dropped).
    """
    derived: list[DerivedObservation] = []
    excluded: list[dict[str, Any]] = []
    for obs in sorted(
        observations,
        key=lambda o: (str(o.get("period_start")), o.get("variable_code"), str(o.get("id"))),
    ):
        rec, exclusion = transform_observation(obs, delta_c=delta_c, multiplier=multiplier)
        if rec is not None:
            derived.append(rec)
        elif exclusion is not None:
            excluded.append(
                {
                    "observation_id": str(obs.get("id")),
                    "variable_code": obs.get("variable_code"),
                    "unit": obs.get("unit"),
                    "reason": exclusion,
                }
            )
    return derived, excluded


ENGINE_VERSION = TRANSFORMATION_ENGINE_VERSION
