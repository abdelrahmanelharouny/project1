'use client'

import { useEffect, useMemo, useRef, useState } from 'react'
import { useLocale, useTranslations } from 'next-intl'
import {
  AlertCircle,
  Bot,
  Check,
  CircleHelp,
  FileText,
  LoaderCircle,
  MessageSquarePlus,
  Plus,
  RefreshCw,
  Send,
  ShieldCheck,
  Trash2,
} from 'lucide-react'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Checkbox } from '@/components/ui/checkbox'
import { Skeleton } from '@/components/ui/skeleton'
import { Textarea } from '@/components/ui/textarea'
import {
  useAiCoreConversationMessages,
  useAiCoreConversations,
  useAiCoreFeedback,
  useAiCoreProviders,
  useAiCoreRequest,
  useDeleteAiCoreConversation,
  useFarms,
} from '@/hooks/use-croptwist'
import type {
  AiCoreConversationMessage,
  AiCoreEvidenceItem,
  AiCoreFeedbackLifecycle,
  AiCoreFeedbackOutcome,
  AiCoreFeedbackRating,
  AiCoreResponseStatus,
  AiCoreResponse,
} from '@/lib/types'
import { useCropTwistUi } from '@/lib/store'

interface CopilotProps {
  fieldId: string
  fieldName: string
}

export function resolveAiCopilotConversationIds(
  conversationId: string | null,
  isNewConversation: boolean,
  conversations: Array<{ conversation_id: string }>,
): { effectiveConversationId: string | null; submissionConversationId: string | null } {
  const effectiveConversationId =
    conversationId ?? (!isNewConversation ? conversations[0]?.conversation_id ?? null : null)
  return {
    effectiveConversationId,
    submissionConversationId: isNewConversation ? null : effectiveConversationId,
  }
}

interface LocalMessage {
  id: string
  role: 'user' | 'assistant'
  text: string
  evidence?: AiCoreEvidenceItem[]
  engine?: AiCoreConversationMessage['engine']
  traceId?: string | null
  status?: AiCoreResponseStatus | null
  execution?: AiCoreResponse['execution'] | null
  limitations?: string[]
  missingInformation?: string[]
  createdAt?: string
  response?: AiCoreResponse
}

const LIFECYCLE_STATES: AiCoreFeedbackLifecycle[] = [
  'accepted',
  'rejected',
  'modified',
  'implemented',
  'outcome_reported',
]
const FEEDBACK_OUTCOMES: AiCoreFeedbackOutcome[] = ['not_observed', 'no_change', 'improved', 'worsened']

function formatTimestamp(value: string | null | undefined, locale: string): string | null {
  if (!value) return null
  const time = Date.parse(value)
  if (Number.isNaN(time)) return value
  try {
    return new Intl.DateTimeFormat(locale, { dateStyle: 'medium', timeStyle: 'short' }).format(time)
  } catch {
    return value
  }
}

function displayValue(value: unknown): string {
  if (typeof value === 'string') return value
  if (value === null || value === undefined) return ''
  if (typeof value === 'number' || typeof value === 'boolean') return String(value)
  try {
    return JSON.stringify(value)
  } catch {
    return ''
  }
}

