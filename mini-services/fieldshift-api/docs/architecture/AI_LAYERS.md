# CropTwist AI Layers — Architecture

CropTwist is **AI-driven and data-driven by design**: every suggestion the
product makes is produced by deterministic engines over provenance-tracked
data, and the AI layers organize, narrate and explain those outputs — they
never replace them. The stack is structured in four layers:

```
┌──────────────────────────────────────────────────────────────────────┐
│ 4. API / Presentation     /api/v1/recommendations.py + frontend tab  │
├──────────────────────────────────────────────────────────────────────┤
│ 3. Recommendation Layer   app/recommendations/  (central registry)   │
├──────────────────────────────────────────────────────────────────────┤
│ 2. Intelligence Layer     app/intelligence/  (evidence · anomalies · │
│                           LLM bridge · advisor · narratives)         │
├──────────────────────────────────────────────────────────────────────┤
│ 1. Data Processing Layer  app/data_platform/ + deterministic engines │
└──────────────────────────────────────────────────────────────────────┘
```

---

## 1. Data Processing Layer — `app/data_platform/` + domain engines

The foundation: everything the AI layers ever say is derived from this layer.

- **Providers** (`app/data_platform/providers/`):
  - **Open-Meteo ERA5** — historical reanalysis (precipitation, temperature,
    ET0 variables) via the archive API.
  - **CHIRPS satellite rainfall** — GeoTIFF extraction for precipitation
    where ground/reanalysis coverage is not used.
  - **ISRIC SoilGrids** — gridded soil properties (0–5 cm predictions,
    explicitly labelled as model predictions, never lab measurements).
  - **Synthetic provider** — fully deterministic test data (flagged
    `is_synthetic` end to end; never mixed with real data).
- **Ingestion + QA** (`ingestion/`, observations contracts): canonical
  observations with quality flags; missing data is never zero-filled.
- **Feature engine** (`app/features/`): versioned, reproducible feature runs
  (seasonal totals, hot/frost-day counts, dry spells, precipitation anomaly
  z, ET0, ...) with per-value provenance and coverage ratios.
- **Domain engines** (all deterministic, all snapshot their inputs):
  - `app/water/` — daily soil-water balance, NIR/GIR, deficit windows,
    allocation checks.
  - `app/soil/` — soil assessments, nutrient budgets, SOC stocks.
  - `app/rotation/` — CP-SAT rotation optimization with Pareto strategies.
  - `app/management/` — soil-cover timeline, erosion screening, cover-crop
    plans, residue ledger.

## 2. Intelligence Layer — `app/intelligence/`

Turns engine outputs into machine-usable understanding. Read-only over the
data layer.

- **`evidence.py` — evidence packs.** `build_field_evidence(db, field)`
  assembles the latest succeeded run of every domain into one compact
  (< ~4000 chars), provenance-labeled pack: every number keeps its unit and
  its source run id; domains without data become explicit `data_gaps`.
- **`anomaly.py` — statistical anomaly detection.**
  `detect_feature_anomalies(db, field_id)` z-scores each feature series
  against its own history (population σ, ≥ 5 periods, |z| ≥ 1.5) and flags
  sustained trends. Pure statistics, no ML dependencies, baselines never mix
  series.
- **`bridge.py` — LLM bridge client.** Sync `httpx` client for the optional
  bridge mini-service (`POST {CROPTWIST_LLM_BRIDGE_URL}/chat`). Best-effort:
  any failure (disabled, unreachable, timeout, non-200, malformed) returns
  `None` after logging; one retry on connection error only.
- **`advisor.py` — AI agronomist.** `answer_field_question` grounds every
  claim in the evidence pack (the model must cite `[evidence: LABEL]` and
  finish with an `EVIDENCE:` line that is parsed into `evidence_used`).
  `field_brief` produces the 2–3 sentence insights summary.
- **`narrative.py` — recommendation narratives.** ONE bridge call per
  refresh; the model may only expand the given facts into a `narrative`
  field. Defensive parsing; on any failure recommendations are unchanged.
