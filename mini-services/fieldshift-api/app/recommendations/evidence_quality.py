"""Evidence-quality assessment (A5).

Separates four concepts that were previously blurred into one 0..1 constant:

- severity            — agronomic priority ladder (info<advisory<recommended
                        <required). Chosen by RULES, unchanged by P1.
- confidence          — how much to trust THIS rule fired correctly. Only two
                        honest kinds exist:
                          * "deterministic_rule": the trigger is a fact about
                            stored engine outputs (e.g. "no water plan row
                            exists") — absence/presence is certain, so a high
                            constant IS justified and is labeled as such;
                          * "evidence_quality": score derived from the actual
                            data behind the evidence (below).
- evidence quality    — computed, component-wise data quality of the evidence
                        supporting a recommendation (never a probability of
                        agronomic correctness).
- agronomic applicability — stays with the knowledge/engine layers; this
                        module does not estimate it.

Components (each independently computable or honestly None):
- completeness        — share of expected evidence sections present.
- recency             — age of the newest engine output.
- coverage            — history length of the run window (months observed).
- source_reliability  — synthetic vs measured provider data.
- measurement_uncertainty — share of quality flags available (valid/partial).
- spatial_resolution  — None today (no resolution metadata reaches the pack);
- agreement           — None today (no redundant independent sources wired).

The score is the plain mean of the AVAILABLE components — documented, not
calibrated, and never presented as a probability. Missing components are
reported as None, not zero-filled.
"""

from __future__ import annotations

import datetime as dt
import logging
from typing import Any

logger = logging.getLogger("croptwist.recommendations.evidence_quality")

_FRESH_DAYS = {"fresh": 7, "recent": 30, "aging": 90, "stale": 365}

COMPONENT_KEYS = (
    "completeness",
    "recency",
    "coverage",
    "source_reliability",
    "measurement_uncertainty",
)


def _recency_score(reference: dt.datetime | dt.date | None) -> float | None:
    """1.0 fresh → 0.1 very stale (documented bands, not calibrated)."""
    if reference is None:
        return None
    try:
        ref = reference if isinstance(reference, dt.datetime) else None
        if ref is not None:
            if ref.tzinfo is None:
                ref = ref.replace(tzinfo=dt.UTC)
            age_days = (dt.datetime.now(dt.UTC) - ref).total_seconds() / 86400
        else:
            age_days = (dt.date.today() - reference).days
    except (TypeError, ValueError, OSError):
        return None
    if age_days <= _FRESH_DAYS["fresh"]:
        return 1.0
    if age_days <= _FRESH_DAYS["recent"]:
        return 0.8
    if age_days <= _FRESH_DAYS["aging"]:
        return 0.5
    if age_days <= _FRESH_DAYS["stale"]:
        return 0.3
    return 0.1


def _newest_reference(section: dict[str, Any] | None) -> dt.datetime | None:
    """Best recency anchor of one evidence section (source id age unknown →
    the run window end when present)."""
    if not isinstance(section, dict):
        return None
    period = section.get("period") or {}
    end = period.get("end")
    if isinstance(end, str):
        try:
            return dt.datetime.fromisoformat(end).replace(tzinfo=dt.UTC)
        except ValueError:
            return None
    return None


def assess_evidence_quality(
    ctx: Any,
    domain: str,
    *,
    expected_sections: tuple[str, ...] = (),
) -> dict[str, Any]:
    """Component-wise evidence quality for one domain's recommendations.

    `expected_sections` names the evidence sections this domain's recs draw
    on (e.g. ("water",) or ("soil", "climate")). Returns:
      {"score": float|None, "components": {name: {"value": float|None,
       "basis": str}}, "summary": str}
    """
    components: dict[str, dict[str, Any]] = {}

    # Completeness: presence of the sections this domain relies on.
    if expected_sections:
        present = [
            s for s in expected_sections
            if isinstance(ctx.evidence.get(s), dict) and ctx.evidence.get(s)
        ]
        components["completeness"] = {
            "value": round(len(present) / len(expected_sections), 2),
            "basis": f"{len(present)}/{len(expected_sections)} required evidence sections present",
        }

    # Recency: newest period end across the required sections.
    anchors = []
    for s in expected_sections:
        section = ctx.evidence.get(s)
        if isinstance(section, dict):
            anchor = _newest_reference(section)
            if anchor:
                anchors.append(anchor)
    recency = _recency_score(max(anchors) if anchors else None)
    components["recency"] = {
        "value": recency,
        "basis": "age of the newest engine output window end" if anchors else "no dated engine output",
    }

    # Coverage: run-window length for climate-backed domains.
    climate = ctx.evidence.get("climate")
    if isinstance(climate, dict) and climate.get("period"):
        try:
            start = dt.datetime.fromisoformat(str(climate["period"].get("start")))
            end = dt.datetime.fromisoformat(str(climate["period"].get("end")))
            months = max(0, (end.year - start.year) * 12 + end.month - start.month)
            components["coverage"] = {
                "value": round(min(1.0, months / 12.0), 2),
                "basis": f"climate run window spans {months} month(s)",
            }
        except (TypeError, ValueError, AttributeError):
            components["coverage"] = {"value": None, "basis": "run window not parseable"}
    else:
        components["coverage"] = {"value": None, "basis": "no climate run to date the window"}

    # Source reliability: synthetic provider data is honest but weaker.
    synthetic_flags = []
    for s in expected_sections:
        section = ctx.evidence.get(s)
        if isinstance(section, dict) and "is_synthetic" in section:
            synthetic_flags.append(bool(section["is_synthetic"]))
    if synthetic_flags:
        reliability = 0.5 if all(synthetic_flags) else (0.75 if any(synthetic_flags) else 1.0)
        basis = (
            "synthetic provider data (sandbox parity)" if all(synthetic_flags)
            else "mixed synthetic/measured provider data"
        )
        components["source_reliability"] = {"value": reliability, "basis": basis}
    else:
        components["source_reliability"] = {"value": None, "basis": "no provider provenance in pack"}

    # Measurement uncertainty: data-gap count for this domain's sections.
    gaps = ctx.evidence.get("data_gaps") or []
    gap_hit = [g for g in gaps if g in expected_sections]
    components["measurement_uncertainty"] = {
        "value": 1.0 if not gap_hit else 0.0,
        "basis": (
            "no data gaps among required sections"
            if not gap_hit
            else f"data gaps: {', '.join(gap_hit)}"
        ),
    }

    # Not computable today — declared, never fabricated (spec E.4-6).
    components["spatial_resolution"] = {
        "value": None,
        "basis": "no spatial resolution metadata reaches the evidence pack yet",
    }
    components["agreement"] = {
        "value": None,
        "basis": "no independent redundant sources wired for cross-validation yet",
    }

    available = [c["value"] for c in components.values() if c["value"] is not None]
    score = round(sum(available) / len(available), 2) if available else None
    summary = (
        f"evidence quality {score} (mean of {len(available)} computable components; "
        f"{len(components) - len(available)} not computable)"
        if score is not None
        else "evidence quality not computable (no components available)"
    )
    return {"score": score, "components": components, "summary": summary}


def evidence_backed_confidence(quality: dict[str, Any], *, floor: float = 0.3) -> float | None:
    """Map evidence quality to a screening-strength confidence.

    DOCUMENTED HEURISTIC, not calibration: floor + (1-floor) * score. Returns
    None when the quality score is None (callers then omit confidence).
    """
    score = quality.get("score")
    if score is None:
        return None
    return round(floor + (1.0 - floor) * float(score), 2)