export default function AiCopilot({ fieldId, fieldName }: CopilotProps) {
  const t = useTranslations('aiinsights')
  const locale = useLocale()
  const field = useCropTwistUi((state) => state.selectedField)
  const farmsQuery = useFarms()
  const farm = farmsQuery.data?.items.find((item) => item.id === field?.farmId)
  const conversations = useAiCoreConversations(fieldId)
  const providers = useAiCoreProviders()
  const deleteConversation = useDeleteAiCoreConversation(fieldId)
  const [conversationId, setConversationId] = useState<string | null>(null)
  const [isNewConversation, setIsNewConversation] = useState(false)
  const [deleteCandidate, setDeleteCandidate] = useState<string | null>(null)
  const [draft, setDraft] = useState('')
  const [localMessages, setLocalMessages] = useState<LocalMessage[]>([])
  const [streamingText, setStreamingText] = useState('')
  const [requestError, setRequestError] = useState(false)
  const [deleteError, setDeleteError] = useState(false)
  const pendingRef = useRef(false)
  const controllerRef = useRef<AbortController | null>(null)
  const activeRef = useRef(true)
  const ask = useAiCoreRequest(fieldId)
  const { effectiveConversationId, submissionConversationId } = resolveAiCopilotConversationIds(
    conversationId,
    isNewConversation,
    conversations.data ?? [],
  )
  const history = useAiCoreConversationMessages(effectiveConversationId)

  useEffect(() => {
    activeRef.current = true
    return () => {
      activeRef.current = false
      controllerRef.current?.abort()
    }
  }, [fieldId])

  const persistedMessages = useMemo<LocalMessage[]>(
    () => (history.data ?? []).map((message) => ({
      id: message.id,
      role: message.role,
      text: message.text,
      evidence: message.evidence,
      engine: { ...message.engine, trace_id: message.engine.trace_id ?? message.trace_id ?? undefined },
      traceId: message.trace_id,
      status: message.status ?? message.engine.status,
      execution: message.execution ?? message.engine.execution,
      limitations: message.limitations ?? message.engine.limitations,
      missingInformation: message.missing_information ?? message.engine.missing_information,
      createdAt: message.created_at,
    })),
    [history.data],
  )

  const visibleMessages = useMemo(() => {
    const localResponse = localMessages.find((message) => message.response)?.response
    const alreadyPersisted = Boolean(
      localResponse && persistedMessages.some((message) => message.engine?.trace_id === localResponse.execution.trace_id),
    )
    return alreadyPersisted ? persistedMessages : [...persistedMessages, ...localMessages]
  }, [localMessages, persistedMessages])

  const startNewConversation = () => {
    if (pendingRef.current) return
    setConversationId(null)
    setIsNewConversation(true)
    setDeleteCandidate(null)
    setLocalMessages([])
    setStreamingText('')
    setDraft('')
    setRequestError(false)
  }

  const selectConversation = (value: string) => {
    if (pendingRef.current) return
    setConversationId(value || null)
    setIsNewConversation(!value)
    setDeleteCandidate(null)
    setLocalMessages([])
    setRequestError(false)
  }

  const submit = async () => {
    const question = draft.trim()
    if (!question || pendingRef.current) return

    pendingRef.current = true
    setRequestError(false)
    setStreamingText('')
    setLocalMessages([{
      id: `pending-user-${crypto.randomUUID()}`,
      role: 'user',
      text: question,
    }])
    controllerRef.current = new AbortController()

    try {
      const response = await ask.mutateAsync({
        question,
        conversationId: submissionConversationId,
        signal: controllerRef.current.signal,
        onChunk: (chunk) => {
          if (activeRef.current) setStreamingText((current) => current + chunk)
        },
      })
      if (!activeRef.current) return
      setDraft('')
      setStreamingText('')
      setLocalMessages([
        { id: `local-user-${response.execution.trace_id}`, role: 'user', text: question },
        {
          id: `local-answer-${response.execution.trace_id}`,
          role: 'assistant',
          text: response.answer ?? '',
          evidence: response.evidence,
          engine: {
            mode: response.execution.degraded ? 'rules' : 'provider',
            provider: response.execution.provider,
            model: response.execution.model,
            trace_id: response.execution.trace_id,
          },
          response,
        },
      ])
      if (response.conversation_id) {
        setConversationId(response.conversation_id)
        setIsNewConversation(false)
      }
    } catch {
      if (!activeRef.current || controllerRef.current?.signal.aborted) return
      setLocalMessages([])
      setDraft(question)
      setRequestError(true)
      setStreamingText('')
    } finally {
      pendingRef.current = false
      controllerRef.current = null
    }
  }

  const confirmDelete = async () => {
    if (!deleteCandidate || deleteConversation.isPending) return
    setDeleteError(false)
    try {
      await deleteConversation.mutateAsync(deleteCandidate)
      if (effectiveConversationId === deleteCandidate) {
        setConversationId(null)
        setIsNewConversation(true)
        setLocalMessages([])
      }
      setDeleteCandidate(null)
    } catch {
      setDeleteError(true)
    }
  }

  const selectedConversation = conversations.data?.find((item) => item.conversation_id === effectiveConversationId)
  const selectedTitle = selectedConversation?.title?.trim() || t('conversationUntitled')

  return (
    <Card dir={locale === 'ar' ? 'rtl' : 'ltr'}>
      <CardHeader className="pb-3">
        <CardTitle className="flex items-center gap-2 text-base">
          <Bot className="h-4 w-4 text-emerald-700" aria-hidden />
          {t('copilotTitle')}
        </CardTitle>
        <CardDescription>{t('copilotDesc')}</CardDescription>
        <div className="flex flex-wrap gap-x-3 gap-y-1 pt-1 text-xs text-stone-500">
          <span><strong className="font-medium text-stone-700">{t('fieldLabel')}:</strong> {fieldName}</span>
          {farm && <span><strong className="font-medium text-stone-700">{t('organizationContextLabel')}:</strong> {farm.name} · {farm.organization_id}</span>}
          <span>{t('organizationContextNote')}</span>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        <section aria-labelledby="ai-core-provider-status" className="rounded-lg border border-stone-200 bg-stone-50/70 p-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h3 id="ai-core-provider-status" className="flex items-center gap-1.5 text-sm font-semibold text-stone-800">
              <ShieldCheck className="h-4 w-4 text-emerald-700" aria-hidden />
              {t('providerStatusTitle')}
            </h3>
            <Button size="sm" variant="ghost" className="min-h-8" onClick={() => void providers.refetch()} disabled={providers.isFetching}>
              <RefreshCw className={`me-1 h-3.5 w-3.5${providers.isFetching ? ' animate-spin' : ''}`} aria-hidden />
              {t('retry')}
            </Button>
          </div>
          {providers.isLoading && <Skeleton className="mt-2 h-8 w-full" />}
          {providers.isError && (
            <p role="alert" className="mt-2 text-xs text-red-800">{t('providerStatusError')}</p>
          )}
          {providers.data && (
            <>
              {providers.data.providers.length === 0 ? (
                <p className="mt-2 text-xs text-stone-600">{t('providerStatusEmpty')}</p>
              ) : (
                <ul className="mt-2 flex flex-wrap gap-2">
                  {providers.data.providers.map((provider) => (
                    <li key={provider.name} className="flex min-w-0 items-center gap-2 rounded-full border border-stone-200 bg-white px-2.5 py-1 text-xs">
                      <span className="font-medium text-stone-800">{provider.name}</span>
                      <code dir="ltr" className="text-[10px] text-stone-500">{provider.status}</code>
                      {provider.model && <span className="max-w-40 truncate text-stone-500">{provider.model}</span>}
                    </li>
                  ))}
                </ul>
              )}
              <p className="mt-2 text-[11px] text-stone-500">{t('providerStatusDisclosure', { verified: String(providers.data.live_connectivity_verified) })}</p>
            </>
          )}
        </section>

        <section aria-label={t('history')} className="space-y-2">
          <div className="flex flex-col gap-2 sm:flex-row">
            <label className="sr-only" htmlFor="ai-core-conversation">{t('history')}</label>
            <select
              id="ai-core-conversation"
              value={effectiveConversationId ?? ''}
              onChange={(event) => selectConversation(event.target.value)}
              disabled={ask.isPending}
              className="min-h-11 min-w-0 flex-1 rounded-md border border-stone-300 bg-white px-3 text-sm text-stone-800"
            >
              <option value="">{t('advisorNewConversation')}</option>
              {(conversations.data ?? []).map((conversation) => (
                <option key={conversation.conversation_id} value={conversation.conversation_id}>
                  {conversation.title?.trim() || `${t('conversationUntitled')} · ${formatTimestamp(conversation.updated_at, locale) ?? conversation.updated_at}`}
                </option>
              ))}
            </select>
            <Button type="button" variant="outline" className="min-h-11 shrink-0" onClick={startNewConversation} disabled={ask.isPending}>
              <Plus className="me-1 h-4 w-4" aria-hidden />{t('advisorNewConversation')}
            </Button>
            {effectiveConversationId && (
              <Button type="button" variant="ghost" className="min-h-11 shrink-0 text-red-800 hover:text-red-900" onClick={() => setDeleteCandidate(effectiveConversationId)} disabled={ask.isPending || deleteConversation.isPending}>
                <Trash2 className="me-1 h-4 w-4" aria-hidden />{t('deleteConversation')}
              </Button>
            )}
          </div>

          {conversations.isLoading && <Skeleton className="h-8 w-full" />}
          {conversations.isError && (
            <Alert variant="destructive">
              <AlertCircle className="h-4 w-4" aria-hidden />
              <AlertTitle>{t('historyErrorTitle')}</AlertTitle>
              <AlertDescription className="flex flex-wrap items-center justify-between gap-2">
                <span>{t('historyErrorDesc')}</span>
                <Button size="sm" variant="outline" onClick={() => void conversations.refetch()}>{t('retry')}</Button>
              </AlertDescription>
            </Alert>
          )}
          {!conversations.isLoading && !conversations.isError && conversations.data?.length === 0 && (
            <p className="text-xs text-stone-500">{t('historyEmpty')}</p>
          )}

          {deleteCandidate && (
            <div className="flex flex-wrap items-center gap-2 rounded-md border border-amber-200 bg-amber-50 p-2 text-xs text-amber-950">
              <span>{t('deleteConversationConfirm', { title: selectedTitle })}</span>
              <Button size="sm" variant="outline" onClick={() => void confirmDelete()} disabled={deleteConversation.isPending}>
                {deleteConversation.isPending ? <LoaderCircle className="me-1 h-3.5 w-3.5 animate-spin" aria-hidden /> : <Trash2 className="me-1 h-3.5 w-3.5" aria-hidden />}
                {t('deleteConfirm')}
              </Button>
              <Button size="sm" variant="ghost" onClick={() => setDeleteCandidate(null)} disabled={deleteConversation.isPending}>{t('cancel')}</Button>
            </div>
          )}
          {deleteError && <p role="alert" className="text-xs text-red-800">{t('deleteConversationError')}</p>}
        </section>

        <div role="log" aria-live="polite" aria-label={t('history')} className="flex max-h-[30rem] flex-col gap-3 overflow-y-auto rounded-lg border border-stone-200 bg-stone-50/50 p-3">
          {effectiveConversationId && history.isLoading && <Skeleton className="h-20 w-full" />}
          {effectiveConversationId && history.isError && (
            <Alert variant="destructive">
              <AlertCircle className="h-4 w-4" aria-hidden />
              <AlertTitle>{t('historyErrorTitle')}</AlertTitle>
              <AlertDescription className="flex items-center justify-between gap-2">
                <span>{t('historyErrorDesc')}</span>
                <Button size="sm" variant="outline" onClick={() => void history.refetch()}>{t('retry')}</Button>
              </AlertDescription>
            </Alert>
          )}
          {!history.isLoading && visibleMessages.length === 0 && (
            <div className="py-8 text-center text-sm text-stone-500">
              <MessageSquarePlus className="mx-auto h-5 w-5 text-emerald-700" aria-hidden />
              <p className="mt-2">{t('noMessagesYet')}</p>
            </div>
          )}
          {visibleMessages.map((message) => (
            <ChatMessage key={message.id} message={message} locale={locale} />
          ))}
          {ask.isPending && (
            <div className="max-w-[90%] self-start rounded-xl border border-stone-200 bg-white px-3 py-2 text-sm text-stone-500" role="status">
              {streamingText ? <p className="whitespace-pre-wrap leading-relaxed">{streamingText}</p> : <span className="inline-flex items-center gap-2"><LoaderCircle className="h-4 w-4 animate-spin" aria-hidden />{t('thinking')}</span>}
            </div>
          )}
        </div>

        {requestError && (
          <Alert variant="destructive">
            <AlertCircle className="h-4 w-4" aria-hidden />
            <AlertTitle>{t('advisorError')}</AlertTitle>
            <AlertDescription className="flex flex-wrap items-center justify-between gap-2">
              <span>{t('advisorErrorRetry')}</span>
              <Button size="sm" variant="outline" onClick={() => void submit()} disabled={ask.isPending}>{t('retry')}</Button>
            </AlertDescription>
          </Alert>
        )}

        <div className="flex items-end gap-2">
          <Textarea
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === 'Enter' && !event.shiftKey) {
                event.preventDefault()
                void submit()
              }
            }}
            placeholder={t('questionPlaceholder')}
            aria-label={t('questionPlaceholder')}
            rows={2}
            maxLength={2000}
            className="min-h-11 flex-1 resize-none"
            disabled={ask.isPending}
          />
          <Button type="button" size="icon" onClick={() => void submit()} disabled={ask.isPending || draft.trim().length === 0} aria-label={t('send')} title={t('send')} className="h-11 w-11 shrink-0">
            {ask.isPending ? <LoaderCircle className="h-4 w-4 animate-spin" aria-hidden /> : <Send className="h-4 w-4" aria-hidden />}
          </Button>
        </div>
        <p className="text-[11px] leading-relaxed text-stone-500">{t('disclaimer')}</p>
      </CardContent>
    </Card>
  )
}

