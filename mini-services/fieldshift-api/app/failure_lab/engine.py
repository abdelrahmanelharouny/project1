"""Failure-lab engine (P2.D): candidate rotations × stress packs.

Pure-ish core (no ORM, no I/O, no wall clock, sorted iteration — identical
inputs produce an identical result document, tested). The ORCHESTRATION and
persistence live in `service.py`; this module owns the evaluation semantics:

For every candidate rotation (a PINNED assignment — baseline from the field's
crop history, recommended/alternative from the field's latest succeeded
rotation run) and every stress pack the engine

1. builds the STRESSED problem: operational stresses act on `FarmContext`
   (allocation multiplier, margin-index penalty); climate stresses rebuild
   the month-of-year climatology (precipitation multiplier; temperature shift
   via the documented 'temperature-ET0 screening sensitivity') and recompute
   the per-season candidates through the existing M5/M6A candidate paths
   (`candidates.generate_candidates` → `estimate_water_requirement_mm` +
   `estimate_net_irrigation_mm` → `water.effective_rainfall`);
2. evaluates the PINNED assignment on the stressed problem with the EXISTING
   M5 post-hoc code (`objectives.evaluate_criteria`, `constraints.check_all`)
   — the lab answers "does the selected rotation survive the stress?", not
   "what would the optimizer choose under stress?" (no re-optimization, so
   `solver_status` is `not_attempted`, mirroring baseline strategies);
3. screens `timing` packs separately: the season start is shifted and the
   knowledge-base calendar windows are re-matched (window overlap ONLY —
   other criteria are never faked under the shift);
4. normalizes all criteria within the candidate×pack matrix (including the
   unstressed reference cells) via the reused `normalize_within_set`, and
   computes the robustness metrics of `metrics.py` on that shared basis.

Honesty rules (carried over from M5/M6A):

- Missing evidence is never zero: a pack dimension without its input
  (allocation, margins, climate evidence) is recorded as `not_evaluated`
  with the reason, and the corresponding stress is NOT silently applied.
- Every recomputed number carries its basis string; the temperature→ET0
  conversion is labelled as the documented 'temperature-ET0 screening
  sensitivity' approximation.
- Every infeasible/violated case produces a failure explanation with a named
  constraint, evidence references, a severity and a constraint-specific
  mitigation.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import timedelta
from typing import Any

from app.failure_lab import metrics as metrics_mod
from app.failure_lab.contracts import (
    FAILURE_LAB_ENGINE_VERSION,
    StressPack,
)
from app.rotation import candidates as candidates_mod
from app.rotation import constraints as constraints_mod
from app.rotation import objectives as objectives_mod
from app.rotation.problem import (
    ClimateEvidence,
    CriterionResult,
    FarmContext,
    RotationProblem,
    SeasonSpec,
    StrategySolution,
)

# Documented screening sensitivity: +1 degC mean temperature ≈ +3.5%
# reference ET0 (applied multiplicatively per degree). An approximation by
# construction — every number derived from it carries this label.
TEMPERATURE_ET0_SENSITIVITY_PER_DEGC = 0.035

# The unstressed reference cells of the matrix (per candidate) join the
# normalization but never the pack-based metrics.
UNSTRESSED_REFERENCE_KEY = "__unstressed__"

TIMING_CONSTRAINT_CODE = "planting_window_shift"

MITIGATIONS_BY_CONSTRAINT: dict[str, str] = {
    "water_allocation": (
        "Consider candidates with a lower net irrigation requirement "
        "(drought-tolerant or shorter-cycle options from the pool), improve "
        "irrigation conveyance/application efficiency, or renegotiate the "
        "seasonal allocation before the season starts."
    ),
    "candidate_admissibility": (
        "Replace the affected crop with a candidate that stays admissible "
        "under the stress, or revisit the stress assumption with local data."
    ),
    TIMING_CONSTRAINT_CODE: (
        "Choose crops whose planting windows still overlap the delayed "
        "season start, or move the affected crop to the next suitable "
        "season."
    ),
    "rotation_break_confirmed_regional": (
        "Reorder the season sequence so the confirmed break requirement is "
        "honoured."
    ),
    "one_crop_per_season": (
        "Ensure every planning season carries an assignment before "
        "interpreting stress results."
    ),
}

SEVERITY_BY_CONSTRAINT: dict[str, str] = {
    "water_allocation": "estimated",  # screening water numbers (ETc/NIR)
    "candidate_admissibility": "estimated",  # stress-induced exclusions (climate screening)
    TIMING_CONSTRAINT_CODE: "certain",  # deterministic calendar arithmetic on cited windows
    "rotation_break_confirmed_regional": "certain",  # confirmed knowledge rules
    "one_crop_per_season": "certain",
}


@dataclass(frozen=True)
class CandidateSpec:
    """One candidate rotation entering the stress matrix (a pinned
    assignment + where it came from). Built by `service.py` from the field's
    crop history and the latest succeeded rotation run."""

    candidate_key: str
    origin: str  # history | rotation_run
    strategy_profile: str | None
    assignment: tuple[tuple[str, str | None], ...]
    source_note: str

    @property
    def assignment_dict(self) -> dict[str, str | None]:
        return dict(self.assignment)

    def document(self) -> dict[str, Any]:
        return {
            "candidate_key": self.candidate_key,
            "origin": self.origin,
            "strategy_profile": self.strategy_profile,
            "assignment": [
                {"season_label": lbl, "crop_code": cc} for lbl, cc in self.assignment
            ],
            "source_note": self.source_note,
        }


# ------------------------------------------------------------- stressed inputs


def stressed_climate(
    evidence: ClimateEvidence, pack: StressPack
) -> tuple[ClimateEvidence, list[str]]:
    """Apply the pack's climate dimensions to one season's climatology.

    Precipitation: monthly climatology × multiplier (season aggregate scaled
    identically). Temperature: the season mean shifts by `temperature_delta_c`
    and monthly ET0 follows the documented temperature-ET0 screening
    sensitivity. Returns (stressed evidence, basis notes)."""
    notes: list[str] = []
    precip_mult = pack.parameters.get("precipitation_multiplier")
    temp_delta = pack.parameters.get("temperature_delta_c")
    et0_factor = 1.0
    basis_parts: list[str] = []

    monthly_precip = evidence.monthly_precip
    season_precip = evidence.season_precipitation_mm
    if precip_mult is not None and precip_mult != 1.0:
        monthly_precip = tuple(
            (y, m, round(v * float(precip_mult), 4)) for y, m, v in evidence.monthly_precip
        )
        if season_precip is not None:
            season_precip = round(season_precip * float(precip_mult), 2)
        basis_parts.append(f"precipitation × {precip_mult}")
        notes.append(
            f"pack '{pack.code}': monthly precipitation climatology of season "
            f"'{evidence.feature_run_id}' scaled by {precip_mult} (month-of-year "
            "climatology transformation — historical proxy, not a forecast)."
        )

    monthly_et0 = evidence.monthly_et0
    season_et0 = evidence.season_et0_mm
    mean_temp = evidence.season_mean_temp_degC
    if temp_delta is not None and temp_delta != 0.0:
        et0_factor = (1.0 + TEMPERATURE_ET0_SENSITIVITY_PER_DEGC) ** float(temp_delta)
        monthly_et0 = tuple(
            (y, m, round(v * et0_factor, 4)) for y, m, v in evidence.monthly_et0
        )
        if season_et0 is not None:
            season_et0 = round(season_et0 * et0_factor, 2)
        if mean_temp is not None:
            mean_temp = round(mean_temp + float(temp_delta), 2)
        basis_parts.append(
            f"temperature {temp_delta:+g} degC (ET0 × {et0_factor:.4f} via the "
            "temperature-ET0 screening sensitivity)"
        )
        notes.append(
            f"pack '{pack.code}': season mean temperature shifted by "
            f"{temp_delta:+g} degC and monthly ET0 scaled by {et0_factor:.4f} "
            "(temperature-ET0 screening sensitivity: +1 degC ≈ +3.5% ET0 — a "
            "documented approximation, not a physical model)."
        )

    if not basis_parts:
        return evidence, []
    basis = evidence.basis + " STRESSED (" + "; ".join(basis_parts) + ")."
    return (
        replace(
            evidence,
            season_precipitation_mm=season_precip,
            season_mean_temp_degC=mean_temp,
            season_et0_mm=season_et0,
            monthly_et0=monthly_et0,
            monthly_precip=monthly_precip,
            basis=basis,
            warnings=evidence.warnings
            + tuple(
                f"climate stressed by pack '{pack.code}'; hot-day counts NOT shifted"
                if temp_delta
                else f"climate stressed by pack '{pack.code}'"
            ),
        ),
        notes,
    )


def stressed_farm(
    farm: FarmContext, pack: StressPack
) -> tuple[FarmContext, list[dict[str, Any]], list[str]]:
    """Apply the pack's operational + climate dimensions to the farm context.

    Returns (stressed farm, not_evaluated entries, engine notes). Dimensions
    whose farmer-supplied input is missing are recorded as `not_evaluated`
    and left UNSTRESSED — never invented, never zero-filled."""
    not_evaluated: list[dict[str, Any]] = []
    notes: list[str] = []
    updates: dict[str, Any] = {}

    def _not_evaluated(dimension: str, reason: str, season_label: str | None = None) -> None:
        not_evaluated.append({
            "dimension": dimension,
            "pack_code": pack.code,
            "candidate_key": None,
            "season_label": season_label,
            "reason": reason,
        })

    alloc_mult = pack.parameters.get("water_allocation_multiplier")
    if alloc_mult is not None:
        if farm.water_allocation_m3 is None:
            _not_evaluated(
                "water_allocation",
                "no farmer-supplied water allocation — the allocation "
                "multiplier has nothing to act on (never invented)",
            )
        else:
            updates["water_allocation_m3"] = round(
                farm.water_allocation_m3 * float(alloc_mult), 3
            )
            notes.append(
                f"pack '{pack.code}': seasonal water allocation "
                f"{farm.water_allocation_m3:.0f} m3 × {alloc_mult} = "
                f"{updates['water_allocation_m3']:.0f} m3. Water REQUIREMENT "
                "coefficients are climatology-based; only the ALLOCATION side "
                "is stressed."
            )

    margin_penalty = pack.parameters.get("margin_index_penalty")
    if margin_penalty is not None:
        if not farm.margin_index_by_crop:
            _not_evaluated(
                "economic_margin_index",
                "no farmer-supplied margin data — the margin-index penalty "
                "has nothing to act on (economics is never invented)",
            )
        else:
            updates["margin_index_by_crop"] = {
                crop: max(0.0, round(idx - float(margin_penalty), 4))
                for crop, idx in sorted(farm.margin_index_by_crop.items())
            }
            notes.append(
                f"pack '{pack.code}': farmer margin index reduced by "
                f"{margin_penalty} (floored at 0) for "
                f"{len(updates['margin_index_by_crop'])} crop(s)."
            )

    climate_dims = (
        pack.parameters.get("precipitation_multiplier") is not None
        or pack.parameters.get("temperature_delta_c") is not None
    )
    if climate_dims:
        stressed_climate_by_season: dict[str, ClimateEvidence] = {}
        for label in sorted(farm.climate_by_season):
            stressed, climate_notes = stressed_climate(
                farm.climate_by_season[label], pack
            )
            stressed_climate_by_season[label] = stressed
            notes.extend(climate_notes)
        missing = [s.label for s in farm.seasons if s.label not in farm.climate_by_season]
        for label in sorted(missing):
            _not_evaluated(
                "climate_stress",
                "no climate evidence for this season — the climate stress is "
                "not applied to it (missing evidence is never treated as zero)",
                season_label=label,
            )
        if stressed_climate_by_season:
            updates["climate_by_season"] = stressed_climate_by_season

    if not updates:
        return farm, not_evaluated, notes
    return replace(farm, **updates), not_evaluated, notes


def stressed_problem(
    base_problem: RotationProblem, farm: FarmContext, *, regenerate_candidates: bool
) -> tuple[RotationProblem, list[str]]:
    """Rebuild the problem on the stressed farm. Climate-stressed packs
    regenerate the per-season candidate assessments (water numbers, temperature
    screening) through the existing candidate paths; operational-only packs
    keep the base assessments (their inputs are unchanged)."""
    notes: list[str] = []
    if regenerate_candidates:
        assessments = candidates_mod.generate_candidates(base_problem.knowledge, farm)
        notes.append(
            "candidate water requirements recomputed from the STRESSED "
            "climatology (FAO-56 single-Kc ETc and net irrigation requirement "
            "via effective_rainfall_mm) — climatology-based, not a forecast."
        )
    else:
        assessments = base_problem.candidates
    problem = replace(
        base_problem,
        farm=farm,
        candidates=assessments,
        water_allocation_m3=farm.water_allocation_m3,
    )
    return problem, notes


# --------------------------------------------------------------- timing screen


def timing_screen(
    knowledge: Any,
    farm: FarmContext,
    shift_days: int,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Calendar-window feasibility screen under a delayed season start.

    For each season the start date is shifted by `shift_days`; a knowledge
    crop is timing-infeasible when NO of its (hemisphere/region-matched)
    planting windows overlaps the shifted season. Crops without any calendar
    window for the hemisphere are `not_evaluated` for timing (mirroring
    candidate generation). Only window overlap is screened — no other
    criterion is re-evaluated under the shift."""
    from app.rotation.candidates import _windows_for_field, _window_planting_overlap

    screens: list[dict[str, Any]] = []
    notes: list[str] = []
    for season in farm.seasons:
        shifted = replace(season, start_date=season.start_date + timedelta(days=shift_days))
        infeasible: list[str] = []
        not_evaluated: list[str] = []
        feasible: list[str] = []
        for code in sorted(knowledge.crops):
            crop = knowledge.crops[code]
            windows = _windows_for_field(crop, farm.hemisphere, farm.country_code)
            if not windows:
                not_evaluated.append(code)
                continue
            if any(
                _window_planting_overlap(shifted, w.planting_start, w.planting_end)
                is not None
                for w in windows
            ):
                feasible.append(code)
            else:
                infeasible.append(code)
        screens.append({
            "season_label": season.label,
            "original_start_date": season.start_date.isoformat(),
            "shifted_start_date": shifted.start_date.isoformat(),
            "shift_days": shift_days,
            "timing_infeasible_crops": infeasible,
            "timing_feasible_crops": feasible,
            "timing_not_evaluated_crops": not_evaluated,
        })
        notes.append(
            f"delayed planting screen for season '{season.label}': start "
            f"{season.start_date.isoformat()} → {shifted.start_date.isoformat()} "
            f"(+{shift_days} d); {len(infeasible)} crop(s) lose all overlapping "
            "planting windows. Feasibility screening only — no other criterion "
            "re-evaluated under the shift."
        )
    return screens, notes


