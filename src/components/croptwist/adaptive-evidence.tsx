'use client'

/**
 * P2.E — Adaptive Evidence tab: gap detection with decision-aware (never
 * monetary) VoI, the acquisition action lifecycle, downstream staleness and
 * the "apply new evidence" recalculation flow with a fingerprint-diff
 * change report.
 */

import { useState } from 'react'
import { useTranslations } from 'next-intl'
import { toast } from 'sonner'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { FieldPicker } from '@/components/croptwist/field-picker'
import {
  useApplyEvidence,
  useCreateEvidenceAction,
  useEvidenceActions,
  useEvidenceGaps,
  useStaleness,
  useTransitionEvidenceAction,
} from '@/hooks/use-croptwist'
import { useCropTwistUi } from '@/lib/store'
import { describeError } from '@/lib/api'
import type { EvidenceApplyReport } from '@/lib/types'

const NEXT_STATUS: Record<string, string[]> = {
  suggested: ['in_progress', 'submitted', 'dismissed'],
  in_progress: ['submitted', 'dismissed'],
  submitted: ['resolved', 'dismissed'],
  resolved: [],
  dismissed: ['suggested'],
}

const REF_KINDS = ['ingestion_job', 'soil_sample', 'crop_history', 'water_plan', 'field_state'] as const

function importanceVariant(importance: string): 'destructive' | 'default' | 'secondary' {
  if (importance === 'critical') return 'destructive'
  if (importance === 'high') return 'default'
  return 'secondary'
}

