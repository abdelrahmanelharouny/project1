# M6C — Erosion Screening & Model Scope (as-built, Increment 6)

**Status:** implemented and tested (`test_erosion_screening.py` — 15 unit
tests; `test_erosion_api.py` — 7 integration tests).

## 1. Process taxonomy (stored, explicit)

`sheet_interrill · rill · ephemeral_gully · classical_gully · wind ·
streambank · sediment_delivery` (`app.management.erosion.EROSION_PROCESSES`).
Every result names what it speaks to; every process NOT covered is listed in
`not_evaluated.processes` with the scope-boundary message. The RUSLE-family
pathway declares exactly `{sheet_interrill, rill}` — tested.

## 2. Qualitative screening (`screening_only`)

Evidence-of-concern flags, each carrying the evidence text + evidence class:

| Concern | Raised by | Processes |
|---|---|---|
| `exposed_soil_days` | soil-cover engine metrics (known-bare days / longest bare interval) — reused, not recomputed | sheet_interrill, wind |
| `slope_class_evidence` | farmer/sourced slope class (moderate/steep) | sheet_interrill, rill, ephemeral_gully |
| `soil_erodibility_evidence` | supplied soil evidence flag | sheet_interrill, rill |
| `rainfall_amount_evidence` | wettest-month climatology — explicitly "NOT an erosivity (R) factor and implies no R value" | sheet_interrill, rill |
| `management_*` | ledger events (residue removal, tillage) with dates | per flag |

Unknowns are first-class (no slope evidence / no cover metrics / no rainfall /
no known-bare days may mean missing observations — stated). Observed erosion
signs (farmer-reported) are kept in `field_observed_signs`, structurally
separate from concerns. The response separates: susceptibility evidence ·
model estimates · observed signs · unknown status (spec §7.4, tested).

## 3. RUSLE-family pathway (conditional by construction)

`A = R·K·LS·C·P` computes **only** when all five factors arrive with
`value + source_reference + region_scope + unit_convention`. Enforced:

- any missing factor → `not_evaluated` with the factors NAMED; a partial
  product is impossible (property: no `annual_soil_loss_a` key without all
  five — tested at unit and API level);
- unsourced provenance → refusal;
- mixed unit conventions (e.g. metric_si R with us_customary K) → refusal
  ("factor values from incompatible unit systems are never combined");
- the platform ships NO factor values: the no-factors message contains no
  numbers at all (regex-tested) and US NRCS databases are not wired as
  defaults anywhere;
- computed results carry `assessment_kind: "screening_only"` and scope
  disclosures: sheet/rill only; NOT sediment yield; no deposition/delivery
  ratio; LS must be supplied (the platform has **no DEM** — slope length is
  never derived from the field polygon, tested);
- golden hand-computed case: R=100, K=0.25, LS=1.0, C=0.3, P=0.5 →
  **A = 3.75** in the declared convention's native unit (the platform does
  not convert conventions).

## 4. Conservation alternatives

Drawn from the ACTIVE practice pack (erosion_control / cover_crop / residue /
tillage families), each alternative keeps its **cited** mechanisms (with
resolved citations) and trade-offs, and carries a standing note: quantitative
evaluation requires model parameters with local applicability (e.g. regional
support-practice P values) — none are bundled, so **no effectiveness number
and no ranking is ever produced** (tested). Practices outside the erosion
families are excluded from this view.

## 5. API

- `POST /fields/{id}/erosion-assessments` — immutable snapshot
  (engine/methods versions, sha256 checksum, idempotency key; same inputs →
  identical checksum, tested); cover metrics are computed internally over the
  requested window from the Increment-3 engine (cross-module).
- `GET /fields/{id}/erosion-assessments`, `GET /erosion-assessments/{run_id}`
  (cross-tenant 403, tested).
- `GET /fields/{id}/erosion-readiness` — honest data readiness: what the
  screening can use today, what the RUSLE pathway would need (factors with
  provenance + LS supplied — no DEM), and the out-of-scope process list.

## 6. Scope boundaries (documented, not attempted)

No DEM ingestion, no erosivity (R) computation from rainfall amounts, no
ephemeral/classical gully model, no wind-erosion quantitative model (taxonomy
slot reserved), no sediment delivery. These appear only as
`not_evaluated`/readiness statements.
