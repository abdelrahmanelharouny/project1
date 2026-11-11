'use client'

/**
 * P2.D — Rotation Failure Lab tab: named stress packs, robustness metrics
 * (mathematically defined, same-unit comparisons only) and failure
 * explanations with named constraints and mitigations.
 */

import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useTranslations } from 'next-intl'
import { toast } from 'sonner'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { FieldPicker } from '@/components/croptwist/field-picker'
import {
  useCreateRotationStressRun,
  useRotationStressRuns,
  useStressPacks,
} from '@/hooks/use-croptwist'
import { useCropTwistUi } from '@/lib/store'
import { describeError, getRotationStressRun } from '@/lib/api'
import type { RotationStressRun } from '@/lib/types'

const CANDIDATES = ['baseline', 'recommended', 'alternative'] as const

const METRIC_LABEL_KEYS = [
  'worstCase',
  'meanScore',
  'variance',
  'downsideRisk',
  'feasibilityRate',
  'regret',
] as const

function metricKey(name: string): (typeof METRIC_LABEL_KEYS)[number] | null {
  if (name.includes('worst_case_score')) return 'worstCase'
  if (name.includes('mean_score')) return 'meanScore'
  if (name.includes('variance')) return 'variance'
  if (name.includes('downside_risk')) return 'downsideRisk'
  if (name.includes('feasibility_rate')) return 'feasibilityRate'
  if (name.includes('regret')) return 'regret'
  return null
}

