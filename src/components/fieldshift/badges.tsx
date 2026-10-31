'use client'

import { FlaskConical } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { cn } from '@/lib/utils'
import type { JobStatus, PassportOverallStatus } from '@/lib/types'

/** Mandatory provenance label — synthetic rows must never blend in. */
export function SyntheticBadge({ className }: { className?: string }) {
  return (
    <Badge
      variant="outline"
      className={cn(
        'gap-1 border-amber-300 bg-amber-50 px-1.5 py-0 text-[10px] font-semibold uppercase tracking-wide text-amber-900',
        className,
      )}
    >
      <FlaskConical className="h-3 w-3" aria-hidden />
      Synthetic
    </Badge>
  )
}

export function QualityBadge({ status }: { status: string }) {
  const tone =
    status === 'valid'
      ? 'border-emerald-200 bg-emerald-50 text-emerald-800'
      : status === 'suspect'
        ? 'border-amber-200 bg-amber-50 text-amber-900'
        : status === 'failed' || status === 'rejected'
          ? 'border-red-200 bg-red-50 text-red-800'
          : 'border-stone-200 bg-stone-100 text-stone-700'
  return (
    <Badge variant="outline" className={cn('px-1.5 py-0 text-[10px] capitalize', tone)}>
      {status}
    </Badge>
  )
}

export function JobStatusBadge({ status }: { status: JobStatus }) {
  const tone =
    status === 'succeeded'
      ? 'border-emerald-200 bg-emerald-50 text-emerald-800'
      : status === 'failed'
        ? 'border-red-200 bg-red-50 text-red-800'
        : 'border-amber-200 bg-amber-50 text-amber-900'
  return (
    <Badge variant="outline" className={cn('px-2 py-0.5 capitalize', tone)}>
      {status}
    </Badge>
  )
}

const PASSPORT_STATUS_COPY: Record<PassportOverallStatus, string> = {
  ready: 'Every required variable has enough valid observations — analyses below are unblocked.',
  partial: 'Some variables are missing or sparse — analyses that need them are blocked.',
  blocked: 'There is not enough data yet. Ingest variables in the Observations tab first.',
}

export function PassportStatusBadge({ status }: { status: PassportOverallStatus }) {
  const tone =
    status === 'ready'
      ? 'border-emerald-200 bg-emerald-50 text-emerald-800'
      : status === 'partial'
        ? 'border-amber-200 bg-amber-50 text-amber-900'
        : 'border-red-200 bg-red-50 text-red-800'
  return (
    <Badge variant="outline" className={cn('px-2 py-0.5 text-xs capitalize', tone)}>
      {status}
    </Badge>
  )
}

export function PassportStatusExplanation({ status }: { status: PassportOverallStatus }) {
  return <p className="text-sm text-stone-600">{PASSPORT_STATUS_COPY[status] ?? status}</p>
}