function ChatMessage({ message, locale }: { message: LocalMessage; locale: string }) {
  const t = useTranslations('aiinsights')
  if (message.role === 'user') {
    return (
      <div className="max-w-[90%] self-end rounded-2xl rounded-ee-sm bg-emerald-700 px-3 py-2 text-sm leading-relaxed text-emerald-50">
        <p className="whitespace-pre-wrap">{message.text}</p>
        {message.createdAt && <time className="mt-1 block text-[10px] text-emerald-100">{formatTimestamp(message.createdAt, locale)}</time>}
      </div>
    )
  }

  const response = message.response
  const execution = response?.execution ?? message.execution
  const traceId = response?.execution.trace_id ?? message.traceId ?? execution?.trace_id ?? (typeof message.engine?.trace_id === 'string' ? message.engine.trace_id : undefined)
  const evidence = response?.evidence ?? message.evidence ?? []
  const evidenceOnlyFallback = execution?.degraded === true

  return (
    <article className="max-w-[96%] self-start rounded-2xl rounded-ss-sm border border-stone-200 bg-white px-3 py-3 text-sm leading-relaxed text-stone-800">
      {evidenceOnlyFallback ? (
        <p className="rounded-md border border-amber-200 bg-amber-50 p-2 text-xs text-amber-950"><CircleHelp className="me-1 inline h-4 w-4" aria-hidden />{t('responseEvidenceOnly')}</p>
      ) : message.text ? (
        <p className="whitespace-pre-wrap">{message.text}</p>
      ) : (
        <p className="text-stone-500"><CircleHelp className="me-1 inline h-4 w-4" aria-hidden />{t('noAnswer')}</p>
      )}
      {message.createdAt && <time className="mt-1 block text-[10px] text-stone-400">{formatTimestamp(message.createdAt, locale)}</time>}
      {(response || message.status || execution) && <ResponseMeta response={response} status={message.status} execution={execution} />}
      {evidence.length > 0 && (
        <section className="mt-3 space-y-2 border-t border-stone-100 pt-2">
          <h4 className="flex items-center gap-1.5 text-xs font-semibold text-stone-600"><FileText className="h-3.5 w-3.5" aria-hidden />{t('evidenceChips')}</h4>
          {evidence.map((item) => <EvidenceCard key={item.evidence_id} item={item} locale={locale} />)}
        </section>
      )}
      {(response || (message.limitations?.length ?? 0) > 0 || (message.missingInformation?.length ?? 0) > 0) && (
        <ResponseLimitations
          response={response}
          limitations={message.limitations}
          missingInformation={message.missingInformation}
        />
      )}
      {traceId && <FeedbackPanel traceId={traceId} />}
    </article>
  )
}