# ----------------------------------------------------------------- evaluation


def _criteria_payload(criteria: tuple[CriterionResult, ...]) -> list[dict[str, Any]]:
    """Serialize criteria exactly like rotation-run strategies (same basis)."""
    return [
        {
            "criterion_code": c.criterion_code,
            "raw_value": c.raw_value,
            "unit": c.unit,
            "direction": c.direction,
            "normalized": c.normalized,
            "evaluable": c.evaluable,
            "missing_evidence": list(c.missing_evidence),
            "derivation": c.derivation,
            "source_refs": list(c.source_refs),
        }
        for c in criteria
    ]


def _water_block(problem: RotationProblem, assignment: dict[str, str | None]) -> dict[str, Any]:
    """Per-cell water document: stressed allocation vs the assigned crops'
    estimated demand (NIR when evaluable, else the ETc screening upper bound)."""
    allocation = problem.water_allocation_m3
    if allocation is None:
        return {
            "allocation_m3": None,
            "demand_m3_estimated": None,
            "basis": (
                "no farmer-supplied water allocation — demand is not compared "
                "to a constraint (and never invented)"
            ),
        }
    area_m2 = problem.farm.area_ha * 10_000.0
    total_mm = 0.0
    complete = True
    basis_parts: list[str] = []
    for season in problem.seasons:
        crop_code = assignment.get(season.label)
        if crop_code is None:
            continue
        assessment = problem.candidates.get(season.label, {}).get(crop_code)
        demand_mm = constraints_mod.water_demand_mm(assessment)
        if demand_mm is None:
            complete = False
            basis_parts.append(
                f"{season.label}: '{crop_code}' has no estimable water "
                "requirement (missing ET0/Kc evidence — never guessed)"
            )
            continue
        total_mm += demand_mm
        basis_parts.append(
            f"{season.label}: '{crop_code}' "
            f"{demand_mm:.1f} mm "
            f"({'net irrigation requirement' if assessment is not None and assessment.net_irrigation_requirement_mm is not None else 'ETc screening (NIR not evaluable)'})"
        )
    demand_m3: float | None = None
    if complete and total_mm > 0.0:
        demand_m3 = round(total_mm / 1000.0 * area_m2, 3)
    detail = ("; ".join(basis_parts) + " ") if basis_parts else ""
    basis = (
        "demand = Σ seasons max(NIR, ETc fallback) mm / 1000 × area m2; "
        + detail
        + "Coefficients are climatology-based — only the ALLOCATION side "
        "carries the pack multiplier."
    )
    return {
        "allocation_m3": allocation,
        "demand_m3_estimated": demand_m3,
        "basis": basis,
    }


