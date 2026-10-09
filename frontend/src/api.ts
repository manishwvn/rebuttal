import type { AnalyticsReport, AuditEntry, DemoSessionInfo, Dispute, Health, Proposal, SimulatorCase } from './types'

// The dashboard only ever talks to the Rebuttal backend. It never calls PayPal.
export const API_BASE = (import.meta.env.VITE_API_BASE ?? 'http://localhost:8000').replace(/\/$/, '')
const API_TOKEN = import.meta.env.VITE_API_TOKEN as string | undefined

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

async function request<T>(
  path: string,
  init: { method?: 'GET' | 'POST'; body?: unknown; sendToken?: boolean } = {},
): Promise<T> {
  const headers: Record<string, string> = {}
  if (API_TOKEN && init.sendToken !== false) headers.Authorization = `Bearer ${API_TOKEN}`
  if (init.body !== undefined) headers['Content-Type'] = 'application/json'
  let response: Response
  try {
    response = await fetch(`${API_BASE}${path}`, {
      method: init.method ?? 'GET',
      headers,
      body: init.body === undefined ? undefined : JSON.stringify(init.body),
    })
  } catch {
    throw new ApiError(0, `Cannot reach the backend at ${API_BASE}. Is it running?`)
  }
  if (!response.ok) {
    let detail = response.statusText
    try {
      const data = await response.json()
      if (typeof data.detail === 'string') detail = data.detail
    } catch {
      // keep the status text
    }
    throw new ApiError(response.status, detail)
  }
  return (await response.json()) as T
}

// One set of calls, rooted at `prefix`: '/api' for the real backend, '/api/demo/<sessionId>' for a demo session.
// sendToken: false keeps VITE_API_TOKEN off every request made through this client.
export function createApi(prefix = '/api', options: { sendToken?: boolean } = {}) {
  const { sendToken } = options
  return {
    health: () => request<Health>(`${prefix}/health`, { sendToken }),
    disputes: () => request<Dispute[]>(`${prefix}/disputes`, { sendToken }),
    analyze: (disputeId: string) =>
      request<Proposal>(`${prefix}/disputes/${encodeURIComponent(disputeId)}/analyze`, { method: 'POST', sendToken }),
    approve: (proposalId: string, editedMessage: string | null) =>
      request<Proposal>(`${prefix}/proposals/${encodeURIComponent(proposalId)}/approve`, {
        method: 'POST',
        body: { edited_message: editedMessage },
        sendToken,
      }),
    reject: (proposalId: string, reason: string) =>
      request<Proposal>(`${prefix}/proposals/${encodeURIComponent(proposalId)}/reject`, {
        method: 'POST',
        body: { reason },
        sendToken,
      }),
    retry: (proposalId: string) =>
      request<Proposal>(`${prefix}/proposals/${encodeURIComponent(proposalId)}/retry`, { method: 'POST', sendToken }),
    audit: (disputeId: string) => request<AuditEntry[]>(`${prefix}/audit/${encodeURIComponent(disputeId)}`, { sendToken }),
    simulatorCases: () => request<SimulatorCase[]>(`${prefix}/simulator/cases`, { sendToken }),
    simulate: (caseId: string) =>
      request<Proposal>(`${prefix}/simulator/dispute/${encodeURIComponent(caseId)}`, { method: 'POST', sendToken }),
    analytics: () => request<AnalyticsReport>(`${prefix}/analytics`, { sendToken }),
  }
}

export type Api = ReturnType<typeof createApi>

export const api = createApi()

// A demo session's calls, rooted at /api/demo/<sessionId>. Demo calls never send the dashboard token.
export function createDemoApi(sessionId: string): Api {
  return createApi(`/api/demo/${encodeURIComponent(sessionId)}`, { sendToken: false })
}

export function startDemoSession(): Promise<DemoSessionInfo> {
  return request<DemoSessionInfo>('/api/demo/sessions', { method: 'POST', sendToken: false })
}

export function resetDemoSession(sessionId: string): Promise<DemoSessionInfo> {
  return request<DemoSessionInfo>(`/api/demo/${encodeURIComponent(sessionId)}/reset`, { method: 'POST', sendToken: false })
}
