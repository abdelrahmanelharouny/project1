"""Multi-objective evaluation (Milestone 5.5, ADR-0018).

Criteria are evaluated on the FINAL assignment with raw values, documented
derivations, evidence citations and honest missing-evidence lists.
Normalization is min-max WITHIN the generated strategy set of one run (and
only across solutions whose evaluable criterion sets intersect). Evidence
coverage — the fraction of criteria evaluable from evidence — is a
transparency metric, NOT a confidence score.
"""

from __future__ import annotations

from typing import Any

from app.rotation.problem import (
    CriterionResult,
    FarmContext,
    KnowledgeBaseData,
    KnowledgeCrop,
    RotationProblem,
    StrategySolution,
)


def _source_ref(
    crop: KnowledgeCrop, trait_code: str, country_code: str | None = None
) -> dict[str, Any] | None:
    t = crop.resolve_trait(trait_code, country_code)
    if t is None:
        return None
    return {
        "type": "knowledge_trait",
        "crop_code": crop.crop_code,
        "trait_code": trait_code,
        "pack_code": t.pack_code,
        "pack_version": t.pack_version,
        "source_key": t.source_key,
        "citation_text": t.citation_text,
        "evidence_class": t.evidence_class,
        "confidence": t.confidence,
    }


def _assigned(problem: RotationProblem, assignment: dict[str, str | None]):
    for season in problem.seasons:
        yield season, assignment.get(season.label)


def _refs_for_traits(
    problem: RotationProblem, assignment: dict[str, str | None], trait_code: str
) -> tuple[dict[str, Any], ...]:
    """Deepening F-10: per-criterion evidence citations collected from the
    assigned crops' knowledge traits (deduplicated by pack+source)."""
    refs: dict[tuple[str, str], dict[str, Any]] = {}
    for _season, crop_code in _assigned(problem, assignment):
        crop = problem.knowledge.crops.get(crop_code or "")
        if crop is None:
            continue
        ref = _source_ref(crop, trait_code, problem.farm.country_code)
        if ref is not None:
            refs[(ref["pack_version"], ref["source_key"])] = ref
    return tuple(refs.values())


def criterion_water(
    problem: RotationProblem, assignment: dict[str, str | None]
) -> CriterionResult:
    values: list[float] = []
    missing: list[str] = []
    for season, crop_code in _assigned(problem, assignment):
        if crop_code is None:
            continue
        assessment = problem.candidates.get(season.label, {}).get(crop_code)
        if assessment is None or assessment.water_requirement_mm is None:
            missing.append(f"{season.label}: no water estimate for '{crop_code}'")
        else:
            values.append(assessment.water_requirement_mm)
    if missing or not values:
        return CriterionResult(
            criterion_code="water_requirement_mm",
            raw_value=None,
            unit="mm/season",
            direction="minimize",
            normalized=None,
            evaluable=False,
            missing_evidence=tuple(missing) or ("no seasons assigned",),
            derivation="FAO-56 single-Kc screening ETc (ADR-0017); lower is better.",
        )
    return CriterionResult(
        criterion_code="water_requirement_mm",
        raw_value=round(sum(values) / len(values), 2),
        unit="mm/season",
        direction="minimize",
        normalized=None,
        evaluable=True,
        derivation="Mean per-season FAO-56 single-Kc screening ETc over the planning "
        "seasons (ADR-0017); lower is better.",
        source_refs=_refs_for_traits(problem, assignment, "stage_mid_days"),
    )


