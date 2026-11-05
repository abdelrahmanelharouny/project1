"""Erosion & conservation screening engine (M6C Increment 6).

Strict model-applicability control (spec §7):

- Process taxonomy is explicit: every result names the processes it speaks
  to. A USLE-family computation speaks ONLY to rainfall-driven sheet and
  rill erosion — never gullies, wind, streambank or sediment delivery.
- The RUSLE-family pathway computes A = R·K·LS·C·P ONLY when all five
  factors arrive with value + source + region + unit-system provenance.
  Missing factors ⇒ `not_evaluated` with the missing factors named — never
  a partial product. Mixing unit conventions ⇒ refusal. The platform ships
  NO factor values and NO factor database: US NRCS databases are not global
  defaults (red line).
- The qualitative pathway flags evidence of concern from cover metrics,
  slope evidence, soil evidence and management records. It is a SCREENING:
  it never outputs a numeric soil loss, and it separates susceptibility
  evidence, model estimates, field-observed signs and unknown status.
- Conservation alternatives are qualitative, cited practice mechanisms with
  their local design requirements — never an invented effectiveness number.
- The platform has NO DEM and fields carry polygons only, so LS cannot be
  computed here at all: it must be farmer/sourced input, or the model
  pathway is data-blocked (documented, honest).
"""

from __future__ import annotations

from typing import Any

EROSION_PROCESSES: tuple[str, ...] = (
    "sheet_interrill", "rill", "ephemeral_gully", "classical_gully",
    "wind", "streambank", "sediment_delivery",
)

RUSLE_PROCESSES: tuple[str, ...] = ("sheet_interrill", "rill")
RUSLE_FACTORS = ("R", "K", "LS", "C", "P")
UNIT_CONVENTIONS = ("us_customary", "metric_si")

SLOPE_CLASSES = ("flat", "gentle", "moderate", "steep", "unknown")


class ErosionEngineError(ValueError):
    pass


def _factor_check(factor: dict[str, Any], code: str) -> dict[str, Any]:
    """Validate one RUSLE factor's provenance envelope."""
    for key in ("value", "source_reference", "region_scope", "unit_convention"):
        if factor.get(key) in (None, ""):
            raise ErosionEngineError(
                f"factor {code} is missing required provenance field "
                f"'{key}' — an unsourced factor is never used"
            )
    if factor["unit_convention"] not in UNIT_CONVENTIONS:
        raise ErosionEngineError(
            f"factor {code}: unknown unit_convention "
            f"'{factor['unit_convention']}' (allowed: {', '.join(UNIT_CONVENTIONS)})"
        )
    value = float(factor["value"])
    if value < 0:
        raise ErosionEngineError(f"factor {code} must be >= 0")
    return {**factor, "value": value}


def rusle_screening(factors: dict[str, dict[str, Any]] | None) -> dict[str, Any]:
    """Conditional RUSLE-family sheet/rill estimate.

    Returns a result dict with `status`:
      not_evaluated  — factors absent/incomplete (named), or mixed conventions
      computed       — all five factors valid; A = R·K·LS·C·P with disclosures
    """
    if not factors:
        return {
            "status": "not_evaluated",
            "processes": list(RUSLE_PROCESSES),
            "missing_factors": list(RUSLE_FACTORS),
            "message": (
                "No RUSLE factors supplied. The platform ships no factor "
                "values and no factor database — R, K, LS, C and P must each "
                "come from a locally applicable source with provenance."
            ),
        }
    missing = [code for code in RUSLE_FACTORS if not factors.get(code)]
    if missing:
        return {
            "status": "not_evaluated",
            "processes": list(RUSLE_PROCESSES),
            "missing_factors": missing,
            "message": (
                "RUSLE refuses to compute a partial product — missing factors: "
                f"{', '.join(missing)}."
            ),
        }
    validated: dict[str, dict[str, Any]] = {}
    try:
        for code in RUSLE_FACTORS:
            validated[code] = _factor_check(dict(factors[code]), code)
    except ErosionEngineError as exc:
        return {
            "status": "not_evaluated",
            "processes": list(RUSLE_PROCESSES),
            "missing_factors": [],
            "message": str(exc),
        }
    conventions = {validated[c]["unit_convention"] for c in RUSLE_FACTORS}
    if len(conventions) > 1:
        return {
            "status": "not_evaluated",
            "processes": list(RUSLE_PROCESSES),
            "missing_factors": [],
            "message": (
                f"Mixed unit conventions {sorted(conventions)} — factor values "
                "from incompatible unit systems are never combined."
            ),
        }
    convention = conventions.pop()
    r, k, ls, c, p = (validated[x]["value"] for x in RUSLE_FACTORS)
    a = r * k * ls * c * p
    return {
        "status": "computed",
        "processes": list(RUSLE_PROCESSES),
        "missing_factors": [],
        "annual_soil_loss_a": round(a, 4),
        "unit_convention": convention,
        "unit_note": (
            "A is in the declared factor convention's native soil-loss unit "
            f"({convention}); the platform does not convert between conventions."
        ),
        "factors": {c: {k_: v[k_] for k_ in ("value", "source_reference", "region_scope", "unit_convention")}
                    for c, v in validated.items()},
        "scope_disclosures": [
            "Estimates rainfall-driven SHEET and RILL erosion only — ephemeral "
            "gullies, classical gullies, wind and streambank erosion are NOT "
            "represented (separate validated models would be required).",
            "This is NOT watershed sediment yield; no deposition or delivery "
            "ratio is applied.",
            "Screening-grade output: a locally calibrated parameter set and "
            "validation are required before treating A as a quantitative "
            "prediction.",
            "LS was supplied, not computed: the platform has no DEM and never "
            "derives slope length from a field polygon.",
        ],
        "assessment_kind": "screening_only",
    }


