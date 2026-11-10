# Task 3b — CropTwist data-visualization charts (P1-2)

Agent: charts-frontend (task ID 3b)
Date: 2026-02-14
Status: ✅ Complete — eslint clean, tsc clean (no new errors), dev server compiles & serves 200.

## Files created

| File | Lines | Purpose |
|---|---|---|
| `src/components/croptwist/charts/climate-overview.tsx` | 161 | Card: ComposedChart — precipitation bars (teal `#0ea5a4`) + `air_temperature_mean` line (emerald `#059669`), dual Y axes (mm / °C), last ~120 days. Tries the trailing 120-day window first; if it is empty, re-queries the 120 days anchored at `COVERAGE_END` (2024-12-31) so historical fixture data still renders. Loading Skeleton / error / noData states; renders `null` when `fieldId` is null. |
| `src/components/croptwist/charts/data-coverage.tsx` | 117 | Card: horizontal BarChart of valid observation counts per variable (sorted desc, capped at 16, humanized tick labels via `humanizeCode`), teal bars, `showingOf` truncation note. |
| `src/components/croptwist/charts/water-monthly.tsx` | 89 | Pure presentational ComposedChart from `WaterPlanMonth[]`: bars `precip_mm` + `effective_rainfall_mm` (teal / lime), lines `et0_mm` (amber), `etc_mm` (emerald), `dr_end_mm` (stone). Months with `precip_evidence_missing` render an honest gap (null, no bar). |
| `src/components/croptwist/charts/sensitivity-charts.tsx` | 281 | Two exports, both pure presentational: (a) `SensitivityTornadoChart({ rows: SensitivityOatResponse[] })` — horizontal bars of `difference_at_lower` (lime) vs `difference_at_upper` (teal), one row per feature keeping its most responsive period, sorted by span, capped at 12 with `showingFeatures` note, zero reference line; (b) `SensitivityCurvesChart({ grid: SensitivityGridResponse | null })` — LineChart of grid `cells` (`cell_value` vs first axis, one line per value of the second axis, ≤6 curves), feature picker (native select), default = most responsive feature by `grid_output_range`; returns `null` when grid/axes/cells absent. |
| `src/components/croptwist/charts/soil-soc.tsx` | 98 | Pure presentational vertical BarChart of `SocStockLayerRow[]`: depth (`top–bottom` cm) on X, `soc_stock_mg_ha` on Y; measured = emerald, predicted = lime (`Cell` fills), refused layers leave an honest gap; hand-rolled swatch legend. |
| `messages/en/charts.json` | 35 | New `charts` namespace (namespace was already registered in `src/i18n/config.ts`). |
| `messages/ar/charts.json` | 35 | Real Arabic translations (agricultural/climate terms; ET₀/ETc/Mg C/ha kept in Latin script). |

All chart components use `ChartContainer`/`ChartTooltip`/`ChartTooltipContent`/`ChartLegend(Content)` from `src/components/ui/chart.tsx`, `'use client'`, emerald/teal/lime/amber/stone palette only, ~260–300px heights, Card style `border-stone-200 bg-white shadow-sm` matching the tabs.

## Files modified (insertion points)

| File | Change (exact location) |
|---|---|
| `overview.tsx` | +2 imports (after `useFields/useFarms/useHealthReady` import, line ~9–11); +1 conditional block after the stat-card grid (line ~147) and before the `{empty ? …}` setup card: `<div className="grid gap-4 lg:grid-cols-2 [&>*]:min-w-0">` with `<ClimateOverview fieldId={firstField.id} />` and `<DataCoverage fieldId={firstField.id} />` (~11 lines total; other diff hunks in git are the pre-existing i18n conversion by another agent). |
| `water.tsx` | +1 import (line 53); inside `SeasonPlanCard` → AccordionItem `"months"` → AccordionContent (line ~756): `<WaterMonthlyChart months={season.months} />` above `<MonthlyTable season={season} />` (table wrapped in `mt-4` div). |
| `sensitivity.tsx` | +1 import block (lines 41–44); `ResponsesCard` CardContent (line ~256): `<SensitivityTornadoChart rows={rows} />` above the responses table; `GridCard` CardContent (line ~363): `<SensitivityCurvesChart grid={data} />` after the summaries table. |
| `soil.tsx` | +1 import (line 47); `SocSection` (line ~499): `{latest?.result ? <SocStockChart layers={latest.result.layers} /> : null}` directly below the profile-total block. |

All diffs ≤ ~11 changed lines per tab file. No changes to `workspace.tsx`, `store.ts`, `api.ts`, `layout.tsx`, other messages files, or `src/app/api/**`. No new routes.

## Hooks reused (no api.ts additions)

- `useObservations(fieldId, start, end, enabled)` — climate chart (two windows via the `enabled` flag; second query only fires when the first resolves empty).
- `useDataCoverage(fieldId, enabled)` — coverage chart.
- Water / sensitivity / soil charts take already-loaded data as props (`season.months`, `rows` from the existing `listSensitivityResponses` query, `data` from `getSensitivityGrid`, `latest.result.layers` from `useSocRuns`) — zero new fetching.
- **No api.ts functions were added or modified** (only imported the existing `COVERAGE_END` constant).

## i18n keys (`charts` namespace, en + ar)

`climateTitle, climateDesc, precipLabel, tempLabel, coverageTitle, coverageDesc, validCount, showingOf, waterTitle, waterDesc, precip, effectiveRainfall, et0, etc, drainage, month, tornadoTitle, tornadoDesc, lowerBound, upperBound, showingFeatures, curvesTitle, curvesDesc, featureLabel, socTitle, socDesc, depth, socStock, measured, predicted, loadError, loading, noData`

All mission-required keys present; extras added: `showingOf`, `showingFeatures`, `featureLabel`, `measured`, `predicted`, `loadError`. Components use `useTranslations('charts')` only.

## Verification

- `bunx eslint src/components/croptwist/charts src/components/croptwist/overview.tsx src/components/croptwist/water.tsx src/components/croptwist/sensitivity.tsx src/components/croptwist/soil.tsx` → **clean (0 errors, 0 warnings)**.
- `bunx tsc --noEmit` → no errors in any file I own (3 pre-existing errors in `skills/image-edit/...` and `src/app/api/auth/*` are untouched/out of scope).
- `dev.log`: page compiles and serves 200 on `/`, `/?tab=soil`, `/?tab=scenarios`; a transient "Identifier already declared" error appeared only from a mid-edit intermediate state of `sensitivity.tsx` (duplicate import for <1 min) and is gone — latest requests compile clean.

## Notes for next agents

- `charts` namespace keys are safe to reuse; don't rename `charts.json` files.
- Grid response-curve parsing assumes the documented cell shape `{feature_code, <param codes…>, cell_value}` (see `docs/m7/m7_4/M7_4_API_CONTRACTS.md` §grid).
- The climate card falls back to the `COVERAGE_END`-anchored window when "now − 120d" has no observations — keep this behavior if you touch it, otherwise historical synthetic fixtures render a permanent empty state.
