# M6B — Test & Benchmark Report

**Status:** implemented (as-built)
**Suite:** 125 soil tests inside a 566-test backend suite, all passing
(collected counts re-verified against the repository before this report was
written).
**Golden-benchmark rule:** expected values are INDEPENDENT hand calculations or
authoritative worked examples — never outputs of the function under test.

---

## 1. Test inventory

| File | Class of coverage | Tests |
|---|---|---|
| `tests/unit/test_soil_core.py` | depths, texture, porosity, AWC, chemistry, SOC, nutrients, versions | 73 |
| `tests/unit/test_soil_assessment.py` | domains, comparability gate, trends, VOI, checksum | 14 |
| `tests/unit/test_soil_import.py` | CSV parsing, rejections, mapping contract, idempotency | 15 |
| `tests/integration/test_soil_api.py` | HTTP flows, method enforcement, run snapshots, tenant isolation | 23 |
| **Total** | | **125** |

## 2. Golden benchmarks (independent derivations)

| Benchmark | Input | Expected (hand derivation) | Where |
|---|---|---|---|
| USDA corners | 100/0/0; 0/100/–; 0/100 silt | `sand`, `clay`, `silt` (triangle vertices P25, P24, P26) | core |
| Wikipedia worked example | sand 70 %, clay 10 % (silt derived 20) | `sandy loam`, `silt_basis=derived_silt_100_minus_sand_clay` | core |
| Triangle centre | 33/34/33 | `clay loam`, silt basis `measured` | core |
| soiltexture USDA.TT edge midpoint | sand 75, silt 25, clay 0 (edge P20–P21) | `loamy sand` (boundary points transcribed against the package polygon table) | core |
| Sand interior | 90/8/2 | `sand` | core |
| Boundary determinism | P20 (85/15/0) shared vertex | same class on repeated classification (inclusive edges) | core |
| Depth-weighted mean | (0–10, 0.10), (10–30, 0.20) | (0.10·10 + 0.20·20)/30 = 5/30 | core |
| Porosity | BD 1.33, PD assumed | n = 1 − 1.33/2.65 = 0.4981, `assumed_pd` + disclosure | core |
| Layer AWC | θFC 0.32, θWP 0.15, 0–30 cm | AWC 0.17; mm = 0.17 × 30 × 10 = 51.0 | core |
| SOC layer (whole-soil) | OC 20 g/kg, BD 1.3, vCF 0.1, 0–20 cm | 20 × 1.3 × 0.9 × 20 × 0.1 = **46.8 Mg C/ha** | core + HTTP |
| SOC layer (fine-earth) | OC 15, BD 1.25, 0–10 cm | 15 × 1.25 × 1 × 10 × 0.1 = **18.75 Mg C/ha** | core |
| SOC profile total | 0–10 (OC 20, BD 1.2) + 10–30 (OC 10, BD 1.3) | 24 + 26 = **50.0 Mg C/ha**, contiguous | core |
| SOC profile with gap | 0–10 (24) + 30–60 (39) | total 63.0 labelled non-contiguous, gap warning | core |
| FD comparison, BD change | baseline 0–10 OC20/BD1.4 (28) vs follow-up OC20/BD1.2 (24) | Δ −4.0 + "mass redistribution" caveat | core + HTTP |
| ESM, same single layer | masses 1400 vs 1200 Mg/ha | Δ 0.0 at reference mass 1200 (ESM removes the BD artefact) | core |
| ESM two-layer scenario | baseline OC20/BD1.4 (0–10) + OC10/BD1.3 (10–30); follow-up BD 1.2/1.25 | target mass 1200+2500 = 3700; baseline stock at 3700 = 28 + (3700−1400)/2600 × 26 = **51.0**; follow-up 49.0; **Δ −2.0** (fixed depth would read −5.0: 49 − 54; derived from the same hand numbers) | core |
| P₂O₅ stoichiometry | 100 kg P₂O₅ | × 2·M(P)/M(P₂O₅) = 0.43642712…, constants recomputed in the test from IUPAC 2021 weights (rel tol 1e-12) | core |
| K₂O stoichiometry + round trip | 100 kg K₂O; 42 kg round trips | exact reciprocal identity | core |
| Budget normalization | 46 kg N on 2 ha; removal 18 kg/ha | inputs 23 kg/ha; balance +5; overall `partial` | core |
| Oxide grade | 40 kg P₂O₅/ha | 40 × 0.4364271 = 17.4571 kg P/ha (engine rounds 6 dp) | core |
| Manure availability | 50 kg N, fraction 0.4 | 20 kg N/ha counted; without fraction → EXCLUDED + warning, inputs 0 | core |
| BNF estimate | 100 kg N midpoint | counted, `is_estimate=true`, "estimated input" note | core |
| NUE | 60 out / 100 in | 0.6, definition "output/input ratio (partial-factor productivity)" | core |
| Cumulative seasons | s1 (+10) + empty s2 | 1 evaluable, s2 skipped by label, N total 10.0 | core |

