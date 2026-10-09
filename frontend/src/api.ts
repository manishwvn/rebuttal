import type { AnalyticsRow, AnalyticsSummary, AuditEntry, DeadlineRow, Dispute, Health, Proposal, SimulatorCase } from './types'

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

async function request<T>(path: string, init: { method?: 'GET' | 'POST'; body?: unknown } = {}): Promise<T> {
  const headers: Record<string, string> = {}
  if (API_TOKEN) headers.Authorization = `Bearer ${API_TOKEN}`
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

export const api = {
  health: () => request<Health>('/api/health'),
  disputes: () => request<Dispute[]>('/api/disputes'),
  analyze: (disputeId: string) => request<Proposal>(`/api/disputes/${encodeURIComponent(disputeId)}/analyze`, { method: 'POST' }),
  approve: (proposalId: string, editedMessage: string | null) =>
    request<Proposal>(`/api/proposals/${encodeURIComponent(proposalId)}/approve`, {
      method: 'POST',
      body: { edited_message: editedMessage },
    }),
  reject: (proposalId: string, reason: string) =>
    request<Proposal>(`/api/proposals/${encodeURIComponent(proposalId)}/reject`, { method: 'POST', body: { reason } }),
  retry: (proposalId: string) =>
    request<Proposal>(`/api/proposals/${encodeURIComponent(proposalId)}/retry`, { method: 'POST' }),
  audit: (disputeId: string) => request<AuditEntry[]>(`/api/audit/${encodeURIComponent(disputeId)}`),
  simulatorCases: () => request<SimulatorCase[]>('/api/simulator/cases'),
  simulate: (caseId: string) => request<Proposal>(`/api/simulator/dispute/${encodeURIComponent(caseId)}`, { method: 'POST' }),
  analyticsRows: () => request<AnalyticsRow[]>('/api/analytics/rows'),
  analyticsSummary: () => request<AnalyticsSummary>('/api/analytics/summary'),
  analyticsDeadlines: () => request<DeadlineRow[]>('/api/analytics/deadlines'),
}