def criterion_soil_health(
    problem: RotationProblem, assignment: dict[str, str | None]
) -> CriterionResult:
    scores: list[float] = []
    missing: list[str] = []
    sub_specs = [
        ("root_depth", lambda c, country: _bounded(c.numeric_trait("root_depth_effective_m", country), 0.3, 1.8),
         "trait root_depth_effective_m (FAO-56 Table 22)"),
        ("n_fixation_capacity", lambda c, country: _bounded(c.numeric_trait("n_fixation_capacity_kg_ha", country), 0, 200),
         "trait n_fixation_capacity_kg_ha (Herridge et al. 2008)"),
    ]
    for season, crop_code in _assigned(problem, assignment):
        if crop_code is None:
            continue
        crop = problem.knowledge.crops.get(crop_code)
        if crop is None:
            missing.append(f"{season.label}: '{crop_code}' not in knowledge base")
            continue
        per_crop: list[float] = []
        missing_sub: list[str] = []
        for name, fn, _desc in sub_specs:
            v = fn(crop, problem.farm.country_code)
            if v is None:
                missing_sub.append(name)
            else:
                per_crop.append(v)
        if per_crop:
            scores.append(sum(per_crop) / len(per_crop))
        if missing_sub:
            missing.append(
                f"{season.label} '{crop_code}': sub-indicators absent — "
                + ", ".join(missing_sub)
            )
    if not scores:
        return CriterionResult(
            criterion_code="soil_health_index",
            raw_value=None,
            unit="index 0..1",
            direction="maximize",
            normalized=None,
            evaluable=False,
            missing_evidence=tuple(missing) or ("no seasons assigned",),
            derivation="Mean of sourced numeric soil-health indicators (root depth "
            "and N-fixation capacity); missing indicators are not zero-filled.",
        )
    return CriterionResult(
        criterion_code="soil_health_index",
        raw_value=round(sum(scores) / len(scores), 4),
        unit="index 0..1",
        direction="maximize",
        normalized=None,
        evaluable=True,
        missing_evidence=tuple(missing),
        derivation="Mean of sourced numeric soil-health indicators per season "
        "(root depth and N-fixation capacity).",
        source_refs=(
            _refs_for_traits(problem, assignment, "root_depth_effective_m")
            + _refs_for_traits(problem, assignment, "n_fixation_capacity_kg_ha")
        ),
    )


def _bounded(v: float | None, lo: float, hi: float) -> float | None:
    if v is None:
        return None
    return max(0.0, min(1.0, (v - lo) / (hi - lo)))


def criterion_margin(
    problem: RotationProblem, assignment: dict[str, str | None]
) -> CriterionResult:
    values: list[float] = []
    missing: list[str] = []
    for season, crop_code in _assigned(problem, assignment):
        if crop_code is None:
            continue
        if crop_code in problem.farm.margin_index_by_crop:
            values.append(problem.farm.margin_index_by_crop[crop_code])
        else:
            missing.append(
                f"{season.label}: no farmer-supplied margin index for '{crop_code}' "
                "(economics is never invented)"
            )
    if not values:
        return CriterionResult(
            criterion_code="economic_margin_index",
            raw_value=None,
            unit="farmer index 0..100",
            direction="maximize",
            normalized=None,
            evaluable=False,
            missing_evidence=tuple(missing) or ("no farmer-supplied margins",),
            derivation="Farmer-supplied relative margin index (0..100). The platform "
            "does NOT estimate prices or yields.",
        )
    return CriterionResult(
        criterion_code="economic_margin_index",
        raw_value=round(sum(values) / len(values), 2),
        unit="farmer index 0..100",
        direction="maximize",
        normalized=None,
        evaluable=True,
        missing_evidence=tuple(missing),
        derivation="Mean farmer-supplied relative margin index across seasons.",
    )


def criterion_diversity(
    problem: RotationProblem, assignment: dict[str, str | None]
) -> CriterionResult:
    crops = [
        problem.knowledge.crops.get(c)
        for _, c in _assigned(problem, assignment)
        if c is not None
    ]
    crops = [c for c in crops if c is not None]
    if len(crops) != len(problem.seasons):
        missing = [
            f"{s.label}: no assigned crop" for s, c in _assigned(problem, assignment) if c is None
        ]
        return CriterionResult(
            criterion_code="crop_family_diversity",
            raw_value=None,
            unit="distinct families / seasons",
            direction="maximize",
            normalized=None,
            evaluable=False,
            missing_evidence=tuple(missing),
            derivation="Distinct botanical families across the planning seasons divided "
            "by the number of seasons.",
        )
    families = [c.family_key or f"__unclassified__:{c.crop_code}" for c in crops]
    value = len(set(families)) / len(families)
    return CriterionResult(
        criterion_code="crop_family_diversity",
        raw_value=round(value, 4),
        unit="distinct families / seasons",
        direction="maximize",
        normalized=None,
        evaluable=True,
        derivation="Distinct botanical families across seasons / seasons; crops without "
        "a family assignment count as their own category.",
    )


