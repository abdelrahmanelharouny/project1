# AI-2a — Backend AI Layers (Intelligence + Recommendation)

**Task:** FieldShift AI-driven pivot — backend layers for the FastAPI service
(`mini-services/fieldshift-api/`). Status: **COMPLETE**, import-verified.

## What was built

### 1. Intelligence Layer — `app/intelligence/` (new package, 7 files)
- `config.py` — AI settings (pydantic-settings, `FIELDSHIFT_` prefix, reads
  `.env`): `llm_bridge_url` (default `http://127.0.0.1:3035`), `llm_enabled`
  (default true), `llm_timeout_seconds` = 20, `llm_temperature` = 0.3.
- `bridge.py` — sync `httpx` client (all existing endpoints are sync `def`):
  `chat(messages, temperature=0.3) -> str | None` + `chat_detail()` which also
  surfaces the bridge-reported `model`. POST `{base}/chat`, expects
  `{"content": ...}`. ANY failure → warning logged + `None`; exactly one
  retry on connection error. Graceful degradation guaranteed.
- `evidence.py` — `build_field_evidence(db, field)` assembles the latest
  succeeded run per domain (feature run, water plan, soil assessment +
  nutrient budget + SOC stock, rotation run + recommended strategy, cover
  metrics over trailing 365 d via the deterministic M6C engine + erosion run)
  into a compact provenance-labeled pack; domains without data land in
  `data_gaps`. Verified < 4000 chars (356 chars on the empty dev DB).
- `anomaly.py` — `detect_feature_anomalies(db, field_id)`: per-series
  population-σ z-scores over the latest feature run (≥ 5 periods,
  |z| ≥ 1.5 → anomaly; 3-period same-sign shift ≥ 1σ → trend). Pure stdlib
  statistics. Tested with a rolled-back synthetic run (outlier z=2.445
  flagged; flat/short series skipped).
- `advisor.py` — `answer_field_question` (evidence-grounded LLM answer,
  `[evidence: LABEL]` citations, trailing `EVIDENCE:` line parsed into
  `evidence_used`; deterministic rules fallback = evidence summary + top
  active recommendations) and `field_brief` (2–3 sentence insights summary,
  `None` when bridge down).
- `narrative.py` — `enrich_recommendations(db, field, recs)`: ONE bridge
  call, asks for JSON `[{key, narrative}]`, defensive parsing, mutates rows
  in place; on any failure recs unchanged. Returns `{model, enriched_count}`
  meta or None.

### 2. Recommendation Layer — `app/recommendations/` (new package, 9 files)
- `contracts.py` — `Severity` (info < advisory < recommended < required,
  aligned with `app/knowledge/contracts.py` ladder) + `Recommendation`
  pydantic model (exact spec shape) + `evidence_item()` helper + DOMAINS.
- `registry.py` — `RecommendationRegistry` with `@registry.generator(domain)`
  decorator; `run_all(db, field)` builds `RecommendationContext` (evidence +
  anomalies) ONCE and runs every generator in try/except (one failure logs
  and returns [] — never breaks the refresh).
- `generators/` — 19 generators across 5 domains (climate 5, water 3, soil 4,
  rotation 3, management 4). Every domain has a data-gap INFO rec; rules cite
  concrete engine ids/values with confidence 0.5–0.95 + `confidence_basis`:
  - climate: dry spell ≥ 14 d, hot days ≥ 30, precip |z| ≥ 2, statistical
    anomaly advisories, data gap.
  - water: allocation shortfall → REQUIRED (engine 'deficit' status +
    shortfall m³), root-zone stress windows → advisory/recommended timing rec,
    data gap.
  - soil: negative N/P/K cumulative balance → RECOMMENDED with deficit kg/ha,
    low SOC stock (< 30 Mg C/ha screening heuristic, disclosed) → advisory,
    missing indicators / non-evaluable budget → INFO, data gap.
  - rotation: recommended (non-baseline, Pareto, optimal/feasible) strategy →
    RECOMMENDED planting rec per season (cites run + strategy id), unevaluated
    water requirements ≥ 3 → advisory, data gap.
  - management: RUSLE `not_evaluated` → INFO listing missing factors,
    screening concerns > 0 → advisory, protective cover < 50% → cover-crop
    advisory (heuristic disclosed), data gap.
- `service.py` — `refresh_field_recommendations` (registry → supersede active
  rows → insert new generation → optional narrative; rows with narrative get
  `generated_by="rules+llm"` + bridge model) and
  `get_field_recommendations(db, field, refresh)` (load-or-refresh) +
  `get_active_recommendations` (read-only, used by advisor fallback). Payload
  matches the frontend contract exactly (field_id, generated_at, engine{mode,
  model}, domains, counts.by_severity, recommendations[]).

