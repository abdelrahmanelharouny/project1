"""Pure regressions for season-aware rotation scoring and crop maturity dates."""

from dataclasses import replace
from datetime import date

from test_rotation_core import (
    SUMMER,
    _crop,
    _evidence,
    _farm,
    _knowledge,
    _problem,
    _rule,
    _window,
)
from app.rotation.problem import CandidateAssessment, SeasonSpec


SECOND = SeasonSpec(
    label="s2026", start_date=date(2026, 5, 1), end_date=date(2026, 9, 15)
)


def _crossing_crops():
    return [
        _crop(
            "barley", "poaceae", duration=120,
            windows=[_window("05-01", "06-01")], kc=(0.3, 1.0, 0.25),
            temp_opt=(15, 20),
        ),
        _crop(
            "wheat", "poaceae", duration=120,
            windows=[_window("05-01", "06-01")], kc=(0.5, 1.3, 0.6),
            temp_opt=(22, 30),
        ),
    ]


def _crossing_problem():
    seasons = (SUMMER, SECOND)
    farm = _farm(
        seasons=list(seasons),
        climate={
            SUMMER.label: _evidence(season_mean_temp_degC=18.0),
            SECOND.label: _evidence(season_mean_temp_degC=25.0),
        },
    )
    return _problem(_crossing_crops(), seasons=seasons, farm=farm)


def test_water_and_temperature_rankings_are_keyed_and_normalized_per_season():
    problem = _crossing_problem()
    for label, values in {
        SUMMER.label: {"barley": 10.0, "wheat": 60.0},
        SECOND.label: {"barley": 90.0, "wheat": 20.0},
    }.items():
        for crop_code, amount in values.items():
            original = problem.candidates[label][crop_code]
            problem.candidates[label][crop_code] = replace(
                original, water_requirement_mm=amount
            )

    from app.rotation.optimizer import (
        PROFILE_WEIGHTS,
        _per_season_scores,
        optimize_strategy,
    )

    pools = {SUMMER.label: ["barley", "wheat"], SECOND.label: ["barley", "wheat"]}
    scores, skipped = _per_season_scores(problem, pools)
    water = scores["water_requirement_mm"]
    resilience = scores["climate_resilience_index"]
    assert water[(SUMMER.label, "barley")] > water[(SUMMER.label, "wheat")]
    assert water[(SECOND.label, "wheat")] > water[(SECOND.label, "barley")]
    assert resilience[(SUMMER.label, "barley")] > resilience[(SUMMER.label, "wheat")]
    assert resilience[(SECOND.label, "wheat")] > resilience[(SECOND.label, "barley")]
    assert not any(key.endswith(f"@{SUMMER.label}") for key in skipped)
    assert not any(key.endswith(f"@{SECOND.label}") for key in skipped)

    water_profile = {key: 0.0 for key in PROFILE_WEIGHTS["water_priority"]}
    water_profile["water_requirement_mm"] = 1.0
    water_solution = optimize_strategy(problem, "water_only", water_profile)
    assert dict(water_solution.assignment) == {
        SUMMER.label: "barley",
        SECOND.label: "wheat",
    }

    temperature_profile = {key: 0.0 for key in PROFILE_WEIGHTS["water_priority"]}
    temperature_profile["climate_resilience_index"] = 1.0
    temperature_solution = optimize_strategy(problem, "temperature_only", temperature_profile)
    assert dict(temperature_solution.assignment) == {
        SUMMER.label: "barley",
        SECOND.label: "wheat",
    }


def test_each_seasons_normalization_uses_only_its_admissible_pool():
    problem = _crossing_problem()
    problem.candidates[SUMMER.label]["barley"] = replace(
        problem.candidates[SUMMER.label]["barley"], water_requirement_mm=10.0
    )
    problem.candidates[SUMMER.label]["wheat"] = replace(
        problem.candidates[SUMMER.label]["wheat"], water_requirement_mm=80.0
    )
    problem.candidates[SECOND.label]["barley"] = CandidateAssessment(
        crop_code="barley", status="excluded", water_requirement_mm=0.0
    )
    problem.candidates[SECOND.label]["wheat"] = replace(
        problem.candidates[SECOND.label]["wheat"], water_requirement_mm=70.0
    )

    from app.rotation.optimizer import _per_season_scores

    scores, _skipped = _per_season_scores(
        problem,
        {SUMMER.label: ["barley", "wheat"], SECOND.label: ["wheat"]},
    )
    water = scores["water_requirement_mm"]
    assert water[(SUMMER.label, "barley")] == 1.0
    assert water[(SUMMER.label, "wheat")] == 0.0
    # A singleton admissible pool has no relative separation and is neutral.
    assert water[(SECOND.label, "wheat")] == 0.5
    assert (SECOND.label, "barley") not in water


