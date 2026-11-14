'use client'

/**
 * FE-2 — Data Hub "Scene catalog" sub-page (`?tab=datahub&sub=scenes`).
 *
 * Scene discovery + acquisition lifecycle for the selected field:
 *   - discovery queries the public NASA CMR STAC catalog for NASA HLS
 *     (Landsat 8/9 + Sentinel-2 harmonized surface reflectance, 30 m);
 *   - acquiring a scene reads its cloud-optimized GeoTIFF assets and derives
 *     vegetation indices server-side.
 *
 * Honesty contract (MANDATORY): this page renders CATALOG + ACQUISITION
 * STATUS ONLY. Vegetation-index values are never shown here — a ready
 * scene's indices live in Crop Intelligence / satellite intelligence views,
 * and the UI says so (`readyHint`).
 *
 * Role gating (frontend UX only; the server is the authority): discovery and
 * acquisition controls require `roleAtLeast(org.my_role, 'operator')` via the
 * shared ['p3-orgs'] cache.
 */

import { useState } from 'react'
import { useLocale, useTranslations } from 'next-intl'
import { useQuery } from '@tanstack/react-query'
import { toast } from 'sonner'
import { Check, Loader2 } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { ErrorState, SectionSkeleton } from '@/components/croptwist/state-views'
import {
  FieldContextGate,
  UnavailableFieldNotice,
  useFieldAvailability,
  useFieldContext,
} from '@/components/croptwist/field-context'
import { SyntheticBadge } from '@/components/croptwist/badges'
import {
  useAcquireScenes,
  useCancelSceneJob,
  useCreateSatelliteProcessing,
  useDiscoverScenes,
  useSatelliteProcessing,
  useSatelliteScenes,
} from '@/hooks/use-croptwist'
import { ApiError, describeError } from '@/lib/api'
import { formatDateTime, pct } from '@/lib/format'
import { listOrganizations, roleAtLeast } from '@/lib/api-p3-account'
import type {
  SatelliteCatalogScene,
  SatelliteMapIndex,
  SatelliteProcessingScene,
  SatelliteProcessingState,
} from '@/lib/types'

type Translator = ReturnType<typeof useTranslations>

/** Fixed page size; pagination walks offset in LIMIT steps. */
const LIMIT = 100
const MAP_SUPPORTED_INDICES: SatelliteMapIndex[] = ['ndvi', 'evi', 'ndmi', 'ndwi', 'bsi']

/** First string-valued key found in the acquisition_detail blob (job_id / error / reason). */
function detailText(detail: Record<string, unknown> | null | undefined, keys: string[]): string | null {
  if (!detail) return null
  for (const key of keys) {
    const value = detail[key]
    if (typeof value === 'string' && value.trim().length > 0) return value
  }
  return null
}

function cloudText(scene: SatelliteCatalogScene): string {
  return scene.cloud_cover_pct != null ? `${Math.round(scene.cloud_cover_pct)}%` : '—'
}

/** Acquisition lifecycle badge — never blue for ready (green = ready here). */
function SceneStatusBadge({ scene, t }: { scene: SatelliteCatalogScene; t: Translator }) {
  const label = t(`status.${scene.acquisition_status}`)
  const badge =
    scene.acquisition_status === 'discovered' ? (
      <Badge variant="secondary">{label}</Badge>
    ) : scene.acquisition_status === 'queued' ? (
      <Badge variant="outline" className="gap-1.5 border-amber-300 bg-amber-50 text-amber-900">
        <span className="inline-block h-1.5 w-1.5 rounded-full bg-amber-500" aria-hidden />
        {label}
      </Badge>
    ) : scene.acquisition_status === 'running' ? (
      <Badge variant="outline" className="gap-1.5 border-emerald-200 bg-white text-emerald-800">
        <span className="inline-block h-1.5 w-1.5 animate-pulse rounded-full bg-emerald-500" aria-hidden />
        {label}
      </Badge>
    ) : scene.acquisition_status === 'ready' ? (
      <Badge className="border-transparent bg-primary/10 text-primary">{label}</Badge>
    ) : (
      <Badge variant="destructive">{label}</Badge>
    )

  // Failed rows must surface the server's acquisition error/reason (truncated
  // in a tooltip AND mirrored in sr-only text — never a silent "Failed").
  const failure =
    scene.acquisition_status === 'failed'
      ? detailText(scene.acquisition_detail, ['error', 'reason'])
      : null
  if (!failure) return badge

  return (
    <span className="inline-flex items-center gap-1.5">
      <Tooltip>
        <TooltipTrigger asChild>
          <span className="cursor-help" aria-label={`${t('detailErrorLabel')}: ${failure}`}>
            {badge}
          </span>
        </TooltipTrigger>
        <TooltipContent className="max-w-80">
          <p className="break-words">{failure}</p>
        </TooltipContent>
      </Tooltip>
      <span className="sr-only">{failure}</span>
    </span>
  )
}

