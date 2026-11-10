'use client'

/**
 * Scenario Comparison & Decision Intelligence (M7.6).
 *
 * One traceable decision document per field, assembled from stored M7.3/M7.4/
 * M7.5 artifacts. Honesty rules rendered here:
 * - No composite scores, no probabilities, no yield predictions, no universal
 *   recommendations — findings are evidence-linked statements.
 * - Objective units, directions, missing values and applicability states stay
 *   visible; different units are never ranked against each other.
 * - Unavailable sections are shown with the API's reason — never hidden.
 */

import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useTranslations } from 'next-intl'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Skeleton } from '@/components/ui/skeleton'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { FieldPicker } from '@/components/croptwist/field-picker'
import {
  ApiError,
  createDecisionComparison,
  getDecisionComparison,
  listDecisionComparisons,
  verifyDecisionComparison,
} from '@/lib/api'
import type { DecisionComparisonSummary, DecisionDocument } from '@/lib/types'
import { useCropTwistUi } from '@/lib/store'
import { AlertTriangle, FileSearch, Loader2, Scale, GitCompareArrows } from 'lucide-react'

export default function Decisions() {
  const t = useTranslations('decisions')
  const selectedField = useCropTwistUi((s) => s.selectedField)
  const fieldId = selectedField?.id ?? null
  const queryClient = useQueryClient()
  const [title, setTitle] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [openId, setOpenId] = useState<string | null>(null)

  const comparisons = useQuery({
    queryKey: ['decision-comparisons', fieldId],
    queryFn: () => listDecisionComparisons(fieldId as string),
    enabled: !!fieldId,
  })

  const generate = useMutation({
    mutationFn: () => createDecisionComparison(fieldId as string, title ? { title } : {}),
    onSuccess: (doc) => {
      setError(null)
      setOpenId(doc.id)
      queryClient.invalidateQueries({ queryKey: ['decision-comparisons'] })
    },
    onError: (e) => setError(e instanceof ApiError ? e.message : t('generateFailed')),
  })

  if (!fieldId) {
    return (
      <div className="space-y-4">
        <Header />
        <Card>
          <CardContent className="py-10 text-center text-sm text-stone-500">
            {t('pickFieldDesc')}
          </CardContent>
        </Card>
      </div>
    )
  }

  return (
    <div className="space-y-4">
      <Header />

      {error && (
        <Alert variant="destructive">
          <AlertTriangle className="h-4 w-4" aria-hidden />
          <AlertTitle>{t('requestFailed')}</AlertTitle>
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}

      <Card>
        <CardHeader className="flex flex-row items-start justify-between space-y-0">
          <div className="min-w-0">
            <CardTitle className="text-base">{t('listTitle')}</CardTitle>
            <CardDescription className="mt-1">{t('listDesc')}</CardDescription>
          </div>
          <div className="flex shrink-0 items-end gap-2">
            <div className="space-y-1">
              <Label htmlFor="cmp-title" className="sr-only">
                {t('titleLabel')}
              </Label>
              <Input
                id="cmp-title"
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                placeholder={t('titlePlaceholder')}
                className="h-9 w-40"
              />
            </div>
            <Button size="sm" onClick={() => generate.mutate()} disabled={generate.isPending}>
              {generate.isPending ? (
                <Loader2 className="mr-1 h-4 w-4 animate-spin" aria-hidden />
              ) : (
                <GitCompareArrows className="mr-1 h-4 w-4" aria-hidden />
              )}
              {t('generate')}
            </Button>
          </div>
        </CardHeader>
        <CardContent>
          {comparisons.isLoading && <Skeleton className="h-16 w-full" />}
          {comparisons.data && comparisons.data.items.length === 0 && (
            <p className="text-xs text-stone-500">{t('noDocsYet')}</p>
          )}
          <div className="grid gap-2">
            {(comparisons.data?.items ?? []).map((d) => (
              <button
                key={d.id}
                type="button"
                onClick={() => setOpenId(openId === d.id ? null : d.id)}
                className={`rounded-lg border p-3 text-left transition ${
                  openId === d.id ? 'border-emerald-300 bg-emerald-50/50' : 'border-stone-200 bg-white hover:border-stone-300'
                }`}
              >
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <span className="font-medium text-stone-800">{d.title}</span>
                  <Badge variant="outline" className="font-normal">
                    {d.doc_status}
                  </Badge>
                </div>
                <p className="mt-1 truncate text-xs text-stone-500">
                  {t('docSummary', {
                    executions: (d.scope?.executions ?? []).length,
                    robust: (d.scope?.robust_runs ?? []).length,
                    checksum: d.document_checksum.slice(0, 10),
                  })}
                </p>
              </button>
            ))}
          </div>
        </CardContent>
      </Card>

      {openId && <DocumentDetail id={openId} />}
    </div>
  )
}

function Header() {
  const t = useTranslations('decisions')
  return (
    <div>
      <h2 className="flex items-center gap-2 text-lg font-semibold text-stone-900">
        <Scale className="h-5 w-5 text-emerald-700" aria-hidden />
        {t('title')}
      </h2>
      <p className="mt-1 text-sm text-stone-600">{t('desc')}</p>
    </div>
  )
}

function DocumentDetail({ id }: { id: string }) {
  const t = useTranslations('decisions')
  const doc = useQuery({
    queryKey: ['decision-comparison', id],
    queryFn: () => getDecisionComparison(id),
  })
  const verify = useMutation({ mutationFn: () => verifyDecisionComparison(id) })

  if (doc.isLoading) return <Skeleton className="h-40 w-full" />
  if (doc.isError || !doc.data) {
    return (
      <Alert variant="destructive">
        <AlertTriangle className="h-4 w-4" aria-hidden />
        <AlertTitle>{t('loadErrorTitle')}</AlertTitle>
      </Alert>
    )
  }
  const d = doc.data.document as DecisionDocument | undefined
  if (!d) return null

  return (
    <div className="space-y-4">
      {doc.data.not_available && Object.keys(doc.data.not_available).length > 0 && (
        <Alert>
          <AlertTriangle className="h-4 w-4" aria-hidden />
          <AlertTitle>{t('notAvailableTitle')}</AlertTitle>
          <AlertDescription>
            <ul className="list-disc space-y-1 pl-4">
              {Object.entries(doc.data.not_available).map(([k, v]) => (
                <li key={k}>
                  <span className="font-mono">{k}</span>: {v}
                </li>
              ))}
            </ul>
          </AlertDescription>
        </Alert>
      )}

      <Card>
        <CardHeader>
          <CardTitle className="text-base">{t('findingsTitle')}</CardTitle>
          <CardDescription>{d.honesty_note}</CardDescription>
        </CardHeader>
        <CardContent>
          <ul className="space-y-2">
            {d.findings.map((f, i) => (
              <li key={i} className="rounded-md border border-stone-200 bg-white p-2 text-sm">
                <Badge variant="outline" className="mr-2 font-normal">
                  {f.kind}
                </Badge>
                {f.text}
              </li>
            ))}
            {d.findings.length === 0 && (
              <li className="text-xs text-stone-500">{t('noFindings')}</li>
            )}
          </ul>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">{t('changesTitle')}</CardTitle>
          <CardDescription>{d.baseline_vs_scenario.ranking_note}</CardDescription>
        </CardHeader>
        <CardContent>
          <div className="overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>{t('colScenario')}</TableHead>
                  <TableHead>{t('colFeature')}</TableHead>
                  <TableHead>{t('colPeriod')}</TableHead>
                  <TableHead>{t('colBaseline')}</TableHead>
                  <TableHead>{t('colScenario')}</TableHead>
                  <TableHead>{t('colChange')}</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {d.baseline_vs_scenario.largest_changes.slice(0, 10).map((c, i) => (
                  <TableRow key={i}>
                    <TableCell className="text-xs">{c.scenario}</TableCell>
                    <TableCell className="font-mono text-xs">{c.feature_code}</TableCell>
                    <TableCell className="text-xs">{c.period_label}</TableCell>
                    <TableCell className="text-xs">
                      {c.baseline_value ?? '—'} {c.unit}
                    </TableCell>
                    <TableCell className="text-xs">
                      {c.scenario_value ?? '—'} {c.unit}
                    </TableCell>
                    <TableCell className="text-xs font-medium">
                      {c.difference_percent ?? '—'}%
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        </CardContent>
      </Card>

      {d.rotation_decisions.runs.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">{t('rotationTitle')}</CardTitle>
            <CardDescription>{t('rotationDesc')}</CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            {d.rotation_decisions.runs.map((r) => (
              <div key={r.robust_run_id} className="rounded-lg border border-stone-200 p-3">
                <p className="text-xs text-stone-500">
                  {t('robustRunLine', {
                    id: r.robust_run_id.slice(0, 8),
                    count: r.member_count,
                    seasons: r.seasons.map((s) => s.label).join(', '),
                  })}
                </p>
                <div className="mt-2 overflow-x-auto">
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>{t('colPlan')}</TableHead>
                        <TableHead>{t('colAssignment')}</TableHead>
                        <TableHead>{t('colWorstCase')}</TableHead>
                        <TableHead>{t('colFeasibility')}</TableHead>
                        <TableHead>{t('colSolver')}</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {r.plans.map((p) => (
                        <TableRow key={p.strategy_key}>
                          <TableCell className="text-xs font-medium">
                            {p.strategy_key}
                            {p.is_baseline && ` ${t('currentSuffix')}`}
                          </TableCell>
                          <TableCell className="text-xs">
                            {p.assignment
                              .map((a) => `${a.season_label}: ${a.crop_code ?? '—'}`)
                              .join(' · ')}
                          </TableCell>
                          <TableCell className="text-xs">{p.worst_case_objective ?? '—'}</TableCell>
                          <TableCell className="text-xs">{p.robust_feasibility}</TableCell>
                          <TableCell className="text-xs">{p.solver_status ?? '—'}</TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </div>
              </div>
            ))}
          </CardContent>
        </Card>
      )}

      {d.tradeoffs.matrix.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">{t('tradeoffsTitle')}</CardTitle>
            <CardDescription>{d.tradeoffs.note}</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="max-h-96 overflow-y-auto rounded-lg border border-stone-200">
              <Table>
                <TableHeader className="sticky top-0 bg-white">
                  <TableRow>
                    <TableHead>{t('colPlan')}</TableHead>
                    <TableHead>{t('colScenario')}</TableHead>
                    <TableHead>{t('colCriterion')}</TableHead>
                    <TableHead>{t('colValue')}</TableHead>
                    <TableHead>{t('colUnit')}</TableHead>
                    <TableHead>{t('colDirection')}</TableHead>
                    <TableHead>{t('colState')}</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {d.tradeoffs.matrix
                    .filter((m) => m.evaluable)
                    .slice(0, 120)
                    .map((m, i) => (
                      <TableRow key={i}>
                        <TableCell className="text-xs">{m.plan}</TableCell>
                        <TableCell className="font-mono text-xs">{m.scenario_id.slice(0, 8)}</TableCell>
                        <TableCell className="font-mono text-xs">{m.criterion_code}</TableCell>
                        <TableCell className="text-xs">{m.raw_value ?? '—'}</TableCell>
                        <TableCell className="text-xs">{m.unit ?? '—'}</TableCell>
                        <TableCell className="text-xs">{m.direction ?? '—'}</TableCell>
                        <TableCell className="text-xs">{m.evaluable ? t('evaluable') : t('missing')}</TableCell>
                      </TableRow>
                    ))}
                </TableBody>
              </Table>
            </div>
          </CardContent>
        </Card>
      )}

      <Card>
        <CardHeader>
          <CardTitle className="text-base">{t('missingEvidenceTitle')}</CardTitle>
          <CardDescription>{t('itemsCount', { count: d.missing_evidence.count })}</CardDescription>
        </CardHeader>
        <CardContent>
          <ul className="max-h-64 list-disc space-y-1 overflow-y-auto pl-4 text-xs text-stone-600">
            {d.missing_evidence.items.map((it, i) => (
              <li key={i}>
                <span className="font-mono">{it.code}</span> ({it.source}): {it.detail}
              </li>
            ))}
          </ul>
        </CardContent>
      </Card>

      <div className="flex items-center gap-2">
        <Button size="sm" variant="outline" onClick={() => verify.mutate()} disabled={verify.isPending}>
          {verify.isPending ? (
            <Loader2 className="mr-1 h-4 w-4 animate-spin" aria-hidden />
          ) : (
            <FileSearch className="mr-1 h-4 w-4" aria-hidden />
          )}
          {t('verifyButton')}
        </Button>
        {verify.data && (
          <Badge
            variant="outline"
            className={
              verify.data.verified
                ? 'border-emerald-200 bg-emerald-50 text-emerald-800'
                : 'border-red-200 bg-red-50 text-red-800'
            }
          >
            {verify.data.verified ? t('verified') : t('findingsCount', { count: verify.data.findings.length })}
          </Badge>
        )}
      </div>
    </div>
  )
}