def criterion_resilience(
    problem: RotationProblem, assignment: dict[str, str | None]
) -> CriterionResult:
    """Fraction of seasons whose temperature evidence fell WITHIN the crop's
    sourced optimum (evaluated during candidate generation). Seasons without
    temperature evaluation are listed as missing, never zero."""
    good = 0
    missing: list[str] = []
    total = 0
    for season, crop_code in _assigned(problem, assignment):
        if crop_code is None:
            continue
        total += 1
        assessment = problem.candidates.get(season.label, {}).get(crop_code)
        if assessment is None:
            missing.append(f"{season.label}: unevaluated candidate '{crop_code}'")
            continue
        codes = {r["code"] for r in assessment.reasons}
        if "temperature_within_optimum" in codes:
            good += 1
        elif any(c.startswith("temperature_") for c in codes):
            pass  # evaluated but outside optimum → contributes 0
        else:
            missing.append(f"{season.label}: temperature not evaluated for '{crop_code}'")
    if not total or (good == 0 and missing):
        return CriterionResult(
            criterion_code="climate_resilience_index",
            raw_value=None,
            unit="fraction 0..1",
            direction="maximize",
            normalized=None,
            evaluable=False,
            missing_evidence=tuple(missing) or ("no seasons assigned",),
            derivation="Fraction of seasons with temperature evidence inside the crop's "
            "sourced optimum range (candidate-generation outcome).",
        )
    return CriterionResult(
        criterion_code="climate_resilience_index",
        raw_value=round(good / total, 4),
        unit="fraction 0..1",
        direction="maximize",
        normalized=None,
        evaluable=True,
        missing_evidence=tuple(missing),
        derivation="Fraction of seasons with temperature evidence inside the crop's "
        "sourced optimum range (candidate-generation outcome).",
        source_refs=_refs_for_traits(problem, assignment, "temp_opt_min_degC"),
    )


def criterion_erosion(
    problem: RotationProblem, assignment: dict[str, str | None]
) -> CriterionResult:
    """Soil-cover proxy: mean fraction of each season covered by the crop's
    duration (longer-lived crops keep soil covered longer)."""
    values: list[float] = []
    missing: list[str] = []
    for season, crop_code in _assigned(problem, assignment):
        if crop_code is None:
            continue
        crop = problem.knowledge.crops.get(crop_code)
        duration = (
            crop.numeric_trait("duration_days_total", problem.farm.country_code)
            if crop
            else None
        )
        if duration is None:
            missing.append(f"{season.label}: duration unknown for '{crop_code}'")
        else:
            values.append(min(1.0, duration / season.length_days))
    if not values:
        return CriterionResult(
            criterion_code="erosion_reduction_index",
            raw_value=None,
            unit="fraction 0..1",
            direction="maximize",
            normalized=None,
            evaluable=False,
            missing_evidence=tuple(missing) or ("no seasons assigned",),
            derivation="Soil-cover PROXY: crop duration / season length (a living-cover "
            "proxy only; residue management data is not yet ingested).",
        )
    return CriterionResult(
        criterion_code="erosion_reduction_index",
        raw_value=round(sum(values) / len(values), 4),
        unit="fraction 0..1",
        direction="maximize",
        normalized=None,
        evaluable=True,
        missing_evidence=tuple(missing),
        derivation="Soil-cover PROXY: mean crop-duration coverage of the season "
        "(a living-cover proxy; residue management data not yet ingested).",
        source_refs=_refs_for_traits(problem, assignment, "duration_days_total"),
    )


def criterion_cover_opportunity(
    problem: RotationProblem, assignment: dict[str, str | None]
) -> CriterionResult:
    total = len(problem.seasons)
    if total == 0:
        return CriterionResult(
            criterion_code="cover_crop_opportunity",
            raw_value=None,
            unit="fraction 0..1",
            direction="maximize",
            normalized=None,
            evaluable=False,
            missing_evidence=("no planning seasons",),
            derivation="Fraction of seasons whose assigned crop is legume or "
            "cover-crop capable (green-manure potential).",
        )
    good = 0
    missing: list[str] = []
    for season, crop_code in _assigned(problem, assignment):
        if crop_code is None:
            missing.append(f"{season.label}: no assigned crop")
            continue
        crop = problem.knowledge.crops.get(crop_code)
        if crop is None:
            missing.append(f"{season.label}: '{crop_code}' not in knowledge base")
            continue
        if crop.is_legume or crop.is_cover_crop_capable:
            good += 1
    return CriterionResult(
        criterion_code="cover_crop_opportunity",
        raw_value=round(good / total, 4),
        unit="fraction 0..1",
        direction="maximize",
        evaluable=True,
        normalized=None,
        missing_evidence=tuple(missing),
        derivation="Fraction of seasons whose assigned crop is a legume or "
        "cover-crop capable (green-manure potential).",
    )


