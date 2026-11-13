'use client'

/**
 * AI Insights (M8 + P1) — one tab that ties the AI layer together:
 *
 * 1. Overview card  — engine mode/model, severity counts, regenerate action.
 * 2. Recommendations — domain-grouped, evidence-linked, expandable rationale,
 *    honest confidence/evidence-quality display (A5) and the feedback
 *    lifecycle actions (A12).
 * 3. Insights strip — seasonal-aware anomaly/trend cards (A1) and the short
 *    AI field brief.
 * 4. Advisor chat   — grounded multi-turn Q&A with stable sessions (A8).
 *
 * Honesty rules carried over from the rest of the workspace: every
 * recommendation shows the evidence it is based on, confidence is stated with
 * its basis kind (never a naked percentage), and the advisor answer always
 * sits next to the disclaimer.
 */

import { useEffect, useMemo, useRef, useState } from 'react'
import { useLocale, useTranslations } from 'next-intl'
import { useQueryClient } from '@tanstack/react-query'
import {
  AlertTriangle,
  CheckCircle2,
  ChevronDown,
  ChevronUp,
  CircleSlash2,
  FileText,
  GitBranch,
  History,
  Info,
  MessageCircleQuestion,
  Minus,
  RefreshCw,
  Send,
  Sparkles,
  SquareCheck,
  ThumbsDown,
  ThumbsUp,
  TrendingDown,
  TrendingUp,
  Wrench,
  XCircle,
  type LucideIcon,
} from 'lucide-react'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { Textarea } from '@/components/ui/textarea'
import {
  useAdvisorHistory,
  useAdvisorQuery,
  useFieldInsights,
  useFieldRecommendations,
  useRecommendationFeedback,
  useRefreshRecommendations,
} from '@/hooks/use-croptwist'
import { useCropTwistUi } from '@/lib/store'
import type {
  AdvisorEvidence,
  EvidenceQuality,
  FeedbackState,
  FieldInsightItem,
  Recommendation,
  RecommendationDomain,
  RecommendationEvidence,
  RecommendationSeverity,
} from '@/lib/types'

// ---------------------------------------------------------------------------
// Display metadata (semantic stone/amber/emerald/red tokens only)
// ---------------------------------------------------------------------------

type SeverityMeta = { icon: LucideIcon; badge: string }

const SEVERITY_META: Record<RecommendationSeverity, SeverityMeta> = {
  info: {
    icon: Info,
    badge: 'border-stone-200 bg-stone-50 text-stone-600',
  },
  advisory: {
    icon: AlertTriangle,
    badge: 'border-amber-200 bg-amber-50 text-amber-900',
  },
  recommended: {
    icon: CheckCircle2,
    badge: 'border-emerald-200 bg-emerald-50 text-emerald-800',
  },
  required: {
    icon: XCircle,
    badge: 'border-red-200 bg-red-50 text-red-800',
  },
}

const SEVERITY_ORDER: RecommendationSeverity[] = ['info', 'advisory', 'recommended', 'required']

const SEVERITY_RANK: Record<string, number> = {
  required: 0,
  recommended: 1,
  advisory: 2,
  info: 3,
}

const SEVERITY_KEY: Record<RecommendationSeverity, string> = {
  info: 'severityInfo',
  advisory: 'severityAdvisory',
  recommended: 'severityRecommended',
  required: 'severityRequired',
}

const DOMAIN_KEY: Record<RecommendationDomain, string> = {
  climate: 'domainClimate',
  vegetation: 'domainVegetation', // P2 backend domain — label existed server-side, frontend mapping was missing (MISSING_MESSAGE)
  water: 'domainWater',
  soil: 'domainSoil',
  rotation: 'domainRotation',
  management: 'domainManagement',
}

/** A12: feedback lifecycle display metadata (icon + tone). */
const FEEDBACK_META: Partial<Record<FeedbackState, { icon: LucideIcon; badge: string }>> = {
  accepted: {
    icon: ThumbsUp,
    badge: 'border-emerald-200 bg-emerald-50 text-emerald-800',
  },
  implemented: {
    icon: Wrench,
    badge: 'border-emerald-200 bg-emerald-50 text-emerald-800',
  },
  dismissed: {
    icon: ThumbsDown,
    badge: 'border-stone-200 bg-stone-50 text-stone-600',
  },
  not_applicable: {
    icon: CircleSlash2,
    badge: 'border-stone-200 bg-stone-50 text-stone-600',
  },
  deferred: {
    icon: History,
    badge: 'border-amber-200 bg-amber-50 text-amber-900',
  },
}

