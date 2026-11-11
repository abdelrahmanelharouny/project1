'use client'

/**
 * P2.F — Farm Portfolio Intelligence tab: farm-level crop-area allocation
 * under shared resource constraints, with the disclosed steering-objective
 * rules (per-criterion values always separate), binding-constraint report,
 * portfolio-vs-independent trade-offs and the resilience scenario.
 */

import { useState } from 'react'
import { useTranslations } from 'next-intl'
import { toast } from 'sonner'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Skeleton } from '@/components/ui/skeleton'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { FieldPicker } from '@/components/croptwist/field-picker'
import {
  useCreatePortfolioRun,
  usePortfolioConstraints,
  usePortfolioRun,
  usePortfolioRuns,
} from '@/hooks/use-croptwist'
import { useCropTwistUi } from '@/lib/store'
import { describeError } from '@/lib/api'

export function FarmPortfolio() {
  const t = useTranslations('portfolio')
  const selectedField = useCropTwistUi((s) => s.selectedField)
  const setSelectedField = useCropTwistUi((s) => s.setSelectedField)
  const farms = useCropTwistUi((s) => s.selectedFarmId)
  const [waterAllocation, setWaterAllocation] = useState<string>('5000')
  const [familyShare, setFamilyShare] = useState<string>('')
  const [waterMultiplier, setWaterMultiplier] = useState<string>('1')
  const [mode, setMode] = useState<string>('weighted')
  const [lastRunId, setLastRunId] = useState<string | null>(null)

  const constraintsInfo = usePortfolioConstraints()
  const farmId = selectedField?.farmId ?? farms ?? null
  const runs = usePortfolioRuns(farmId)
  const runMutation = useCreatePortfolioRun(farmId)
  const runDetail = usePortfolioRun(lastRunId)

  if (!selectedField) {
    return (
      <Card>
        <CardContent className="py-10 text-center text-sm text-stone-500">
          <p>{t('pickFarmHint')}</p>
          <div className="mx-auto mt-4 max-w-xs">
            <FieldPicker value={null} onValueChange={setSelectedField} />
          </div>
        </CardContent>
      </Card>
    )
  }

  const payload = {
    season_count: 1,
    mode,
    constraints: {
      water_allocation_m3: waterAllocation ? Number(waterAllocation) : null,
      max_family_share: familyShare ? Number(familyShare) : null,
    },
    scenario:
      waterMultiplier && Number(waterMultiplier) !== 1
        ? { water_allocation_multiplier: Number(waterMultiplier), label: 'water stress' }
        : null,
  }

  const result = runDetail.data?.result ?? null
  const allocations = runDetail.data?.allocations ?? []

  return (
    <div className="space-y-4" dir="ltr">
      <Card>
        <CardHeader>
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div>
              <CardTitle>{t('title')}</CardTitle>
              <CardDescription>{t('description')}</CardDescription>
            </div>
            <FieldPicker value={selectedField.id} onValueChange={setSelectedField} />
          </div>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="flex flex-wrap items-end gap-3 text-xs">
            <label className="flex flex-col gap-1">
              <span>{t('waterAllocation')}</span>
              <Input className="w-36" type="number" min="0" value={waterAllocation} onChange={(e) => setWaterAllocation(e.target.value)} />
            </label>
            <label className="flex flex-col gap-1">
              <span>{t('familyShare')}</span>
              <Input className="w-28" type="number" min="0.1" max="1" step="0.05" value={familyShare} onChange={(e) => setFamilyShare(e.target.value)} placeholder="—" />
            </label>
            <label className="flex flex-col gap-1">
              <span>{t('waterMultiplier')}</span>
              <Input className="w-24" type="number" min="0" max="1.5" step="0.1" value={waterMultiplier} onChange={(e) => setWaterMultiplier(e.target.value)} />
            </label>
            <label className="flex flex-col gap-1">
              <span>{t('mode')}</span>
              <select className="h-9 rounded-md border border-stone-200 px-2" value={mode} onChange={(e) => setMode(e.target.value)}>
                <option value="weighted">{t('weighted')}</option>
                <option value="lexicographic">{t('lexicographic')}</option>
              </select>
            </label>
            <Button
              size="sm"
              disabled={runMutation.isPending}
              onClick={() =>
                runMutation.mutate(payload, {
                  onSuccess: (data) => {
                    setLastRunId(data.id)
                    toast.success(t('runDone'))
                  },
                  onError: (err) => {
                    const d = describeError(err)
                    toast.error(d.title, { description: d.description })
                  },
                })
              }
            >
              {runMutation.isPending ? t('running') : t('run')}
            </Button>
          </div>

          {constraintsInfo.data && (
            <ul className="list-disc space-y-0.5 ps-4 text-xs text-stone-500">
              {constraintsInfo.data.disclosures.map((d, i) => (
                <li key={i}>{d}</li>
              ))}
            </ul>
          )}
          {runMutation.data?.not_evaluated && runMutation.data.not_evaluated.length > 0 && (
            <div className="rounded-md border border-amber-200 bg-amber-50/60 p-2 text-xs text-amber-900">
              <p className="font-semibold">{t('notEvaluated')}</p>
              <ul className="list-disc ps-4">
                {runMutation.data.not_evaluated.slice(0, 3).map((n, i) => (
                  <li key={i}>{n.reason.slice(0, 220)}</li>
                ))}
              </ul>
            </div>
          )}
        </CardContent>
      </Card>

      {runDetail.isLoading && <Skeleton className="h-32 w-full" />}
      {runDetail.data && (
        <>
          <Card>
            <CardHeader>
              <CardTitle className="text-base">{t('allocations')}</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="max-h-64 overflow-y-auto scrollbar-thin">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>{t('field')}</TableHead>
                      <TableHead>{t('season')}</TableHead>
                      <TableHead>{t('crop')}</TableHead>
                      <TableHead>{t('area')}</TableHead>
                      <TableHead>{t('status')}</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {allocations.map((a, i) => (
                      <TableRow key={i}>
                        <TableCell className="text-xs">{a.field_id.slice(0, 8)}…</TableCell>
                        <TableCell className="text-xs">{a.season_label}</TableCell>
                        <TableCell className="text-xs">{a.crop_code}</TableCell>
                        <TableCell className="text-xs">{a.area_ha.toFixed(2)}</TableCell>
                        <TableCell className="text-xs">
                          <Badge variant={a.status === 'assigned' ? 'default' : 'secondary'}>
                            {a.status === 'assigned' ? t('assigned') : t('fallow')}
                          </Badge>
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>
            </CardContent>
          </Card>

          <div className="grid gap-4 md:grid-cols-2">
            <Card>
              <CardHeader>
                <CardTitle className="text-base">{t('bindingConstraints')}</CardTitle>
              </CardHeader>
              <CardContent className="space-y-1 text-xs">
                {(!result?.binding_constraints || result.binding_constraints.length === 0) && (
                  <p className="text-stone-500">{t('noBinding')}</p>
                )}
                {result?.binding_constraints?.map((c, i) => (
                  <p key={i}>
                    <span className="font-medium">{String(c.name)}</span>
                    {c.limit != null && c.used != null
                      ? ` — ${Number(c.used).toFixed(1)} / ${Number(c.limit).toFixed(1)} ${String(c.unit ?? '')}`
                      : ''}
                  </p>
                ))}
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle className="text-base">{t('comparison')}</CardTitle>
              </CardHeader>
              <CardContent className="space-y-1 text-xs">
                {result?.independent_comparison?.comparisons.map((c) => (
                  <p key={c.criterion}>
                    <span className="font-medium">{c.criterion}</span>:{' '}
                    {c.portfolio_value != null ? Number(c.portfolio_value).toFixed(3) : '—'} vs{' '}
                    {c.independent_value != null ? Number(c.independent_value).toFixed(3) : '—'}{' '}
                    <Badge variant={c.verdict === 'portfolio' ? 'default' : 'secondary'}>{c.verdict}</Badge>
                  </p>
                ))}
                {result?.independent_comparison?.explanations.map((e, i) => (
                  <p key={i} className="text-stone-500">
                    {e}
                  </p>
                ))}
              </CardContent>
            </Card>
          </div>

          {result?.scenario_evaluation && (
            <Card>
              <CardHeader>
                <CardTitle className="text-base">{t('scenarioResult')}</CardTitle>
              </CardHeader>
              <CardContent className="text-xs">
                <p>
                  <span className="font-medium">{result.scenario_evaluation.verdict}</span> —{' '}
                  {result.scenario_evaluation.detail}
                </p>
                <p className="mt-1 text-stone-500">
                  {result.scenario_evaluation.allocation_deltas?.length ?? 0} allocation delta(s)
                </p>
              </CardContent>
            </Card>
          )}
        </>
      )}
    </div>
  )
}
