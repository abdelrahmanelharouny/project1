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
import { FieldPicker } from '@/components/fieldshift/field-picker'
import { SyntheticBadge } from '@/components/fieldshift/badges'
import { useFieldShiftUi } from '@/lib/store'
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
  { value: 'plan', label: 'Overview', icon: <Sprout className="h-3.5 w-3.5" aria-hidden /> },
  { value: 'covers', label: 'Cover Crops', icon: <Leaf className="h-3.5 w-3.5" aria-hidden /> },
  { value: 'timeline', label: 'Soil Cover', icon: <Layers className="h-3.5 w-3.5" aria-hidden /> },
  { value: 'residue', label: 'Residue', icon: <Recycle className="h-3.5 w-3.5" aria-hidden /> },
  { value: 'erosion', label: 'Erosion', icon: <ShieldAlert className="h-3.5 w-3.5" aria-hidden /> },
  { value: 'operations', label: 'Operations', icon: <CalendarDays className="h-3.5 w-3.5" aria-hidden /> },
] as const

type SubView = (typeof SUB_VIEWS)[number]['value']

export function Management() {
  const selectedField = useFieldShiftUi((s) => s.selectedField)
  const setSelectedField = useFieldShiftUi((s) => s.setSelectedField)
  const selectedFarmId = useFieldShiftUi((s) => s.selectedFarmId)
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
                Field management
              </CardTitle>
              <CardDescription>
                Cover crops, soil cover, residues, erosion screening and the
                operations calendar — every recommendation discloses its
                evidence, and missing knowledge stays missing.
              </CardDescription>
            </div>
            <div className="flex items-center gap-2 text-xs text-stone-500">
              <span aria-hidden>Simple</span>
              <Switch checked={expert} onCheckedChange={setExpert} aria-label="Toggle expert mode" />
              <span aria-hidden>Expert</span>
            </div>
          </div>
        </CardHeader>
        <CardContent className="space-y-3">
          <FieldPicker
            value={selectedField?.id ?? null}
            onValueChange={setSelectedField}
            emptyHint={
              <p className="text-sm text-stone-500">
                Create a farm and field first — management planning is field-based.
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
                      {s.label}
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
            <HonestEmpty>Pick a field above to see its management plan.</HonestEmpty>
          )}
        </CardContent>
      </Card>
    </div>
  )
}

// ------------------------------------------------------------ plan view

