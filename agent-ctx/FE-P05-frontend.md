# FE-P05 — CropTwist P05/P06 Frontend Workstream (Map layers, profile, processing ledger)

Task ID: FE-P05 · Date: session record · Runtime: bun / Next.js 16 App Router

## Scope executed

Backend (:3030) was consumed read-only. All work is frontend-only, appended to the
existing P02/P04 surfaces (no new tabs/sub-pages; `src/lib/navigation.ts` untouched).

### Files changed

1. **src/lib/types.ts** (append, lines ~3857–4096) — P05/P06 contract types:
   `SatelliteProcessingState`, `SatelliteProcessingDetail` (state-dependent union-ish:
   processing → `job_ids/indices/stage/progress`; failed → `job_id/error`),
   `SatelliteZonalStats`, `SatelliteZonePartition`, `SatelliteZoneSummary`,
   `SatelliteDerivedProduct` (`bbox_wgs84: [number,number,number,number] | null`),
   `SatelliteProcessingScene`, `SatelliteProcessingResponse`, `SatelliteProcessingInput`,
   `SatelliteProcessingJob`, `SatelliteProcessingJobResponse` (202 body incl. `skipped`,
   `queued_scenes`, `warnings`), `SatelliteProcessingCancelResponse`,
   `SatelliteProfileObservation`, `SatelliteProfileGap`, `SatelliteProfileCoverage`,
   `SatelliteProfileQualitySummary`, `SatelliteProfileBaseline`, `SatelliteProfileComparison`,
   `SatelliteProfileTrend`, `SatelliteSpatialVariation`, `SatelliteDerivedAssetRecord`,
   `SatelliteInsufficientEvidence`, `SatelliteProfileResponse`.

2. **src/lib/api.ts** (append, section "P05/P06 endpoints", lines ~1703–1777):
   - `getSatelliteProcessing(fieldId)` → GET `/fields/{id}/satellite/processing`
   - `createSatelliteProcessing(fieldId, input)` → POST (202) same path
   - `getSatelliteProfile(fieldId, index='ndvi')` → GET `/fields/{id}/satellite/profile?index=…`
   - `cancelSatelliteProcessingJob(fieldId, jobId)` → POST `/fields/{id}/satellite/processing/{job_id}/cancel`
   - `fetchSatelliteAssetBlob(fieldId, assetId)` → GET `/fields/{id}/satellite/assets/{asset_id}/content`,
     binary bypass of the JSON pipeline with the same one-shot 401→refresh retry; caller owns
     the returned Blob → object URL and MUST revoke it.

3. **src/hooks/use-croptwist.ts** (append, lines ~709–763):
   - `useSatelliteProcessing(fieldId)` — query `['satellite-processing', fieldId]`,
     conditional `refetchInterval` 5000 ms while any scene `processing_state === 'processing'`.
   - `useCreateSatelliteProcessing(fieldId)` — mutation invalidating `['satellite-processing']`
     and `['satellite-scenes']`.
   - `useCancelSatelliteProcessingJob(fieldId)` — cancels a derivation job (invalidates both).
   - `useSatelliteProfile(fieldId, index)` — query `['satellite-profile', fieldId, index]`, staleTime 30 s.

4. **src/components/croptwist/navigation/map-satellite-pane.tsx** — added the "Satellite layers"
   card + `useSatelliteLayers` hook (file lives in `navigation/` where the P02 pane already was;
   composition unchanged). Features: index selector ndvi/evi/ndmi/ndwi/bsi (indices without
   products disabled + "not available" hint + amber `unavailableHint` line), scene-date selector
   (scenes having a product for the chosen index), Radix Slider opacity + Show/Hide toggle,
   documented-colormap legend (brown→white→green over the documented range, "masked =
   transparent" note, NDVI-specific low/high labels), provenance line (product·provider,
   `SyntheticBadge` when `is_synthetic`, acquired date, resolution, processing version, valid
   pixel %, cloud %), honest states (SectionSkeleton / ErrorState / empty card with
   `setActiveTab('datahub'); setActiveSub('scenes')` link). Blob URL lifecycle owned here:
   fetched via `fetchSatelliteAssetBlob`, revoked in a dedicated cleanup effect that runs after
   FarmMap's teardown (child unmounts first), race-guarded by an `alive` flag.

