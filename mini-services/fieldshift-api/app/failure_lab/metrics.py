"""Robustness metrics for the Rotation Failure Lab (P2.D) — pure math.

Every metric is computed across stress packs for ONE candidate rotation on
the SAME normalization basis (the min-max normalized criterion scores within
the candidate×pack matrix, ADR-0018 machinery reused). Each metric is
returned as a first-class document:

    {"name": ..., "value": ..., "unit": ..., "formula_text": ...}

so no number ever appears without its definition. `value` is `None` (with a
`reason`) when the metric is not evaluable — missing evidence is never
treated as zero.

There is deliberately NO composite "resilience score": the only scalar that
feeds these metrics is `normalized_score` — the equal-weight mean of the
EVALUABLE normalized criterion values of one cell. It never mixes raw units
(normalized values are dimensionless 0..1) and never combines an evaluable
criterion with an unevaluable one.
"""

from __future__ import annotations

from typing import Any

ROBUSTNESS_METRICS_VERSION = "stress-metrics-1.0.0"

SCORE_UNIT = "normalized score 0..1"
RATE_UNIT = "fraction 0..1"

NORMALIZED_SCORE_FORMULA = (
    "normalized_score = mean of the evaluable normalized criterion values of "
    "the cell (min-max normalized WITHIN the candidate×pack matrix by "
    "objectives.normalize_within_set); criteria that are not evaluable are "
    "excluded, never zero-filled. A transparency device on a shared "
    "normalization basis — not a utility function and not a probability."
)


def normalized_score(normalized_values: list[float | None]) -> float | None:
    """Equal-weight mean of the evaluable normalized values of one cell.

    Returns None when NO criterion is evaluable (the cell has no score and is
    excluded from every metric rather than scored as zero)."""
    evaluable = [v for v in normalized_values if v is not None]
    if not evaluable:
        return None
    return round(sum(evaluable) / len(evaluable), 6)


def _metric(
    name: str,
    value: float | None,
    unit: str,
    formula_text: str,
    reason: str | None = None,
) -> dict[str, Any]:
    doc: dict[str, Any] = {
        "name": name,
        "value": round(value, 6) if value is not None else None,
        "unit": unit,
        "formula_text": formula_text,
    }
    if reason is not None:
        doc["reason"] = reason
    return doc


def evaluable_scores(scores_by_pack: dict[str, float | None]) -> dict[str, float]:
    """The pack cells that produced a score (scoreless cells are excluded
    from every score-based metric, never zero-filled)."""
    return {p: s for p, s in scores_by_pack.items() if s is not None}


def worst_case_score(scores_by_pack: dict[str, float | None]) -> dict[str, Any]:
    """Worst (minimum) normalized score across the pack cells of a candidate."""
    scores = evaluable_scores(scores_by_pack)
    if not scores:
        return _metric(
            "worst_case_score",
            None,
            SCORE_UNIT,
            "worst_case_score = min over evaluated packs of the cell's "
            "normalized_score.",
            reason="no pack produced an evaluable normalized score",
        )
    return _metric(
        "worst_case_score",
        min(scores.values()),
        SCORE_UNIT,
        f"worst_case_score = min over the {len(scores)} evaluated pack(s) "
        f"[{', '.join(sorted(scores))}] of the cell's normalized_score.",
    )


def mean_score(scores_by_pack: dict[str, float | None]) -> dict[str, Any]:
    """Arithmetic mean of the normalized scores across evaluated packs."""
    scores = evaluable_scores(scores_by_pack)
    if not scores:
        return _metric(
            "mean_score",
            None,
            SCORE_UNIT,
            "mean_score = (1/N)·Σ s_i over evaluated packs.",
            reason="no pack produced an evaluable normalized score",
        )
    return _metric(
        "mean_score",
        sum(scores.values()) / len(scores),
        SCORE_UNIT,
        f"mean_score = (1/N)·Σ s_i with N = {len(scores)} evaluated pack(s) "
        f"[{', '.join(sorted(scores))}].",
    )


