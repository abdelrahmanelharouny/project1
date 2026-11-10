'use client'

/**
 * Management workspace (M6C): cover crops, soil cover, residue, erosion
 * screening and operations planning — one tab, six sub-views, Simple/Expert.
 *
 * Honesty rules mirrored from the backend:
 * - missing data is shown as missing ("—", "not evaluated") — never zero
 * - SYNTHETIC warnings surface wherever the evidence run is synthetic
 * - statuses render with colour AND text (accessibility)
 * - nothing here silently relaxes a backend refusal
 */

import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useTranslations } from 'next-intl'
import {
  CalendarDays,
  Layers,
  Leaf,
  Mountain,
  Recycle,
  ShieldAlert,
  Sprout,
} from 'lucide-react'
import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from '@/components/ui/accordion'
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
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Separator } from '@/components/ui/separator'
import { Skeleton } from '@/components/ui/skeleton'
import { Switch } from '@/components/ui/switch'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { FieldPicker } from '@/components/croptwist/field-picker'
import { SyntheticBadge } from '@/components/croptwist/badges'
import { useCropTwistUi } from '@/lib/store'
import { describeError } from '@/lib/api'
import {
  createCoverCropPlan,
  createCoverCropPlanItem,
  createCoverObservation,
  createErosionAssessment,
  createFarmResource,
  createManagementPlan,
  createResidueFlow,
  createResidueRecord,
  createScheduleRun,
  generateOperations,
  getCoverTimeline,
  getResidueLedger,
  listCoverCropPlanItems,
  listCoverCropPlans,
  listFarmResources,
  listFieldOperations,
  listManagementPractices,
  listOperationTemplates,
  patchOperation,
} from '@/lib/api'
import type {
  CoverCandidate,
  CoverMetrics,
  CoverTimelineResponse,
  ErosionRun,
  ManagementPlan,
  ResidueLedgerResponse,
  ScheduleRun,
} from '@/lib/types'

// ---------------------------------------------------------------- helpers

function today(): string {
  return new Date().toISOString().slice(0, 10)
}

function daysAgo(n: number): string {
  const d = new Date()
  d.setDate(d.getDate() - n)
  return d.toISOString().slice(0, 10)
}

function StatusBadge({ status }: { status: string }) {
  const tone =
    status === 'eligible' || status === 'evaluated' || status === 'succeeded' || status === 'scheduled'
      ? 'border-emerald-200 bg-emerald-50 text-emerald-800'
      : status === 'conditional'
        ? 'border-amber-200 bg-amber-50 text-amber-900'
        : status === 'excluded' || status === 'failed' || status === 'over_allocated'
          ? 'border-red-200 bg-red-50 text-red-800'
          : status === 'not_evaluated' || status === 'unknown' || status === 'unscheduled'
            ? 'border-stone-300 bg-stone-100 text-stone-600'
            : 'border-stone-200 bg-stone-50 text-stone-700'
  return (
    <Badge variant="outline" className={`px-1.5 py-0 text-[10px] ${tone}`}>
      {status.replace(/_/g, ' ')}
    </Badge>
  )
}

function SectionStatus({ status, message }: { status: string; message?: string | null }) {
  return (
    <div className="flex flex-col gap-1">
      <StatusBadge status={status} />
      {message ? <p className="text-xs text-stone-500">{message}</p> : null}
    </div>
  )
}

function HonestEmpty({ children }: { children: React.ReactNode }) {
  return (
    <p className="rounded-md border border-dashed border-stone-300 bg-stone-50 px-3 py-2 text-sm text-stone-500">
      {children}
    </p>
  )
}

function ErrorNote({ error }: { error: unknown }) {
  if (!error) return null
  const described = describeError(error)
  return (
    <p className="text-xs font-medium text-red-700" role="alert">
      {described.title}
      {described.description ? ` — ${described.description}` : ''}
    </p>
  )
}

function Metric({ label, value, hint }: { label: string; value: React.ReactNode; hint?: string }) {
  return (
    <div className="rounded-lg border border-stone-200 bg-white px-3 py-2">
      <p className="text-[11px] uppercase tracking-wide text-stone-500">{label}</p>
      <p className="text-lg font-semibold text-stone-900">{value}</p>
      {hint ? <p className="text-[11px] text-stone-400">{hint}</p> : null}
    </div>
  )
}

// ------------------------------------------------------------ main view

const SUB_VIEWS = [
  { value: 'plan', labelKey: 'viewPlan', icon: <Sprout className="h-3.5 w-3.5" aria-hidden /> },
  { value: 'covers', labelKey: 'viewCovers', icon: <Leaf className="h-3.5 w-3.5" aria-hidden /> },
  { value: 'timeline', labelKey: 'viewTimeline', icon: <Layers className="h-3.5 w-3.5" aria-hidden /> },
  { value: 'residue', labelKey: 'viewResidue', icon: <Recycle className="h-3.5 w-3.5" aria-hidden /> },
  { value: 'erosion', labelKey: 'viewErosion', icon: <ShieldAlert className="h-3.5 w-3.5" aria-hidden /> },
  { value: 'operations', labelKey: 'viewOperations', icon: <CalendarDays className="h-3.5 w-3.5" aria-hidden /> },
] as const

type SubView = (typeof SUB_VIEWS)[number]['value']