def _evidence_ref(ref_type: str, ref_id: str, label: str) -> dict[str, str]:
    """Evidence reference in the recommendation system's item style."""
    return {"type": ref_type, "id": ref_id, "label": label}


def _pack_ref(pack: StressPack) -> dict[str, str]:
    return _evidence_ref(
        "stress_pack", pack.code, f"stress pack '{pack.code}' ({pack.label})"
    )


def _violation_entry(
    pack: StressPack,
    candidate_key: str,
    constraint: str,
    detail: str,
    evidence_refs: list[dict[str, str]],
) -> tuple[dict[str, str], dict[str, Any]]:
    """One constraint violation + its failure explanation."""
    entry = {"constraint": constraint, "detail": detail}
    refs = [_pack_ref(pack), *evidence_refs]
    explanation = {
        "what_failed": (
            f"Candidate rotation '{candidate_key}' does not survive stress pack "
            f"'{pack.code}' ({pack.label}): {detail}"
        ),
        "violated_constraint": constraint,
        "evidence_refs": refs,
        "pack": pack.code,
        "severity": SEVERITY_BY_CONSTRAINT.get(constraint, "estimated"),
        "possible_mitigation": MITIGATIONS_BY_CONSTRAINT.get(
            constraint,
            "Replace the affected crop or revisit the stress assumption with "
            "local data.",
        ),
    }
    return entry, explanation


