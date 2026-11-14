/// <reference types="bun-types" />
import { afterEach, describe, expect, test } from 'bun:test'
import {
  deleteAiCoreConversation,
  getAiCoreConversationMessages,
  getAiCoreProviders,
  isAiCoreResponse,
  listAiCoreConversations,
  streamAiCoreRequest,
  submitAiCoreFeedback,
} from '@/lib/api'
import type { AiCoreResponse } from '@/lib/types'

const originalFetch = globalThis.fetch

afterEach(() => {
  globalThis.fetch = originalFetch
})

function validResponse(): AiCoreResponse {
  return {
    request_id: 'req-1',
    conversation_id: 'conversation-1',
    intent: 'field_question',
    status: 'answered',
    answer: 'The field evidence is available.',
    verified_facts: [],
    derived_results: [],
    predictions: [],
    recommendations: [],
    general_knowledge: [],
    assumptions: [],
    evidence: [],
    limitations: [],
    missing_information: [],
    follow_up_suggestions: [],
    plan: {
      intent: 'field_question',
      required_entities: [],
      required_context: [],
      required_tools: [],
      tool_calls: [],
      missing_information: [],
      permission_scope: [],
      clarification_needed: false,
      availability: 'available',
      expected_output: 'grounded_explanation',
      limitations: [],
    },
    execution: {
      trace_id: 'trace-1',
      request_id: 'req-1',
      status: 'answered',
      provider: null,
      model: null,
      token_usage: { input_tokens: null, output_tokens: null, total_tokens: null },
      provider_attempts: [],
      latency_ms: 1,
      planned_steps: 0,
      tools: [],
      degraded: false,
      error_category: null,
    },
  }
}

function sseResponse(response: AiCoreResponse, split = false): Response {
  const encoder = new TextEncoder()
  const content = [
    'event: meta\ndata: {"request_id":"req-1"}\n\n',
    'event: chunk\ndata: {"text":"The field "}\n\n',
    'event: chunk\ndata: {"text":"evidence is available."}\n\n',
    `event: done\ndata: ${JSON.stringify(response)}\n\n`,
  ].join('')
  if (!split) return new Response(content, { headers: { 'Content-Type': 'text/event-stream' } })
  const pieces = [content.slice(0, 19), content.slice(19, 73), content.slice(73, 151), content.slice(151)]
  const body = new ReadableStream<Uint8Array>({
    start(controller) {
      for (const piece of pieces) controller.enqueue(encoder.encode(piece))
      controller.close()
    },
  })
  return new Response(body, { headers: { 'Content-Type': 'text/event-stream; charset=utf-8' } })
}

describe('AI Core API contract', () => {
  test('streams chunks but returns the complete structurally validated done response', async () => {
    const fullResponse = validResponse()
    const chunks: string[] = []
    let requestUrl = ''
    const requestBodies: Record<string, unknown>[] = []
    globalThis.fetch = (async (input, init) => {
      requestUrl = String(input)
      requestBodies.push(JSON.parse(String(init?.body)) as Record<string, unknown>)
      return sseResponse(fullResponse, true)
    }) as unknown as typeof fetch

    const result = await streamAiCoreRequest({
      question: 'How should I assess this field?',
      field_id: 'field-1',
      conversation_id: null,
      locale: 'en',
      context_domains: ['field'],
    }, { onChunk: (text) => chunks.push(text) })

    expect(requestUrl).toBe('/api/v1/ai/requests/stream')
    expect(requestUrl).not.toContain('XTransformPort')
    expect(requestBodies[0]).toEqual({
      question: 'How should I assess this field?',
      field_id: 'field-1',
      conversation_id: null,
      locale: 'en',
      context_domains: ['field'],
    })
    expect(requestBodies[0]).not.toHaveProperty('organization_id')
    expect(chunks.join('')).toBe('The field evidence is available.')
    expect(result).toEqual(fullResponse)
  })

  test('rejects a malformed terminal event instead of exposing it as a response', async () => {
    globalThis.fetch = (async () => new Response(
      'event: done\ndata: {"answer":"unvalidated"}\n\n',
      { headers: { 'Content-Type': 'text/event-stream' } },
    )) as unknown as typeof fetch

    await expect(streamAiCoreRequest({
      question: 'What is known?',
      field_id: 'field-1',
      conversation_id: null,
      locale: 'ar',
      context_domains: ['field'],
    })).rejects.toMatchObject({ code: 'AI_STREAM_INVALID_RESPONSE' })
  })

  test('exposes structural response guard for full AI Core envelopes', () => {
    const response = validResponse()
    expect(isAiCoreResponse(response)).toBe(true)
    expect(isAiCoreResponse({ ...response, execution: { ...response.execution, trace_id: undefined } })).toBe(false)
    expect(isAiCoreResponse({ ...response, evidence: null })).toBe(false)
  })

  test('conversation list/history/delete and provider status use the owner-scoped API routes', async () => {
    const urls: string[] = []
    globalThis.fetch = (async (input) => {
      urls.push(String(input))
      if (String(input).includes('/providers')) {
        return new Response(JSON.stringify({ providers: [], field_data_policy_enabled: false, openrouter_field_data_policy_enabled: false, live_connectivity_verified: false }), { headers: { 'Content-Type': 'application/json' } })
      }
      return new Response('[]', { headers: { 'Content-Type': 'application/json' } })
    }) as unknown as typeof fetch

    await getAiCoreProviders()
    await listAiCoreConversations('field 1')
    await getAiCoreConversationMessages('conversation-1')
    await deleteAiCoreConversation('conversation-1')

    expect(urls).toEqual([
      '/api/v1/ai/providers',
      '/api/v1/ai/conversations?field_id=field+1',
      '/api/v1/ai/conversations/conversation-1/messages',
      '/api/v1/ai/conversations/conversation-1',
    ])
  })

  test('feedback sends trace, rating, lifecycle, optional fields and explicit consent in one request', async () => {
    const requestBodies: Record<string, unknown>[] = []
    const requestUrls: string[] = []
    globalThis.fetch = (async (input, init) => {
      requestUrls.push(String(input))
      requestBodies.push(JSON.parse(String(init?.body)) as Record<string, unknown>)
      return new Response(JSON.stringify({ feedback_id: 'feedback-1', status: 'recorded' }), { headers: { 'Content-Type': 'application/json' } })
    }) as unknown as typeof fetch

    await submitAiCoreFeedback({
      trace_id: 'trace-1',
      rating: 'needs_improvement',
      lifecycle_state: 'modified',
      correction: 'Clarify the evidence period.',
      comment: 'Please explain the limitation.',
      outcome: 'no_change',
      quality_review_consent: true,
    })

    expect(requestUrls).toEqual(['/api/v1/ai/feedback'])
    expect(requestBodies[0]).toEqual({
      trace_id: 'trace-1',
      rating: 'needs_improvement',
      lifecycle_state: 'modified',
      correction: 'Clarify the evidence period.',
      comment: 'Please explain the limitation.',
      outcome: 'no_change',
      quality_review_consent: true,
    })
  })
})
