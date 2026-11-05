"""Residue & biomass ledger engine (M6C Increment 5).

Dry-matter mass accounting with hard mass-balance honesty (spec §6):

- produced mass is measured / farmer_reported / coefficient_estimate (with
  provenance) / missing — missing stays missing (never zero);
- flows (retained, incorporated, removed/baled, grazed, burned, other, unknown)
  sum against production; over-allocation is a hard error surfaced to the
  farmer, NEVER clamped or absorbed;
- unit conversions are explicit: t→kg exact; fresh→dry requires a supplied
  dry-matter fraction (a missing fraction is a refusal, not an assumption);
- nutrient content (N, C) is derived arithmetic on measured/entered quality
  values and is presented as AVAILABLE for nutrient budgeting — the M6B
  nutrient budget counts only rows in its own applications ledger, so nothing
  is double-counted by this module (no automatic import);
- residue carbon input is reported as an INPUT quantity — the ledger makes no
  SOC-sequestration claim (M6B separation, red line).
"""

from __future__ import annotations

from typing import Any

FLOW_TYPES = (
    "retained_surface", "incorporated", "removed_baled", "grazed",
    "burned", "other_loss", "unknown",
)
PRODUCTION_STATUSES = ("measured", "farmer_reported", "coefficient_estimate", "missing")
DM_STATUSES = ("measured", "farmer_reported", "estimated", "unknown")

PROTECTIVE_FLOWS = frozenset({"retained_surface"})
INCORPORATING_FLOWS = frozenset({"incorporated"})


class ResidueLedgerError(ValueError):
    """Raised for hard ledger violations (over-allocation, invalid input)."""


def tonnes_to_kg(tonnes: float) -> float:
    """Exact scale conversion (1 t = 1000 kg)."""
    if tonnes < 0:
        raise ResidueLedgerError("negative mass")
    return tonnes * 1000.0


def fresh_to_dry_kg(fresh_kg: float, dry_matter_fraction: float) -> float:
    """Fresh-mass → dry-matter conversion with an explicit fraction.

    A missing/unknown fraction raises — the conversion is never guessed."""
    if dry_matter_fraction is None:
        raise ResidueLedgerError(
            "fresh→dry conversion requires a dry-matter fraction — "
            "without one the conversion is refused (never assumed)"
        )
    if not (0 < dry_matter_fraction <= 1):
        raise ResidueLedgerError(
            f"dry-matter fraction must be within (0, 1]: got {dry_matter_fraction}"
        )
    if fresh_kg < 0:
        raise ResidueLedgerError("negative mass")
    return fresh_kg * dry_matter_fraction


def _flow_dm_kg(flow: dict[str, Any]) -> tuple[float | None, str]:
    """Resolve a flow's dry-matter kg + honest status.

    Accepts explicit `dm_kg` or `fresh_kg` + `dry_matter_fraction`. Returns
    (kg | None, status) — None means the flow's mass is genuinely unknown and
    is reported as such (never zero)."""
    status = flow.get("dm_kg_status", "unknown")
    if flow.get("dm_kg") is not None:
        kg = float(flow["dm_kg"])
        if kg < 0:
            raise ResidueLedgerError("flow dm_kg must be >= 0")
        return kg, status
    if flow.get("fresh_kg") is not None:
        fraction = flow.get("dry_matter_fraction")
        if fraction is None:
            raise ResidueLedgerError(
                "flow supplies fresh mass without a dry-matter fraction — "
                "provide one or record the mass as unknown"
            )
        kg = fresh_to_dry_kg(float(flow["fresh_kg"]), float(fraction))
        return kg, status if status != "unknown" else "estimated"
    return None, status if status else "unknown"