def _candidate_violations(
    pack: StressPack,
    candidate: CandidateSpec,
    problem: RotationProblem,
    checks: list,
    timing: list[dict[str, Any]] | None,
) -> tuple[list[dict[str, str]], list[dict[str, Any]]]:
    """Violated-constraint entries + failure explanations for one cell."""
    violations: list[dict[str, str]] = []
    explanations: list[dict[str, Any]] = []
    for check in checks:
        if check.status != "violated":
            continue
        detail = f"{check.constraint_code}: {check.detail or check.description}"
        refs: list[dict[str, str]] = []
        if check.constraint_code == "water_allocation":
            for season in problem.seasons:
                crop_code = candidate.assignment_dict.get(season.label)
                if crop_code is None:
                    continue
                assessment = problem.candidates.get(season.label, {}).get(crop_code)
                demand_mm = constraints_mod.water_demand_mm(assessment)
                if demand_mm is None or problem.water_allocation_m3 is None:
                    continue
                need_m3 = demand_mm / 1000.0 * problem.farm.area_ha * 10_000.0
                refs.append(
                    _evidence_ref(
                        "water_number",
                        f"{season.label}:{crop_code}",
                        f"'{crop_code}' in season '{season.label}': demand "
                        f"{need_m3:.0f} m3 vs allocation "
                        f"{problem.water_allocation_m3:.0f} m3 (basis: "
                        f"{assessment.water_demand_basis or 'ETc screening'}; "
                        "climatology-based)",
                    )
                )
        elif check.constraint_code == "candidate_admissibility":
            for season in problem.seasons:
                crop_code = candidate.assignment_dict.get(season.label)
                assessment = (
                    problem.candidates.get(season.label, {}).get(crop_code)
                    if crop_code
                    else None
                )
                if assessment is None or assessment.admissible:
                    continue
                hard = next(
                    (r.get("message") for r in assessment.reasons if r.get("severity") == "hard"),
                    f"status '{assessment.status}' under stress",
                )
                refs.append(
                    _evidence_ref(
                        "candidate_assessment",
                        f"{season.label}:{assessment.crop_code}",
                        f"'{assessment.crop_code}' in season '{season.label}': {hard}",
                    )
                )
        elif check.constraint_code == "rotation_break_confirmed_regional":
            refs.extend(
                _evidence_ref("rotation_rule", rc.get("rule_code", "rule"), f"rule '{rc.get('rule_code', 'rule')}' cited in the constraint detail")
                for rc in check.source_refs
                if isinstance(rc, dict)
            )
        entry, explanation = _violation_entry(
            pack, candidate.candidate_key, check.constraint_code, detail, refs
        )
        violations.append(entry)
        explanations.append(explanation)

    if timing:
        infeasible_by_season = {
            s["season_label"]: s["timing_infeasible_crops"] for s in timing
        }
        for season in problem.seasons:
            crop_code = candidate.assignment_dict.get(season.label)
            if crop_code is None or crop_code not in infeasible_by_season.get(season.label, []):
                continue
            detail = (
                f"{season.label}: '{crop_code}' has no planting window overlapping "
                f"the season start delayed by "
                f"{pack.parameters.get('planting_window_shift_days')} days — "
                "timing-infeasible under the shift (calendar-window screening only)."
            )
            entry, explanation = _violation_entry(
                pack,
                candidate.candidate_key,
                TIMING_CONSTRAINT_CODE,
                detail,
                [
                    _evidence_ref(
                        "crop_calendar_window",
                        f"{season.label}:{crop_code}",
                        f"'{crop_code}' calendar windows vs delayed season start "
                        "(knowledge-base windows)",
                    )
                ],
            )
            violations.append(entry)
            explanations.append(explanation)
    return violations, explanations


