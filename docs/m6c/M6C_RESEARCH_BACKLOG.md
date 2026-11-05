# M6C — Research Backlog

Deliberately out of M6C scope (documented, not attempted). Items are ordered
by expected decision value.

## Erosion & terrain
- **DEM ingestion + flow-routing analytics** — slope length (LS), flow
  accumulation, concentrated-flow area detection. Requires an elevation data
  pipeline (none exists); naive polygon-derived slope length is forbidden.
- **Regional R/K factor sources** — licensed regional erosivity/erodibility
  datasets with versioning; the platform ships none and must not default to
  US NRCS tables.
- **RUSLE2-full integration** — the official tool's daily-loop internals are
  out of scope; M6C implements only the factor-product screening with
  farmer/sourced factors.
- **Wind-erosion quantitative model** (RWEQ/WEQ or region-appropriate) —
  taxonomy slot reserved (`wind`), no model.
- **Ephemeral/classical gully indicators** — needs flow-path evidence.

## Remote sensing
- **Validated fractional-cover conversion** — NDVI/vegetation-index → % soil
  cover requires a regionally validated model + sensor conditions; until
  then index values are stored and displayed as indices only.
- **Residue cover from shortwave-infrared indices** (e.g. CAI/NBR-class
  products) — same precondition.

## Cover crops & residue
- **Regionally sourced cover-crop trait packs** — seeding rates, sowing
  windows, termination methods, invasiveness status per species/region.
  The engine is ready (trait vocabulary documented); nothing ships without a
  verifiable source.
- **Sourced residue-production coefficients** (residue-to-product ratios /
  harvest indices per crop × environment × management) for the
  `coefficient_estimate` path.
- **Mixture competition knowledge** — composition interactions; plan items
  support mixtures structurally, evaluation does not claim mixture behaviour.
- **Residue-N into the M6B budget as a reviewed application** — an explicit,
  provenance-carrying import workflow (double-counting guard exists; the
  workflow itself is future work).

## Operations
- **Weather forecast provider integration** — explicit provider contract
  (issue time, valid time, uncertainty, expiry); until then weather checks
  stay pending.
- **Trafficability model** — needs defensible soil-moisture/consistency +
  axle-load inputs and a valid method; the manual readiness check stands.
- **Multi-crew `Cumulative` labour capacity, travel times, multi-field
  routing** — the scheduler models exclusive day-granularity resources on
  one field.
- **Machinery cost/economics** — only with farmer-entered costs.

## Platform
- **Agronomist review workflow activation** for upgrading reference
  practices/rules to confirmed_regional (the review table exists from M5;
  no confirmed rows ship).
- **Offline write-queue for M6C entities** — current offline support covers
  viewing cached data and the existing observation patterns.
- **Notification/deadline engine** for management-plan deadlines.
