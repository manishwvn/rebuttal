import type { AgAiEvent, AgAiInputContent, AgAiOutputContent, AgAiOutputItem, AgLlmAdapter, AgLlmRequest, AgLlmResponse } from 'ag-studio'

// AG Studio's LLM boundary, served by the backend proxy POST /api/studio/ai. Type-only imports from 'ag-studio' keep
// this file free of runtime imports, so the e2e project and Node can load it unchanged.

// Wire format: the OpenAI chat-completions subset the backend proxy accepts.
export interface StudioAiToolCall {
  id: string
  type: 'function'
  function: { name: string; arguments: string }
}

export interface StudioAiMessage {
  role: 'system' | 'user' | 'assistant' | 'tool'
  content: string | null
  tool_calls?: StudioAiToolCall[]
  tool_call_id?: string
}

export interface StudioAiRequest {
  messages: StudioAiMessage[]
  tools?: { type: 'function'; function: { name: string; description: string; parameters: unknown } }[]
  tool_choice?: 'auto' | 'none' | 'required' | { type: 'function'; function: { name: string } }
  response_format?: { type: 'json_object' }
}

export interface StudioAiReply {
  message: { content: string | null; tool_calls: StudioAiToolCall[] }
  finish_reason: string | null
  usage: { prompt_tokens: number; completion_tokens: number } | null
  model: string
}

export type StudioAiSend = (body: StudioAiRequest, signal?: AbortSignal) => Promise<StudioAiReply>

function inputText(parts: AgAiInputContent[]): string {
  return parts.flatMap((part) => (part.type === 'text' ? [part.text] : [])).join('\n')
}

function outputText(parts: AgAiOutputContent[]): string {
  return parts.map((part) => (part.type === 'text' ? part.text : part.refusal)).join('\n')
}

function appendToSystem(messages: StudioAiMessage[], text: string): void {
  const first = messages[0]
  if (first?.role === 'system') first.content = first.content ? `${first.content}\n\n${text}` : text
  else messages.unshift({ role: 'system', content: text })
}

export function toStudioAiRequest(request: AgLlmRequest): StudioAiRequest {
  const messages: StudioAiMessage[] = []
  if (request.instructions) messages.push({ role: 'system', content: request.instructions })

  for (const item of request.input) {
    if (item.type === 'message') {
      if (item.kind === 'input') messages.push({ role: item.role, content: inputText(item.content) })
      else messages.push({ role: 'assistant', content: outputText(item.content) })
    } else if (item.type === 'function_call') {
      const call: StudioAiToolCall = { id: item.callId, type: 'function', function: { name: item.name, arguments: item.arguments } }
      // Consecutive calls, and a call right after assistant text, share one assistant message.
      const last = messages.at(-1)
      if (last?.role === 'assistant') last.tool_calls = [...(last.tool_calls ?? []), call]
      else messages.push({ role: 'assistant', content: null, tool_calls: [call] })
    } else if (item.type === 'function_call_output') {
      messages.push({ role: 'tool', tool_call_id: item.callId, content: item.output })
    }
  }

  // request.model is not forwarded: the backend proxy owns the model and its effort, so the browser never picks one.
  const body: StudioAiRequest = { messages }
  const tools = (request.tools ?? [])
    .filter((tool) => tool.kind !== 'provided')
    .map((tool) => ({ type: 'function' as const, function: { name: tool.name, description: tool.description, parameters: tool.parameters } }))
  if (tools.length > 0) {
    body.tools = tools
    if (request.toolChoice !== undefined) {
      const choice = request.toolChoice
      body.tool_choice = typeof choice === 'string' ? choice : { type: 'function', function: { name: choice.name } }
    }
  }

  if (request.responseFormat.type === 'json') {
    body.response_format = { type: 'json_object' }
    appendToSystem(messages, `Reply with a single JSON object that matches this JSON Schema: ${JSON.stringify(request.responseFormat.schema)}`)
  }
  return body
}

// randomUUID exists only in secure contexts, so a plain-http page falls back to a counter.
let fallbackIds = 0
function newId(): string {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') return crypto.randomUUID()
  fallbackIds += 1
  return `studio-ai-${fallbackIds}`
}