export function Management() {
  const t = useTranslations('management')
  const selectedField = useCropTwistUi((s) => s.selectedField)
  const setSelectedField = useCropTwistUi((s) => s.setSelectedField)
  const selectedFarmId = useCropTwistUi((s) => s.selectedFarmId)
  const [view, setView] = useState<SubView>('plan')
  const [expert, setExpert] = useState(false)

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader className="pb-3">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <CardTitle className="flex items-center gap-2 text-base">
                <Sprout className="h-4 w-4 text-emerald-700" aria-hidden />
                {t('title')}
              </CardTitle>
              <CardDescription>
                {t('desc')}
              </CardDescription>
            </div>
            <div className="flex items-center gap-2 text-xs text-stone-500">
              <span aria-hidden>{t('simple')}</span>
              <Switch checked={expert} onCheckedChange={setExpert} aria-label={t('toggleExpert')} />
              <span aria-hidden>{t('expert')}</span>
            </div>
          </div>
        </CardHeader>
        <CardContent className="space-y-3">
          <FieldPicker
            value={selectedField?.id ?? null}
            onValueChange={setSelectedField}
            emptyHint={
              <p className="text-sm text-stone-500">
                {t('emptyHint')}
              </p>
            }
          />
          {selectedField ? (
            <Tabs value={view} onValueChange={(v) => setView(v as SubView)}>
              <div className="-mx-1 overflow-x-auto pb-1 scrollbar-thin">
                <TabsList className="mx-1 inline-flex min-w-max">
                  {SUB_VIEWS.map((s) => (
                    <TabsTrigger key={s.value} value={s.value} className="gap-1.5 px-2.5 text-xs">
                      {s.icon}
                      {t(s.labelKey)}
                    </TabsTrigger>
                  ))}
                </TabsList>
              </div>
              <TabsContent value="plan" className="mt-3">
                <PlanView fieldId={selectedField.id} expert={expert} />
              </TabsContent>
              <TabsContent value="covers" className="mt-3">
                <CoverStudio fieldId={selectedField.id} expert={expert} />
              </TabsContent>
              <TabsContent value="timeline" className="mt-3">
                <TimelineView fieldId={selectedField.id} expert={expert} />
              </TabsContent>
              <TabsContent value="residue" className="mt-3">
                <ResidueView fieldId={selectedField.id} expert={expert} />
              </TabsContent>
              <TabsContent value="erosion" className="mt-3">
                <ErosionView fieldId={selectedField.id} expert={expert} />
              </TabsContent>
              <TabsContent value="operations" className="mt-3">
                <OperationsView fieldId={selectedField.id} farmId={selectedFarmId ?? selectedField.farmId} expert={expert} />
              </TabsContent>
            </Tabs>
          ) : (
            <HonestEmpty>{t('pickField')}</HonestEmpty>
          )}
        </CardContent>
      </Card>
    </div>
  )
}

// ------------------------------------------------------------ plan view

function PlanView({ fieldId, expert }: { fieldId: string; expert: boolean }) {
  const t = useTranslations('management')
  const qc = useQueryClient()
  const [created, setCreated] = useState<ManagementPlan | null>(null)
  const [error, setError] = useState<unknown>(null)

  const createPlan = useMutation({
    mutationFn: () =>
      createManagementPlan(fieldId, {
        window_start: daysAgo(180),
        window_end: today(),
        season_label: undefined,
        label: 'Management plan',
      }),
    onSuccess: (plan) => {
      setCreated(plan)
      setError(null)
      qc.invalidateQueries({ queryKey: ['management-plan', fieldId] })
    },
    onError: setError,
  })

  const plan = created
  if (!plan) {
    return (
      <div className="space-y-3">
        <p className="text-sm text-stone-600">
          {t('planIntro')}
        </p>
        <Button onClick={() => createPlan.mutate()} disabled={createPlan.isPending} className="bg-emerald-700 hover:bg-emerald-800">
          {createPlan.isPending ? t('building') : t('buildPlan')}
        </Button>
        <ErrorNote error={error} />
      </div>
    )
  }

  const r = plan.result
  const m = r.soil_cover.metrics
  return (
    <div className="space-y-4" data-testid="management-plan">
      {plan.warnings.map((w, i) => (
        <p key={i} className="rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-900">
          {w}
        </p>
      ))}

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Metric label={t('metricCover')} value={`${m.days_protective_cover} d`} hint={t('hintOfDays', { total: m.window_days })} />
        <Metric label={t('metricBare')} value={`${m.days_known_bare} d`} hint={m.longest_bare_interval ? t('hintLongest', { days: m.longest_bare_interval_days }) : t('noBareEvidence')} />
        <Metric label={t('metricUnknown')} value={`${m.days_unknown} d`} hint={t('hintNeverBare')} />
        <Metric label={t('metricChecks')} value={r.checks.length} hint={t('hintAttention')} />
      </div>

      <Accordion type="multiple" defaultValue={['checks', 'season']} className="w-full">
        <AccordionItem value="season">
          <AccordionTrigger className="text-sm">
            {t('seasonContext')} <StatusBadge status={r.season_context.status} />
          </AccordionTrigger>
          <AccordionContent className="space-y-2 text-sm text-stone-600">
            {r.season_context.recent_crop_history.length === 0 ? (
              <HonestEmpty>{r.season_context.message ?? t('noCropHistory')}</HonestEmpty>
            ) : (
              <ul className="space-y-1">
                {r.season_context.recent_crop_history.map((h, i) => (
                  <li key={i} className="flex flex-wrap gap-2 text-xs">
                    <span className="font-medium text-stone-800">{h.crop_label}</span>
                    <span>{h.sowing_date ?? '—'} → {h.harvest_date ?? '—'}</span>
                    {h.season_label ? <Badge variant="outline" className="px-1 py-0 text-[10px]">{h.season_label}</Badge> : null}
                  </li>
                ))}
              </ul>
            )}
          </AccordionContent>
        </AccordionItem>

        <AccordionItem value="checks">
          <AccordionTrigger className="text-sm">{t('checksTrigger')}</AccordionTrigger>
          <AccordionContent className="space-y-2">
            {r.checks.length === 0 ? (
              <p className="text-sm text-emerald-800">{t('noOpenChecks')}</p>
            ) : (
              r.checks.map((c, i) => (
                <div key={i} className="flex items-start gap-2 text-xs">
                  <Badge variant="outline" className={c.severity === 'warning' ? 'border-amber-300 bg-amber-50 text-amber-900' : 'border-stone-300 bg-stone-50 text-stone-600'}>
                    {c.severity}
                  </Badge>
                  <span className="text-stone-600">{c.message}</span>
                </div>
              ))
            )}
          </AccordionContent>
        </AccordionItem>

        <AccordionItem value="sections">
          <AccordionTrigger className="text-sm">{t('moduleStatus')}</AccordionTrigger>
          <AccordionContent>
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
              {[
                { label: t('moduleCoverCrops'), ...r.cover_crop },
                { label: t('moduleResidue'), ...r.residue },
                { label: t('moduleErosion'), ...r.erosion },
                { label: t('moduleOperations'), ...r.operations },
                { label: t('moduleWater'), ...r.water },
              ].map((s) => (
                <div key={s.label} className="rounded-lg border border-stone-200 p-3">
                  <p className="text-xs font-semibold text-stone-700">{s.label}</p>
                  <div className="mt-1"><SectionStatus status={s.status} message={s.message} /></div>
                </div>
              ))}
            </div>
          </AccordionContent>
        </AccordionItem>

        <AccordionItem value="ops">
          <AccordionTrigger className="text-sm">{t('nextOps')}</AccordionTrigger>
          <AccordionContent className="space-y-1">
            {r.operations.next_operations.length === 0 ? (
              <HonestEmpty>{r.operations.message ?? t('noOpsRecorded')}</HonestEmpty>
            ) : (
              r.operations.next_operations.map((o) => (
                <div key={o.id} className="flex flex-wrap items-center gap-2 text-xs">
                  <StatusBadge status={o.status} />
                  <span className="font-medium text-stone-800">{o.title}</span>
                  <span className="text-stone-500">
                    {o.scheduled_start ?? o.earliest_start ?? t('noWindow')} … {o.scheduled_end ?? o.latest_finish ?? ''}
                  </span>
                  {o.status_reason ? <span className="text-amber-800">{o.status_reason}</span> : null}
                </div>
              ))
            )}
          </AccordionContent>
        </AccordionItem>

        {expert ? (
          <>
            <AccordionItem value="practice">
              <AccordionTrigger className="text-sm">{t('practiceGuidance')}</AccordionTrigger>
              <AccordionContent>
                <div className="max-h-64 space-y-1 overflow-y-auto scrollbar-thin pr-1">
                  {r.practice_guidance.practices.map((p) => (
                    <div key={p.practice_code} className="flex flex-wrap items-center gap-2 text-xs">
                      <span className="font-medium text-stone-800">{p.name}</span>
                      <Badge variant="outline" className="px-1 py-0 text-[10px]">{p.practice_family}</Badge>
                      <StatusBadge status={p.validation_status} />
                    </div>
                  ))}
                </div>
                <p className="mt-2 text-[11px] text-stone-500">{r.practice_guidance.note}</p>
              </AccordionContent>
            </AccordionItem>
            <AccordionItem value="prov">
              <AccordionTrigger className="text-sm">{t('provenance')}</AccordionTrigger>
              <AccordionContent className="space-y-1 text-xs text-stone-600">
                <p>{t('engineLine', { version: plan.engine_version })}</p>
                <p className="break-all">{t('checksumLine')} <span className="font-mono">{plan.checksum_sha256}</span></p>
                {Object.entries(plan.not_evaluated).map(([k, v]) => (
                  <p key={k}><span className="font-medium">{k.replace(/_/g, ' ')}:</span> {v}</p>
                ))}
              </AccordionContent>
            </AccordionItem>
          </>
        ) : null}
      </Accordion>
    </div>
  )
}

