'use client'

import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import {
  AlertTriangle,
  BookOpen,
  CheckCircle2,
  ChevronRight,
  GitCompareArrows,
  Info,
  Loader2,
  Scale,
  Sprout,
  XCircle,
} from 'lucide-react'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card'
import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from '@/components/ui/accordion'
import { Checkbox } from '@/components/ui/checkbox'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { FieldPicker } from '@/components/fieldshift/field-picker'
import { SyntheticBadge } from '@/components/fieldshift/badges'
import {
  useCropHistory,
  useKnowledgeCrops,
  useKnowledgePacks,
  useKnowledgePackSources,
  useRotationComparison,
  useRotationRules,
  useRotationRun,
  useRotationRuns,
} from '@/hooks/use-fieldshift'
import {
  addCropHistory,
  createRotationRun,
  describeError,
  generateCropCandidates,
} from '@/lib/api'
import { useFieldShiftUi, type SelectedField } from '@/lib/store'
import type {
  CandidateAssessment,
  CandidateSeason,
  RotationStrategy,
} from '@/lib/types'
import { cn } from '@/lib/utils'

const PROFILE_OPTIONS = [
  { value: 'water_priority', label: 'Water priority' },
  { value: 'soil_health_priority', label: 'Soil health priority' },
  { value: 'balanced', label: 'Balanced' },
  { value: 'economic_priority', label: 'Economic priority' },
] as const

interface SeasonWindow {
  label: string
  start: string
  end: string
}

function fmt(value: number | null | undefined, digits = 2): string {
  if (value === null || value === undefined) return '—'
  return value.toLocaleString(undefined, { maximumFractionDigits: digits })
}

function CandidateStatusBadge({ status }: { status: CandidateAssessment['status'] }) {
  const map: Record<CandidateAssessment['status'], { cls: string; label: string }> = {
    eligible: { cls: 'border-emerald-200 bg-emerald-50 text-emerald-800', label: 'Eligible' },
    conditionally_eligible: { cls: 'border-amber-200 bg-amber-50 text-amber-900', label: 'Conditional' },
    excluded: { cls: 'border-red-200 bg-red-50 text-red-800', label: 'Excluded' },
    unevaluated: { cls: 'border-stone-300 bg-stone-100 text-stone-600', label: 'Unevaluated' },
  }
  const it = map[status]
  return (
    <Badge variant="outline" className={cn('font-normal', it.cls)}>
      {it.label}
    </Badge>
  )
}

// --------------------------------------------------------- crop history

