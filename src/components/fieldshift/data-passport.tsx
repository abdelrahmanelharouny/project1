'use client'

import { useMemo } from 'react'
import { useTranslations } from 'next-intl'
import {
  AlertTriangle,
  BadgeCheck,
  BookOpenText,
  CheckCircle2,
  ClipboardCheck,
  Info,
  Lock,
  ShieldAlert,
} from 'lucide-react'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { FieldPicker } from '@/components/fieldshift/field-picker'
import { PassportStatusBadge, PassportStatusExplanation, SyntheticBadge } from '@/components/fieldshift/badges'
import { useCatalog, useDataPassport } from '@/hooks/use-fieldshift'
import { formatDateTime, humanizeCode, pct } from '@/lib/format'
import { useFieldShiftUi } from '@/lib/store'
import type { PassportDatasetProduct, PassportWarning } from '@/lib/types'

function WarningLine({ warning }: { warning: PassportWarning }) {
  const severe = warning.severity === 'error' || warning.severity === 'high'
  return (
    <li className="flex items-start gap-2 text-xs">
      <AlertTriangle className={`mt-0.5 h-3.5 w-3.5 shrink-0 ${severe ? 'text-red-600' : 'text-amber-600'}`} aria-hidden />
      <span>
        <span className="font-medium text-stone-800">{warning.flag_code}</span>{' '}
        <span className="text-stone-600">({warning.severity})</span> — {warning.message}
      </span>
    </li>
  )
}

