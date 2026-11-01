'use client'

/**
 * Water Intelligence (Milestone 6A) — seasonal water planning with the
 * versioned water engine: growth-stage demand, effective rainfall, the
 * irrigation-requirement ladder, root-zone stress windows, allocation checks
 * and full methodology/provenance disclosures.
 *
 * Honesty contract surfaced here: missing evidence renders as "(not
 * evaluated)", an unknown allocation is reported as unknown (never
 * unlimited), synthetic evidence carries a banner, and every number traces to
 * a cited method or knowledge row (Expert mode shows checksums).
 */

import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  AlertTriangle,
  ChevronDown,
  Droplets,
  Gauge,
  Info,
  Layers,
  ScrollText,
  ShieldCheck,
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
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Switch } from '@/components/ui/switch'
import { FieldPicker } from '@/components/fieldshift/field-picker'
import { useFieldShiftUi } from '@/lib/store'
import {
  useKnowledgeCrops,
  useWaterMethods,
  useWaterPlan,
  useWaterPlans,
  useWaterReadiness,
} from '@/hooks/use-fieldshift'
import { createWaterPlan, deleteWaterPlan } from '@/lib/api'
import { describeError } from '@/lib/api'
import { useToast } from '@/hooks/use-toast'
import type {
  WaterPlan,
  WaterPlanSeason,
  WaterReadinessCrop,
} from '@/lib/types'

function fmt(value: number | null | undefined, digits = 1): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '—'
  return value.toLocaleString(undefined, {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  })
}

// ------------------------------------------------------------- readiness

const READINESS_STYLES: Record<string, string> = {
  complete: 'bg-emerald-100 text-emerald-800 border-emerald-200',
  partial: 'bg-amber-100 text-amber-800 border-amber-200',
  missing: 'bg-stone-200 text-stone-600 border-stone-300',
  not_locally_validated: 'bg-orange-100 text-orange-800 border-orange-200',
  not_applicable: 'bg-stone-100 text-stone-500 border-stone-200',
}

function ReadinessCard() {
  const selectedField = useFieldShiftUi((s) => s.selectedField)
  const readiness = useWaterReadiness(selectedField?.id ?? null)

  if (!selectedField) return null

  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="flex items-center gap-2 text-base">
          <Layers className="h-4 w-4 text-emerald-700" aria-hidden />
          Water-knowledge readiness
        </CardTitle>
        <CardDescription>
          Crop-by-crop coverage of the water knowledge base — complete,
          partially documented, or deliberately missing (never guessed).
          Everything is reference-grade until an agronomist confirms it
          regionally.
        </CardDescription>
      </CardHeader>
      <CardContent>
        {readiness.isLoading ? (
          <p className="text-sm text-stone-500">Loading readiness…</p>
        ) : readiness.isError ? (
          <p className="text-sm text-red-700">Readiness unavailable.</p>
        ) : readiness.data ? (
          <div className="max-h-96 space-y-2 overflow-y-auto pr-1 scrollbar-thin">
            {readiness.data.crops.map((crop: WaterReadinessCrop) => (
              <ReadinessRow key={crop.crop_code} crop={crop} />
            ))}
          </div>
        ) : null}
      </CardContent>
    </Card>
  )
}

