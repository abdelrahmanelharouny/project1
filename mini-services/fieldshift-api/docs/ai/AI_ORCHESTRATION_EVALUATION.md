# AI Orchestration Evaluation and Verification Ledger

**Purpose:** Define what the checked-in offline evaluation can measure and keep implementation, test verification, live-provider verification, and production readiness separate. This document does not claim that current provider reliability tests or the final suite have passed. The provider workstream is updating reliability tests; authoritative final counts and pass/fail records belong in [`MASTER_INTEGRATION_ENGINEERING_REPORT.md`](../../../../docs/implementation/MASTER_INTEGRATION_ENGINEERING_REPORT.md), not in a stale historical count here.

## Evaluation scope

The deterministic offline benchmark evaluates planner and safety behavior without live inference or production field data. It is not an agricultural model accuracy benchmark, not a provider connectivity test, and not proof of deployment readiness. The synthetic, version-controlled cases live in `tests/evaluation/ai_core_cases.jsonl`; they exercise supported field explanations, clarification, and explicit planned/unavailable intents such as suitability, prediction/yield, scenario, recommendation, knowledge, and actions. Inspect the current dataset for its exact case set; no stale fixed case/pass count is asserted here.

Run only the intended unit/offline slice after consulting the current integration test safety guidance. Do not invoke database-backed/full suites against a shared or undeclared database: repository test fixtures can migrate and truncate public tables. A final safe invocation, environment, commit/tree snapshot, and outcome must be recorded by the integration owner in the master report.

## Evaluation layers

| Layer | What it can establish | What it cannot establish |
|---|---|---|
| Static/source inspection | A route, provider adapter, gate, schema, or retention task is present in source. | That migration has been applied, a route works in deployment, or an external provider is reachable. |
| Deterministic unit/contract tests | Rule-based intent/plan outcomes, strict schemas, evidence filtering, bounds, side-effect rejection, citation/number checks, retention primitives, and mocked adapter behavior covered by those tests. | Agronomic factual accuracy, live provider service, distributed behavior, or production safety. |
| Mocked integration tests | HTTP/API orchestration, error mapping, ownership/persistence paths, and provider chain behavior for the tested mocks/configuration. | Real provider terms/connectivity, real model quality, or live credentials/account limits. |
| Live provider smoke check | A time-bounded authenticated request with explicit configuration and policy authorization can reach a named provider/model at the checked time. | Stable availability, general answer accuracy, privacy/legal approval, cost, or production readiness. No live check is claimed by this document. |
| Domain/qualitative evaluation | With a consented, source-backed, expert-reviewed gold set, estimates quality for that specified sample. | General correctness outside the sample, regions, crops, languages, versions, or time period. No gold-set accuracy figure is currently claimed. |
| Production readiness review | Operational, security, privacy, database, scale, cost, observability, and support controls after deployment-specific review. | Not established solely by code, unit tests, or passing one integration run. |

## Properties to evaluate