interface SceneActionProps {
  scene: SatelliteCatalogScene
  processingScene: SatelliteProcessingScene | null
  canOperate: boolean
  busy: boolean
  selectedIndices: SatelliteMapIndex[]
  t: Translator
  tSat: Translator
  onAcquire: () => void
  onCancel: () => void
  onProcess: () => void
}

/**
 * P05 per-scene index-derivation badge:
 *   unprocessed → outline/secondary · processing → pulsing dot + stage %
 *   processed → emerald · failed → destructive with the server error in a
 *   tooltip AND sr-only text (never a silent failure).
 */
function ProcessingStateBadge({
  state,
  detail,
  tSat,
}: {
  state: SatelliteProcessingState
  detail: SatelliteProcessingScene['processing_detail']
  tSat: Translator
}) {
  const label = tSat(`procState${state.charAt(0).toUpperCase()}${state.slice(1)}`)

  if (state === 'processing') {
    const progress = typeof detail?.progress === 'number' ? Math.round(detail.progress) : null
    return (
      <Badge variant="outline" className="gap-1.5 border-amber-300 bg-amber-50 text-amber-900">
        <span className="inline-block h-1.5 w-1.5 animate-pulse rounded-full bg-amber-500" aria-hidden />
        {label}
        {progress != null && <span className="tabular-nums">{progress}%</span>}
      </Badge>
    )
  }
  if (state === 'processed') {
    return <Badge className="border-transparent bg-emerald-100 text-emerald-900">{label}</Badge>
  }
  if (state === 'failed') {
    const error = typeof detail?.error === 'string' && detail.error.trim() ? detail.error : null
    const badge = <Badge variant="destructive">{label}</Badge>
    if (!error) return badge
    return (
      <span className="inline-flex items-center gap-1.5">
        <Tooltip>
          <TooltipTrigger asChild>
            <span className="cursor-help" aria-label={`${tSat('detailErrorLabel')}: ${error}`}>
              {badge}
            </span>
          </TooltipTrigger>
          <TooltipContent className="max-w-80">
            <p className="break-words">{error}</p>
          </TooltipContent>
        </Tooltip>
        <span className="sr-only">{error}</span>
      </span>
    )
  }
  return <Badge variant="secondary">{label}</Badge>
}

function ProcessingProductsDetail({
  detail,
  tSat,
}: {
  detail: SatelliteProcessingScene['processing_detail']
  tSat: Translator
}) {
  if (!detail?.available_indices || !detail.missing_indices) return null
  return (
    <p className="mt-1 text-[10px] leading-relaxed text-stone-600">
      <span className="font-medium">{tSat('availableIndices')}:</span>{' '}
      {detail.available_indices.map((index) => index.toUpperCase()).join(', ') || '—'}
      <span className="mx-1.5" aria-hidden>·</span>
      <span className="font-medium">{tSat('missingIndices')}:</span>{' '}
      {detail.missing_indices.map((index) => index.toUpperCase()).join(', ') || '—'}
    </p>
  )
}