def _evaluate_cell(
    pack: StressPack,
    candidate: CandidateSpec,
    problem: RotationProblem,
    timing: list[dict[str, Any]] | None,
) -> dict[str, Any]:
    """One candidate×pack cell: pinned assignment evaluated on the (stressed)
    problem with the existing M5 post-hoc code."""
    assignment = dict(candidate.assignment)
    checks = constraints_mod.check_all(problem, assignment)
    criteria = objectives_mod.evaluate_criteria(problem, assignment)
    violations, explanations = _candidate_violations(
        pack, candidate, problem, checks, timing
    )
    has_violation = bool(violations)
    has_undecided = any(c.status == "partially_checked" for c in checks)
    feasible: bool | None = False if has_violation else (None if has_undecided else True)
    return {
        "candidate_key": candidate.candidate_key,
        "pack_code": pack.code,
        "feasible": feasible,
        "solver_status": "not_attempted",  # pinned assignment — no re-optimization
        "assignment": [
            {"season_label": lbl, "crop_code": cc} for lbl, cc in candidate.assignment
        ],
        "criteria": _criteria_payload(criteria),
        "water": _water_block(problem, assignment),
        "constraint_violations": violations,
        "explanations": explanations,
        "timing_screen": timing,
    }


def _cell_sort_key(cell: dict[str, Any]) -> tuple[str, str]:
    pack = cell["pack_code"] or ""
    return (cell["candidate_key"], pack)