// ------------------------------------------------------------ cover studio

function CoverStudio({ fieldId, expert }: { fieldId: string; expert: boolean }) {
  const t = useTranslations('management')
  const qc = useQueryClient()
  const [windowStart, setWindowStart] = useState(today())
  const [windowEnd, setWindowEnd] = useState(daysAgo(-120))
  const [nextCrop, setNextCrop] = useState('')
  const [plan, setPlan] = useState<CoverPlan | null>(null)
  const [adopted, setAdopted] = useState<string | null>(null)
  const [error, setError] = useState<unknown>(null)

  const items = useQuery({
    queryKey: ['cover-items', fieldId],
    queryFn: () => import('@/lib/api').then((m) => m.listCoverCropPlanItems(fieldId)),
    enabled: Boolean(fieldId),
  })

  const run = useMutation({
    mutationFn: () => createCoverCropPlan(fieldId, { window_start: windowStart, window_end: windowEnd, next_crop_label: nextCrop || undefined }),
    onSuccess: (p) => {
      setPlan(p)
      setError(null)
      qc.invalidateQueries({ queryKey: ['cover-items', fieldId] })
    },
    onError: setError,
  })

  const adopt = useMutation({
    mutationFn: (candidate: CoverCandidate) =>
      createCoverCropPlanItem(fieldId, {
        crop_label: candidate.crop_code,
        plan_run_id: plan?.id,
        intended_sowing_start: candidate.sowing_window?.[0],
        intended_termination_window_start: undefined,
      }),
    onSuccess: (item) => {
      setAdopted(item.id)
      qc.invalidateQueries({ queryKey: ['cover-items', fieldId] })
    },
    onError: setError,
  })

  const candidates = plan?.result.candidates ?? []

  return (
    <div className="space-y-4">
      <p className="text-sm text-stone-600">
        {t.rich('coverIntro', { cond: (chunks) => <span className="font-medium">{chunks}</span> })}
      </p>
      <div className="grid gap-2 sm:grid-cols-4">
        <div className="space-y-1">
          <Label htmlFor="cover-start" className="text-xs">{t('windowStart')}</Label>
          <Input id="cover-start" type="date" value={windowStart} onChange={(e) => setWindowStart(e.target.value)} className="h-9 text-sm" />
        </div>
        <div className="space-y-1">
          <Label htmlFor="cover-end" className="text-xs">{t('windowEnd')}</Label>
          <Input id="cover-end" type="date" value={windowEnd} onChange={(e) => setWindowEnd(e.target.value)} className="h-9 text-sm" />
        </div>
        <div className="space-y-1">
          <Label htmlFor="cover-next" className="text-xs">{t('nextCropLabel')}</Label>
          <Input id="cover-next" value={nextCrop} onChange={(e) => setNextCrop(e.target.value)} placeholder={t('cropPlaceholder')} className="h-9 text-sm" />
        </div>
        <div className="flex items-end">
          <Button onClick={() => run.mutate()} disabled={run.isPending} className="w-full bg-emerald-700 hover:bg-emerald-800">
            {run.isPending ? t('evaluating') : t('evaluateCandidates')}
          </Button>
        </div>
      </div>
      <ErrorNote error={error} />

      {plan ? (
        <div className="space-y-3" data-testid="cover-candidates">
          {plan.warnings.map((w, i) => (
            <p key={i} className="rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-900">{w}</p>
          ))}
          {candidates.length === 0 ? (
            <HonestEmpty>
              {t('noCandidates')}
            </HonestEmpty>
          ) : (
            candidates.map((c) => (
              <Card key={c.crop_code} className="border-stone-200">
                <CardHeader className="pb-2">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <CardTitle className="text-sm">{c.crop_label}</CardTitle>
                    <div className="flex items-center gap-2">
                      <StatusBadge status={c.status} />
                      {adopted === c.crop_code || items.data?.items.some((i) => i.crop_label === c.crop_code) ? (
                        <Badge variant="outline" className="border-emerald-300 bg-emerald-50 px-1.5 py-0 text-[10px] text-emerald-800">{t('inPlan')}</Badge>
                      ) : null}
                    </div>
                  </div>
                  <CardDescription>{c.trade_off_note}</CardDescription>
                </CardHeader>
                <CardContent className="space-y-2 text-xs text-stone-600">
                  <div className="flex flex-wrap gap-1">
                    {c.functions.map((f) => (
                      <Badge key={f.function_code} variant="outline" className="border-emerald-200 bg-emerald-50 text-[10px] text-emerald-800">
                        {f.function_code.replace(/_/g, ' ')}
                      </Badge>
                    ))}
                  </div>
                  <ul className="space-y-1">
                    {c.conditions.map((cond, i) => (
                      <li key={i} className="flex gap-2">
                        <span className="mt-1 h-1.5 w-1.5 shrink-0 rounded-full bg-amber-500" aria-hidden />
                        <span>{cond.message}</span>
                      </li>
                    ))}
                  </ul>
                  {c.sowing_window ? (
                    <p className="text-[11px]">{t('sowingWindow', { start: c.sowing_window[0], end: c.sowing_window[1] })}</p>
                  ) : null}
                  {expert ? (
                    <Accordion type="single" collapsible className="w-full">
                      <AccordionItem value="dims">
                        <AccordionTrigger className="text-xs">{t('dimensionDetail')}</AccordionTrigger>
                        <AccordionContent>
                          <div className="space-y-1">
                            {Object.entries(c.dimensions).map(([k, d]) => (
                              <div key={k} className="flex flex-wrap items-center gap-2">
                                <StatusBadge status={d.status} />
                                <span className="font-mono text-[10px] text-stone-500">{k}</span>
                                <span className="text-stone-600">{d.message}</span>
                              </div>
                            ))}
                          </div>
                        </AccordionContent>
                      </AccordionItem>
                    </Accordion>
                  ) : null}
                  {c.status !== 'excluded' ? (
                    <Button
                      size="sm"
                      variant="outline"
                      className="h-8 text-xs"
                      onClick={() => adopt.mutate(c)}
                      disabled={adopt.isPending}
                    >
                      {t('adoptIntoPlan')}
                    </Button>
                  ) : null}
                </CardContent>
              </Card>
            ))
          )}
        </div>
      ) : null}

      {items.data && items.data.items.length > 0 ? (
        <div className="space-y-1">
          <p className="text-xs font-semibold text-stone-700">{t('adoptedDecisions')}</p>
          {items.data.items.map((i) => (
            <div key={i.id} className="flex flex-wrap items-center gap-2 text-xs text-stone-600">
              <StatusBadge status={i.status} />
              <span className="font-medium text-stone-800">{i.crop_label}</span>
              <span>{i.season_label ?? ''}</span>
            </div>
          ))}
        </div>
      ) : null}
    </div>
  )
}

