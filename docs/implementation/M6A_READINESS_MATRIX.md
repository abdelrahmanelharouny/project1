# M6A — Crop-by-Crop Water-Knowledge Readiness Matrix

**Milestone:** M6A Advanced Water Intelligence Engine — Phase 0 deliverable
**Date:** 2026-10-31 · **Baseline verified:** 343/343 backend tests passing; API :3030 healthy; frontend :3000 serving.
**Method:** every row below was checked against the actual repository state
(`app/knowledge/packs/seed_pack_v1.py`, `app/rotation/candidates.py`, feature
catalog `featurespec-2026.11.1-d1`, migrations 0001–0005) and, for external
values, against the cited primary sources (FAO-56 chapters 6 & 8; FAO I&D
Paper 33 ch. 4; FAO Training Manual 1 Annex I) fetched during this phase —
never from memory.

## Status vocabulary

- **Complete & source-backed** — all parameters needed for that capability are
  present with citation, unit, evidence class and confidence.
- **Partially documented** — enough for a screening-level calculation with
  disclosed assumptions; named parameters are missing.
- **Missing** — deliberately absent; the capability stays unevaluated
  (never guessed).
- **Not locally validated** — values exist but carry
  `validation_status="reference"`; hard agronomic claims are blocked until the
  agronomist review workflow upgrades them.
- **Not applicable** — the parameter does not apply to the crop/method.

## 1. Crop-level water knowledge (seed pack `kp-seed-2026.11.0`)

| Crop | Kc anchors (ini/mid/end, FAO-56 T12) | Stage lengths (T11) | Root depth Zr (T22) | Depletion fraction p (T22) | Stress sensitivity (Ks basis) | Readiness |
|---|---|---|---|---|---|---|
| maize | 0.30/1.20/0.60 ✅ (end 0.60 = high-moisture-harvest endpoint of 0.60–0.35 range) | 20/40/50/30 — close to T11 rows (Nigeria 20/35/40/30; Spain 30/40/50/30); declared "typical", not a verbatim row | 1.0–1.7 m ✅ matches T22 | **absent** → added in pack v2026.11.1 (p=0.55) | Partial | **Partially documented** — complete enough for single-Kc ETc + seasonal planning; p added in v2026.11.1 |
| wheat_spring | 0.30/1.15/0.35 ✅ (0.35 inside T12 range 0.25–0.40, dry-down) | 20/25/60/30 ✅ exact T11 row (Barley/Oats/Wheat, Mar/Apr 35–45°L) | 1.0–1.5 m ✅ | **absent** → v2026.11.1 (p=0.55) | Partial | **Partially documented** (same terms) |
| barley | 0.30/1.15/0.25 ✅ exact | 15/25/50/30 ✅ exact T11 row (Nov, Central India) | 1.0–1.2 m ⚠️ **discrepancy** — T22 prints 1.0–1.5 | absent → v2026.11.1 (p=0.55) + Zr corrected | Partial | **Partially documented**; Zr transcription error found by verification, corrected in v2026.11.1 |
| potato | 0.50/1.15/0.75 ✅ exact | 25/30/45/30 ✅ exact T11 row (May, Continental) | 0.4–0.6 m ✅ | absent → v2026.11.1 (p=0.35) | Partial | **Partially documented** |
| soybean | 0.40/1.15/0.50 ✅ exact | 20/35/40/25 — T11 Central-USA row prints 20/30–35/60/25; pack mid=40 is a typical-value choice | 0.6–1.3 m ✅ | absent → v2026.11.1 (p=0.50) | Partial | **Partially documented** |
| dry_bean | 0.40/1.15/0.35 ✅ exact | 20/30/40/20 ✅ exact T11 row (May/June Continental) | 0.6–1.2 m ⚠️ — T22 "Beans, dry and Pulses" prints 0.6–0.9 | absent → v2026.11.1 (p=0.45) + Zr corrected | Partial | **Partially documented**; Zr discrepancy corrected in v2026.11.1 |
| faba_bean | **none — deliberate gap** (no defensible transcription; stays unevaluated) | none (only EcoCrop duration range 110–150 d) | absent → v2026.11.1 adds Zr 0.5–0.7 m + p 0.45 from T22 ("Fababean, Dry/Seed") — **no Kc is added** | added (T22) | Partial (no ETc possible without Kc) | **Missing for ETc** (honest); Zr/p now documented for the moment Kc evidence arrives |
| sunflower | 0.35/1.15/0.35 ✅ (mid 1.15 = upper endpoint of T12 range 1.0–1.15) | 25/35/45/30 — T11 row prints late=25; pack 30 is a typical-value choice | 0.8–1.5 m ✅ | absent → v2026.11.1 (p=0.45) | Partial | **Partially documented** |
| cotton | 0.35/1.18/0.50 ⚠️ mid 1.18 lies inside T12 range 1.15–1.20 but is not a printed endpoint (documented choice); end 0.50 = dry-harvest endpoint | 30/50/55/45 ✅ exact T11 row (April) | 0.6–1.8 m ⚠️ — T22 prints 1.0–1.7 | absent → v2026.11.1 (p=0.65) + Zr corrected | Partial | **Partially documented**; Zr discrepancy corrected in v2026.11.1 |
| tomato | 0.60/1.15/0.80 ✅ (end 0.80 = midpoint of T12 range 0.70–0.90; disclosed) | 30/40/40/25 ✅ exact T11 row (Jan, Arid) | 0.7–1.5 m ✅ | absent → v2026.11.1 (p=0.40) | Partial | **Partially documented** |
| onion | 0.70/1.05/0.75 ✅ exact | 15/25/70/40 ✅ exact T11 row (Apr, Mediterranean) | 0.3–0.6 m ✅ | absent → v2026.11.1 (p=0.30) | Partial | **Partially documented** |