## 3. Honesty/property tests (selection)

- **Depth:** unknown units, inverted intervals, negative tops, > 300 cm refused;
  original unit preserved through mm/m conversion; overlaps detected with exact
  overlap_cm; gaps with gap_cm; weighted mean refuses overlapping intervals.
- **Texture:** inconsistent three-fraction sums (> 100 ± 0.5) refused; negative
  derived silt refused; percentage and g/kg groups mutually exclusive.
- **Porosity/AWC:** BD ≥ 2.65 refused; unknown BD basis refused; θWP ≥ θFC
  refused; profile AWC returns None with "refused" reason on overlaps and labels
  gaps "NOT interpolated".
- **Chemistry:** pH without medium refused; pH > 14 refused; water vs CaCl₂
  series not comparable; ECe classes at 1.5/3.0/5.0/10.0 match Table 4 bands;
  cross-ratio EC comparison refused.
- **SOC:** missing OC / missing BD / missing basis / whole-soil-without-vCF /
  fine-earth-with-vCF each produce the specific refusal text (never zero stocks);
  overlapping profile refused (`SocStockError`); prediction layers flagged;
  ESM refused without BD and when follow-up mass exceeds baseline; FD refused on
  disjoint support.
- **Nutrients:** removal without concentration → `not_evaluable` + missing-flow
  entry; loss flows leaching/denitrification/volatilization each appear as "NOT
  assumed zero"; interpretation disclaims stock change; negative masses refused.
- **Versions:** all six version constants asserted; checksum reproducibility
  (SOC and assessment) — identical inputs → identical 64-hex digest.

## 4. CSV import coverage (15 tests)

Parsing/report counts on the canonical fixture (5 rows: pH, OC, below-detection
P `<2.0`, sand in %, EC marked NA); below-detection semantics (`value=None`,
qualifier `<`, limit 2.0); `%`→`g/kg` (55 % → 550 g/kg); missing-value recording
(never zero); depth preservation; idempotency key = file checksum prefix.
Rejections: unknown variable, inverted depths (2 rows), duplicate natural key,
undeclared unit ("furlongs"), unparseable date. Mapping contract: built-in
template, custom columns (`Lab No` → sample_code …), missing required target
refused, unknown target refused.

## 5. Integration coverage (23 tests, HTTP level)

- **Sampling domain:** event→sample→composite-core linking; GPS validation 422;
  cross-tenant profile access 403.
- **Method enforcement (ADR-0023):** pH without method metadata 422; pH with
  method descriptor 201 (`method_params.code` echoed); bulk density accepted
  with `bd_basis` method params (BD needs no registry method); unknown variable
  422; `soilgrids_profile` + measured evidence class 422.
- **Profile:** 0–5 + 15–30 measurements ⇒ gap 5–15 (10.0 cm) reported; texture
  derived over HTTP (700/100 g/kg → sandy loam, silt derivation disclosed).
- **SOC runs:** golden 46.8 Mg C/ha over HTTP with checksum; missing BD ⇒
  `profile_total` None + `not_evaluated` listed; FD comparison flow (Δ −4.0 +
  caveat); idempotency (same key → same run id); run-detail tenant isolation 403.
- **Nutrient budget:** urea 46 % × 100 kg → 46 kg N; DAP oxide grade keeps the
  declared P₂O₅ form (23 kg) and the engine converts (P inputs = 23 × 0.4364271
  = 10.0378 kg/ha; the test asserts against the label constant with rel tol 1e-4);
  N balance 55 in / 14 out / +41, overall `partial`; manure without availability
  422; removal without concentration 422.
- **Lab import:** multipart round trip (2 measurements created, report counts,
  profile contains the pH row).
- **Assessment & readiness:** snapshot + checksum stability across GET;
  `soil-health` served from snapshot; readiness ranking lists EC and every
  priority carries a decision statement.
- **Ledger:** tillage event round trip; unknown event_type 422.

## 6. Reproducing

```
cd mini-services/fieldshift-api
.venv/bin/python -m pytest tests/unit/test_soil_core.py \
    tests/unit/test_soil_assessment.py tests/unit/test_soil_import.py \
    tests/integration/test_soil_api.py          # 125 passed
.venv/bin/python -m pytest tests/                # 566 passed (full suite)
```
