"""Numeric consistency validation (A7).

When the advisor's answer contains agricultural measurements, every claim is
checked against the evidence pack handed to the model in the SAME request.
Design goals:

- No naive string matching: rounding (2.5 vs 2.50), percent points, unit
  conversions (mm/cm, °C/°F, %/fraction) and baselines are all legitimate.
- Explicit tolerances: relative 1.5% or small absolute epsilon per scale,
  z-scores ±0.15 (models usually round to 1-2 decimals).
- "Calculated values" the model derives from evidence (e.g. NIR − effective
  rain) cannot be exhaustively pre-verified, so material mismatches are
  FLAGGED (and trigger a constrained regeneration), not silently dropped.
- Small bare integers (1, 2, 3 …) and prompt boilerplate numbers are
  ignored: they are enumeration/section counts, not measurements.

Failure mode: `validate_numbers` returns a report; the advisor decides to
regenerate once with a corrective message or fall back to deterministic
output. Metrics record every failure kind. Nothing here touches the
deterministic engines.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

from app.intelligence import metrics

logger = logging.getLogger("croptwist.intelligence.numeric_guard")

REL_TOL = 0.015          # 1.5% relative tolerance (legitimate rounding)
Z_TOL = 0.15             # z-scores are usually rounded to 1-2 decimals
PERCENT_POINT_TOL = 1.0  # percentage points
SMALL_INT_IGNORE = 12    # bare integers <= this are enumeration, not data

_NUMBER_RE = re.compile(
    r"(?<![\w.])(?P<sign>-)?"
    r"(?P<num>\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)"
    r"\s*(?P<unit>kg/ha/yr|kg/ha|Mg/ha|mm/day|days?|years?|index|z\b|mm|cm|m3|m³|kg|Mg|ha|°C|°F|%|m\b|t\b)?"
    r"(?!\d)"
)

# Known unit conversions -> canonical unit. Only pairs with an exact, safe
# factor are supported; anything else is compared unconverted.
_LENGTH_TO_MM = {"mm": 1.0, "cm": 10.0, "m": 1000.0}


def _c_to_f(c: float) -> float:
    return c * 9.0 / 5.0 + 32.0


@dataclass
class NumericClaim:
    value: float
    unit: str | None
    context: str


@dataclass
class NumericReport:
    supported: list[NumericClaim] = field(default_factory=list)
    unsupported: list[NumericClaim] = field(default_factory=list)
    ignored: list[NumericClaim] = field(default_factory=list)

    @property
    def material_mismatch(self) -> bool:
        return bool(self.unsupported)


# --------------------------------------------------------------- references
def collect_reference_values(evidence: dict[str, Any]) -> list[NumericClaim]:
    """All numeric claims the evidence pack legitimizes (incl. anomalies)."""
    refs: list[NumericClaim] = []

    def _add(value: Any, unit: str | None, context: str) -> None:
        try:
            v = float(value)
        except (TypeError, ValueError):
            return
        refs.append(NumericClaim(value=v, unit=unit, context=context))

    for metric in ((evidence.get("climate") or {}).get("metrics") or []):
        _add(
            metric.get("value"),
            metric.get("unit"),
            f"climate.{metric.get('code')}",
        )

    water = evidence.get("water") or {}
    _add(water.get("nir_mm"), "mm", "water.nir_mm")
    _add(water.get("gir_mm"), "mm", "water.gir_mm")
    _add(water.get("water_allocation_m3"), "m3", "water.water_allocation_m3")
    first = water.get("first_deficit_window") or {}
    _add(first.get("days"), "days", "water.first_deficit_window.days")
    _add(first.get("max_dr_mm"), "mm", "water.first_deficit_window.max_dr_mm")
    _add(first.get("deficit_m3"), "m3", "water.first_deficit_window.deficit_m3")

    soil = evidence.get("soil") or {}
    assessment = soil.get("assessment") or {}
    for domain in assessment.get("domains") or []:
        for indicator in domain.get("indicators") or []:
            _add(
                indicator.get("value"),
                indicator.get("unit"),
                f"soil.indicator.{indicator.get('code')}",
            )
    budget = soil.get("nutrient_budget") or {}
    for nutrient, value in (budget.get("cumulative_balance_kg_ha") or {}).items():
        _add(value, "kg/ha", f"soil.nutrient_balance[{nutrient}]")
    soc = soil.get("soc_stock") or {}
    _add(soc.get("stock_Mg_C_ha"), "Mg/ha", "soil.soc_stock")

    field_sec = evidence.get("field") or {}
    _add(field_sec.get("area_ha"), "ha", "field.area_ha")

    cover = (evidence.get("management") or {}).get("soil_cover") or {}
    _add(
        cover.get("protective_cover_fraction"),
        None,
        "management.soil_cover.protective_cover_fraction",
    )
    _add(
        cover.get("days_protective_cover"),
        "days",
        "management.soil_cover.days_protective_cover",
    )
    _add(
        cover.get("longest_bare_interval_days"),
        "days",
        "management.soil_cover.longest_bare_interval_days",
    )

    vegetation = evidence.get("vegetation") or {}
    latest = vegetation.get("latest_observation") or {}
    _add(
        latest.get("value"),
        latest.get("unit"),
        "vegetation.latest_observation.value",
    )
    comparison = vegetation.get("baseline_comparison") or {}
    _add(
        comparison.get("delta_vs_baseline_mean"),
        "index",
        "vegetation.baseline_comparison.delta_vs_baseline_mean",
    )
    _add(
        comparison.get("z_score_vs_baseline"),
        "z",
        "vegetation.baseline_comparison.z_score_vs_baseline",
    )

    return refs


def _matches(value: float, unit: str | None, refs: list[NumericClaim]) -> bool:
    for ref in refs:
        # Direct same-unit or unitless comparison.
        for cand, cand_unit in _candidate_pairs(value, unit):
            if _close(cand, ref.value, cand_unit or ref.unit):
                return True
    return False


def _close(a: float, b: float, unit: str | None) -> bool:
    scale = abs(b)
    if unit == "%" or (unit is None and scale >= 1 and abs(a - b) <= PERCENT_POINT_TOL and abs(a) <= 100):
        tol = max(PERCENT_POINT_TOL, REL_TOL * scale)
    elif unit and unit.lower() in ("z", ""):
        tol = Z_TOL
    else:
        tol = max(10 ** -(2 + len(str(abs(b)).split(".")[-1]) if "." in str(b) else 0), REL_TOL * scale)
        tol = max(0.05, REL_TOL * scale)  # floor: 0.05 absolute for tiny values
    return abs(a - b) <= tol


def _candidate_pairs(value: float, unit: str | None) -> list[tuple[float, str | None]]:
    pairs: list[tuple[float, str | None]] = [(value, unit)]
    if unit in ("mm", "cm", "m"):
        factor = _LENGTH_TO_MM[unit]
        # value expressed in `unit`; compare against mm references.
        mm_value = value * factor
        pairs.append((mm_value, "mm"))
        if unit != "cm":
            pairs.append((value, "mm" if unit == "cm" else None))
        if unit == "cm":
            pairs.append((value / 10.0, "mm"))  # cm value stated as mm ref
        if unit == "mm":
            pairs.append((value / 10.0, "cm"))
            pairs.append((value / 1000.0, "m"))
    elif unit in ("°C", "°F"):
        converted = _c_to_f(value) if unit == "°C" else (value - 32.0) * 5.0 / 9.0
        pairs.append((converted, "°F" if unit == "°C" else "°C"))
    elif unit is None:
        # percent-as-fraction vs fraction-as-percent both directions.
        pairs.append((value / 100.0, None))
        pairs.append((value * 100.0, None))
    elif unit in ("kg/ha", "Mg/ha"):
        pairs.append((value, "kg/ha" if unit == "Mg/ha" else "Mg/ha"))
    return pairs


# ------------------------------------------------------------------ extract
def extract_claims(text: str) -> list[NumericClaim]:
    claims: list[NumericClaim] = []
    for sentence in re.split(r"(?<=[.!?\n])\s+", text):
        for match in _NUMBER_RE.finditer(sentence):
            sign = -1.0 if match.group("sign") else 1.0
            raw = match.group("num").replace(" ", "").replace(",", "")
            try:
                value = sign * float(raw)
            except ValueError:  # pragma: no cover — regex guarantees digits
                continue
            unit = match.group("unit")
            unit = {"m3": "m3", "m³": "m3", "t": "t", "m": "m"}.get(unit, unit)
            claims.append(
                NumericClaim(value=value, unit=unit, context=sentence.strip()[:160])
            )
    return claims


def _is_boilerplate(claim: NumericClaim) -> bool:
    """Enumeration numbers, years, and label-like values are not measurements."""
    if claim.unit is None and abs(claim.value) <= SMALL_INT_IGNORE:
        return True
    # Years (2020-2100) without a measurement unit.
    if claim.unit is None and 2000 <= claim.value <= 2100 and claim.value == int(claim.value):
        return True
    return False


_SECTION_CONTEXT_PREFIXES: dict[str, tuple[str, ...]] = {
    "field": ("field.",),
    "climate": ("climate.",),
    "water": ("water.",),
    "soil": ("soil.",),
    "management": ("management.",),
    "vegetation": ("vegetation.",),
}


def _same_unit_matches(value: float, unit: str | None, refs: list[NumericClaim]) -> bool:
    aliases = {"m³": "m3", "degC": "°C", "degF": "°F"}
    normalized_unit = aliases.get(unit, unit)
    for ref in refs:
        if aliases.get(ref.unit, ref.unit) != normalized_unit:
            continue
        if _close(value, ref.value, normalized_unit):
            return True
    return False


def _references_for_section(
    evidence: dict[str, Any], label: str
) -> list[NumericClaim]:
    prefixes = _SECTION_CONTEXT_PREFIXES.get(label, ())
    if not prefixes:
        return []
    return [
        ref
        for ref in collect_reference_values(evidence)
        if ref.context.startswith(prefixes)
    ]


def validate_numbers_for_citations(
    answer: str, evidence: dict[str, Any]
) -> NumericReport:
    """Require each measurement to match same-unit facts in its cited section.

    Unlike `validate_numbers`, this conservative field-brief check performs no
    cross-section matching and no unit conversion. Every numeric claim must
    have exactly one distinct inline evidence label in its sentence.
    """
    report = NumericReport()
    inline_citation = re.compile(r"\[evidence:\s*([A-Za-z0-9_.:-]+)\]", re.IGNORECASE)
    for claim in extract_claims(answer):
        if _is_boilerplate(claim):
            report.ignored.append(claim)
            continue
        labels = set(inline_citation.findall(claim.context))
        if len(labels) != 1:
            report.unsupported.append(claim)
            continue
        label = next(iter(labels))
        refs = _references_for_section(evidence, label)
        if _same_unit_matches(claim.value, claim.unit, refs):
            report.supported.append(claim)
        else:
            report.unsupported.append(claim)
            logger.warning(
                "cited numeric claim not grounded in compatible evidence: value=%s unit=%s label=%s ctx=%s",
                claim.value, claim.unit, label, claim.context,
            )
    if report.material_mismatch:
        metrics.incr_validation_failure("cited_numeric_consistency")
    return report


def validate_numbers(
    answer: str, evidence: dict[str, Any], anomalies: list[dict[str, Any]] | None = None
) -> NumericReport:
    """Check every numeric claim in `answer` against the evidence pack."""
    refs = collect_reference_values(evidence)
    for finding in anomalies or []:
        try:
            refs.append(NumericClaim(value=float(finding.get("value")), unit=None, context="anomaly.value"))
            refs.append(NumericClaim(value=float(finding.get("baseline_mean")), unit=None, context="anomaly.baseline_mean"))
            refs.append(NumericClaim(value=float(finding.get("z")), unit=None, context="anomaly.z"))
        except (TypeError, ValueError):
            continue

    report = NumericReport()
    for claim in extract_claims(answer):
        if _is_boilerplate(claim):
            report.ignored.append(claim)
            continue
        if _matches(claim.value, claim.unit, refs):
            report.supported.append(claim)
        else:
            report.unsupported.append(claim)
            logger.warning(
                "numeric claim not grounded in evidence: value=%s unit=%s ctx=%s",
                claim.value, claim.unit, claim.context,
            )
    if report.material_mismatch:
        metrics.incr_validation_failure("numeric_consistency")
    return report