CRITERION_FUNCS = {
    "water_requirement_mm": criterion_water,
    "soil_health_index": criterion_soil_health,
    "economic_margin_index": criterion_margin,
    "crop_family_diversity": criterion_diversity,
    "climate_resilience_index": criterion_resilience,
    "erosion_reduction_index": criterion_erosion,
    "cover_crop_opportunity": criterion_cover_opportunity,
}

CRITERION_UNITS = {
    "water_requirement_mm": "mm/season",
    "soil_health_index": "index 0..1",
    "economic_margin_index": "farmer index 0..100",
    "crop_family_diversity": "distinct families / seasons",
    "climate_resilience_index": "fraction 0..1",
    "erosion_reduction_index": "fraction 0..1",
    "cover_crop_opportunity": "fraction 0..1",
}

CRITERION_DIRECTIONS = {
    "water_requirement_mm": "minimize",
    "soil_health_index": "maximize",
    "economic_margin_index": "maximize",
    "crop_family_diversity": "maximize",
    "climate_resilience_index": "maximize",
    "erosion_reduction_index": "maximize",
    "cover_crop_opportunity": "maximize",
}


def evaluate_criteria(
    problem: RotationProblem, assignment: dict[str, str | None]
) -> tuple[CriterionResult, ...]:
    return tuple(fn(problem, assignment) for fn in CRITERION_FUNCS.values())


def normalize_within_set(
    solutions: list[StrategySolution],
) -> None:
    """Min-max normalize each criterion WITHIN the generated strategy set.

    Mutates the criteria tuples' normalized fields via reconstructed tuples.
    Solutions with different evaluable sets are normalized per-criterion over
    the solutions where that criterion is evaluable (restriction recorded in
    the pareto block by the caller)."""
    if not solutions:
        return
    for code in CRITERION_FUNCS:
        raw_by_solution: dict[int, float] = {}
        for i, sol in enumerate(solutions):
            for crit in sol.criteria:
                if crit.criterion_code == code and crit.evaluable and crit.raw_value is not None:
                    raw_by_solution[i] = crit.raw_value
                    break
        if len(raw_by_solution) < 2:
            normalized = 0.5  # single/zero evaluable value → neutral, documented
            values: dict[int, float] = {i: normalized for i in raw_by_solution}
        else:
            lo = min(raw_by_solution.values())
            hi = max(raw_by_solution.values())
            span = hi - lo
            if span <= 1e-12:
                values = {i: 0.5 for i in raw_by_solution}  # identical raw values → neutral
            else:
                values = {i: (v - lo) / span for i, v in raw_by_solution.items()}
        out: list[StrategySolution] = []
        for i, sol in enumerate(solutions):
            new_criteria = []
            for crit in sol.criteria:
                if crit.criterion_code == code:
                    new_criteria.append(
                        CriterionResult(
                            criterion_code=crit.criterion_code,
                            raw_value=crit.raw_value,
                            unit=crit.unit,
                            direction=crit.direction,
                            normalized=round(values[i], 4) if i in values else None,
                            evaluable=crit.evaluable,
                            missing_evidence=crit.missing_evidence,
                            derivation=crit.derivation,
                            source_refs=crit.source_refs,
                        )
                        if crit.evaluable
                        else crit
                    )
                else:
                    new_criteria.append(crit)
            out.append(
                StrategySolution(
                    strategy_key=sol.strategy_key,
                    strategy_kind=sol.strategy_kind,
                    is_baseline=sol.is_baseline,
                    profile_weights=sol.profile_weights,
                    weights_effective=sol.weights_effective,
                    skipped_weights=sol.skipped_weights,
                    assignment=sol.assignment,
                    objective_value=sol.objective_value,
                    criteria=tuple(new_criteria),
                    constraints_checked=sol.constraints_checked,
                    evidence_coverage=sol.evidence_coverage,
                    solver_status=sol.solver_status,
                    solver_wall_time_ms=sol.solver_wall_time_ms,
                    dominated_by=sol.dominated_by,
                    dominates=sol.dominates,
                    on_pareto_front=sol.on_pareto_front,
                    checksum_sha256=sol.checksum_sha256,
                )
            )
        solutions[:] = out


