'use client'

import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useTranslations } from 'next-intl'
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
import { ExportButton } from '@/components/fieldshift/export-button'
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
  { value: 'water_priority', labelKey: 'profileWaterPriority' },
  { value: 'soil_health_priority', labelKey: 'profileSoilHealth' },
  { value: 'balanced', labelKey: 'profileBalanced' },
  { value: 'economic_priority', labelKey: 'profileEconomic' },
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
  const t = useTranslations('rotation')
  const map: Record<CandidateAssessment['status'], { cls: string; labelKey: string }> = {
    eligible: { cls: 'border-emerald-200 bg-emerald-50 text-emerald-800', labelKey: 'statusEligible' },
    conditionally_eligible: { cls: 'border-amber-200 bg-amber-50 text-amber-900', labelKey: 'statusConditional' },
    excluded: { cls: 'border-red-200 bg-red-50 text-red-800', labelKey: 'statusExcluded' },
    unevaluated: { cls: 'border-stone-300 bg-stone-100 text-stone-600', labelKey: 'statusUnevaluated' },
  }
  const it = map[status]
  return (
    <Badge variant="outline" className={cn('font-normal', it.cls)}>
      {t(it.labelKey)}
    </Badge>
  )
}

// --------------------------------------------------------- crop history

function CropHistoryCard({ selectedField }: { selectedField: SelectedField }) {
  const t = useTranslations('rotation')
  const tc = useTranslations('common')
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
        crop_label: label || cropCode || t('unnamedCrop'),
        sowing_date: sowing || null,
        harvest_date: harvest || null,
        season_label: seasonLabel || null,
      }),
    onSuccess: () => {
      toast.success(t('cropAddedToast'))
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
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <CardTitle className="flex items-center gap-2 text-base">
              <Sprout className="h-4 w-4 text-emerald-700" aria-hidden />
              {t('cropHistoryTitle')}
            </CardTitle>
            <CardDescription>{t('cropHistoryDesc')}</CardDescription>
          </div>
          <ExportButton
            baseFilename="crop-history"
            getRows={() =>
              items.map((item) => ({
                crop_label: item.crop_label,
                sowing_date: item.sowing_date,
                harvest_date: item.harvest_date,
                season_label: item.season_label,
                area_ha: item.area_ha,
                source: item.source,
              }))
            }
            columns={[
              { key: 'crop_label', label: t('labelCrop') },
              { key: 'sowing_date', label: t('labelSowing') },
              { key: 'harvest_date', label: t('labelHarvest') },
              { key: 'season_label', label: t('labelSeason') },
              { key: 'area_ha', label: t('colArea') },
              { key: 'source', label: t('colSource') },
            ]}
          />
        </div>
      </CardHeader>
      <CardContent className="space-y-3">
        {history.isLoading ? (
          <div className="flex items-center gap-2 text-sm text-stone-500">
            <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> {tc('loading')}
          </div>
        ) : items.length === 0 ? (
          <p className="text-sm text-stone-500">
            {t('noCropHistory')}
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
            <Label className="text-xs text-stone-500">{t('labelCrop')}</Label>
            <Select value={cropCode} onValueChange={setCropCode}>
              <SelectTrigger className="h-9 text-sm">
                <SelectValue placeholder={t('placeholderKnowledgeCrop')} />
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
            <Label className="text-xs text-stone-500">{t('labelFreeText')}</Label>
            <Input value={label} onChange={(e) => setLabel(e.target.value)} placeholder={t('placeholderLabelExample')} className="h-9 text-sm" />
          </div>
          <div>
            <Label className="text-xs text-stone-500">{t('labelSowing')}</Label>
            <Input type="date" value={sowing} onChange={(e) => setSowing(e.target.value)} className="h-9 text-sm" />
          </div>
          <div>
            <Label className="text-xs text-stone-500">{t('labelHarvest')}</Label>
            <Input type="date" value={harvest} onChange={(e) => setHarvest(e.target.value)} className="h-9 text-sm" />
          </div>
          <div className="flex items-end gap-2">
            <div className="flex-1">
              <Label className="text-xs text-stone-500">{t('labelSeason')}</Label>
              <Input value={seasonLabel} onChange={(e) => setSeasonLabel(e.target.value)} placeholder={t('placeholderSeasonExample')} className="h-9 text-sm" />
            </div>
            <Button size="sm" className="h-9" onClick={() => addMutation.mutate()} disabled={addMutation.isPending || (!cropCode && !label)}>
              {addMutation.isPending ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> : t('add')}
            </Button>
          </div>
        </div>
      </CardContent>
    </Card>
  )
}

// ------------------------------------------------------------ candidates

function CandidateRow({ assessment }: { assessment: CandidateAssessment }) {
  const t = useTranslations('rotation')
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
              ≈{t('waterBadge', { mm: fmt(assessment.water_requirement_mm, 0) })}
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
              {t('notEvaluatedLine', { message: d.message })}
            </p>
          ))}
          {assessment.water_estimate_assumptions.length > 0 && (
            <p className="text-stone-400">{t('waterAssumptions', { list: assessment.water_estimate_assumptions.join(' ') })}</p>
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
  const t = useTranslations('rotation')
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
        <CardTitle className="text-base">{t('candidatesTitle')}</CardTitle>
        <CardDescription>
          {t('candidatesDesc')}
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        <Button
          size="sm"
          onClick={() => mutation.mutate()}
          disabled={mutation.isPending || seasons.length === 0}
        >
          {mutation.isPending ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> : <Sprout className="h-4 w-4" aria-hidden />}
          {t('generateCandidates')}
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
                <Badge variant="outline" className="border-emerald-200 font-normal text-emerald-800">{t('countEligible', { count: counts.eligible ?? 0 })}</Badge>
                <Badge variant="outline" className="border-amber-200 font-normal text-amber-900">{t('countConditional', { count: counts.conditionally_eligible ?? 0 })}</Badge>
                <Badge variant="outline" className="border-red-200 font-normal text-red-800">{t('countExcluded', { count: counts.excluded ?? 0 })}</Badge>
                <Badge variant="outline" className="border-stone-300 font-normal text-stone-600">{t('countUnevaluated', { count: counts.unevaluated ?? 0 })}</Badge>
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
  const t = useTranslations('rotation')
  const exp = strategy.explanations
  const rec = exp.recommendation
  return (
    <Card className={cn(strategy.is_baseline && 'border-dashed')}>
      <CardHeader className="pb-2">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <CardTitle className="flex flex-wrap items-center gap-2 text-base">
            {strategy.strategy_key}
            {strategy.is_baseline && <Badge variant="outline" className="font-normal text-stone-600">{t('baseline')}</Badge>}
            {strategy.pareto.on_front && !strategy.is_baseline && (
              <Badge variant="outline" className="border-emerald-200 bg-emerald-50 font-normal text-emerald-800">{t('paretoFront')}</Badge>
            )}
            {!strategy.pareto.on_front && !strategy.is_baseline && (
              <Badge variant="outline" className="border-stone-300 font-normal text-stone-500">
                {t('dominatedBy', { names: strategy.pareto.dominated_by.join(', ') })}
              </Badge>
            )}
          </CardTitle>
          <div className="flex items-center gap-2 text-xs text-stone-500">
            {strategy.objective_value !== null && <span>{t('objective', { value: fmt(strategy.objective_value, 3) })}</span>}
            {strategy.evidence_coverage != null && (
              <Badge variant="outline" className="border-stone-300 font-normal">
                {t('evidenceCoverage', { percent: Math.round(strategy.evidence_coverage * 100) })}
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
                <TableHead className="text-xs">{t('thCriterion')}</TableHead>
                <TableHead className="text-xs">{t('thRaw')}</TableHead>
                <TableHead className="text-xs">{t('thNorm')}</TableHead>
                <TableHead className="text-xs">{t('thDir')}</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {strategy.criteria.map((c) => (
                <TableRow key={c.criterion_code}>
                  <TableCell className="text-xs">
                    {c.criterion_code}
                    {!c.evaluable && (
                      <span className="ml-1 text-stone-400" title={c.missing_evidence.join('; ')}>
                        {t('notEvaluated')}
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
            <AccordionTrigger className="py-2 text-xs text-stone-600">{t('whyThisStrategy')}</AccordionTrigger>
            <AccordionContent className="space-y-2 text-xs text-stone-600">
              <p>{exp.why_generated}</p>
              {exp.expected_benefits.length > 0 && (
                <div>
                  <p className="font-semibold text-emerald-800">{t('expectedBenefits')}</p>
                  <ul className="list-disc pl-4">
                    {exp.expected_benefits.map((b, i) => <li key={i}>{b}</li>)}
                  </ul>
                </div>
              )}
              {exp.risks_trade_offs.length > 0 && (
                <div>
                  <p className="font-semibold text-amber-800">{t('risksTradeOffs')}</p>
                  <ul className="list-disc pl-4">
                    {exp.risks_trade_offs.map((b, i) => <li key={i}>{b}</li>)}
                  </ul>
                </div>
              )}
            </AccordionContent>
          </AccordionItem>
          <AccordionItem value={`constraints-${strategy.id}`} className="border-stone-100">
            <AccordionTrigger className="py-2 text-xs text-stone-600">{t('constraintsChecked')}</AccordionTrigger>
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
            <AccordionTrigger className="py-2 text-xs text-stone-600">{t('evidenceLimitations')}</AccordionTrigger>
            <AccordionContent className="space-y-2 text-xs text-stone-600">
              {exp.data_limitations.map((l, i) => (
                <p key={i} className="leading-relaxed text-amber-800">{l}</p>
              ))}
              <details className="text-stone-500">
                <summary className="cursor-pointer">{t('referencesCount', { count: exp.evidence_references.length })}</summary>
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
            <AccordionTrigger className="py-2 text-xs text-stone-600">{t('localValidation')}</AccordionTrigger>
            <AccordionContent className="space-y-1.5 text-xs text-stone-600">
              {exp.local_expert_validation_required.length === 0 ? (
                <p className="text-stone-400">{t('noLocalValidation')}</p>
              ) : (
                <ul className="list-disc pl-4">
                  {exp.local_expert_validation_required.map((v, i) => <li key={i}>{v}</li>)}
                </ul>
              )}
            </AccordionContent>
          </AccordionItem>
        </Accordion>

        <p className="text-[10px] text-stone-400">
          {t('checksumLine', { checksum: strategy.checksum_sha256?.slice(0, 16) ?? '' })}
          {Object.keys(strategy.skipped_weights).length > 0 && (
            <> · {t('skippedWeights', { weights: Object.keys(strategy.skipped_weights).join(', ') })}</>
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
  const t = useTranslations('rotation')
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
          ? t('runInfeasibleToast')
          : t('runFinishedToast'),
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
          {t('optimizerTitle')}
        </CardTitle>
        <CardDescription>
          {t('optimizerDesc')}
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
          {PROFILE_OPTIONS.map((p) => (
            <label key={p.value} className="flex items-center gap-2 rounded-lg border border-stone-200 px-2 py-2 text-xs text-stone-700">
              <Checkbox checked={profiles.includes(p.value)} onCheckedChange={() => toggleProfile(p.value)} />
              {t(p.labelKey)}
            </label>
          ))}
        </div>
        <div className="flex flex-wrap items-end gap-2">
          <div>
            <Label className="text-xs text-stone-500">{t('waterAllocationLabel')}</Label>
            <Input
              type="number"
              min="1"
              value={allocation}
              onChange={(e) => setAllocation(e.target.value)}
              placeholder={t('placeholderAllocation')}
              className="h-9 w-48 text-sm"
            />
          </div>
          <Button size="sm" className="h-9" onClick={() => runMutation.mutate()} disabled={runMutation.isPending || seasons.length === 0}>
            {runMutation.isPending ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> : <GitCompareArrows className="h-4 w-4" aria-hidden />}
            {t('optimizeRotation')}
          </Button>
        </div>

        {runs.data && runs.data.runs.length > 0 && (
          <div>
            <Label className="text-xs text-stone-500">{t('pastRuns')}</Label>
            <Select value={selectedRunId ?? undefined} onValueChange={setSelectedRunId}>
              <SelectTrigger className="h-9 text-sm">
                <SelectValue placeholder={t('placeholderSelectRun')} />
              </SelectTrigger>
              <SelectContent className="max-h-72">
                {runs.data.runs.map((r) => (
                  <SelectItem key={r.id} value={r.id}>
                    {t('runOption', { id: r.id.slice(0, 8), status: r.solver_status ?? r.status, count: r.n_strategies })}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        )}

        {infeasibleProfiles.length > 0 && (
          <Alert className="border-red-200 bg-red-50">
            <XCircle className="h-4 w-4 text-red-700" aria-hidden />
            <AlertTitle className="text-sm text-red-900">{t('infeasibleProfilesTitle')}</AlertTitle>
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
  const t = useTranslations('rotation')
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
            {t('knowledgeTitle')}
          </CardTitle>
          <CardDescription>
            {t('knowledgeDesc')}
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
                    {t('packCounts', { crops: p.counts.crops, traits: p.counts.traits, rules: p.counts.rotation_rules })}
                  </Badge>
                  <Button variant="ghost" size="sm" className="h-7 text-xs" onClick={() => setSelectedPack(selectedPack === p.id ? null : p.id)}>
                    {selectedPack === p.id ? t('hideSources') : t('sources')}
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
                          {t('link')}
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
          <CardTitle className="text-base">{t('cropsCount', { count: crops.data?.total ?? 0 })}</CardTitle>
          <CardDescription>{t('cropsDesc')}</CardDescription>
        </CardHeader>
        <CardContent>
          <div className="overflow-x-auto scrollbar-thin">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="text-xs">{t('thCrop')}</TableHead>
                  <TableHead className="text-xs">{t('thFamily')}</TableHead>
                  <TableHead className="text-xs">{t('thLegume')}</TableHead>
                  <TableHead className="text-xs">{t('thKc')}</TableHead>
                  <TableHead className="text-xs">{t('thTraits')}</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {(crops.data?.crops ?? []).map((c) => (
                  <TableRow key={c.id}>
                    <TableCell className="text-xs font-medium text-stone-800">{c.crop_code}</TableCell>
                    <TableCell className="text-xs text-stone-600">{c.family_key ?? '—'}</TableCell>
                    <TableCell className="text-xs">{c.is_legume ? t('yes') : '—'}</TableCell>
                    <TableCell className="text-xs">
                      {c.has_kc_parameters ? (
                        <CheckCircle2 className="h-3.5 w-3.5 text-emerald-600" aria-label={t('ariaHasKc')} />
                      ) : (
                        <span className="text-stone-400">{t('none')}</span>
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
          <CardTitle className="text-base">{t('rulesCount', { count: rules.data?.total ?? 0 })}</CardTitle>
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
                  <Badge variant="outline" className="font-normal text-stone-600">{t('breakSeasons', { count: r.min_break_seasons })}</Badge>
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
  const t = useTranslations('rotation')
  const tCommon = useTranslations('common')
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
              <span>{t('pickFieldHint')}</span>
              <FieldPicker
                value={null}
                onValueChange={setSelectedField}
                emptyHint={
                  <Button variant="outline" size="sm" onClick={() => goToObservationsFor({ id: '', name: '', farmId: '' })}>
                    {tCommon('createFarmField')}
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
              <CardTitle className="text-base">{t('seasonsTitle')}</CardTitle>
              <CardDescription>
                {t('seasonsDesc')}
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-2">
              {seasons.map((s, i) => (
                <div key={i} className="grid grid-cols-2 gap-2 sm:grid-cols-4">
                  <Input
                    value={s.label}
                    onChange={(e) => updateSeason(i, { label: e.target.value })}
                    placeholder={t('placeholderLabel')}
                    className="h-9 text-sm"
                    aria-label={t('seasonLabelAria', { number: i + 1 })}
                  />
                  <Input
                    type="date"
                    value={s.start}
                    onChange={(e) => updateSeason(i, { start: e.target.value })}
                    className="h-9 text-sm"
                    aria-label={t('seasonStartAria', { number: i + 1 })}
                  />
                  <Input
                    type="date"
                    value={s.end}
                    onChange={(e) => updateSeason(i, { end: e.target.value })}
                    className="h-9 text-sm"
                    aria-label={t('seasonEndAria', { number: i + 1 })}
                  />
                  <Button
                    variant="ghost"
                    size="sm"
                    className="h-9 text-xs text-stone-500"
                    onClick={() => setSeasons((prev) => prev.filter((_, j) => j !== i))}
                    disabled={seasons.length === 1}
                  >
                    {t('remove')}
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
                {t('addSeason')}
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
