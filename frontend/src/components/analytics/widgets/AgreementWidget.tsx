import type { CSSProperties } from 'react'
import type { AgWidgetParams } from 'ag-studio'
import { useWidgetRows } from './useWidgetRows'

interface Metrics {
  pct: number
  compared: number
  agreed: number
  guardChanges: number
}

type WidgetRows = NonNullable<ReturnType<typeof useWidgetRows>>

// Used only once the data has loaded and holds no row: nothing has been compared yet.
const NO_DATA: Metrics = { pct: 0, compared: 0, agreed: 0, guardChanges: 0 }

// Below this many compared decisions a percentage says little (0 of 1 reads as 0.0%), so the rate shows n/a.
// Display rule only: the backend agreement.rate is unchanged.
const MIN_SAMPLE = 5

const METRIC_COUNT = 4
// Module scope keeps the slots array stable: useWidgetRows re-runs its effect when slots changes.
const METRICS = ['metrics']

// Reads the one 'metrics' row. Fields are in order: agreement_pct (percentage points), compared, agreed, guard_changes.
function readMetrics({ fields, rows }: WidgetRows): Metrics {
  const row = rows[0]
  if (!row) return NO_DATA
  const [pct, compared, agreed, guard] = fields
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
  const data = useWidgetRows(params, METRICS, METRIC_COUNT)
  if (!data) {
    return (
      <div data-widget-id={params.widgetId} style={ROOT}>
        <div style={CAPTION}>Model vs final agreement</div>
        <div style={DETAIL}>Loading...</div>
      </div>
    )
  }
  const { pct, compared, agreed, guardChanges } = readMetrics(data)
  const hasComparison = compared > 0
  const showRate = compared >= MIN_SAMPLE
  const clamped = Math.min(100, Math.max(0, pct))
  const decisions = compared === 1 ? 'decision' : 'decisions'
  return (
    <div data-widget-id={params.widgetId} style={ROOT}>
      <div style={CAPTION}>Model vs final agreement</div>
      <div data-testid="agreement-rate" style={FIGURE}>
        {showRate ? `${pct.toFixed(1)}%` : 'n/a'}
      </div>
      {showRate && (
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