**All 11 crops are `validation_status="reference"` — none is locally
validated or regionally confirmed.** Water figures are therefore screening
estimates with the "≈ + assumptions" contract, never agronomic guarantees.

## 2. Environmental evidence readiness (feature run inputs)

| Input | State | Provider / feature | Readiness |
|---|---|---|---|
| Reference ET0 (daily/monthly) | **Present** (daily ingested; monthly total feature exists; daily total + seasonal + crop-season totals added in M6A) | ERA5 product, `reanalysis_model_estimate`, coverage floor 0.90 | **Complete & source-backed** (provider-computed FAO-56 reference surface). No local ET0 *computation* exists — deliberately (see design §ET0). |
| Precipitation (daily/monthly/seasonal/crop-season) | Present | ERA5 / CHIRPS v2 (area-weighted), `satellite_derived_estimate` for CHIRPS | **Complete & source-backed** |
| Mean/max temperature | Present | ERA5-Land / ERA5 | **Complete** (needed for future Hargreaves fallback — not implemented, backlog W-6) |
| Root-zone soil water holding (θFC, θWP) | **Missing everywhere** | — | **Missing** → three honest sources in M6A: farmer/lab measurement; cited PTF (Saxton & Rawls 2006, verified coefficients) over SoilGrids texture **with explicit "texture assumed uniform across root zone" disclosure**; or absent → FAO-33 no-storage fallback |
| Root-zone soil moisture | **Not represented** (ERA5-Land is 0–7 cm surface only) | soil_moisture_surface | **Not applicable for root-zone balance** — M6A never feeds surface moisture into a root-zone storage claim (deepening rule) |
| Deep drainage / capillary rise | **Not represented** | — | **Missing** — terms documented as zero only when the balance is explicitly run in "simplified FAO-33 mode" (disclosed) |
| Irrigation application efficiency | **Missing by default** | farmer-supplied (0–1) or method class | FAO TM1 Annex I Table 8 verified: surface 60% / sprinkler 75% / drip 90% (indicative) — offered as labelled reference values, farmer value wins |
| Water allocation | Farmer constraint `water_allocation_m3_per_season` or run payload | `farmer_reported_record` | **Complete** (never inferred when absent) |
| Actual irrigation applied | **Missing** (no farmer irrigation records ingestion yet) | — | **Missing** — plan reports "actual applied: unknown"; no fake compliance claims |