def _matrix_solutions(cells: list[dict[str, Any]]) -> list[StrategySolution]:
    """Wrap cells as StrategySolution shells so the EXISTING M5 normalizer
    (`objectives.normalize_within_set`) can min-max normalize each criterion
    within the candidate×pack matrix."""
    shells: list[StrategySolution] = []
    for cell in cells:
        criteria = tuple(
            CriterionResult(
                criterion_code=c["criterion_code"],
                raw_value=c["raw_value"],
                unit=c["unit"],
                direction=c["direction"],
                normalized=None,
                evaluable=c["evaluable"],
                missing_evidence=tuple(c["missing_evidence"]),
                derivation=c["derivation"],
                source_refs=tuple(c["source_refs"]),
            )
            for c in cell["criteria"]
        )
        shells.append(
            StrategySolution(
                strategy_key=cell["cell_key"],
                strategy_kind="stress_cell",
                is_baseline=False,
                profile_weights={},
                weights_effective={},
                skipped_weights={},
                assignment=tuple(
                    (a["season_label"], a["crop_code"]) for a in cell["assignment"]
                ),
                objective_value=None,
                criteria=criteria,
                constraints_checked=(),
                evidence_coverage=None,
                solver_status="not_attempted",
            )
        )
    return shells


def _apply_normalized(cells: list[dict[str, Any]], shells: list[StrategySolution]) -> None:
    """Copy the normalized values back from the rebuilt shells into the cell
    documents (in order)."""
    for cell, shell in zip(cells, shells):
        by_code = {c.criterion_code: c.normalized for c in shell.criteria}
        for c in cell["criteria"]:
            c["normalized"] = by_code.get(c["criterion_code"])


