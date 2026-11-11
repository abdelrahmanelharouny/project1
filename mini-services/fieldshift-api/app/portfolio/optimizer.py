"""Farm portfolio CP-SAT optimizer (P2.F) — the only portfolio module that
knows OR-Tools. A NEW model (the per-field rotation optimizer in
`app.rotation.optimizer` is untouched and reused only through its pure
helpers).

Deterministic: num_search_workers=1, random_seed=0, max_time_in_seconds=15.0
— identical inputs yield identical allocations (tested).

Decision variables: x[(field, season, crop)] = allocated area in integer
0.01-ha units, one per ADMISSIBLE candidate (candidate admissibility and
planting-window matching are inherited from `app.rotation.candidates` —
unevaluated/excluded crops never get a variable), plus a fallow pseudo-crop
per field-season that absorbs shortfall the shared constraints force. Fallow
carries zero water demand. One documented honesty rule guards it: fallow is a
PARTIAL-use allowance — a field-season with an available candidate must
cultivate at least one 0.01-ha unit, so a farm whose shared allocation
supports no cultivation at all is reported INFEASIBLE with the named
constraint instead of returning a silent do-nothing plan. Only field-seasons
with no available candidate may fallow completely.

Hard constraints are registered as solver ASSUMPTIONS (the exact pattern of
`app.rotation.optimizer`): infeasibility maps back through
`SufficientAssumptionsForInfeasibility` to named constraints — no silent
relaxation, explicit conflict identification.

The weighted objective is a DISCLOSED steering device: a weighted sum of
normalized 0-1 sub-scores (weights echoed as normalized shares). The reported
per-criterion evidence is ALWAYS recomputed post hoc by
`app.portfolio.evaluation.score_allocation` — the solver's internal objective
is never the reported agronomic result (the same rule as the rotation
engine).

Honesty: labor and machinery capacities are never enforced — no sourced
per-crop coefficients exist platform-wide and coefficients are never invented
(see `contracts.validate_constraints`). Water demand uses the net irrigation
requirement when evaluable, else the ETc screening value (a conservative
upper bound, disclosed) — the same fallback the rotation engine uses.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field as dc_field
from typing import Any

from ortools.sat.python import cp_model

from app.portfolio.contracts import (
    MODE_LEXICOGRAPHIC,
    MODE_WEIGHTED,
    OBJECTIVE_KEYS,
    normalized_shares,
)
from app.rotation.candidates import (
    _window_planting_overlap,
    _windows_for_field,
)
from app.rotation.optimizer import _norm_min_max, _per_crop_scores
from app.rotation.problem import (
    CandidateAssessment,
    FarmContext,
    KnowledgeBaseData,
    RANDOM_SEED,
    RotationProblem,
    SeasonSpec,
    SOLVER_NAME,
    solver_version,
)
from app.water.contracts import MM_PER_HA_TO_M3

logger = logging.getLogger("croptwist.portfolio")

MAX_SOLVE_SECONDS = 15.0
AREA_SCALE = 100  # one x unit = 0.01 ha (matches portfolio_allocations.area_ha)
OBJECTIVE_SCALE = 1_000_000  # one full-weight score unit in the steering objective
FALLOW_CROP_CODE = "__fallow__"
FALLOW_STATUS = "fallow"
ASSIGNED_STATUS = "assigned"

# resource_utilization shape: water use between 0 and 80% of the allocation is
# scored on a linear ramp (0 -> 0), use at or beyond 80% scores 1.0 — the
# criterion avoids BOTH breach (impossible: the allocation is hard) and gross
# underuse, without pressuring the solver to waste water.
RESOURCE_UTILIZATION_TARGET = 0.8

DIRECTION_MAXIMIZE = "maximize"


# ------------------------------------------------------------------ prepared


@dataclass(frozen=True)
class FieldInput:
    """One field of the portfolio (pure data — no ORM objects)."""

    field_id: str
    area_ha: float
    farm: FarmContext


@dataclass(frozen=True)
class PreparedCrop:
    """One admissible (field, season, crop) decision with its steering scores
    and water-demand coefficient. Scores follow the rotation engine's
    philosophy: solution-independent, normalized 0..1 within the field's
    candidate pool; criteria that cannot be scored from evidence are omitted
    (never zero-filled)."""

    field_idx: int
    season_idx: int
    crop_code: str
    family_key: str | None
    demand_mm: float | None
    demand_basis: str | None  # net_irrigation_requirement | etc_screening_fallback
    coeff_l: int | None  # water demand per 0.01-ha unit, litres (None: unknown)
    scores: dict[str, float] = dc_field(default_factory=dict)


@dataclass
class PreparedModel:
    """Everything the solver and the evaluation layer need, prepared once."""

    field_ids: list[str]
    fields: list[FieldInput]
    seasons: tuple[SeasonSpec, ...]
    knowledge: KnowledgeBaseData
    # one RotationProblem per field — drives score reuse AND the independent
    # per-field baseline in the evaluation layer
    problems: dict[str, RotationProblem]
    candidates: dict[str, dict[str, dict[str, CandidateAssessment]]]
    crops: list[PreparedCrop]
    weights: dict[str, float]
    weight_shares: dict[str, float]
    mode: str
    priority: list[str]
    constraints: dict[str, float | None]
    scenario: dict[str, Any] | None
    total_area_ha: float
    not_evaluated: list[dict[str, Any]] = dc_field(default_factory=list)
    warnings: list[str] = dc_field(default_factory=list)
    notes: list[str] = dc_field(default_factory=list)

    @property
    def total_scaled(self) -> int:
        return int(round(self.total_area_ha * AREA_SCALE))

    def area_scaled(self, field_idx: int) -> int:
        return int(round(self.fields[field_idx].area_ha * AREA_SCALE))

    def family_of(self, crop_code: str) -> str:
        crop = self.knowledge.crops.get(crop_code)
        family = crop.family_key if crop else None
        return family or f"__u__:{crop_code}"


# ----------------------------------------------------------------- prepare


def _duration_fit(assessment: CandidateAssessment) -> float:
    """Duration-fit flag from the candidate reasons (documented mapping):
    1.0 duration fits the season; 0.5 harvest spills within tolerance or the
    duration is unknown (conditional outcomes)."""
    codes = {r["code"] for r in assessment.reasons}
    if "duration_fits" in codes:
        return 1.0
    if "duration_spills" in codes or "window_matched_duration_unknown" in codes:
        return 0.5
    return 0.5


def _window_coverage(
    farm: FarmContext, crop_code: str, knowledge: KnowledgeBaseData, season: SeasonSpec
) -> float:
    """Best planting-window coverage of the season across the crop's matched
    windows (same matching logic as candidate generation)."""
    crop = knowledge.crops.get(crop_code)
    if crop is None:
        return 0.0
    best = 0.0
    for window in _windows_for_field(crop, farm.hemisphere, farm.country_code):
        overlap = _window_planting_overlap(season, window.planting_start, window.planting_end)
        if overlap is None:
            continue
        days = (overlap[1] - overlap[0]).days + 1
        best = max(best, min(1.0, days / season.length_days))
    return best


def prepare_model(
    *,
    fields: list[FieldInput],
    seasons: list[SeasonSpec],
    candidates_by_field: dict[str, dict[str, dict[str, CandidateAssessment]]],
    knowledge: KnowledgeBaseData,
    weights: dict[str, float],
    mode: str,
    constraints: dict[str, float | None],
    scenario: dict[str, Any] | None,
    not_evaluated: list[dict[str, Any]] | None = None,
    warnings: list[str] | None = None,
) -> PreparedModel:
    """Build the prepared portfolio model from pure inputs.

    `constraints` must already be validated/canonicalized by
    `contracts.validate_constraints`; `weights` by
    `contracts.validate_objective_weights`. Candidate generation and the
    per-field FarmContexts are the caller's responsibility (the service does
    the DB work; tests build pure fixtures).
    """
    if not fields:
        raise ValueError("prepare_model needs at least one field.")
    if not seasons:
        raise ValueError("prepare_model needs at least one season.")

    fields = sorted(fields, key=lambda f: (f.farm.area_ha is None, str(f.field_id)))
    not_evaluated = list(not_evaluated or [])
    warnings = list(warnings or [])
    water_constraint_active = constraints.get("water_allocation_m3") is not None

    crops: list[PreparedCrop] = []
    problems: dict[str, RotationProblem] = {}
    demand_basis_counts = {"net_irrigation_requirement": 0, "etc_screening_fallback": 0}
    held_out: list[str] = []

    for field_idx, fin in enumerate(fields):
        farm = fin.farm
        candidates = candidates_by_field[str(fin.field_id)]

        problem = RotationProblem(
            field_id=str(fin.field_id),
            seasons=tuple(seasons),
            candidates=candidates,
            knowledge=knowledge,
            farm=farm,
            water_allocation_m3=farm.water_allocation_m3,
            baseline_assignment=tuple((s.label, None) for s in seasons),
            synthetic_evidence=farm.synthetic_evidence_in_use,
        )
        problems[str(fin.field_id)] = problem

        # admissible pool per season (ADR-0016 semantics, inherited)
        admissible_by_season: dict[int, list[str]] = {}
        for s_idx, season in enumerate(seasons):
            pool = [
                code
                for code, assessment in candidates.get(season.label, {}).items()
                if assessment.admissible
            ]
            # with a hard shared allocation, crops without ANY water-demand
            # estimate are held out (mirror of the rotation optimizer; the
            # ETc fallback covers every crop that has an estimate at all)
            kept: list[str] = []
            for code in sorted(pool):
                assessment = candidates[season.label][code]
                demand = (
                    assessment.net_irrigation_requirement_mm
                    if assessment.net_irrigation_requirement_mm is not None
                    else assessment.water_requirement_mm
                )
                if water_constraint_active and demand is None:
                    held_out.append(f"{fin.field_id}/{season.label}:{code}")
                    continue
                kept.append(code)
            admissible_by_season[s_idx] = kept

        pool_union = sorted({c for codes in admissible_by_season.values() for c in codes})

        # ---- steering score tables (rotation philosophy, per field) --------
        # soil health: REUSED verbatim from the rotation engine's pure
        # per-crop score helper (same constants, same formula — cross-checked
        # by tests).
        soil_table: dict[str, float] = {}
        if pool_union:
            tables, _skipped = _per_crop_scores(problem, pool_union)
            soil_table = dict(tables.get("soil_health_index", {}))

        # water efficiency: inverse of the per-ha demand (NIR, else ETc
        # fallback — the SAME fallback the water constraint uses), normalized
        # across the field's candidate crops on the first evaluable season
        # (the same first-season pooling the rotation engine reports).
        water_demand_first: dict[str, float] = {}
        for code in pool_union:
            for season in seasons:
                assessment = candidates.get(season.label, {}).get(code)
                if assessment is None:
                    continue
                demand = (
                    assessment.net_irrigation_requirement_mm
                    if assessment.net_irrigation_requirement_mm is not None
                    else assessment.water_requirement_mm
                )
                if demand is not None:
                    water_demand_first[code] = demand
                    break
        water_table = _norm_min_max(water_demand_first, invert=True) if water_demand_first else {}

        crops.extend(
            _build_field_crops(
                field_idx=field_idx,
                fin=fin,
                seasons=seasons,
                candidates=candidates,
                admissible_by_season=admissible_by_season,
                soil_table=soil_table,
                water_table=water_table,
                demand_basis_counts=demand_basis_counts,
                knowledge=knowledge,
            )
        )

    if held_out:
        not_evaluated.append(
            {
                "code": "water_demand_estimate",
                "reason": (
                    "crops held out of the allocation because no water-demand "
                    "estimate (NIR or ETc screening) is evaluable while a hard "
                    "shared water allocation is active: " + ", ".join(sorted(held_out))
                ),
            }
        )

    shares = normalized_shares(weights)
    priority = [
        k for k, w in sorted(weights.items(), key=lambda kv: (-kv[1], kv[0])) if w > 0
    ]

    return PreparedModel(
        field_ids=[str(f.field_id) for f in fields],
        fields=fields,
        seasons=tuple(seasons),
        knowledge=knowledge,
        problems=problems,
        candidates=candidates_by_field,
        crops=crops,
        weights=dict(weights),
        weight_shares=shares,
        mode=mode,
        priority=priority,
        constraints=dict(constraints),
        scenario=scenario,
        total_area_ha=sum(f.area_ha for f in fields),
        not_evaluated=not_evaluated,
        warnings=warnings,
        notes=[],
    )


def _build_field_crops(
    *,
    field_idx: int,
    fin: FieldInput,
    seasons: list[SeasonSpec],
    candidates: dict[str, dict[str, CandidateAssessment]],
    admissible_by_season: dict[int, list[str]],
    soil_table: dict[str, float],
    water_table: dict[str, float],
    demand_basis_counts: dict[str, int],
    knowledge: KnowledgeBaseData,
) -> list[PreparedCrop]:
    out: list[PreparedCrop] = []
    farm = fin.farm
    for s_idx, season in enumerate(seasons):
        for code in admissible_by_season[s_idx]:
            assessment = candidates[season.label][code]
            if assessment.net_irrigation_requirement_mm is not None:
                demand = assessment.net_irrigation_requirement_mm
                basis = "net_irrigation_requirement"
            elif assessment.water_requirement_mm is not None:
                demand = assessment.water_requirement_mm
                basis = "etc_screening_fallback"
            else:
                demand = None
                basis = None
            scores: dict[str, float] = {}
            if code in water_table:
                scores["water_efficiency"] = water_table[code]
            if code in soil_table:
                scores["soil_health"] = soil_table[code]
            scores["operational_feasibility"] = round(
                0.5 * _window_coverage(farm, code, knowledge, season)
                + 0.5 * _duration_fit(assessment),
                6,
            )
            if basis is not None:
                demand_basis_counts[basis] += 1
            out.append(
                PreparedCrop(
                    field_idx=field_idx,
                    season_idx=s_idx,
                    crop_code=code,
                    family_key=(
                        knowledge.crops[code].family_key if code in knowledge.crops else None
                    ),
                    demand_mm=demand,
                    demand_basis=basis,
                    coeff_l=int(round(demand * 100.0)) if demand is not None else None,
                    scores=scores,
                )
            )
    out.sort(key=lambda c: (c.field_idx, c.season_idx, c.crop_code))
    return out


# ------------------------------------------------------------------- solve


@dataclass
class PortfolioSolution:
    """Typed solve outcome. `status` mirrors the rotation engine's semantics:
    'optimal'/'feasible' carry allocations; 'infeasible' carries named
    conflicts; 'unknown'/'model_invalid' are solver failures and fabricate
    nothing."""

    status: str
    allocations: list[dict[str, Any]]
    objective_value: float | None
    per_criterion_scores: dict[str, dict[str, Any]]
    binding_constraints: list[dict[str, Any]]
    diagnostics: dict[str, Any]
    conflicts: list[dict[str, Any]] = dc_field(default_factory=list)
    notes: list[str] = dc_field(default_factory=list)


class _AssumptionRegistry:
    """The rotation optimizer's assumption pattern, verbatim: every hard
    constraint is enforced OnlyEnforceIf(an assumption literal); the literals
    are fixed true for the solve and an infeasibility maps back through
    SufficientAssumptionsForInfeasibility to named constraints."""

    def __init__(self, model: cp_model.CpModel) -> None:
        self._model = model
        self._vars: list[Any] = []
        self._labels: dict[int, dict[str, Any]] = {}

    def register(self, label: dict[str, Any], enforce: Any) -> None:
        assumption = self._model.NewBoolVar(f"assume_{len(self._vars)}")
        self._model.Add(enforce).OnlyEnforceIf(assumption)
        self._vars.append(assumption)
        # SufficientAssumptionsForInfeasibility returns MODEL VARIABLE
        # indices, not positions in our list — key by the variable's index.
        self._labels[assumption.Index()] = label

    def attach(self, model: cp_model.CpModel) -> None:
        if self._vars:
            model.AddAssumptions(self._vars)

    def conflicts(self, solver: cp_model.CpSolver) -> list[dict[str, Any]]:
        found: list[dict[str, Any]] = []
        try:
            for idx in solver.SufficientAssumptionsForInfeasibility():
                label = self._labels.get(idx)
                if label:
                    found.append(label)
        except Exception:  # noqa: BLE001 — older ortools may lack the API
            pass
        return found


def _effective_water_allocation(model: PreparedModel) -> float | None:
    base = model.constraints.get("water_allocation_m3")
    if base is None:
        return None
    multiplier = 1.0
    if model.scenario is not None:
        multiplier = float(model.scenario.get("water_allocation_multiplier", 1.0) or 0.0)
    return max(0.0, float(base) * multiplier)


def solve_portfolio(model: PreparedModel) -> PortfolioSolution:
    """Build and solve the deterministic CP-SAT portfolio model."""
    cp = cp_model.CpModel()
    registry = _AssumptionRegistry(cp)
    total_scaled = model.total_scaled
    seasons = model.seasons

    # ---- variables ---------------------------------------------------------
    x: dict[tuple[int, int, str], Any] = {}
    by_field_season: dict[tuple[int, int], list[PreparedCrop]] = {}
    for crop in model.crops:
        var = cp.NewIntVar(0, model.area_scaled(crop.field_idx), f"x_{crop.field_idx}_{crop.season_idx}_{crop.crop_code}")
        x[(crop.field_idx, crop.season_idx, crop.crop_code)] = var
        by_field_season.setdefault((crop.field_idx, crop.season_idx), []).append(crop)

    fallow: dict[tuple[int, int], Any] = {}
    for f_idx in range(len(model.fields)):
        for s_idx in range(len(seasons)):
            hi = model.area_scaled(f_idx)
            if by_field_season.get((f_idx, s_idx)):
                # partial-use honesty rule: with an available candidate the
                # field-season cannot be 100% fallow (see module docstring)
                hi = max(0, hi - 1)
            fallow[(f_idx, s_idx)] = cp.NewIntVar(
                0, hi, f"fallow_{f_idx}_{s_idx}"
            )

    # ---- area conservation (structural equality, not an assumption) --------
    for f_idx in range(len(model.fields)):
        for s_idx in range(len(seasons)):
            terms = [v for (f, s, _c), v in x.items() if f == f_idx and s == s_idx]
            terms.append(fallow[(f_idx, s_idx)])
            cp.Add(sum(terms) == model.area_scaled(f_idx))

    # ---- shared water allocation (assumption) ------------------------------
    water_alloc_m3 = _effective_water_allocation(model)
    water_terms: list[Any] = []
    if water_alloc_m3 is not None:
        alloc_l = int(round(water_alloc_m3 * 1000.0))
        for crop in model.crops:
            if crop.coeff_l is not None:
                water_terms.append(x[(crop.field_idx, crop.season_idx, crop.crop_code)] * crop.coeff_l)
        if water_terms:
            fallback_note = any(c.demand_basis == "etc_screening_fallback" for c in model.crops)
            registry.register(
                {
                    "constraint": "water_allocation",
                    "detail": (
                        f"Farm water demand within the shared allocation "
                        f"({water_alloc_m3:.0f} m3"
                        + (
                            f" = {model.constraints.get('water_allocation_m3')} m3 x "
                            f"scenario multiplier {model.scenario.get('water_allocation_multiplier')}"
                            if model.scenario is not None
                            and model.scenario.get("water_allocation_multiplier") is not None
                            and float(model.scenario.get("water_allocation_multiplier", 1.0)) != 1.0
                            else ""
                        )
                        + "). Demand basis: net irrigation requirement (NIR mm x "
                        f"{MM_PER_HA_TO_M3} m3/ha/mm)"
                        + (
                            "; crops without an evaluable NIR use the ETc screening "
                            "value — a conservative upper bound (disclosed)."
                            if fallback_note
                            else "."
                        )
                    ),
                },
                sum(water_terms) <= alloc_l,
            )

    # ---- family share cap (assumption) --------------------------------------
    max_family_share = model.constraints.get("max_family_share")
    family_cap_entries: list[dict[str, Any]] = []
    if max_family_share is not None:
        cap_scaled = int(round(float(max_family_share) * total_scaled))
        for s_idx, season in enumerate(seasons):
            per_family: dict[str, list[Any]] = {}
            for crop in model.crops:
                if crop.season_idx != s_idx:
                    continue
                key = model.family_of(crop.crop_code)
                per_family.setdefault(key, []).append(
                    x[(crop.field_idx, crop.season_idx, crop.crop_code)]
                )
            for family in sorted(per_family):
                registry.register(
                    {
                        "constraint": "family_share_cap",
                        "season_label": season.label,
                        "family_key": family,
                        "detail": (
                            f"Season {season.label}: combined area of family "
                            f"'{family}' across the farm <= {max_family_share} x "
                            f"total farm area ({cap_scaled / AREA_SCALE:.2f} ha)."
                        ),
                    },
                    sum(per_family[family]) <= cap_scaled,
                )
                family_cap_entries.append(
                    {"season_label": season.label, "family_key": family, "cap_scaled": cap_scaled}
                )

    # ---- steering objective --------------------------------------------------
    stage_exprs = _criterion_expressions(cp, model, x)
    diagnostics: dict[str, Any] = {
        "solver": SOLVER_NAME,
        "solver_version": solver_version(),
        "random_seed": RANDOM_SEED,
        "num_search_workers": 1,
        "max_time_in_seconds": MAX_SOLVE_SECONDS,
        "mode": model.mode,
        "variables": len(x) + len(fallow),
        "demand_basis_counts": {
            "net_irrigation_requirement": sum(
                1 for c in model.crops if c.demand_basis == "net_irrigation_requirement"
            ),
            "etc_screening_fallback": sum(
                1 for c in model.crops if c.demand_basis == "etc_screening_fallback"
            ),
        },
        "fallow_rule": (
            "fallow is a partial-use allowance: a field-season with an available "
            "candidate cultivates at least one 0.01-ha unit; a fully fallowed "
            "field-season is possible only when no candidate is available"
        ),
    }

    solver, status_name, internal_objective, stage_values, wall_ms = _run_solves(
        cp, model, registry, stage_exprs
    )
    diagnostics["wall_time_ms"] = wall_ms
    diagnostics["status_name"] = status_name
    if stage_values is not None:
        diagnostics["lexicographic_stages"] = stage_values

    if status_name == "infeasible":
        conflicts = registry.conflicts(solver)
        if not conflicts:
            conflicts.append(
                {
                    "constraint": "combined_constraints",
                    "detail": (
                        "No allocation satisfies the area balance (with the "
                        "partial-use fallow rule) together with the active "
                        "shared constraints."
                    ),
                }
            )
        logger.info("portfolio solve infeasible: %d named conflicts", len(conflicts))
        return PortfolioSolution(
            status="infeasible",
            allocations=[],
            objective_value=None,
            per_criterion_scores={},
            binding_constraints=[],
            diagnostics=diagnostics,
            conflicts=conflicts,
        )
    if status_name in ("model_invalid", "unknown"):
        return PortfolioSolution(
            status=status_name,
            allocations=[],
            objective_value=None,
            per_criterion_scores={},
            binding_constraints=[],
            diagnostics=diagnostics,
            conflicts=[
                {
                    "constraint": "solver_failure",
                    "detail": (
                        f"Solver ended with status {status_name} — no solution is "
                        "fabricated and nothing is concluded about the constraints."
                    ),
                }
            ],
        )

    # ---- extract ------------------------------------------------------------
    allocations: list[dict[str, Any]] = []
    for (f_idx, s_idx, code), var in sorted(
        x.items(), key=lambda kv: (kv[0][0], kv[0][1], kv[0][2])
    ):
        units = solver.Value(var)
        if units <= 0:
            continue
        prepared = next(
            c
            for c in model.crops
            if c.field_idx == f_idx and c.season_idx == s_idx and c.crop_code == code
        )
        allocations.append(
            {
                "field_id": model.field_ids[f_idx],
                "season_index": s_idx,
                "season_label": seasons[s_idx].label,
                "crop_code": code,
                "area_ha": round(units / AREA_SCALE, 2),
                "family_key": prepared.family_key,
                "status": ASSIGNED_STATUS,
                "demand_mm": prepared.demand_mm,
                "demand_basis": prepared.demand_basis,
            }
        )
    for (f_idx, s_idx), var in sorted(fallow.items()):
        units = solver.Value(var)
        if units <= 0:
            continue
        allocations.append(
            {
                "field_id": model.field_ids[f_idx],
                "season_index": s_idx,
                "season_label": seasons[s_idx].label,
                "crop_code": FALLOW_CROP_CODE,
                "area_ha": round(units / AREA_SCALE, 2),
                "family_key": None,
                "status": FALLOW_STATUS,
                "demand_mm": 0.0,
                "demand_basis": None,
            }
        )

    # ---- post-hoc reported evidence (never the steering objective) ----------
    from app.portfolio.evaluation import score_allocation

    per_criterion = score_allocation(model, allocations)

    binding, constraint_report = _constraint_report(
        model, solver, x, water_alloc_m3, family_cap_entries, allocations
    )
    diagnostics["constraint_report"] = constraint_report
    if model.mode == MODE_WEIGHTED and internal_objective is not None:
        objective_value = round(internal_objective / OBJECTIVE_SCALE, 6)
    else:
        objective_value = None

    if model.mode == MODE_LEXICOGRAPHIC:
        diagnostics["note"] = (
            "lexicographic mode: no composite score is computed; criteria are "
            "optimized in the disclosed priority order and reported separately"
        )

    return PortfolioSolution(
        status="optimal" if status_name == "optimal" else "feasible",
        allocations=allocations,
        objective_value=objective_value,
        per_criterion_scores=per_criterion,
        binding_constraints=binding,
        diagnostics=diagnostics,
        notes=list(model.notes),
    )


def _run_solves(
    cp: cp_model.CpModel,
    model: PreparedModel,
    registry: _AssumptionRegistry,
    stage_exprs: dict[str, Any],
) -> tuple[cp_model.CpSolver, str, float | None, list[dict[str, Any]] | None, int]:
    """Run the solve (single weighted objective, or one staged solve per
    criterion in lexicographic mode). Returns (solver, status_name, internal
    objective, stage values | None, total wall ms)."""
    registry.attach(cp)
    solver = cp_model.CpSolver()
    solver.parameters.num_search_workers = 1
    solver.parameters.random_seed = RANDOM_SEED
    solver.parameters.max_time_in_seconds = MAX_SOLVE_SECONDS

    wall_total = 0.0

    def _solve_once(objective_expr: Any | None) -> tuple[Any, str]:
        nonlocal wall_total
        if objective_expr is None:
            cp.ClearObjective()
        else:
            cp.Maximize(objective_expr)
        status = solver.Solve(cp)
        wall_total += solver.WallTime()
        name = solver.StatusName(status).lower()
        return status, name

    if model.mode == MODE_LEXICOGRAPHIC:
        stages: list[dict[str, Any]] = []
        stage_values: list[dict[str, Any]] = []
        for criterion in model.priority:
            expr = stage_exprs.get(criterion)
            if expr is None:
                stages.append({"criterion": criterion, "skipped": "criterion not evaluable"})
                continue
            status, name = _solve_once(expr)
            if name not in ("optimal", "feasible"):
                return solver, name, None, stages, int(wall_total * 1000)
            value = int(round(solver.ObjectiveValue()))
            stages.append({"criterion": criterion, "status": name, "value": value})
            stage_values.append({"criterion": criterion, "value": value})
            cp.Add(expr == value)
        if not stage_values:
            # no criterion evaluable → feasibility-only solve, disclosed
            status, name = _solve_once(None)
            if name not in ("optimal", "feasible"):
                return solver, name, None, stages, int(wall_total * 1000)
            stages.append({"criterion": None, "status": name, "value": 0})
        return solver, "optimal", None, stages, int(wall_total * 1000)

    # weighted mode
    if stage_exprs.get("__composite__") is None:
        status, name = _solve_once(None)
        if name not in ("optimal", "feasible"):
            return solver, name, None, None, int(wall_total * 1000)
        return solver, name, 0.0, None, int(wall_total * 1000)
    status, name = _solve_once(stage_exprs["__composite__"])
    if name not in ("optimal", "feasible"):
        return solver, name, None, None, int(wall_total * 1000)
    return solver, name, solver.ObjectiveValue(), None, int(wall_total * 1000)


def _criterion_expressions(
    cp: cp_model.CpModel, model: PreparedModel, x: dict[tuple[int, int, str], Any]
) -> dict[str, Any]:
    """Steering expressions, one per criterion (plus the weighted composite
    under '__composite__'). All criteria share one scale: a criterion at
    score 1.0 across the whole farm contributes OBJECTIVE_SCALE x weight —
    so the composite is a faithful weighted sum of the disclosed 0-1
    sub-scores (up to integer rounding). Criteria that cannot be scored from
    evidence are OMITTED and reported as skipped weights (never zero-filled).
    """
    total_scaled = model.total_scaled
    exprs: dict[str, Any] = {}
    shares = model.weight_shares

    direct_scores: dict[str, list[tuple[PreparedCrop, float]]] = {
        "water_efficiency": [],
        "soil_health": [],
        "operational_feasibility": [],
    }
    for crop in model.crops:
        for criterion, score in crop.scores.items():
            if criterion in direct_scores:
                direct_scores[criterion].append((crop, score))

    def _direct_expr(criterion: str, weight: float) -> Any | None:
        entries = direct_scores[criterion]
        if not entries or weight <= 0:
            return None
        terms = []
        for crop, score in entries:
            coeff = int(round(score * weight * OBJECTIVE_SCALE / total_scaled))
            if coeff:
                terms.append(x[(crop.field_idx, crop.season_idx, crop.crop_code)] * coeff)
        return sum(terms) if terms else None

    composite_terms: list[Any] = []
    skipped_weights: dict[str, str] = {}

    for criterion in OBJECTIVE_KEYS:
        weight = shares.get(criterion, 0.0)
        expr: Any | None = None
        if criterion in direct_scores:
            expr = _direct_expr(criterion, weight)
            if expr is None and weight > 0:
                skipped_weights[criterion] = (
                    "no candidate carries an evaluable score for this criterion"
                )
        elif criterion == "risk_diversification":
            expr = _risk_expression(cp, model, x, weight)
            if expr is None and weight > 0:
                skipped_weights[criterion] = "no admissible crop area to diversify"
        elif criterion == "rotation_diversity":
            expr = _diversity_expression(cp, model, x, weight)
            if expr is None and weight > 0:
                skipped_weights[criterion] = (
                    "no admissible crop area to diversify (nothing cultivated)"
                )
        elif criterion == "resource_utilization":
            expr = _resource_utilization_expression(cp, model, x, weight)
            if expr is None and weight > 0:
                skipped_weights[criterion] = (
                    "no shared water allocation supplied — water utilization is "
                    "not evaluable (absent constraints are never unlimited)"
                )
        if expr is not None:
            exprs[criterion] = expr
            composite_terms.append(expr)

    if model.mode == MODE_WEIGHTED:
        exprs["__composite__"] = sum(composite_terms) if composite_terms else None
    if skipped_weights:
        model.notes.append(
            "skipped steering weights (criterion not evaluable from evidence): "
            + ", ".join(f"{k} ({v})" for k, v in sorted(skipped_weights.items()))
        )
    return exprs


def _risk_expression(
    cp: cp_model.CpModel, model: PreparedModel, x: dict[tuple[int, int, str], Any], weight: float
) -> Any | None:
    """risk_diversification steering: minimize the maximum single-crop share
    across the farm (reported value: 1 - max_share). R >= total area of every
    crop; the term is -weight x R (normalized by total farm area)."""
    if weight <= 0 or not model.crops:
        return None
    total_scaled = model.total_scaled
    per_crop: dict[str, list[Any]] = {}
    for crop in model.crops:
        per_crop.setdefault(crop.crop_code, []).append(
            x[(crop.field_idx, crop.season_idx, crop.crop_code)]
        )
    r = cp.NewIntVar(0, total_scaled, "risk_max_crop_area")
    for code in sorted(per_crop):
        cp.Add(r >= sum(per_crop[code]))
    return -r * int(round(weight * OBJECTIVE_SCALE / total_scaled))


def _diversity_expression(
    cp: cp_model.CpModel, model: PreparedModel, x: dict[tuple[int, int, str], Any], weight: float
) -> Any | None:
    """rotation_diversity steering (two equally-weighted sub-terms, disclosed):
    (a) per field, per consecutive season pair: minimize the max single-family
    area within the pair (penalizes the same family dominating consecutive
    seasons on one field); (b) minimize the max single-family area across the
    farm and seasons (family concentration). The REPORTED criterion is
    recomputed exactly post hoc in the evaluation layer."""
    if weight <= 0 or not model.crops:
        return None
    total_scaled = model.total_scaled
    terms: list[Any] = []
    seasons = model.seasons
    pair_weight = weight * (0.5 if len(seasons) >= 2 else 0.0)
    concentration_weight = weight * (0.5 if len(seasons) >= 2 else 1.0)

    if pair_weight > 0:
        by_fs_family: dict[tuple[int, int, str], list[Any]] = {}
        for crop in model.crops:
            key = (crop.field_idx, crop.season_idx, model.family_of(crop.crop_code))
            by_fs_family.setdefault(key, []).append(
                x[(crop.field_idx, crop.season_idx, crop.crop_code)]
            )
        for f_idx in range(len(model.fields)):
            area_scaled = model.area_scaled(f_idx)
            for s_idx in range(len(seasons) - 1):
                families = sorted(
                    {
                        key[2]
                        for key in by_fs_family
                        if key[0] == f_idx and key[1] in (s_idx, s_idx + 1)
                    }
                )
                if not families:
                    continue
                m = cp.NewIntVar(0, area_scaled, f"div_max_f{f_idx}_p{s_idx}")
                for family in families:
                    season_terms = []
                    for s2 in (s_idx, s_idx + 1):
                        season_terms.extend(by_fs_family.get((f_idx, s2, family), []))
                    if season_terms:
                        cp.Add(m >= sum(season_terms))
                terms.append(
                    -m * int(round(pair_weight * OBJECTIVE_SCALE / area_scaled))
                )

    if concentration_weight > 0:
        per_family: dict[str, list[Any]] = {}
        for crop in model.crops:
            per_family.setdefault(model.family_of(crop.crop_code), []).append(
                x[(crop.field_idx, crop.season_idx, crop.crop_code)]
            )
        m2 = cp.NewIntVar(0, total_scaled, "div_max_family_farm")
        for family in sorted(per_family):
            cp.Add(m2 >= sum(per_family[family]))
        terms.append(
            -m2 * int(round(concentration_weight * OBJECTIVE_SCALE / total_scaled))
        )

    return sum(terms) if terms else None


def _resource_utilization_expression(
    cp: cp_model.CpModel, model: PreparedModel, x: dict[tuple[int, int, str], Any], weight: float
) -> Any | None:
    """resource_utilization steering: linear-ramp bonus on water use up to
    RESOURCE_UTILIZATION_TARGET x allocation (disclosed shape; the allocation
    itself is hard, so breach is impossible). P <= water use, P <= target;
    maximizing weight x P/target yields the exact piecewise-linear score."""
    alloc_m3 = _effective_water_allocation(model)
    if weight <= 0 or alloc_m3 is None or alloc_m3 <= 0:
        return None
    water_terms = [
        x[(c.field_idx, c.season_idx, c.crop_code)] * c.coeff_l
        for c in model.crops
        if c.coeff_l is not None
    ]
    if not water_terms:
        return None
    target_l = int(round(RESOURCE_UTILIZATION_TARGET * alloc_m3 * 1000.0))
    if target_l <= 0:
        return None
    p = cp.NewIntVar(0, target_l, "resource_util_bonus")
    cp.Add(p <= sum(water_terms))
    return p * int(round(weight * OBJECTIVE_SCALE / target_l))


def _constraint_report(
    model: PreparedModel,
    solver: cp_model.CpSolver,
    x: dict[tuple[int, int, str], Any],
    water_alloc_m3: float | None,
    family_cap_entries: list[dict[str, Any]],
    allocations: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Post-hoc constraint accounting: used / limit / slack per active shared
    constraint (exact integer arithmetic, then converted to display units).
    `binding_constraints` carries the entries with zero slack; the full report
    lands in diagnostics."""
    report: list[dict[str, Any]] = []

    if water_alloc_m3 is not None:
        used_l = 0
        unknown_area_units = 0
        for crop in model.crops:
            value = solver.Value(x[(crop.field_idx, crop.season_idx, crop.crop_code)])
            if crop.coeff_l is not None:
                used_l += value * crop.coeff_l
            else:
                unknown_area_units += value
        limit_l = int(round(water_alloc_m3 * 1000.0))
        entry = {
            "name": "water_allocation",
            "limit": round(limit_l / 1000.0, 3),
            "used": round(used_l / 1000.0, 3),
            "slack": round((limit_l - used_l) / 1000.0, 3),
            "binding": used_l == limit_l,
            "unit": "m3",
        }
        if unknown_area_units > 0:
            entry["used_is_lower_bound"] = True
            entry["note"] = (
                f"{unknown_area_units / AREA_SCALE:.2f} ha of cultivated area have "
                "no water-demand estimate; 'used' is a lower bound"
            )
        report.append(entry)

    for entry_spec in family_cap_entries:
        family_terms = [
            x[(c.field_idx, c.season_idx, c.crop_code)]
            for c in model.crops
            if c.season_idx == _season_index_of(model, entry_spec["season_label"])
            and model.family_of(c.crop_code) == entry_spec["family_key"]
        ]
        used = sum(solver.Value(t) for t in family_terms)
        cap = entry_spec["cap_scaled"]
        report.append(
            {
                "name": "family_share_cap",
                "season_label": entry_spec["season_label"],
                "family_key": entry_spec["family_key"],
                "limit": round(cap / AREA_SCALE, 2),
                "used": round(used / AREA_SCALE, 2),
                "slack": round((cap - used) / AREA_SCALE, 2),
                "binding": used == cap,
                "unit": "ha",
            }
        )

    binding = [e for e in report if e.get("binding")]
    return binding, report


def _season_index_of(model: PreparedModel, label: str) -> int:
    for idx, season in enumerate(model.seasons):
        if season.label == label:
            return idx
    return -1