function CropHistoryCard({ selectedField }: { selectedField: SelectedField }) {
  const history = useCropHistory(selectedField.id)
  const queryClient = useQueryClient()
  const [cropCode, setCropCode] = useState('')
  const [label, setLabel] = useState('')
  const [sowing, setSowing] = useState('')
  const [harvest, setHarvest] = useState('')
  const [seasonLabel, setSeasonLabel] = useState('')

  const crops = useKnowledgeCrops()

  const addMutation = useMutation({
    mutationFn: () =>
      addCropHistory(selectedField.id, {
        crop_code: cropCode || null,
        crop_label: label || cropCode || 'Unnamed crop',
        sowing_date: sowing || null,
        harvest_date: harvest || null,
        season_label: seasonLabel || null,
      }),
    onSuccess: () => {
      toast.success('Crop history entry added.')
      setCropCode('')
      setLabel('')
      setSowing('')
      setHarvest('')
      setSeasonLabel('')
      void queryClient.invalidateQueries({ queryKey: ['crop-history', selectedField.id] })
    },
    onError: (err) => {
      const d = describeError(err)
      toast.error(d.title, { description: d.description })
    },
  })

  const items = history.data?.items ?? []

  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="flex items-center gap-2 text-base">
          <Sprout className="h-4 w-4 text-emerald-700" aria-hidden />
          Crop history (rotation baseline)
        </CardTitle>
        <CardDescription>
          What actually grew here. The current rotation is preserved as the labelled
          baseline in every optimization run.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        {history.isLoading ? (
          <div className="flex items-center gap-2 text-sm text-stone-500">
            <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> Loading…
          </div>
        ) : items.length === 0 ? (
          <p className="text-sm text-stone-500">
            No crop history recorded — the baseline will be empty until you add entries.
          </p>
        ) : (
          <ul className="max-h-40 space-y-1.5 overflow-y-auto pr-1 text-sm scrollbar-thin">
            {items.map((item) => (
              <li key={item.id} className="flex flex-wrap items-center gap-2">
                <Badge variant="outline" className="border-stone-300 font-normal text-stone-700">
                  {item.crop_code ?? item.crop_label}
                </Badge>
                <span className="text-xs text-stone-500">
                  {item.season_label ?? '—'} · {item.sowing_date ?? '?'} → {item.harvest_date ?? '?'}
                </span>
                <Badge variant="outline" className="font-normal text-[10px] text-stone-500">
                  {item.evidence_class}
                </Badge>
              </li>
            ))}
          </ul>
        )}
        <div className="grid grid-cols-2 gap-2 border-t border-stone-100 pt-3 sm:grid-cols-5">
          <div className="col-span-2 sm:col-span-1">
            <Label className="text-xs text-stone-500">Crop</Label>
            <Select value={cropCode} onValueChange={setCropCode}>
              <SelectTrigger className="h-9 text-sm">
                <SelectValue placeholder="Knowledge crop…" />
              </SelectTrigger>
              <SelectContent className="max-h-72">
                {(crops.data?.crops ?? []).map((c) => (
                  <SelectItem key={c.id} value={c.crop_code}>
                    {c.crop_code}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="col-span-2 sm:col-span-1">
            <Label className="text-xs text-stone-500">Label (free text)</Label>
            <Input value={label} onChange={(e) => setLabel(e.target.value)} placeholder="e.g. Maize" className="h-9 text-sm" />
          </div>
          <div>
            <Label className="text-xs text-stone-500">Sowing</Label>
            <Input type="date" value={sowing} onChange={(e) => setSowing(e.target.value)} className="h-9 text-sm" />
          </div>
          <div>
            <Label className="text-xs text-stone-500">Harvest</Label>
            <Input type="date" value={harvest} onChange={(e) => setHarvest(e.target.value)} className="h-9 text-sm" />
          </div>
          <div className="flex items-end gap-2">
            <div className="flex-1">
              <Label className="text-xs text-stone-500">Season</Label>
              <Input value={seasonLabel} onChange={(e) => setSeasonLabel(e.target.value)} placeholder="summer_2023" className="h-9 text-sm" />
            </div>
            <Button size="sm" className="h-9" onClick={() => addMutation.mutate()} disabled={addMutation.isPending || (!cropCode && !label)}>
              {addMutation.isPending ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> : 'Add'}
            </Button>
          </div>
        </div>
      </CardContent>
    </Card>
  )
}

// ------------------------------------------------------------ candidates

function CandidateRow({ assessment }: { assessment: CandidateAssessment }) {
  const [open, setOpen] = useState(false)
  return (
    <li className="rounded-lg border border-stone-200 bg-white">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex w-full flex-wrap items-center justify-between gap-2 px-3 py-2 text-left"
        aria-expanded={open}
      >
        <span className="flex min-w-0 flex-wrap items-center gap-2">
          <span className="truncate text-sm font-medium text-stone-900">{assessment.crop_code}</span>
          <CandidateStatusBadge status={assessment.status} />
          {assessment.water_requirement_mm != null && (
            <Badge variant="outline" className="border-sky-200 bg-sky-50 font-normal text-sky-800">
              ≈{fmt(assessment.water_requirement_mm, 0)} mm water
            </Badge>
          )}
        </span>
        <ChevronRight className={cn('h-4 w-4 shrink-0 text-stone-400 transition-transform', open && 'rotate-90')} aria-hidden />
      </button>
      {open && (
        <div className="space-y-2 border-t border-stone-100 px-3 py-2 text-xs text-stone-600">
          {assessment.reasons.map((r, i) => (
            <p key={i} className="leading-relaxed">
              <span
                className={cn(
                  'mr-1 inline-block h-1.5 w-1.5 rounded-full align-middle',
                  r.severity === 'hard' ? 'bg-red-500' : r.severity === 'conditional' ? 'bg-amber-500' : 'bg-emerald-500',
                )}
                aria-hidden
              />
              {r.message}
              {r.source_refs?.map((ref, j) => {
                const typed = ref as { citation_text?: string; source_key?: string }
                return typed.citation_text ? (
                  <span key={j} className="ml-1 text-stone-400">[{typed.source_key}]</span>
                ) : null
              })}
            </p>
          ))}
          {assessment.unevaluated_dimensions.map((d, i) => (
            <p key={i} className="leading-relaxed text-stone-500">
              <Info className="mr-1 inline h-3 w-3 align-[-2px]" aria-hidden />
              Not evaluated — {d.message}
            </p>
          ))}
          {assessment.water_estimate_assumptions.length > 0 && (
            <p className="text-stone-400">Water estimate assumptions: {assessment.water_estimate_assumptions.join(' ')}</p>
          )}
        </div>
      )}
    </li>
  )
}

function CandidatesCard({
  selectedField,
  seasons,
}: {
  selectedField: SelectedField
  seasons: SeasonWindow[]
}) {
  const [result, setResult] = useState<{
    seasons: CandidateSeason[]
    warnings: string[]
    counts: Record<string, Record<string, number>>
  } | null>(null)

  const mutation = useMutation({
    mutationFn: () =>
      generateCropCandidates(selectedField.id, {
        seasons: seasons.map((s) => ({ label: s.label, start_date: s.start, end_date: s.end })),
        hemisphere: 'north',
      }),
    onSuccess: (data) => {
      setResult({
        seasons: data.seasons,
        warnings: data.warnings,
        counts: data.counts_by_season,
      })
    },
    onError: (err) => {
      const d = describeError(err)
      toast.error(d.title, { description: d.description })
    },
  })

  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="text-base">Candidate crops per season</CardTitle>
        <CardDescription>
          Every knowledge-base crop evaluated against the planning seasons: calendar
          windows, duration, climate ranges, soil, water estimability and rotation
          knowledge. Missing evidence is reported, never filled.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        <Button
          size="sm"
          onClick={() => mutation.mutate()}
          disabled={mutation.isPending || seasons.length === 0}
        >
          {mutation.isPending ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> : <Sprout className="h-4 w-4" aria-hidden />}
          Generate candidates
        </Button>
        {result?.warnings.map((w, i) => (
          <Alert key={i} className={w.includes('SYNTHETIC') ? 'border-amber-200 bg-amber-50' : undefined}>
            <AlertTriangle className="h-4 w-4" aria-hidden />
            <AlertDescription className="text-xs">{w}</AlertDescription>
          </Alert>
        ))}
        {result?.seasons.map((season) => {
          const counts = result.counts[season.season_label] ?? {}
          return (
            <div key={season.season_label} className="space-y-2">
              <div className="flex flex-wrap items-center gap-1.5 text-xs text-stone-500">
                <span className="font-semibold text-stone-700">{season.season_label}</span>
                <Badge variant="outline" className="border-emerald-200 font-normal text-emerald-800">{counts.eligible ?? 0} eligible</Badge>
                <Badge variant="outline" className="border-amber-200 font-normal text-amber-900">{counts.conditionally_eligible ?? 0} conditional</Badge>
                <Badge variant="outline" className="border-red-200 font-normal text-red-800">{counts.excluded ?? 0} excluded</Badge>
                <Badge variant="outline" className="border-stone-300 font-normal text-stone-600">{counts.unevaluated ?? 0} unevaluated</Badge>
              </div>
              <ul className="max-h-72 space-y-1.5 overflow-y-auto pr-1 scrollbar-thin">
                {season.candidates.map((c) => (
                  <CandidateRow key={c.crop_code} assessment={c} />
                ))}
              </ul>
            </div>
          )
        })}
      </CardContent>
    </Card>
  )
}

// ----------------------------------------------------------- strategies

function StrategyCard({ strategy }: { strategy: RotationStrategy }) {
  const exp = strategy.explanations
  const rec = exp.recommendation
  return (
    <Card className={cn(strategy.is_baseline && 'border-dashed')}>
      <CardHeader className="pb-2">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <CardTitle className="flex flex-wrap items-center gap-2 text-base">
            {strategy.strategy_key}
            {strategy.is_baseline && <Badge variant="outline" className="font-normal text-stone-600">Baseline</Badge>}
            {strategy.pareto.on_front && !strategy.is_baseline && (
              <Badge variant="outline" className="border-emerald-200 bg-emerald-50 font-normal text-emerald-800">Pareto front</Badge>
            )}
            {!strategy.pareto.on_front && !strategy.is_baseline && (
              <Badge variant="outline" className="border-stone-300 font-normal text-stone-500">
                Dominated by {strategy.pareto.dominated_by.join(', ')}
              </Badge>
            )}
          </CardTitle>
          <div className="flex items-center gap-2 text-xs text-stone-500">
            {strategy.objective_value !== null && <span>objective {fmt(strategy.objective_value, 3)}</span>}
            {strategy.evidence_coverage != null && (
              <Badge variant="outline" className="border-stone-300 font-normal">
                evidence-backed criteria {Math.round(strategy.evidence_coverage * 100)}%
              </Badge>
            )}
          </div>
        </div>
        <CardDescription>{rec.message}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="flex flex-wrap gap-1.5">
          {strategy.assignment.map((a) => (
            <Badge
              key={a.season_label}
              variant="outline"
              className={cn(
                'font-normal',
                a.crop_code ? 'border-emerald-200 bg-emerald-50 text-emerald-900' : 'border-stone-300 text-stone-500',
              )}
            >
              {a.season_label}: {a.crop_code ?? '—'}
            </Badge>
          ))}
        </div>

        <div className="overflow-x-auto scrollbar-thin">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="text-xs">Criterion</TableHead>
                <TableHead className="text-xs">Raw</TableHead>
                <TableHead className="text-xs">Norm.</TableHead>
                <TableHead className="text-xs">Dir.</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {strategy.criteria.map((c) => (
                <TableRow key={c.criterion_code}>
                  <TableCell className="text-xs">
                    {c.criterion_code}
                    {!c.evaluable && (
                      <span className="ml-1 text-stone-400" title={c.missing_evidence.join('; ')}>
                        (not evaluated)
                      </span>
                    )}
                  </TableCell>
                  <TableCell className="text-xs">
                    {c.evaluable ? `${fmt(c.raw_value)} ${c.unit}` : <span className="text-stone-400">—</span>}
                  </TableCell>
                  <TableCell className="text-xs">{c.normalized !== null ? fmt(c.normalized, 2) : '—'}</TableCell>
                  <TableCell className="text-xs text-stone-500">{c.direction}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>

        <Accordion type="single" collapsible>
          <AccordionItem value={`why-${strategy.id}`} className="border-stone-100">
            <AccordionTrigger className="py-2 text-xs text-stone-600">Why this strategy</AccordionTrigger>
            <AccordionContent className="space-y-2 text-xs text-stone-600">
              <p>{exp.why_generated}</p>
              {exp.expected_benefits.length > 0 && (
                <div>
                  <p className="font-semibold text-emerald-800">Expected benefits</p>
                  <ul className="list-disc pl-4">
                    {exp.expected_benefits.map((b, i) => <li key={i}>{b}</li>)}
                  </ul>
                </div>
              )}
              {exp.risks_trade_offs.length > 0 && (
                <div>
                  <p className="font-semibold text-amber-800">Risks & trade-offs</p>
                  <ul className="list-disc pl-4">
                    {exp.risks_trade_offs.map((b, i) => <li key={i}>{b}</li>)}
                  </ul>
                </div>
              )}
            </AccordionContent>
          </AccordionItem>
          <AccordionItem value={`constraints-${strategy.id}`} className="border-stone-100">
            <AccordionTrigger className="py-2 text-xs text-stone-600">Constraints checked</AccordionTrigger>
            <AccordionContent className="space-y-2 text-xs text-stone-600">
              {exp.constraints_checked.map((c, i) => (
                <p key={i} className="leading-relaxed">
                  <span
                    className={cn(
                      'mr-1 inline-block h-1.5 w-1.5 rounded-full align-middle',
                      c.status === 'satisfied' ? 'bg-emerald-500' : c.status === 'violated' ? 'bg-red-500' : 'bg-stone-400',
                    )}
                    aria-hidden
                  />
                  <span className="font-medium">{c.constraint_code}</span> [{c.status}] {c.detail}
                </p>
              ))}
            </AccordionContent>
          </AccordionItem>
          <AccordionItem value={`evidence-${strategy.id}`} className="border-stone-100">
            <AccordionTrigger className="py-2 text-xs text-stone-600">Evidence & data limitations</AccordionTrigger>
            <AccordionContent className="space-y-2 text-xs text-stone-600">
              {exp.data_limitations.map((l, i) => (
                <p key={i} className="leading-relaxed text-amber-800">{l}</p>
              ))}
              <details className="text-stone-500">
                <summary className="cursor-pointer">References ({exp.evidence_references.length})</summary>
                <ul className="mt-1 list-disc pl-4">
                  {exp.evidence_references.map((r, i) => {
                    const typed = r as { type?: string; citation_text?: string; pack_version?: string; source_key?: string }
                    return (
                      <li key={i}>
                        {typed.type}: {typed.citation_text ?? typed.pack_version ?? typed.source_key}
                      </li>
                    )
                  })}
                </ul>
              </details>
            </AccordionContent>
          </AccordionItem>
          <AccordionItem value={`validation-${strategy.id}`} className="border-stone-100">
            <AccordionTrigger className="py-2 text-xs text-stone-600">Local expert validation required</AccordionTrigger>
            <AccordionContent className="space-y-1.5 text-xs text-stone-600">
              {exp.local_expert_validation_required.length === 0 ? (
                <p className="text-stone-400">None — all applied knowledge is regionally confirmed.</p>
              ) : (
                <ul className="list-disc pl-4">
                  {exp.local_expert_validation_required.map((v, i) => <li key={i}>{v}</li>)}
                </ul>
              )}
            </AccordionContent>
          </AccordionItem>
        </Accordion>

        <p className="text-[10px] text-stone-400">
          checksum {strategy.checksum_sha256?.slice(0, 16)}…
          {Object.keys(strategy.skipped_weights).length > 0 && (
            <> · skipped weights: {Object.keys(strategy.skipped_weights).join(', ')}</>
          )}
        </p>
      </CardContent>
    </Card>
  )
}

function RunOptimizerCard({
  selectedField,
  seasons,
}: {
  selectedField: SelectedField
  seasons: SeasonWindow[]
}) {
  const queryClient = useQueryClient()
  const [profiles, setProfiles] = useState<string[]>(['balanced'])
  const [allocation, setAllocation] = useState('')
  const runs = useRotationRuns(selectedField.id)
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null)
  const runDetail = useRotationRun(selectedRunId)
  const comparison = useRotationComparison(selectedRunId)

  const toggleProfile = (p: string) =>
    setProfiles((prev) => (prev.includes(p) ? prev.filter((x) => x !== p) : [...prev, p]))

  const runMutation = useMutation({
    mutationFn: () =>
      createRotationRun(selectedField.id, {
        seasons: seasons.map((s) => ({ label: s.label, start_date: s.start, end_date: s.end })),
        hemisphere: 'north',
        strategy_profiles: profiles.length ? profiles : ['balanced'],
        water_allocation_m3: allocation ? Number(allocation) : null,
        idempotency_key: `ui-${selectedField.id}-${Date.now()}`,
      }),
    onSuccess: (run) => {
      toast.success(
        run.solver_status === 'infeasible'
          ? 'Run finished: no feasible assignment (see conflicts).'
          : 'Rotation run finished.',
      )
      setSelectedRunId(run.id)
      void queryClient.invalidateQueries({ queryKey: ['rotation-runs', selectedField.id] })
    },
    onError: (err) => {
      const d = describeError(err)
      toast.error(d.title, { description: d.description })
    },
  })

  const strategies = runDetail.data?.strategies ?? []
  const infeasibleProfiles = runDetail.data?.infeasibility_details?.profiles ?? []

  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="flex items-center gap-2 text-base">
          <Scale className="h-4 w-4 text-emerald-700" aria-hidden />
          Constraint-based optimization
        </CardTitle>
        <CardDescription>
          CP-SAT over admissible candidates. Hard constraints are never relaxed;
          infeasible requests are reported with their conflicting constraints.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
          {PROFILE_OPTIONS.map((p) => (
            <label key={p.value} className="flex items-center gap-2 rounded-lg border border-stone-200 px-2 py-2 text-xs text-stone-700">
              <Checkbox checked={profiles.includes(p.value)} onCheckedChange={() => toggleProfile(p.value)} />
              {p.label}
            </label>
          ))}
        </div>
        <div className="flex flex-wrap items-end gap-2">
          <div>
            <Label className="text-xs text-stone-500">Water allocation per season (m³, optional)</Label>
            <Input
              type="number"
              min="1"
              value={allocation}
              onChange={(e) => setAllocation(e.target.value)}
              placeholder="e.g. 1450000"
              className="h-9 w-48 text-sm"
            />
          </div>
          <Button size="sm" className="h-9" onClick={() => runMutation.mutate()} disabled={runMutation.isPending || seasons.length === 0}>
            {runMutation.isPending ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> : <GitCompareArrows className="h-4 w-4" aria-hidden />}
            Optimize rotation
          </Button>
        </div>

        {runs.data && runs.data.runs.length > 0 && (
          <div>
            <Label className="text-xs text-stone-500">Past runs</Label>
            <Select value={selectedRunId ?? undefined} onValueChange={setSelectedRunId}>
              <SelectTrigger className="h-9 text-sm">
                <SelectValue placeholder="Select a run…" />
              </SelectTrigger>
              <SelectContent className="max-h-72">
                {runs.data.runs.map((r) => (
                  <SelectItem key={r.id} value={r.id}>
                    {r.id.slice(0, 8)} · {r.solver_status ?? r.status} · {r.n_strategies} strategies
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        )}

        {infeasibleProfiles.length > 0 && (
          <Alert className="border-red-200 bg-red-50">
            <XCircle className="h-4 w-4 text-red-700" aria-hidden />
            <AlertTitle className="text-sm text-red-900">Infeasible profile(s)</AlertTitle>
            <AlertDescription className="text-xs text-red-800">
              {infeasibleProfiles.map((p, i) => (
                <div key={i}>
                  <span className="font-semibold">{p.strategy_key}</span>: {p.conflicts.map((c) => `${c.constraint} — ${c.detail}`).join(' | ')}
                </div>
              ))}
            </AlertDescription>
          </Alert>
        )}

        {runDetail.data?.warnings.map((w, i) => (
          <Alert key={i} className={w.includes('SYNTHETIC') ? 'border-amber-200 bg-amber-50' : undefined}>
            <AlertTriangle className="h-4 w-4" aria-hidden />
            <AlertDescription className="text-xs">{w}</AlertDescription>
          </Alert>
        ))}

        {comparison.data && (
          <p className="text-xs text-stone-500">{comparison.data.note}</p>
        )}

        <div className="space-y-3">
          {strategies.map((s) => (
            <StrategyCard key={s.id} strategy={s} />
          ))}
        </div>
      </CardContent>
    </Card>
  )
}

// ---------------------------------------------------- knowledge browser

function KnowledgeBrowser() {
  const packs = useKnowledgePacks()
  const crops = useKnowledgeCrops()
  const rules = useRotationRules()
  const [selectedPack, setSelectedPack] = useState<string | null>(null)
  const sources = useKnowledgePackSources(selectedPack)

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="flex items-center gap-2 text-base">
            <BookOpen className="h-4 w-4 text-emerald-700" aria-hidden />
            Knowledge packs
          </CardTitle>
          <CardDescription>
            Versioned, source-cited crop knowledge. Reference values are pending
            regional validation — nothing is confirmed just because it is published.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-2">
          {packs.data?.packs.map((p) => (
            <div key={p.id} className="rounded-lg border border-stone-200 p-3">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="min-w-0">
                  <p className="truncate text-sm font-medium text-stone-900">
                    {p.pack_code} <span className="text-stone-400">{p.pack_version}</span>
                  </p>
                  <p className="text-xs text-stone-500">{p.description}</p>
                </div>
                <div className="flex flex-wrap items-center gap-1.5">
                  <Badge variant="outline" className="font-normal text-stone-600">{p.status}</Badge>
                  <Badge variant="outline" className="font-normal text-stone-600">
                    {p.counts.crops} crops · {p.counts.traits} traits · {p.counts.rotation_rules} rules
                  </Badge>
                  <Button variant="ghost" size="sm" className="h-7 text-xs" onClick={() => setSelectedPack(selectedPack === p.id ? null : p.id)}>
                    {selectedPack === p.id ? 'Hide sources' : 'Sources'}
                  </Button>
                </div>
              </div>
              {p.digitization_note && (
                <p className="mt-2 text-xs text-amber-800">{p.digitization_note}</p>
              )}
              <p className="mt-1 text-xs text-stone-500">{p.attribution_text}</p>
              {selectedPack === p.id && (
                <ul className="mt-2 max-h-48 space-y-1 overflow-y-auto border-t border-stone-100 pt-2 text-xs text-stone-600 scrollbar-thin">
                  {(sources.data?.sources ?? []).map((s) => (
                    <li key={s.source_key}>
                      <span className="font-medium">{s.source_key}</span> — {s.citation_text}
                      {s.url && (
                        <a href={s.url} target="_blank" rel="noreferrer" className="ml-1 text-emerald-700 underline">
                          link
                        </a>
                      )}
                    </li>
                  ))}
                </ul>
              )}
            </div>
          ))}
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-base">Crops ({crops.data?.total ?? 0})</CardTitle>
          <CardDescription>Deliberate gaps stay gaps: no sourced trait → no row.</CardDescription>
        </CardHeader>
        <CardContent>
          <div className="overflow-x-auto scrollbar-thin">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="text-xs">Crop</TableHead>
                  <TableHead className="text-xs">Family</TableHead>
                  <TableHead className="text-xs">Legume</TableHead>
                  <TableHead className="text-xs">Kc</TableHead>
                  <TableHead className="text-xs">Traits</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {(crops.data?.crops ?? []).map((c) => (
                  <TableRow key={c.id}>
                    <TableCell className="text-xs font-medium text-stone-800">{c.crop_code}</TableCell>
                    <TableCell className="text-xs text-stone-600">{c.family_key ?? '—'}</TableCell>
                    <TableCell className="text-xs">{c.is_legume ? 'yes' : '—'}</TableCell>
                    <TableCell className="text-xs">
                      {c.has_kc_parameters ? (
                        <CheckCircle2 className="h-3.5 w-3.5 text-emerald-600" aria-label="has Kc" />
                      ) : (
                        <span className="text-stone-400">none</span>
                      )}
                    </TableCell>
                    <TableCell className="text-xs text-stone-500">{c.trait_codes.length}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-base">Rotation rules ({rules.data?.total ?? 0})</CardTitle>
          <CardDescription>{rules.data?.note}</CardDescription>
        </CardHeader>
        <CardContent className="space-y-2">
          {(rules.data?.rules ?? []).map((r) => (
            <div key={r.rule_code} className="rounded-lg border border-stone-200 p-3 text-xs">
              <div className="flex flex-wrap items-center gap-2">
                <span className="font-medium text-stone-800">{r.rule_code}</span>
                <Badge variant="outline" className="font-normal text-stone-600">{r.rule_type}</Badge>
                <Badge
                  variant="outline"
                  className={cn(
                    'font-normal',
                    r.hard_enforceable ? 'border-red-300 bg-red-50 text-red-800' : 'border-amber-200 bg-amber-50 text-amber-900',
                  )}
                >
                  {r.validation_status}
                </Badge>
                {r.min_break_seasons > 0 && (
                  <Badge variant="outline" className="font-normal text-stone-600">break ≥ {r.min_break_seasons}</Badge>
                )}
              </div>
              <p className="mt-1.5 leading-relaxed text-stone-600">{r.mechanism}</p>
              <p className="mt-1 text-stone-400">[{r.source.citation_text}]</p>
            </div>
          ))}
        </CardContent>
      </Card>
    </div>
  )
}

// ------------------------------------------------------------------ main

export function Rotation() {
  const selectedField = useFieldShiftUi((s) => s.selectedField)
  const setSelectedField = useFieldShiftUi((s) => s.setSelectedField)
  const goToObservationsFor = useFieldShiftUi((s) => s.goToObservationsFor)
  const [seasons, setSeasons] = useState<SeasonWindow[]>([
    { label: 'summer_2026', start: '2026-05-01', end: '2026-09-15' },
  ])

  const hasField = !!selectedField

  const updateSeason = (idx: number, patch: Partial<SeasonWindow>) =>
    setSeasons((prev) => prev.map((s, i) => (i === idx ? { ...s, ...patch } : s)))

  return (
    <div className="space-y-4">
      {!hasField ? (
        <Card>
          <CardContent className="py-10 text-center text-sm text-stone-500">
            <div className="flex flex-wrap items-center justify-center gap-2">
              <span>Pick a field to plan its rotation. Knowledge browsing is available below.</span>
              <FieldPicker
                value={null}
                onValueChange={setSelectedField}
                emptyHint={
                  <Button variant="outline" size="sm" onClick={() => goToObservationsFor({ id: '', name: '', farmId: '' })}>
                    Create a farm and field first
                  </Button>
                }
              />
            </div>
          </CardContent>
        </Card>
      ) : (
        <>
          <FieldPicker value={selectedField.id} onValueChange={setSelectedField} />
          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-base">Planning seasons</CardTitle>
              <CardDescription>
                Up to four seasons per run. Climate evidence comes from the field&apos;s
                latest feature run as a month-of-year baseline — a short-record
                historical proxy (not a WMO climatological normal, never a forecast).
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-2">
              {seasons.map((s, i) => (
                <div key={i} className="grid grid-cols-2 gap-2 sm:grid-cols-4">
                  <Input
                    value={s.label}
                    onChange={(e) => updateSeason(i, { label: e.target.value })}
                    placeholder="Label"
                    className="h-9 text-sm"
                    aria-label={`Season ${i + 1} label`}
                  />
                  <Input
                    type="date"
                    value={s.start}
                    onChange={(e) => updateSeason(i, { start: e.target.value })}
                    className="h-9 text-sm"
                    aria-label={`Season ${i + 1} start`}
                  />
                  <Input
                    type="date"
                    value={s.end}
                    onChange={(e) => updateSeason(i, { end: e.target.value })}
                    className="h-9 text-sm"
                    aria-label={`Season ${i + 1} end`}
                  />
                  <Button
                    variant="ghost"
                    size="sm"
                    className="h-9 text-xs text-stone-500"
                    onClick={() => setSeasons((prev) => prev.filter((_, j) => j !== i))}
                    disabled={seasons.length === 1}
                  >
                    Remove
                  </Button>
                </div>
              ))}
              <Button
                variant="outline"
                size="sm"
                className="text-xs"
                onClick={() => setSeasons((prev) => [...prev, { label: `season_${prev.length + 1}`, start: '2026-05-01', end: '2026-09-15' }])}
                disabled={seasons.length >= 4}
              >
                Add season
              </Button>
            </CardContent>
          </Card>

          <CropHistoryCard selectedField={selectedField} />
          <CandidatesCard selectedField={selectedField} seasons={seasons} />
          <RunOptimizerCard selectedField={selectedField} seasons={seasons} />
        </>
      )}

      <KnowledgeBrowser />
    </div>
  )
}
