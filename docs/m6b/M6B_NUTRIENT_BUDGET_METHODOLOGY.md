# M6B — Nutrient Budget Methodology (`nutrient-budget-1.0.0`)

**Status:** implemented (as-built)
**Code:** `app/soil/nutrients.py` (pure engine), `app/api/v1/soil.py`
(products / applications / removals / budget runs).
**ADR:** ADR-0025 (budgets partial by default; versioned oxide conversions).

---

## 1. Budget structure

Per season and per nutrient (N, P, K):

```
balance_kg_ha = Σ documented inputs − Σ documented outputs      [kg/ha]
```

- Input records carry TOTAL element masses (kg over the application) + `area_ha`;
  the engine normalizes to kg/ha. Output records arrive already as kg/ha.
- Every flow carries its `evidence_class`; outputs additionally carry a
  concentration basis; estimates carry `is_estimate=True`.
- Classification: `partial` (at least one usable documented flow) or
  `not_evaluable` (no usable flow on either side). **`complete` is reserved for a
  future full-accounting mode** — in M6B every balance is partial by definition
  because loss flows are never known (§5).

## 2. Input kinds and the availability-fraction rule

Eight CHECK-constrained input kinds: `fertilizer`, `manure`, `compost`,
`organic_amendment`, `biological_nitrogen_fixation`, `atmospheric_deposition`,
`irrigation_water`, `other`.

- **Manure / compost / organic amendments REQUIRE an explicit
  `availability_fraction` ∈ (0, 1]** (with optional `availability_basis`):
  - the API refuses the write without it (HTTP 422: "never assumed fully
    available");
  - the engine independently excludes any such record lacking the fraction,
    warning that the flow is EXCLUDED from the balance and listing the missing
    availability in `missing_flows`.
- Applied masses with a fraction are scaled per nutrient and the scaling is
  recorded on the flow row (e.g. `"× availability 0.4"`).
- Oxide-basis records: P/K masses declared as P₂O₅/K₂O are converted through the
  versioned stoichiometric functions (§6) before normalization to kg/ha.
- Records carrying no nutrient content at all are not counted and are listed in
  `missing_flows` ("nutrient content missing").

## 3. BNF discipline

Biological nitrogen fixation enters a budget ONLY as a recorded estimate row
(`input_kind='biological_nitrogen_fixation'`, `is_estimate=True` set by the run
path, `citation_text` carried from the record's source reference). The engine
never infers BNF from `is_legume`, and the M6B run path does not automatically
pull knowledge-pack traits; the pack's `n_fixation_capacity_kg_ha` ranges
(Herridge, Peoples & Boddey 2008; confidence **low**, declared
order-of-magnitude) remain the reference a farmer may enter from, keeping the
estimate label. Estimate rows are annotated "estimated input (documented method,
not a measurement)".

## 4. Removal (output) discipline

Output kinds: `harvested_product` | `crop_residue` | `other_biomass` (CHECK).

- **Concentration is mandatory**: removal = biomass × concentration; yield alone
  is NEVER a removal estimate. The API refuses a removal row without at least one
  of `n/p/k_concentration_g_kg` (HTTP 422: "yield alone is never a removal
  estimate"); the engine likewise refuses to count a concentration-less output
  and lists it as missing.
- Arithmetic: `kg/ha = concentration [g/kg] × biomass [kg] ÷ 1000 ÷ area [ha]`
  (area from the run request or the field record).
- **Moisture basis is explicit**: `moisture_basis` ∈ (`as_harvested`,
  `dry_matter`, CHECK); `concentration_basis` defaults to the moisture basis;
  an undisclosed moisture basis produces a warning. Dry-matter vs as-harvested
  is recorded on both sides of the balance.
- **The nutrient-removal reference library is intentionally EMPTY** pending
  verified sources; every budget run result carries the note that concentrations
  come from farmer/lab records only (see `M6B_RESEARCH_BACKLOG.md`).

## 5. Loss-flow honesty

The flows `leaching`, `denitrification`, `volatilization`, `erosion_losses`,
`runoff` are NEVER assumed zero. Every budget lists each of them in
`missing_flows` as "loss flow '…': not measured — NOT assumed zero". Their
absence is exactly why no M6B balance is classified `complete`, and the result's
interpretation note states that "a nutrient balance is an ACCOUNTING statement
over documented flows — it is not a measured soil stock change (no soil-sampling
evidence enters this number)".

## 6. Oxide ⇄ elemental conversions (`oxide-conversion-1.0.0`)

Exact stoichiometric identities, versioned functions — never ad-hoc factors:

| Conversion | Derivation | Factor (evaluated) |
|---|---|---|
| P₂O₅ → P | × 2·M(P) / M(P₂O₅) = 61.9476 / 141.9426 | 0.43642712 |
| K₂O → K | × 2·M(K) / M(K₂O) = 78.1966 / 94.1956 | 0.83015130 |
| P → P₂O₅, K → K₂O | reciprocals of the above | 2.29133332 / 1.20459969 |

Molecular weights: P 30.9738, K 39.0983, O 15.999 g/mol — IUPAC 2021 standard
atomic weights; the derivation ships with the functions and with
`GET /api/v1/soil/methods` (which returns the evaluated factors
`0.43642712` / `0.8301513`). Note: the module's disclosure string prints the
rounded labels "×0.436421 / ×0.830127"; the actual versioned constants — and the
values the methods endpoint exposes — are the evaluated figures above. Negative
or non-finite masses are refused. The conversion round-trips exactly
(property-tested).

## 7. NUE scope

Only the explicit output/input ratio is computed, labelled with its definition:
`"output/input ratio (partial-factor productivity)"`. It is produced per nutrient
only when the input is positive and the output is evaluable. Agronomic efficiency
and apparent recovery fraction need control treatments the platform does not
have — they are refused with that reason rather than faked. The ratio is one
explicit definition among several in the literature and is never presented as a
generic "efficiency".

## 8. Multi-season budgets

`POST /fields/{id}/nutrient-budget-runs` takes a list of season labels; per
season the run collects that season's applications/removals and evaluates a
budget; `cumulative_budget` then sums `balance_kg_ha` over **evaluable seasons
only**, listing skipped (`not_evaluable`) seasons by label — never zero-filled
(the water-engine rotation-total pattern). The run snapshot stores the seasons,
per-season results, cumulative block, aggregated warnings, a
`not_evaluated` map (season → missing flows) and the sha256 checksum over
`{engine, methods, balance, inputs, outputs}`.

## 9. Golden arithmetic (verified by tests)

- 46 kg N (urea content) on 2 ha → 23 kg N/ha; with 18 kg/ha removal the balance
  is +5 kg/ha, overall `partial`.
- Oxide grade: 40 kg P₂O₅/ha → 17.4571 kg P/ha (× 0.4364271); API scenario:
  DAP 18-46-0, 50 kg product → 23 kg P₂O₅ → P inputs 23 × 0.4364271 = 10.0378 kg/ha.
- Manure 50 kg N with availability 0.4 → 20 kg N/ha counted; without the
  fraction → excluded from inputs (balance shows removal only) + warning.
- NUE: 60 kg output / 100 kg input → 0.6, definition-labelled.