def weighted_objective(solution: StrategySolution) -> tuple[float | None, dict[str, float], dict[str, str]]:
    """Weighted sum of normalized scores. Weights renormalized over EVALUABLE
    criteria; skipped weights are reported with reasons (never silently dropped)."""
    weights = solution.profile_weights
    evaluable = {c.criterion_code: c for c in solution.criteria if c.evaluable and c.normalized is not None}
    skipped: dict[str, str] = {}
    total_w = 0.0
    effective: dict[str, float] = {}
    for code, w in weights.items():
        if w <= 0:
            skipped[code] = "weight is zero"
            continue
        crit = evaluable.get(code)
        if crit is None:
            missing = next(
                (c for c in solution.criteria if c.criterion_code == code), None
            )
            reason = "criterion not evaluable from available evidence"
            if missing is not None and missing.missing_evidence:
                reason += f": {missing.missing_evidence[0]}"
            skipped[code] = reason
            continue
        effective[code] = w
        total_w += w
    if total_w <= 0 or not effective:
        return None, effective, skipped
    objective = sum(
        weights[code] / total_w * evaluable[code].normalized for code in effective
    )
    return round(objective, 6), effective, skipped


def compute_pareto(solutions: list[StrategySolution]) -> None:
    """Pareto dominance over the SHARED evaluable criterion set of each pair.

    Solutions with disjoint evaluable sets are mutually non-comparable — that
    restriction is recorded rather than hidden."""
    for sol in solutions:
        sol.dominated_by = ()
        sol.dominates = ()
        sol.on_pareto_front = False

    def evaluable_map(sol: StrategySolution) -> dict[str, float]:
        return {
            c.criterion_code: (
                c.normalized if c.normalized is not None else 0.0
            )
            for c in sol.criteria
            if c.evaluable
        }

    maps = {sol.strategy_key: evaluable_map(sol) for sol in solutions}
    for a in solutions:
        for b in solutions:
            if a.strategy_key == b.strategy_key:
                continue
            shared = set(maps[a.strategy_key]) & set(maps[b.strategy_key])
            if not shared:
                continue  # non-comparable — recorded, not hidden
            direction = CRITERION_DIRECTIONS

            def better_or_equal(x: dict[str, float], y: dict[str, float]) -> bool:
                for code in shared:
                    if direction[code] == "maximize":
                        if x[code] < y[code] - 1e-9:
                            return False
                    else:
                        if x[code] > y[code] + 1e-9:
                            return False
                return True

            def strictly_better(x: dict[str, float], y: dict[str, float]) -> bool:
                for code in shared:
                    if direction[code] == "maximize":
                        if x[code] > y[code] + 1e-9:
                            return True
                    else:
                        if x[code] < y[code] - 1e-9:
                            return True
                return False

            if better_or_equal(
                maps[b.strategy_key], maps[a.strategy_key]
            ) and strictly_better(maps[b.strategy_key], maps[a.strategy_key]):
                a.dominated_by = tuple(sorted(set(a.dominated_by) | {b.strategy_key}))
    for sol in solutions:
        sol.on_pareto_front = not sol.dominated_by
    for sol in solutions:
        if sol.on_pareto_front:
            sol.dominates = tuple(
                sorted(
                    other.strategy_key
                    for other in solutions
                    if other.strategy_key != sol.strategy_key
                    and not other.on_pareto_front
                    and sol.strategy_key in other.dominated_by
                )
            )


def evidence_coverage_of(solution: StrategySolution) -> float | None:
    if not solution.criteria:
        return None
    evaluable = sum(1 for c in solution.criteria if c.evaluable)
    return round(evaluable / len(solution.criteria), 4)