function PlanView({ fieldId, expert }: { fieldId: string; expert: boolean }) {
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
          Build a seasonal management overview for this field: what grew, where
          the soil is exposed, what is planned, and what needs your attention.
        </p>
        <Button onClick={() => createPlan.mutate()} disabled={createPlan.isPending} className="bg-emerald-700 hover:bg-emerald-800">
          {createPlan.isPending ? 'Building…' : 'Build management plan'}
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
        <Metric label="Protective cover" value={`${m.days_protective_cover} d`} hint={`of ${m.window_days} days`} />
        <Metric label="Known bare" value={`${m.days_known_bare} d`} hint={m.longest_bare_interval ? `longest ${m.longest_bare_interval_days} d` : 'no bare evidence'} />
        <Metric label="Unknown" value={`${m.days_unknown} d`} hint="never counted as bare" />
        <Metric label="Open checks" value={r.checks.length} hint="items needing attention" />
      </div>

      <Accordion type="multiple" defaultValue={['checks', 'season']} className="w-full">
        <AccordionItem value="season">
          <AccordionTrigger className="text-sm">
            Season context <StatusBadge status={r.season_context.status} />
          </AccordionTrigger>
          <AccordionContent className="space-y-2 text-sm text-stone-600">
            {r.season_context.recent_crop_history.length === 0 ? (
              <HonestEmpty>{r.season_context.message ?? 'No crop history recorded.'}</HonestEmpty>
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
          <AccordionTrigger className="text-sm">Unresolved agronomic checks</AccordionTrigger>
          <AccordionContent className="space-y-2">
            {r.checks.length === 0 ? (
              <p className="text-sm text-emerald-800">No open checks — data coverage is good.</p>
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
          <AccordionTrigger className="text-sm">Module status</AccordionTrigger>
          <AccordionContent>
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
              {[
                { label: 'Cover crops', ...r.cover_crop },
                { label: 'Residue', ...r.residue },
                { label: 'Erosion', ...r.erosion },
                { label: 'Operations', ...r.operations },
                { label: 'Water (M6A)', ...r.water },
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
          <AccordionTrigger className="text-sm">Next operations</AccordionTrigger>
          <AccordionContent className="space-y-1">
            {r.operations.next_operations.length === 0 ? (
              <HonestEmpty>{r.operations.message ?? 'No operations recorded.'}</HonestEmpty>
            ) : (
              r.operations.next_operations.map((o) => (
                <div key={o.id} className="flex flex-wrap items-center gap-2 text-xs">
                  <StatusBadge status={o.status} />
                  <span className="font-medium text-stone-800">{o.title}</span>
                  <span className="text-stone-500">
                    {o.scheduled_start ?? o.earliest_start ?? 'no window'} … {o.scheduled_end ?? o.latest_finish ?? ''}
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
              <AccordionTrigger className="text-sm">Practice guidance (cited, reference knowledge)</AccordionTrigger>
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
              <AccordionTrigger className="text-sm">Provenance & versions</AccordionTrigger>
              <AccordionContent className="space-y-1 text-xs text-stone-600">
                <p>Engine: {plan.engine_version}</p>
                <p className="break-all">Checksum: <span className="font-mono">{plan.checksum_sha256}</span></p>
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
        Evaluate cover-crop candidates for a window. Missing knowledge (no
        regional calendar, no water curve, no termination guidance) keeps a
        candidate <span className="font-medium">conditional</span> — it is
        never presented as a proven recommendation.
      </p>
      <div className="grid gap-2 sm:grid-cols-4">
        <div className="space-y-1">
          <Label htmlFor="cover-start" className="text-xs">Window start</Label>
          <Input id="cover-start" type="date" value={windowStart} onChange={(e) => setWindowStart(e.target.value)} className="h-9 text-sm" />
        </div>
        <div className="space-y-1">
          <Label htmlFor="cover-end" className="text-xs">Window end</Label>
          <Input id="cover-end" type="date" value={windowEnd} onChange={(e) => setWindowEnd(e.target.value)} className="h-9 text-sm" />
        </div>
        <div className="space-y-1">
          <Label htmlFor="cover-next" className="text-xs">Next crop (optional)</Label>
          <Input id="cover-next" value={nextCrop} onChange={(e) => setNextCrop(e.target.value)} placeholder="e.g. maize" className="h-9 text-sm" />
        </div>
        <div className="flex items-end">
          <Button onClick={() => run.mutate()} disabled={run.isPending} className="w-full bg-emerald-700 hover:bg-emerald-800">
            {run.isPending ? 'Evaluating…' : 'Evaluate candidates'}
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
              No cover-crop-capable species in the active knowledge base could be
              evaluated — an honest empty result.
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
                        <Badge variant="outline" className="border-emerald-300 bg-emerald-50 px-1.5 py-0 text-[10px] text-emerald-800">in plan</Badge>
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
                    <p className="text-[11px]">Sowing window (reference): {c.sowing_window[0]} → {c.sowing_window[1]}</p>
                  ) : null}
                  {expert ? (
                    <Accordion type="single" collapsible className="w-full">
                      <AccordionItem value="dims">
                        <AccordionTrigger className="text-xs">Dimension detail</AccordionTrigger>
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
                      Adopt into plan
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
          <p className="text-xs font-semibold text-stone-700">Adopted cover decisions</p>
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
          <Label htmlFor="tl-start" className="text-xs">From</Label>
          <Input id="tl-start" type="date" value={start} onChange={(e) => setStart(e.target.value)} className="h-9 text-sm" />
        </div>
        <div className="space-y-1">
          <Label htmlFor="tl-end" className="text-xs">To</Label>
          <Input id="tl-end" type="date" value={end} onChange={(e) => setEnd(e.target.value)} className="h-9 text-sm" />
        </div>
      </div>

      {timeline.isLoading ? <Skeleton className="h-40 w-full" /> : null}
      <ErrorNote error={timeline.error} />

      {data ? (
        <div className="space-y-3">
          <div className="flex flex-wrap gap-3 text-[11px] text-stone-600">
            <span className="flex items-center gap-1"><span className={`inline-block h-2.5 w-2.5 rounded ${CLASS_COLOR.protective}`} aria-hidden /> protective cover</span>
            <span className="flex items-center gap-1"><span className={`inline-block h-2.5 w-2.5 rounded ${CLASS_COLOR.bare}`} aria-hidden /> known bare</span>
            <span className="flex items-center gap-1"><span className={`inline-block h-2.5 w-2.5 rounded ${CLASS_COLOR.unknown}`} aria-hidden /> unknown (not bare)</span>
          </div>

          {/* timeline strip: one cell per day (wrapped, labeled by month) */}
          <div className="overflow-hidden rounded-lg border border-stone-200 p-2">
            <div className="flex flex-wrap gap-px" role="img" aria-label="Daily soil cover status strip">
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
            <Metric label="Protective" value={`${data.metrics.days_protective_cover} d`} />
            <Metric label="Known bare" value={`${data.metrics.days_known_bare} d`} />
            <Metric label="Unknown" value={`${data.metrics.days_unknown} d`} />
            <Metric
              label="Longest bare"
              value={data.metrics.longest_bare_interval_days ? `${data.metrics.longest_bare_interval_days} d` : '—'}
              hint={data.metrics.longest_bare_interval ? data.metrics.longest_bare_interval.join(' → ') : 'no bare evidence'}
            />
          </div>

          <p className="text-[11px] text-stone-500">{data.thresholds.note}</p>

          <Separator />

          <div className="space-y-2">
            <p className="text-xs font-semibold text-stone-700">Record a cover observation</p>
            <div className="flex flex-wrap items-end gap-2">
              <div className="space-y-1">
                <Label htmlFor="obs-date" className="text-xs">Date</Label>
                <Input id="obs-date" type="date" value={obsDate} onChange={(e) => setObsDate(e.target.value)} className="h-9 text-sm" />
              </div>
              <div className="space-y-1">
                <Label htmlFor="obs-state" className="text-xs">Observed state</Label>
                <Select value={obsState} onValueChange={setObsState}>
                  <SelectTrigger id="obs-state" className="h-9 w-44 text-sm"><SelectValue /></SelectTrigger>
                  <SelectContent>
                    <SelectItem value="bare">Bare soil</SelectItem>
                    <SelectItem value="living_main_crop">Living main crop</SelectItem>
                    <SelectItem value="living_cover_crop">Living cover crop</SelectItem>
                    <SelectItem value="surface_residue">Surface residue</SelectItem>
                    <SelectItem value="mulch">Mulch</SelectItem>
                    <SelectItem value="unknown">Unknown</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <Button size="sm" variant="outline" className="h-9" onClick={() => addObs.mutate()} disabled={addObs.isPending}>
                {addObs.isPending ? 'Saving…' : 'Add observation'}
              </Button>
            </div>
            <ErrorNote error={error} />
          </div>

          {expert ? (
            <Accordion type="single" collapsible>
              <AccordionItem value="method">
                <AccordionTrigger className="text-xs">Method & evidence notes</AccordionTrigger>
                <AccordionContent className="space-y-1 text-[11px] text-stone-600">
                  <p>{data.method.engine} · {data.method.version}</p>
                  {data.method.rules.map((r, i) => <p key={i}>· {r}</p>)}
                  {data.evidence_notes.map((n, i) => <p key={i} className="text-amber-800">· {n.detail}</p>)}
                  <p>Inputs: {Object.entries(data.inputs_summary).map(([k, v]) => `${k}=${v}`).join(' · ')}</p>
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
        Residue flows on a dry-matter basis. Mass balance is enforced: flows
        above production are a hard error, and unknown production is never
        assumed to be zero.
      </p>

      <div className="flex flex-wrap items-end gap-2">
        <div className="space-y-1">
          <Label htmlFor="res-crop" className="text-xs">Crop</Label>
          <Input id="res-crop" value={crop} onChange={(e) => setCrop(e.target.value)} placeholder="e.g. maize" className="h-9 w-40 text-sm" />
        </div>
        <div className="space-y-1">
          <Label htmlFor="res-prod" className="text-xs">Produced DM (kg, optional)</Label>
          <Input id="res-prod" type="number" min="0" value={produced} onChange={(e) => setProduced(e.target.value)} className="h-9 w-44 text-sm" />
        </div>
        <Button variant="outline" className="h-9" onClick={() => addRecord.mutate()} disabled={addRecord.isPending || !crop}>
          {addRecord.isPending ? 'Saving…' : 'Add residue record'}
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
            <HonestEmpty>No residue records yet — add one above after harvest.</HonestEmpty>
          ) : (
            data.records.map((rec) => (
              <Card key={rec.record.id} className="border-stone-200">
                <CardHeader className="pb-2">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <CardTitle className="text-sm">{rec.record.crop_label}</CardTitle>
                    <StatusBadge status={rec.balance.status} />
                  </div>
                  <CardDescription>
                    produced {rec.record.produced_dm_kg !== null ? `${rec.record.produced_dm_kg} kg DM` : 'unknown'} ·
                    {' '}{rec.record.production_status.replace(/_/g, ' ')}
                  </CardDescription>
                </CardHeader>
                <CardContent className="space-y-2 text-xs text-stone-600">
                  {rec.flows.map((f) => (
                    <div key={f.id} className="flex flex-wrap items-center gap-2">
                      <Badge variant="outline" className="px-1.5 py-0 text-[10px]">{f.flow_type.replace(/_/g, ' ')}</Badge>
                      <span>{f.dm_kg !== null ? `${f.dm_kg} kg` : 'mass unknown'}</span>
                      <span className="text-stone-400">{f.dm_kg_status}</span>
                    </div>
                  ))}
                  <p>
                    Σ flows {rec.balance.total_flow_dm_kg} kg · unaccounted{' '}
                    {rec.balance.unaccounted_dm_kg !== null ? `${rec.balance.unaccounted_dm_kg} kg` : 'not computable'}
                  </p>
                  {expert && rec.derived.total_nitrogen_kg !== undefined ? (
                    <p className="text-[11px]">
                      Nitrogen in flows ≈ {String(rec.derived.total_nitrogen_kg)} kg (bookkeeping — not counted in the
                      M6B nutrient budget; no SOC claim)
                    </p>
                  ) : null}
                  {targetRecord === rec.record.id ? (
                    <div className="flex flex-wrap items-end gap-2 border-t border-stone-100 pt-2">
                      <div className="space-y-1">
                        <Label htmlFor={`flow-type-${rec.record.id}`} className="text-xs">Flow</Label>
                        <Select value={flowType} onValueChange={setFlowType}>
                          <SelectTrigger id={`flow-type-${rec.record.id}`} className="h-9 w-44 text-sm"><SelectValue /></SelectTrigger>
                          <SelectContent>
                            <SelectItem value="retained_surface">Retained on surface</SelectItem>
                            <SelectItem value="incorporated">Incorporated</SelectItem>
                            <SelectItem value="removed_baled">Removed / baled</SelectItem>
                            <SelectItem value="grazed">Grazed</SelectItem>
                            <SelectItem value="burned">Burned</SelectItem>
                            <SelectItem value="other_loss">Other loss</SelectItem>
                            <SelectItem value="unknown">Unknown fate</SelectItem>
                          </SelectContent>
                        </Select>
                      </div>
                      <div className="space-y-1">
                        <Label htmlFor={`flow-kg-${rec.record.id}`} className="text-xs">DM kg (optional)</Label>
                        <Input id={`flow-kg-${rec.record.id}`} type="number" min="0" value={flowKg} onChange={(e) => setFlowKg(e.target.value)} className="h-9 w-36 text-sm" />
                      </div>
                      <Button size="sm" variant="outline" className="h-9" onClick={() => addFlow.mutate()} disabled={addFlow.isPending}>
                        Add flow
                      </Button>
                    </div>
                  ) : (
                    <Button size="sm" variant="ghost" className="h-7 text-xs" onClick={() => setTargetRecord(rec.record.id)}>
                      Add flow to this record
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
        Two separate outputs: a <span className="font-medium">screening</span>{' '}
        from your field records (never a soil-loss number), and an optional
        sheet-&amp;-rill calculation that runs <span className="font-medium">only</span> when
        you supply all five sourced factors. Gully, wind and channel processes
        are out of scope for this platform.
      </p>

      <div className="flex flex-wrap items-end gap-2">
        <div className="space-y-1">
          <Label htmlFor="slope" className="text-xs">Slope class (from your knowledge)</Label>
          <Select value={slopeClass} onValueChange={setSlopeClass}>
            <SelectTrigger id="slope" className="h-9 w-40 text-sm"><SelectValue /></SelectTrigger>
            <SelectContent>
              <SelectItem value="unknown">Not declared</SelectItem>
              <SelectItem value="flat">Flat</SelectItem>
              <SelectItem value="gentle">Gentle</SelectItem>
              <SelectItem value="moderate">Moderate</SelectItem>
              <SelectItem value="steep">Steep</SelectItem>
            </SelectContent>
          </Select>
        </div>
        <div className="flex items-center gap-2 pb-2 text-xs text-stone-500">
          <Switch checked={useRusle} onCheckedChange={setUseRusle} aria-label="Include RUSLE factors" id="rusle-toggle" />
          <Label htmlFor="rusle-toggle" className="text-xs">I have sourced R·K·LS·C·P factors</Label>
        </div>
        {useRusle ? (
          <div className="space-y-1">
            <Label htmlFor="factor-src" className="text-xs">Factor source</Label>
            <Input id="factor-src" value={factorSource} onChange={(e) => setFactorSource(e.target.value)} placeholder="e.g. county soil survey 2024" className="h-9 w-52 text-sm" />
          </div>
        ) : null}
        <Button onClick={() => assess.mutate()} disabled={assess.isPending} className="bg-emerald-700 hover:bg-emerald-800">
          {assess.isPending ? 'Assessing…' : 'Run assessment'}
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
                Screening <Badge variant="outline" className="px-1.5 py-0 text-[10px]">screening only — not a soil-loss prediction</Badge>
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-2 text-xs text-stone-600">
              {run.result.screening.concerns.length === 0 ? (
                <HonestEmpty>No evidence of concern found in the field records. Unknowns: {run.result.screening.unknowns.length}</HonestEmpty>
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
                  <p className="font-medium text-stone-700">Your observed erosion signs</p>
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
                <CardTitle className="text-sm">Sheet &amp; rill estimate (RUSLE-family)</CardTitle>
                <CardDescription>
                  {run.result.rusle.annual_soil_loss_a !== undefined
                    ? `A ≈ ${run.result.rusle.annual_soil_loss_a} (${run.result.rusle.unit_convention} native unit) — screening grade, sheet & rill only`
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
                <CardTitle className="text-sm">Conservation alternatives (cited mechanisms — not a ranking)</CardTitle>
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
          <Label htmlFor="gen-crop" className="text-xs">Generate operations for crop</Label>
          <Input id="gen-crop" value={crop} onChange={(e) => setCrop(e.target.value)} placeholder="e.g. maize" className="h-9 w-40 text-sm" />
        </div>
        <Button variant="outline" className="h-9" onClick={() => generate.mutate()} disabled={generate.isPending || !crop}>
          {generate.isPending ? 'Generating…' : 'Generate from templates'}
        </Button>
        <div className="space-y-1">
          <Label htmlFor="hpd" className="text-xs">Hours per workday</Label>
          <Input id="hpd" type="number" min="1" value={hoursPerDay} onChange={(e) => setHoursPerDay(e.target.value)} className="h-9 w-24 text-sm" />
        </div>
        <Button onClick={() => scheduleRun.mutate()} disabled={scheduleRun.isPending} className="bg-emerald-700 hover:bg-emerald-800">
          {scheduleRun.isPending ? 'Scheduling…' : 'Schedule operations'}
        </Button>
      </div>
      <ErrorNote error={error ?? ops.error} />

      <div className="grid gap-3 lg:grid-cols-2">
        <Card className="border-stone-200">
          <CardHeader className="pb-2">
            <CardTitle className="text-sm">Operations</CardTitle>
            <CardDescription>
              Planned work derived from cited templates. Durations are yours to
              supply — the engine invents none, and nothing unscheduled is
              hidden.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-2">
            {ops.isLoading ? <Skeleton className="h-24 w-full" /> : null}
            {ops.data && ops.data.items.length === 0 ? (
              <HonestEmpty>No operations yet — generate them for a crop above.</HonestEmpty>
            ) : null}
            {ops.data?.items.map((op) => {
              const entry = schedule?.result.entries.find((e) => e.operation_id === op.id)
              return (
                <div key={op.id} className="rounded-lg border border-stone-100 p-2 text-xs">
                  <div className="flex flex-wrap items-center gap-2">
                    <StatusBadge status={op.status} />
                    <span className="font-medium text-stone-800">{op.title}</span>
                    <span className="text-stone-500">
                      {op.scheduled_start ?? op.earliest_start ?? 'no window'}
                      {op.scheduled_end ?? op.latest_finish ? ` → ${op.scheduled_end ?? op.latest_finish}` : ''}
                    </span>
                    {op.status !== 'completed' ? (
                      <Button size="sm" variant="ghost" className="ml-auto h-6 px-2 text-[11px]" onClick={() => complete.mutate(op.id)} disabled={complete.isPending}>
                        Mark done
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
            <CardTitle className="text-sm">Machinery & labour</CardTitle>
            <CardDescription>Your resources — capacity is never assumed.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-2">
            <div className="flex flex-wrap items-end gap-2">
              <div className="space-y-1">
                <Label htmlFor="res-type" className="text-xs">Type</Label>
                <Select value={resourceType} onValueChange={setResourceType}>
                  <SelectTrigger id="res-type" className="h-9 w-36 text-sm"><SelectValue /></SelectTrigger>
                  <SelectContent>
                    <SelectItem value="tractor">Tractor</SelectItem>
                    <SelectItem value="implement">Implement</SelectItem>
                    <SelectItem value="seeder">Seeder</SelectItem>
                    <SelectItem value="sprayer">Sprayer</SelectItem>
                    <SelectItem value="harvester">Harvester</SelectItem>
                    <SelectItem value="baler">Baler</SelectItem>
                    <SelectItem value="contractor">Contractor</SelectItem>
                    <SelectItem value="labor_crew">Labour crew</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-1">
                <Label htmlFor="res-name" className="text-xs">Name</Label>
                <Input id="res-name" value={resourceName} onChange={(e) => setResourceName(e.target.value)} placeholder="e.g. Ford 5000" className="h-9 w-36 text-sm" />
              </div>
              <Button size="sm" variant="outline" className="h-9" onClick={() => addResource.mutate()} disabled={addResource.isPending || !farmId}>
                Add
              </Button>
            </div>
            {resources.data?.items.length ? (
              <div className="flex flex-wrap gap-1">
                {resources.data.items.map((r) => (
                  <Badge key={r.id} variant="outline" className="px-1.5 py-0 text-[10px]">{r.name}</Badge>
                ))}
              </div>
            ) : (
              <HonestEmpty>No resources registered — scheduling will report every operation as unscheduled.</HonestEmpty>
            )}
            {schedule ? (
              <div className="border-t border-stone-100 pt-2 text-[11px] text-stone-600">
                <p className="font-medium text-stone-700">Last schedule run</p>
                <p>
                  {schedule.result.solver.status} ·{' '}
                  {schedule.result.entries.filter((e) => e.status === 'scheduled').length} scheduled ·{' '}
                  {schedule.result.entries.filter((e) => e.status === 'unscheduled').length} unscheduled
                </p>
                <p className="text-stone-500">
                  Weather checks pending (no forecast provider) · soil readiness is a manual check.
                </p>
                {schedule.result.conflicts.map((c, i) => (
                  <p key={i} className="text-red-700">{c.message}</p>
                ))}
              </div>
            ) : null}
            {expert && templates.data ? (
              <p className="text-[11px] text-stone-400">
                Template pack: {templates.data.total} templates · validation status {templates.data.operation_templates[0]?.validation_status ?? '—'}
              </p>
            ) : null}
          </CardContent>
        </Card>
      </div>
    </div>
  )
}