function ResponseMeta({ response, status, execution }: {
  response?: AiCoreResponse
  status?: AiCoreResponseStatus | null
  execution?: AiCoreResponse['execution'] | null
}) {
  const t = useTranslations('aiinsights')
  const resolvedStatus = response?.status ?? status
  const resolvedExecution = response?.execution ?? execution
  const statusLabels: Record<string, string> = {
    answered: t('responseStatusAnswered'),
    partial: t('responseStatusPartial'),
    clarification_required: t('responseStatusClarification'),
    unavailable: t('responseStatusUnavailable'),
    failed: t('responseStatusFailed'),
  }
  if (!resolvedStatus && !resolvedExecution) return null
  return (
    <div className="mt-2 flex flex-wrap items-center gap-1.5 text-[11px] text-stone-500">
      {resolvedStatus && <Badge variant="outline" className="font-normal">{statusLabels[resolvedStatus] ?? resolvedStatus}</Badge>}
      {resolvedExecution?.provider && <span>{resolvedExecution.provider}</span>}
      {resolvedExecution?.model && <span>· {resolvedExecution.model}</span>}
      {resolvedExecution?.degraded && <Badge variant="outline" className="font-normal text-amber-800">{t('responseEvidenceOnlyShort')}</Badge>}
      {response?.request_id && <code dir="ltr" className="max-w-48 truncate font-mono text-[10px]">{response.request_id}</code>}
    </div>
  )
}