/** Row-level actions, gated on org role (desktop table + mobile card share it). */
function SceneActionButtons({
  scene,
  processingScene,
  canOperate,
  busy,
  selectedIndices,
  t,
  tSat,
  onAcquire,
  onCancel,
  onProcess,
}: SceneActionProps) {
  if (!canOperate) return <span className="text-xs text-stone-300">—</span>

  if (scene.acquisition_status === 'ready') {
    const processState = processingScene?.processing_state ?? 'unprocessed'
    // P05 honesty gate: only scenes the preprocessing pipeline can accept
    // offer derivation — real NASA HLS scenes and the explicitly-labeled
    // fixture_demo demo fixtures. Every other provider (e.g. P2 SIM-*)
    // is refused by the backend, so the action is never offered for them.
    const processable =
      scene.provider_code === 'nasa_hls' ||
      (scene.provider_code === 'fixture_demo' && scene.is_synthetic)
    if (['unprocessed', 'partial', 'failed'].includes(processState) && processable) {
      return (
        <Button
          variant="outline"
          size="sm"
          className="h-8 px-2 text-xs"
          disabled={busy || selectedIndices.length === 0}
          onClick={onProcess}
        >
          {processState === 'failed' ? tSat('retryProcessing') : tSat('processSelected')}
        </Button>
      )
    }
    if (processState === 'processed') {
      return (
        <span className="inline-flex items-center gap-1 text-emerald-700" title={t('readyHint')}>
          <Check className="h-4 w-4" aria-hidden />
          <span className="sr-only">{t('readyHint')}</span>
        </span>
      )
    }
    // 'processing' — derivation is running; nothing actionable.
    return null
  }

  if (scene.acquisition_status === 'queued' || scene.acquisition_status === 'running') {
    const jobId = detailText(scene.acquisition_detail, ['job_id'])
    if (!jobId) return null
    return (
      <Button variant="outline" size="sm" className="h-8 px-2 text-xs" disabled={busy} onClick={onCancel}>
        {t('cancel')}
      </Button>
    )
  }

  if (scene.acquisition_status === 'discovered' || scene.acquisition_status === 'failed') {
    return (
      <Button variant="outline" size="sm" className="h-8 px-2 text-xs" disabled={busy} onClick={onAcquire}>
        {t('acquire')}
      </Button>
    )
  }

  return null
}

function SceneRow(props: SceneActionProps) {
  const { scene, t, tSat, processingScene } = props
  return (
    <TableRow>
      <TableCell className="whitespace-nowrap text-xs text-stone-600">
        {formatDateTime(scene.acquired_at)}
      </TableCell>
      <TableCell className="text-xs">
        <span className="font-medium text-stone-900">{scene.scene_id}</span>
        <span className="ms-2 inline-flex items-center gap-1 align-middle">
          <Badge variant="outline" className="px-1.5 py-0 text-[10px] uppercase">
            {scene.product_code}
          </Badge>
          {scene.is_synthetic && <SyntheticBadge />}
        </span>
      </TableCell>
      <TableCell className="text-xs tabular-nums text-stone-600">{cloudText(scene)}</TableCell>
      <TableCell>
        <SceneStatusBadge scene={scene} t={t} />
      </TableCell>
      <TableCell>
        {processingScene ? (
          <div>
            <ProcessingStateBadge
              state={processingScene.processing_state}
              detail={processingScene.processing_detail}
              tSat={tSat}
            />
            <ProcessingProductsDetail detail={processingScene.processing_detail} tSat={tSat} />
          </div>
        ) : (
          <span className="text-xs text-stone-300">—</span>
        )}
      </TableCell>
      <TableCell className="text-xs tabular-nums text-stone-600">
        {pct(scene.coverage_fraction)}
      </TableCell>
      <TableCell>
        <div className="flex justify-end">
          <SceneActionButtons {...props} />
        </div>
      </TableCell>
    </TableRow>
  )
}

function SceneCard(props: SceneActionProps) {
  const { scene, t, tSat, processingScene } = props
  const failure =
    scene.acquisition_status === 'failed'
      ? detailText(scene.acquisition_detail, ['error', 'reason'])
      : null
  return (
    <div className="rounded-lg border border-stone-200 bg-white p-3">
      <div className="flex items-center justify-between gap-2">
        <span className="min-w-0 truncate text-sm font-medium text-stone-900">{scene.scene_id}</span>
        <SceneStatusBadge scene={scene} t={t} />
      </div>
      <p className="mt-1 text-xs text-stone-600">
        {scene.product_code} · {formatDateTime(scene.acquired_at)} · {t('colCloud')}{' '}
        {cloudText(scene)} · {t('colCoverage')} {pct(scene.coverage_fraction)}
      </p>
      {processingScene && (
        <div className="mt-1">
          <ProcessingStateBadge
            state={processingScene.processing_state}
            detail={processingScene.processing_detail}
            tSat={tSat}
          />
          <ProcessingProductsDetail detail={processingScene.processing_detail} tSat={tSat} />
        </div>
      )}
      {scene.is_synthetic && (
        <div className="mt-1">
          <SyntheticBadge />
        </div>
      )}
      {failure && (
        <p className="mt-1 break-words rounded bg-red-50 p-1.5 text-[11px] text-red-700">{failure}</p>
      )}
      {scene.acquisition_status === 'ready' && processingScene?.processing_state === 'processed' && (
        <p className="mt-1 text-[11px] text-emerald-800">{t('readyHint')}</p>
      )}
      <div className="mt-2 flex justify-end">
        <SceneActionButtons {...props} />
      </div>
    </div>
  )
}