export function FailureLab() {
  const t = useTranslations('failurelab')
  const selectedField = useCropTwistUi((s) => s.selectedField)
  const setSelectedField = useCropTwistUi((s) => s.setSelectedField)
  const [selectedPacks, setSelectedPacks] = useState<string[]>(['water_restriction'])

  const packs = useStressPacks()
  const runs = useRotationStressRuns(selectedField?.id ?? null)
  const run = useCreateRotationStressRun(selectedField?.id ?? null)

  const latestSummary = runs.data?.runs?.[0] ?? null
  const latestDetail = useQuery({
    queryKey: ['rotation-stress-run', latestSummary?.id ?? null],
    queryFn: () => getRotationStressRun(latestSummary!.id),
    enabled: !!latestSummary,
    staleTime: 60_000,
  })
  const latest: RotationStressRun | null = latestDetail.data ?? latestSummary as RotationStressRun | null

  if (!selectedField) {
    return (
      <Card>
        <CardContent className="py-10 text-center text-sm text-stone-500">
          <p>{t('pickFieldHint')}</p>
          <div className="mx-auto mt-4 max-w-xs">
            <FieldPicker value={null} onValueChange={setSelectedField} />
          </div>
        </CardContent>
      </Card>
    )
  }

  const togglePack = (code: string) =>
    setSelectedPacks((prev) => (prev.includes(code) ? prev.filter((c) => c !== code) : [...prev, code]))

  const robustness = (latest?.result?.robustness ?? {}) as Record<
    string,
    Record<string, { value: number | null } & Record<string, unknown>>
  >

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
          <div>
            <h3 className="mb-1 text-sm font-semibold">{t('packs')}</h3>
            {packs.isLoading && <Skeleton className="h-16 w-full" />}
            <div className="flex flex-wrap gap-2">
              {packs.data?.packs?.map((pack) => (
                <button
                  key={pack.code}
                  type="button"
                  onClick={() => togglePack(pack.code)}
                  className={`rounded-md border px-2 py-1 text-xs transition-colors ${
                    selectedPacks.includes(pack.code)
                      ? 'border-emerald-700 bg-emerald-50 text-emerald-900'
                      : 'border-stone-200 bg-white text-stone-600 hover:bg-stone-50'
                  }`}
                  title={pack.assumption_note}
                >
                  {pack.label}
                </button>
              ))}
            </div>
          </div>
          <div className="flex items-center gap-2">
            <Button
              size="sm"
              disabled={run.isPending || selectedPacks.length === 0}
              onClick={() =>
                run.mutate(
                  { packs: selectedPacks, candidates: [...CANDIDATES] },
                  {
                    onSuccess: () => toast.success(t('runDone')),
                    onError: (err) => {
                      const d = describeError(err)
                      toast.error(d.title, { description: d.description ?? t('requiresRotation') })
                    },
                  },
                )
              }
            >
              {run.isPending ? t('running') : t('run')}
            </Button>
            <span className="text-xs text-stone-500">{CANDIDATES.join(' · ')}</span>
          </div>
          {latest?.not_evaluated && latest.not_evaluated.length > 0 && (
            <div className="rounded-md border border-amber-200 bg-amber-50/60 p-2 text-xs text-amber-900">
              <p className="font-semibold">{t('notEvaluated')}</p>
              <ul className="list-disc ps-4">
                {latest.not_evaluated.slice(0, 3).map((n, i) => (
                  <li key={i}>{n.reason}</li>
                ))}
              </ul>
            </div>
          )}
        </CardContent>
      </Card>

      {runs.isLoading && <Skeleton className="h-32 w-full" />}
      {latestDetail.isFetching && !latestDetail.data && <Skeleton className="h-24 w-full" />}
      {latest && latest.result && (
        <>
          <Card>
            <CardHeader>
              <CardTitle className="text-base">{t('robustness')}</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
                {Object.entries(robustness).map(([candidate, metrics]) => (
                  <div key={candidate} className="rounded-md border border-stone-100 bg-stone-50/60 p-2">
                    <p className="mb-1 text-xs font-semibold">{candidate}</p>
                    <div className="space-y-0.5">
                      {Object.entries(metrics)
                        .filter(([, doc]) => metricKey(Object.keys({ [Object.keys(doc).length ? candidate : candidate]: 1 }).length ? candidate : candidate) !== null)
                        .slice(0, 0).length === 0 &&
                        Object.entries(metrics)
                          .filter(([name]) => metricKey(name) !== null)
                          .map(([name, doc]) => (
                            <p key={name} className="text-xs text-stone-600">
                              {t(metricKey(name)!)}: <span className="font-medium">{doc.value != null ? Number(doc.value).toFixed(3) : '—'}</span>
                            </p>
                          ))}
                    </div>
                  </div>
                ))}
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="text-base">{t('evaluations')}</CardTitle>
            </CardHeader>
            <CardContent className="space-y-1">
              {(latest.result?.evaluations ?? []).slice(0, 12).map((ev, i) => (
                <div key={i} className="flex flex-wrap items-center gap-2 rounded border border-stone-100 bg-stone-50/60 px-2 py-1 text-xs">
                  <Badge variant={ev.feasible === true ? 'default' : ev.feasible === false ? 'destructive' : 'secondary'}>
                    {ev.feasible === true ? t('feasible') : ev.feasible === false ? t('infeasible') : t('notEvaluated')}
                  </Badge>
                  <span className="font-medium">{ev.candidate_key}</span>
                  <span className="text-stone-500">{ev.pack_code}</span>
                  {ev.assignment && (
                    <span className="text-stone-600">
                      {ev.assignment.map((a) => `${a.season_label}:${a.crop_code ?? '—'}`).join(' · ')}
                    </span>
                  )}
                </div>
              ))}
              {(latest.result?.evaluations ?? []).some((ev) => (ev.explanations ?? []).length > 0) && (
                <div className="mt-2 space-y-1">
                  <h3 className="text-sm font-semibold">{t('explanations')}</h3>
                  {(latest.result?.evaluations ?? [])
                    .flatMap((ev) =>
                      (ev.explanations ?? []).map((ex) => ({
                        pack: ev.pack_code,
                        candidate: ev.candidate_key,
                        what_failed: String((ex as Record<string, unknown>).what_failed ?? ''),
                        detail: String((ex as Record<string, unknown>).detail ?? ''),
                        possible_mitigation: (ex as Record<string, unknown>).possible_mitigation as string | undefined,
                      })),
                    )
                    .slice(0, 6)
                    .map((ex, i) => (
                      <div key={i} className="rounded-md border border-stone-100 p-2 text-xs">
                        <p className="font-medium">
                          {String(ex.candidate)} / {String(ex.pack)} — {String(ex.what_failed ?? '')}
                        </p>
                        <p className="text-stone-600">{String(ex.detail ?? '')}</p>
                        {ex.possible_mitigation && (
                          <p className="mt-1 text-stone-500">
                            {t('mitigation')}: {String(ex.possible_mitigation)}
                          </p>
                        )}
                      </div>
                    ))}
                </div>
              )}
            </CardContent>
          </Card>
        </>
      )}
    </div>
  )
}
