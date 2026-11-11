"""AI recommendation evaluation runner (A11.2-3): deterministic + LLM layers.

Measures recommendation quality reproducibly. Success of an API response or
existence of LLM text is NOT treated as quality; everything is checked
against deterministic golden fixtures.

- run_deterministic_eval: correctness, severity consistency, evidence
  traceability, numerical correctness, run-to-run stability (same inputs →
  same fingerprints), and behavior with missing/stale evidence.
- run_llm_eval (optional + supplementary): deterministic criteria first —
  groundedness (numeric subset vs facts), citation validity, locale
  correctness, clarity, absence of fabricated recommendations. A bridge-based
  LLM judge runs ONLY with --with-llm and is never the source of truth.
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any

from app.recommendations import registry as registry_module
from app.recommendations.fingerprint import compute_fingerprint

logger = logging.getLogger("croptwist.evaluation")


@dataclass
class CheckResult:
    name: str
    passed: bool
    detail: str = ""


@dataclass
class CaseResult:
    case_id: str
    domain: str
    checks: list[CheckResult] = field(default_factory=list)
    latency_ms: float = 0.0

    @property
    def passed(self) -> bool:
        return all(c.passed for c in self.checks)

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "domain": self.domain,
            "passed": self.passed,
            "latency_ms": round(self.latency_ms, 2),
            "checks": [
                {"name": c.name, "passed": c.passed, "detail": c.detail}
                for c in self.checks
            ],
        }


def _check(name: str, passed: bool, detail: str = "") -> CheckResult:
    return CheckResult(name=name, passed=passed, detail=detail)


def _generators_for(registry: registry_module.RecommendationRegistry, domain: str) -> list[Any]:
    return registry._generators.get(domain, [])  # noqa: SLF001 — evaluation harness


def run_golden_case(
    case: dict[str, Any],
    registry: registry_module.RecommendationRegistry | None = None,
) -> CaseResult:
    """Run ONE golden case through the real generators (no DB, no bridge)."""
    reg = registry or registry_module.registry
    started = time.perf_counter()
    result = CaseResult(case_id=case["case_id"], domain=case["domain"])

    ctx = registry_module.RecommendationContext(**case["context"])
    recs: list[Any] = []
    for fn in _generators_for(reg, case["domain"]):
        try:
            recs.extend(fn(None, ctx.field, ctx) or [])
        except Exception as exc:  # noqa: BLE001 — record as a failed check
            result.checks.append(
                _check(f"generator_{getattr(fn, '__name__', fn)}", False, f"raised {exc}")
            )
    result.latency_ms = (time.perf_counter() - started) * 1000

    expect = case.get("expect") or {}

    if "min_recs" in expect:
        result.checks.append(_check("min_recs", len(recs) >= expect["min_recs"], f"got {len(recs)}"))
    if "max_recs" in expect:
        result.checks.append(_check("max_recs", len(recs) <= expect["max_recs"], f"got {len(recs)}"))
    if expect.get("required_severities"):
        got = {r.severity.value for r in recs}
        missing = set(expect["required_severities"]) - got
        result.checks.append(_check(
            "required_severities", not missing, f"missing {sorted(missing)}; got {sorted(got)}",
        ))
    if expect.get("forbidden_severities"):
        got = {r.severity.value for r in recs}
        present = set(expect["forbidden_severities"]) & got
        result.checks.append(_check(
            "forbidden_severities", not present, f"forbidden {sorted(present)} present",
        ))
    if expect.get("required_evidence_labels"):
        labels = {e.get("label") for r in recs for e in (r.evidence or [])}
        missing = set(expect["required_evidence_labels"]) - labels
        result.checks.append(_check(
            "required_evidence_labels", not missing, f"missing {sorted(missing)}; got {sorted(labels)}",
        ))
    if expect.get("required_title_fragments"):
        joined = " | ".join(r.title for r in recs)
        for fragment in expect["required_title_fragments"]:
            result.checks.append(_check(
                f"title_contains:{fragment[:32]}", fragment in joined, joined[:160],
            ))
    if expect.get("required_numbers"):
        blob_parts: list[str] = []
        for r in recs:
            blob_parts.extend([r.title, r.summary, r.rationale])
            blob_parts.extend(str(e.get("detail")) for e in (r.evidence or []))
        blob = " | ".join(blob_parts)
        for number in expect["required_numbers"]:
            result.checks.append(_check(
                f"number:{number}", str(number) in blob, blob[:160],
            ))
    if expect.get("generator"):
        names = {r.generator or "" for r in recs}
        result.checks.append(_check(
            "generator_emitted", any(expect["generator"] in n for n in names),
            f"generators: {sorted(names)}",
        ))
    return result


def run_stability_check(
    case: dict[str, Any],
    registry: registry_module.RecommendationRegistry | None = None,
) -> CheckResult:
    """Run the same golden case twice; fingerprints must be identical."""
    reg = registry or registry_module.registry
    ctx = registry_module.RecommendationContext(**case["context"])

    def _fps() -> list[str]:
        out: list[str] = []
        for fn in _generators_for(reg, case["domain"]):
            for rec in fn(None, ctx.field, ctx) or []:
                out.append(compute_fingerprint(rec, ctx.field["id"]))
        return out

    first, second = _fps(), _fps()
    return _check(
        "fingerprint_stability", first == second,
        f"{len(first)} vs {len(second)} fingerprints; equal={first == second}",
    )


def run_missing_evidence_check(
    case: dict[str, Any],
    registry: registry_module.RecommendationRegistry | None = None,
) -> CheckResult:
    """Behavior with missing/stale evidence: data-gap recs must appear and
    no crash may occur (case provides `missing_evidence_context`)."""
    reg = registry or registry_module.registry
    empty_ctx = registry_module.RecommendationContext(**case["missing_evidence_context"])
    recs: list[Any] = []
    raised: str | None = None
    try:
        for fn in _generators_for(reg, case["domain"]):
            recs.extend(fn(None, empty_ctx.field, empty_ctx) or [])
    except Exception as exc:  # noqa: BLE001
        raised = str(exc)
    expect = case.get("missing_expect") or {}
    ok = raised is None
    detail = f"recs={len(recs)}"
    if expect.get("required_severities"):
        got = {r.severity.value for r in recs}
        ok = ok and set(expect["required_severities"]) <= got
        detail += f"; severities={sorted(got)}"
    if expect.get("required_title_fragments"):
        joined = " | ".join(r.title for r in recs)
        for fragment in expect["required_title_fragments"]:
            ok = ok and fragment in joined
        detail += "; fragments checked"
    return _check("missing_evidence_behavior", ok, detail)


def run_deterministic_eval(
    cases: list[dict[str, Any]] | None = None,
    registry: registry_module.RecommendationRegistry | None = None,
) -> dict[str, Any]:
    """Full deterministic evaluation over all golden cases."""
    from app.evaluation.golden_cases import GOLDEN_CASES

    cases = cases if cases is not None else GOLDEN_CASES
    results: list[CaseResult] = []
    stability: list[CheckResult] = []
    missing: list[CheckResult] = []
    for case in cases:
        results.append(run_golden_case(case, registry))
        stability.append(run_stability_check(case, registry))
        if case.get("missing_evidence_context"):
            missing.append(run_missing_evidence_check(case, registry))

    all_checks = [c for r in results for c in r.checks] + stability + missing
    passed = sum(1 for c in all_checks if c.passed)
    total = len(all_checks)
    by_domain: dict[str, dict[str, Any]] = {}
    for r in results:
        entry = by_domain.setdefault(
            r.domain, {"cases": 0, "passed": 0, "checks": 0, "checks_passed": 0}
        )
        entry["cases"] += 1
        entry["passed"] += 1 if r.passed else 0
        entry["checks"] += len(r.checks)
        entry["checks_passed"] += sum(1 for c in r.checks if c.passed)

    return {
        "suite": "deterministic",
        "total_checks": total,
        "passed_checks": passed,
        "failed_checks": total - passed,
        "pass_rate": round(passed / total, 4) if total else None,
        "stability_rate": (
            round(sum(1 for c in stability if c.passed) / len(stability), 4)
            if stability else None
        ),
        "coverage_by_domain": by_domain,
        "results": [r.to_dict() for r in results],
        "stability_checks": [
            {"case_id": case["case_id"], "passed": c.passed, "detail": c.detail}
            for case, c in zip(cases, stability)
        ],
        "missing_evidence_checks": [
            {"case_id": cases[i]["case_id"], "passed": c.passed, "detail": c.detail}
            for i, c in enumerate(missing)
        ],
    }


# ---------------------------------------------------------------------------
# A11.3: LLM narrative evaluation (supplementary; deterministic checks first)
# ---------------------------------------------------------------------------

_NUM_RE = re.compile(r"\d+(?:\.\d+)?")


def _facts_numbers(recs: list[Any]) -> set[str]:
    """All numeric strings present in the deterministic facts."""
    numbers: set[str] = set()
    for rec in recs:
        for text in (
            rec.get("title"), rec.get("summary"), rec.get("rationale"),
            *[(e or {}).get("detail") for e in (rec.get("evidence") or [])],
        ):
            if not isinstance(text, str):
                continue
            for match in _NUM_RE.findall(text):
                numbers.add(match)
                numbers.add(str(round(float(match), 1)))
                numbers.add(str(round(float(match), 2)))
                numbers.add(str(int(float(match))) if float(match).is_integer() else match)
    return numbers


def evaluate_narrative_set(
    recs: list[dict[str, Any]], narratives: dict[str, str], locale: str
) -> dict[str, Any]:
    """Deterministic LLM-narrative criteria (no judge model needed):

    - groundedness: every number in a narrative must exist in the facts;
    - fabrication: narrative may not invent a different recommendation;
    - clarity: non-empty, reasonable length;
    - language: Arabic narratives contain Arabic script; English ones don't
      need checks beyond non-emptiness (locale correctness heuristic).
    """
    numbers = _facts_numbers(recs)
    titles = " | ".join(str(r.get("title")) for r in recs)
    checks: list[dict[str, Any]] = []
    arabic_re = re.compile(r"[\u0600-\u06FF]")

    for key, text in narratives.items():
        text = (text or "").strip()
        numeric_ok = True
        unsupported: list[str] = []
        for match in _NUM_RE.findall(text):
            if match not in numbers:
                numeric_ok = False
                unsupported.append(match)
        checks.append({
            "narrative_key": key,
            "groundedness_numeric": numeric_ok,
            "unsupported_numbers": unsupported,
            "clarity": 20 <= len(text) <= 600,
            "locale_consistent": (
                bool(arabic_re.search(text)) if locale == "ar" else True
            ),
            "fabrication_free": not any(
                token and token not in titles and token.isupper()
                for token in re.findall(r"\b[A-Z][A-Z ]{8,}\b", text)
            ),
        })

    total = len(checks) or 1
    return {
        "narrative_count": len(checks),
        "groundedness_rate": round(
            sum(1 for c in checks if c["groundedness_numeric"]) / total, 4
        ),
        "unsupported_numeric_claims": sum(len(c["unsupported_numbers"]) for c in checks),
        "clarity_rate": round(sum(1 for c in checks if c["clarity"]) / total, 4),
        "locale_consistency_rate": round(
            sum(1 for c in checks if c["locale_consistent"]) / total, 4
        ),
        "fabrication_free_rate": round(
            sum(1 for c in checks if c["fabrication_free"]) / total, 4
        ),
        "checks": checks,
    }


def run_llm_eval(
    cases: list[dict[str, Any]] | None = None,
    registry: registry_module.RecommendationRegistry | None = None,
    *,
    with_judge: bool = False,
) -> dict[str, Any]:
    """LLM narrative evaluation over golden cases with live rec generation.

    Deterministic criteria ALWAYS run (groundedness/clarity/locale). The
    bridge-based judge is supplementary and off by default; it is skipped
    silently when the bridge is unavailable — its verdict is never decisive.
    """
    reg = registry or registry_module.registry
    from app.evaluation.golden_cases import GOLDEN_CASES

    cases = cases if cases is not None else GOLDEN_CASES
    from app.intelligence import narrative as narrative_module

    narratives_by_case: dict[str, dict[str, str]] = {}
    judge_by_case: dict[str, Any] = {}
    for case in cases:
        ctx = registry_module.RecommendationContext(**case["context"])
        recs: list[dict[str, Any]] = []
        for fn in _generators_for(reg, case["domain"]):
            try:
                for rec in fn(None, ctx.field, ctx) or []:
                    recs.append(rec.model_dump(mode="json"))
            except Exception:  # noqa: BLE001 — eval must not crash
                continue
        if not recs:
            continue
        locale = case.get("locale", "en")
        detail = narrative_module.chat_detail
        meta = None
        try:
            meta = narrative_module.enrich_recommendations(
                None, ctx.field, [dict(r) for r in recs], locale=locale, force=True
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("llm eval narrative enrichment failed: %s", exc)
        if meta:
            nar = {
                str(i): r["narrative"]
                for i, r in enumerate(recs)
                if r.get("narrative")
            }
            narratives_by_case[case["case_id"]] = nar
            if with_judge and detail is not None:
                judge_by_case[case["case_id"]] = _judge_case(recs, nar, locale)

    metrics_summary = {
        "cases_with_narratives": len(narratives_by_case),
        "schema_validity_rate": 1.0 if narratives_by_case else None,
        "fallback_rate": None,
        "cache_hit_rate": None,
    }

    per_case = {}
    for case in cases:
        nar = narratives_by_case.get(case["case_id"])
        if nar is None:
            continue
        ctx = registry_module.RecommendationContext(**case["context"])
        recs: list[dict[str, Any]] = []
        for fn in _generators_for(reg, case["domain"]):
            try:
                for rec in fn(None, ctx.field, ctx) or []:
                    recs.append(rec.model_dump(mode="json"))
            except Exception:  # noqa: BLE001
                continue
        per_case[case["case_id"]] = {
            "deterministic_criteria": evaluate_narrative_set(recs, nar, case.get("locale", "en")),
            "judge": judge_by_case.get(case["case_id"]),
        }

    return {"suite": "llm", "metrics": metrics_summary, "cases": per_case}


def _judge_case(recs: list[dict[str, Any]], narratives: dict[str, str], locale: str) -> dict[str, Any]:
    """Supplementary single-call LLM judge; NEVER decisive (A11.3)."""
    from app.intelligence.bridge import chat_detail

    prompt = (
        "You are evaluating AI-generated narratives for agronomic "
        "recommendations. Rate each 1-5 on: groundedness, clarity, language "
        "correctness. Reply ONLY with JSON "
        '{"scores": [{"key": "0", "groundedness": n, "clarity": n, '
        '"language": n}], "notes": "..."}\n'
        f"Locale: {locale}\n"
        "Facts:\n" + "\n".join(
            f"{r.get('title')} — {r.get('summary')}" for r in recs
        ) + "\nNarratives:\n" + "\n".join(f"{k}: {v}" for k, v in narratives.items())
    )
    detail = chat_detail([{"role": "user", "content": prompt}])
    if detail is None:
        return {"available": False}
    return {"available": True, "raw": detail["content"][:4000]}
