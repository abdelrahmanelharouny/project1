'use client'

/**
 * Soil Intelligence (Milestone 6B) — depth-explicit soil profile, method-aware
 * indicators, SOC stock runs, N/P/K nutrient budgets, the multi-domain
 * assessment profile and the data-readiness (VOI) ranking.
 *
 * Honesty contract surfaced here: no composite score (a transparent
 * multi-domain profile instead), measured ≠ mapped (structurally distinct
 * badges), missing ≠ zero ("(not evaluated)" everywhere), method metadata in
 * Expert mode, synthetic banners, and every number traceable to a cited
 * method or a recorded measurement.
 */

import { useMemo, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useTranslations } from 'next-intl'
import { toast } from 'sonner'
import {
  AlertTriangle,
  ChevronDown,
  FileUp,
  Layers,
  Microscope,
  Mountain,
  ScrollText,
  ShieldCheck,
  Sprout,
} from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from '@/components/ui/accordion'
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Switch } from '@/components/ui/switch'
import { FieldPicker } from '@/components/croptwist/field-picker'
import { SocStockChart } from '@/components/croptwist/charts/soil-soc'
import { useCropTwistUi } from '@/lib/store'
import {
  useSocRuns,
  useSoilDataReadiness,
  useSoilHealth,
  useSoilIndicators,
  useSoilMethods,
  useSoilProfile,
} from '@/hooks/use-croptwist'
import {
  createNutrientBudgetRun,
  createSocStockRun,
  importSoilLabCsv,
  runSoilAssessment,
} from '@/lib/api'
import { describeError } from '@/lib/api'
import type {
  NutrientBudgetRun,
  SoilAssessmentResult,
  SoilDomainRow,
} from '@/lib/types'

function fmt(value: number | null | undefined, digits = 1): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '—'
  return value.toLocaleString(undefined, {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  })
}

const DOMAIN_LABEL_KEYS: Record<string, string> = {
  physical: 'domainPhysical',
  chemical: 'domainChemical',
  biological: 'domainBiological',
  hydrological: 'domainHydrological',
  organic_matter_nutrient_cycling: 'domainOrganic',
}

const EVIDENCE_BADGES: Record<string, string> = {
  direct_field_measurement: 'border-emerald-300 bg-emerald-50 text-emerald-800',
  farmer_reported_record: 'border-amber-300 bg-amber-50 text-amber-800',
  global_soil_prediction: 'border-orange-300 bg-orange-50 text-orange-800',
  synthetic_test_data: 'border-stone-400 bg-stone-100 text-stone-600',
}

function EvidenceBadge({ evidence }: { evidence: string }) {
  const style = EVIDENCE_BADGES[evidence] ?? 'border-stone-300 bg-stone-50 text-stone-600'
  const label = evidence.replaceAll('_', ' ')
  return (
    <Badge variant="outline" className={`text-[10px] ${style}`}>
      {label}
    </Badge>
  )
}

// ------------------------------------------------------------- assessment

