"""Soil Memory core (P2.C) — snapshots, conservative change models, alerts.

The platform's soil tables already keep a full, immutable measurement
history (soil_measurements.observed_at, never overwritten). P2.C adds:

1. SNAPSHOTs — a versioned, checksummed longitudinal soil state assembled
   from measurements (all evidence classes kept side by side), management
   events, and crop history at a point in time (`as_of`).
2. CHANGE ESTIMATES — conservative, documented models between two snapshots:
   - `soc_fixed_depth_trajectory`: linear per-year SOC change between two
     comparable SOC stock runs (reuses the existing comparability gate);
     refuse when < 2 comparable measurements — never interpolate.
   - `nutrient_balance_summary`: reuse of the N/P/K mass-balance engine's
     cumulative partial balance over the window.
   Every estimate records method, model version, assumptions and
   uncertainty, and is labelled ESTIMATED end to end (never presented as a
   measured improvement).
3. ALERTS — evidence-based screening signals (nutrient depletion, salinity,
   low/rising SOC context, erosion risk) that reuse the existing engines'
   documented thresholds (FAO salinity classes, EcoCrop optima, budget
   sign) and attach their citations. No universal thresholds are invented.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date
from typing import Any

SOIL_MEMORY_VERSION = "soil-memory-1.0.0"
SOC_TRAJECTORY_VERSION = "soc-trajectory-1.0.0"


def snapshot_checksum(snapshot: dict[str, Any]) -> str:
    canonical = json.dumps(snapshot, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def build_snapshot_document(
    *,
    field_id: str,
    as_of: date,
    measurements: list[dict[str, Any]],
    management_events: list[dict[str, Any]],
    nutrient_inputs: list[dict[str, Any]],
    nutrient_outputs: list[dict[str, Any]],
    crop_history: list[dict[str, Any]],
    missing_evidence: list[str],
) -> dict[str, Any]:
    """Assemble the snapshot document (pure — the service queries the rows).

    Measurements carry their evidence_class/source_kind per value; values
    are never merged across evidence classes or depths.
    """
    document = {
        "field_id": field_id,
        "as_of": as_of.isoformat(),
        "version": SOIL_MEMORY_VERSION,
        "variables": sorted(
            measurements,
            key=lambda m: (m.get("variable_code"), m.get("top_depth_cm") or 0.0, str(m.get("observed_at"))),
        ),
        "management_events": sorted(
            management_events, key=lambda e: str(e.get("event_date"))
        ),
        "nutrient_inputs": nutrient_inputs,
        "nutrient_outputs": nutrient_outputs,
        "crop_history": crop_history,
    }
    return document


def soc_fixed_depth_trajectory(
    *,
    soc_stocks: list[dict[str, Any]],
) -> dict[str, Any]:
    """Linear SOC stock trajectory between the earliest and latest COMPARABLE
    fixed-depth stock results.

    `soc_stocks` rows: {observed_at (date|str), total_stock_mg_ha: float,
    comparable_key: str} — comparable_key groups stock runs measured the
    same way (same depths/method; produced by the soil service). The slope
    is (last - first) / years; the label is ESTIMATED (a two-point linear
    interpolation, not a validated model) and uncertainty reflects the
    two-point nature.
    """
    usable = [s for s in soc_stocks if s.get("total_stock_mg_ha") is not None and s.get("observed_at")]
    if len(usable) < 2:
        return {
            "method": "soc_fixed_depth_trajectory",
            "model_version": SOC_TRAJECTORY_VERSION,
            "value": None,
            "not_evaluated": (
                "SOC trajectory needs at least 2 comparable stock measurements; "
                f"found {len(usable)}. Missing evidence is never interpolated."
            ),
        }
    comparable_groups: dict[str, list[dict[str, Any]]] = {}
    for s in usable:
        comparable_groups.setdefault(str(s.get("comparable_key") or "default"), []).append(s)
    best_key, best_rows = max(
        comparable_groups.items(),
        key=lambda kv: sorted(str(r["observed_at"]) for r in kv[1]).__len__(),
    )
    rows = sorted(best_rows, key=lambda r: str(r["observed_at"]))
    first, last = rows[0], rows[-1]
    d1 = first["observed_at"] if isinstance(first["observed_at"], date) else date.fromisoformat(str(first["observed_at"]))
    d2 = last["observed_at"] if isinstance(last["observed_at"], date) else date.fromisoformat(str(last["observed_at"]))
    years = (d2 - d1).days / 365.25
    if years <= 0:
        return {
            "method": "soc_fixed_depth_trajectory",
            "model_version": SOC_TRAJECTORY_VERSION,
            "value": None,
            "not_evaluated": "the two comparable measurements share the same date; no time span exists",
        }
    delta = float(last["total_stock_mg_ha"]) - float(first["total_stock_mg_ha"])
    per_year = delta / years
    return {
        "method": "soc_fixed_depth_trajectory",
        "model_version": SOC_TRAJECTORY_VERSION,
        "value": round(per_year, 4),
        "unit": "Mg C/ha/yr",
        "comparable_key": best_key,
        "window": {
            "start": d1.isoformat(),
            "end": d2.isoformat(),
            "years": round(years, 2),
            "n_measurements": len(rows),
        },
        "first_stock_mg_ha": float(first["total_stock_mg_ha"]),
        "last_stock_mg_ha": float(last["total_stock_mg_ha"]),
        "delta_mg_ha": round(delta, 4),
        "estimated": True,
        "assumptions": [
            "Two-point linear trajectory between the earliest and latest "
            "comparable measurements — intermediate years are interpolated, "
            "not measured.",
            "Fixed-depth comparison; bulk-density changes between sampling "
            "events are not corrected here (the SOC engine's ESM comparison "
            "covers that case and refuses without per-layer masses).",
        ],
        "uncertainty": {
            "type": "two_point_linear",
            "detail": "No independent replication is available; the direction "
            "of change is screening-grade only.",
        },
    }


def soil_alerts(
    *,
    nutrient_budget: dict[str, Any] | None,
    salinity: dict[str, Any] | None,
    soc_trajectory: dict[str, Any] | None,
    erosion: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    """Evidence-based soil health alerts (screening, with citations).

    - nutrient depletion: the cumulative budget engine's negative balance
      (its own documented stoichiometry; loss flows are never assumed zero,
      so a balance is always partial and labelled as such).
    - salinity: FAO Soils Bulletin 62 ECe classes from the soil chemistry
      engine — ECe measurements only (cross-method comparison refused
      upstream).
    - SOC trajectory: direction of the ESTIMATED two-point trajectory,
      explicitly labelled estimated.
    - erosion: the erosion screening engine's own factors (reused verbatim).
    """
    alerts: list[dict[str, Any]] = []
    if nutrient_budget:
        for element in ("n", "p", "k"):
            balance = (nutrient_budget.get("elements") or {}).get(element)
            if balance is None:
                continue
            net = balance.get("net_kg_ha")
            if net is not None and float(net) < 0:
                alerts.append(
                    {
                        "code": f"nutrient_depletion_{element}",
                        "severity": "advisory",
                        "title": f"Negative {element.upper()} balance (partial budget)",
                        "detail": (
                            f"Cumulative {element.upper()} balance is {net:.1f} kg/ha over the "
                            "budget window. The balance is PARTIAL: loss flows "
                            "(leaching, denitrification, volatilization, erosion, runoff) are "
                            "never assumed zero, so this is a screening signal, not a "
                            "measured depletion."
                        ),
                        "evidence_refs": [nutrient_budget.get("source_ref")],
                        "basis": "nutrient mass-balance engine (documented stoichiometry)",
                    }
                )
    if salinity and salinity.get("class") and salinity.get("class") not in ("non_saline", None):
        alerts.append(
            {
                "code": "salinity_concern",
                "severity": "advisory" if salinity.get("class") == "slightly_saline" else "recommended",
                "title": f"Soil salinity class: {salinity.get('class')}",
                "detail": (
                    f"ECe {salinity.get('ec_ds_m')} dS/m classifies as "
                    f"{salinity.get('class')} (FAO Soils Bulletin 62 classes; ECe "
                    "measurements only)."
                ),
                "evidence_refs": salinity.get("source_ref"),
                "basis": "FAO Soils Bulletin 62 salinity classes (soil chemistry engine)",
            }
        )
    if soc_trajectory and soc_trajectory.get("value") is not None:
        direction = "declining" if float(soc_trajectory["value"]) < 0 else "increasing"
        alerts.append(
            {
                "code": f"soc_trajectory_{direction}",
                "severity": "info",
                "title": f"Estimated SOC stock trajectory is {direction}",
                "detail": (
                    f"{soc_trajectory['value']:+.3f} Mg C/ha/yr between "
                    f"{soc_trajectory.get('window', {}).get('start')} and "
                    f"{soc_trajectory.get('window', {}).get('end')} "
                    "(two-point linear ESTIMATE — not a measured improvement)."
                ),
                "evidence_refs": [],
                "basis": "SOC fixed-depth two-point trajectory (estimated)",
            }
        )
    if erosion and erosion.get("concern"):
        alerts.append(
            {
                "code": "erosion_risk",
                "severity": erosion.get("severity", "advisory"),
                "title": "Erosion screening flags concerns",
                "detail": erosion.get("detail", "The erosion screening engine flagged risk factors."),
                "evidence_refs": erosion.get("source_ref"),
                "basis": "erosion screening engine (RUSLE-style screening)",
            }
        )
    severity_rank = {"required": 0, "recommended": 1, "advisory": 2, "info": 3}
    alerts.sort(key=lambda a: severity_rank.get(a.get("severity", "info"), 4))
    return alerts
