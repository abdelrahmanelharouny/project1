'use client'

/**
 * P2.C — Soil Memory tab: longitudinal timeline, checksummed snapshots,
 * conservative change estimates (always labelled ESTIMATE) and evidence-
 * based screening alerts.
 */

import { useState } from 'react'
import { useTranslations } from 'next-intl'
import { toast } from 'sonner'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { FieldContextGate } from '@/components/croptwist/field-context'
import { ErrorState, SectionSkeleton } from '@/components/croptwist/state-views'
import {
  useCreateSoilChangeEstimate,
  useCreateSoilSnapshot,
  useSoilAlerts,
  useSoilTimeline,
} from '@/hooks/use-croptwist'
import { useCropTwistUi } from '@/lib/store'
import { describeError } from '@/lib/api'

function kindBadge(kind: string, t: ReturnType<typeof useTranslations<'soilmemory'>>) {
  if (kind === 'measurement') return <Badge variant="outline">{t('measurement')}</Badge>
  if (kind === 'management') return <Badge variant="secondary">{t('management')}</Badge>
  return <Badge>{t('snapshot')}</Badge>
}

export function SoilMemory() {
  const t = useTranslations('soilmemory')
  const selectedField = useCropTwistUi((s) => s.selectedField)
  const [asOf, setAsOf] = useState<string>(new Date().toISOString().slice(0, 10))
  const [startId, setStartId] = useState<string | null>(null)
  const [endId, setEndId] = useState<string | null>(null)
  const [estimate, setEstimate] = useState<{ value: number | null; unit?: string; note?: string } | null>(null)

  const timeline = useSoilTimeline(selectedField?.id ?? null)
  const alerts = useSoilAlerts(selectedField?.id ?? null)
  const createSnapshot = useCreateSoilSnapshot(selectedField?.id ?? null)
  const createEstimate = useCreateSoilChangeEstimate(selectedField?.id ?? null)

  if (!selectedField) return <FieldContextGate hint={t('pickFieldHint')} />

  const snapshots = timeline.data?.snapshots ?? []

  return (
    <div className="space-y-4" dir="ltr">
      <Card>
        <CardHeader>
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div>
              <CardTitle>{t('title')}</CardTitle>
              <CardDescription>{t('description')}</CardDescription>
            </div>
          </div>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex flex-wrap items-center gap-2">
            <Input
              type="date"
              className="w-40"
              value={asOf}
              max={new Date().toISOString().slice(0, 10)}
              onChange={(e) => setAsOf(e.target.value)}
              aria-label={t('asOf')}
            />
            <Button
              size="sm"
              disabled={createSnapshot.isPending}
              onClick={() =>
                createSnapshot.mutate(asOf, {
                  onSuccess: () => toast.success(t('snapshotCreated')),
                  onError: (err) => {
                    const d = describeError(err)
                    toast.error(d.title, { description: d.description })
                  },
                })
              }
            >
              {t('createSnapshot')}
            </Button>
          </div>

          {timeline.isLoading && <SectionSkeleton lines={4} />}
          {timeline.isError && <ErrorState message={t('loadError')} onRetry={() => timeline.refetch()} />}
          {timeline.data && (
            <>
              <div>
                <h3 className="mb-1 text-sm font-semibold">{t('timeline')}</h3>
                <div className="max-h-64 space-y-1 overflow-y-auto scrollbar-thin">
                  {timeline.data.events
                    .slice()
                    .reverse()
                    .slice(0, 60)
                    .map((event, i) => (
                      <div key={i} className="flex items-center gap-2 rounded border border-stone-100 bg-stone-50/60 px-2 py-1 text-xs">
                        <span className="w-24 shrink-0 text-stone-500">{String(event.date).slice(0, 10)}</span>
                        {kindBadge(event.kind, t)}
                        <span className="truncate">
                          {event.kind === 'measurement'
                            ? `${String(event.variable_code)}: ${event.value ?? '—'} ${String(event.unit ?? '')} ${Array.isArray(event.depth) && event.depth[0] != null ? `@${event.depth[0]}-${event.depth[1]}cm` : ''} · ${String(event.evidence_class)}`
                            : event.kind === 'management'
                              ? String(event.event_type ?? '')
                              : `#${String(event.checksum ?? '').slice(0, 8)}`}
                        </span>
                      </div>
                    ))}
                </div>
              </div>

              {snapshots.length >= 2 && (
                <div className="space-y-2 rounded-md border border-stone-200 p-3">
                  <h3 className="text-sm font-semibold">{t('changeEstimates')}</h3>
                  <div className="flex flex-wrap items-center gap-2 text-xs">
                    <select aria-label="start" className="h-8 rounded border border-stone-200 px-1" value={startId ?? ''} onChange={(e) => setStartId(e.target.value || null)}>
                      <option value="">—</option>
                      {snapshots.map((s) => (
                        <option key={s.id} value={s.id}>
                          {s.as_of}
                        </option>
                      ))}
                    </select>
                    <span>→</span>
                    <select aria-label="end" className="h-8 rounded border border-stone-200 px-1" value={endId ?? ''} onChange={(e) => setEndId(e.target.value || null)}>
                      <option value="">—</option>
                      {snapshots.map((s) => (
                        <option key={s.id} value={s.id}>
                          {s.as_of}
                        </option>
                      ))}
                    </select>
                    <Button
                      size="sm"
                      variant="outline"
                      disabled={!startId || !endId || createEstimate.isPending}
                      onClick={() =>
                        createEstimate.mutate(
                          { start: startId!, end: endId! },
                          {
                            onSuccess: (data) =>
                              setEstimate({
                                value: data.result.soc_trajectory.value,
                                unit: data.result.soc_trajectory.unit,
                                note: data.result.soc_trajectory.not_evaluated,
                              }),
                            onError: (err) => {
                              const d = describeError(err)
                              toast.error(d.title, { description: d.description })
                            },
                          },
                        )
                      }
                    >
                      {t('createEstimate')}
                    </Button>
                    {estimate && (
                      <span className="flex items-center gap-1">
                        <Badge variant="secondary">{t('estimated')}</Badge>
                        <span className="font-medium">
                          {estimate.value != null ? `${estimate.value} ${estimate.unit ?? t('perYear')}` : estimate.note}
                        </span>
                      </span>
                    )}
                  </div>
                </div>
              )}
            </>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">{t('alerts')}</CardTitle>
        </CardHeader>
        <CardContent className="space-y-2">
          {alerts.isLoading && <SectionSkeleton lines={2} />}
          {alerts.data && alerts.data.alerts.length === 0 && (
            <div className="flex h-14 items-center justify-center rounded-md border border-dashed border-stone-200 bg-stone-50/60 text-sm text-stone-500">
              {t('noAlerts')}
            </div>
          )}
          {alerts.data?.alerts.map((alert) => (
            <div key={alert.code} className="rounded-md border border-stone-100 bg-stone-50/60 p-2 text-xs">
              <div className="flex items-center gap-2">
                <Badge variant={alert.severity === 'recommended' ? 'destructive' : 'secondary'}>{alert.severity}</Badge>
                <span className="font-medium">{alert.title}</span>
              </div>
              <p className="mt-1 text-stone-600">{alert.detail}</p>
            </div>
          ))}
        </CardContent>
      </Card>
    </div>
  )
}
