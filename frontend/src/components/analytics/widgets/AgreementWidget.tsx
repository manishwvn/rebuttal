import type { CSSProperties } from 'react'
import type { AgWidgetParams } from 'ag-studio'
import { useWidgetRows } from './useWidgetRows'

interface Metrics {
  pct: number
  compared: number
  agreed: number
  guardChanges: number
}

const NO_DATA: Metrics = { pct: 0, compared: 0, agreed: 0, guardChanges: 0 }

// Reads the one 'metrics' row. Fields are in order: agreement_pct (percentage points), compared, agreed, guard_changes.
function readMetrics(data: ReturnType<typeof useWidgetRows>): Metrics {
  if (!data || data.rows.length === 0) return NO_DATA
  const [pct, compared, agreed, guard] = data.fields
  const row = data.rows[0]
  return {
    pct: Number(row[pct.key]),
    compared: Number(row[compared.key]),
    agreed: Number(row[agreed.key]),
    guardChanges: Number(row[guard.key]),
  }
}

const ROOT: CSSProperties = { height: '100%', display: 'flex', flexDirection: 'column', gap: 8, padding: 12 }

const CAPTION: CSSProperties = {
  color: 'var(--muted)',
  fontSize: '0.72rem',
  fontWeight: 600,
  letterSpacing: '0.08em',
  textTransform: 'uppercase',
}

const FIGURE: CSSProperties = { fontFamily: 'var(--display)', fontSize: '2.5rem', fontWeight: 700, lineHeight: 1.1 }

const TRACK: CSSProperties = { height: 8, borderRadius: 4, background: 'var(--line)', overflow: 'hidden' }

const FILL: CSSProperties = { height: '100%', background: 'var(--accent)' }

const DETAIL: CSSProperties = { color: 'var(--muted)', fontSize: '0.875rem' }

export default function AgreementWidget(params: AgWidgetParams) {
  const { pct, compared, agreed, guardChanges } = readMetrics(useWidgetRows(params, ['metrics']))
  const hasComparison = compared > 0
  const clamped = Math.min(100, Math.max(0, pct))
  const decisions = compared === 1 ? 'decision' : 'decisions'
  return (
    <div data-widget-id={params.widgetId} style={ROOT}>
      <div style={CAPTION}>Model vs final agreement</div>
      <div data-testid="agreement-rate" style={FIGURE}>
        {hasComparison ? `${pct.toFixed(1)}%` : 'n/a'}
      </div>
      {hasComparison && (
        <div style={TRACK}>
          <div style={{ ...FILL, width: `${clamped}%` }} />
        </div>
      )}
      <div data-testid="agreement-detail" style={DETAIL}>
        {hasComparison
          ? `${agreed} of ${compared} ${decisions} kept as the model chose · ${guardChanges} changed by the guard`
          : 'No decisions compared yet'}
      </div>
    </div>
  )
}
