"""AI recommendation evaluation framework (A11) — reproducible quality gates.

Success of an API response or existence of LLM text is NOT treated as
quality; everything is checked against deterministic golden fixtures.

Layers:
1. Golden cases (golden_cases.py) — deterministic per-domain fixtures with
   expected behavior (severity, evidence references, numeric content,
   fallbacks). Each case runs the REAL registry generators against a synthetic
   RecommendationContext (no DB, no network).
2. Deterministic regression evaluation (runner.run_deterministic_eval) —
   correctness, severity consistency, evidence traceability, numerical
   correctness, run-to-run stability (same inputs → same fingerprints), and
   behavior with missing/stale evidence.
3. LLM narrative evaluation (llm_eval.run_llm_eval, optional + supplementary)
   — deterministic criteria first (groundedness via numeric-subset checks,
   citation validity, locale correctness); a bridge-based LLM judge is used
   only when explicitly requested and the bridge is reachable, and is NEVER
   the source of truth.
4. Reporting (report.py) — machine-readable JSON with the tracked metrics:
   citation validity rate, unsupported numeric claim rate, schema validity
   rate, fallback rate, latency, cache hit rate, recommendation stability,
   coverage by domain.

Run: `scripts/run_evaluation.py` (adds --with-llm for the supplementary
bridge-backed judge). Tests: tests/integration/test_ai_golden_cases.py
executes the deterministic layers as part of CI (no network required).
"""