def qualitative_screening(
    *,
    slope_evidence: dict[str, Any] | None,
    soil_evidence: dict[str, Any] | None,
    cover_metrics: dict[str, Any] | None,
    rainfall_evidence: dict[str, Any] | None,
    management_flags: list[dict[str, Any]] | None,
    observed_signs: list[dict[str, Any]] | None,
) -> dict[str, Any]:
    """Evidence-of-concern screening — qualitative, never numeric.

    Raises concern flags per process family with the exact evidence that
    raised them; unknowns stay unknown."""
    concerns: list[dict[str, Any]] = []
    unknowns: list[str] = []

    bare_days = None
    longest_bare = None
    if cover_metrics:
        bare_days = cover_metrics.get("days_known_bare")
        longest_bare = cover_metrics.get("longest_bare_interval_days")
        if (bare_days or 0) > 0 or (longest_bare or 0) > 0:
            concerns.append(
                {
                    "processes": ["sheet_interrill", "wind"],
                    "code": "exposed_soil_days",
                    "evidence": (
                        f"cover metrics report {bare_days} known-bare day(s), "
                        f"longest bare interval {longest_bare} day(s) in the "
                        "assessment window"
                    ),
                    "evidence_class": "computed_from_records",
                }
            )
        else:
            unknowns.append("cover: no known-bare days in the window (metrics may "
                            "reflect missing observations, not verified cover)")
    else:
        unknowns.append("cover: no cover metrics supplied")

    slope_class = (slope_evidence or {}).get("slope_class")
    if slope_evidence is None or slope_class in (None, "unknown"):
        unknowns.append("slope: no slope evidence supplied")
    elif slope_class in ("moderate", "steep"):
        concerns.append(
            {
                "processes": ["sheet_interrill", "rill", "ephemeral_gully"],
                "code": "slope_class_evidence",
                "evidence": f"farmer/sourced slope class '{slope_class}' "
                "increases runoff concentration potential",
                "evidence_class": slope_evidence.get("evidence_class", "farmer_reported_record"),
            }
        )

    if (soil_evidence or {}).get("erodibility_concern"):
        concerns.append(
            {
                "processes": ["sheet_interrill", "rill"],
                "code": "soil_erodibility_evidence",
                "evidence": soil_evidence["erodibility_concern"],
                "evidence_class": soil_evidence.get("evidence_class", "farmer_reported_record"),
            }
        )

    if rainfall_evidence and rainfall_evidence.get("wettest_month_mm"):
        concerns.append(
            {
                "processes": ["sheet_interrill", "rill"],
                "code": "rainfall_amount_evidence",
                "evidence": (
                    f"wettest month {rainfall_evidence['wettest_month_mm']} mm "
                    "(climatological amount — this is NOT an erosivity (R) "
                    "factor and implies no R value)"
                ),
                "evidence_class": "model_estimate",
            }
        )
    else:
        unknowns.append("rainfall: no precipitation climatology available")

    for flag in management_flags or []:
        concerns.append(
            {
                "processes": flag.get("processes", ["sheet_interrill"]),
                "code": f"management_{flag['code']}",
                "evidence": flag["message"],
                "evidence_class": "farmer_reported_record",
            }
        )

    observed = [
        {
            "processes": s.get("processes", []),
            "description": s["description"],
            "evidence_class": s.get("evidence_class", "farmer_reported_record"),
        }
        for s in (observed_signs or [])
    ]

    return {
        "assessment_kind": "qualitative_screening",
        "processes_assessed": sorted({p for c in concerns for p in c["processes"]}),
        "concerns": concerns,
        "field_observed_signs": observed,
        "unknowns": unknowns,
        "message": (
            "Screening result: evidence of concern flags from field records — "
            "NOT a soil-loss prediction. Susceptibility evidence, model "
            "estimates, observed signs and unknown status are kept separate."
        ),
    }


