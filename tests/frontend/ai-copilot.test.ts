/// <reference types="bun-types" />
import { describe, expect, test } from 'bun:test'
import { resolveAiCopilotConversationIds } from '@/components/croptwist/ai-copilot'
import { buildAiCoreRequestPayload } from '@/hooks/use-croptwist'

describe('AI Copilot request context selection', () => {
  test('sends an empty context domain list so the planner selects relevant evidence', () => {
    expect(buildAiCoreRequestPayload('Assess this field', 'field-1', null, 'ar')).toEqual({
      question: 'Assess this field',
      field_id: 'field-1',
      conversation_id: null,
      locale: 'ar',
      context_domains: [],
    })
  })
})

describe('AI Copilot conversation routing', () => {
  const threads = [
    { conversation_id: 'latest-thread' },
    { conversation_id: 'older-thread' },
  ]

  test('first submission continues the latest thread already displayed by default', () => {
    expect(resolveAiCopilotConversationIds(null, false, threads)).toEqual({
      effectiveConversationId: 'latest-thread',
      submissionConversationId: 'latest-thread',
    })
  })

  test('an explicitly selected thread is both displayed and continued', () => {
    expect(resolveAiCopilotConversationIds('older-thread', false, threads)).toEqual({
      effectiveConversationId: 'older-thread',
      submissionConversationId: 'older-thread',
    })
  })

  test('explicit new-conversation mode does not inherit the displayed latest thread', () => {
    expect(resolveAiCopilotConversationIds(null, true, threads)).toEqual({
      effectiveConversationId: null,
      submissionConversationId: null,
    })
  })
})
