import type { AnalyticsReport, AuditEntry, DemoSessionInfo, Dispute, Health, Proposal, SimulatorCase } from './types'

// The dashboard only ever talks to the Rebuttal backend. It never calls PayPal.
// Served by the backend (same origin) the base is empty; `npm run dev` and the e2e build point at localhost:8000.
export const API_BASE = ((import.meta.env.VITE_API_BASE as string | undefined) ?? (import.meta.env.DEV ? 'http://localhost:8000' : '')).replace(/\/$/, '')

// The API token is typed on the sign-in screen and kept in sessionStorage only (gone when the tab closes). A
// VITE_API_TOKEN is honoured by `npm run dev` alone: the build refuses it, and DEV is false there so it is dropped.
const TOKEN_KEY = 'rebuttal.token'
const DEV_TOKEN = import.meta.env.DEV ? (import.meta.env.VITE_API_TOKEN as string | undefined) : undefined

export function getToken(): string | null {
  try {
    return window.sessionStorage.getItem(TOKEN_KEY) || DEV_TOKEN || null
  } catch {
    return DEV_TOKEN || null
  }
}

export function setToken(token: string | null): void {
  try {
    if (token) window.sessionStorage.setItem(TOKEN_KEY, token)
    else window.sessionStorage.removeItem(TOKEN_KEY)
  } catch {
    // storage blocked: the token then lives for this page only, which getToken() reports as signed out on reload
  }
}

// Fired when a request that carried (or needed) the token is refused, so the app can return to the sign-in screen.
export const UNAUTHORIZED_EVENT = 'rebuttal:unauthorized'

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

async function request<T>(
  path: string,
  init: { method?: 'GET' | 'POST'; body?: unknown; sendToken?: boolean; token?: string } = {},
): Promise<T> {
  const headers: Record<string, string> = {}
  const token = init.sendToken !== false ? (init.token ?? getToken()) : null
  if (token) headers.Authorization = `Bearer ${token}`
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
    if (response.status === 401 && init.sendToken !== false && init.token === undefined) window.dispatchEvent(new Event(UNAUTHORIZED_EVENT))
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
  }
}

export type Api = ReturnType<typeof createApi>

// The dashboard-only call stays off the factory, so a demo client (Api) carries nothing the demo routes lack.
export const api = {
  ...createApi(),
  analytics: () => request<AnalyticsReport>('/api/analytics'),
}

// Checks a pasted token against a protected route without storing it. Resolves true when the backend accepts it.
export async function verifyToken(token: string): Promise<boolean> {
  try {
    await request<Dispute[]>('/api/disputes', { token })
    return true
  } catch (e) {
    if (e instanceof ApiError && e.status === 401) return false
    throw e
  }
}

// The session id becomes a path segment. encodeURIComponent leaves '.' and '..' unchanged and fetch resolves them,
// so the id is checked against a plain alphabet before any path is built.
const DEMO_SESSION_ID = /^[A-Za-z0-9_-]+$/

function demoRoot(sessionId: string): string {
  if (!DEMO_SESSION_ID.test(sessionId)) throw new Error('Invalid demo session id')
  return `/api/demo/${encodeURIComponent(sessionId)}`
}

// A demo session's calls, rooted at /api/demo/<sessionId>. Demo calls never send the dashboard token.
export function createDemoApi(sessionId: string): Api {
  return createApi(demoRoot(sessionId), { sendToken: false })
}

export function startDemoSession(): Promise<DemoSessionInfo> {
  return request<DemoSessionInfo>('/api/demo/sessions', { method: 'POST', sendToken: false })
}

export async function resetDemoSession(sessionId: string): Promise<DemoSessionInfo> {
  return request<DemoSessionInfo>(`${demoRoot(sessionId)}/reset`, { method: 'POST', sendToken: false })
}