const FEEDBACK_KEY: Partial<Record<FeedbackState, string>> = {
  accepted: 'feedbackAccepted',
  implemented: 'feedbackImplemented',
  dismissed: 'feedbackDismissed',
  not_applicable: 'feedbackNotApplicable',
  deferred: 'feedbackDeferred',
  pending: 'feedbackPending',
}

function severityMeta(severity: string): SeverityMeta {
  return SEVERITY_META[severity as RecommendationSeverity] ?? SEVERITY_META.info
}

function severityLabelKey(severity: string): string {
  return SEVERITY_KEY[severity as RecommendationSeverity] ?? 'severityInfo'
}

function domainLabelKey(domain: string): string {
  return DOMAIN_KEY[domain as RecommendationDomain] ?? domain
}

function fmtNumber(value: number | null | undefined, digits = 1): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '—'
  return value.toLocaleString(undefined, { maximumFractionDigits: digits })
}

/** Relative time for the last day, short datetime otherwise (locale-aware). */
function formatWhen(iso: string | null | undefined, locale: string): string {
  if (!iso) return '—'
  const then = Date.parse(iso)
  if (Number.isNaN(then)) return iso
  const diffMs = Date.now() - then
  if (diffMs >= 0 && diffMs < 24 * 3_600_000) {
    try {
      const rtf = new Intl.RelativeTimeFormat(locale, { numeric: 'auto' })
      const minutes = Math.round(diffMs / 60_000)
      if (minutes < 1) return rtf.format(0, 'minute')
      if (minutes < 60) return rtf.format(-minutes, 'minute')
      return rtf.format(-Math.round(minutes / 60), 'hour')
    } catch {
      // fall through to the absolute format
    }
  }
  try {
    return new Intl.DateTimeFormat(locale, { dateStyle: 'medium', timeStyle: 'short' }).format(then)
  } catch {
    return iso
  }
}

// ---------------------------------------------------------------------------
// Section shells
// ---------------------------------------------------------------------------

function Header() {
  const t = useTranslations('aiinsights')
  return (
    <div>
      <h2 className="flex items-center gap-2 text-lg font-semibold text-stone-900">
        <Sparkles className="h-5 w-5 text-emerald-700" aria-hidden />
        {t('title')}
      </h2>
      <p className="mt-1 text-sm text-stone-600">{t('subtitle')}</p>
    </div>
  )
}

export default function AiInsights() {
  const t = useTranslations('aiinsights')
  const selectedField = useCropTwistUi((s) => s.selectedField)
  const setSelectedField = useCropTwistUi((s) => s.setSelectedField)
  const fieldId = selectedField?.id ?? null

  if (!fieldId || !selectedField) {
    return (
      <div className="space-y-4">
        <Header />
        <Card>
          <CardContent className="py-10 text-center text-sm text-stone-500">
            {t('pickFieldDesc')}
          </CardContent>
        </Card>
      </div>
    )
  }

  return (
    <div className="space-y-4">
      <Header />
      <OverviewCard fieldId={fieldId} />
      <RecommendationsSection fieldId={fieldId} />
      <InsightsStrip fieldId={fieldId} />
      {/* Keyed by field: switching fields remounts the chat and resets its state. */}
      <AdvisorChat key={fieldId} fieldId={fieldId} />
    </div>
  )
}

// ---------------------------------------------------------------------------
// a) Overview card — engine, counts, regenerate
// ---------------------------------------------------------------------------

function engineModeLabel(mode: string | null | undefined, t: (key: string) => string): string {
  const m = (mode ?? '').toLowerCase()
  if (m.includes('llm')) return t('engineModeRulesLlm')
  if (m.includes('rule')) return t('engineModeRules')
  return mode ?? ''
}