def conservation_alternatives(practices: list[dict[str, Any]]) -> dict[str, Any]:
    """Sourced qualitative alternatives for erosion-prone situations.

    Practices come from the ACTIVE practice pack (contour_operations,
    strip_cropping, vegetated_buffer, cover_cropping, residue_retention,
    reduced_tillage families). Each alternative keeps its cited mechanism and
    states what local design/quantification would require — the engine never
    ranks alternatives with invented effectiveness numbers."""
    relevant_families = {"erosion_control", "cover_crop", "residue", "tillage"}
    alternatives = []
    for practice in practices:
        if practice.get("practice_family") not in relevant_families:
            continue
        mechanisms = [
            {
                "mechanism_code": m.get("mechanism_code"),
                "text": m.get("text"),
                "citation": m.get("citation"),
                "confidence": m.get("confidence"),
            }
            for m in practice.get("payload", {}).get("mechanisms", [])
            if any(
                kw in (m.get("text") or "").lower()
                for kw in ("erosion", "runoff", "detach", "sediment", "cover", "disturbance")
            )
        ]
        trade_offs = [
            {
                "dimension": t.get("dimension"),
                "direction": t.get("direction"),
                "text": t.get("text"),
                "citation": t.get("citation"),
            }
            for t in practice.get("payload", {}).get("trade_offs", [])
        ]
        alternatives.append(
            {
                "practice_code": practice["practice_code"],
                "name": practice["name"],
                "practice_family": practice["practice_family"],
                "validation_status": practice["validation_status"],
                "mechanisms": mechanisms,
                "trade_offs": trade_offs,
                "quantitative_note": (
                    "Quantitative evaluation of this practice requires model "
                    "parameters with local applicability (e.g. RUSLE support-"
                    "practice P values for this region) — none are bundled, so "
                    "only the sourced qualitative mechanism is shown."
                ),
            }
        )
    return {
        "alternatives": alternatives,
        "message": (
            "Alternatives are cited qualitative mechanisms, not a ranking — "
            "no effectiveness number is invented for any practice."
        ),
    }


def run_erosion_assessment(
    *,
    rusle_factors: dict[str, dict[str, Any]] | None,
    slope_evidence: dict[str, Any] | None,
    soil_evidence: dict[str, Any] | None,
    cover_metrics: dict[str, Any] | None,
    rainfall_evidence: dict[str, Any] | None,
    management_flags: list[dict[str, Any]] | None,
    observed_signs: list[dict[str, Any]] | None,
    practices: list[dict[str, Any]],
) -> dict[str, Any]:
    screening = qualitative_screening(
        slope_evidence=slope_evidence,
        soil_evidence=soil_evidence,
        cover_metrics=cover_metrics,
        rainfall_evidence=rainfall_evidence,
        management_flags=management_flags,
        observed_signs=observed_signs,
    )
    rusle = rusle_screening(rusle_factors)
    alternatives = conservation_alternatives(practices)
    warnings: list[str] = []
    if rusle["status"] == "computed":
        warnings.append(
            "RUSLE-family result is screening-grade sheet/rill erosion under "
            "the supplied factors' own applicability — not a validated local "
            "prediction and not a sediment yield."
        )
    not_evaluated: dict[str, Any] = {"processes": {}}
    for process in EROSION_PROCESSES:
        covered = process in screening["processes_assessed"] or (
            rusle["status"] == "computed" and process in RUSLE_PROCESSES
        )
        if not covered:
            not_evaluated["processes"][process] = (
                "no applicable method or evidence in this platform for this "
                "process (documented scope boundary)"
            )
    return {
        "screening": screening,
        "rusle": rusle,
        "alternatives": alternatives,
        "warnings": warnings,
        "not_evaluated": not_evaluated,
        "status_separation": {
            "susceptibility_evidence": screening["concerns"],
            "model_estimates": [rusle] if rusle["status"] == "computed" else [],
            "field_observed_signs": screening["field_observed_signs"],
            "unknown_status": screening["unknowns"],
        },
    }
