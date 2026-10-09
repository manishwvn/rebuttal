import { lazy, Suspense, useCallback, useEffect, useRef, useState } from 'react'
import { api, API_BASE } from './api'
import { CaseView } from './components/CaseView'
import { Inbox } from './components/Inbox'
import { SimulatorPanel } from './components/SimulatorPanel'
import type { AuditEntry, Dispute, Health } from './types'
import './App.css'
import './components/analytics/analytics.css'

// AG Studio is a large bundle, so the Analytics view loads the first time its tab opens.
const AnalyticsView = lazy(() => import('./components/analytics/AnalyticsView').then((m) => ({ default: m.AnalyticsView })))

type View = 'desk' | 'analytics'

// The open tab lives in the URL hash: it survives a reload, and #analytics opens that tab directly.
const viewFromHash = (): View => (window.location.hash === '#analytics' ? 'analytics' : 'desk')

const message = (e: unknown) => (e instanceof Error ? e.message : String(e))

export default function App() {
  const [view, setView] = useState<View>(viewFromHash)
  const [health, setHealth] = useState<Health | null>(null)
  const [disputes, setDisputes] = useState<Dispute[] | null>(null)
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [audit, setAudit] = useState<AuditEntry[]>([])
  const [error, setError] = useState<string | null>(null)

  // Only the newest audit request may set the trail: a slow older response (another dispute, or the same one before
  // a decision) must not overwrite it.
  const openId = useRef<string | null>(null)
  const auditRequest = useRef(0)
  const loadAudit = useCallback(async (disputeId: string) => {
    const request = ++auditRequest.current
    const entries = await api.audit(disputeId)
    if (request === auditRequest.current && openId.current === disputeId) setAudit(entries)
  }, [])

  const refresh = useCallback(
    async (focus?: string) => {
      const list = await api.disputes()
      setDisputes(list)
      const next = focus ?? openId.current
      if (next && list.some((d) => d.dispute_id === next)) {
        openId.current = next
        setSelectedId(next)
        await loadAudit(next)
      }
    },
    [loadAudit],
  )

  useEffect(() => {
    api.health().then(setHealth, (e: unknown) => setError(message(e)))
    api.disputes().then(setDisputes, (e: unknown) => setError(message(e)))
    // Load once on mount.
  }, [])

  // Back and forward move between the tabs; a typed or pasted #analytics does too.
  useEffect(() => {
    const sync = () => setView(viewFromHash())
    window.addEventListener('hashchange', sync)
    window.addEventListener('popstate', sync)
    return () => {
      window.removeEventListener('hashchange', sync)
      window.removeEventListener('popstate', sync)
    }
  }, [])

  const showView = (next: View) => {
    if (next === view) return
    // pushState leaves no trailing '#' on the Desk address, and Back returns to the previous tab.
    window.history.pushState(null, '', next === 'analytics' ? '#analytics' : `${window.location.pathname}${window.location.search}`)
    setView(next)
  }

  const select = (disputeId: string) => {
    openId.current = disputeId
    setSelectedId(disputeId)
    setAudit([])
    loadAudit(disputeId).catch((e: unknown) => setError(message(e)))
  }

  const changed = useCallback(async () => {
    try {
      await refresh()
      setError(null)
    } catch (e) {
      setError(message(e))
    }
  }, [refresh])

  const created = async (disputeId: string) => {
    setAudit([])
    await refresh(disputeId)
  }

  const selected = disputes?.find((d) => d.dispute_id === selectedId) ?? null
  const waiting = disputes?.filter((d) => d.proposal?.status === 'PENDING').length ?? 0
  const isMock = health?.mode.startsWith('mock') ?? false

  return (
    <div className="wrap">
      <header className="bar">
        <div className="brand">
          <h1>Rebuttal</h1>
          <span>PayPal dispute desk</span>
        </div>
        <span className="badge" data-testid="mode-badge" title={API_BASE}>
          {health ? `${health.mode}${health.auth ? ' · token' : ''}` : 'connecting…'}
        </span>
      </header>

      <div className="tabs" role="tablist" aria-label="Sections">
        <button
          type="button"
          role="tab"
          id="tab-desk"
          data-testid="tab-desk"
          className="tab"
          aria-selected={view === 'desk'}
          aria-controls="panel-desk"
          onClick={() => showView('desk')}
        >
          Desk
        </button>
        <button
          type="button"
          role="tab"
          id="tab-analytics"
          data-testid="tab-analytics"
          className="tab"
          aria-selected={view === 'analytics'}
          aria-controls="panel-analytics"
          onClick={() => showView('analytics')}
        >
          Analytics
        </button>
      </div>

      {/* Kept mounted while Analytics is open, so the open case and an unsent draft survive a tab switch. */}
      <div className="desk-panel" role="tabpanel" id="panel-desk" aria-labelledby="tab-desk" hidden={view !== 'desk'}>
        {error && (
          <p role="alert" className="error banner" data-testid="app-error">
            {error}
          </p>
        )}

        {isMock && <SimulatorPanel onCreated={created} />}

        <section className="block" aria-labelledby="inbox-title">
          <div className="block-head">
            <h2 id="inbox-title">Inbox</h2>
            <p data-testid="waiting">
              {waiting} {waiting === 1 ? 'proposal' : 'proposals'} waiting for you
            </p>
          </div>
          <Inbox disputes={disputes ?? []} selectedId={selectedId} onSelect={select} />
        </section>

        {selected ? (
          <CaseView dispute={selected} audit={audit} onChanged={changed} />
        ) : (
          <p className="note empty">{disputes === null ? 'Loading disputes…' : 'Pick a dispute in the inbox to see what the agent proposes.'}</p>
        )}
      </div>

      <div role="tabpanel" id="panel-analytics" aria-labelledby="tab-analytics" hidden={view !== 'analytics'}>
        {view === 'analytics' && (
          <Suspense fallback={<p className="note">Loading analytics…</p>}>
            <AnalyticsView />
          </Suspense>
        )}
      </div>
    </div>
  )
}
