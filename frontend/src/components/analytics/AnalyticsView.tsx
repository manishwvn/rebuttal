import { useEffect, useState } from 'react'
import { api } from '../../api'
import type { AnalyticsReport } from '../../types'
import { DashboardErrorBoundary } from './DashboardErrorBoundary'
import { StudioDashboard } from './StudioDashboard'
import { useAgThemeMode } from './useAgThemeMode'

const message = (e: unknown) => (e instanceof Error ? e.message : String(e))

export function AnalyticsView() {
  useAgThemeMode()
  const [report, setReport] = useState<AnalyticsReport | null>(null)
  // Counts successful loads. It is the dashboard's key, so each load remounts Studio with the new data.
  const [loadedAt, setLoadedAt] = useState(0)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  // Refresh increments this, and the effect loads again for each new value.
  const [attempt, setAttempt] = useState(0)

  useEffect(() => {
    // Once a newer load starts, this one's response is dropped, so a slow older response cannot overwrite it.
    let current = true
    api
      .analytics()
      .then((loaded) => {
        if (!current) return
        setReport(loaded)
        setLoadedAt((n) => n + 1)
        setError(null)
      })
      .catch((e: unknown) => {
        if (current) setError(message(e))
      })
      .finally(() => {
        if (current) setLoading(false)
      })
    return () => {
      current = false
    }
  }, [attempt])

  const refresh = () => {
    setLoading(true)
    setAttempt((n) => n + 1)
  }

  const totals = report?.summary.totals
  const status = totals
    ? `${totals.disputes} ${totals.disputes === 1 ? 'dispute' : 'disputes'} · ${totals.analyzed} analyzed · ${totals.executed} executed`
    : ''

  return (
    <section className="block analytics" aria-labelledby="analytics-title">
      <div className="block-head">
        <h2 id="analytics-title">Overview</h2>
        <p data-testid="analytics-status" aria-live="polite">
          {status}
        </p>
        <button type="button" className="ghost" onClick={refresh} disabled={loading} aria-busy={loading}>
          {loading ? 'Refreshing…' : 'Refresh'}
        </button>
      </div>
      {error && (
        <p role="alert" className="error banner">
          {error}
        </p>
      )}
      {error && !report && (
        <button type="button" className="ghost" onClick={refresh} data-testid="analytics-retry">
          Retry
        </button>
      )}
      {report ? (
        <DashboardErrorBoundary key={loadedAt}>
          <StudioDashboard rows={report.rows} deadlines={report.deadlines} summary={report.summary} />
        </DashboardErrorBoundary>
      ) : (
        !error && (
          <p className="note empty loading" role="status">
            Loading analytics…
          </p>
        )
      )}
    </section>
  )
}
