import { lazy, Suspense, useEffect, useState } from 'react'
import { api, API_BASE } from '../api'
import type { Health } from '../types'
import { Desk } from './Desk'

// AG Studio is a large bundle, so the Analytics view loads the first time its tab opens.
const AnalyticsView = lazy(() => import('./analytics/AnalyticsView').then((m) => ({ default: m.AnalyticsView })))

type View = 'desk' | 'analytics'

// The open tab lives in the URL hash: it survives a reload, and #analytics opens that tab directly.
const viewFromHash = (): View => (window.location.hash === '#analytics' ? 'analytics' : 'desk')

export function Dashboard() {
  const [view, setView] = useState<View>(viewFromHash)
  const [health, setHealth] = useState<Health | null>(null)
  const [healthError, setHealthError] = useState<string | null>(null)

  useEffect(() => {
    // An error with no text (an empty detail, or an empty status text over HTTP/2) still gets a banner.
    api.health().then(setHealth, (e: unknown) => setHealthError(e instanceof Error && e.message ? e.message : 'The backend health check failed'))
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

  const isMock = health?.mode.startsWith('mock') ?? false

  return (
    <div className="wrap">
      <header className="bar">
        <div className="brand">
          <h1>Rebuttal</h1>
          <span>PayPal dispute desk</span>
        </div>
        <div className="actions">
          <span className="badge" data-testid="mode-badge" title={API_BASE}>
            {health ? `${health.mode}${health.auth ? ' · token' : ''}` : 'connecting…'}
          </span>
          <a href="#demo" className="demo-link" data-testid="try-demo">
            Try the demo
          </a>
        </div>
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
        {healthError !== null && (
          <p role="alert" className="error banner" data-testid="app-error">
            {healthError}
          </p>
        )}
        <Desk simulator={isMock} />
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
