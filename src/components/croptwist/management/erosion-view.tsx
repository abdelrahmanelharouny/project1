'use client'

/**
 * P03 W2.1 — "Erosion" sub-page (cropintel/erosion). ErosionView moved
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
import { createErosionAssessment } from '@/lib/api'
import type { ErosionRun } from '@/lib/types'
import { daysAgo, ErrorNote, HonestEmpty, ManagementShell, today } from './shared'

function ErosionView({ fieldId, expert }: { fieldId: string; expert: boolean }) {
  const t = useTranslations('management')
  const qc = useQueryClient()
  const [slopeClass, setSlopeClass] = useState('unknown')
  const [useRusle, setUseRusle] = useState(false)
  const [factors, setFactors] = useState({ R: '100', K: '0.25', LS: '1.0', C: '0.3', P: '0.5' })
  const [factorSource, setFactorSource] = useState('')
  const [run, setRun] = useState<ErosionRun | null>(null)
  const [error, setError] = useState<unknown>(null)

  const assess = useMutation({
    mutationFn: () => {
      const input: Parameters<typeof createErosionAssessment>[1] = {
        window_start: daysAgo(365),
        window_end: today(),
        slope_evidence: slopeClass !== 'unknown' ? { slope_class: slopeClass } : undefined,
      }
      if (useRusle) {
        input.rusle_factors = Object.fromEntries(
          Object.entries(factors).map(([code, value]) => [
            code,
            {
              value: Number(value),
              source_reference: factorSource || 'unspecified local source',
              region_scope: 'farm_declared',
              unit_convention: 'metric_si',
            },
          ]),
        )
      }
      return createErosionAssessment(fieldId, input)
    },
    onSuccess: (r) => {
      setRun(r)
      setError(null)
      qc.invalidateQueries({ queryKey: ['erosion', fieldId] })
    },
    onError: setError,
  })

  return (
    <div className="space-y-4">
      <p className="text-sm text-stone-600">
        {t.rich('erosionIntro', { b: (chunks) => <span className="font-medium">{chunks}</span> })}
      </p>

      <div className="flex flex-wrap items-end gap-2">
        <div className="space-y-1">
          <Label htmlFor="slope" className="text-xs">{t('slopeLabel')}</Label>
          <Select value={slopeClass} onValueChange={setSlopeClass}>
            <SelectTrigger id="slope" className="h-9 w-40 text-sm"><SelectValue /></SelectTrigger>
            <SelectContent>
              <SelectItem value="unknown">{t('slopeUndeclared')}</SelectItem>
              <SelectItem value="flat">{t('slopeFlat')}</SelectItem>
              <SelectItem value="gentle">{t('slopeGentle')}</SelectItem>
              <SelectItem value="moderate">{t('slopeModerate')}</SelectItem>
              <SelectItem value="steep">{t('slopeSteep')}</SelectItem>
            </SelectContent>
          </Select>
        </div>
        <div className="flex items-center gap-2 pb-2 text-xs text-stone-500">
          <Switch checked={useRusle} onCheckedChange={setUseRusle} aria-label={t('rusleAria')} id="rusle-toggle" />
          <Label htmlFor="rusle-toggle" className="text-xs">{t('rusleLabel')}</Label>
        </div>
        {useRusle ? (
          <div className="space-y-1">
            <Label htmlFor="factor-src" className="text-xs">{t('factorSourceLabel')}</Label>
            <Input id="factor-src" value={factorSource} onChange={(e) => setFactorSource(e.target.value)} placeholder={t('factorSourcePlaceholder')} className="h-9 w-52 text-sm" />
          </div>
        ) : null}
        <Button onClick={() => assess.mutate()} disabled={assess.isPending} className="bg-emerald-700 hover:bg-emerald-800">
          {assess.isPending ? t('assessing') : t('runAssessment')}
        </Button>
      </div>

      {useRusle ? (
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-5">
          {(['R', 'K', 'LS', 'C', 'P'] as const).map((code) => (
            <div key={code} className="space-y-1">
              <Label htmlFor={`factor-${code}`} className="text-xs">{code}</Label>
              <Input id={`factor-${code}`} value={factors[code]} onChange={(e) => setFactors({ ...factors, [code]: e.target.value })} className="h-9 text-sm" />
            </div>
          ))}
        </div>
      ) : null}
      <ErrorNote error={error} />

      {run ? (
        <div className="space-y-3" data-testid="erosion-result">
          <Card className="border-stone-200">
            <CardHeader className="pb-2">
              <CardTitle className="flex items-center gap-2 text-sm">
                {t('screeningTitle')} <Badge variant="outline" className="px-1.5 py-0 text-[10px]">{t('screeningBadge')}</Badge>
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-2 text-xs text-stone-600">
              {run.result.screening.concerns.length === 0 ? (
                <HonestEmpty>{t('noConcerns', { count: run.result.screening.unknowns.length })}</HonestEmpty>
              ) : (
                run.result.screening.concerns.map((c, i) => (
                  <div key={i} className="flex items-start gap-2">
                    <span className="mt-1 h-1.5 w-1.5 shrink-0 rounded-full bg-amber-500" aria-hidden />
                    <span>{c.evidence} <span className="text-stone-400">({c.processes.join(', ')})</span></span>
                  </div>
                ))
              )}
              {run.result.screening.field_observed_signs.length > 0 ? (
                <div className="rounded-md border border-stone-200 bg-stone-50 p-2">
                  <p className="font-medium text-stone-700">{t('observedSigns')}</p>
                  {run.result.screening.field_observed_signs.map((s, i) => <p key={i}>{s.description}</p>)}
                </div>
              ) : null}
              {run.result.screening.unknowns.length > 0 && expert ? (
                <ul className="space-y-0.5 text-[11px] text-stone-500">
                  {run.result.screening.unknowns.map((u, i) => <li key={i}>· {u}</li>)}
                </ul>
              ) : null}
            </CardContent>
          </Card>

          {run.result.rusle.status !== 'not_evaluated' ? (
            <Card className="border-stone-200">
              <CardHeader className="pb-2">
                <CardTitle className="text-sm">{t('rusleTitle')}</CardTitle>
                <CardDescription>
                  {run.result.rusle.annual_soil_loss_a !== undefined
                    ? t('rusleEstimate', {
                        value: run.result.rusle.annual_soil_loss_a,
                        unit: run.result.rusle.unit_convention ?? '',
                      })
                    : run.result.rusle.message}
                </CardDescription>
              </CardHeader>
              {expert && run.result.rusle.scope_disclosures ? (
                <CardContent>
                  <ul className="space-y-0.5 text-[11px] text-stone-500">
                    {run.result.rusle.scope_disclosures.map((d, i) => <li key={i}>· {d}</li>)}
                  </ul>
                </CardContent>
              ) : null}
            </Card>
          ) : null}

          {run.result.alternatives.length > 0 ? (
            <Card className="border-stone-200">
              <CardHeader className="pb-2">
                <CardTitle className="text-sm">{t('alternativesTitle')}</CardTitle>
              </CardHeader>
              <CardContent>
                <Accordion type="single" collapsible className="w-full">
                  {run.result.alternatives.map((a) => (
                    <AccordionItem key={a.practice_code} value={a.practice_code}>
                      <AccordionTrigger className="text-xs">{a.name}</AccordionTrigger>
                      <AccordionContent className="space-y-1 text-[11px] text-stone-600">
                        {a.mechanisms.map((m, i) => (
                          <p key={i}>· {m.text} {m.citation ? <span className="text-stone-400">— {m.citation.citation_text}</span> : null}</p>
                        ))}
                        <p className="text-stone-400">{a.quantitative_note}</p>
                      </AccordionContent>
                    </AccordionItem>
                  ))}
                </Accordion>
              </CardContent>
            </Card>
          ) : null}
        </div>
      ) : null}
    </div>
  )
}

export function ErosionPage() {
  return (
    <ManagementShell labelKey="erosion">
      {({ fieldId, expert }) => <ErosionView fieldId={fieldId} expert={expert} />}
    </ManagementShell>
  )
}