def test_incomplete_season_evidence_is_uniformly_omitted_and_disclosed():
    problem = _crossing_problem()
    problem.candidates[SUMMER.label]["barley"] = replace(
        problem.candidates[SUMMER.label]["barley"], water_requirement_mm=10.0
    )
    problem.candidates[SUMMER.label]["wheat"] = replace(
        problem.candidates[SUMMER.label]["wheat"], water_requirement_mm=60.0
    )
    problem.candidates[SECOND.label]["barley"] = replace(
        problem.candidates[SECOND.label]["barley"], water_requirement_mm=90.0
    )
    problem.candidates[SECOND.label]["wheat"] = replace(
        problem.candidates[SECOND.label]["wheat"], water_requirement_mm=None, reasons=()
    )

    from app.rotation.optimizer import _per_season_scores

    scores, skipped = _per_season_scores(
        problem,
        {SUMMER.label: ["barley", "wheat"], SECOND.label: ["barley", "wheat"]},
    )
    water = scores["water_requirement_mm"]
    assert (SUMMER.label, "barley") in water
    assert (SUMMER.label, "wheat") in water
    assert (SECOND.label, "barley") not in water
    assert (SECOND.label, "wheat") not in water
    assert "water_requirement_mm@s2026" in skipped
    assert "uniformly omitted" in skipped["water_requirement_mm@s2026"]
    assert "wheat" in skipped["water_requirement_mm@s2026"]

    temperature = scores["climate_resilience_index"]
    assert (SECOND.label, "barley") not in temperature
    assert (SECOND.label, "wheat") not in temperature
    assert "climate_resilience_index@s2026" in skipped
    assert "uniformly omitted" in skipped["climate_resilience_index@s2026"]


def test_per_season_omission_survives_weighted_objective_reporting():
    problem = _crossing_problem()
    for crop_code, amount in {"barley": 10.0, "wheat": 60.0}.items():
        problem.candidates[SUMMER.label][crop_code] = replace(
            problem.candidates[SUMMER.label][crop_code], water_requirement_mm=amount
        )
    problem.candidates[SECOND.label]["barley"] = replace(
        problem.candidates[SECOND.label]["barley"], water_requirement_mm=90.0
    )
    problem.candidates[SECOND.label]["wheat"] = replace(
        problem.candidates[SECOND.label]["wheat"], water_requirement_mm=None
    )

    from app.rotation.objectives import evaluate_criteria, weighted_objective
    from app.rotation.optimizer import PROFILE_WEIGHTS, optimize_strategy

    profile = {key: 0.0 for key in PROFILE_WEIGHTS["water_priority"]}
    profile["water_requirement_mm"] = 1.0
    solution = optimize_strategy(problem, "water_only", profile)
    omission_key = f"water_requirement_mm@{SECOND.label}"
    assert omission_key in solution.skipped_weights
    assert "uniformly omitted" in solution.skipped_weights[omission_key]

    solution.criteria = evaluate_criteria(problem, dict(solution.assignment))
    _objective, _effective, skipped = weighted_objective(solution)
    assert omission_key in skipped
    assert skipped[omission_key] == solution.skipped_weights[omission_key]


def test_missing_temperature_is_excluded_from_resilience_denominator():
    problem = _crossing_problem()
    problem.candidates[SECOND.label]["barley"] = replace(
        problem.candidates[SECOND.label]["barley"], reasons=()
    )

    from app.rotation.objectives import criterion_resilience

    result = criterion_resilience(
        problem, {SUMMER.label: "barley", SECOND.label: "barley"}
    )
    assert result.evaluable
    assert result.raw_value == 1.0
    assert result.missing_evidence == (
        f"{SECOND.label}: temperature not evaluated for 'barley'",
    )
    assert "not a crop-yield forecast" in result.derivation


def test_late_planting_window_checks_actual_maturity_date():
    crops = [
        _crop(
            "late_matures_in_season", duration=42,
            windows=[_window("08-15", "08-31")],
        ),
        _crop(
            "late_matures_too_late", duration=60,
            windows=[_window("08-15", "08-31")],
        ),
    ]
    from app.rotation.candidates import generate_candidates

    assessments = generate_candidates(_knowledge(crops), _farm())[SUMMER.label]
    feasible = assessments["late_matures_in_season"]
    assert feasible.status == "conditionally_eligible"
    spill = next(reason for reason in feasible.reasons if reason["code"] == "duration_spills")
    assert "2025-08-15" in spill["message"]
    assert "2025-09-25" in spill["message"]

    infeasible = assessments["late_matures_too_late"]
    assert infeasible.status == "excluded"
    too_late = next(
        reason for reason in infeasible.reasons
        if reason["code"] == "duration_exceeds_season"
    )
    assert "2025-10-13" in too_late["message"]
    assert "beyond" in too_late["message"]


def test_per_season_soft_scores_do_not_relax_confirmed_hard_constraints():
    crops = _crossing_crops()
    seasons = (SUMMER, SECOND)
    problem = _problem(
        crops,
        rules=[_rule("r_barley_repeat", "barley", "barley", status="confirmed_regional")],
        seasons=seasons,
    )
    from app.rotation.optimizer import PROFILE_WEIGHTS, optimize_strategy

    profile = {key: 0.0 for key in PROFILE_WEIGHTS["water_priority"]}
    profile["water_requirement_mm"] = 1.0
    solution = optimize_strategy(problem, "water_only", profile)
    assignment = dict(solution.assignment)
    assert not (assignment[SUMMER.label] == "barley" and assignment[SECOND.label] == "barley")