function EvidenceCard({ item, locale }: { item: AiCoreEvidenceItem; locale: string }) {
  const t = useTranslations('aiinsights')
  const period = item.observation_period
    ? Object.entries(item.observation_period).filter(([, value]) => typeof value === 'string' && value.length > 0)
    : []
  const qualitySummary = typeof item.evidence_quality.summary === 'string' ? item.evidence_quality.summary : null
  const qualityScore = typeof item.evidence_quality.score === 'number' ? item.evidence_quality.score : null
  const values = Object.entries(item.value).slice(0, 4)

  return (
    <article className="rounded-md border border-stone-200 bg-stone-50/70 p-2.5">
      <div className="flex flex-wrap items-center gap-1.5">
        <Badge variant="outline" className="font-normal">{item.claim_class.replaceAll('_', ' ')}</Badge>
        <span className="font-medium text-stone-800">{item.result_type}</span>
        <span className="text-[10px] text-stone-500">· {item.status}</span>
        {item.unit && <span className="text-[10px] text-stone-500">· {item.unit}</span>}
      </div>
      <p dir="ltr" className="mt-1 break-all font-mono text-[10px] text-stone-400">{item.evidence_id}</p>
      {values.length > 0 && (
        <dl className="mt-1 grid gap-x-3 gap-y-0.5 text-xs sm:grid-cols-2">
          {values.map(([key, value]) => (
            <div key={key} className="flex min-w-0 gap-1">
              <dt className="shrink-0 text-stone-500">{key}:</dt><dd className="min-w-0 break-words text-stone-700">{displayValue(value)}</dd>
            </div>
          ))}
        </dl>
      )}
      {period.length > 0 && <p className="mt-1 text-[11px] text-stone-500">{t('evidencePeriod')}: {period.map(([key, value]) => `${key} ${value}`).join(' · ')}</p>}
      {item.spatial_resolution_m !== null && <p className="mt-1 text-[11px] text-stone-500">{t('evidenceSpatialResolution')}: {item.spatial_resolution_m} m</p>}
      {item.processing_version && <p className="mt-1 text-[11px] text-stone-500">{t('evidenceProcessingVersion')}: {item.processing_version}</p>}
      {qualitySummary && <p className="mt-1 text-xs text-stone-600"><strong>{t('evidenceQualityLabel')}:</strong> {qualitySummary}</p>}
      {qualityScore !== null && <p className="mt-1 text-[11px] text-stone-500">{t('evidenceQualityScore', { score: Math.round(qualityScore * 100) })}</p>}
      {item.model_confidence !== null && <p className="mt-1 text-[11px] text-stone-500">{t('evidenceModelConfidence')}: {Math.round(item.model_confidence * 100)}%</p>}
      {item.source_references.length > 0 && (
        <div className="mt-2 border-t border-stone-200 pt-1.5">
          <p className="text-[11px] font-semibold text-stone-500">{t('evidenceSources')}</p>
          <ul className="mt-1 space-y-1">
            {item.source_references.map((source, index) => (
              <li key={`${source.source_kind}-${source.source_id ?? index}`} className="text-[11px] text-stone-600">
                <span>{source.source_kind}</span>
                {source.source_id && <code dir="ltr" className="ms-1 font-mono text-[10px]">{source.source_id}</code>}
                {source.provider && <span className="ms-1">· {source.provider}</span>}
                {source.acquired_at && <time className="ms-1 text-stone-400">· {formatTimestamp(source.acquired_at, locale)}</time>}
              </li>
            ))}
          </ul>
        </div>
      )}
      {item.limitations.length > 0 && <ul className="mt-2 list-disc space-y-0.5 ps-4 text-[11px] text-amber-900">{item.limitations.map((limitation, index) => <li key={`${index}-${limitation}`}>{limitation}</li>)}</ul>}
    </article>
  )
}

