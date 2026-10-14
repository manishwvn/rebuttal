import type { CSSProperties } from 'react'
import type { AgWidgetParams } from 'ag-studio'
import { useWidgetRows } from './useWidgetRows'

const SLOTS = ['category', 'value']

const ROOT: CSSProperties = { display: 'flex', flexDirection: 'column', gap: 8, height: '100%', boxSizing: 'border-box', padding: 12, overflow: 'auto' }
const ROW: CSSProperties = { display: 'grid', gridTemplateColumns: 'minmax(0, 30%) 1fr auto', alignItems: 'center', gap: 10 }
const LABEL: CSSProperties = { overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }
const TRACK: CSSProperties = { height: 12, borderRadius: 4, background: 'var(--raised)', overflow: 'hidden' }
const FILL: CSSProperties = { height: '100%', background: 'var(--accent)' }
const VALUE: CSSProperties = { fontFamily: 'var(--mono)', fontVariantNumeric: 'tabular-nums', whiteSpace: 'nowrap' }

export default function RankedBarsWidget(params: AgWidgetParams) {
  const { widgetApi, widgetId } = params
  const data = useWidgetRows(params, SLOTS)
  if (!data) return <div data-widget-id={widgetId} style={ROOT} />

  const [categoryField, valueField] = data.fields
  const bars = data.rows
    .map((row) => ({
      label: widgetApi.formatFieldValue(categoryField, row[categoryField.key]),
      value: Number(row[valueField.key] ?? 0),
    }))
    .sort((a, b) => b.value - a.value)
  const max = bars[0]?.value ?? 0

  return (
    <div data-widget-id={widgetId} style={ROOT}>
      {bars.map((bar, index) => (
        <div key={index} data-testid="bar-row" data-label={bar.label} data-value={bar.value} style={ROW}>
          <span style={LABEL}>{bar.label}</span>
          <div style={TRACK}>
            <div style={{ ...FILL, width: max > 0 ? `${(bar.value / max) * 100}%` : '0%' }} />
          </div>
          <span style={VALUE}>{widgetApi.formatFieldValue(valueField, bar.value)}</span>
        </div>
      ))}
    </div>
  )
}
