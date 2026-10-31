# SOIL_SCIENCE_METHODOLOGY.md — Phase E

## 1. Soil ontology — what the system represents today

| Property group | Represented | Source | Unit / form | Not represented (and honest about it) |
|---|---|---|---|---|
| Physical | texture fractions: sand, clay | SoilGrids (0–5 cm, prediction) | g/kg, concentration | silt (derivable), bulk density yes (g/cm³), porosity, compaction, structure, infiltration |
| Chemical | pH, organic carbon | SoilGrids + farmer/lab rows | pH; g/kg **concentration** | EC, total N, available P, exchangeable K, CEC, salinity/sodicity |
| Biological | — | — | — | microbial activity, BNF (soil side), SOM decomposition, biodiversity — no data surface yet |
| Hydrological | surface soil moisture | ERA5-Land 0–7 cm (reanalysis) | m³/m³ volumetric | field capacity, PWP, Ksat, root-zone moisture, deep drainage |

`SoilEvidence` carries (value, evidence_class) pairs; the candidate evaluator
shows the evidence class in its reason text ("a 0–5 cm model prediction is
not a lab measurement").

## 2. Method distinctions (enforced semantics)

1. **pH methods are not silently comparable.** Farmer/lab pH (e.g. 1:2.5
   suspension vs saturated paste) and SoilGrids predicted pH arrive with
   different evidence classes and are never merged into one series; the
   passport groups by (variable, product). The platform does not convert
   between pH scales (no defensible general conversion exists) — comparing a
   crop pH optimum against a predicted-pH value is labelled as a screening
   comparison, pending local lab calibration (backlog S-3).
2. **EC of saturation paste extract vs other procedures**: the platform has NO
   EC ingestion today; when it arrives, the measurement procedure MUST be part
   of the variable metadata (the variable catalog already reserves an
   evidence/conditions pattern for this) — recorded as a hard requirement in
   backlog S-4 before any EC rows are accepted.
3. **Concentration vs stock (SOC)**: stored values are concentrations (g/kg).
   A stock (t/ha) needs layer thickness × bulk density × (1 − coarse
   fraction) × concentration with explicit spatial assumptions — none of the
   required layers (coarse fragments) are ingested and NO stock is computed
   or displayed anywhere. Root-zone profiles are NOT derived from the single
   0–5 cm layer.
4. **Volumetric vs gravimetric**: soil moisture is volumetric (m³/m³) from
   reanalysis; if gravimetric lab data arrives later it must enter as a
   distinct variable (unit-differentiated), never converted silently.
5. **Prediction vs measurement uncertainty**: SoilGrids uncertainty is the
   honest mean-of-pixel-quantile half-width (F-08 label); lab rows would carry
   measurement metadata. The two are never blended.
6. **Depth comparability**: 0–5 cm (SoilGrids) vs 0–7 cm class (ERA5-Land
   moisture) vs arbitrary farmer sampling depths are distinct rows with
   distinct evidence classes; cross-depth comparisons are not computed.

## 3. Evaluation consequences (what the rotation engine does with soil data)

- pH outside the sourced optimum → `conditionally_eligible` with citation and
  evidence class (never silent exclusion; never ignored when present).
- Missing soil data → `soil_ph` dimension explicitly "not evaluated"
  (missing ≠ zero).
- SoilGrids values feed no hidden model: only the pH comparison consumes soil
  evidence today; SOC/texture are stored and displayed, reserved for the
  soil-health engine (later milestone).
- If soil properties are unavailable, the candidate reasons list exactly
  which indicators could not be evaluated (exit criterion: explicit
  identification of non-evaluable indicators).

## 4. Backlog pointers

S-1 field-level prediction intervals (spatial covariance model) ·
S-2 SOC stock computation (requires coarse fragments + depth profile) ·
S-3 local lab-calibration workflow (pH method mapping) ·
S-4 EC ingestion with mandatory procedure metadata ·
S-5 hydrological properties (FC/PWP/Ksat) from texture via pedotransfer
functions — requires a cited PTF (e.g. Saxton & Rawls 2006) before use.
