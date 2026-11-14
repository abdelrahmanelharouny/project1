# AI Core Evidence and Response Validation

**Status:** Describes current source-level behavior. It is not a claim of agronomic accuracy, live-provider operation, or production approval. The mocked provider-adapter suite passed 73 tests; the complete local verification ledger belongs in [`MASTER_INTEGRATION_ENGINEERING_REPORT.md`](../../../../docs/implementation/MASTER_INTEGRATION_ENGINEERING_REPORT.md).

## Evidence source and selected context

The database and existing deterministic domain services remain the source of truth. The Core reuses `app.intelligence.evidence.build_field_evidence(db, authorized_field)`. It does not create soil tests, water plans, satellite observations, risk scores, forecasts, rankings, or predictions. The current planner workflow first runs `collect_field_evidence`, then passes its schema-validated result to `synthesize_field_answer`.

The planner's seven evidence domains are `climate`, `water`, `soil`, `rotation`, `management`, `vegetation`, and `data_gaps`. Evidence selection always retains the authorized `field` profile and explicit data-gap metadata. An optional allowlisted request-domain list can narrow the selected domains but never authorizes the field. Water may include climate; rotation may include soil/climate/water; some explanatory vegetation questions include climate/water/soil/management. The selected pack is limited to 16,000 UTF-8 bytes before use in the provider-backed explanation path.

A normalized `EvidenceItem` carries:

- Stable envelope ID and capability/entity scope (`field` plus the authorized field ID).
- Result type and claim class (`verified_fact`, `derived_result`, `model_prediction`, `recommendation`, `general_knowledge`, `assumption`, or `missing_information`).
- The source section's value with units preserved when present; no AI-generated confidence is added.
- Observation period and up to 12 discovered source references when available.
- Source-derived spatial resolution, processing version, freshness/cloud/evidence-quality indicators and limitations where available.
- Source-provided `model_confidence`/`recommendation_confidence` only if the underlying service actually supplied it.
- Status `available`, `partial`, `insufficient`, or `unavailable`.

Missing domain evidence is represented separately with `claim_class="missing_information"`, `status="insufficient"`; a missing value is not zero. The provider receives selected source evidence rather than authority to fetch arbitrary resources. Evidence normalization is an envelope, not a replacement source database.

## Claim separation and unsupported classes

The response separates recorded/profile facts (`verified_facts`) from stored deterministic engine outputs (`derived_results`). It does not promote model prose into domain predictions, recommendations, or cited agricultural knowledge. For the current Core, `predictions`, `recommendations`, and `general_knowledge` response arrays are empty. Model confidence is not calibrated or generated.

Soil, water, climate, vegetation, stress/anomaly, spatial, and saved rotation explanations are partial views of existing evidence only. Crop suitability, field risk ranking, scenarios, and report generation are planned and not callable. Agricultural recommendations/prescriptions, yield/other prediction, general agricultural knowledge, and platform action/mutation are unavailable. A limitation or capability descriptor is not evidence that the capability ran.

## Current validation sequence

1. Existing advisor guards sanitize question/history and mark user text and selected evidence as untrusted, escaping delimiter characters used by prompt wrappers. Recent history is bounded and roles are constrained.
2. The existing advisor's structured response/citation path validates its expected output and evidence labels; a constrained regeneration may be attempted by that advisor. This is not a provider-native JSON-schema guarantee for every provider or endpoint.
3. AI Core adds a stricter check: factual sentences need inline `[evidence: LABEL]` citations, and labels must resolve to the current selected evidence pack.
4. The Core numeric check associates a cited numeric sentence with its cited evidence section and requires the number/unit to match a reference in that section. It is deliberately conservative: no cross-section matching and no unit conversion at this final citation gate.
5. Existing general numeric guards normalize explicitly supported dimensions/conversions (length, Celsius/Fahrenheit, percent/fraction, and `kg/ha`/`Mg/ha`); equal values with incompatible dimensions are not equal. Anomaly z-score magnitude/direction matching is handled by the existing guard.
6. If the strict Core check fails, unvalidated model prose is discarded. The service substitutes a localized deterministic notice limited to recorded facts/deterministic results and marks the result degraded/partial. If the provider is blocked/unavailable, a fallback notice may be returned; it is not a provider-generated answer.

The provider chain is configured in this order by default: Gemini `gemini-3.6-flash` → Groq `openai/gpt-oss-120b` → OpenRouter `nvidia/nemotron-3.5-super-vl:free`. Field data remains gated off by default; enabling Gemini/Groq requires `CROPTWIST_AI_ALLOW_FIELD_DATA_TO_PROVIDERS=true`, and OpenRouter also requires `CROPTWIST_OPENROUTER_ALLOW_FIELD_DATA=true`. Provider status is configuration-only and reports live connectivity unverified. Provider fallback does not bypass evidence validation.

## Citation and semantic limitations

An inline label such as `[evidence: soil]` identifies an evidence section, not an immutable source-row/claim binding. The current checks validate label membership and conservative numeric consistency; they do **not** prove semantic entailment, agronomic correctness, source freshness for a crop-specific decision, or that the labeled section is the only support for a sentence. A qualitative claim can be false while its citation label is valid. Stored data-quality indicators are forwarded where present; the Core does not independently recalculate source quality or define agronomic freshness thresholds.

No citation should be fabricated for knowledge retrieval: the rights-aware knowledge primitives under `.../orchestration/knowledge.py` are separate from advisor synthesis, the embedding registry is empty by default, and no approved corpus/embedding adapter is configured. Retrieval requires same-organization, provider/model/dimension and freshness checks and an explicit embedding-sharing policy. Until source passages are actually retrieved and connected to synthesis, an LLM answer from general agricultural knowledge is unavailable rather than RAG-backed.

## Traceability, history, and prompt version

The current prompt version is `ai-core-advisor-v1`. The execution trace stores a SHA-256 fingerprint of selected evidence JSON, selected context names, source references, validation codes, provider attempts when reported, usage when actually reported, tool outcomes, and safe request/user/field/conversation identifiers. It omits the full prompt, raw question/answer, complete evidence values, and provider secrets. A fingerprint supports correlation but does not provide full replay.

Core history is owner- and field-bounded; model context defaults to six turns and is sanitized/untrusted. Conversation APIs separately expose bounded stored transcripts only to their owner after field authorization. Transcript storage contains user and assistant content and is not the metadata-only trace.

## Verification and promotion criteria

Unit/contract tests should cover allowed evidence labels, missing-data semantics, citation omission, numeric/unit mismatch, cross-section numeric rejection, provider failure and fallback, prompt delimiter attacks, selected-domain filtering, output bounds, and Arabic planning/notice paths. Integration tests should cover field authorization, conversation owner/field isolation, trace metadata, privacy gates, feedback consent, tenant-scoped knowledge, and retention deletion against an isolated disposable database.

The mocked provider-adapter suite passed 73 tests; this establishes tested request/response and failure contracts only, not provider reachability or model quality. Consult the linked integration engineering report for the complete verification ledger. Before any domain is marked operational beyond current stored-evidence explanation, its owner must supply source-backed evaluation, documented freshness/quality semantics, agronomist review where relevant, and release approval.