- **`config.py` —** `CROPTWIST_LLM_BRIDGE_URL` (default
  `http://127.0.0.1:3035`), `CROPTWIST_LLM_ENABLED` (default `true`),
  20 s timeout. Same pydantic-settings pattern as the central settings.

## 3. Recommendation Layer — `app/recommendations/`

**The single source of every suggestion in the product.** Climate, water,
soil, rotation and management each contribute generators to one central
registry; nothing else in the codebase emits user-facing advice.

- **`contracts.py`** — `Recommendation` (id, domain, severity, title,
  summary, rationale, evidence, actions, confidence + `confidence_basis`,
  status, `generated_by`, model, narrative) and the severity ladder aligned
  with the knowledge contracts (`advisory < recommended < required`) extended
  by an `info` rung: `info < advisory < recommended < required`.
- **`registry.py`** — generators register via
  `@registry.generator("domain")`; `run_all(db, field)` builds the context
  ONCE (evidence pack + anomalies) and runs every generator inside
  try/except — one generator failing never breaks the refresh.
- **`generators/`** — one module per domain. Each reads the latest engine
  outputs (through the shared context) and emits 0..n recommendations with
  concrete numbers and engine-output citations in `rationale`/`evidence`,
  deterministic confidence (0.5–0.95) and a `confidence_basis` string. A
  domain with NO data emits exactly one INFO "no data yet — run X"
  recommendation, so the system is comprehensive even in the empty state.
- **`service.py`** — `refresh_field_recommendations` (run registry →
  supersede active rows → insert new generation in `ai_recommendations` →
  optional LLM narrative) and `get_field_recommendations` (load-or-refresh).

## 4. API / Presentation Layer

- `app/api/v1/recommendations.py` (mounted under `/api/v1`):
  - `GET  /fields/{id}/recommendations?refresh=false`
  - `POST /fields/{id}/recommendations/refresh`
  - `GET  /fields/{id}/insights` — anomaly findings + LLM field brief
  - `POST /fields/{id}/advisor/query` — grounded Q&A, transcript persisted
    to `ai_advisor_messages`
  - `GET  /fields/{id}/advisor/history?limit=20`
- Frontend consumes the recommendations payload (domains, counts by severity,
  recommendation cards with evidence links, narratives when present) in the
  field view's AI tab. Every endpoint is tenant-scoped via the standard
  field-access guard.

---

## Degradation policy — the LLM is optional, the rules are always on

| Bridge state        | Recommendations | Insights summary | Advisor            |
|---------------------|-----------------|------------------|--------------------|
| reachable + enabled | `rules+llm`     | LLM brief        | LLM answer (grounded) |
| unreachable/disabled/malformed | `rules` | `summary: null` | deterministic evidence summary + top recommendations |

- The bridge client NEVER raises toward callers: any failure returns `None`
  and the caller falls back. One retry, connection errors only, 20 s timeout.
- `CROPTWIST_LLM_ENABLED=false` disables every LLM call globally.
- Refreshes, insights and advisor queries therefore never fail because of the
  LLM — worst case they return the deterministic content alone.

## Honesty contract — the LLM narrates, engines compute

1. The LLM only ever receives the evidence pack / recommendation facts and
   may only attach prose (`narrative`, advisor answers, briefs). It NEVER
   writes numeric fields, severities, confidences or evidence items.
2. Every claim must be citable to an evidence label
   (`[evidence: LABEL]`); missing data must be named as missing; numbers are
   never invented.
3. Rules content (`title`, `summary`, `rationale`, `evidence`, `actions`,
   `confidence`, `confidence_basis`) is fully deterministic: identical engine
   outputs yield identical recommendations. The narrative is the only
   non-deterministic field, and rows carrying one are stamped
   `generated_by: "rules+llm"` with the bridge-reported `model`.
4. Provenance is preserved end to end: recommendations cite the run ids they
   were derived from; advisor answers persist the evidence used and the
   engine mode; superseded recommendation rows are kept, never deleted.
