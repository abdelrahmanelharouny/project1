# KNOWLEDGE_GAPS_AND_RESEARCH_BACKLOG.md — remaining limitations, explicitly assigned

Nothing below is silently missing: each item names its required evidence or
design work. External agronomic validation is NOT marked complete anywhere —
all seed knowledge remains `reference` until a regional agronomist confirms it.

## K — Agronomic knowledge (Phase D)

| ID | Gap | Required evidence / work | Where it would land |
|---|---|---|---|
| K-1 | GDD, base/upper temperatures, photoperiod, vernalization | crop-science sources (e.g. FAO EcoCrop documentation set, cultivar trials) transcribed with page-level citations | new trait rows + phenology engine (M6+) |
| K-2 | Residue quantities, C:N, decomposition; cover-crop water competition | residue/biomass datasets + M7 daily water balance | soil-health engine |
| K-3 | Salinity thresholds (ECe) | FAO I&D Paper 29 Rev.1 (Ayers & Westcot 1985) crop table — must be digitized from the source, values never from memory | crop_traits + irrigation suitability |
| K-4 | Pathogen-level rotation model (survival structures, alternative hosts, per-pathogen durations) | Agrios (2005) chapters per pathogen, regionally confirmed | rotation_rules + host entity model |
| K-5 | Variety/cultivar records (duration/water/heat differences) | cultivar trial data or national variety catalogs | crop_varieties rows |
| K-6 | Regional crop calendars (incl. equatorial rainfall-based seasons) | national/subnational calendar datasets, licensing review | regional knowledge packs |

## C — Climate methodology (Phase C)

| ID | Gap | Work needed |
|---|---|---|
| C-1 | Reference-period configuration (exclude evaluated year; fixed WMO windows) | catalog version bump + provenance semantics change |
| C-2 | SPI/SPEI | ≥30 y records (provider coverage 2015+ for synthetic, 1940+ ERA5) + distribution-fitting review |
| C-3 | ETCCDI WSDI / percentile-based indices | computed reference percentiles (needs climatology stage) |
| C-4 | Locally defined seasons beyond user windows | regional crop-calendar packs (K-6) |

## S — Soil science (Phase E)

S-1 field-level prediction intervals (spatial covariance) · S-2 SOC stocks
(needs coarse fragments + depth integration) · S-3 pH method calibration
workflow · S-4 EC ingestion with mandatory procedure metadata · S-5
pedotransfer functions for FC/PWP/Ksat (cited PTF required) · S-6 deeper
SoilGrids depth intervals (soil measurement history milestone).

## M — Rotation mathematics / economics (Phase F)

| ID | Gap | Work needed |
|---|---|---|
| M-1 | Epsilon-constraint Pareto sweep (guaranteed front coverage) | engine version bump; changes strategy count + UI |
| M-2 | Farm economics surface (gross revenue, variable/fixed costs, currency, valuation year, losses) | farmer input schema + storage; NO platform-estimated prices |
| M-3 | Multi-field farm-level rotation planning | constraint layer extension |
| M-4 | Agronomist review UI (approval workflow that flips `reference` → `confirmed_regional`) | review tables exist; UI + role enforcement pending |

## B — Engineering (accepted, non-blocking)

B-1 roles defined but not yet enforced on routes (owner/manager/agronomist/viewer) ·
B-2 knowledge list endpoints N+1 + unbounded lists (paginate) · B-3 upload
size checked after buffering (stream-limit) · B-4 `dev_mode` default True
(flip in deployment) · B-5 UI hemisphere selector (today: fixed 'north' in the
rotation form; backend honours a proper value) · B-6 severity shown as colour
only on candidate reasons (add text) · B-7 `calendar_windows_matched` lists
all field-applicable windows rather than only the matched one · B-8
`min_break_seasons` serialized as 0 when unspecified (should be null) ·
B-9 float8 accumulation policy documented (NUMERIC accumulation reserved for
M7 water ledger) · B-10 inline job execution (no worker queue) · B-11
SoilGrids area-weighting deferred (G-2 rationale).

## G — Geospatial

G-1 automatic antimeridian re-wrapping (today: explicit warning) ·
G-2 area-weighted SoilGrids extraction (kept unweighted deliberately —
250 m grid; revisit for sub-hectare fields).