// ------------------------------------------------------------ timeline view

const CLASS_COLOR: Record<string, string> = {
  protective: 'bg-emerald-500',
  bare: 'bg-amber-600',
  unknown: 'bg-stone-300',
}

function TimelineView({ fieldId, expert }: { fieldId: string; expert: boolean }) {
  const t = useTranslations('management')
  const [start, setStart] = useState(daysAgo(180))
  const [end, setEnd] = useState(today())
  const timeline = useQuery({
    queryKey: ['cover-timeline', fieldId, start, end],
    queryFn: () => getCoverTimeline(fieldId, start, end),
    enabled: Boolean(fieldId),
  })
  const qc = useQueryClient()
  const [obsDate, setObsDate] = useState(today())
  const [obsState, setObsState] = useState('bare')
  const [error, setError] = useState<unknown>(null)

  const addObs = useMutation({
    mutationFn: () => createCoverObservation(fieldId, { observed_date: obsDate, cover_state: obsState }),
    onSuccess: () => {
      setError(null)
      qc.invalidateQueries({ queryKey: ['cover-timeline', fieldId] })
    },
    onError: setError,
  })

  const data = timeline.data
  const months = useMemo(() => {
    if (!data) return []
    // downsample timeline to per-day cells grouped by month for the strip
    return data.timeline
  }, [data])

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end gap-2">
        <div className="space-y-1">
          <Label htmlFor="tl-start" className="text-xs">{t('fromLabel')}</Label>
          <Input id="tl-start" type="date" value={start} onChange={(e) => setStart(e.target.value)} className="h-9 text-sm" />
        </div>
        <div className="space-y-1">
          <Label htmlFor="tl-end" className="text-xs">{t('toLabel')}</Label>
          <Input id="tl-end" type="date" value={end} onChange={(e) => setEnd(e.target.value)} className="h-9 text-sm" />
        </div>
      </div>

      {timeline.isLoading ? <Skeleton className="h-40 w-full" /> : null}
      <ErrorNote error={timeline.error} />

      {data ? (
        <div className="space-y-3">
          <div className="flex flex-wrap gap-3 text-[11px] text-stone-600">
            <span className="flex items-center gap-1"><span className={`inline-block h-2.5 w-2.5 rounded ${CLASS_COLOR.protective}`} aria-hidden /> {t('legendProtective')}</span>
            <span className="flex items-center gap-1"><span className={`inline-block h-2.5 w-2.5 rounded ${CLASS_COLOR.bare}`} aria-hidden /> {t('legendBare')}</span>
            <span className="flex items-center gap-1"><span className={`inline-block h-2.5 w-2.5 rounded ${CLASS_COLOR.unknown}`} aria-hidden /> {t('legendUnknown')}</span>
          </div>

          {/* timeline strip: one cell per day (wrapped, labeled by month) */}
          <div className="overflow-hidden rounded-lg border border-stone-200 p-2">
            <div className="flex flex-wrap gap-px" role="img" aria-label={t('stripAria')}>
              {data.timeline.map((d) => (
                <span
                  key={d.date}
                  title={`${d.date}: ${d.classification}${d.states.length ? ` (${d.states.join(', ')})` : ''}`}
                  className={`h-3 w-3 shrink-0 rounded-sm ${CLASS_COLOR[d.classification] ?? CLASS_COLOR.unknown}`}
                />
              ))}
            </div>
          </div>

          <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
            <Metric label={t('metricProtective')} value={`${data.metrics.days_protective_cover} d`} />
            <Metric label={t('metricBare')} value={`${data.metrics.days_known_bare} d`} />
            <Metric label={t('metricUnknown')} value={`${data.metrics.days_unknown} d`} />
            <Metric
              label={t('metricLongestBare')}
              value={data.metrics.longest_bare_interval_days ? `${data.metrics.longest_bare_interval_days} d` : '—'}
              hint={data.metrics.longest_bare_interval ? data.metrics.longest_bare_interval.join(' → ') : t('noBareEvidence')}
            />
          </div>

          <p className="text-[11px] text-stone-500">{data.thresholds.note}</p>

          <Separator />

          <div className="space-y-2">
            <p className="text-xs font-semibold text-stone-700">{t('recordObs')}</p>
            <div className="flex flex-wrap items-end gap-2">
              <div className="space-y-1">
                <Label htmlFor="obs-date" className="text-xs">{t('dateLabel')}</Label>
                <Input id="obs-date" type="date" value={obsDate} onChange={(e) => setObsDate(e.target.value)} className="h-9 text-sm" />
              </div>
              <div className="space-y-1">
                <Label htmlFor="obs-state" className="text-xs">{t('stateLabel')}</Label>
                <Select value={obsState} onValueChange={setObsState}>
                  <SelectTrigger id="obs-state" className="h-9 w-44 text-sm"><SelectValue /></SelectTrigger>
                  <SelectContent>
                    <SelectItem value="bare">{t('stateBare')}</SelectItem>
                    <SelectItem value="living_main_crop">{t('stateLivingMain')}</SelectItem>
                    <SelectItem value="living_cover_crop">{t('stateLivingCover')}</SelectItem>
                    <SelectItem value="surface_residue">{t('stateResidue')}</SelectItem>
                    <SelectItem value="mulch">{t('stateMulch')}</SelectItem>
                    <SelectItem value="unknown">{t('stateUnknown')}</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <Button size="sm" variant="outline" className="h-9" onClick={() => addObs.mutate()} disabled={addObs.isPending}>
                {addObs.isPending ? t('saving') : t('addObservation')}
              </Button>
            </div>
            <ErrorNote error={error} />
          </div>

          {expert ? (
            <Accordion type="single" collapsible>
              <AccordionItem value="method">
                <AccordionTrigger className="text-xs">{t('methodNotes')}</AccordionTrigger>
                <AccordionContent className="space-y-1 text-[11px] text-stone-600">
                  <p>{data.method.engine} · {data.method.version}</p>
                  {data.method.rules.map((r, i) => <p key={i}>· {r}</p>)}
                  {data.evidence_notes.map((n, i) => <p key={i} className="text-amber-800">· {n.detail}</p>)}
                  <p>{t('inputsLine', { inputs: Object.entries(data.inputs_summary).map(([k, v]) => `${k}=${v}`).join(' · ') })}</p>
                </AccordionContent>
              </AccordionItem>
            </Accordion>
          ) : null}
        </div>
      ) : null}
    </div>
  )
}