def score_variance(scores_by_pack: dict[str, float | None]) -> dict[str, Any]:
    """POPULATION variance of the normalized scores across evaluated packs.

    The outcome set is the fixed list of deterministic stress scenarios —
    this is variance across deterministic scenarios, NOT the variance of a
    probability distribution and NOT a risk forecast."""
    scores = evaluable_scores(scores_by_pack)
    if not scores:
        return _metric(
            "score_variance",
            None,
            SCORE_UNIT + " squared",
            "score_variance = (1/N)·Σ (s_i − mean(s))² — population variance "
            "across deterministic scenarios, not a probability distribution.",
            reason="no pack produced an evaluable normalized score",
        )
    mean = sum(scores.values()) / len(scores)
    variance = sum((s - mean) ** 2 for s in scores.values()) / len(scores)
    return _metric(
        "score_variance",
        variance,
        SCORE_UNIT + " squared",
        f"score_variance = (1/N)·Σ (s_i − mean(s))² with N = {len(scores)} "
        "evaluated pack(s) — population variance across deterministic "
        "scenarios, not a probability distribution.",
    )


def downside_risk(
    scores_by_pack: dict[str, float | None], unstressed_score: float | None
) -> dict[str, Any]:
    """Mean shortfall below the candidate's OWN unstressed (reference) score.

    downside_risk = (1/N)·Σ max(0, s_unstressed − s_i). A deterministic
    shortfall measure against the candidate's own reference cell — not a
    probability-weighted loss."""
    formula = (
        "downside_risk = (1/N)·Σ max(0, s_unstressed − s_i) over evaluated "
        "packs, where s_unstressed is the candidate's own unstressed "
        "reference score on the same normalization basis."
    )
    if unstressed_score is None:
        return _metric(
            "downside_risk",
            None,
            SCORE_UNIT,
            formula,
            reason="the candidate has no evaluable unstressed reference score",
        )
    scores = evaluable_scores(scores_by_pack)
    if not scores:
        return _metric(
            "downside_risk",
            None,
            SCORE_UNIT,
            formula,
            reason="no pack produced an evaluable normalized score",
        )
    risk = sum(max(0.0, unstressed_score - s) for s in scores.values()) / len(scores)
    return _metric(
        "downside_risk",
        risk,
        SCORE_UNIT,
        f"downside_risk = (1/N)·Σ max(0, {unstressed_score} − s_i) with "
        f"N = {len(scores)} evaluated pack(s).",
    )


def feasibility_rate(feasible_by_pack: dict[str, bool | None]) -> dict[str, Any]:
    """Share of EVALUATED pack cells that are feasible (None cells — where
    feasibility could not be decided — are excluded, never counted as
    failures)."""
    evaluated = {p: f for p, f in feasible_by_pack.items() if f is not None}
    formula = (
        "feasibility_rate = (# packs with feasible=true) / (# evaluated "
        "packs); cells whose feasibility is undecidable are excluded."
    )
    if not evaluated:
        return _metric(
            "feasibility_rate", None, RATE_UNIT, formula,
            reason="no pack cell was evaluable for feasibility",
        )
    rate = sum(1 for f in evaluated.values() if f) / len(evaluated)
    return _metric(
        "feasibility_rate",
        rate,
        RATE_UNIT,
        f"feasibility_rate = {sum(1 for f in evaluated.values() if f)}/"
        f"{len(evaluated)} evaluated pack(s).",
    )


def violation_frequency(violations_by_pack: dict[str, bool]) -> dict[str, Any]:
    """Share of evaluated pack cells with at least one constraint violation."""
    formula = (
        "constraint_violation_frequency = (# packs with >= 1 constraint "
        "violation) / (# evaluated packs)."
    )
    if not violations_by_pack:
        return _metric(
            "constraint_violation_frequency",
            None,
            RATE_UNIT,
            formula,
            reason="no pack cell was evaluated",
        )
    hit = sum(1 for v in violations_by_pack.values() if v)
    return _metric(
        "constraint_violation_frequency",
        hit / len(violations_by_pack),
        RATE_UNIT,
        f"constraint_violation_frequency = {hit}/{len(violations_by_pack)} "
        "evaluated pack(s).",
    )