### 3. DB + migration
- `app/db/models_ai.py` — `AIRecommendation` (`ai_recommendations`, TimestampMixin,
  checks on severity/status/confidence, indexes field+status) and
  `AIAdvisorMessage` (`ai_advisor_messages`, append-only, inline created_at,
  role check). Mirrors models.py conventions (UUID(as_uuid=True) + `_uuid`,
  JSONB with python defaults, ForeignKey ondelete CASCADE).
- `migrations/versions/0017_ai_recommendations.py` — same structure as 0016
  (`revision = "0017_ai_recommendations"`, `down_revision = "0016_background_jobs"`,
  both tables in upgrade(), dropped in downgrade()). NOT run (orchestrator's job).

### 4. API — `app/api/v1/recommendations.py` (5 endpoints)
GET /fields/{id}/recommendations?refresh= · POST /fields/{id}/recommendations/refresh ·
GET /fields/{id}/insights · POST /fields/{id}/advisor/query (persists user +
assistant rows; disclaimer text per spec) · GET /fields/{id}/advisor/history?limit=20
(ascending, cap 50). Auth + field guard + session dependencies mirror
features.py exactly. Registered with the exact mount line below.

### 5. Docs + config
- `docs/architecture/AI_LAYERS.md` — 4-layer architecture, degradation
  policy, honesty contract.
- `.env` (fieldshift-api dir; file did not exist, created with the single
  line): `FIELDSHIFT_LLM_BRIDGE_URL=http://127.0.0.1:3035`

## Router mount line (the only edits to existing code)
```python
# in app/api/v1/router.py — import block: added one member
    recommendations,
# and one mount line at the end:
api_router.include_router(recommendations.router)
```

## Verification
- `cd mini-services/fieldshift-api && /home/z/fieldshift-api-venv/bin/python -c "from app.main import app"` → **OK** (181 routes incl. the 5 new ones).
- Read-only tests against the live dev DB: evidence pack (empty-state gaps
  for all 5 domains), `registry.run_all` → 5 INFO data-gap recs, anomaly
  math (rolled-back synthetic run), advisor rules fallback with bridge down.
- Transactional end-to-end tests (DDL + data created inside a transaction,
  then **rolled back** — nothing persisted): refresh → supersede → re-refresh
  (active=5, superseded=5), GET path, payload contract; with a one-shot
  in-process mock bridge: `engine.mode="rules+llm"`, model="glm-4.6",
  narratives attached, advisor `evidence_used` parsed from EVIDENCE line,
  field brief mode "llm". All mock servers were in-process and died with the
  one-shot command — **no background processes remain**.

## Deviations from spec (all minor, all intentional)
1. `ai_recommendations` has an extra nullable `narrative` TEXT column — the
   spec's payload contract requires `narrative` on loaded rows; without the
   column narratives would vanish on the next GET. (Model column list in the
   spec omitted it; the Recommendation contract includes it.)
2. `enrich_recommendations(db, field, recs)` takes the `field` object (not
   `field_id`) — consistent with `build_field_evidence(db, field)`; avoids a
   redundant query.
3. Advisor fallback reads active recommendations via
   `get_active_recommendations` (read-only SELECT) instead of
   `get_field_recommendations(refresh=False)` — prevents an advisor query
   from triggering surprise writes when no generation exists yet.
4. `chat_detail()` added alongside spec-exact `chat()` so `engine.model` /
   `generated_by` can carry the bridge-reported model name.
5. The evidence pack's `field.profile` is implemented as the farm context
   (farm name, country, timezone, unit system, boundary version) + `year` =
   latest data year — the Field row has no profile/year attributes; this is
   the honest, useful reading.
6. Rotation "excluded candidates" are not persisted by the engine (they are
   computed at run time), so the evidence/generator use the persisted
   `not_evaluated` ledger (crop-season pairs with unevaluated dimensions,
   incl. `water_requirement`) and label it honestly instead of fabricating
   exclusion counts.
7. `.env` did not exist in the fieldshift-api dir, so it was created
   containing exactly the one required line (nothing was overwritten).

## Notes for other agents
- Frontend payload shape: `{"field_id", "generated_at", "engine": {"mode",
  "model"}, "domains": [...], "counts": {"total", "by_severity": {...}},
  "recommendations": [{"id","domain","severity","title","summary",
  "rationale","evidence":[{type,id,label,detail}],"actions","confidence",
  "confidence_basis","status","generated_by","model"?,"narrative",
  "created_at"}]}` — recommendations sorted severity-desc then domain order.
- Engine modes: recommendations payload `rules` | `rules+llm`; insights/advisor
  `llm` | `rules`.
- The bridge contract my layer expects: `POST {FIELDSHIFT_LLM_BRIDGE_URL}/chat`
  with `{"messages":[{role,content}...], "temperature":0.3}` →
  `{"content": "...", "model"?: "..."}` (AI-2b's service on port 3035).
- Until migration 0017 runs, the 5 new endpoints will 500 on the
  `ai_recommendations` lookup — the orchestrator runs alembic.