5. **src/components/croptwist/farm-map.tsx** — new optional prop
   `satelliteOverlay?: SatelliteMapOverlay | null` (exported interface: `id`, `imageUrl`,
   `bbox`, `opacity`, `visible`). Inside the existing build effect, when set, adds an image
   source `croptwist-satellite-layer-{id}` + raster layer inserted with `beforeId
   'farm-field-outline'` (above the field fill, below outlines). Wrapped in try/catch so an
   invalid overlay can never take down the base map. Overlay is in the effect-deps rebuild
   pattern; when `null` the map renders exactly as before. Existing callers unaffected
   (prop defaults to `null`; field-map.tsx still compiles untouched).

6. **src/components/croptwist/satellite.tsx** — added `SatelliteProfileSection` below the
   monthly-means chart, for the panel's currently selected index: recharts timeline LineChart
   (ChartContainer, `dir="ltr"` island, Y domain = documented_range), freshness badge
   (green fresh "X d ago" / amber stale; CLDR plurals), valid/excluded counts + avg valid-pixel
   %, amber insufficient-evidence banner (reasons + note; hides trend/comparison/zones when
   present), baseline comparison card (latest, delta, z-score, baseline stats; amber
   weak-evidence note with `uncertainty_note`), trend card (slope_per_30d, points, method),
   statistical-zones table (lowest/middle/highest tercile, mean, pixel share, value range,
   description caption), coverage-gaps amber box (windows + `gaps_note`), provenance line
   (derived-assets count, processing version, first-8-char checksums).

7. **src/components/croptwist/satellite-scenes.tsx** — added Processing ledger integration:
   `ProcessingStateBadge` (unprocessed = secondary; processing = pulsing amber dot +
   stage progress %; processed = emerald; failed = destructive with server error in tooltip
   AND sr-only), "Process" column in the desktop table and the mobile card, operator-gated
   (`roleAtLeast(..., 'operator')`) "Process NDVI" action on ready+unprocessed rows and
   "Retry processing" on ready+failed rows → `useCreateSatelliteProcessing` with
   `processQueued`/`processSkipped` toasts. Existing discovery/acquire/cancel flows untouched.

8. **messages/en/satellite.json + messages/ar/satellite.json** — 75 new keys appended in a
   P05/P06 block; full en/ar parity verified programmatically (108 keys each). Arabic uses
   correct terminology and CLDR plural categories (two/few/many). `satellite` namespace was
   already registered in `src/i18n/config.ts` — no namespace change needed.

## i18n keys added (satellite namespace)

layersTitle, layersDesc, sceneDateLabel, indexDescNDVI, indexDescEVI, indexDescNDMI,
indexDescNDWI, indexDescBSI, notAvailableHint, unavailableHint, noProductsTitle,
noProductsDesc, layersLoadError, previewLoading, previewError, noPreviewHint, opacity,
showLayer, hideLayer, legendTitle, legendLowNdvi, legendHighNdvi, legendLow, legendHigh,
legendMasked, infoAcquired, infoResolution, infoVersion, infoValidPixels, infoCloud,
colProcess, procStateUnprocessed, procStateProcessing, procStateProcessed, procStateFailed,
detailErrorLabel, processNdvi, retryProcessing, processQueued, processSkipped, profileTitle,
profileDesc, profileTimeline, profileLoadError, freshnessFresh, freshnessStale, noObservations,
validObservations, excludedObservations, avgValidPixel, insufficientTitle, baselineComparison,
latestValue, deltaVsBaseline, zScore, baselineStats, baselineStatsValue, weakEvidenceNote,
trendTitle, slopePer30d, trendPoints, trendMethod, zonesTitle, zonesZone, zonesMean,
zonesPixelShare, zonesValueRange, zoneLowestTercile, zoneMiddleTercile, zoneHighestTercile,
gapsTitle, gapWindow, provenance, checksumLabel.