export default function SatelliteScenesPage() {
  const locale = useLocale()
  const t = useTranslations('scenecatalog')
  const tSat = useTranslations('satellite')
  const { selectedField, setSelectedField } = useFieldContext()
  const availability = useFieldAvailability()

  // Shared org cache (kept fresh by the Team tab) — frontend role gating only.
  // `listOrganizations` (api-p3-account) is the typed variant of the same
  // /orgs endpoint the other ['p3-orgs'] consumers use, so `my_role` arrives
  // as an OrgRoleCode for `roleAtLeast`.
  const orgsQuery = useQuery({
    queryKey: ['p3-orgs'],
    queryFn: listOrganizations,
    staleTime: 60_000,
    retry: 1,
  })
  const canOperate = roleAtLeast(orgsQuery.data?.items[0]?.my_role, 'operator')

  // Discovery controls — defaults: last 30 days, ≤80% cloud.
  const today = new Date().toISOString().slice(0, 10)
  const monthAgo = new Date(Date.now() - 30 * 86400_000).toISOString().slice(0, 10)
  const [startDate, setStartDate] = useState(monthAgo)
  const [endDate, setEndDate] = useState(today)
  const [maxCloud, setMaxCloud] = useState('80')
  const [warnings, setWarnings] = useState<string[]>([])
  const [selectedProcessingIndices, setSelectedProcessingIndices] = useState<SatelliteMapIndex[]>(['ndvi'])

  // Pagination is keyed to the selected field: switching fields resets to page
  // 0 via derived state (no effect — the offset only applies while the same
  // field stays selected).
  const [pageState, setPageState] = useState<{ fieldId: string | null; offset: number }>({
    fieldId: null,
    offset: 0,
  })
  const fieldId = selectedField?.id ?? null
  const offset = pageState.fieldId === fieldId ? pageState.offset : 0
  const setOffset = (next: number) => setPageState({ fieldId, offset: next })

  const catalog = useSatelliteScenes(fieldId, { limit: LIMIT, offset })
  const discover = useDiscoverScenes(fieldId)
  const acquire = useAcquireScenes(fieldId)
  const cancelJob = useCancelSceneJob(fieldId)

  // P05 processing ledger — per-scene derivation states + live polling while
  // any scene is mid-derivation (shared query with the map layers card).
  const processing = useSatelliteProcessing(fieldId)
  const process = useCreateSatelliteProcessing(fieldId)

  if (availability === 'none') return <FieldContextGate hint={t('pickFieldHint')} />
  if (availability === 'unavailable' && selectedField) {
    return <UnavailableFieldNotice field={selectedField} onClear={() => setSelectedField(null)} />
  }

  const datesValid = !!startDate && !!endDate && startDate <= endDate
  const scenes = catalog.data?.scenes ?? []
  const total = catalog.data?.total ?? 0
  const discoveredScenes = scenes.filter((s) => s.acquisition_status === 'discovered')
  const processingByScene = new Map(
    (processing.data?.scenes ?? []).map((entry) => [entry.scene_id, entry]),
  )

  const mutationErrorToast = (err: unknown) => {
    if (err instanceof ApiError && err.status === 403) {
      toast.error(t('operatorRequired'))
      return
    }
    const d = describeError(err)
    toast.error(d.title, { description: d.description })
  }

  const handleDiscover = () => {
    setWarnings([])
    discover.mutate(
      { start_date: startDate, end_date: endDate, max_cloud_cover: Number(maxCloud) },
      {
        onSuccess: (res) => {
          setWarnings(res.warnings)
          toast.success(t('discoveryDone', { discovered: res.discovered, created: res.new }))
        },
        onError: mutationErrorToast,
      },
    )
  }

  const handleAcquire = (scene: SatelliteCatalogScene) => {
    acquire.mutate(
      { scene_ids: [scene.scene_id], variables: ['ndvi'] },
      {
        onSuccess: (res) => toast.success(t('acquireQueued', { count: res.queued_scenes.length })),
        onError: mutationErrorToast,
      },
    )
  }

  const handleAcquireAll = () => {
    acquire.mutate(
      { scene_ids: discoveredScenes.map((s) => s.scene_id), variables: ['ndvi'] },
      {
        onSuccess: (res) => toast.success(t('acquireQueued', { count: res.queued_scenes.length })),
        onError: mutationErrorToast,
      },
    )
  }

  const handleCancel = (scene: SatelliteCatalogScene) => {
    const jobId = detailText(scene.acquisition_detail, ['job_id'])
    if (!jobId) return
    cancelJob.mutate(jobId, {
      onSuccess: (res) => toast.success(t('cancelDone', { count: res.scenes_released.length })),
      onError: mutationErrorToast,
    })
  }

  const handleProcess = (scene: SatelliteCatalogScene) => {
    if (selectedProcessingIndices.length === 0) return
    process.mutate(
      { scene_ids: [scene.scene_id], indices: selectedProcessingIndices },
      {
        onSuccess: (res) => {
          toast.success(tSat('processQueued', { count: res.queued_scenes }))
          if (res.skipped.length > 0) {
            toast.info(tSat('processSkipped', { count: res.skipped.length }))
          }
        },
        onError: mutationErrorToast,
      },
    )
  }

  const actionProps = (scene: SatelliteCatalogScene) => ({
    scene,
    processingScene: processingByScene.get(scene.scene_id) ?? null,
    canOperate,
    busy: acquire.isPending || cancelJob.isPending || process.isPending,
    selectedIndices: selectedProcessingIndices,
    t,
    tSat,
    onAcquire: () => handleAcquire(scene),
    onCancel: () => handleCancel(scene),
    onProcess: () => handleProcess(scene),
  })

  return (
    <div className="space-y-4" dir={locale === 'ar' ? 'rtl' : 'ltr'}>
      <header>
        <h2 className="text-lg font-semibold text-stone-900">{t('title')}</h2>
        <p className="mt-0.5 text-sm text-stone-500">{t('description')}</p>
        <p className="mt-1 max-w-3xl text-xs leading-relaxed text-stone-400">{t('provenanceNote')}</p>
      </header>

      {/* Discovery controls */}
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-base">{t('discoveryTitle')}</CardTitle>
          <CardDescription className="text-sm text-stone-500">{t('discoveryDesc')}</CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
            <div className="flex flex-col gap-1">
              <Label className="text-xs text-stone-600" htmlFor="scenes-start">
                {t('startDate')}
              </Label>
              <Input
                id="scenes-start"
                type="date"
                className="h-9"
                value={startDate}
                max={today}
                onChange={(e) => setStartDate(e.target.value)}
              />
            </div>
            <div className="flex flex-col gap-1">
              <Label className="text-xs text-stone-600" htmlFor="scenes-end">
                {t('endDate')}
              </Label>
              <Input
                id="scenes-end"
                type="date"
                className="h-9"
                value={endDate}
                max={today}
                onChange={(e) => setEndDate(e.target.value)}
              />
            </div>
            <div className="flex flex-col gap-1">
              <Label className="text-xs text-stone-600" htmlFor="scenes-cloud">
                {t('maxCloud')}
              </Label>
              <Select value={maxCloud} onValueChange={setMaxCloud}>
                <SelectTrigger id="scenes-cloud" className="h-9 bg-white">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {['40', '60', '80', '100'].map((value) => (
                    <SelectItem key={value} value={value}>
                      {t('maxCloudOption', { value })}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-3">
            {canOperate ? (
              <Button
                className="bg-emerald-700 text-white hover:bg-emerald-800"
                disabled={discover.isPending || !datesValid}
                onClick={handleDiscover}
              >
                {discover.isPending ? (
                  <>
                    <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> {t('discovering')}
                  </>
                ) : (
                  t('discover')
                )}
              </Button>
            ) : (
              <p className="text-xs text-stone-500">{t('operatorRequired')}</p>
            )}
            {canOperate && !datesValid && (
              <p className="text-xs text-amber-800">{t('invalidRange')}</p>
            )}
          </div>
          {warnings.length > 0 && (
            <div
              className="rounded-md border border-amber-200 bg-amber-50/60 p-3 text-xs text-amber-900"
              role="status"
            >
              <p className="font-semibold">{t('discoveryWarningsTitle', { count: warnings.length })}</p>
              <ul className="mt-1 list-disc space-y-0.5 ps-4">
                {warnings.map((warning, i) => (
                  <li key={i}>{warning}</li>
                ))}
              </ul>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Catalog */}
      <Card>
        <CardHeader className="pb-2">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div>
              <CardTitle className="text-base">{t('catalogTitle')}</CardTitle>
              <CardDescription className="text-sm text-stone-500">{t('catalogDesc')}</CardDescription>
            </div>
            {canOperate && (
              <Button
                variant="outline"
                size="sm"
                disabled={discoveredScenes.length === 0 || acquire.isPending}
                onClick={handleAcquireAll}
              >
                {acquire.isPending ? t('acquiring') : t('acquireAllNdvi')}
              </Button>
            )}
          </div>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="rounded-md border border-stone-200 bg-stone-50/70 p-3">
            <p className="text-sm font-medium text-stone-800">{tSat('processProductsTitle')}</p>
            <p className="mt-0.5 text-xs leading-relaxed text-stone-600">{tSat('processProductsHint')}</p>
            <div
              className="mt-2 flex flex-wrap gap-x-4 gap-y-2"
              role="group"
              aria-label={tSat('processProductsTitle')}
            >
              {MAP_SUPPORTED_INDICES.map((index) => (
                <label key={index} className="inline-flex cursor-pointer items-center gap-1.5 text-xs text-stone-700">
                  <input
                    type="checkbox"
                    className="size-3.5 accent-emerald-700"
                    checked={selectedProcessingIndices.includes(index)}
                    onChange={() =>
                      setSelectedProcessingIndices((current) =>
                        current.includes(index)
                          ? current.filter((selected) => selected !== index)
                          : [...current, index],
                      )
                    }
                  />
                  <span className="font-semibold">{index.toUpperCase()}</span>
                </label>
              ))}
            </div>
            {selectedProcessingIndices.length === 0 && (
              <p className="mt-2 text-xs text-amber-800">{tSat('selectAtLeastOne')}</p>
            )}
          </div>
          {catalog.isLoading ? (
            <SectionSkeleton lines={5} />
          ) : catalog.isError ? (
            <ErrorState message={t('loadError')} onRetry={() => catalog.refetch()} />
          ) : total === 0 ? (
            <div className="flex flex-col items-center gap-1 rounded-md border border-dashed border-stone-300 bg-stone-50/60 px-4 py-10 text-center">
              <p className="text-sm font-medium text-stone-600">{t('emptyCatalog')}</p>
              <p className="text-xs text-stone-500">{t('emptyCatalogHint')}</p>
            </div>
          ) : (
            <>
              {/* Desktop table (hidden md:block — house responsive pattern) */}
              <div className="hidden overflow-x-auto md:block">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>{t('colAcquired')}</TableHead>
                      <TableHead>{t('colProduct')}</TableHead>
                      <TableHead>{t('colCloud')}</TableHead>
                      <TableHead>{t('colStatus')}</TableHead>
                      <TableHead>{tSat('colProcess')}</TableHead>
                      <TableHead>{t('colCoverage')}</TableHead>
                      <TableHead className="text-end">{t('colActions')}</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {scenes.map((scene) => (
                      <SceneRow key={scene.id} {...actionProps(scene)} />
                    ))}
                  </TableBody>
                </Table>
              </div>
              {/* Mobile cards */}
              <div className="space-y-2 md:hidden">
                {scenes.map((scene) => (
                  <SceneCard key={scene.id} {...actionProps(scene)} />
                ))}
              </div>
              <div className="flex flex-wrap items-center justify-between gap-2 border-t border-stone-100 pt-3">
                <p className="text-xs text-stone-500">{t('totalScenes', { count: total })}</p>
                <div className="flex items-center gap-2">
                  <Button
                    variant="outline"
                    size="sm"
                    disabled={offset === 0}
                    onClick={() => setOffset(Math.max(0, offset - LIMIT))}
                  >
                    {t('prevPage')}
                  </Button>
                  <Button
                    variant="outline"
                    size="sm"
                    disabled={offset + LIMIT >= total}
                    onClick={() => setOffset(offset + LIMIT)}
                  >
                    {t('nextPage')}
                  </Button>
                </div>
              </div>
              <p className="text-[11px] text-stone-400">{t('readyHint')}</p>
            </>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
