# AI Orchestration Evaluation Foundation

## Evaluation scope

The current benchmark is a deterministic, offline foundation for planner and safety behavior—not a claim of agricultural model accuracy. It intentionally separates (a) deterministic unit assertions, (b) provider-mocked integration cases, and (c) future qualitative/model evaluation. No live model call or production field data is used by the checked-in benchmark.

The synthetic JSONL dataset is `tests/evaluation/ai_core_cases.jsonl`. It contains nine versionable cases covering soil explanation, missing field clarification, crop suitability (planned), yield prediction (unavailable), scenario comparison (planned), climate explanation, blocked platform mutation, recommendation request, and unavailable general knowledge. Each row specifies an ID, question, field-scope presence, expected intent, expected operational tool, availability, and clarification expectation. It is safe, synthetic text and contains no user or farm data.

Run the plan benchmark:

```bash
cd mini-services/fieldshift-api
PYTHONPATH=. .venv/bin/pytest -c /dev/null --confcutdir=tests/unit \
  tests/unit/test_ai_core_evaluation.py tests/unit/test_ai_core_orchestration.py -q
```

The test invokes the same deterministic `create_plan`/`evaluate_plan_case` functions used by the service. Any intent, tool-presence, availability or clarification drift fails the benchmark.

## Coverage matrix

| Evaluation property | Deterministic test/evidence |
|---|---|
| Intent and tool selection | JSONL plan benchmark; priority regression for crop suitability vs soil keyword; recommendation/prediction/scenario cases. |
| Required field/clarification | Field-missing planner case; typed request rejects blank questions and extra actor/tenant keys. |
| Context selection | Allowlist test verifies unsupported domains are discarded, field is retained and data gaps remain explicit. Evidence selection has a 16 KB hard budget. |
| Tool permission/schema/output | Unplanned tool denied; controlled side-effect handler is never called; sequential workflow test checks validated prior-step context; registry enforces argument/output schemas, timeout, step and byte limits. |
| Provider capability honesty | Tests ensure legacy bridge adapter does not claim native structured output, model tool calling, streaming or guaranteed token usage; unsupported modes raise. |
| Grounding/citations | Core validator tests cited facts, uncited factual sentence rejection and allowed-label membership. Unit tests remain deterministic. |
| Numeric consistency | Existing and new tests cover rounding, supported unit conversion, anomaly z-score magnitude, same-number/wrong-dimension rejection, and kg/ha↔Mg/ha factor. Cited numeric claims must match the same unit in the one cited section. |
| Prompt injection | Existing sanitization tests plus regressions for escaped `</untrusted_data>`/fake `<system>` payloads in both user input and retrieved evidence/anomaly text. |
| Session privacy | Database-backed integration test is authored for two users in one organization; not executed in this environment. |
| Provider route behavior | Database-backed integration test uses a mocked bridge; no live LLM call; not executed here. |
| Latency | Each invocation records `latency_ms`; `summarize_latency_ms()` computes count/mean/nearest-rank p50/p95/p99. Unit test covers ordering and empty samples. |
| Success rate | Invocation trace records `answered`, `partial`, `clarification_required`, `unavailable`, or `failed`; aggregate full/partial rates can be computed from trace counts. No public analytics query endpoint is added. |
| Cost | Trace stores optional token counts only when the adapter reports them. `estimate_provider_cost()` requires both counts and caller-supplied per-million input/output rates; returns `None` when usage or price is missing. Current bridge advertises no guaranteed usage reporting, so current cost is **not measurable from this code**. |
| Factual accuracy | Core validators score format/label/unit consistency, not semantic truth. No field-owner gold labels, agronomist adjudication set, calibration study or factual-accuracy percentage is available. No accuracy claim is made. |

## What is measured and how

For an operational dashboard or offline report, group `ai_execution_traces` by date, intent, provider/model, status and low-cardinality tool name. Use `answered + partial` as “response returned” rate and `answered` as “fully available path” rate; separately report unavailable, clarification and failed counts so success cannot be inflated by hiding unsupported requests. Compute latency percentiles from recorded `latency_ms`. Include only tokens actually returned by the provider; estimate price only with the pricing applicable to the exact provider/model/time. The new trace deliberately omits prompt/answer/evidence values; accuracy evaluation must use a separate protected, consented evaluation harness rather than recover sensitive conversations from operational logs.

`evaluation.py` supplies pure helpers for intent-case scoring, outcome-rate summaries (`answer_returned_rate`, `fully_answered_rate`, `failure_rate`), latency percentiles and caller-priced token cost. It does not query production traces, fetch provider prices, call an LLM judge, log prompts, or report an unsupported aggregate. This separation avoids claiming cost/quality data the current adapter cannot measure.

## Current test results and execution boundary

The safe offline AI slice last completed with **63 passed, 13 warnings in 2.81 seconds**:

```bash
PYTHONPATH=. .venv/bin/pytest -c /dev/null --confcutdir=tests/unit \
  tests/unit/test_ai_core_orchestration.py \
  tests/unit/test_ai_core_evaluation.py \
  tests/unit/test_guard_prompt_injection.py \
  tests/unit/test_numeric_guard.py \
  tests/unit/test_structured_response.py \
  tests/unit/test_bridge_async.py -q
```

The warnings are pre-existing SQLAlchemy reserved-name warnings for model attributes named `metadata`. Python compile checks passed. FastAPI OpenAPI generation registered `/api/v1/ai/requests`, `/api/v1/ai/capabilities`, and `/api/v1/ai/tools`. Alembic recognized `0024_ai_core_orchestration` as head without a database connection.

The integration tests in `tests/integration/test_ai_core.py` were **not run**. Repository `tests/conftest.py` connects to `croptwist_test`, upgrades migrations, and has an autouse cleanup that truncates non-internal public tables. No disposable database was designated for this task; running it could alter a shared database. Integration/full-suite execution is a release gate against an isolated PostGIS database.

## Next benchmark phases

1. Add agronomist-reviewed, source-cited gold examples covering region/crop/season, missing/stale/cloud-contaminated observations, uncertainty and contraindications; store no customer prompts.
2. Add contract tests for source freshness, versioned engine inputs, units, citation-to-claim association and unavailable/partial semantics per capability.
3. Add deterministic integration cases for field authorization, same-org owner privacy, 429/`Retry-After`, provider outage, invalid model citations, stale evidence and failed multi-step traces.
4. Only after privacy approval, run a blinded qualitative model evaluation with domain reviewers. Report sample size, confidence interval, model/prompt versions, regions, languages and adjudication method.
5. Add telemetry-backed success/latency/cost reports after provider usage/pricing and a shared limiter are available; do not place prompts or farm facts in metric labels.
