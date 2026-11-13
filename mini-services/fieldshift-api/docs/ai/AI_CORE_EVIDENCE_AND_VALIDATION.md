# AI Core Evidence and Response Validation

## Source of truth

The database and existing deterministic domain services remain the source of truth. The gateway reuses `app.intelligence.evidence.build_field_evidence(db, authorized_field)` and does not invent soil tests, water plans, satellite observations, rankings, or predictions. The evidence pack may contain field profile, latest successful climate/water/soil/rotation/management/vegetation results and `data_gaps`; selected context is filtered before provider use.

Every normalized `EvidenceItem` carries:

- Stable `evidence_id` (`field:<field UUID>`, `<domain>:<field UUID>`, or `data_gaps:<field UUID>`).
- Capability, entity scope/ID, result type and `claim_class`.
- Domain result value with units preserved by the source contract.
- Observation period, source kind/ID/provider/acquisition time where discoverable.
- Spatial resolution, processing version, evidence quality/freshness/cloud flags and limitations when present.
- `model_confidence`/`recommendation_confidence` only if the source actually supplies them; the language model does not create confidence scores.
- `status` (`available`, `partial`, `insufficient`, `unavailable`).

Source references are discovered from the existing evidence structure, capped at 12 per envelope item. Missing domain entries are represented separately as `claim_class="missing_information"`, `status="insufficient"`; absence is not zero. The small `data_gaps` labels remain available even when the user narrows domain evidence so the response can explain what is missing.

## Claim classes

The response separates `verified_facts` (field-record/profile facts), `derived_results` (stored engine output), `predictions`, `recommendations`, `general_knowledge`, `assumptions`, and `missing_information`. Current AI Core tooling supplies only recorded/derived field evidence. It therefore returns empty prediction/recommendation/general-knowledge arrays. It does not promote LLM prose into a prediction or recommendation. A future result must retain its domain engine's own provenance, confidence semantics, freshness, status and limitations.

## Validation sequence

1. The advisor sanitizes the question and history, detects injection signals, wraps question/history/evidence/anomaly context as untrusted content, and HTML-escapes delimiter characters so payload text cannot close the wrapper.
2. The existing structured advisor parser validates the response shape and checks citation labels against the current request evidence. One constrained regeneration is allowed after its validation failure; provider failure or repeated failure uses deterministic fallback behavior.
3. AI Core adds a stricter gate: each factual sentence must contain inline `[evidence: LABEL]`; the label must belong to the selected evidence pack; cited numeric claims are checked against the corresponding cited section.
4. The general numeric guard uses explicit dimensional normalization for supported aliases/conversions. Equal values with incompatible dimensions (for example `42.5 mm` and `42.5 kg/ha`) no longer compare as equal. Supported conversions include length (`mm/cm/m`), Celsius/Fahrenheit, percent/fraction, and `kg/ha`↔`Mg/ha`; unknown units are only comparable to the same normalized unit. A z-score magnitude such as `2.35 sigma below` can match a negative `-2.35 z` reference with the textual direction.
5. The citation-specific numeric gate is intentionally more conservative: each numeric sentence must have exactly one inline evidence label and the number/unit must match a reference in that section without cross-section matching or unit conversion.
6. When the strict Core check fails, unvalidated model prose is discarded. The service returns a fixed, localized fallback notice with a field citation and marks execution degraded/partial.

## Important limitations

A citation label such as `[evidence: soil]` identifies a section; the current validators do **not** prove semantic entailment between each sentence and a particular source row, nor do they guarantee the section is the only source of the claim. Labels are not cryptographic references to individual claims. The numerical checker catches unsupported values/units, not false qualitative claims. A syntactically valid model answer can still be agronomically wrong; all operational claims require source data and domain review.

The current model is instructed to avoid recommendations, predictions, diagnosis and general knowledge. Planner rules route explicit requests for these unsupported capabilities to `unavailable`/`planned`, and the Core response schema keeps those result arrays empty. New domain services must pass deterministic validators and agronomist-reviewed benchmark cases before their descriptors can be marked available.

## Context, freshness and prompt versioning

Prompt version is stored as `ai-core-advisor-v1`. Execution traces store a SHA-256 fingerprint of the selected evidence JSON, domain names and source IDs, but not the evidence values or complete prompt/answer. This supports change correlation, not full replay. Source timestamps/periods are carried when present; the Core does not independently decide that stale data are still fit for a specific crop decision. The domain owner must define freshness thresholds and quality rules in the analytical result contract.