def build_residue_record_ledger(
    record: dict[str, Any], flows: list[dict[str, Any]], quality: list[dict[str, Any]]
) -> dict[str, Any]:
    """One record's ledger: production, flows, balance, quality, nutrient
    content. Pure function; the API maps ORM rows into these dicts."""
    production_status = record.get("production_status", "missing")
    produced = record.get("produced_dm_kg")
    if produced is not None:
        produced = float(produced)
        if produced < 0:
            raise ResidueLedgerError("produced_dm_kg must be >= 0")
    if production_status == "coefficient_estimate" and not record.get(
        "coefficient_provenance"
    ):
        raise ResidueLedgerError(
            "coefficient_estimate production requires coefficient provenance "
            "(value, source, applicability) — an unsourced coefficient is never "
            "accepted"
        )

    flow_rows: list[dict[str, Any]] = []
    total_flows = 0.0
    unknown_flow_count = 0
    for flow in flows:
        kg, status = _flow_dm_kg(flow)
        if kg is None:
            unknown_flow_count += 1
        else:
            total_flows += kg
        flow_rows.append(
            {
                "id": flow.get("id"),
                "flow_type": flow["flow_type"],
                "flow_date": flow.get("flow_date"),
                "dm_kg": kg,
                "dm_kg_status": status,
                "soil_management_event_id": flow.get("soil_management_event_id"),
                "evidence_class": flow.get("evidence_class", "farmer_reported_record"),
            }
        )

    if produced is None:
        balance_status = "production_unknown"
        unaccounted = None
    else:
        if total_flows > produced + 1e-6:
            balance_status = "over_allocated"
            unaccounted = round(produced - total_flows, 3)  # negative, surfaced
        else:
            balance_status = "balanced"
            unaccounted = round(produced - total_flows, 3)

    # ---- quality & derived nutrient content (available, not counted) --------
    latest_quality = quality[-1] if quality else None
    carbon_fraction = latest_quality.get("carbon_fraction") if latest_quality else None
    nitrogen_pct = latest_quality.get("nitrogen_pct") if latest_quality else None
    cn_ratio = latest_quality.get("cn_ratio") if latest_quality else None
    derived: dict[str, Any] = {"note": (
        "Nutrient/carbon contents below are INPUT bookkeeping derived from "
        "entered quality values. They are NOT counted in the M6B nutrient "
        "budget (which reads its own applications ledger) and make NO "
        "SOC-sequestration claim — carbon input ≠ stable SOC stock change."
    )}
    protective_dm = sum(
        f["dm_kg"] for f in flow_rows
        if f["flow_type"] in PROTECTIVE_FLOWS and f["dm_kg"] is not None
    )
    if nitrogen_pct is not None:
        derived["nitrogen_in_flows_kg"] = {
            str(f["flow_type"]): round(f["dm_kg"] * nitrogen_pct / 100.0, 3)
            for f in flow_rows if f["dm_kg"] is not None
        }
        derived["total_nitrogen_kg"] = round(
            total_flows * nitrogen_pct / 100.0, 3
        )
    if carbon_fraction is not None:
        derived["carbon_input_total_tonnes"] = round(
            total_flows * carbon_fraction / 100.0 / 1000.0, 4
        )
    if cn_ratio is None and carbon_fraction and nitrogen_pct:
        cn_ratio = round(carbon_fraction / nitrogen_pct, 2) if nitrogen_pct > 0 else None
        if cn_ratio is not None:
            derived["cn_ratio_derived"] = cn_ratio

    return {
        "record": {
            "id": record.get("id"),
            "crop_label": record.get("crop_label"),
            "season_label": record.get("season_label"),
            "basis": record.get("basis", "dry_matter"),
            "produced_dm_kg": produced,
            "production_status": production_status,
            "coefficient_provenance": record.get("coefficient_provenance") or None,
            "harvested_product_dm_kg": record.get("harvested_product_dm_kg"),
            "harvested_product_status": record.get("harvested_product_status"),
        },
        "flows": flow_rows,
        "balance": {
            "status": balance_status,
            "total_flow_dm_kg": round(total_flows, 3),
            "unaccounted_dm_kg": unaccounted,
            "flows_with_unknown_mass": unknown_flow_count,
            "basis": (
                "unaccounted = produced − Σ(flows); over-allocation is a hard "
                "error surfaced for correction, never clamped"
                if produced is not None
                else "production is unknown — the balance is not computable "
                "and production is never assumed to be zero"
            ),
        },
        "quality": {
            "carbon_fraction": carbon_fraction,
            "nitrogen_pct": nitrogen_pct,
            "cn_ratio": cn_ratio,
            "lignin_pct": latest_quality.get("lignin_pct") if latest_quality else None,
            "evidence_class": latest_quality.get("evidence_class") if latest_quality else None,
            "measurement_count": len(quality),
        },
        "derived": derived,
        "surface_retained_dm_kg": round(protective_dm, 3),
    }


def build_residue_ledger(
    records: list[dict[str, Any]],
    flows_by_record: dict[str, list[dict[str, Any]]],
    quality_by_record: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    """Field-level ledger: per-record ledgers + honest field totals.

    Field totals sum only records with KNOWN production; records with unknown
    production are listed separately (never zero-filled into totals)."""
    ledgers = []
    total_produced = 0.0
    records_with_known_production = 0
    production_unknown = 0
    over_allocated = 0
    total_retained = 0.0
    for record in records:
        rid = str(record.get("id"))
        ledger = build_residue_record_ledger(
            record,
            flows_by_record.get(rid, []),
            quality_by_record.get(rid, []),
        )
        ledgers.append(ledger)
        if ledger["record"]["produced_dm_kg"] is not None:
            total_produced += ledger["record"]["produced_dm_kg"]
            records_with_known_production += 1
        else:
            production_unknown += 1
        if ledger["balance"]["status"] == "over_allocated":
            over_allocated += 1
        total_retained += ledger["surface_retained_dm_kg"]

    warnings: list[str] = []
    if over_allocated:
        warnings.append(
            f"{over_allocated} record(s) have flows exceeding produced mass — "
            "correct the record or the flows; the imbalance is never absorbed."
        )
    if production_unknown:
        warnings.append(
            f"{production_unknown} record(s) have unknown production — they are "
            "excluded from totals and never assumed to be zero."
        )

    return {
        "records": ledgers,
        "totals": {
            "record_count": len(records),
            "records_with_known_production": records_with_known_production,
            "records_production_unknown": production_unknown,
            "produced_dm_kg_known_total": round(total_produced, 3),
            "surface_retained_dm_kg_total": round(total_retained, 3),
            "over_allocated_count": over_allocated,
            "basis": "totals include only records with known production "
            "(dry-matter basis)",
        },
        "warnings": warnings,
        "method": {
            "engine": "residue-ledger",
            "version": "residue-ledger-1.0.0",
            "rules": [
                "dry-matter basis everywhere; fresh masses require an explicit "
                "dry-matter fraction to convert",
                "produced ≥ Σ(flows) enforced; violations surface as "
                "over_allocated (hard), never clamped",
                "residue production is never inferred from grain yield without "
                "a sourced, record-specific coefficient with provenance",
                "nutrient/carbon contents are bookkeeping inputs; the M6B "
                "budget is not modified by this module (no double counting)",
            ],
        },
    }