// ------------------------------------------------------------ residue view

function ResidueView({ fieldId, expert }: { fieldId: string; expert: boolean }) {
  const t = useTranslations('management')
  const qc = useQueryClient()
  const ledger = useQuery({
    queryKey: ['residue-ledger', fieldId],
    queryFn: () => getResidueLedger(fieldId),
    enabled: Boolean(fieldId),
  })
  const [crop, setCrop] = useState('')
  const [produced, setProduced] = useState('')
  const [flowType, setFlowType] = useState('retained_surface')
  const [flowKg, setFlowKg] = useState('')
  const [targetRecord, setTargetRecord] = useState<string | null>(null)
  const [error, setError] = useState<unknown>(null)

  const addRecord = useMutation({
    mutationFn: () =>
      createResidueRecord(fieldId, {
        crop_label: crop,
        production_status: produced ? 'farmer_reported' : 'missing',
        produced_dm_kg: produced ? Number(produced) : undefined,
      }),
    onSuccess: (rec) => {
      setError(null)
      setCrop('')
      setProduced('')
      setTargetRecord(rec.id)
      qc.invalidateQueries({ queryKey: ['residue-ledger', fieldId] })
    },
    onError: setError,
  })

  const addFlow = useMutation({
    mutationFn: () =>
      createResidueFlow(targetRecord as string, {
        flow_type: flowType,
        dm_kg: flowKg ? Number(flowKg) : undefined,
        dm_kg_status: flowKg ? 'farmer_reported' : 'unknown',
      }),
    onSuccess: () => {
      setError(null)
      setFlowKg('')
      qc.invalidateQueries({ queryKey: ['residue-ledger', fieldId] })
    },
    onError: setError,
  })

  const data: ResidueLedgerResponse | undefined = ledger.data

  return (
    <div className="space-y-4">
      <p className="text-sm text-stone-600">
        {t('residueIntro')}
      </p>

      <div className="flex flex-wrap items-end gap-2">
        <div className="space-y-1">
          <Label htmlFor="res-crop" className="text-xs">{t('cropLabel')}</Label>
          <Input id="res-crop" value={crop} onChange={(e) => setCrop(e.target.value)} placeholder={t('cropPlaceholder')} className="h-9 w-40 text-sm" />
        </div>
        <div className="space-y-1">
          <Label htmlFor="res-prod" className="text-xs">{t('producedLabel')}</Label>
          <Input id="res-prod" type="number" min="0" value={produced} onChange={(e) => setProduced(e.target.value)} className="h-9 w-44 text-sm" />
        </div>
        <Button variant="outline" className="h-9" onClick={() => addRecord.mutate()} disabled={addRecord.isPending || !crop}>
          {addRecord.isPending ? t('saving') : t('addRecord')}
        </Button>
      </div>
      <ErrorNote error={error} />

      {ledger.isLoading ? <Skeleton className="h-32 w-full" /> : null}
      <ErrorNote error={ledger.error} />

      {data ? (
        <div className="space-y-3">
          {data.warnings.map((w, i) => (
            <p key={i} className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-800">{w}</p>
          ))}
          {data.records.length === 0 ? (
            <HonestEmpty>{t('noRecords')}</HonestEmpty>
          ) : (
            data.records.map((rec) => (
              <Card key={rec.record.id} className="border-stone-200">
                <CardHeader className="pb-2">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <CardTitle className="text-sm">{rec.record.crop_label}</CardTitle>
                    <StatusBadge status={rec.balance.status} />
                  </div>
                  <CardDescription>
                    {t('recordDesc', {
                      amount: rec.record.produced_dm_kg !== null ? `${rec.record.produced_dm_kg} kg DM` : t('unknownAmount'),
                      status: rec.record.production_status.replace(/_/g, ' '),
                    })}
                  </CardDescription>
                </CardHeader>
                <CardContent className="space-y-2 text-xs text-stone-600">
                  {rec.flows.map((f) => (
                    <div key={f.id} className="flex flex-wrap items-center gap-2">
                      <Badge variant="outline" className="px-1.5 py-0 text-[10px]">{f.flow_type.replace(/_/g, ' ')}</Badge>
                      <span>{f.dm_kg !== null ? `${f.dm_kg} kg` : t('massUnknown')}</span>
                      <span className="text-stone-400">{f.dm_kg_status}</span>
                    </div>
                  ))}
                  <p>
                    {t('balanceLine', {
                      flows: rec.balance.total_flow_dm_kg,
                      unaccounted: rec.balance.unaccounted_dm_kg !== null ? `${rec.balance.unaccounted_dm_kg} kg` : t('notComputable'),
                    })}
                  </p>
                  {expert && rec.derived.total_nitrogen_kg !== undefined ? (
                    <p className="text-[11px]">
                      {t('nitrogenNote', { value: String(rec.derived.total_nitrogen_kg) })}
                    </p>
                  ) : null}
                  {targetRecord === rec.record.id ? (
                    <div className="flex flex-wrap items-end gap-2 border-t border-stone-100 pt-2">
                      <div className="space-y-1">
                        <Label htmlFor={`flow-type-${rec.record.id}`} className="text-xs">{t('flowLabel')}</Label>
                        <Select value={flowType} onValueChange={setFlowType}>
                          <SelectTrigger id={`flow-type-${rec.record.id}`} className="h-9 w-44 text-sm"><SelectValue /></SelectTrigger>
                          <SelectContent>
                            <SelectItem value="retained_surface">{t('flowRetained')}</SelectItem>
                            <SelectItem value="incorporated">{t('flowIncorporated')}</SelectItem>
                            <SelectItem value="removed_baled">{t('flowRemoved')}</SelectItem>
                            <SelectItem value="grazed">{t('flowGrazed')}</SelectItem>
                            <SelectItem value="burned">{t('flowBurned')}</SelectItem>
                            <SelectItem value="other_loss">{t('flowOther')}</SelectItem>
                            <SelectItem value="unknown">{t('flowUnknownFate')}</SelectItem>
                          </SelectContent>
                        </Select>
                      </div>
                      <div className="space-y-1">
                        <Label htmlFor={`flow-kg-${rec.record.id}`} className="text-xs">{t('dmKgLabel')}</Label>
                        <Input id={`flow-kg-${rec.record.id}`} type="number" min="0" value={flowKg} onChange={(e) => setFlowKg(e.target.value)} className="h-9 w-36 text-sm" />
                      </div>
                      <Button size="sm" variant="outline" className="h-9" onClick={() => addFlow.mutate()} disabled={addFlow.isPending}>
                        {t('addFlow')}
                      </Button>
                    </div>
                  ) : (
                    <Button size="sm" variant="ghost" className="h-7 text-xs" onClick={() => setTargetRecord(rec.record.id)}>
                      {t('addFlowToRecord')}
                    </Button>
                  )}
                </CardContent>
              </Card>
            ))
          )}
        </div>
      ) : null}
    </div>
  )
}