function ResponseLimitations({ response, limitations, missingInformation }: {
  response?: AiCoreResponse
  limitations?: string[]
  missingInformation?: string[]
}) {
  const t = useTranslations('aiinsights')
  const rows = [
    [t('responseAssumptions'), response?.assumptions ?? []],
    [t('responseLimitations'), response?.limitations ?? limitations ?? []],
    [t('responseMissingInformation'), response?.missing_information ?? missingInformation ?? []],
    [t('responseFollowUps'), response?.follow_up_suggestions ?? []],
  ] as const
  const populated = rows.filter(([, values]) => values.length > 0)
  if (populated.length === 0) return null
  return (
    <div className="mt-2 space-y-1 border-t border-stone-100 pt-2">
      {populated.map(([label, values]) => (
        <div key={label}>
          <p className="text-[11px] font-semibold text-stone-500">{label}</p>
          <ul className="list-disc space-y-0.5 ps-4 text-xs text-stone-600">{values.map((value, index) => <li key={`${index}-${value}`}>{value}</li>)}</ul>
        </div>
      ))}
    </div>
  )
}

function FeedbackPanel({ traceId }: { traceId: string }) {
  const t = useTranslations('aiinsights')
  const feedback = useAiCoreFeedback()
  const [rating, setRating] = useState<AiCoreFeedbackRating>('helpful')
  const [lifecycle, setLifecycle] = useState<AiCoreFeedbackLifecycle>('accepted')
  const [outcome, setOutcome] = useState<AiCoreFeedbackOutcome | ''>('')
  const [correction, setCorrection] = useState('')
  const [comment, setComment] = useState('')
  const [consent, setConsent] = useState(false)
  const [saved, setSaved] = useState(false)

  const submit = async () => {
    if (!consent || feedback.isPending || (lifecycle === 'outcome_reported' && !outcome)) return
    setSaved(false)
    try {
      await feedback.mutateAsync({
        trace_id: traceId,
        rating,
        lifecycle_state: lifecycle,
        ...(correction.trim() ? { correction: correction.trim() } : {}),
        ...(comment.trim() ? { comment: comment.trim() } : {}),
        ...(outcome ? { outcome } : {}),
        quality_review_consent: true,
      })
      setSaved(true)
    } catch {
      setSaved(false)
    }
  }

  return (
    <section className="mt-3 border-t border-stone-100 pt-2">
      <p className="text-xs font-semibold text-stone-600">{t('feedbackTitle')}</p>
      <div className="mt-2 flex flex-wrap gap-1.5" role="group" aria-label={t('feedbackTitle')}>
        {(['helpful', 'needs_improvement'] as AiCoreFeedbackRating[]).map((choice) => (
          <Button key={choice} type="button" size="sm" variant={rating === choice ? 'default' : 'outline'} className="min-h-9" onClick={() => setRating(choice)}>
            {choice === 'helpful' ? t('feedbackRatingHelpful') : t('feedbackRatingNeedsImprovement')}
          </Button>
        ))}
      </div>
      <div className="mt-2 grid gap-2 sm:grid-cols-2">
        <label className="grid gap-1 text-xs text-stone-600">
          <span>{t('feedbackLifecycle')}</span>
          <select value={lifecycle} onChange={(event) => setLifecycle(event.target.value as AiCoreFeedbackLifecycle)} className="min-h-9 rounded-md border border-stone-300 bg-white px-2 text-sm">
            {LIFECYCLE_STATES.map((state) => <option key={state} value={state}>{t(`feedbackLifecycle_${state}`)}</option>)}
          </select>
        </label>
        <label className="grid gap-1 text-xs text-stone-600">
          <span>{t('feedbackOutcome')}</span>
          <select value={outcome} onChange={(event) => setOutcome(event.target.value as AiCoreFeedbackOutcome | '')} className="min-h-9 rounded-md border border-stone-300 bg-white px-2 text-sm">
            <option value="">{t('feedbackOutcomeNone')}</option>
            {FEEDBACK_OUTCOMES.map((value) => <option key={value} value={value}>{t(`feedbackOutcome_${value}`)}</option>)}
          </select>
        </label>
      </div>
      {lifecycle === 'outcome_reported' && !outcome && <p className="text-[11px] text-amber-900">{t('feedbackOutcomeRequired')}</p>}
      <label className="mt-2 grid gap-1 text-xs text-stone-600">
        <span>{t('feedbackCorrection')}</span>
        <Textarea value={correction} onChange={(event) => setCorrection(event.target.value)} maxLength={2000} rows={2} className="min-h-9 resize-y text-xs" />
      </label>
      <label className="mt-2 grid gap-1 text-xs text-stone-600">
        <span>{t('feedbackComment')}</span>
        <Textarea value={comment} onChange={(event) => setComment(event.target.value)} maxLength={1000} rows={2} className="min-h-9 resize-y text-xs" />
      </label>
      <label className="mt-2 flex items-start gap-2 rounded-md border border-stone-200 bg-stone-50 p-2 text-xs leading-relaxed text-stone-700">
        <Checkbox checked={consent} onCheckedChange={(checked) => setConsent(checked === true)} aria-label={t('feedbackConsent')} className="mt-0.5" />
        <span>{t('feedbackConsent')}</span>
      </label>
      {feedback.isError && <p role="alert" className="mt-1 text-xs text-red-800">{t('feedbackError')}</p>}
      {saved && <p role="status" className="mt-1 inline-flex items-center gap-1 text-xs text-emerald-800"><Check className="h-3.5 w-3.5" aria-hidden />{t('feedbackSuccess')}</p>}
      <div className="mt-2 flex items-center justify-between gap-2">
        <code dir="ltr" className="min-w-0 truncate font-mono text-[10px] text-stone-400">{traceId}</code>
        <Button type="button" size="sm" onClick={() => void submit()} disabled={!consent || feedback.isPending || (lifecycle === 'outcome_reported' && !outcome)}>
          {feedback.isPending && <LoaderCircle className="me-1 h-3.5 w-3.5 animate-spin" aria-hidden />}
          {t('feedbackSubmit')}
        </Button>
      </div>
    </section>
  )
}