function DomainCard({ domain, expert }: { domain: SoilDomainRow; expert: boolean }) {
  const t = useTranslations('soil')
  const domainKey = DOMAIN_LABEL_KEYS[domain.domain]
  return (
    <Card className="min-w-0">
      <CardHeader className="pb-2">
        <CardTitle className="flex flex-wrap items-center gap-2 text-sm">
          {domainKey ? t(domainKey) : domain.domain}
          <Badge variant="outline" className="text-[10px]">
            {t('availableCount', { count: domain.available_count })}
          </Badge>
          {domain.missing_count > 0 && (
            <Badge variant="outline" className="border-stone-300 bg-stone-50 text-[10px] text-stone-500">
              {t('missingCount', { count: domain.missing_count })}
            </Badge>
          )}
          {domain.synthetic_flag && (
            <Badge variant="outline" className="border-stone-400 bg-stone-100 text-[10px] text-stone-600">
              {t('includesSynthetic')}
            </Badge>
          )}
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-2">
        {domain.available.length === 0 ? (
          <p className="text-xs text-stone-500">
            {t('noIndicators')}
          </p>
        ) : (
          domain.available.map((indicator) => (
            <div key={indicator.variable_code} className="rounded-lg border border-stone-200 bg-white px-3 py-2">
              <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
                <span className="font-mono text-xs text-stone-700">{indicator.variable_code}</span>
                <span className="text-sm font-semibold text-stone-900">
                  {fmt(indicator.latest_value, 2)} <span className="text-xs font-normal text-stone-500">{indicator.unit}</span>
                </span>
              </div>
              <div className="mt-1 flex flex-wrap items-center gap-1.5">
                <EvidenceBadge evidence={indicator.evidence_class} />
                {indicator.method && expert && (
                  <Badge variant="outline" className="text-[10px] text-stone-500">
                    {indicator.method}
                  </Badge>
                )}
                {indicator.depth[0] !== null && (
                  <span className="text-[10px] text-stone-400">
                    {indicator.depth[0]}–{indicator.depth[1]} cm
                  </span>
                )}
                {indicator.trend && (
                  <Badge
                    variant="outline"
                    className={`text-[10px] ${
                      indicator.trend.status === 'measured_change'
                        ? 'border-emerald-200 bg-emerald-50 text-emerald-700'
                        : 'border-stone-300 bg-stone-50 text-stone-500'
                    }`}
                  >
                    {indicator.trend.status === 'measured_change'
                      ? `Δ ${fmt(indicator.trend.delta, 2)}`
                      : t('trendNotComparable')}
                  </Badge>
                )}
              </div>
              {indicator.trend?.status === 'not_comparable' && expert && indicator.trend.reason && (
                <p className="mt-1 text-[11px] text-stone-500">{indicator.trend.reason}</p>
              )}
            </div>
          ))
        )}
        {expert && domain.missing.length > 0 && (
          <p className="text-[11px] text-stone-400">{t('missingList', { list: domain.missing.join(', ') })}</p>
        )}
      </CardContent>
    </Card>
  )
}

function AssessmentSection() {
  const t = useTranslations('soil')
  const selectedField = useCropTwistUi((s) => s.selectedField)
  const [expert, setExpert] = useState(false)
  const health = useSoilHealth(selectedField?.id ?? null)
  const queryClient = useQueryClient()

  const runAssessment = useMutation({
    mutationFn: () => runSoilAssessment(selectedField!.id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['soil-health', selectedField?.id] })
      toast.success(t('toastAssessmentCreated'), { description: t('toastAssessmentDesc') })
    },
    onError: (error) => {
      const d = describeError(error)
      toast.error(d.title, { description: d.description })
    },
  })

  if (!selectedField) return null

  return (
    <Card className="min-w-0">
      <CardHeader className="pb-3">
        <CardTitle className="flex items-center gap-2 text-base">
          <Sprout className="h-4 w-4 text-emerald-700" aria-hidden />
          {t('assessmentTitle')}
        </CardTitle>
        <CardDescription>
          {t('assessmentDesc')}
        </CardDescription>
        <div className="flex items-center gap-2 pt-1">
          <Switch id="soil-expert" checked={expert} onCheckedChange={setExpert} aria-label={t('toggleExpert')} />
          <Label htmlFor="soil-expert" className="text-xs text-stone-600">{t('expertMode')}</Label>
          <Button
            size="sm"
            variant="outline"
            className="ml-auto"
            disabled={runAssessment.isPending}
            onClick={() => runAssessment.mutate()}
          >
            {runAssessment.isPending ? t('assessing') : t('snapshotAssessment')}
          </Button>
        </div>
      </CardHeader>
      <CardContent>
        {health.isLoading ? (
          <p className="text-sm text-stone-500">{t('loadingAssessment')}</p>
        ) : health.isError ? (
          <p className="text-sm text-red-700">{t('assessmentUnavailable')}</p>
        ) : health.data ? (
          <div className="grid min-w-0 gap-4 md:grid-cols-2">
            {health.data.result.domains.map((domain) => (
              <DomainCard key={domain.domain} domain={domain} expert={expert} />
            ))}
          </div>
        ) : null}
      </CardContent>
    </Card>
  )
}

