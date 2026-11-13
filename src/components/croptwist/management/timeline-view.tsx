'use client'

/**
 * P03 W2.1 — "Soil cover" sub-page (cropintel/timeline). TimelineView moved
 * verbatim from the former management.tsx container.
 */

import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useTranslations } from 'next-intl'
import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from '@/components/ui/accordion'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Separator } from '@/components/ui/separator'
import { Skeleton } from '@/components/ui/skeleton'
import { createCoverObservation, getCoverTimeline } from '@/lib/api'
import { daysAgo, ErrorNote, ManagementShell, Metric, today } from './shared'

const CLASS_COLOR: Record<string, string> = {
  protective: 'bg-emerald-500',
  bare: 'bg-amber-600',
  unknown: 'bg-stone-300',
}

function TimelineView({ fieldId, expert }: { fieldId: string; expert: boolean }) {
  const t = useTranslations('management')
  const [start, setStart] = useState(daysAgo(180))
  const [end, setEnd] = useState(today())
  const timeline = useQuery({
    queryKey: ['cover-timeline', fieldId, start, end],
    queryFn: () => getCoverTimeline(fieldId, start, end),
    enabled: Boolean(fieldId),
  })
  const qc = useQueryClient()
  const [obsDate, setObsDate] = useState(today())
  const [obsState, setObsState] = useState('bare')
  const [error, setError] = useState<unknown>(null)

  const addObs = useMutation({
    mutationFn: () => createCoverObservation(fieldId, { observed_date: obsDate, cover_state: obsState }),
    onSuccess: () => {
      setError(null)
      qc.invalidateQueries({ queryKey: ['cover-timeline', fieldId] })
    },
    onError: setError,
  })

  const data = timeline.data
  const months = useMemo(() => {
    if (!data) return []
    // downsample timeline to per-day cells grouped by month for the strip
    return data.timeline
  }, [data])
  void months

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end gap-2">
        <div className="space-y-1">
          <Label htmlFor="tl-start" className="text-xs">{t('fromLabel')}</Label>
          <Input id="tl-start" type="date" value={start} onChange={(e) => setStart(e.target.value)} className="h-9 text-sm" />
        </div>
        <div className="space-y-1">
          <Label htmlFor="tl-end" className="text-xs">{t('toLabel')}</Label>
          <Input id="tl-end" type="date" value={end} onChange={(e) => setEnd(e.target.value)} className="h-9 text-sm" />
        </div>
      </div>

      {timeline.isLoading ? <Skeleton className="h-40 w-full" /> : null}
      <ErrorNote error={timeline.error} />

      {data ? (
        <div className="space-y-3">
          <div className="flex flex-wrap gap-3 text-[11px] text-stone-600">
            <span className="flex items-center gap-1"><span className={`inline-block h-2.5 w-2.5 rounded ${CLASS_COLOR.protective}`} aria-hidden /> {t('legendProtective')}</span>
            <span className="flex items-center gap-1"><span className={`inline-block h-2.5 w-2.5 rounded ${CLASS_COLOR.bare}`} aria-hidden /> {t('legendBare')}</span>
            <span className="flex items-center gap-1"><span className={`inline-block h-2.5 w-2.5 rounded ${CLASS_COLOR.unknown}`} aria-hidden /> {t('legendUnknown')}</span>
          </div>

          {/* timeline strip: one cell per day (wrapped, labeled by month) */}
          <div className="overflow-hidden rounded-lg border border-stone-200 p-2">
            <div className="flex flex-wrap gap-px" role="img" aria-label={t('stripAria')}>
              {data.timeline.map((d) => (
                <span
                  key={d.date}
                  title={`${d.date}: ${d.classification}${d.states.length ? ` (${d.states.join(', ')})` : ''}`}
                  className={`h-3 w-3 shrink-0 rounded-sm ${CLASS_COLOR[d.classification] ?? CLASS_COLOR.unknown}`}
                />
              ))}
            </div>
          </div>

          <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
            <Metric label={t('metricProtective')} value={`${data.metrics.days_protective_cover} d`} />
            <Metric label={t('metricBare')} value={`${data.metrics.days_known_bare} d`} />
            <Metric label={t('metricUnknown')} value={`${data.metrics.days_unknown} d`} />
            <Metric
              label={t('metricLongestBare')}
              value={data.metrics.longest_bare_interval_days ? `${data.metrics.longest_bare_interval_days} d` : '—'}
              hint={data.metrics.longest_bare_interval ? data.metrics.longest_bare_interval.join(' → ') : t('noBareEvidence')}
            />
          </div>

          <p className="text-[11px] text-stone-500">{data.thresholds.note}</p>

          <Separator />

          <div className="space-y-2">
            <p className="text-xs font-semibold text-stone-700">{t('recordObs')}</p>
            <div className="flex flex-wrap items-end gap-2">
              <div className="space-y-1">
                <Label htmlFor="obs-date" className="text-xs">{t('dateLabel')}</Label>
                <Input id="obs-date" type="date" value={obsDate} onChange={(e) => setObsDate(e.target.value)} className="h-9 text-sm" />
              </div>
              <div className="space-y-1">
                <Label htmlFor="obs-state" className="text-xs">{t('stateLabel')}</Label>
                <Select value={obsState} onValueChange={setObsState}>
                  <SelectTrigger id="obs-state" className="h-9 w-44 text-sm"><SelectValue /></SelectTrigger>
                  <SelectContent>
                    <SelectItem value="bare">{t('stateBare')}</SelectItem>
                    <SelectItem value="living_main_crop">{t('stateLivingMain')}</SelectItem>
                    <SelectItem value="living_cover_crop">{t('stateLivingCover')}</SelectItem>
                    <SelectItem value="surface_residue">{t('stateResidue')}</SelectItem>
                    <SelectItem value="mulch">{t('stateMulch')}</SelectItem>
                    <SelectItem value="unknown">{t('stateUnknown')}</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <Button size="sm" variant="outline" className="h-9" onClick={() => addObs.mutate()} disabled={addObs.isPending}>
                {addObs.isPending ? t('saving') : t('addObservation')}
              </Button>
            </div>
            <ErrorNote error={error} />
          </div>

          {expert ? (
            <Accordion type="single" collapsible>
              <AccordionItem value="method">
                <AccordionTrigger className="text-xs">{t('methodNotes')}</AccordionTrigger>
                <AccordionContent className="space-y-1 text-[11px] text-stone-600">
                  <p>{data.method.engine} · {data.method.version}</p>
                  {data.method.rules.map((r, i) => <p key={i}>· {r}</p>)}
                  {data.evidence_notes.map((n, i) => <p key={i} className="text-amber-800">· {n.detail}</p>)}
                  <p>{t('inputsLine', { inputs: Object.entries(data.inputs_summary).map(([k, v]) => `${k}=${v}`).join(' · ') })}</p>
                </AccordionContent>
              </AccordionItem>
            </Accordion>
          ) : null}
        </div>
      ) : null}
    </div>
  )
}

export function TimelinePage() {
  return (
    <ManagementShell labelKey="timeline">
      {({ fieldId, expert }) => <TimelineView fieldId={fieldId} expert={expert} />}
    </ManagementShell>
  )
}
