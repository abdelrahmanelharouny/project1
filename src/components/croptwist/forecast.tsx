'use client'

/**
 * P2.B — Climate Forecasting tab.
 *
 * Honesty contract surfaced in the UI:
 * - Forecast values are labelled FORECAST (issue/valid time separated) and
 *   never blended with historical observations.
 * - Freshness is explicit (age vs limit).
 * - Risk screening uses documented generic thresholds (ETCCDI/WMO) with the
 *   threshold source shown per risk.
 * - The capability matrix states what each provider's product ACTUALLY
 *   supports; the CMIP6 projection adapter is declared blocked.
 */

import { useState } from 'react'
import { useTranslations } from 'next-intl'
import { toast } from 'sonner'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from '@/components/ui/accordion'
import { FieldPicker } from '@/components/croptwist/field-picker'
import {
  useClimateCapabilities,
  useForecastRisks,
  useForecastWindow,
  useIngestForecast,
} from '@/hooks/use-croptwist'
import { useCropTwistUi } from '@/lib/store'
import { describeError } from '@/lib/api'

const FORECAST_VARIABLES = [
  { code: 'air_temperature_max', label: 'T max (°C)' },
  { code: 'precipitation', label: 'Precipitation (mm)' },
] as const

export function ClimateForecast() {
  const t = useTranslations('forecast')
  const selectedField = useCropTwistUi((s) => s.selectedField)
  const setSelectedField = useCropTwistUi((s) => s.setSelectedField)
  const [variable, setVariable] = useState<string>('air_temperature_max')

  const capabilities = useClimateCapabilities()
  const window_ = useForecastWindow(selectedField?.id ?? null, variable)
  const risks = useForecastRisks(selectedField?.id ?? null)
  const ingest = useIngestForecast(selectedField?.id ?? null)

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

  const values = window_.data?.values ?? []
  const maxAbs = Math.max(1, ...values.map((v) => Math.abs(v.value ?? 0)))

  return (
    <div className="space-y-4" dir="ltr">
      <Card>
        <CardHeader>
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div>
              <CardTitle>{t('title')}</CardTitle>
              <CardDescription>{t('description')}</CardDescription>
            </div>
            <div className="flex items-center gap-2">
              <select
                aria-label={t('variables')}
                className="h-9 rounded-md border border-stone-200 bg-white px-2 text-sm"
                value={variable}
                onChange={(e) => setVariable(e.target.value)}
              >
                {FORECAST_VARIABLES.map((v) => (
                  <option key={v.code} value={v.code}>
                    {v.label}
                  </option>
                ))}
              </select>
              <FieldPicker value={selectedField.id} onValueChange={setSelectedField} />
            </div>
          </div>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex flex-wrap items-center gap-2">
            <Button
              size="sm"
              disabled={ingest.isPending}
              onClick={() =>
                ingest.mutate(
                  { forecast_days: 7 },
                  {
                    onSuccess: () => toast.success(t('ingestDone')),
                    onError: (err) => {
                      const d = describeError(err)
                      toast.error(d.title, { description: t('ingestBlocked') + (d.description ? ` — ${d.description}` : '') })
                    },
                  },
                )
              }
            >
              {ingest.isPending ? t('ingesting') : t('ingest')}
            </Button>
            {window_.data && (
              <Badge variant={window_.data.freshness.fresh ? 'default' : 'destructive'}>
                {t('freshness')}: {window_.data.freshness.fresh ? t('fresh') : t('stale')}
              </Badge>
            )}
          </div>

          {window_.isLoading && <Skeleton className="h-40 w-full" />}
          {window_.isError && <p className="text-sm text-red-700">{t('loadError')}</p>}
          {window_.data && values.length === 0 && (
            <div className="flex h-24 items-center justify-center rounded-md border border-dashed border-stone-200 bg-stone-50/60 text-sm text-stone-500">
              {t('noForecast')}
            </div>
          )}
          {window_.data && values.length > 0 && (
            <div className="space-y-1">
              <div className="flex items-center justify-between">
                <h3 className="text-sm font-semibold">{t('timeline')}</h3>
                <Badge variant="secondary">{t('basisForecast')}</Badge>
              </div>
              <div className="flex h-36 items-end gap-1 overflow-x-auto rounded-md border border-stone-100 bg-stone-50/60 p-2">
                {values.slice(0, 16).map((v) => {
                  const height = Math.round(((v.value ?? 0) / maxAbs) * 45 + 45)
                  return (
                    <div key={v.valid_time} className="flex w-8 flex-col items-center justify-end" title={`${v.valid_time.slice(0, 10)}: ${v.value ?? '—'} ${v.unit}`}>
                      <div
                        className="w-full rounded-t bg-sky-700/70"
                        style={{ height: `${height}%` }}
                        aria-hidden
                      />
                      <span className="mt-1 text-[9px] text-stone-400">{v.valid_time.slice(5, 10)}</span>
                    </div>
                  )
                })}
              </div>
              <p className="text-xs text-stone-500">
                {t('model')}: {values[0]?.model_id ?? '—'} · {t('issuedAt')}: {values[0]?.issued_at.slice(0, 16).replace('T', ' ')}
              </p>
            </div>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">{t('risks')}</CardTitle>
        </CardHeader>
        <CardContent className="space-y-2">
          {risks.isLoading && <Skeleton className="h-20 w-full" />}
          {risks.data && risks.data.risks.length === 0 && (
            <div className="flex h-16 items-center justify-center rounded-md border border-dashed border-stone-200 bg-stone-50/60 text-sm text-stone-500">
              {t('noRisks')}
            </div>
          )}
          {risks.data?.risks.map((risk) => (
            <Alert key={risk.risk_code + String(risk.window_start)}>
              <AlertTitle className="flex items-center gap-2">
                <Badge variant={risk.severity === 'recommended' ? 'destructive' : 'default'}>{risk.severity}</Badge>
                {risk.title}
              </AlertTitle>
              <AlertDescription className="text-xs">
                <p>{risk.detail}</p>
                <p className="mt-1 text-stone-500">
                  {t('threshold')}: {risk.threshold} · {t('source')}: {risk.threshold_source}
                </p>
              </AlertDescription>
            </Alert>
          ))}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">{t('capabilityMatrix')}</CardTitle>
          <CardDescription>{t('projectionsBlocked')}</CardDescription>
        </CardHeader>
        <CardContent>
          {capabilities.isLoading && <Skeleton className="h-24 w-full" />}
          {capabilities.data && (
            <Accordion type="single" collapsible>
              {capabilities.data.capability_matrix.map((p) => (
                <AccordionItem key={p.provider_code} value={p.provider_code}>
                  <AccordionTrigger className="text-sm">
                    <span className="flex items-center gap-2">
                      {p.provider_code}
                      <Badge variant={p.status === 'blocked_pending_credentials' ? 'destructive' : 'outline'}>
                        {p.forecast_class}
                      </Badge>
                    </span>
                  </AccordionTrigger>
                  <AccordionContent className="space-y-1 text-xs text-stone-600">
                    <p>
                      <span className="font-medium">{t('horizon')}: </span>
                      {p.temporal_horizon}
                    </p>
                    <p>
                      <span className="font-medium">{t('variables')}: </span>
                      {p.variables.join(', ')}
                    </p>
                    <p>{p.known_limitations}</p>
                  </AccordionContent>
                </AccordionItem>
              ))}
            </Accordion>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
