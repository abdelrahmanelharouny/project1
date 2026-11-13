'use client'

/**
 * P03 W2.1 — "Management plan" sub-page (cropintel/plan). View moved
 * verbatim from the former management.tsx container.
 */

import { useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useTranslations } from 'next-intl'
import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from '@/components/ui/accordion'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { createManagementPlan } from '@/lib/api'
import type { ManagementPlan } from '@/lib/types'
import { daysAgo, ErrorNote, HonestEmpty, ManagementShell, Metric, SectionStatus, StatusBadge, today } from './shared'

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

export function PlanPage() {
  return (
    <ManagementShell labelKey="plan">
      {({ fieldId, expert }) => <PlanView fieldId={fieldId} expert={expert} />}
    </ManagementShell>
  )
}