export function DataPassport() {
  const t = useTranslations('passport')
  const selectedField = useFieldShiftUi((s) => s.selectedField)
  const setSelectedField = useFieldShiftUi((s) => s.setSelectedField)
  const passportQuery = useDataPassport(selectedField?.id ?? null)
  const catalog = useCatalog(Boolean(selectedField))

  const variableName = (code: string) =>
    catalog.data?.variables.find((v) => v.code === code)?.name ?? humanizeCode(code)

  const products = useMemo(() => {
    if (!passportQuery.data) return []
    // Deepening F-01: identity includes the synthetic flag — a product that
    // exists in both a synthetic and a real variant gets TWO cards, never a
    // merged one, and the badge is driven by the flag instead of assumed.
    const seen = new Map<string, PassportDatasetProduct>()
    for (const variable of passportQuery.data.variables) {
      const product = variable.dataset_product
      if (!product) continue
      const key = `${product.provider_code}|${product.product_code}|${product.product_version}|${product.is_synthetic ? 'synthetic' : 'real'}`
      if (!seen.has(key)) seen.set(key, product)
    }
    return Array.from(seen.values())
  }, [passportQuery.data])

  if (!selectedField) {
    return (
      <div className="space-y-4" aria-label={t('ariaLabel')}>
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <h2 className="text-lg font-semibold text-stone-900">{t('title')}</h2>
          <FieldPicker value={null} onValueChange={setSelectedField} />
        </div>
        <Card className="border-dashed border-stone-300 bg-white">
          <CardContent className="flex flex-col items-center gap-3 p-8 text-center">
            <ClipboardCheck className="h-8 w-8 text-stone-400" aria-hidden />
            <p className="text-sm text-stone-500">
              {t('pickFieldDesc')}
            </p>
          </CardContent>
        </Card>
      </div>
    )
  }

  return (
    <div className="space-y-6" aria-label={t('ariaLabel')}>
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h2 className="text-lg font-semibold text-stone-900">{t('title')}</h2>
          <p className="text-sm text-stone-500">
            {t('honestyPrefix')}{' '}
            <strong className="font-medium text-stone-700">{selectedField.name}</strong>{' '}
            {t('honestySuffix')}
          </p>
        </div>
        <FieldPicker value={selectedField.id} onValueChange={setSelectedField} />
      </div>

      {passportQuery.isLoading ? (
        <div className="space-y-4">
          <Skeleton className="h-24 w-full rounded-lg" />
          <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
            {Array.from({ length: 3 }).map((_, index) => (
              <Skeleton key={index} className="h-48 rounded-lg" />
            ))}
          </div>
        </div>
      ) : passportQuery.isError || !passportQuery.data ? (
        <Alert variant="destructive">
          <ShieldAlert className="h-4 w-4" />
          <AlertTitle>{t('loadErrorTitle')}</AlertTitle>
          <AlertDescription>
            {passportQuery.error instanceof Error
              ? passportQuery.error.message
              : t('loadErrorDesc')}
          </AlertDescription>
        </Alert>
      ) : (
        <>
          {/* ---------- overall status ---------- */}
          <Card className="border-stone-200 bg-white shadow-sm">
            <CardHeader className="pb-2">
              <div className="flex flex-wrap items-center gap-2">
                <PassportStatusBadge status={passportQuery.data.overall_status} />
                <CardTitle className="text-base">{t('overallStatusTitle')}</CardTitle>
              </div>
              <CardDescription>{t('generatedAt', { date: formatDateTime(passportQuery.data.generated_at) })}</CardDescription>
            </CardHeader>
            <CardContent className="space-y-3">
              <PassportStatusExplanation status={passportQuery.data.overall_status} />
              {passportQuery.data.warnings.length > 0 ? (
                <ul className="space-y-1.5">
                  {passportQuery.data.warnings.map((warning, index) => (
                    <WarningLine key={index} warning={warning} />
                  ))}
                </ul>
              ) : null}
            </CardContent>
          </Card>

          {/* ---------- available variables ---------- */}
          <section aria-label={t('sourcesAria')} className="space-y-3">
            <h3 className="text-sm font-semibold uppercase tracking-wide text-stone-500">
              {t('sourcesAvailable', { count: passportQuery.data.variables.length })}
            </h3>
            <p className="text-xs text-stone-500">
              {t('sourcesNote')}
            </p>
            {passportQuery.data.variables.length === 0 ? (
              <p className="rounded-lg border border-dashed border-stone-300 bg-white p-4 text-sm text-stone-500">
                {t('noVariablesYet')}
              </p>
            ) : (
              <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
                {passportQuery.data.variables.map((variable) => (
                  <Card
                    key={`${variable.variable_code}-${variable.dataset_product?.provider_code ?? 'unknown'}-${variable.dataset_product?.product_code ?? 'unknown'}`}
                    className="border-stone-200 bg-white shadow-sm"
                  >
                    <CardHeader className="pb-2">
                      <div className="flex flex-wrap items-start justify-between gap-2">
                        <CardTitle className="text-sm font-semibold text-stone-900">
                          {variableName(variable.variable_code)}
                          <span className="mt-0.5 block text-[11px] font-normal text-stone-500">
                            {variable.variable_code} · {variable.unit}
                          </span>
                        </CardTitle>
                        {variable.is_synthetic ? <SyntheticBadge /> : null}
                      </div>
                    </CardHeader>
                    <CardContent className="space-y-2 text-xs text-stone-600">
                      <div className="flex flex-wrap gap-1.5">
                        <Badge variant="outline" className="border-emerald-200 bg-emerald-50 text-emerald-800">
                          {t('validPct', { pct: pct(variable.valid_ratio) })}
                        </Badge>
                        <Badge variant="outline" className="border-stone-300 text-stone-600">
                          {t('obsCount', { count: variable.observation_count })}
                        </Badge>
                        <Badge variant="outline" className="border-stone-300 text-stone-600">
                          {t('validMissing', { valid: variable.valid_count, missing: variable.missing_count })}
                        </Badge>
                      </div>
                      <p>
                        {t('freshness', {
                          value:
                            variable.freshness_days == null
                              ? t('freshnessUnknown')
                              : t('freshnessDays', { count: variable.freshness_days }),
                        })}
                      </p>
                      <p>
                        {t('periodLine', {
                          period: variable.period ? `${variable.period.start} → ${variable.period.end}` : '—',
                          support: variable.time_support ?? '—',
                        })}
                      </p>
                      <p>
                        {t('spatialSupport', {
                          value: variable.spatial_support
                            ? `${variable.spatial_support.type}${
                                variable.spatial_support.resolution_m ? ` @ ${variable.spatial_support.resolution_m} m` : ''
                              }`
                            : '—',
                        })}
                      </p>
                      <p className="text-stone-500">
                        {t('evidenceClass', {
                          value: `${variable.evidence_class}${
                            variable.processing_version ? ` · ${variable.processing_version}` : ''
                          }`,
                        })}
                      </p>
                      {variable.dataset_product ? (
                        <p className="text-stone-500">
                          {t('datasetLine', {
                            code: variable.dataset_product.product_code,
                            version: variable.dataset_product.product_version,
                            license: variable.dataset_product.license_name,
                          })}
                        </p>
                      ) : null}
                      {variable.warnings.length > 0 ? (
                        <ul className="space-y-1 border-t border-stone-100 pt-2">
                          {variable.warnings.map((warning, index) => (
                            <WarningLine key={index} warning={warning} />
                          ))}
                        </ul>
                      ) : null}
                    </CardContent>
                  </Card>
                ))}
              </div>
            )}
          </section>

          {/* ---------- missing variables ---------- */}
          {passportQuery.data.missing_variables.length > 0 ? (
            <section aria-label={t('missingAria')} className="space-y-3">
              <h3 className="text-sm font-semibold uppercase tracking-wide text-stone-500">
                {t('missingVariables', { count: passportQuery.data.missing_variables.length })}
              </h3>
              <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
                {passportQuery.data.missing_variables.map((missing) => (
                  <div
                    key={missing.variable_code}
                    className="rounded-lg border border-dashed border-stone-300 bg-stone-100 p-4"
                  >
                    <p className="flex items-center gap-1.5 text-sm font-medium text-stone-700">
                      <Lock className="h-3.5 w-3.5 text-stone-400" aria-hidden />
                      {variableName(missing.variable_code)}
                      <span className="text-[11px] font-normal text-stone-500">
                        {missing.variable_code} · {missing.unit}
                      </span>
                    </p>
                    <p className="mt-1 text-xs text-stone-600">{missing.reason}</p>
                  </div>
                ))}
              </div>
            </section>
          ) : null}

          {/* ---------- analyses ---------- */}
          <section aria-label={t('analysesAria')} className="space-y-3">
            <h3 className="text-sm font-semibold uppercase tracking-wide text-stone-500">
              {t('analyses', { count: passportQuery.data.analyses.length })}
            </h3>
            <div className="space-y-3">
              {passportQuery.data.analyses.map((analysis) => {
                const available = analysis.status === 'available'
                return (
                  <Card
                    key={analysis.analysis_code}
                    className={`shadow-sm ${available ? 'border-emerald-200 bg-white' : 'border-amber-200 bg-amber-50/50'}`}
                  >
                    <CardContent className="flex items-start gap-3 p-4">
                      {available ? (
                        <CheckCircle2 className="mt-0.5 h-5 w-5 shrink-0 text-emerald-600" aria-hidden />
                      ) : (
                        <AlertTriangle className="mt-0.5 h-5 w-5 shrink-0 text-amber-600" aria-hidden />
                      )}
                      <div className="min-w-0 flex-1 space-y-1.5">
                        <div className="flex flex-wrap items-center gap-2">
                          <p className="text-sm font-semibold text-stone-900">{analysis.name}</p>
                          <Badge
                            variant="outline"
                            className={`px-1.5 py-0 text-[10px] uppercase ${
                              available
                                ? 'border-emerald-200 bg-emerald-50 text-emerald-800'
                                : 'border-amber-300 bg-amber-50 text-amber-900'
                            }`}
                          >
                            {analysis.status}
                          </Badge>
                        </div>
                        <p className="text-xs text-stone-600">{analysis.description}</p>
                        <div className="flex flex-wrap items-center gap-1.5">
                          <span className="text-[11px] text-stone-500">{t('requires')}</span>
                          {analysis.required_inputs.map((input) => {
                            const isMissing = analysis.missing_inputs.includes(input)
                            return (
                              <Badge
                                key={input}
                                variant="outline"
                                className={`px-1.5 py-0 text-[10px] ${
                                  isMissing
                                    ? 'border-amber-300 bg-amber-50 text-amber-900 line-through'
                                    : 'border-stone-300 bg-white text-stone-600'
                                }`}
                              >
                                {variableName(input)}
                              </Badge>
                            )
                          })}
                        </div>
                        {analysis.reasons.length > 0 ? (
                          <ul className="list-disc space-y-0.5 pl-4 text-[11px] text-stone-500">
                            {analysis.reasons.map((reason, index) => (
                              <li key={index}>{reason}</li>
                            ))}
                          </ul>
                        ) : null}
                      </div>
                    </CardContent>
                  </Card>
                )
              })}
            </div>
          </section>

          {/* ---------- attribution ---------- */}
          {products.length > 0 ? (
            <section aria-label={t('attributionAria')} className="space-y-3">
              <h3 className="flex items-center gap-2 text-sm font-semibold uppercase tracking-wide text-stone-500">
                <BookOpenText className="h-4 w-4" aria-hidden /> {t('attributionTitle')}
              </h3>
              {products.map((product) => (
                <Card key={product.product_code} className="border-stone-200 bg-white shadow-sm">
                  <CardContent className="space-y-2 p-4 text-xs text-stone-600">
                    <p className="flex flex-wrap items-center gap-2 text-sm font-semibold text-stone-900">
                      <BadgeCheck className="h-4 w-4 text-emerald-700" aria-hidden />
                      {product.provider_name} — {product.product_code} v{product.product_version}
                      <Badge variant="outline" className="border-stone-300 text-[10px] font-normal text-stone-600">
                        {product.license_name}
                      </Badge>
                      {product.is_synthetic ? <SyntheticBadge /> : null}
                    </p>
                    <blockquote className="border-l-2 border-emerald-600 pl-3 text-stone-700" cite={product.documentation_url}>
                      {product.attribution_text}
                    </blockquote>
                    {product.documentation_url ? (
                      <p>
                        {t('documentationLabel')}{' '}
                        <a
                          href={product.documentation_url}
                          className="text-emerald-700 underline underline-offset-2"
                          target="_blank"
                          rel="noreferrer"
                        >
                          {product.documentation_url}
                        </a>
                      </p>
                    ) : null}
                  </CardContent>
                </Card>
              ))}
            </section>
          ) : null}

          {/* ---------- notes ---------- */}
          {passportQuery.data.notes.length > 0 ? (
            <div className="rounded-lg border border-stone-200 bg-stone-50 p-4">
              <p className="mb-2 flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-stone-500">
                <Info className="h-3.5 w-3.5" aria-hidden /> {t('notesTitle')}
              </p>
              <ul className="list-disc space-y-1 pl-4 text-xs text-stone-600">
                {passportQuery.data.notes.map((note, index) => (
                  <li key={index}>{note}</li>
                ))}
              </ul>
            </div>
          ) : null}
        </>
      )}
    </div>
  )
}

export default DataPassport