// ------------------------------------------------------------ erosion view

function ErosionView({ fieldId, expert }: { fieldId: string; expert: boolean }) {
  const t = useTranslations('management')
  const qc = useQueryClient()
  const [slopeClass, setSlopeClass] = useState('unknown')
  const [useRusle, setUseRusle] = useState(false)
  const [factors, setFactors] = useState({ R: '100', K: '0.25', LS: '1.0', C: '0.3', P: '0.5' })
  const [factorSource, setFactorSource] = useState('')
  const [run, setRun] = useState<ErosionRun | null>(null)
  const [error, setError] = useState<unknown>(null)

  const assess = useMutation({
    mutationFn: () => {
      const input: Parameters<typeof createErosionAssessment>[1] = {
        window_start: daysAgo(365),
        window_end: today(),
        slope_evidence: slopeClass !== 'unknown' ? { slope_class: slopeClass } : undefined,
      }
      if (useRusle) {
        input.rusle_factors = Object.fromEntries(
          Object.entries(factors).map(([code, value]) => [
            code,
            {
              value: Number(value),
              source_reference: factorSource || 'unspecified local source',
              region_scope: 'farm_declared',
              unit_convention: 'metric_si',
            },
          ]),
        )
      }
      return createErosionAssessment(fieldId, input)
    },
    onSuccess: (r) => {
      setRun(r)
      setError(null)
      qc.invalidateQueries({ queryKey: ['erosion', fieldId] })
    },
    onError: setError,
  })

  return (
    <div className="space-y-4">
      <p className="text-sm text-stone-600">
        {t.rich('erosionIntro', { b: (chunks) => <span className="font-medium">{chunks}</span> })}
      </p>

      <div className="flex flex-wrap items-end gap-2">
        <div className="space-y-1">
          <Label htmlFor="slope" className="text-xs">{t('slopeLabel')}</Label>
          <Select value={slopeClass} onValueChange={setSlopeClass}>
            <SelectTrigger id="slope" className="h-9 w-40 text-sm"><SelectValue /></SelectTrigger>
            <SelectContent>
              <SelectItem value="unknown">{t('slopeUndeclared')}</SelectItem>
              <SelectItem value="flat">{t('slopeFlat')}</SelectItem>
              <SelectItem value="gentle">{t('slopeGentle')}</SelectItem>
              <SelectItem value="moderate">{t('slopeModerate')}</SelectItem>
              <SelectItem value="steep">{t('slopeSteep')}</SelectItem>
            </SelectContent>
          </Select>
        </div>
        <div className="flex items-center gap-2 pb-2 text-xs text-stone-500">
          <Switch checked={useRusle} onCheckedChange={setUseRusle} aria-label={t('rusleAria')} id="rusle-toggle" />
          <Label htmlFor="rusle-toggle" className="text-xs">{t('rusleLabel')}</Label>
        </div>
        {useRusle ? (
          <div className="space-y-1">
            <Label htmlFor="factor-src" className="text-xs">{t('factorSourceLabel')}</Label>
            <Input id="factor-src" value={factorSource} onChange={(e) => setFactorSource(e.target.value)} placeholder={t('factorSourcePlaceholder')} className="h-9 w-52 text-sm" />
          </div>
        ) : null}
        <Button onClick={() => assess.mutate()} disabled={assess.isPending} className="bg-emerald-700 hover:bg-emerald-800">
          {assess.isPending ? t('assessing') : t('runAssessment')}
        </Button>
      </div>

      {useRusle ? (
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-5">
          {(['R', 'K', 'LS', 'C', 'P'] as const).map((code) => (
            <div key={code} className="space-y-1">
              <Label htmlFor={`factor-${code}`} className="text-xs">{code}</Label>
              <Input id={`factor-${code}`} value={factors[code]} onChange={(e) => setFactors({ ...factors, [code]: e.target.value })} className="h-9 text-sm" />
            </div>
          ))}
        </div>
      ) : null}
      <ErrorNote error={error} />

      {run ? (
        <div className="space-y-3" data-testid="erosion-result">
          <Card className="border-stone-200">
            <CardHeader className="pb-2">
              <CardTitle className="flex items-center gap-2 text-sm">
                {t('screeningTitle')} <Badge variant="outline" className="px-1.5 py-0 text-[10px]">{t('screeningBadge')}</Badge>
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-2 text-xs text-stone-600">
              {run.result.screening.concerns.length === 0 ? (
                <HonestEmpty>{t('noConcerns', { count: run.result.screening.unknowns.length })}</HonestEmpty>
              ) : (
                run.result.screening.concerns.map((c, i) => (
                  <div key={i} className="flex items-start gap-2">
                    <span className="mt-1 h-1.5 w-1.5 shrink-0 rounded-full bg-amber-500" aria-hidden />
                    <span>{c.evidence} <span className="text-stone-400">({c.processes.join(', ')})</span></span>
                  </div>
                ))
              )}
              {run.result.screening.field_observed_signs.length > 0 ? (
                <div className="rounded-md border border-stone-200 bg-stone-50 p-2">
                  <p className="font-medium text-stone-700">{t('observedSigns')}</p>
                  {run.result.screening.field_observed_signs.map((s, i) => <p key={i}>{s.description}</p>)}
                </div>
              ) : null}
              {run.result.screening.unknowns.length > 0 && expert ? (
                <ul className="space-y-0.5 text-[11px] text-stone-500">
                  {run.result.screening.unknowns.map((u, i) => <li key={i}>· {u}</li>)}
                </ul>
              ) : null}
            </CardContent>
          </Card>

          {run.result.rusle.status !== 'not_evaluated' ? (
            <Card className="border-stone-200">
              <CardHeader className="pb-2">
                <CardTitle className="text-sm">{t('rusleTitle')}</CardTitle>
                <CardDescription>
                  {run.result.rusle.annual_soil_loss_a !== undefined
                    ? t('rusleEstimate', {
                        value: run.result.rusle.annual_soil_loss_a,
                        unit: run.result.rusle.unit_convention ?? '',
                      })
                    : run.result.rusle.message}
                </CardDescription>
              </CardHeader>
              {expert && run.result.rusle.scope_disclosures ? (
                <CardContent>
                  <ul className="space-y-0.5 text-[11px] text-stone-500">
                    {run.result.rusle.scope_disclosures.map((d, i) => <li key={i}>· {d}</li>)}
                  </ul>
                </CardContent>
              ) : null}
            </Card>
          ) : null}

          {run.result.alternatives.length > 0 ? (
            <Card className="border-stone-200">
              <CardHeader className="pb-2">
                <CardTitle className="text-sm">{t('alternativesTitle')}</CardTitle>
              </CardHeader>
              <CardContent>
                <Accordion type="single" collapsible className="w-full">
                  {run.result.alternatives.map((a) => (
                    <AccordionItem key={a.practice_code} value={a.practice_code}>
                      <AccordionTrigger className="text-xs">{a.name}</AccordionTrigger>
                      <AccordionContent className="space-y-1 text-[11px] text-stone-600">
                        {a.mechanisms.map((m, i) => (
                          <p key={i}>· {m.text} {m.citation ? <span className="text-stone-400">— {m.citation.citation_text}</span> : null}</p>
                        ))}
                        <p className="text-stone-400">{a.quantitative_note}</p>
                      </AccordionContent>
                    </AccordionItem>
                  ))}
                </Accordion>
              </CardContent>
            </Card>
          ) : null}
        </div>
      ) : null}
    </div>
  )
}

