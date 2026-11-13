'use client'

/**
 * P03 W2.1 — shared primitives for the six promoted management sub-pages.
 *
 * Everything here is moved VERBATIM from the former 1,239-line
 * `management.tsx` container (P01 audit: honesty rules — missing data is
 * shown as missing, statuses render with colour AND text, SYNTHETIC warnings
 * surface wherever evidence is synthetic). The Simple/Expert toggle moved
 * from component state into the UI store (`managementExpert`) so the shared
 * mode survives moving between the promoted sub-pages.
 */

import { useTranslations } from 'next-intl'
import { Sprout } from 'lucide-react'
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Switch } from '@/components/ui/switch'
import { describeError } from '@/lib/api'
import { useCropTwistUi } from '@/lib/store'

// ---------------------------------------------------------------- helpers

export function today(): string {
  return new Date().toISOString().slice(0, 10)
}

export function daysAgo(n: number): string {
  const d = new Date()
  d.setDate(d.getDate() - n)
  return d.toISOString().slice(0, 10)
}

export function StatusBadge({ status }: { status: string }) {
  const tone =
    status === 'eligible' || status === 'evaluated' || status === 'succeeded' || status === 'scheduled'
      ? 'border-emerald-200 bg-emerald-50 text-emerald-800'
      : status === 'conditional'
        ? 'border-amber-200 bg-amber-50 text-amber-900'
        : status === 'excluded' || status === 'failed' || status === 'over_allocated'
          ? 'border-red-200 bg-red-50 text-red-800'
          : status === 'not_evaluated' || status === 'unknown' || status === 'unscheduled'
            ? 'border-stone-300 bg-stone-100 text-stone-600'
            : 'border-stone-200 bg-stone-50 text-stone-700'
  return (
    <Badge variant="outline" className={`px-1.5 py-0 text-[10px] ${tone}`}>
      {status.replace(/_/g, ' ')}
    </Badge>
  )
}

export function SectionStatus({ status, message }: { status: string; message?: string | null }) {
  return (
    <div className="flex flex-col gap-1">
      <StatusBadge status={status} />
      {message ? <p className="text-xs text-stone-500">{message}</p> : null}
    </div>
  )
}

export function HonestEmpty({ children }: { children: React.ReactNode }) {
  return (
    <p className="rounded-md border border-dashed border-stone-300 bg-stone-50 px-3 py-2 text-sm text-stone-500">
      {children}
    </p>
  )
}

export function ErrorNote({ error }: { error: unknown }) {
  if (!error) return null
  const described = describeError(error)
  return (
    <p className="text-xs font-medium text-red-700" role="alert">
      {described.title}
      {described.description ? ` — ${described.description}` : ''}
    </p>
  )
}

export function Metric({ label, value, hint }: { label: string; value: React.ReactNode; hint?: string }) {
  return (
    <div className="rounded-lg border border-stone-200 bg-white px-3 py-2">
      <p className="text-[11px] uppercase tracking-wide text-stone-500">{label}</p>
      <p className="text-lg font-semibold text-stone-900">{value}</p>
      {hint ? <p className="text-[11px] text-stone-400">{hint}</p> : null}
    </div>
  )
}

// ------------------------------------------------------------ page shell

export interface ManagementPageContext {
  fieldId: string
  /** Farm used for farm-scoped data (operations resources): the explicit
   * selection wins, the selected field's farm is the fallback. */
  farmId: string | null
  expert: boolean
}

/**
 * Shared shell for one management sub-page: title (labelKey into the
 * `destinations.sub` namespace — rail parity), the suite description, the
 * Simple/Expert toggle (store-backed), and the no-field guidance. The view
 * itself is only mounted when a field is actually selected (render-prop, so
 * views never evaluate props without a field).
 */
export function ManagementShell({
  labelKey,
  children,
}: {
  labelKey: string
  children: (ctx: ManagementPageContext) => React.ReactNode
}) {
  const t = useTranslations('management')
  const tDest = useTranslations('destinations')
  const selectedField = useCropTwistUi((s) => s.selectedField)
  const selectedFarmId = useCropTwistUi((s) => s.selectedFarmId)
  const expert = useCropTwistUi((s) => s.managementExpert)
  const setExpert = useCropTwistUi((s) => s.setManagementExpert)

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader className="pb-3">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <CardTitle className="flex items-center gap-2 text-base">
                <Sprout className="h-4 w-4 text-emerald-700" aria-hidden />
                {tDest(`sub.${labelKey}`)}
              </CardTitle>
              <CardDescription>{t('desc')}</CardDescription>
            </div>
            <div className="flex items-center gap-2 text-xs text-stone-500">
              <span aria-hidden>{t('simple')}</span>
              <Switch checked={expert} onCheckedChange={setExpert} aria-label={t('toggleExpert')} />
              <span aria-hidden>{t('expert')}</span>
            </div>
          </div>
        </CardHeader>
        <CardContent className="space-y-3">
          {selectedField ? (
            children({
              fieldId: selectedField.id,
              farmId: selectedFarmId ?? selectedField.farmId,
              expert,
            })
          ) : (
            <HonestEmpty>{t('pickField')}</HonestEmpty>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