# ------------------------------------------------------------------- main entry


def run_stress_matrix(
    base_problem: RotationProblem,
    *,
    candidates: list[CandidateSpec],
    packs: list[StressPack],
) -> dict[str, Any]:
    """Run the full candidate×pack matrix on the unstressed base problem.

    Deterministic: sorted pack iteration, canonical candidate order, no wall
    clock in the returned document (timestamps live only in run metadata).
    Returns the result document persisted as `RotationStressRun.result`."""
    assumptions: list[str] = [
        "Water REQUIREMENT coefficients (net irrigation requirement / ETc "
        "screening) are climatology-based; precipitation and temperature "
        "stresses recompute the climatology, while water-allocation stresses "
        "act ONLY on the allocation side.",
        "Temperature stresses convert to ET0 via the 'temperature-ET0 "
        "screening sensitivity' (+1 degC ≈ +3.5% ET0, applied multiplicatively "
        "per degree) — a documented approximation, not a physical model.",
        "Delayed planting is screened for calendar-window feasibility ONLY; "
        "no other criterion is re-evaluated under the shift.",
        "Candidate rotations are evaluated as PINNED assignments under stress "
        "(no re-optimization): the lab answers whether the selected rotations "
        "survive the stress, not what the optimizer would choose instead.",
    ]

    # ---- unstressed reference cells (join the normalization basis)
    reference_cells: list[dict[str, Any]] = []
    reference_pack = StressPack(
        code=UNSTRESSED_REFERENCE_KEY,
        label="Unstressed reference",
        kind="reference",
        parameters={},
        assumption_note="The candidate evaluated on the unstressed base problem.",
        provenance={"source": "preset", "basis": "internal reference cell"},
    )
    for candidate in candidates:
        cell = _evaluate_cell(reference_pack, candidate, base_problem, None)
        cell["cell_key"] = f"{candidate.candidate_key}|{UNSTRESSED_REFERENCE_KEY}"
        cell["pack_code"] = None
        reference_cells.append(cell)

    # ---- pack cells (packs arrive sorted from contracts.resolve_packs)
    pack_cells: list[dict[str, Any]] = []
    not_evaluated: list[dict[str, Any]] = []
    for pack in sorted(packs, key=lambda p: p.code):
        farm, pack_not_evaluated, notes = stressed_farm(base_problem.farm, pack)
        not_evaluated.extend(pack_not_evaluated)
        assumptions.extend(notes)
        problem = base_problem
        timing: list[dict[str, Any]] | None = None
        has_climate_dims = (
            pack.parameters.get("precipitation_multiplier") is not None
            or pack.parameters.get("temperature_delta_c") is not None
        )
        has_problem_dims = has_climate_dims or (
            pack.parameters.get("water_allocation_multiplier") is not None
            or pack.parameters.get("margin_index_penalty") is not None
        )
        if has_problem_dims:
            problem, problem_notes = stressed_problem(
                base_problem, farm, regenerate_candidates=has_climate_dims
            )
            assumptions.extend(problem_notes)
        shift = pack.parameters.get("planting_window_shift_days")
        if shift is not None:
            timing, timing_notes = timing_screen(
                base_problem.knowledge, base_problem.farm, int(shift)
            )
            assumptions.extend(timing_notes)
        for candidate in candidates:
            cell = _evaluate_cell(pack, candidate, problem, timing)
            cell["cell_key"] = f"{candidate.candidate_key}|{pack.code}"
            pack_cells.append(cell)

    # ---- shared normalization basis across the WHOLE matrix
    matrix = reference_cells + pack_cells
    shells = _matrix_solutions(matrix)
    objectives_mod.normalize_within_set(shells)
    _apply_normalized(matrix, shells)

    for cell in matrix:
        cell["score"] = metrics_mod.normalized_score(
            [c["normalized"] for c in cell["criteria"]]
        )

    scores_by_candidate: dict[str, dict[str, float | None]] = {
        c.candidate_key: {} for c in candidates
    }
    feasible_by_candidate: dict[str, dict[str, bool | None]] = {
        c.candidate_key: {} for c in candidates
    }
    violations_by_candidate: dict[str, dict[str, bool]] = {
        c.candidate_key: {} for c in candidates
    }
    unstressed_scores: dict[str, float | None] = {}
    for cell in reference_cells:
        unstressed_scores[cell["candidate_key"]] = cell["score"]
    for cell in sorted(pack_cells, key=_cell_sort_key):
        key = cell["candidate_key"]
        scores_by_candidate[key][cell["pack_code"]] = cell["score"]
        feasible_by_candidate[key][cell["pack_code"]] = cell["feasible"]
        violations_by_candidate[key][cell["pack_code"]] = bool(
            cell["constraint_violations"]
        )

    best_by_pack = metrics_mod.best_score_by_pack(scores_by_candidate)
    robustness = [
        metrics_mod.candidate_robustness(
            candidate_key=key,
            scores_by_pack=scores_by_candidate[key],
            feasible_by_pack=feasible_by_candidate[key],
            violations_by_pack=violations_by_candidate[key],
            best_by_pack=best_by_pack,
            unstressed_score=unstressed_scores.get(key),
        )
        for key in (c.candidate_key for c in candidates)
    ]

    failure_explanations = [
        explanation
        for cell in sorted(pack_cells, key=_cell_sort_key)
        for explanation in cell["explanations"]
    ]

    return {
        "engine_version": FAILURE_LAB_ENGINE_VERSION,
        "metrics_version": metrics_mod.ROBUSTNESS_METRICS_VERSION,
        "scoring_basis": {
            "score": "normalized_score",
            "formula_text": metrics_mod.NORMALIZED_SCORE_FORMULA,
            "normalization": (
                "min-max within the candidate×pack matrix INCLUDING the "
                "unstressed reference cells (objectives.normalize_within_set, "
                "reused); single/zero evaluable values normalize to the "
                "documented neutral 0.5"
            ),
            "no_composite_claim": (
                "the score never mixes raw units and never combines an "
                "evaluable criterion with an unevaluable one; no arbitrary "
                "composite resilience score is produced"
            ),
        },
        "unstressed_reference": sorted(reference_cells, key=_cell_sort_key),
        "evaluations": sorted(pack_cells, key=_cell_sort_key),
        "robustness": robustness,
        "best_scores_by_pack": best_by_pack,
        "failure_explanations": failure_explanations,
        "not_evaluated": not_evaluated,
        "assumptions": assumptions,
    }
