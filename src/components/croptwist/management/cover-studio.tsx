'use client'

/**
 * P03 W2.1 — "Cover crops" sub-page (cropintel/covers). CoverStudio view
 * moved verbatim from the former management.tsx container; the implicit
 * global `CoverPlan` is now a proper type import.
 */

import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useTranslations } from 'next-intl'
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
import { createCoverCropPlan, createCoverCropPlanItem, listCoverCropPlanItems } from '@/lib/api'
import type { CoverCandidate, CoverCropPlan } from '@/lib/types'
import { daysAgo, ErrorNote, HonestEmpty, ManagementShell, StatusBadge, today } from './shared'

type CoverPlan = CoverCropPlan

function CoverStudio({ fieldId, expert }: { fieldId: string; expert: boolean }) {
  const t = useTranslations('management')
  const qc = useQueryClient()
  const [windowStart, setWindowStart] = useState(today())
  const [windowEnd, setWindowEnd] = useState(daysAgo(-120))
  const [nextCrop, setNextCrop] = useState('')
  const [plan, setPlan] = useState<CoverPlan | null>(null)
  const [adopted, setAdopted] = useState<string | null>(null)
  const [error, setError] = useState<unknown>(null)

  const items = useQuery({
    queryKey: ['cover-items', fieldId],
    queryFn: () => listCoverCropPlanItems(fieldId),
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
        {t.rich('coverIntro', { cond: (chunks) => <span className="font-medium">{chunks}</span> })}
      </p>
      <div className="grid gap-2 sm:grid-cols-4">
        <div className="space-y-1">
          <Label htmlFor="cover-start" className="text-xs">{t('windowStart')}</Label>
          <Input id="cover-start" type="date" value={windowStart} onChange={(e) => setWindowStart(e.target.value)} className="h-9 text-sm" />
        </div>
        <div className="space-y-1">
          <Label htmlFor="cover-end" className="text-xs">{t('windowEnd')}</Label>
          <Input id="cover-end" type="date" value={windowEnd} onChange={(e) => setWindowEnd(e.target.value)} className="h-9 text-sm" />
        </div>
        <div className="space-y-1">
          <Label htmlFor="cover-next" className="text-xs">{t('nextCropLabel')}</Label>
          <Input id="cover-next" value={nextCrop} onChange={(e) => setNextCrop(e.target.value)} placeholder={t('cropPlaceholder')} className="h-9 text-sm" />
        </div>
        <div className="flex items-end">
          <Button onClick={() => run.mutate()} disabled={run.isPending} className="w-full bg-emerald-700 hover:bg-emerald-800">
            {run.isPending ? t('evaluating') : t('evaluateCandidates')}
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
              {t('noCandidates')}
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
                        <Badge variant="outline" className="border-emerald-300 bg-emerald-50 px-1.5 py-0 text-[10px] text-emerald-800">{t('inPlan')}</Badge>
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
                    <p className="text-[11px]">{t('sowingWindow', { start: c.sowing_window[0], end: c.sowing_window[1] })}</p>
                  ) : null}
                  {expert ? (
                    <Accordion type="single" collapsible className="w-full">
                      <AccordionItem value="dims">
                        <AccordionTrigger className="text-xs">{t('dimensionDetail')}</AccordionTrigger>
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
                      {t('adoptIntoPlan')}
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
          <p className="text-xs font-semibold text-stone-700">{t('adoptedDecisions')}</p>
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

export function CoversPage() {
  return (
    <ManagementShell labelKey="covers">
      {({ fieldId, expert }) => <CoverStudio fieldId={fieldId} expert={expert} />}
    </ManagementShell>
  )
}
