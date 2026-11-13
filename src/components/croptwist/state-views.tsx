'use client'

/**
 * P02 W0.7 — shared section-state primitives (audit P13: three different
 * loading styles, no shared loader primitive; per-tab error handling varies).
 *
 * House pattern:
 *   - `SectionLoader`    — inline spinner + label for a section boundary
 *   - `SectionSkeleton`  — shape-preserving skeleton block
 *   - `ErrorState`       — accessible error card (role="alert") with retry
 *
 * W0 migrates the audited silent-failure surface (water plan) and the
 * Overview error card. Propagating these to every tab is tracked for W2+
 * (P01 plan item 0.7 "applied to 5 worst tabs" — remaining tabs keep their
 * existing, working states until then).
 */

import { RefreshCw } from 'lucide-react'
import { useTranslations } from 'next-intl'

import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { cn } from '@/lib/utils'

export function SectionLoader({ label, className }: { label: string; className?: string }) {
  return (
    <div
      className={cn('flex items-center justify-center gap-2 py-10 text-sm text-stone-500', className)}
      role="status"
      aria-live="polite"
    >
      <span
        className="h-4 w-4 animate-spin rounded-full border-2 border-stone-300 border-t-emerald-700"
        aria-hidden
      />
      <span>{label}</span>
    </div>
  )
}

export function SectionSkeleton({ className, lines = 3 }: { className?: string; lines?: number }) {
  return (
    <div className={cn('space-y-2', className)} aria-hidden>
      {Array.from({ length: lines }).map((_, i) => (
        <Skeleton key={i} className="h-4 w-full" style={{ width: `${100 - i * 12}%` }} />
      ))}
    </div>
  )
}

export function ErrorState({
  message,
  onRetry,
  className,
}: {
  message: string
  /** Optional — when omitted the card renders without a retry control. */
  onRetry?: () => void
  className?: string
}) {
  const tCommon = useTranslations('common')
  return (
    <Card className={cn('border-red-200 bg-red-50', className)} role="alert">
      <CardContent className="flex flex-col items-start gap-3 p-4 sm:flex-row sm:items-center sm:justify-between">
        <p className="text-sm text-red-900">{message}</p>
        {onRetry ? (
          <Button variant="outline" size="sm" onClick={onRetry}>
            <RefreshCw className="h-4 w-4" aria-hidden /> {tCommon('retry')}
          </Button>
        ) : null}
      </CardContent>
    </Card>
  )
}