function OverviewCard({ fieldId }: { fieldId: string }) {
  const t = useTranslations('aiinsights')
  const locale = useLocale()
  const recs = useFieldRecommendations(fieldId)
  const refresh = useRefreshRecommendations(fieldId)
  const [refreshError, setRefreshError] = useState<string | null>(null)

  const data = recs.data
  const bySeverity = data?.counts?.by_severity ?? {}

  const handleRefresh = () => {
    setRefreshError(null)
    refresh.mutate({}, {
      onError: () => setRefreshError(t('loadErrorTitle')),
    })
  }

  return (
    <Card>
      <CardHeader className="flex flex-col gap-3 space-y-0 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0">
          <CardTitle className="flex items-center gap-2 text-base">
            <Sparkles className="h-4 w-4 text-emerald-700" aria-hidden />
            {t('overviewTitle')}
          </CardTitle>
          <CardDescription className="mt-1">{t('overviewDesc')}</CardDescription>
        </div>
        <Button
          size="sm"
          onClick={handleRefresh}
          disabled={refresh.isPending}
          className="min-h-11 shrink-0 sm:min-h-9"
        >
          <RefreshCw
            className={`me-1 h-4 w-4${refresh.isPending ? ' animate-spin' : ''}`}
            aria-hidden
          />
          {refresh.isPending ? t('refreshing') : data ? t('refresh') : t('generate')}
        </Button>
      </CardHeader>
      <CardContent className="space-y-3">
        {recs.isLoading && (
          <div className="space-y-3">
            <Skeleton className="h-5 w-48" />
            <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
              {SEVERITY_ORDER.map((s) => (
                <Skeleton key={s} className="h-9 w-full" />
              ))}
            </div>
          </div>
        )}

        {recs.isError && (
          <Alert variant="destructive">
            <AlertTriangle className="h-4 w-4" aria-hidden />
            <AlertTitle>{t('loadErrorTitle')}</AlertTitle>
            <AlertDescription>
              {recs.error instanceof Error ? recs.error.message : undefined}
            </AlertDescription>
          </Alert>
        )}

        {refreshError && (
          <Alert variant="destructive">
            <AlertTriangle className="h-4 w-4" aria-hidden />
            <AlertTitle>{refreshError}</AlertTitle>
          </Alert>
        )}

        {data && (
          <>
            <div className="flex flex-wrap items-center gap-2">
              <Badge
                variant="outline"
                className="gap-1.5 border-stone-300 bg-white font-normal text-stone-600"
              >
                <Sparkles className="h-3 w-3 text-emerald-700" aria-hidden />
                {engineModeLabel(data.engine?.mode, t)}
                {data.engine?.model ? (
                  <span className="text-stone-400">· {data.engine.model}</span>
                ) : null}
              </Badge>
              <span className="text-xs text-stone-500">
                {t('countsSummary', { total: data.counts?.total ?? 0 })}
              </span>
            </div>

            <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
              {SEVERITY_ORDER.map((severity) => {
                const meta = severityMeta(severity)
                const Icon = meta.icon
                const count = bySeverity[severity] ?? 0
                return (
                  <div
                    key={severity}
                    className={`flex min-w-0 items-center gap-1.5 rounded-lg border px-2.5 py-1.5 text-xs ${meta.badge}`}
                  >
                    <Icon className="h-3.5 w-3.5 shrink-0" aria-hidden />
                    <span className="font-semibold">{count}</span>
                    <span className="truncate">{t(severityLabelKey(severity))}</span>
                  </div>
                )
              })}
            </div>

            <p className="text-xs text-stone-500">
              {t('generatedAt', { time: formatWhen(data.generated_at, locale) })}
            </p>
          </>
        )}
      </CardContent>
    </Card>
  )
}

// ---------------------------------------------------------------------------
// b) Recommendations list — grouped by domain
// ---------------------------------------------------------------------------

interface DomainGroup {
  domain: string
  items: Recommendation[]
}