## Verification

- `bunx tsc --noEmit` → clean (no output).
- `bun test tests/frontend/` → **45 pass, 0 fail** (367 expect() calls).
- `bun run lint` → no errors (`eslint .` clean).
- Live backend smoke (scratch bun script, read-only, deleted afterwards):
  login OK (`demo@croptwist.local`); field `fbe4ddb8-5eda-480a-bb92-5aadd05b51d7`:
  GET processing → `total: 3`, all `processed`, 3 products each for ndvi/evi/ndmi/ndwi/bsi,
  zero contract key gaps (scene + product shapes match types exactly); GET profile?index=ndvi
  → `profile_version: field-satellite-profile-1.0.0`, timeline 3 / excluded 0, `fresh: true`
  (2 d), baseline present, `comparison.weak_evidence: true` (z null → UI shows amber note,
  hides z row), trend OLS 3 points, 3 statistical terciles with description, `derived_assets: 3`,
  zero missing keys; GET assets/{preview_asset_id}/content → 200 `image/png`, PNG magic bytes
  confirmed, bbox present (31.40–31.42 E, 31.07–31.09 N).

## Contract notes / intentional deviations

1. **MapLibre image-source coordinates**: the task's literal order
   `[[minLon,minLat],[maxLon,minLat],[maxLon,maxLat],[minLon,maxLat]]` is bottom-left-first;
   MapLibre requires top-left, top-right, bottom-right, bottom-left. Implementation uses
   `[[minLon,maxLat],[maxLon,maxLat],[maxLon,minLat],[minLon,minLat]]` so north-up backend
   renderings are not vertically flipped.
2. Source id is `croptwist-satellite-layer-{assetId}` (per-asset suffix) instead of the fixed
   `croptwist-satellite-layer` — avoids addSource/addLayer id collisions across map rebuilds;
   same namespace prefix.
3. Poll interval conflict in the spec (A: 5000 ms, C: 4 s for the same shared hook):
   implemented 5000 ms in `useSatelliteProcessing` (A's explicit value).
4. `fetchSatelliteAssetBlob` authenticates via the app's HttpOnly session-cookie plumbing
   (backend accepts `fs_token` cookie as bearer) — identical to every existing satellite fn;
   the smoke test separately confirmed an explicit `Authorization: Bearer` header also works.
5. Legend documented ranges are the backend's documented constants (ndvi [-1,1], evi [-1,3],
   ndmi/ndwi/bsi [-1,1]); gradient is fixed brown→white→green over the documented range,
   never per-image normalized.
6. Pre-existing console warning "Select is changing from uncontrolled to controlled" traces to
   `field-picker.tsx` (`value ?? undefined`) in the context bar and `rotation.tsx:651` — NOT to
   the P05 Selects (all receive stable string values); those files are outside this task's scope.
7. POST processing allows `savi` per contract, but per spec the layers card exposes
   ndvi/evi/ndmi/ndwi/bsi only; the satellite panel's existing selector (ndvi/evi/savi/ndmi/ndwi)
   was left as-is (pre-existing P2 surface).

## Handoff notes for future agents

- `useSatelliteProcessing` shares one query key with both the map layers card and the scene
  catalog → one poll loop serves both surfaces; keep that key stable.
- Blob URLs for map overlays are owned by `useSatelliteLayers` (map-satellite-pane.tsx);
  never revoke inside FarmMap (parent cleanup ordering matters).
- The scene catalog's `processingByScene` map is the join point between the
  `satellite-scenes` catalog and the processing ledger; if the backend adds per-scene
  processing rows without catalog rows, the join stays null-safe.
