import type { CSSProperties } from 'react'
import type { AgWidgetParams } from 'ag-studio'
import { useWidgetRows } from './useWidgetRows'

const SLOTS = ['parts']
const COLOURS = ['var(--good)', 'var(--warn)', 'var(--line)']

const ROOT: CSSProperties = { display: 'flex', flexDirection: 'column', gap: 16, height: '100%', boxSizing: 'border-box', padding: 12 }
const BAR: CSSProperties = { display: 'flex', height: 18, borderRadius: 4, overflow: 'hidden' }
const LEGEND: CSSProperties = { display: 'flex', flexWrap: 'wrap', gap: 16 }
const ITEM: CSSProperties = { display: 'flex', alignItems: 'center', gap: 6 }
const DOT: CSSProperties = { width: 10, height: 10, borderRadius: '50%' }
const VALUE: CSSProperties = { fontFamily: 'var(--mono)', fontVariantNumeric: 'tabular-nums' }

export default function MoneySplitWidget(params: AgWidgetParams) {
  const { widgetApi, widgetId } = params
  const data = useWidgetRows(params, SLOTS)
  if (!data) return <div data-widget-id={widgetId} style={ROOT} />

  const row: Record<string, unknown> = data.rows[0] ?? {}
  const parts = data.fields.map((field) => ({ field, value: Number(row[field.key] ?? 0) }))
  const sum = parts.reduce((total, part) => total + part.value, 0)

  return (
    <div data-widget-id={widgetId} style={ROOT}>
      <div style={BAR}>
        {sum > 0 &&
          parts.map((part, index) => (
            <div key={index} style={{ width: `${(part.value / sum) * 100}%`, background: COLOURS[index] }} />
          ))}
      </div>
      <div style={LEGEND}>
        {parts.map((part, index) => {
          const name = widgetApi.getFieldName(part.field)
          return (
            <div key={index} data-testid="money-part" data-label={name} data-value={part.value} style={ITEM}>
              <span style={{ ...DOT, background: COLOURS[index] }} />
              <span>{name}</span>
              <span style={VALUE}>{widgetApi.formatFieldValue(part.field, part.value)}</span>
            </div>
          )
        })}
      </div>
    </div>
  )
}