// The fetch boundary casts the JSON reply without checking it, so a reply off the wire shape fails the turn here
// with a fixed message instead of a TypeError.
function checkedReply(value: StudioAiReply): StudioAiReply {
  const calls = value?.message?.tool_calls
  if (!Array.isArray(calls) || !calls.every((call) => call?.function)) throw new Error('The model reply was malformed.')
  return value
}

function eventsFor(reply: StudioAiReply, messageId: string): AgAiEvent[] {
  const events: AgAiEvent[] = []
  if (reply.message.content) {
    events.push({ type: 'TEXT_MESSAGE_START', messageId, role: 'assistant' })
    events.push({ type: 'TEXT_MESSAGE_CONTENT', messageId, delta: reply.message.content })
    events.push({ type: 'TEXT_MESSAGE_END', messageId })
  }
  for (const call of reply.message.tool_calls) {
    events.push({ type: 'TOOL_CALL_START', toolCallId: call.id, toolCallName: call.function.name })
    events.push({ type: 'TOOL_CALL_ARGS', toolCallId: call.id, delta: call.function.arguments })
    events.push({ type: 'TOOL_CALL_END', toolCallId: call.id })
  }
  return events
}

// A failed turn yields no events: `complete` carries the failure. The events are built before the first yield, so a
// bad reply ends the stream empty instead of throwing mid-stream.
async function* streamEvents(reply: Promise<StudioAiReply>, messageId: string): AsyncGenerator<AgAiEvent> {
  let events: AgAiEvent[]
  try {
    events = eventsFor(checkedReply(await reply), messageId)
  } catch {
    return
  }
  yield* events
}

function completedResponse(reply: StudioAiReply, messageId: string): AgLlmResponse {
  const output: AgAiOutputItem[] = []
  if (reply.message.content) {
    output.push({
      id: messageId,
      kind: 'output',
      type: 'message',
      role: 'assistant',
      status: 'completed',
      content: [{ type: 'text', text: reply.message.content, annotations: [] }],
    })
  }
  for (const call of reply.message.tool_calls) {
    output.push({
      id: newId(),
      kind: 'output',
      type: 'function_call',
      callId: call.id,
      name: call.function.name,
      arguments: call.function.arguments,
      status: 'completed',
    })
  }
  const truncated = reply.finish_reason === 'length'
  const { usage } = reply
  return {
    id: newId(),
    createdAt: Date.now(),
    status: truncated ? 'incomplete' : 'completed',
    incompleteDetails: truncated ? { reason: 'max_output_tokens' } : undefined,
    output,
    usage: usage
      ? { inputTokens: usage.prompt_tokens, outputTokens: usage.completion_tokens, totalTokens: usage.prompt_tokens + usage.completion_tokens }
      : undefined,
    model: reply.model,
  }
}

function failedResponse(error: unknown, signal: AbortSignal | undefined): AgLlmResponse {
  const base = { id: newId(), createdAt: Date.now(), output: [] }
  if (signal?.aborted || (error instanceof Error && error.name === 'AbortError')) return { ...base, status: 'cancelled' }
  const message = error instanceof Error ? error.message : 'The model request failed.'
  return { ...base, status: 'failed', error: { code: 'proxy_error', message } }
}

export function createProxyAdapter(send: StudioAiSend): AgLlmAdapter {
  return {
    executeTurn(request, options) {
      const signal = options?.signal
      const messageId = newId()
      // The send starts now, once, and both stream and complete share it. A send that throws instead of rejecting
      // also ends as a failed reply, and a malformed reply fails the same way, so executeTurn never throws and
      // complete always resolves.
      const reply = new Promise<StudioAiReply>((resolve) => resolve(send(toStudioAiRequest(request), signal)))
      return {
        stream: streamEvents(reply, messageId),
        complete: reply
          .then((value) => completedResponse(checkedReply(value), messageId))
          .catch((error: unknown) => failedResponse(error, signal)),
      }
    },
  }
}