function ReadinessRow({ crop }: { crop: WaterReadinessCrop }) {
  const [open, setOpen] = useState(false)
  const overallStyle =
    READINESS_STYLES[crop.overall] ?? READINESS_STYLES.missing
  return (
    <div className="rounded-lg border border-stone-200 bg-white">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center justify-between gap-2 px-3 py-2 text-left"
        aria-expanded={open}
      >
        <span className="flex min-w-0 items-center gap-2">
          <span className="truncate text-sm font-medium text-stone-800">
            {crop.crop_code}
          </span>
          {crop.etc_computable ? (
            <Badge variant="outline" className="border-emerald-200 bg-emerald-50 text-[10px] text-emerald-800">
              ETc computable
            </Badge>
          ) : (
            <Badge variant="outline" className="border-stone-300 bg-stone-50 text-[10px] text-stone-500">
              ETc not evaluated
            </Badge>
          )}
        </span>
        <span className="flex shrink-0 items-center gap-2">
          <Badge variant="outline" className={`text-[10px] capitalize ${overallStyle}`}>
            {crop.overall.replace('_', ' ')}
          </Badge>
          <ChevronDown className={`h-4 w-4 text-stone-400 transition-transform ${open ? 'rotate-180' : ''}`} aria-hidden />
        </span>
      </button>
      {open && (
        <div className="space-y-1.5 border-t border-stone-100 px-3 py-2">
          {Object.entries(crop.dimensions).map(([key, dim]) => (
            <div key={key} className="flex items-start justify-between gap-2 text-xs">
              <span className="min-w-0">
                <span className="font-medium capitalize text-stone-700">
                  {key.replace(/_/g, '')}
                </span>
                <span className="block text-stone-500">{dim.detail}</span>
              </span>
              <Badge
                variant="outline"
                className={`shrink-0 text-[10px] ${READINESS_STYLES[dim.status] ?? ''}`}
              >
                {dim.status.replace(/_/g, ' ')}
              </Badge>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

// ------------------------------------------------------------- plan form

interface PlanSeasonForm {
  label: string
  start: string
  end: string
  crop: string
  sowing: string
}

const PE_METHOD_LABELS: Record<string, string> = {
  fao_aglw_1986: 'FAO-33 (Brouwer & Heibloem 1986)',
  constant_fraction: 'Constant fraction (farmer-supplied)',
  none: 'None — rainfall credit unknown',
}

function PlanBuilderCard({ onPlanCreated }: { onPlanCreated: (id: string) => void }) {
  const selectedField = useFieldShiftUi((s) => s.selectedField)
  const queryClient = useQueryClient()
  const { toast } = useToast()
  const methods = useWaterMethods()
  const crops = useKnowledgeCrops(true)

  const [expert, setExpert] = useState(false)
  const [seasons, setSeasons] = useState<PlanSeasonForm[]>([
    { label: 'summer_2026', start: '2026-05-01', end: '2026-09-15', crop: 'maize', sowing: '' },
  ])
  const [allocation, setAllocation] = useState('45000')
  const [allocationEnabled, setAllocationEnabled] = useState(true)
  const [soilSource, setSoilSource] = useState<'none' | 'farmer_measured' | 'ptf_texture'>('none')
  const [thetaFc, setThetaFc] = useState('')
  const [thetaWp, setThetaWp] = useState('')
  const [zr, setZr] = useState('')
  const [pTable, setPTable] = useState('')
  const [peMethod, setPeMethod] = useState('fao_aglw_1986')
  const [peFraction, setPeFraction] = useState('')
  const [efficiencyClass, setEfficiencyClass] = useState('surface')
  const [efficiencyValue, setEfficiencyValue] = useState('')
  const [efficiencyEnabled, setEfficiencyEnabled] = useState(false)

  const cropOptions = useMemo(
    () => (crops.data?.crops ?? []).map((c) => c.crop_code).sort(),
    [crops.data],
  )

  const createMutation = useMutation({
    mutationFn: (fieldId: string) => {
      const farmerSoilValid =
        soilSource === 'farmer_measured' && thetaFc !== '' && thetaWp !== ''
      if (soilSource === 'farmer_measured' && !farmerSoilValid) {
        throw new Error('Farmer-measured soil needs field capacity and wilting point (m³/m³).')
      }
      return createWaterPlan(fieldId, {
        label: `Water plan ${new Date().toISOString().slice(0, 10)}`,
        seasons: seasons.map((s) => ({
          label: s.label || 'season',
          start_date: s.start,
          end_date: s.end,
        })),
        crop_assignments: seasons.map((s) => ({ crop_code: s.crop })),
        sowing_dates: Object.fromEntries(
          seasons.filter((s) => s.sowing).map((s) => [s.label || 'season', s.sowing]),
        ),
        soil_source: soilSource,
        farmer_soil:
          soilSource === 'farmer_measured' && farmerSoilValid
            ? {
                theta_fc: Number(thetaFc),
                theta_wp: Number(thetaWp),
                ...(zr !== '' ? { zr_m: Number(zr) } : {}),
                ...(pTable !== '' ? { p_table: Number(pTable) } : {}),
              }
            : undefined,
        effective_rainfall_method: peMethod,
        pe_fraction:
          peMethod === 'constant_fraction' && peFraction !== ''
            ? Number(peFraction)
            : undefined,
        irrigation_efficiency: efficiencyEnabled
          ? efficiencyValue !== ''
            ? { value: Number(efficiencyValue) }
            : { method_class: efficiencyClass }
          : undefined,
        water_allocation_m3: allocationEnabled && allocation !== '' ? Number(allocation) : null,
      })
    },
    onSuccess: (plan) => {
      queryClient.invalidateQueries({ queryKey: ['water-plans', selectedField?.id] })
      onPlanCreated(plan.id)
      toast({ title: 'Water plan created', description: `Checksum ${plan.checksum_sha256?.slice(0, 12)}…` })
    },
    onError: (err) => {
      const d = describeError(err)
      toast({ title: d.title, description: d.description, variant: 'destructive' })
    },
  })

  if (!selectedField) return null

  const updateSeason = (idx: number, patch: Partial<PlanSeasonForm>) =>
    setSeasons((prev) => prev.map((s, i) => (i === idx ? { ...s, ...patch } : s)))

  return (
    <Card>
      <CardHeader className="pb-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div>
            <CardTitle className="flex items-center gap-2 text-base">
              <Droplets className="h-4 w-4 text-emerald-700" aria-hidden />
              Seasonal water plan
            </CardTitle>
            <CardDescription>
              ETc = Kc × ET0 (FAO-56 single curve), effective rainfall, the net
              and gross irrigation requirement, and the allocation check —
              every assumption disclosed with the result.
            </CardDescription>
          </div>
          <div className="flex items-center gap-2 text-xs text-stone-500">
            <span aria-hidden>Simple</span>
            <Switch
              checked={expert}
              onCheckedChange={setExpert}
              aria-label="Toggle expert mode"
            />
            <span aria-hidden>Expert</span>
          </div>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="space-y-2">
          {seasons.map((s, i) => (
            <div key={i} className="grid grid-cols-2 gap-2 sm:grid-cols-5">
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
              <Select
                value={s.crop}
                onValueChange={(v) => updateSeason(i, { crop: v })}
              >
                <SelectTrigger className="h-9 text-sm" aria-label={`Season ${i + 1} crop`}>
                  <SelectValue placeholder="Crop" />
                </SelectTrigger>
                <SelectContent className="max-h-72">
                  {cropOptions.map((code) => (
                    <SelectItem key={code} value={code} className="text-sm">
                      {code}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              {expert ? (
                <Input
                  type="date"
                  value={s.sowing}
                  onChange={(e) => updateSeason(i, { sowing: e.target.value })}
                  className="h-9 text-sm"
                  aria-label={`Season ${i + 1} sowing date (optional)`}
                  placeholder="Sowing"
                />
              ) : (
                <Button
                  variant="ghost"
                  size="sm"
                  className="h-9 text-xs text-stone-500"
                  onClick={() => setSeasons((prev) => prev.filter((_, j) => j !== i))}
                  disabled={seasons.length === 1}
                >
                  Remove
                </Button>
              )}
            </div>
          ))}
          <Button
            variant="outline"
            size="sm"
            className="text-xs"
            onClick={() =>
              setSeasons((prev) => [
                ...prev,
                {
                  label: `season_${prev.length + 1}`,
                  start: '2026-05-01',
                  end: '2026-09-15',
                  crop: cropOptions[0] ?? 'maize',
                  sowing: '',
                },
              ])
            }
            disabled={seasons.length >= 4}
          >
            Add season
          </Button>
        </div>

        <div className="grid gap-3 sm:grid-cols-2">
          <div className="space-y-1.5">
            <div className="flex items-center justify-between">
              <Label htmlFor="water-allocation" className="text-xs text-stone-600">
                Seasonal water allocation (m³)
              </Label>
              <Switch
                checked={allocationEnabled}
                onCheckedChange={setAllocationEnabled}
                aria-label="Toggle allocation constraint"
                className="scale-90"
              />
            </div>
            <Input
              id="water-allocation"
              type="number"
              min="0"
              value={allocation}
              onChange={(e) => setAllocation(e.target.value)}
              disabled={!allocationEnabled}
              className="h-9 text-sm"
              placeholder="Leave off if unknown — never assumed unlimited"
            />
            {!allocationEnabled && (
              <p className="text-[11px] text-amber-700">
                Allocation unknown — the plan reports it as unknown, never as
                unlimited water.
              </p>
            )}
          </div>

          <div className="space-y-1.5">
            <Label className="text-xs text-stone-600">Soil water-holding inputs</Label>
            <Select value={soilSource} onValueChange={(v) => setSoilSource(v as typeof soilSource)}>
              <SelectTrigger className="h-9 text-sm" aria-label="Soil source">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="none" className="text-sm">None — FAO-33 no-storage method</SelectItem>
                <SelectItem value="farmer_measured" className="text-sm">Farmer-measured θFC/θWP</SelectItem>
                <SelectItem value="ptf_texture" className="text-sm">Estimate from texture (Saxton-Rawls PTF)</SelectItem>
              </SelectContent>
            </Select>
            {soilSource === 'farmer_measured' && (
              <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
                <Input type="number" step="0.01" min="0" max="0.6" value={thetaFc} onChange={(e) => setThetaFc(e.target.value)} className="h-9 text-sm" placeholder="θFC" aria-label="Field capacity m3/m3" />
                <Input type="number" step="0.01" min="0" max="0.6" value={thetaWp} onChange={(e) => setThetaWp(e.target.value)} className="h-9 text-sm" placeholder="θWP" aria-label="Wilting point m3/m3" />
                <Input type="number" step="0.1" min="0" value={zr} onChange={(e) => setZr(e.target.value)} className="h-9 text-sm" placeholder="Zr (m)" aria-label="Root zone depth metres (optional)" />
                <Input type="number" step="0.01" min="0" max="1" value={pTable} onChange={(e) => setPTable(e.target.value)} className="h-9 text-sm" placeholder="p" aria-label="Depletion fraction (optional)" />
              </div>
            )}
            {soilSource === 'ptf_texture' && (
              <p className="text-[11px] text-stone-500">
                Estimated from the field&apos;s texture observations
                (Saxton &amp; Rawls 2006; validity domain enforced). A
                texture-based estimate — never a measurement.
              </p>
            )}
          </div>
        </div>

        {expert && (
          <div className="grid gap-3 sm:grid-cols-2">
            <div className="space-y-1.5">
              <Label className="text-xs text-stone-600">Effective-rainfall method</Label>
              <Select value={peMethod} onValueChange={setPeMethod}>
                <SelectTrigger className="h-9 text-sm" aria-label="Effective rainfall method">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {(methods.data?.effective_rainfall_methods ?? []).map((m) => (
                    <SelectItem key={m.code} value={m.code} className="text-sm">
                      {PE_METHOD_LABELS[m.code] ?? m.code}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              {peMethod === 'constant_fraction' && (
                <Input
                  type="number" step="0.05" min="0" max="1"
                  value={peFraction}
                  onChange={(e) => setPeFraction(e.target.value)}
                  className="h-9 text-sm"
                  placeholder="Fraction (0–1)"
                  aria-label="Effective rainfall fraction"
                />
              )}
            </div>
            <div className="space-y-1.5">
              <div className="flex items-center justify-between">
                <Label className="text-xs text-stone-600">Application efficiency</Label>
                <Switch
                  checked={efficiencyEnabled}
                  onCheckedChange={setEfficiencyEnabled}
                  aria-label="Toggle application efficiency"
                  className="scale-90"
                />
              </div>
              {efficiencyEnabled && (
                <div className="grid grid-cols-2 gap-2">
                  <Select value={efficiencyClass} onValueChange={setEfficiencyClass}>
                    <SelectTrigger className="h-9 text-sm" aria-label="Efficiency method class">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {(methods.data?.irrigation_efficiency_classes ?? []).map((c) => (
                        <SelectItem key={c.method_class} value={c.method_class} className="text-sm">
                          {c.method_class} ({Math.round(c.efficiency * 100)}%)
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                  <Input
                    type="number" step="0.05" min="0.05" max="1"
                    value={efficiencyValue}
                    onChange={(e) => setEfficiencyValue(e.target.value)}
                    className="h-9 text-sm"
                    placeholder="Or farmer value"
                    aria-label="Farmer application efficiency"
                  />
                </div>
              )}
            </div>
          </div>
        )}

        <Button
          size="sm"
          className="w-full sm:w-auto"
          onClick={() => selectedField.id && createMutation.mutate(selectedField.id)}
          disabled={createMutation.isPending || !selectedField.id}
        >
          {createMutation.isPending ? 'Computing plan…' : 'Compute water plan'}
        </Button>
      </CardContent>
    </Card>
  )
}

// ------------------------------------------------------------- results

function AllocationBadge({ allocation }: { allocation: WaterPlanSeason['allocation'] }) {
  if (allocation.status === 'unknown') {
    return (
      <Badge variant="outline" className="border-stone-300 bg-stone-100 text-stone-600">
        allocation unknown
      </Badge>
    )
  }
  if (allocation.status === 'not_evaluated') {
    return (
      <Badge variant="outline" className="border-amber-200 bg-amber-50 text-amber-800">
        allocation not evaluated
      </Badge>
    )
  }
  if (allocation.status === 'deficit') {
    return (
      <Badge variant="outline" className="border-red-200 bg-red-50 text-red-800">
        deficit {fmt(allocation.deficit_m3, 0)} m³
      </Badge>
    )
  }
  return (
    <Badge variant="outline" className="border-emerald-200 bg-emerald-50 text-emerald-800">
      within allocation ({Math.round((allocation.coverage_ratio ?? 0) * 100)}%)
    </Badge>
  )
}

function StageTimeline({ season }: { season: WaterPlanSeason }) {
  const stages = season.stages
  const maxEtc = Math.max(...stages.map((s) => s.etc_mm ?? 0), 1)
  const stageColors: Record<string, string> = {
    initial: 'bg-amber-300',
    development: 'bg-lime-400',
    mid: 'bg-emerald-500',
    late: 'bg-teal-500',
  }
  return (
    <div className="space-y-2">
      <div className="flex h-8 w-full overflow-hidden rounded-md border border-stone-200" role="img" aria-label="Seasonal ETc by growth stage">
        {stages.map((s) => (
          <div
            key={s.stage}
            className={`flex items-center justify-center ${stageColors[s.stage] ?? 'bg-stone-300'}`}
            style={{ width: `${((s.etc_mm ?? 0) / maxEtc) * 100}%` }}
            title={`${s.stage}: ${fmt(s.etc_mm)} mm ETc over ${s.days_in_season} days`}
          >
            <span className="truncate px-1 text-[10px] font-medium text-stone-800">
              {fmt(s.etc_mm, 0)} mm
            </span>
          </div>
        ))}
      </div>
      <div className="overflow-x-auto scrollbar-thin">
        <table className="w-full min-w-[560px] text-left text-xs">
          <thead className="text-stone-500">
            <tr>
              <th className="py-1 pr-2 font-medium">Stage</th>
              <th className="py-1 pr-2 font-medium">Window</th>
              <th className="py-1 pr-2 font-medium">Days</th>
              <th className="py-1 pr-2 font-medium">Kc mean</th>
              <th className="py-1 pr-2 font-medium">ETc (mm)</th>
              <th className="py-1 pr-2 font-medium">Pe (mm)</th>
              <th className="py-1 pr-2 font-medium">Dr end (mm)</th>
              <th className="py-1 font-medium">Ks mean</th>
            </tr>
          </thead>
          <tbody>
            {stages.map((s) => (
              <tr key={s.stage} className="border-t border-stone-100">
                <td className="py-1 pr-2 font-medium capitalize text-stone-700">{s.stage}</td>
                <td className="py-1 pr-2 text-stone-500">
                  {s.dates[0]} → {s.dates[1]}
                </td>
                <td className="py-1 pr-2 text-stone-500">{s.days_in_season}</td>
                <td className="py-1 pr-2 text-stone-700">{fmt(s.kc_mean, 2)}</td>
                <td className="py-1 pr-2 text-stone-700">{fmt(s.etc_mm)}</td>
                <td className="py-1 pr-2 text-stone-700">{fmt(s.pe_mm)}</td>
                <td className="py-1 pr-2 text-stone-700">{fmt(s.dr_end_mm)}</td>
                <td className="py-1 text-stone-700">{fmt(s.ks_mean, 2)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

function MonthlyTable({ season }: { season: WaterPlanSeason }) {
  return (
    <div className="overflow-x-auto scrollbar-thin">
      <table className="w-full min-w-[620px] text-left text-xs">
        <thead className="text-stone-500">
          <tr>
            <th className="py-1 pr-2 font-medium">Month</th>
            <th className="py-1 pr-2 font-medium">ET0 (mm)</th>
            <th className="py-1 pr-2 font-medium">Kc mean</th>
            <th className="py-1 pr-2 font-medium">ETc (mm)</th>
            <th className="py-1 pr-2 font-medium">P (mm)</th>
            <th className="py-1 pr-2 font-medium">Pe (mm)</th>
            <th className="py-1 pr-2 font-medium">Net irr. (mm)</th>
            <th className="py-1 font-medium">Dr end (mm)</th>
          </tr>
        </thead>
        <tbody>
          {season.months.map((m) => (
            <tr key={`${m.year}-${m.month}`} className="border-t border-stone-100">
              <td className="py-1 pr-2 font-medium text-stone-700">
                {m.year}-{String(m.month).padStart(2, '0')}
              </td>
              <td className="py-1 pr-2 text-stone-700">{fmt(m.et0_mm)}</td>
              <td className="py-1 pr-2 text-stone-700">{fmt(m.kc_mean, 2)}</td>
              <td className="py-1 pr-2 text-stone-700">{fmt(m.etc_mm)}</td>
              <td className={`py-1 pr-2 ${m.precip_evidence_missing ? 'text-amber-700' : 'text-stone-700'}`}>
                {m.precip_evidence_missing ? 'no evidence' : fmt(m.precip_mm)}
              </td>
              <td className="py-1 pr-2 text-stone-700">{fmt(m.effective_rainfall_mm)}</td>
              <td className="py-1 pr-2 text-stone-700">{fmt(m.net_irrigation_mm)}</td>
              <td className="py-1 text-stone-700">{fmt(m.dr_end_mm)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function LadderCard({ season }: { season: WaterPlanSeason }) {
  const label: Record<string, string> = {
    crop_evapotranspiration: 'Crop evapotranspiration (ETc)',
    effective_rainfall: 'Effective rainfall (Pe)',
    soil_water_contribution: 'Soil-water contribution (ΔSW)',
    net_irrigation_requirement: 'Net irrigation requirement',
    gross_irrigation_requirement: 'Gross irrigation requirement',
    actual_irrigation_applied: 'Actual irrigation applied',
  }
  return (
    <div className="space-y-1.5">
      {season.ladder.map((step) => {
        const muted = step.status !== 'evaluated'
        return (
          <div key={step.quantity} className="flex items-start justify-between gap-3 text-xs">
            <span className="min-w-0">
              <span className={`font-medium ${muted ? 'text-stone-500' : 'text-stone-800'}`}>
                {label[step.quantity] ?? step.quantity}
              </span>
              <span className="block text-stone-500">{step.basis}</span>
              {step.detail && <span className="block text-stone-400">{step.detail}</span>}
            </span>
            <span className="shrink-0 text-right">
              <span className={`font-semibold ${muted ? 'text-stone-400' : 'text-stone-900'}`}>
                {step.value_mm === null ? '(not evaluated)' : `${fmt(step.value_mm, 1)} mm`}
              </span>
              {season.volumes_m3[`${step.quantity}_m3`] !== undefined && !muted && (
                <span className="block text-stone-500">
                  ≈ {fmt(season.volumes_m3[`${step.quantity}_m3`], 0)} m³
                </span>
              )}
            </span>
          </div>
        )
      })}
    </div>
  )
}

function SeasonPlanCard({ season }: { season: WaterPlanSeason }) {
  const totals = season.totals
  return (
    <Card>
      <CardHeader className="pb-2">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <CardTitle className="text-sm font-semibold text-stone-800">
            {season.season_label} · {season.crop_code}
          </CardTitle>
          <AllocationBadge allocation={season.allocation} />
        </div>
        <CardDescription>
          {season.season.start_date} → {season.season.end_date} · sowing{' '}
          {season.sowing_date} · {fmt(season.area_ha, 2)} ha
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
          {[
            { label: 'Reference ET0', value: `${fmt(totals.et0_mm)} mm`, hint: 'FAO-56 reference surface' },
            { label: 'Crop ETc', value: `${fmt(totals.etc_mm)} mm`, hint: 'Kc × ET0' },
            { label: 'Effective rainfall', value: `${fmt(totals.effective_rainfall_mm)} mm`, hint: season.effective_rainfall.method },
            { label: 'Net irrigation', value: `${fmt(totals.net_irrigation_requirement_mm)} mm`, hint: '≈ ' + fmt(totals.volumes_m3.net_irrigation_requirement_m3, 0) + ' m³' },
          ].map((tile) => (
            <div key={tile.label} className="rounded-lg border border-stone-200 bg-stone-50 px-3 py-2">
              <p className="text-[11px] font-medium uppercase tracking-wide text-stone-500">{tile.label}</p>
              <p className="text-sm font-semibold text-stone-900">{tile.value}</p>
              <p className="text-[10px] text-stone-400">{tile.hint}</p>
            </div>
          ))}
        </div>

        <div className="grid gap-4 lg:grid-cols-2">
          <div className="min-w-0 space-y-2">
            <p className="flex items-center gap-1.5 text-xs font-semibold text-stone-700">
              <Gauge className="h-3.5 w-3.5 text-emerald-700" aria-hidden /> Growth-stage demand
            </p>
            <StageTimeline season={season} />
          </div>
          <div className="min-w-0 space-y-2">
            <p className="flex items-center gap-1.5 text-xs font-semibold text-stone-700">
              <ScrollText className="h-3.5 w-3.5 text-emerald-700" aria-hidden /> Water ladder
            </p>
            <LadderCard season={season} />
          </div>
        </div>

        <Accordion type="multiple" className="w-full">
          <AccordionItem value="months">
            <AccordionTrigger className="text-xs text-stone-600">
              Monthly timeline
            </AccordionTrigger>
            <AccordionContent>
              <MonthlyTable season={season} />
            </AccordionContent>
          </AccordionItem>
          <AccordionItem value="deficits">
            <AccordionTrigger className="text-xs text-stone-600">
              Deficit windows ({season.deficit_windows.length})
            </AccordionTrigger>
            <AccordionContent>
              {season.deficit_windows.length === 0 ? (
                <p className="text-xs text-stone-500">
                  No root-zone stress windows or allocation shortfall identified.
                </p>
              ) : (
                <ul className="space-y-1.5 text-xs text-stone-600">
                  {season.deficit_windows.map((w, i) => (
                    <li key={i} className="flex items-start gap-2">
                      <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-amber-600" aria-hidden />
                      <span>
                        {String(w.kind).replace(/_/g, ' ')}
                        {w.start_date ? `: ${String(w.start_date)} → ${String(w.end_date)} (${String(w.days)} days, max Dr ${fmt(Number(w.max_dr_mm))} mm)` : ''}
                        {w.deficit_m3 ? `: shortfall ${fmt(Number(w.deficit_m3), 0)} m³` : ''}
                        {w.detail ? ` — ${String(w.detail)}` : ''}
                      </span>
                    </li>
                  ))}
                </ul>
              )}
            </AccordionContent>
          </AccordionItem>
          <AccordionItem value="method">
            <AccordionTrigger className="text-xs text-stone-600">
              Methodology &amp; assumptions ({season.assumptions.length})
            </AccordionTrigger>
            <AccordionContent>
              <ul className="list-disc space-y-1 pl-4 text-xs text-stone-600">
                {season.assumptions.map((a, i) => (
                  <li key={i}>{a}</li>
                ))}
              </ul>
            </AccordionContent>
          </AccordionItem>
          <AccordionItem value="missing">
            <AccordionTrigger className="text-xs text-stone-600">
              Not evaluated ({season.missing_evidence.length})
            </AccordionTrigger>
            <AccordionContent>
              {season.missing_evidence.length === 0 ? (
                <p className="text-xs text-stone-500">Every dimension was evaluable.</p>
              ) : (
                <ul className="list-disc space-y-1 pl-4 text-xs text-amber-800">
                  {season.missing_evidence.map((m, i) => (
                    <li key={i}>{m}</li>
                  ))}
                </ul>
              )}
            </AccordionContent>
          </AccordionItem>
          <AccordionItem value="sources">
            <AccordionTrigger className="text-xs text-stone-600">
              Data provenance ({season.sources.length})
            </AccordionTrigger>
            <AccordionContent>
              <ul className="space-y-1 text-xs text-stone-600">
                {season.sources.map((src, i) => (
                  <li key={i}>
                    <span className="font-medium capitalize">
                      {String(src.type ?? 'source').replace(/_/g, ' ')}
                    </span>
                    {src.citation_text ? ` — ${String(src.citation_text)}` : ''}
                    {src.basis ? ` — ${String(src.basis)}` : ''}
                    {src.validation_status ? ` (${String(src.validation_status)})` : ''}
                  </li>
                ))}
              </ul>
              <p className="mt-2 flex items-center gap-1 text-[10px] text-stone-400">
                <ShieldCheck className="h-3 w-3" aria-hidden />
                plan checksum {season.checksum_sha256}
              </p>
            </AccordionContent>
          </AccordionItem>
        </Accordion>
      </CardContent>
    </Card>
  )
}

function PlanHistory({
  selectedFieldId,
  activePlanId,
  onSelect,
}: {
  selectedFieldId: string | null
  activePlanId: string | null
  onSelect: (id: string) => void
}) {
  const plans = useWaterPlans(selectedFieldId)
  const queryClient = useQueryClient()
  const { toast } = useToast()
  const deleteMutation = useMutation({
    mutationFn: (planId: string) => deleteWaterPlan(planId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['water-plans', selectedFieldId] })
      toast({ title: 'Plan deleted' })
    },
  })

  if (!selectedFieldId) return null
  const items = plans.data?.items ?? []

  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="text-base">Plan history</CardTitle>
        <CardDescription>
          Immutable snapshots — re-running a scenario creates a new plan, never
          overwrites.
        </CardDescription>
      </CardHeader>
      <CardContent>
        {items.length === 0 ? (
          <p className="text-sm text-stone-500">No plans yet.</p>
        ) : (
          <div className="max-h-96 space-y-2 overflow-y-auto pr-1 scrollbar-thin">
            {items.map((plan: WaterPlan) => (
              <div
                key={plan.id}
                className={`flex items-center justify-between gap-2 rounded-lg border px-3 py-2 text-xs ${
                  plan.id === activePlanId
                    ? 'border-emerald-300 bg-emerald-50'
                    : 'border-stone-200 bg-white'
                }`}
              >
                <button
                  type="button"
                  className="min-w-0 flex-1 text-left"
                  onClick={() => onSelect(plan.id)}
                >
                  <span className="block truncate font-medium text-stone-800">{plan.label}</span>
                  <span className="block truncate text-stone-500">
                    {(plan.seasons ?? []).map((s) => s.label).join(', ') || '—'} ·{' '}
                    {plan.methods?.effective_rainfall_method ?? '—'} ·{' '}
                    {plan.checksum_sha256 ? plan.checksum_sha256.slice(0, 8) : '—'}
                  </span>
                </button>
                <Badge
                  variant="outline"
                  className={
                    plan.status === 'succeeded'
                      ? 'border-emerald-200 bg-white text-emerald-800'
                      : 'border-red-200 bg-white text-red-700'
                  }
                >
                  {plan.status}
                </Badge>
                <Button
                  variant="ghost"
                  size="sm"
                  className="h-7 px-2 text-stone-400 hover:text-red-700"
                  onClick={() => deleteMutation.mutate(plan.id)}
                  disabled={deleteMutation.isPending}
                  aria-label={`Delete plan ${plan.label}`}
                >
                  ×
                </Button>
              </div>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  )
}

export function Water() {
  const selectedField = useFieldShiftUi((s) => s.selectedField)
  const setSelectedField = useFieldShiftUi((s) => s.setSelectedField)
  const goToObservationsFor = useFieldShiftUi((s) => s.goToObservationsFor)
  const [activePlanId, setActivePlanId] = useState<string | null>(null)
  const plan = useWaterPlan(activePlanId)
  const methods = useWaterMethods()

  const hasField = !!selectedField

  return (
    <div className="space-y-4">
      {!hasField ? (
        <Card>
          <CardContent className="py-10 text-center text-sm text-stone-500">
            <div className="flex flex-wrap items-center justify-center gap-2">
              <span>Pick a field to plan its water. Methodology is public:</span>
              <a
                className="text-emerald-800 underline decoration-dotted"
                href="#water-methods"
              >
                see below
              </a>
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
          <PlanBuilderCard onPlanCreated={setActivePlanId} />
          {plan.data?.warnings && plan.data.warnings.length > 0 && (
            <div className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">
              <ul className="list-disc space-y-0.5 pl-4">
                {plan.data.warnings.map((w, i) => (
                  <li key={i}>{w}</li>
                ))}
              </ul>
            </div>
          )}
          {plan.data?.result?.seasons.map((season) => (
            <SeasonPlanCard key={season.season_label + season.crop_code} season={season} />
          ))}
          {plan.data?.result && (
            <Card>
              <CardContent className="flex flex-wrap items-center justify-between gap-2 py-3 text-xs text-stone-600">
                <span className="flex items-center gap-1.5">
                  <Info className="h-3.5 w-3.5 text-stone-400" aria-hidden />
                  {plan.data.result.rotation_totals.note}
                </span>
                <span className="flex items-center gap-3">
                  <span>
                    rotation NIR total ≈{' '}
                    <strong className="text-stone-900">
                      {fmt(plan.data.result.rotation_totals.net_irrigation_requirement_m3_sum, 0)} m³
                    </strong>
                  </span>
                  <span>
                    engine {plan.data.result.engine_version} · methods{' '}
                    {plan.data.result.methods_version}
                  </span>
                </span>
              </CardContent>
            </Card>
          )}
          <PlanHistory
            selectedFieldId={selectedField.id}
            activePlanId={activePlanId}
            onSelect={setActivePlanId}
          />
          <ReadinessCard />
        </>
      )}

      <Card id="water-methods">
        <CardHeader className="pb-3">
          <CardTitle className="flex items-center gap-2 text-base">
            <ScrollText className="h-4 w-4 text-emerald-700" aria-hidden />
            Water methodology disclosures
          </CardTitle>
          <CardDescription>
            Every calculation cites its published method. Methods that could not
            be verified from primary sources are listed as not implemented —
            never approximated.
          </CardDescription>
        </CardHeader>
        <CardContent>
          {methods.data ? (
            <Accordion type="multiple" className="w-full">
              <AccordionItem value="pe">
                <AccordionTrigger className="text-xs text-stone-600">
                  Effective-rainfall methods ({methods.data.effective_rainfall_methods.length})
                </AccordionTrigger>
                <AccordionContent>
                  <ul className="space-y-2 text-xs text-stone-600">
                    {methods.data.effective_rainfall_methods.map((m) => (
                      <li key={m.code}>
                        <p className="font-semibold text-stone-800">{m.code}</p>
                        <p>{m.formula}</p>
                        <p className="text-stone-500">{m.conditions}</p>
                        <p className="text-stone-400">{m.citation_text}</p>
                      </li>
                    ))}
                  </ul>
                </AccordionContent>
              </AccordionItem>
              <AccordionItem value="soil">
                <AccordionTrigger className="text-xs text-stone-600">
                  Soil water-holding sources
                </AccordionTrigger>
                <AccordionContent>
                  <ul className="space-y-1.5 text-xs text-stone-600">
                    {methods.data.soil_sources.map((s) => (
                      <li key={s.code}>
                        <span className="font-semibold text-stone-800">{s.code}</span> — {s.detail}
                      </li>
                    ))}
                  </ul>
                </AccordionContent>
              </AccordionItem>
              <AccordionItem value="efficiency">
                <AccordionTrigger className="text-xs text-stone-600">
                  Application-efficiency classes (FAO TM1 Annex I, Table 8)
                </AccordionTrigger>
                <AccordionContent>
                  <ul className="space-y-1.5 text-xs text-stone-600">
                    {methods.data.irrigation_efficiency_classes.map((c) => (
                      <li key={c.method_class}>
                        <span className="font-semibold capitalize text-stone-800">{c.method_class}</span>{' '}
                        — {Math.round(c.efficiency * 100)}% ({c.applies_to})
                      </li>
                    ))}
                  </ul>
                </AccordionContent>
              </AccordionItem>
              <AccordionItem value="not-implemented">
                <AccordionTrigger className="text-xs text-stone-600">
                  Deliberately not implemented ({methods.data.not_implemented.length})
                </AccordionTrigger>
                <AccordionContent>
                  <ul className="space-y-1.5 text-xs text-stone-600">
                    {methods.data.not_implemented.map((n) => (
                      <li key={n.item}>
                        <span className="font-semibold text-stone-800">{n.item}</span> — {n.reason}
                      </li>
                    ))}
                  </ul>
                  <p className="mt-2 text-[11px] text-stone-500">
                    Unit identities: 1 mm over 1 ha = 10 m³; 1 mm over 1 m² = 1 L.
                  </p>
                </AccordionContent>
              </AccordionItem>
            </Accordion>
          ) : (
            <p className="text-sm text-stone-500">Loading methodology…</p>
          )}
        </CardContent>
      </Card>
    </div>
  )
}

export default Water