## 3. Methodology readiness (verified during Phase 0)

| Method | Status | Verified source |
|---|---|---|
| ETc = Kc × ET0 (single Kc, 3-anchor curve) | Implemented (ADR-0017) | FAO-56 ch. 6 (Tables 11/12, curve construction) |
| Dual Kc (Kcb + Ke) | **Not implemented — refused** (no Kcb evidence in pack; accepted in schema only) | FAO-56 ch. 7 (machinery documented, inputs absent) |
| Effective rainfall `fao_aglw_1986`: Pe = 0.8P−25 (P>75 mm/mo); 0.6P−10 (P<75) | **Verified this phase** incl. 6 worked-example values (35→11, 90→47, 116→68, 5→0, 260→183, 75→35) | FAO I&D Paper 33 (Brouwer & Heibloem 1986) §4.2 |
| Effective rainfall `constant_fraction` | Implemented (parameterized, farmer/region-supplied fraction) | generic; requires explicit fraction |
| USDA-SCS effective rainfall | **NOT implemented** (coefficients could not be verified verbatim from the primary source in this phase) | backlog W-5 |
| p adjustment p = p_T22 + 0.04·(5 − ETc) | **Verified** | FAO-56 ch. 8, Table 22 footnote 2 |
| Root-zone balance TAW/RAW/Dr/Ks | Implemented in M6A (requires soil inputs) | FAO-56 ch. 8 (Eq. 82–84 context) |
| PTF θFC/θWP from sand/clay/OM | Implemented in M6A with **verified coefficients** (cross-checked in two independent sources; validity domain enforced) | Saxton & Rawls 2006, SSSAJ 70:1569–1578 |
| Application efficiency classes | Verified | FAO TM1 (Brouwer, Goffeau & Heibloem 1985) Annex I Tables 7–8 |
| Scheme efficiency e = ec × ea | Verified (same source) | FAO TM1 Annex I |
| Seasonal need IN = ETc − Pe (no soil storage) | Verified incl. 5-month worked example (IN 67/110/166/195/180) | FAO I&D 33 §4.3 |

## 4. Known transcription findings (found by Phase 0 verification)

1. **barley** root depth: pack 1.0–1.2 m vs FAO-56 T22 1.0–1.5 m.
2. **dry_bean** root depth: pack 0.6–1.2 m vs T22 0.6–0.9 m.
3. **cotton** root depth: pack 0.6–1.8 m vs T22 1.0–1.7 m.
4. Stage lengths for maize/soybean/sunflower are *typical-value* choices near
   (not verbatim rows of) Table 11 — consistent with the pack's declared
   "typical values" note; retained and disclosed.
5. cotton Kc_mid = 1.18 is a within-range choice (T12 range 1.15–1.20),
   documented in the pack notes.

All five findings are carried into seed pack `kp-seed-2026.11.1` (M6A):
findings 1–3 corrected against the verified primary source; 4–5 explicitly
disclosed. Values remain `reference` — the agronomist review workflow (M-4)
is still the only path to confirmed status.

## 5. What M6A will NOT do (honest boundaries carried forward)

- No local ET0 computation (no radiation/humidity evidence contract; ERA5 ET0
  is the FAO-56 reference surface) — backlog W-6.
- No dual-Kc estimation (no Kcb rows).
- No USDA-SCS Pe formula (unverified coefficients) — backlog W-5.
- No root-zone storage claims from surface soil moisture.
- No irrigation scheduling (daily gap-filling recommendations) — that is a
  different decision product from seasonal planning; backlog W-7.
- No invented water-allocation values (allocation absent ⇒ "unknown", never
  unlimited).