// ------------------------------------------------------------- profile

function ProfileExplorer() {
  const t = useTranslations('soil')
  const tc = useTranslations('common')
  const selectedField = useCropTwistUi((s) => s.selectedField)
  const profile = useSoilProfile(selectedField?.id ?? null)
  const indicators = useSoilIndicators(selectedField?.id ?? null)

  if (!selectedField) return null

  return (
    <Card className="min-w-0">
      <CardHeader className="pb-3">
        <CardTitle className="flex items-center gap-2 text-base">
          <Layers className="h-4 w-4 text-emerald-700" aria-hidden />
          {t('profileTitle')}
        </CardTitle>
        <CardDescription>
          {t('profileDesc')}
        </CardDescription>
      </CardHeader>
      <CardContent>
        {profile.isLoading ? (
          <p className="text-sm text-stone-500">{t('loadingProfile')}</p>
        ) : profile.isError ? (
          <p className="text-sm text-red-700">{t('profileUnavailable')}</p>
        ) : profile.data && profile.data.layers.length > 0 ? (
          <div className="space-y-3">
            {profile.data.layers.map((layer) => {
              const indicator = indicators.data?.layers.find(
                (l) => l.top_cm === layer.top_cm && l.bottom_cm === layer.bottom_cm,
              )
              const texture =
                indicator?.texture && 'class' in indicator.texture ? indicator.texture : null
              const awc = indicator?.awc && 'awc_mm' in indicator.awc ? indicator.awc : null
              return (
                <div key={`${layer.top_cm}-${layer.bottom_cm}-${layer.sample_id ?? 'field'}`} className="rounded-lg border border-stone-200 bg-white p-3">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <span className="text-sm font-semibold text-stone-800">
                      {layer.top_cm}–{layer.bottom_cm} cm
                    </span>
                    <div className="flex flex-wrap items-center gap-1.5">
                      {texture && (
                        <Badge variant="outline" className="border-emerald-200 bg-emerald-50 text-[10px] text-emerald-800">
                          {t('usdaClass', { cls: texture.class })}
                        </Badge>
                      )}
                      {awc && (
                        <Badge variant="outline" className="border-sky-200 bg-sky-50 text-[10px] text-sky-800">
                          {t('awcBadge', { value: fmt(awc.awc_mm) })}
                        </Badge>
                      )}
                      {layer.source_kinds.map((kind) => (
                        <Badge key={kind} variant="outline" className="text-[10px] text-stone-500">
                          {kind.replaceAll('_', ' ')}
                        </Badge>
                      ))}
                    </div>
                  </div>
                  <div className="mt-2 grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
                    {layer.measurements.map((m) => (
                      <div key={m.id} className="rounded border border-stone-100 bg-stone-50 px-2 py-1.5">
                        <div className="flex items-baseline justify-between gap-2">
                          <span className="truncate font-mono text-[11px] text-stone-600">{m.variable_code}</span>
                          <span className="text-xs font-semibold text-stone-800">
                            {m.value !== null ? (
                              <>
                                {fmt(m.value, 2)} <span className="font-normal text-stone-500">{m.unit}</span>
                              </>
                            ) : m.result_qualifier ? (
                              <span className="text-amber-700">
                                {m.result_qualifier} {fmt(m.detection_limit, 2)} ({m.unit})
                              </span>
                            ) : (
                              <span className="text-stone-400">{t('notEvaluated')}</span>
                            )}
                          </span>
                        </div>
                        <div className="mt-1 flex flex-wrap items-center gap-1">
                          <EvidenceBadge evidence={m.evidence_class} />
                          {m.is_synthetic && (
                            <Badge variant="outline" className="text-[10px] text-stone-500">{tc('synthetic')}</Badge>
                          )}
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              )
            })}
            {profile.data.integrity.gaps.length > 0 && (
              <div className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-xs text-amber-800">
                <p className="flex items-center gap-1.5 font-medium">
                  <AlertTriangle className="h-3.5 w-3.5" aria-hidden /> {t('depthGaps')}
                </p>
                <ul className="mt-1 list-inside list-disc">
                  {profile.data.integrity.gaps.map((gap, i) => (
                    <li key={i}>{t('gapLine', { from: gap.from_cm ?? '?', to: gap.to_cm ?? '?', gap: fmt(gap.gap_cm) })}</li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        ) : (
          <div className="rounded-lg border border-dashed border-stone-300 bg-stone-50 p-6 text-center">
            <p className="text-sm text-stone-500">
              {t('noMeasurements')}
            </p>
          </div>
        )}
      </CardContent>
    </Card>
  )
}

// ------------------------------------------------------------- SOC runs

function SocSection() {
  const t = useTranslations('soil')
  const selectedField = useCropTwistUi((s) => s.selectedField)
  const runs = useSocRuns(selectedField?.id ?? null)
  const queryClient = useQueryClient()
  const [expert, setExpert] = useState(false)
  const [oc, setOc] = useState('12.5')
  const [bd, setBd] = useState('1.33')
  const [basis, setBasis] = useState<'fine_earth' | 'whole_soil'>('fine_earth')
  const [vcf, setVcf] = useState('')
  const [top, setTop] = useState('0')
  const [bottom, setBottom] = useState('30')

  const createRun = useMutation({
    mutationFn: () =>
      createSocStockRun(selectedField!.id, {
        label: 'Layer SOC run',
        layers: [
          {
            top_depth: Number(top),
            bottom_depth: Number(bottom),
            oc_g_kg: oc === '' ? null : Number(oc),
            bulk_density_g_cm3: bd === '' ? null : Number(bd),
            bd_basis: bd === '' ? null : basis,
            coarse_fragment_vol_fraction: basis === 'whole_soil' && vcf !== '' ? Number(vcf) / 100 : null,
          },
        ],
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['soc-runs', selectedField?.id] })
      toast.success(t('toastSocCreated'), { description: t('toastSocDesc') })
    },
    onError: (error) => {
      const d = describeError(error)
      toast.error(d.title, { description: d.description })
    },
  })

  if (!selectedField) return null

  const latest = runs.data?.items.find((r) => r.status === 'succeeded')

  return (
    <Card className="min-w-0">
      <CardHeader className="pb-3">
        <CardTitle className="flex flex-wrap items-center gap-2 text-base">
          <Mountain className="h-4 w-4 text-emerald-700" aria-hidden />
          {t('socTitle')}
        </CardTitle>
        <CardDescription>
          {t('socDesc')}
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="grid gap-3 sm:grid-cols-3 lg:grid-cols-6">
          <div className="space-y-1">
            <Label htmlFor="soc-top" className="text-xs">{t('topLabel')}</Label>
            <Input id="soc-top" type="number" value={top} onChange={(e) => setTop(e.target.value)} />
          </div>
          <div className="space-y-1">
            <Label htmlFor="soc-bottom" className="text-xs">{t('bottomLabel')}</Label>
            <Input id="soc-bottom" type="number" value={bottom} onChange={(e) => setBottom(e.target.value)} />
          </div>
          <div className="space-y-1">
            <Label htmlFor="soc-oc" className="text-xs">{t('ocLabel')}</Label>
            <Input id="soc-oc" type="number" value={oc} onChange={(e) => setOc(e.target.value)} />
          </div>
          <div className="space-y-1">
            <Label htmlFor="soc-bd" className="text-xs">{t('bdLabel')}</Label>
            <Input id="soc-bd" type="number" value={bd} onChange={(e) => setBd(e.target.value)} />
          </div>
          <div className="space-y-1">
            <Label htmlFor="soc-basis" className="text-xs">{t('bdBasisLabel')}</Label>
            <select
              id="soc-basis"
              value={basis}
              onChange={(e) => setBasis(e.target.value as 'fine_earth' | 'whole_soil')}
              className="h-9 w-full rounded-md border border-stone-300 bg-white px-2 text-sm"
            >
              <option value="fine_earth">{t('basisFineEarth')}</option>
              <option value="whole_soil">{t('basisWholeSoil')}</option>
            </select>
          </div>
          {basis === 'whole_soil' && (
            <div className="space-y-1">
              <Label htmlFor="soc-vcf" className="text-xs">{t('vcfLabel')}</Label>
              <Input id="soc-vcf" type="number" value={vcf} onChange={(e) => setVcf(e.target.value)} placeholder={t('vcfPlaceholder')} />
            </div>
          )}
        </div>
        <Button size="sm" disabled={createRun.isPending} onClick={() => createRun.mutate()}>
          {createRun.isPending ? t('computing') : t('computeSoc')}
        </Button>

        {latest?.result && (
          <div className="rounded-lg border border-stone-200 bg-white p-4">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div>
                <p className="text-xs text-stone-500">{t('profileTotal', { depth: fmt(latest.result.profile_total.covered_thickness_cm) })}</p>
                <p className="text-2xl font-semibold text-stone-900">
                  {latest.result.profile_total.soc_stock_mg_ha !== null ? (
                    <>
                      {fmt(latest.result.profile_total.soc_stock_mg_ha)} <span className="text-sm font-normal text-stone-500">Mg C/ha</span>
                    </>
                  ) : (
                    <span className="text-stone-400">{t('notEvaluated')}</span>
                  )}
                </p>
              </div>
              {expert && latest.checksum_sha256 && (
                <Badge variant="outline" className="font-mono text-[10px] text-stone-500">
                  sha256 {latest.checksum_sha256.slice(0, 12)}…
                </Badge>
              )}
            </div>
            {expert && (
              <p className="mt-2 font-mono text-[11px] text-stone-500">{latest.result.formula}</p>
            )}
            {latest.result.not_evaluated.length > 0 && (
              <ul className="mt-2 space-y-1 text-xs text-amber-800">
                {latest.result.not_evaluated.map((ne, i) => (
                  <li key={i} className="flex items-start gap-1.5">
                    <AlertTriangle className="mt-0.5 h-3 w-3 shrink-0" aria-hidden /> {ne.layer}: {ne.reason}
                  </li>
                ))}
              </ul>
            )}
            <div className="mt-3 flex items-center gap-2">
              <Switch id="soc-expert" checked={expert} onCheckedChange={setExpert} aria-label={t('socExpertAria')} />
              <Label htmlFor="soc-expert" className="text-xs text-stone-600">{t('expertDetail')}</Label>
            </div>
          </div>
        )}

        {latest?.result ? <SocStockChart layers={latest.result.layers} /> : null}

        {runs.data && runs.data.items.length > 0 && (
          <div className="max-h-64 space-y-2 overflow-y-auto pr-1 scrollbar-thin">
            {runs.data.items.map((run) => (
              <div key={run.id} className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-stone-200 bg-white px-3 py-2 text-xs">
                <span className="font-medium text-stone-700">{run.label}</span>
                <span className="text-stone-500">
                  {run.status} · {run.comparison_mode.replaceAll('_', ' ')}
                  {run.result?.profile_total.soc_stock_mg_ha != null &&
                    ` · ${fmt(run.result.profile_total.soc_stock_mg_ha)} Mg C/ha`}
                </span>
              </div>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  )
}

// ------------------------------------------------------------- nutrients

function NutrientSection() {
  const t = useTranslations('soil')
  const selectedField = useCropTwistUi((s) => s.selectedField)
  const queryClient = useQueryClient()
  const [season, setSeason] = useState('summer_2026')
  const [areaHa, setAreaHa] = useState('1')
  const [run, setRun] = useState<NutrientBudgetRun | null>(null)

  const budgetRun = useMutation({
    mutationFn: () =>
      createNutrientBudgetRun(selectedField!.id, {
        seasons: [season.trim()],
        area_ha: areaHa === '' ? undefined : Number(areaHa),
        label: `NPK budget ${season.trim()}`,
      }),
    onSuccess: (data) => {
      setRun(data)
      queryClient.invalidateQueries({ queryKey: ['soc-runs'] })
      toast.success(t('toastBudgetDone'), { description: t('toastBudgetDesc') })
    },
    onError: (error) => {
      const d = describeError(error)
      toast.error(d.title, { description: d.description })
    },
  })

  if (!selectedField) return null

  const seasonResult = run?.result?.seasons[0]

  return (
    <Card className="min-w-0">
      <CardHeader className="pb-3">
        <CardTitle className="text-base">{t('budgetTitle')}</CardTitle>
        <CardDescription>
          {t('budgetDesc')}
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="flex flex-wrap items-end gap-3">
          <div className="space-y-1">
            <Label htmlFor="npk-season" className="text-xs">{t('seasonLabel')}</Label>
            <Input id="npk-season" value={season} onChange={(e) => setSeason(e.target.value)} className="w-44" />
          </div>
          <div className="space-y-1">
            <Label htmlFor="npk-area" className="text-xs">{t('areaLabel')}</Label>
            <Input id="npk-area" type="number" value={areaHa} onChange={(e) => setAreaHa(e.target.value)} className="w-28" />
          </div>
          <Button size="sm" disabled={budgetRun.isPending} onClick={() => budgetRun.mutate()}>
            {budgetRun.isPending ? t('computing') : t('computeBudget')}
          </Button>
        </div>

        {seasonResult && (
          <div className="space-y-3">
            <div className="grid min-w-0 gap-3 sm:grid-cols-3">
              {(['N', 'P', 'K'] as const).map((nutrient) => {
                const balance = seasonResult.balance[nutrient]
                return (
                  <div key={nutrient} className="rounded-lg border border-stone-200 bg-white p-3">
                    <p className="text-xs font-medium text-stone-500">{t('nutrientHeader', { nutrient })}</p>
                    <p className="mt-1 text-lg font-semibold text-stone-900">
                      {balance.balance_kg_ha !== null ? (
                        <span className={balance.balance_kg_ha >= 0 ? 'text-emerald-700' : 'text-amber-700'}>
                          {balance.balance_kg_ha >= 0 ? '+' : ''}{fmt(balance.balance_kg_ha)}
                        </span>
                      ) : (
                        <span className="text-stone-400">{t('notEvaluated')}</span>
                      )}
                    </p>
                    <p className="mt-1 text-[11px] text-stone-500">
                      {t('inOut', { inValue: fmt(balance.inputs_kg_ha), outValue: fmt(balance.outputs_kg_ha) })}
                    </p>
                  </div>
                )
              })}
            </div>
            <div className="rounded-lg border border-amber-200 bg-amber-50 p-3">
              <p className="text-xs font-medium text-amber-800">
                {t('missingFlows', { count: seasonResult.missing_flows.length })}
              </p>
              <ul className="mt-1 list-inside list-disc text-[11px] text-amber-800">
                {seasonResult.missing_flows.slice(0, 6).map((flow, i) => (
                  <li key={i}>{flow}</li>
                ))}
              </ul>
            </div>
            <p className="text-[11px] text-stone-500">{seasonResult.interpretation_note}</p>
          </div>
        )}

        {run?.result?.reference_library_note && (
          <p className="text-[11px] italic text-stone-400">{run.result.reference_library_note}</p>
        )}
      </CardContent>
    </Card>
  )
}

// ------------------------------------------------------------- lab import

function LabImportSection() {
  const t = useTranslations('soil')
  const selectedField = useCropTwistUi((s) => s.selectedField)
  const fileRef = useRef<HTMLInputElement>(null)
  const [report, setReport] = useState<{
    imported: number
    rejected: number
    warnings: number
    rows: Array<{ row_number: number; status: string; message: string | null }>
  } | null>(null)

  const importMutation = useMutation({
    mutationFn: async () => {
      const file = fileRef.current?.files?.[0]
      if (!file) throw new Error(t('chooseCsv'))
      return importSoilLabCsv(selectedField!.id, file)
    },
    onSuccess: (data) => {
      setReport({
        imported: data.created_measurements,
        rejected: data.report.rejected,
        warnings: data.report.warnings,
        rows: data.report.rows,
      })
      toast.success(t('toastImported', { count: data.created_measurements }), {
        description: t('toastImportedDesc', {
          rejected: data.report.rejected,
          checksum: data.report.file_sha256.slice(0, 8),
        }),
      })
    },
    onError: (error) => {
      const d = describeError(error)
      toast.error(d.title, { description: d.description })
    },
  })

  if (!selectedField) return null

  return (
    <Card className="min-w-0">
      <CardHeader className="pb-3">
        <CardTitle className="flex items-center gap-2 text-base">
          <FileUp className="h-4 w-4 text-emerald-700" aria-hidden />
          {t('labImportTitle')}
        </CardTitle>
        <CardDescription>
          {t('labImportDesc')}
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="flex flex-wrap items-center gap-3">
          <Input ref={fileRef} type="file" accept=".csv,text/csv" className="max-w-sm" aria-label={t('labFileAria')} />
          <Button size="sm" disabled={importMutation.isPending} onClick={() => importMutation.mutate()}>
            {importMutation.isPending ? t('importing') : t('importButton')}
          </Button>
        </div>
        {report && (
          <div className="rounded-lg border border-stone-200 bg-white p-3 text-xs">
            <p className="font-medium text-stone-700">
              {t('importSummary', {
                imported: report.imported,
                rejected: report.rejected,
                warnings: report.warnings,
              })}
            </p>
            {report.rows.filter((r) => r.status !== 'imported').length > 0 && (
              <ul className="mt-2 max-h-40 space-y-1 overflow-y-auto scrollbar-thin">
                {report.rows
                  .filter((r) => r.status !== 'imported')
                  .map((r, i) => (
                    <li key={i} className={r.status === 'rejected' ? 'text-red-700' : 'text-amber-700'}>
                      {t('rowLine', { row: r.row_number, status: r.status, message: r.message ?? '' })}
                    </li>
                  ))}
              </ul>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  )
}

// ------------------------------------------------------------- readiness

function ReadinessSection() {
  const t = useTranslations('soil')
  const tc = useTranslations('common')
  const selectedField = useCropTwistUi((s) => s.selectedField)
  const readiness = useSoilDataReadiness(selectedField?.id ?? null)

  if (!selectedField) return null

  return (
    <Card className="min-w-0">
      <CardHeader className="pb-3">
        <CardTitle className="flex items-center gap-2 text-base">
          <ShieldCheck className="h-4 w-4 text-emerald-700" aria-hidden />
          {t('readinessTitle')}
        </CardTitle>
        <CardDescription>
          {t('readinessDesc')}
        </CardDescription>
      </CardHeader>
      <CardContent>
        {readiness.isLoading ? (
          <p className="text-sm text-stone-500">{tc('loading')}</p>
        ) : readiness.isError || !readiness.data ? (
          <p className="text-sm text-red-700">{t('readinessUnavailable')}</p>
        ) : readiness.data.priorities.length === 0 ? (
          <p className="text-sm text-stone-500">
            {t('noPriorities')}
          </p>
        ) : (
          <div className="max-h-96 space-y-2 overflow-y-auto pr-1 scrollbar-thin">
            {readiness.data.priorities.map((p) => (
              <div key={p.variable_code} className="rounded-lg border border-stone-200 bg-white px-3 py-2">
                <p className="font-mono text-xs text-stone-700">{p.variable_code}</p>
                <p className="mt-0.5 text-xs text-stone-600">{p.decision_unblocked}</p>
                {p.priority_basis && <p className="mt-0.5 text-[11px] text-stone-400">{p.priority_basis}</p>}
              </div>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  )
}

// ------------------------------------------------------------------ root

export function Soil() {
  const t = useTranslations('soil')
  const selectedField = useCropTwistUi((s) => s.selectedField)
  const setSelectedField = useCropTwistUi((s) => s.setSelectedField)
  const methods = useSoilMethods()

  return (
    <div className="space-y-6">
      {!selectedField && (
        <Card>
          <CardContent className="flex flex-col items-center gap-3 py-10 text-center">
            <Mountain className="h-8 w-8 text-stone-400" aria-hidden />
            <p className="text-sm text-stone-500">{t('selectFieldPrompt')}</p>
            <FieldPicker
              value={null}
              onValueChange={setSelectedField}
            />
          </CardContent>
        </Card>
      )}

      {selectedField && (
        <>
          {methods.data && (
            <p className="text-xs text-stone-500">
              {t('methodsLine', {
                engine: methods.data.soil_engine_version,
                methods: methods.data.methods_version,
                system: methods.data.texture_classifier.system,
              })}
            </p>
          )}
          <AssessmentSection />
          <ProfileExplorer />
          <div className="grid min-w-0 gap-6 xl:grid-cols-2">
            <SocSection />
            <NutrientSection />
          </div>
          <div className="grid min-w-0 gap-6 xl:grid-cols-2">
            <LabImportSection />
            <ReadinessSection />
          </div>
          {methods.data && (
            <Card>
              <CardHeader className="pb-3">
                <CardTitle className="flex items-center gap-2 text-base">
                  <ScrollText className="h-4 w-4 text-emerald-700" aria-hidden />
                  {t('methodologyTitle')}
                </CardTitle>
                <CardDescription>
                  {t('methodologyDesc')}
                </CardDescription>
              </CardHeader>
              <CardContent>
                <Accordion type="single" collapsible>
                  <AccordionItem value="texture">
                    <AccordionTrigger className="text-sm">{t('textureTrigger')}</AccordionTrigger>
                    <AccordionContent className="text-xs text-stone-600">
                      {methods.data.texture_classifier.system} — {methods.data.texture_classifier.source}
                    </AccordionContent>
                  </AccordionItem>
                  <AccordionItem value="conversions">
                    <AccordionTrigger className="text-sm">{t('conversionsTrigger')}</AccordionTrigger>
                    <AccordionContent className="text-xs text-stone-600">
                      {Object.entries(methods.data.conversions).map(([key, conv]) => (
                        <p key={key} className="mt-1">
                          <span className="font-mono">{key}</span>
                          {conv.factor !== undefined && <> = ×{conv.factor}</>} — {conv.derivation ?? conv.method}
                        </p>
                      ))}
                    </AccordionContent>
                  </AccordionItem>
                  <AccordionItem value="salinity">
                    <AccordionTrigger className="text-sm">{t('salinityTrigger')}</AccordionTrigger>
                    <AccordionContent className="text-xs text-stone-600">
                      {methods.data.salinity_classes.map((c) => (
                        <p key={c.class}>
                          {c.class}: {c.range_ds_m[0]}
                          {c.range_ds_m[1] === null ? '+' : `–${c.range_ds_m[1]}`} dS/m — {c.citation}
                        </p>
                      ))}
                    </AccordionContent>
                  </AccordionItem>
                </Accordion>
              </CardContent>
            </Card>
          )}
        </>
      )}
    </div>
  )
}
