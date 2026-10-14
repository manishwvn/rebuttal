import { expect, test } from '@playwright/test'
import type { AgAiEvent, AgAiInputMessage, AgLlmRequest } from 'ag-studio'
import { createProxyAdapter, toStudioAiRequest, type StudioAiReply } from '../src/components/analytics/studioAiAdapter.ts'

// Pure adapter tests: no page and no browser. Real turns always carry a responseFormat, so the fixture defaults to text.
function turn(fields: Partial<AgLlmRequest>): AgLlmRequest {
  return { input: [], responseFormat: { type: 'text' }, ...fields } as AgLlmRequest
}

function userText(text: string): AgAiInputMessage {
  return { id: 'u1', kind: 'input', type: 'message', role: 'user', status: 'completed', content: [{ type: 'text', text }] }
}

function reply(overrides: Partial<StudioAiReply>): StudioAiReply {
  return { message: { content: null, tool_calls: [] }, finish_reason: 'stop', usage: null, model: 'test-model', ...overrides }
}

async function collect(stream: AsyncIterable<AgAiEvent>): Promise<AgAiEvent[]> {
  const events: AgAiEvent[] = []
  for await (const event of stream) events.push(event)
  return events
}

test('instructions become the first system message', () => {
  const body = toStudioAiRequest(turn({ instructions: 'Answer in one line.', input: [userText('Hi')] }))
  expect(body.messages).toEqual([
    { role: 'system', content: 'Answer in one line.' },
    { role: 'user', content: 'Hi' },
  ])
  expect(body).not.toHaveProperty('tools')
  expect(body).not.toHaveProperty('response_format')
})

test('history maps to messages: tool calls merge into one assistant message and results become tool messages', () => {
  const body = toStudioAiRequest(
    turn({
      input: [
        { id: 'u1', kind: 'input', type: 'message', role: 'user', status: 'completed', content: [{ type: 'text', text: 'Where is my order?' }] },
        { id: 'r1', kind: 'output', type: 'reasoning', summary: [] },
        { id: 'a1', kind: 'output', type: 'message', role: 'assistant', status: 'completed', content: [{ type: 'text', text: 'Let me check.', annotations: [] }] },
        { id: 'fc1', kind: 'output', type: 'function_call', callId: 'call_1', name: 'get_order', arguments: '{"id":"o1"}' },
        { id: 'fc2', kind: 'output', type: 'function_call', callId: 'call_2', name: 'get_tracking', arguments: '{}' },
        { type: 'function_call_output', callId: 'call_1', output: '{"status":"shipped"}', status: 'completed' },
        { type: 'function_call_output', callId: 'call_2', output: '{}', status: 'completed' },
      ],
    }),
  )
  expect(body.messages).toEqual([
    { role: 'user', content: 'Where is my order?' },
    {
      role: 'assistant',
      content: 'Let me check.',
      tool_calls: [
        { id: 'call_1', type: 'function', function: { name: 'get_order', arguments: '{"id":"o1"}' } },
        { id: 'call_2', type: 'function', function: { name: 'get_tracking', arguments: '{}' } },
      ],
    },
    { role: 'tool', tool_call_id: 'call_1', content: '{"status":"shipped"}' },
    { role: 'tool', tool_call_id: 'call_2', content: '{}' },
  ])
})

test('tool calls with no assistant text get null content', () => {
  const body = toStudioAiRequest(
    turn({ input: [{ id: 'fc1', kind: 'output', type: 'function_call', callId: 'call_1', name: 'get_order', arguments: '{}' }] }),
  )
  expect(body.messages).toEqual([
    { role: 'assistant', content: null, tool_calls: [{ id: 'call_1', type: 'function', function: { name: 'get_order', arguments: '{}' } }] },
  ])
})

test('provided tools are dropped and the tool choice is mapped', () => {
  const body = toStudioAiRequest(
    turn({
      input: [userText('Hi')],
      tools: [
        { name: 'lookup_order', description: 'Find an order.', parameters: { type: 'object' }, kind: 'client' },
        { name: 'web_search', description: 'Search the web.', parameters: {}, kind: 'provided', provider: { type: 'web_search' } },
      ],
      toolChoice: { name: 'lookup_order' },
    }),
  )
  expect(body.tools).toEqual([{ type: 'function', function: { name: 'lookup_order', description: 'Find an order.', parameters: { type: 'object' } } }])
  expect(body.tool_choice).toEqual({ type: 'function', function: { name: 'lookup_order' } })
})

test('client tools without a tool choice are sent with no tool_choice', () => {
  const body = toStudioAiRequest(
    turn({ input: [userText('Hi')], tools: [{ name: 'lookup_order', description: 'Find an order.', parameters: {} }] }),
  )
  expect(body.tools).toHaveLength(1)
  expect(body).not.toHaveProperty('tool_choice')
})

test('a string tool choice passes through, and no tool choice is sent without client tools', () => {
  const auto = toStudioAiRequest(
    turn({ tools: [{ name: 'lookup_order', description: 'Find an order.', parameters: {} }], toolChoice: 'auto' }),
  )
  expect(auto.tool_choice).toBe('auto')

  const providedOnly = toStudioAiRequest(
    turn({
      tools: [{ name: 'web_search', description: 'Search the web.', parameters: {}, kind: 'provided', provider: { type: 'web_search' } }],
      toolChoice: 'required',
    }),
  )
  expect(providedOnly).not.toHaveProperty('tools')
  expect(providedOnly).not.toHaveProperty('tool_choice')
})