| Property | Deterministic evidence to collect |
|---|---|
| Intent and plan selection | Compare `create_plan` output against JSONL expected intent, ordered tool list, availability, clarification, and explicit supported/unavailable cases. Current supported plan sequence is `collect_field_evidence` then `synthesize_field_answer`. |
| Field requirement and request strictness | Missing field clarification, blank/oversized question rejection, duplicate/unknown context-domain rejection, and rejection of extra actor/tenant/provider/tool inputs. |
| Context and evidence bounds | Allowlist behavior; field profile/data-gap retention; seven selected domains; 16 KB evidence ceiling; explicit absent data rather than zero. |
| Tool security and limits | Unplanned tool denial, permission checks, no side effects, dependency ordering, validated prior-result handling, workflow/tool deadlines and output byte limits. |
| Provider behavior | Configured default priority and exact model IDs; environment-only credentials; global and OpenRouter-specific privacy gates; only retryable failure advances; no fallback after partial stream output; status endpoint remains non-live. Provider reliability tests are in progress. |
| Provider schema claims | Adapter contracts and capability declarations should be tested against request/response fixtures. Do not claim every provider/path uses native structured output merely because an adapter exposes it; Core factual narrative validation remains local. |
| Response grounding | Allowed citation labels, per-factual-sentence citation requirement, deterministic safe fallback after invalid prose, explicit unsupported result arrays. |
| Numeric consistency | Supported conversions in the general guard, incompatible dimensions rejected, and the final citation-specific comparison restricted to the same cited section and unit. |
| Prompt injection | Escaped closing delimiters/fake system tags in question, history, and evidence; tests verify guardrails rather than prove semantic immunity. |
| Session privacy | Database-backed checks for same-organization different-user access, cross-field sessions, owner-null legacy sessions, expiry, and transcript list/history ownership. Use a disposable DB only. |
| Feedback privacy | Required affirmative consent, user/trace/field scoping, allowed lifecycle transitions, owner-only update/delete, and `unverified_user_reported` outcome label. |
| Knowledge boundaries | Rights attestation; manager/org scope; document/query provider sharing gates; provider/model/dimension/freshness matching; no lexical fallback or fabricated citation when embedding is not configured. |
| Retention | Bounded purge of feedback, traces and expired conversations; scheduler registration and operations history; verify settings and cascading transcript deletion in an isolated DB. |
| Latency, status and cost helpers | `evaluation.py` can summarize latency/outcome rates and estimate cost only when actual input/output usage plus caller-supplied exact rates are available. Current operations endpoint returns `cost_estimate: null`; no live pricing is configured. |
| Semantic/agronomic accuracy | Requires separate consented, source-backed and domain expert-adjudicated examples with sample, region/crop/language, model/prompt versions and method reported. No accuracy percentage is claimed. |

## Operational measurements and interpretation

`AIExecutionTrace` stores status, latency, provider/model, attempts when available, optional token counts, plan/tool metadata, evidence fingerprint/references and normalized errors. `/api/v1/ai/operations/status` returns a seven-day summary for the authenticated user's own traces (bounded to recent rows), provider-attempt counts and latency summaries; it reports no cost estimate without live provider pricing. It does not run a live provider check and does not recover prompt/answer/evidence content.

Use separate outcome counts for `answered`, `partial`, `clarification_required`, `unavailable`, and `failed`; do not inflate “success” by hiding unavailable/clarification requests. Latency percentiles should be calculated only from captured request timings and labeled with the source/time window. Tokens are countable only if the adapter returned them. A caller-supplied price rate is not proof of the provider's current price.

## Current verification boundary

This documentation update did not run tests, touch database state, call any provider, or modify test/source code. Provider reliability tests are being actively updated by their owner; interim test records are not final. Do not infer a current pass from source presence, a stale log, a mock-only test, or `/providers` status. The provider-status endpoint explicitly reports `live_connectivity_verified: false` until a separate authorized smoke test is performed.

The checkout contains migration revision files through 0025: 0024 adds session ownership and traces; 0025 adds provider-attempt metadata, feedback and knowledge document/chunk tables. Repository revision presence is distinct from a target database's applied revision. Do not report later integration migrations as applied until the integration owner verifies them after merge/deployment.

## Final reporting and promotion gates

The integration owner should record the exact test commands, pass/fail/skip counts, warnings, database isolation, migration revision state, provider mock/live status, source snapshot, and unresolved blockers in [`MASTER_INTEGRATION_ENGINEERING_REPORT.md`](../../../../docs/implementation/MASTER_INTEGRATION_ENGINEERING_REPORT.md). This report is the single final ledger; this page intentionally avoids duplicating interim counts.

Before enabling field data to external models, review exact provider terms and explicitly enable the applicable privacy gates. Before promoting domain capability descriptors, require authorized end-to-end tests and domain-owner freshness/quality/provenance semantics. Before production, separately review distributed rate limits, retention scheduler operation, access policy, monitoring, vendor/contract terms, cost controls, migration rollout/backups, and incident response. Any future recommendation, yield/prediction, suitability, risk ranking, scenario, report-action, or platform mutation requires dedicated domain validation and an explicit release decision.