function RecommendationsSection({ fieldId }: { fieldId: string }) {
  const t = useTranslations('aiinsights')
  const recs = useFieldRecommendations(fieldId)
  const refresh = useRefreshRecommendations(fieldId)

  const groups = useMemo<DomainGroup[]>(() => {
    const items = recs.data?.recommendations ?? []
    if (items.length === 0) return []
    const order: string[] = (recs.data?.domains ?? []).filter((domain) =>
      items.some((r) => r.domain === domain),
    )
    for (const r of items) {
      if (!order.includes(r.domain)) order.push(r.domain)
    }
    return order.map((domain) => ({
      domain,
      items: items
        .filter((r) => r.domain === domain)
        .slice()
        .sort(
          (a, b) =>
            (SEVERITY_RANK[a.severity] ?? 9) - (SEVERITY_RANK[b.severity] ?? 9),
        ),
    }))
  }, [recs.data])

  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="text-base">{t('listTitle')}</CardTitle>
        <CardDescription>{t('listDesc')}</CardDescription>
      </CardHeader>
      <CardContent>
        {recs.isLoading && (
          <div className="space-y-2">
            <Skeleton className="h-16 w-full" />
            <Skeleton className="h-16 w-full" />
            <Skeleton className="h-16 w-full" />
          </div>
        )}

        {recs.data && groups.length === 0 && (
          <div className="py-8 text-center">
            <Sparkles className="mx-auto h-6 w-6 text-emerald-700" aria-hidden />
            <p className="mt-2 text-sm font-medium text-stone-800">{t('emptyTitle')}</p>
            <p className="mx-auto mt-1 max-w-sm text-sm text-stone-500">{t('emptyDesc')}</p>
            <Button
              size="sm"
              className="mt-3 min-h-11 sm:min-h-9"
              onClick={() => refresh.mutate({})}
              disabled={refresh.isPending}
            >
              <RefreshCw
                className={`me-1 h-4 w-4${refresh.isPending ? ' animate-spin' : ''}`}
                aria-hidden
              />
              {refresh.isPending ? t('refreshing') : t('generate')}
            </Button>
          </div>
        )}

        {groups.length > 0 && (
          <div
            className="max-h-[32rem] space-y-5 overflow-y-auto pe-1 scrollbar-thin"
            aria-busy={refresh.isPending}
          >
            {groups.map((group) => (
              <section key={group.domain} aria-labelledby={`ai-domain-${group.domain}`}>
                <h3
                  id={`ai-domain-${group.domain}`}
                  className="mb-2 flex items-center gap-2 text-sm font-semibold text-stone-800"
                >
                  {t(domainLabelKey(group.domain))}
                  <span className="rounded-full bg-stone-100 px-2 py-0.5 text-[11px] font-medium text-stone-500">
                    {group.items.length}
                  </span>
                </h3>
                <div className="space-y-2">
                  {group.items.map((rec) => (
                    <RecommendationCard key={rec.id} rec={rec} />
                  ))}
                </div>
              </section>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  )
}

/** A5: evidence-quality summary line — never a naked probability. */
function EvidenceQualityLine({ quality }: { quality: EvidenceQuality }) {
  const t = useTranslations('aiinsights')
  const computable = Object.entries(quality.components ?? {}).filter(
    ([, c]) => c?.value !== null && c?.value !== undefined,
  )
  if (computable.length === 0) return null
  return (
    <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
      <span className="text-[11px] font-semibold text-stone-500">
        {t('evidenceQualityLabel')}
      </span>
      {computable.slice(0, 4).map(([name, component]) => (
        <span
          key={name}
          title={`${component.basis} (${t('evidenceQualityComponent')}: ${component.value})`}
          className="inline-flex max-w-44 items-center gap-1 rounded-full border border-stone-200 bg-stone-50 px-2 py-0.5 text-[11px] text-stone-600"
        >
          <GitBranch className="h-3 w-3 shrink-0 text-stone-400" aria-hidden />
          <span className="truncate">{t(`eqComponent_${name}`)}</span>
        </span>
      ))}
      {quality.score !== null && (
        <span className="text-[11px] text-stone-500">
          {t('evidenceQualityScore', { score: Math.round(quality.score * 100) })}
        </span>
      )}
    </div>
  )
}

/** A12: compact feedback row — accept / implement / defer / dismiss / N/A. */
function FeedbackRow({ rec }: { rec: Recommendation }) {
  const t = useTranslations('aiinsights')
  const selectedField = useCropTwistUi((s) => s.selectedField)
  const feedback = useRecommendationFeedback(selectedField?.id ?? null)
  const [reasonOpen, setReasonOpen] = useState(false)
  const [reason, setReason] = useState('')
  const [error, setError] = useState(false)

  const send = (state: FeedbackState, withReason?: string) => {
    setError(false)
    feedback.mutate(
      { recommendationId: rec.id, state, reason: withReason || undefined },
      { onError: () => setError(true) },
    )
    setReasonOpen(false)
    setReason('')
  }

  const actions: Array<{ state: FeedbackState; icon: LucideIcon; label: string }> = [
    { state: 'accepted', icon: ThumbsUp, label: t('feedbackAccept') },
    { state: 'implemented', icon: Wrench, label: t('feedbackImplement') },
    { state: 'deferred', icon: History, label: t('feedbackDefer') },
    { state: 'not_applicable', icon: CircleSlash2, label: t('feedbackNotApplicableAction') },
    { state: 'dismissed', icon: ThumbsDown, label: t('feedbackDismiss') },
  ]
  const current = rec.feedback_state
  const currentMeta = current ? FEEDBACK_META[current] : null
  const CurrentIcon = currentMeta?.icon

  return (
    <div className="mt-2 border-t border-stone-100 pt-2">
      <div className="flex flex-wrap items-center gap-1.5">
        <span className="text-[11px] font-semibold text-stone-500">
          {t('feedbackLabel')}
        </span>
        {actions.map(({ state, icon: Icon, label }) => {
          const active = current === state
          return (
            <button
              key={state}
              type="button"
              onClick={() => (state === 'dismissed' && !reasonOpen ? setReasonOpen(true) : send(state))}
              aria-pressed={active}
              aria-label={label}
              title={label}
              disabled={feedback.isPending}
              className={`inline-flex min-h-8 items-center gap-1 rounded-full border px-2 py-0.5 text-[11px] transition-colors sm:min-h-0 ${
                active
                  ? 'border-emerald-300 bg-emerald-50 text-emerald-900'
                  : 'border-stone-200 bg-white text-stone-600 hover:bg-stone-50'
              } disabled:opacity-50`}
            >
              <Icon className="h-3 w-3" aria-hidden />
              <span className="hidden sm:inline">{label}</span>
            </button>
          )
        })}
        {current && CurrentIcon && (
          <Badge variant="outline" className={`gap-1 font-normal ${currentMeta?.badge ?? ''}`}>
            <CurrentIcon className="h-3 w-3" aria-hidden />
            {t(FEEDBACK_KEY[current] ?? 'feedbackPending')}
          </Badge>
        )}
        <button
          type="button"
          onClick={() => setReasonOpen((prev) => !prev)}
          aria-expanded={reasonOpen}
          className="ms-auto inline-flex min-h-8 items-center text-[11px] font-medium text-emerald-800 hover:text-emerald-900 sm:min-h-0"
        >
          {reasonOpen ? t('feedbackReasonHide') : t('feedbackReasonAdd')}
        </button>
      </div>
      {reasonOpen && (
        <div className="mt-1.5 flex items-end gap-2">
          <Textarea
            value={reason}
            onChange={(event) => setReason(event.target.value)}
            placeholder={t('feedbackReasonPlaceholder')}
            rows={1}
            aria-label={t('feedbackReasonAdd')}
            className="min-h-9 flex-1 resize-none text-xs"
          />
          <Button
            size="sm"
            variant="outline"
            className="min-h-9"
            onClick={() => send('dismissed', reason)}
            disabled={feedback.isPending}
          >
            {t('feedbackSubmit')}
          </Button>
        </div>
      )}
      {error && (
        <p role="alert" className="mt-1 flex items-center gap-1 text-[11px] text-red-800">
          <AlertTriangle className="h-3 w-3 shrink-0" aria-hidden />
          {t('feedbackError')}
        </p>
      )}
    </div>
  )
}

function RecommendationCard({ rec }: { rec: Recommendation }) {
  const t = useTranslations('aiinsights')
  const [open, setOpen] = useState(false)
  const meta = severityMeta(rec.severity)
  const SeverityIcon = meta.icon
  const evidence: RecommendationEvidence[] = Array.isArray(rec.evidence) ? rec.evidence : []
  const actions = Array.isArray(rec.actions) ? rec.actions : []
  const isEvidenceQuality = rec.confidence_kind === 'evidence_quality'

  return (
    <article className="rounded-lg border border-stone-200 bg-white p-3">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <h4 className="min-w-0 flex-1 text-sm font-medium text-stone-800">{rec.title}</h4>
        <Badge variant="outline" className={`shrink-0 gap-1 font-normal ${meta.badge}`}>
          <SeverityIcon className="h-3 w-3" aria-hidden />
          {t(severityLabelKey(rec.severity))}
        </Badge>
      </div>

      <p className="mt-1 text-sm leading-relaxed text-stone-600">{rec.summary}</p>

      {rec.narrative && (
        <figure className="mt-2 rounded-md border-s-2 border-emerald-300 bg-emerald-50/60 p-2.5">
          <figcaption className="text-[11px] font-semibold text-emerald-900">
            {t('narrativeLabel')}
          </figcaption>
          <blockquote className="mt-0.5 text-xs leading-relaxed text-stone-700">
            {rec.narrative}
          </blockquote>
        </figure>
      )}

      {actions.length > 0 && (
        <div className="mt-2">
          <p className="text-[11px] font-semibold text-stone-500">{t('actionsLabel')}</p>
          <ul className="mt-1 list-disc space-y-0.5 ps-4 text-xs text-stone-600">
            {actions.map((action, i) => (
              <li key={i}>{action}</li>
            ))}
          </ul>
        </div>
      )}

      {rec.rationale && (
        <div className="mt-2">
          <button
            type="button"
            onClick={() => setOpen((prev) => !prev)}
            aria-expanded={open}
            className="inline-flex min-h-11 items-center gap-1 text-xs font-medium text-emerald-800 hover:text-emerald-900 sm:min-h-0"
          >
            {open ? (
              <ChevronUp className="h-3.5 w-3.5" aria-hidden />
            ) : (
              <ChevronDown className="h-3.5 w-3.5" aria-hidden />
            )}
            {open ? t('rationaleHide') : t('rationaleShow')}
          </button>
          {open && (
            <p className="mt-1.5 rounded-md bg-stone-50 p-2 text-xs leading-relaxed text-stone-600">
              {rec.rationale}
            </p>
          )}
        </div>
      )}

      {(evidence.length > 0 || rec.confidence !== null || rec.evidence_quality) && (
        <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1.5 border-t border-stone-100 pt-2">
          {evidence.length > 0 && (
            <div className="flex min-w-0 flex-wrap items-center gap-1">
              <span className="text-[11px] font-semibold text-stone-500">
                {t('evidenceLabel')}
              </span>
              {evidence.map((ev) => (
                <span
                  key={ev.id}
                  title={ev.detail ?? ev.label}
                  className="inline-flex max-w-56 items-center gap-1 rounded-full border border-stone-200 bg-stone-50 px-2 py-0.5 text-[11px] text-stone-600"
                >
                  <FileText className="h-3 w-3 shrink-0" aria-hidden />
                  <span className="truncate">{ev.label}</span>
                </span>
              ))}
            </div>
          )}
          {rec.confidence !== null && rec.confidence !== undefined && !isEvidenceQuality && (
            <span className="text-[11px] text-stone-500">
              {t('confidence')}: {Math.round(rec.confidence * 100)}%
              {rec.confidence_basis ? <span> · {rec.confidence_basis}</span> : null}
            </span>
          )}
          {rec.evidence_quality && <EvidenceQualityLine quality={rec.evidence_quality} />}
          {rec.status && rec.status !== 'active' && (
            <Badge variant="outline" className="font-normal text-stone-500">
              {rec.status}
            </Badge>
          )}
        </div>
      )}

      {/* A12: feedback lifecycle (active recs only — history stays readable). */}
      {rec.status === 'active' && <FeedbackRow rec={rec} />}
    </article>
  )
}

// ---------------------------------------------------------------------------
// c) Insights strip — anomaly/trend cards + AI brief
// ---------------------------------------------------------------------------

function directionIcon(direction: string | null | undefined): LucideIcon {
  if (direction === 'below') return TrendingDown
  if (direction === 'above') return TrendingUp
  return Minus
}

function directionLabelKey(direction: string | null | undefined): string {
  if (direction === 'below') return 'directionBelow'
  if (direction === 'above') return 'directionAbove'
  return 'directionFlat'
}

function kindLabelKey(kind: string): string {
  if (kind === 'anomaly') return 'kindAnomaly'
  if (kind === 'trend') return 'kindTrend'
  if (kind === 'seasonal_variation') return 'kindSeasonal'
  if (kind === 'insufficient_baseline') return 'kindInsufficient'
  return kind
}

function InsightsStrip({ fieldId }: { fieldId: string }) {
  const t = useTranslations('aiinsights')
  const query = useFieldInsights(fieldId)
  const data = query.data
  const insights: FieldInsightItem[] = data?.insights ?? []

  if (query.isLoading) {
    return (
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-base">{t('insightsTitle')}</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
            <Skeleton className="h-20 w-full" />
            <Skeleton className="h-20 w-full" />
            <Skeleton className="hidden h-20 w-full sm:block" />
            <Skeleton className="hidden h-20 w-full sm:block" />
          </div>
        </CardContent>
      </Card>
    )
  }

  // Nothing detected (or the endpoint is not deployed yet) — stay quiet.
  if (query.isError || !data || (insights.length === 0 && !data.summary)) return null

  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="text-base">{t('insightsTitle')}</CardTitle>
        <CardDescription>{t('insightsDesc')}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        {insights.length > 0 && (
          <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
            {insights.map((insight, index) => {
              const DirectionIcon = directionIcon(insight.direction)
              const meta = severityMeta(insight.severity)
              return (
                <div
                  key={`${insight.metric ?? insight.kind}-${index}`}
                  className="rounded-lg border border-stone-200 bg-white p-3"
                >
                  <div className="flex items-center justify-between gap-2">
                    <p className="min-w-0 truncate font-mono text-[11px] text-stone-500">
                      {insight.metric ?? t(kindLabelKey(insight.kind))}
                    </p>
                    <DirectionIcon
                      className="h-4 w-4 shrink-0 text-stone-500"
                      aria-label={t(directionLabelKey(insight.direction))}
                    />
                  </div>
                  <p className="mt-1 truncate text-sm font-semibold text-stone-900">
                    {insight.title}
                  </p>
                  <p className="mt-0.5 text-[11px] leading-relaxed text-stone-500">
                    {t('vsBaseline', {
                      baseline: fmtNumber(insight.baseline_mean),
                    })}
                    {insight.value !== null && insight.value !== undefined
                      ? ` · ${fmtNumber(insight.value)}`
                      : ''}
                    {insight.z !== null && insight.z !== undefined
                      ? ` · ${t('zLabel', { z: fmtNumber(insight.z, 2) })}`
                      : ''}
                  </p>
                  <Badge
                    variant="outline"
                    className={`mt-2 gap-1 font-normal ${meta.badge}`}
                  >
                    {t(kindLabelKey(insight.kind))}
                  </Badge>
                </div>
              )
            })}
          </div>
        )}

        {data.summary && (
          <div className="flex gap-2 rounded-lg border border-emerald-200 bg-emerald-50 p-3">
            <Sparkles className="mt-0.5 h-4 w-4 shrink-0 text-emerald-700" aria-hidden />
            <div className="min-w-0">
              <p className="text-xs font-semibold text-emerald-900">{t('briefLabel')}</p>
              <p className="mt-0.5 text-sm leading-relaxed text-stone-700">{data.summary}</p>
              {data.engine?.model && (
                <p className="mt-1 text-[11px] text-stone-500">{data.engine.model}</p>
              )}
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  )
}

// ---------------------------------------------------------------------------
// d) Advisor chat — grounded multi-turn Q&A with stable sessions (A8)
// ---------------------------------------------------------------------------

interface ChatMessage {
  role: 'user' | 'assistant'
  question: string | null
  answer: string | null
  created_at: string
  evidence?: AdvisorEvidence[]
}

function AdvisorChat({ fieldId }: { fieldId: string }) {
  const t = useTranslations('aiinsights')
  const locale = useLocale()
  const queryClient = useQueryClient()
  const [sessionId, setSessionId] = useState<string | null>(null)
  const history = useAdvisorHistory(fieldId, 20, sessionId)
  const ask = useAdvisorQuery(fieldId)
  const [draft, setDraft] = useState('')
  const [optimistic, setOptimistic] = useState<ChatMessage[]>([])
  const [error, setError] = useState(false)
  const [lastDisclaimer, setLastDisclaimer] = useState<string | null>(null)
  const scrollRef = useRef<HTMLDivElement | null>(null)

  const display = useMemo<ChatMessage[]>(() => {
    const persisted = history.data?.messages ?? []
    return [...persisted, ...optimistic]
  }, [history.data, optimistic])

  // Keep the newest message in view (history load, send, thinking state).
  useEffect(() => {
    const el = scrollRef.current
    if (el) el.scrollTop = el.scrollHeight
  }, [display.length, ask.isPending])

  const submit = () => {
    const question = draft.trim()
    if (!question || ask.isPending) return
    setDraft('')
    setError(false)
    const userMessage: ChatMessage = {
      role: 'user',
      question,
      answer: null,
      created_at: new Date().toISOString(),
    }
    setOptimistic([userMessage])
    ask.mutate(
      { question, sessionId },
      {
        onSuccess: async (response) => {
          setLastDisclaimer(response.disclaimer ?? null)
          // The server issues/reuses the stable session id (A8).
          if (response.session_id) setSessionId(response.session_id)
          setOptimistic([
            userMessage,
            {
              role: 'assistant',
              question: null,
              answer: response.answer,
              created_at: response.created_at || new Date().toISOString(),
              evidence: Array.isArray(response.evidence_used) ? response.evidence_used : [],
            },
          ])
          // The hook already invalidated the history; wait for the refetch to
          // land, then let the persisted messages replace the optimistic ones.
          try {
            await queryClient.invalidateQueries({ queryKey: ['advisor-history'] })
          } catch {
            // Refetch failed — keep the optimistic answer visible.
            return
          }
          setOptimistic([])
        },
        onError: () => {
          setOptimistic([])
          setDraft(question) // never lose the farmer's question
          setError(true)
        },
      },
    )
  }

  const startNewConversation = () => {
    setSessionId(null)
    setOptimistic([])
    setLastDisclaimer(null)
    setError(false)
    setDraft('')
  }

  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="flex items-center gap-2 text-base">
          <MessageCircleQuestion className="h-4 w-4 text-emerald-700" aria-hidden />
          {t('advisorTitle')}
        </CardTitle>
        <CardDescription>{t('advisorDesc')}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        <div
          ref={scrollRef}
          role="log"
          aria-live="polite"
          aria-label={t('history')}
          className="flex max-h-96 flex-col gap-2 overflow-y-auto pe-1 scrollbar-thin"
        >
          {history.isLoading && <Skeleton className="h-16 w-full" />}

          {!history.isLoading && display.length === 0 && (
            <p className="py-6 text-center text-sm text-stone-500">{t('noMessagesYet')}</p>
          )}

          {display.map((message, index) => (
            <ChatBubble
              key={`${message.created_at}-${index}`}
              message={message}
              locale={locale}
            />
          ))}

          {ask.isPending && (
            <div
              className="flex items-center gap-1.5 self-start rounded-2xl rounded-ss-sm border border-stone-200 bg-white px-3 py-2.5"
              role="status"
            >
              <span className="sr-only">{t('thinking')}</span>
              {[0, 150, 300].map((delay) => (
                <span
                  key={delay}
                  className="h-1.5 w-1.5 animate-bounce rounded-full bg-stone-400"
                  style={{ animationDelay: `${delay}ms` }}
                  aria-hidden
                />
              ))}
            </div>
          )}
        </div>

        {error && (
          <p role="alert" className="flex items-center gap-1.5 text-xs text-red-800">
            <AlertTriangle className="h-3.5 w-3.5 shrink-0" aria-hidden />
            {t('advisorError')}
          </p>
        )}

        <div className="flex items-end gap-2">
          <Textarea
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === 'Enter' && !event.shiftKey) {
                event.preventDefault()
                submit()
              }
            }}
            placeholder={t('questionPlaceholder')}
            aria-label={t('questionPlaceholder')}
            rows={2}
            className="min-h-11 flex-1 resize-none"
            disabled={ask.isPending}
          />
          <Button
            size="icon"
            onClick={submit}
            disabled={ask.isPending || draft.trim().length === 0}
            aria-label={t('send')}
            title={t('send')}
            className="h-11 w-11 shrink-0"
          >
            <Send className="h-4 w-4" aria-hidden />
          </Button>
        </div>

        <div className="flex items-center justify-between gap-2">
          <p className="text-[11px] leading-relaxed text-stone-500">
            {lastDisclaimer ?? t('disclaimer')}
          </p>
          {sessionId && (
            <Button
              size="sm"
              variant="ghost"
              onClick={startNewConversation}
              disabled={ask.isPending}
              className="min-h-8 shrink-0 text-[11px] text-stone-600"
            >
              <SquareCheck className="me-1 h-3 w-3" aria-hidden />
              {t('advisorNewConversation')}
            </Button>
          )}
        </div>
      </CardContent>
    </Card>
  )
}

function ChatBubble({ message, locale }: { message: ChatMessage; locale: string }) {
  const t = useTranslations('aiinsights')
  const when = formatWhen(message.created_at, locale)

  if (message.role === 'user') {
    return (
      <div
        className="max-w-[85%] self-end rounded-2xl rounded-ee-sm bg-emerald-700 px-3 py-2 text-sm leading-relaxed text-emerald-50"
        title={when}
      >
        {message.question}
      </div>
    )
  }

  const evidence = message.evidence ?? []
  return (
    <div
      className="max-w-[85%] self-start rounded-2xl rounded-ss-sm border border-stone-200 bg-white px-3 py-2 text-sm leading-relaxed text-stone-800"
      title={when}
    >
      {message.answer}
      {evidence.length > 0 && (
        <div className="mt-2 space-y-1 border-t border-stone-100 pt-2">
          <p className="text-[11px] font-semibold text-stone-500">{t('evidenceChips')}</p>
          <div className="flex flex-wrap gap-1">
            {evidence.map((ev) => (
              <span
                key={ev.id}
                title={ev.detail ?? ev.label}
                className="inline-flex max-w-56 items-center gap-1 rounded-full border border-stone-200 bg-stone-50 px-2 py-0.5 text-[11px] text-stone-600"
              >
                <FileText className="h-3 w-3 shrink-0" aria-hidden />
                <span className="truncate">{ev.label}</span>
              </span>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