export function AdaptiveEvidence() {
  const t = useTranslations('adaptiveevidence')
  const selectedField = useCropTwistUi((s) => s.selectedField)
  const setSelectedField = useCropTwistUi((s) => s.setSelectedField)
  const [applyReport, setApplyReport] = useState<EvidenceApplyReport | null>(null)
  const [refKind, setRefKind] = useState<string>('ingestion_job')
  const [refId, setRefId] = useState<string>('')

  const gaps = useEvidenceGaps(selectedField?.id ?? null)
  const staleness = useStaleness(selectedField?.id ?? null)
  const actions = useEvidenceActions(selectedField?.id ?? null)
  const createAction = useCreateEvidenceAction(selectedField?.id ?? null)
  const transition = useTransitionEvidenceAction(selectedField?.id ?? null)
  const apply = useApplyEvidence(selectedField?.id ?? null)

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
        <CardContent className="space-y-4">
          {gaps.isLoading && <Skeleton className="h-40 w-full" />}
          {gaps.data && (
            <>
              <div className="flex flex-wrap gap-2 text-xs">
                <Badge variant="outline">
                  {t('domainsReady')}: {gaps.data.completeness.domains_ready.join(', ') || '—'}
                </Badge>
                <Badge variant="outline">
                  {t('domainsWithGaps')}: {gaps.data.completeness.domains_with_gaps.join(', ') || '—'}
                </Badge>
              </div>

              {gaps.data.gaps.length === 0 && (
                <div className="flex h-16 items-center justify-center rounded-md border border-dashed border-stone-200 bg-stone-50/60 text-sm text-stone-500">
                  {t('noGaps')}
                </div>
              )}

              <div className="grid gap-2 md:grid-cols-2">
                {gaps.data.gaps.map((gap) => (
                  <div key={gap.gap_code} className="rounded-md border border-stone-200 p-3 text-xs">
                    <div className="flex items-center gap-2">
                      <Badge variant={importanceVariant(gap.importance)}>{gap.importance}</Badge>
                      <span className="font-semibold">{gap.gap_code}</span>
                      {gap.urgent && <Badge variant="destructive">{gap.urgency}</Badge>}
                    </div>
                    <p className="mt-1">
                      <span className="font-medium">{t('requiredEvidence')}: </span>
                      {gap.required_evidence}
                    </p>
                    <p className="text-stone-600">{gap.current_status}</p>
                    <p className="mt-1">
                      <span className="font-medium">{t('affectedDecisions')}: </span>
                      {gap.affected_decisions.join(', ')}
                    </p>
                    <p className="mt-1 text-stone-600">{gap.potential_impact}</p>
                    <p className="mt-1">
                      <span className="font-medium">{t('howToObtain')}: </span>
                      {gap.how_to_obtain}
                    </p>
                    <p className="mt-1 text-stone-500">
                      {t('sensitivity')} [{gap.voi.decision_sensitivity.level}]: {gap.voi.decision_sensitivity.detail}
                    </p>
                    <p className="text-stone-500">
                      {t('cost')}: {gap.collection_cost.category} — {gap.collection_cost.effort}
                    </p>
                    <div className="mt-2">
                      <Button
                        size="sm"
                        variant="outline"
                        disabled={createAction.isPending}
                        onClick={() =>
                          createAction.mutate(
                            {
                              gap_code: gap.gap_code,
                              action_type: gap.gap_code.split('_')[0] === 'soil' ? 'collect_soil_sample' : 'other',
                              title: gap.how_to_obtain.split('.')[0].slice(0, 200),
                            },
                            {
                              onSuccess: () => toast.success(t('newAction')),
                              onError: (err) => {
                                const d = describeError(err)
                                toast.error(d.title, { description: d.description })
                              },
                            },
                          )
                        }
                      >
                        {t('newAction')}
                      </Button>
                    </div>
                  </div>
                ))}
              </div>
            </>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">{t('applyTitle')}</CardTitle>
          <CardDescription>{t('applyHint')}</CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="flex flex-wrap items-center gap-2 text-xs">
            <Select value={refKind} onValueChange={setRefKind}>
              <SelectTrigger className="w-44" aria-label={t('refKind')}>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {REF_KINDS.map((k) => (
                  <SelectItem key={k} value={k}>
                    {k}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <input
              className="h-9 w-72 rounded-md border border-stone-200 px-2 text-xs"
              placeholder="id (uuid)"
              value={refId}
              onChange={(e) => setRefId(e.target.value)}
              aria-label="reference id"
            />
            <Button
              size="sm"
              disabled={!refId || apply.isPending}
              onClick={() =>
                apply.mutate(
                  { ref_kind: refKind, ref_id: refId },
                  {
                    onSuccess: (data) => {
                      setApplyReport(data)
                      toast.success(t('applied'))
                    },
                    onError: (err) => {
                      const d = describeError(err)
                      toast.error(d.title, { description: d.description })
                    },
                  },
                )
              }
            >
              {t('apply')}
            </Button>
          </div>
          {applyReport && (
            <div className="rounded-md border border-emerald-200 bg-emerald-50/60 p-3 text-xs">
              <p className="font-semibold">{t('changedDecisions')}: {applyReport.changed_count}</p>
              <p className="mt-1 text-stone-600">{applyReport.note}</p>
              <ul className="mt-1 list-disc ps-4">
                {applyReport.recomputed.map((r, i) => (
                  <li key={i}>
                    {r.artifact}: {r.action}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">{t('actions')}</CardTitle>
        </CardHeader>
        <CardContent className="space-y-2">
          {actions.isLoading && <Skeleton className="h-16 w-full" />}
          {actions.data?.actions.length === 0 && (
            <div className="flex h-14 items-center justify-center rounded-md border border-dashed border-stone-200 bg-stone-50/60 text-sm text-stone-500">
              —
            </div>
          )}
          {actions.data?.actions.map((action) => (
            <div key={action.id} className="flex flex-wrap items-center gap-2 rounded-md border border-stone-100 bg-stone-50/60 px-2 py-1 text-xs">
              <Badge variant="outline">{action.status}</Badge>
              <span className="font-medium">{action.gap_code}</span>
              <span className="truncate text-stone-600">{action.title}</span>
              {NEXT_STATUS[action.status]?.map((next) => (
                <Button
                  key={next}
                  size="sm"
                  variant="ghost"
                  className="h-6 px-2 text-xs"
                  disabled={transition.isPending}
                  onClick={() =>
                    transition.mutate(
                      { actionId: action.id, toStatus: next },
                      {
                        onError: (err) => {
                          const d = describeError(err)
                          toast.error(d.title, { description: d.description })
                        },
                      },
                    )
                  }
                >
                  → {next}
                </Button>
              ))}
            </div>
          ))}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">{t('staleness')}</CardTitle>
        </CardHeader>
        <CardContent className="space-y-1">
          {staleness.isLoading && <Skeleton className="h-16 w-full" />}
          {staleness.data &&
            Object.entries(staleness.data.domains).map(([domain, info]) => (
              <div key={domain} className="flex flex-wrap items-center gap-2 text-xs">
                <span className="w-24 font-medium">{domain}</span>
                {Object.entries(info.downstream).map(([artifact, st]) => (
                  <Badge key={artifact} variant={st.stale ? 'destructive' : 'secondary'}>
                    {artifact}: {st.status === 'stale' ? t('stale') : st.status === 'current' ? t('current') : t('notBuilt')}
                  </Badge>
                ))}
              </div>
            ))}
        </CardContent>
      </Card>
    </div>
  )
}