// ------------------------------------------------------------ operations view

function OperationsView({ fieldId, farmId, expert }: { fieldId: string; farmId: string | null; expert: boolean }) {
  const t = useTranslations('management')
  const qc = useQueryClient()
  const [crop, setCrop] = useState('')
  const [hoursPerDay, setHoursPerDay] = useState('8')
  const [resourceType, setResourceType] = useState('tractor')
  const [resourceName, setResourceName] = useState('')
  const [schedule, setSchedule] = useState<ScheduleRun | null>(null)
  const [error, setError] = useState<unknown>(null)

  const ops = useQuery({
    queryKey: ['operations', fieldId],
    queryFn: () => listFieldOperations(fieldId),
    enabled: Boolean(fieldId),
  })
  const resources = useQuery({
    queryKey: ['resources', farmId],
    queryFn: () => listFarmResources(farmId as string),
    enabled: Boolean(farmId),
  })
  const templates = useQuery({
    queryKey: ['operation-templates'],
    queryFn: listOperationTemplates,
  })

  const generate = useMutation({
    mutationFn: () => generateOperations(fieldId, { crop_label: crop, window_year: new Date().getFullYear() + 1 }),
    onSuccess: () => {
      setError(null)
      qc.invalidateQueries({ queryKey: ['operations', fieldId] })
    },
    onError: setError,
  })
  const addResource = useMutation({
    mutationFn: () => createFarmResource(farmId as string, { resource_type: resourceType, name: resourceName || resourceType }),
    onSuccess: () => {
      setError(null)
      setResourceName('')
      qc.invalidateQueries({ queryKey: ['resources', farmId] })
    },
    onError: setError,
  })
  const scheduleRun = useMutation({
    mutationFn: () =>
      createScheduleRun(fieldId, { hours_per_workday: Number(hoursPerDay) || undefined }),
    onSuccess: (r) => {
      setSchedule(r)
      setError(null)
      qc.invalidateQueries({ queryKey: ['operations', fieldId] })
    },
    onError: setError,
  })
  const complete = useMutation({
    mutationFn: (opId: string) => patchOperation(opId, { status: 'completed', completion_date: today() }),
    onSuccess: () => {
      setError(null)
      qc.invalidateQueries({ queryKey: ['operations', fieldId] })
    },
    onError: setError,
  })

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end gap-2">
        <div className="space-y-1">
          <Label htmlFor="gen-crop" className="text-xs">{t('generateCropLabel')}</Label>
          <Input id="gen-crop" value={crop} onChange={(e) => setCrop(e.target.value)} placeholder={t('cropPlaceholder')} className="h-9 w-40 text-sm" />
        </div>
        <Button variant="outline" className="h-9" onClick={() => generate.mutate()} disabled={generate.isPending || !crop}>
          {generate.isPending ? t('generating') : t('generateFromTemplates')}
        </Button>
        <div className="space-y-1">
          <Label htmlFor="hpd" className="text-xs">{t('hoursLabel')}</Label>
          <Input id="hpd" type="number" min="1" value={hoursPerDay} onChange={(e) => setHoursPerDay(e.target.value)} className="h-9 w-24 text-sm" />
        </div>
        <Button onClick={() => scheduleRun.mutate()} disabled={scheduleRun.isPending} className="bg-emerald-700 hover:bg-emerald-800">
          {scheduleRun.isPending ? t('scheduling') : t('scheduleOps')}
        </Button>
      </div>
      <ErrorNote error={error ?? ops.error} />

      <div className="grid gap-3 lg:grid-cols-2">
        <Card className="border-stone-200">
          <CardHeader className="pb-2">
            <CardTitle className="text-sm">{t('opsTitle')}</CardTitle>
            <CardDescription>
              {t('opsDesc')}
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-2">
            {ops.isLoading ? <Skeleton className="h-24 w-full" /> : null}
            {ops.data && ops.data.items.length === 0 ? (
              <HonestEmpty>{t('noOpsYet')}</HonestEmpty>
            ) : null}
            {ops.data?.items.map((op) => {
              const entry = schedule?.result.entries.find((e) => e.operation_id === op.id)
              return (
                <div key={op.id} className="rounded-lg border border-stone-100 p-2 text-xs">
                  <div className="flex flex-wrap items-center gap-2">
                    <StatusBadge status={op.status} />
                    <span className="font-medium text-stone-800">{op.title}</span>
                    <span className="text-stone-500">
                      {op.scheduled_start ?? op.earliest_start ?? t('noWindow')}
                      {op.scheduled_end ?? op.latest_finish ? ` → ${op.scheduled_end ?? op.latest_finish}` : ''}
                    </span>
                    {op.status !== 'completed' ? (
                      <Button size="sm" variant="ghost" className="ml-auto h-6 px-2 text-[11px]" onClick={() => complete.mutate(op.id)} disabled={complete.isPending}>
                        {t('markDone')}
                      </Button>
                    ) : null}
                  </div>
                  {entry && entry.status === 'unscheduled' && entry.reason ? (
                    <p className="mt-1 text-[11px] text-amber-800">{entry.reason}</p>
                  ) : null}
                  {op.status_reason ? <p className="mt-1 text-[11px] text-amber-800">{op.status_reason}</p> : null}
                </div>
              )
            })}
          </CardContent>
        </Card>

        <Card className="border-stone-200">
          <CardHeader className="pb-2">
            <CardTitle className="text-sm">{t('resourcesTitle')}</CardTitle>
            <CardDescription>{t('resourcesDesc')}</CardDescription>
          </CardHeader>
          <CardContent className="space-y-2">
            <div className="flex flex-wrap items-end gap-2">
              <div className="space-y-1">
                <Label htmlFor="res-type" className="text-xs">{t('typeLabel')}</Label>
                <Select value={resourceType} onValueChange={setResourceType}>
                  <SelectTrigger id="res-type" className="h-9 w-36 text-sm"><SelectValue /></SelectTrigger>
                  <SelectContent>
                    <SelectItem value="tractor">{t('resTractor')}</SelectItem>
                    <SelectItem value="implement">{t('resImplement')}</SelectItem>
                    <SelectItem value="seeder">{t('resSeeder')}</SelectItem>
                    <SelectItem value="sprayer">{t('resSprayer')}</SelectItem>
                    <SelectItem value="harvester">{t('resHarvester')}</SelectItem>
                    <SelectItem value="baler">{t('resBaler')}</SelectItem>
                    <SelectItem value="contractor">{t('resContractor')}</SelectItem>
                    <SelectItem value="labor_crew">{t('resLabourCrew')}</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-1">
                <Label htmlFor="res-name" className="text-xs">{t('nameLabel')}</Label>
                <Input id="res-name" value={resourceName} onChange={(e) => setResourceName(e.target.value)} placeholder={t('namePlaceholder')} className="h-9 w-36 text-sm" />
              </div>
              <Button size="sm" variant="outline" className="h-9" onClick={() => addResource.mutate()} disabled={addResource.isPending || !farmId}>
                {t('addResource')}
              </Button>
            </div>
            {resources.data?.items.length ? (
              <div className="flex flex-wrap gap-1">
                {resources.data.items.map((r) => (
                  <Badge key={r.id} variant="outline" className="px-1.5 py-0 text-[10px]">{r.name}</Badge>
                ))}
              </div>
            ) : (
              <HonestEmpty>{t('noResources')}</HonestEmpty>
            )}
            {schedule ? (
              <div className="border-t border-stone-100 pt-2 text-[11px] text-stone-600">
                <p className="font-medium text-stone-700">{t('lastSchedule')}</p>
                <p>
                  {t('scheduleSummary', {
                    status: schedule.result.solver.status,
                    scheduled: schedule.result.entries.filter((e) => e.status === 'scheduled').length,
                    unscheduled: schedule.result.entries.filter((e) => e.status === 'unscheduled').length,
                  })}
                </p>
                <p className="text-stone-500">
                  {t('weatherPending')}
                </p>
                {schedule.result.conflicts.map((c, i) => (
                  <p key={i} className="text-red-700">{c.message}</p>
                ))}
              </div>
            ) : null}
            {expert && templates.data ? (
              <p className="text-[11px] text-stone-400">
                {t('templatePack', {
                  total: templates.data.total,
                  status: templates.data.operation_templates[0]?.validation_status ?? '—',
                })}
              </p>
            ) : null}
          </CardContent>
        </Card>
      </div>
    </div>
  )
}