def best_score_by_pack(
    scores_by_candidate: dict[str, dict[str, float | None]],
) -> dict[str, float | None]:
    """Per pack, the best normalized score reached by ANY candidate.

    Packs where no candidate produced a score map to None (regret is then
    not evaluable for that pack — recorded, never zero)."""
    packs = sorted({p for scores in scores_by_candidate.values() for p in scores})
    best: dict[str, float | None] = {}
    for pack in packs:
        values = [
            scores[pack]
            for scores in scores_by_candidate.values()
            if scores.get(pack) is not None
        ]
        best[pack] = max(values) if values else None
    return best


def regret_by_pack(
    scores_by_pack: dict[str, float | None],
    best_by_pack: dict[str, float | None],
) -> dict[str, dict[str, Any]]:
    """Per-pack maximin regret on the normalized scores.

    regret(pack) = best_score_any_candidate_in_pack − candidate_score_in_pack.
    Not evaluable when the candidate (or every candidate) is scoreless in
    that pack — recorded with a reason, never zero-filled."""
    out: dict[str, dict[str, Any]] = {}
    for pack in sorted(set(scores_by_pack) | set(best_by_pack)):
        score = scores_by_pack.get(pack)
        best = best_by_pack.get(pack)
        formula = (
            f"regret[{pack}] = best_score_any_candidate_in_pack − "
            "candidate_score_in_pack (maximin regret on normalized scores)."
        )
        if score is None:
            out[pack] = _metric(
                f"regret[{pack}]", None, SCORE_UNIT, formula,
                reason="candidate has no evaluable score in this pack",
            )
        elif best is None:
            out[pack] = _metric(
                f"regret[{pack}]", None, SCORE_UNIT, formula,
                reason="no candidate produced an evaluable score in this pack",
            )
        else:
            out[pack] = _metric(
                f"regret[{pack}]", best - score, SCORE_UNIT, formula,
            )
    return out


def worst_case_regret(regrets: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Maximum per-pack regret of a candidate across the evaluated packs."""
    formula = (
        "worst_case_regret = max over packs of regret(pack) = max over packs "
        "of (best_score_any_candidate_in_pack − candidate_score_in_pack)."
    )
    values = {
        pack: doc["value"]
        for pack, doc in regrets.items()
        if doc.get("value") is not None
    }
    if not values:
        return _metric(
            "worst_case_regret", None, SCORE_UNIT, formula,
            reason="no pack produced an evaluable regret",
        )
    worst_pack = max(sorted(values), key=lambda p: values[p])
    return _metric(
        "worst_case_regret",
        values[worst_pack],
        SCORE_UNIT,
        f"worst_case_regret = max over packs of regret(pack); attained at "
        f"'{worst_pack}'.",
    )


def candidate_robustness(
    *,
    candidate_key: str,
    scores_by_pack: dict[str, float | None],
    feasible_by_pack: dict[str, bool | None],
    violations_by_pack: dict[str, bool],
    best_by_pack: dict[str, float | None],
    unstressed_score: float | None,
) -> dict[str, Any]:
    """The full metric block of one candidate (deterministic key order)."""
    regrets = regret_by_pack(scores_by_pack, best_by_pack)
    return {
        "candidate_key": candidate_key,
        "pack_scores": {p: scores_by_pack.get(p) for p in sorted(scores_by_pack)},
        "metrics": {
            "worst_case_score": worst_case_score(scores_by_pack),
            "mean_score": mean_score(scores_by_pack),
            "score_variance": score_variance(scores_by_pack),
            "downside_risk": downside_risk(scores_by_pack, unstressed_score),
            "feasibility_rate": feasibility_rate(feasible_by_pack),
            "constraint_violation_frequency": violation_frequency(violations_by_pack),
            "regret_by_pack": regrets,
            "worst_case_regret": worst_case_regret(regrets),
        },
    }