test('a JSON response format asks for a JSON object and states the schema in the system message', () => {
  const schema = { type: 'object', properties: { verdict: { type: 'string' } }, required: ['verdict'] }
  const body = toStudioAiRequest(turn({ instructions: 'Decide the case.', responseFormat: { type: 'json', name: 'verdict', schema } }))
  expect(body.response_format).toEqual({ type: 'json_object' })
  expect(body.messages[0]).toEqual({ role: 'system', content: expect.stringContaining('Decide the case.') })
  expect(body.messages[0].content).toContain(`Reply with a single JSON object that matches this JSON Schema: ${JSON.stringify(schema)}`)
})

test('a JSON response format without instructions creates the system message', () => {
  const schema = { type: 'object', properties: { ok: { type: 'boolean' } } }
  const body = toStudioAiRequest(turn({ responseFormat: { type: 'json', name: 'check', schema } }))
  expect(body.messages).toEqual([
    { role: 'system', content: `Reply with a single JSON object that matches this JSON Schema: ${JSON.stringify(schema)}` },
  ])
})

test('executeTurn streams a text reply and completes with its output and usage', async () => {
  const controller = new AbortController()
  let sentSignal: AbortSignal | undefined
  let sends = 0
  const adapter = createProxyAdapter(async (_body, signal) => {
    sends += 1
    sentSignal = signal
    return reply({ message: { content: 'Refund approved.', tool_calls: [] }, usage: { prompt_tokens: 120, completion_tokens: 8 } })
  })
  const handler = adapter.executeTurn(turn({ input: [userText('Refund?')] }), { signal: controller.signal })
  expect(sends).toBe(1)
  const events = await collect(handler.stream)
  const response = await handler.complete
  expect(sends).toBe(1)
  const messageId = response.output[0].id
  expect(events).toEqual([
    { type: 'TEXT_MESSAGE_START', messageId, role: 'assistant' },
    { type: 'TEXT_MESSAGE_CONTENT', messageId, delta: 'Refund approved.' },
    { type: 'TEXT_MESSAGE_END', messageId },
  ])
  expect(response).toMatchObject({
    status: 'completed',
    model: 'test-model',
    usage: { inputTokens: 120, outputTokens: 8, totalTokens: 128 },
    output: [
      { kind: 'output', type: 'message', role: 'assistant', status: 'completed', content: [{ type: 'text', text: 'Refund approved.', annotations: [] }] },
    ],
  })
  expect(sentSignal).toBe(controller.signal)
})

test('a reply with tool calls streams each call and completes with function_call items', async () => {
  const adapter = createProxyAdapter(async () =>
    reply({
      message: { content: null, tool_calls: [{ id: 'call_9', type: 'function', function: { name: 'issue_refund', arguments: '{"amount":12}' } }] },
      finish_reason: 'tool_calls',
    }),
  )
  const handler = adapter.executeTurn(turn({ input: [userText('Refund 12')] }))
  expect(await collect(handler.stream)).toEqual([
    { type: 'TOOL_CALL_START', toolCallId: 'call_9', toolCallName: 'issue_refund' },
    { type: 'TOOL_CALL_ARGS', toolCallId: 'call_9', delta: '{"amount":12}' },
    { type: 'TOOL_CALL_END', toolCallId: 'call_9' },
  ])
  const response = await handler.complete
  expect(response.status).toBe('completed')
  expect(response.output).toEqual([
    { id: expect.any(String), kind: 'output', type: 'function_call', callId: 'call_9', name: 'issue_refund', arguments: '{"amount":12}', status: 'completed' },
  ])
})

test('a rejected send completes as failed with its message, and the stream ends without throwing', async () => {
  const adapter = createProxyAdapter(() => Promise.reject(new Error('The model proxy is not configured.')))
  const handler = adapter.executeTurn(turn({ input: [userText('Hi')] }))
  await expect(collect(handler.stream)).resolves.toEqual([])
  expect(await handler.complete).toEqual({
    id: expect.any(String),
    createdAt: expect.any(Number),
    status: 'failed',
    output: [],
    error: { code: 'proxy_error', message: 'The model proxy is not configured.' },
  })
})

const malformedReplies: [string, unknown][] = [
  ['no message', {}],
  ['no message and no tool_calls', { finish_reason: 'stop' }],
  ['no tool_calls key', { message: { content: 'Partial.' }, finish_reason: 'stop' }],
  ['a null tool call', { message: { content: null, tool_calls: [null] }, finish_reason: 'tool_calls' }],
]

for (const [name, badReply] of malformedReplies) {
  test(`a malformed reply (${name}) completes as failed and the stream ends empty without throwing`, async () => {
    const handler = createProxyAdapter(async () => badReply as StudioAiReply).executeTurn(turn({ input: [userText('Hi')] }))
    await expect(collect(handler.stream)).resolves.toEqual([])
    expect(await handler.complete).toMatchObject({
      status: 'failed',
      output: [],
      error: { code: 'proxy_error', message: 'The model reply was malformed.' },
    })
  })
}

test('an AbortError rejection completes as cancelled with no error', async () => {
  const aborted = new Error('The operation was aborted.')
  aborted.name = 'AbortError'
  const handler = createProxyAdapter(() => Promise.reject(aborted)).executeTurn(turn({ input: [userText('Hi')] }))
  expect(await collect(handler.stream)).toEqual([])
  const response = await handler.complete
  expect(response.status).toBe('cancelled')
  expect(response.error).toBeUndefined()
})

test('a reply cut off by the token limit completes as incomplete', async () => {
  const adapter = createProxyAdapter(async () => reply({ message: { content: 'The refund', tool_calls: [] }, finish_reason: 'length' }))
  const handler = adapter.executeTurn(turn({ input: [userText('Explain')] }))
  await collect(handler.stream)
  expect(await handler.complete).toMatchObject({ status: 'incomplete', incompleteDetails: { reason: 'max_output_tokens' } })
})
