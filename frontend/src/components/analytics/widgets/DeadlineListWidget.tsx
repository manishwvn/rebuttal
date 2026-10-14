import type { CSSProperties } from 'react'
import type { AgWidgetField, AgWidgetParams } from 'ag-studio'
import { useWidgetRows } from './useWidgetRows'

// Positions in the 'cols' fieldset. The dashboard maps dispute_id, reason, amount, status, due, hours_left in this order.
const DISPUTE_ID = 0
const REASON = 1
const AMOUNT = 2
const STATUS = 3
const HOURS_LEFT = 5
const MIN_FIELDS = HOURS_LEFT + 1

// Module scope keeps the slots array stable: useWidgetRows re-runs its effect when slots changes.
const COLS = ['cols']

type Row = Record<string, unknown>

// Under 48 hours show hours; from 48 hours up show whole days.
function duration(hours: number): string {
  return hours < 48 ? `${hours} h` : `${Math.round(hours / 24)} d`
}

function urgency(hours: number): { text: string; tone: string } {
  if (hours < 0) return { text: `Overdue ${duration(Math.abs(hours))}`, tone: 'var(--bad)' }
  return { text: `${duration(hours)} left`, tone: hours < 24 ? 'var(--warn)' : 'var(--muted)' }
}

const LIST: CSSProperties = { height: '100%', overflowY: 'auto', padding: 12 }

const ROW: CSSProperties = {
  display: 'flex',
  flexWrap: 'wrap',
  alignItems: 'center',
  gap: '6px 12px',
  padding: '8px 0',
  borderBottom: '1px solid var(--line)',
}

const DISPUTE: CSSProperties = { fontFamily: 'var(--mono)', fontSize: '0.84em' }

const REASON_TEXT: CSSProperties = { flex: '1 1 160px', minWidth: 0, overflowWrap: 'anywhere' }

const AMOUNT_TEXT: CSSProperties = { fontVariantNumeric: 'tabular-nums' }

const STATUS_TEXT: CSSProperties = { color: 'var(--muted)' }

const PILL: CSSProperties = {
  marginLeft: 'auto',
  padding: '1px 8px',
  borderRadius: 999,
  background: 'transparent',
  fontSize: '0.8rem',
  whiteSpace: 'nowrap',
}

interface DeadlineRowProps {
  params: AgWidgetParams
  fields: AgWidgetField[]
  row: Row
}

function DeadlineRow({ params, fields, row }: DeadlineRowProps) {
  const disputeId = String(row[fields[DISPUTE_ID].key] ?? '')
  const hoursLeft = Number(row[fields[HOURS_LEFT].key])
  const pill = urgency(hoursLeft)
  return (
    <div data-testid="deadline-row" data-dispute-id={disputeId} data-hours-left={hoursLeft} style={ROW}>
      <span style={DISPUTE}>{disputeId}</span>
      <span style={REASON_TEXT}>{String(row[fields[REASON].key] ?? '')}</span>
      <span style={AMOUNT_TEXT}>{params.widgetApi.formatFieldValue(fields[AMOUNT], row[fields[AMOUNT].key])}</span>
      <span style={STATUS_TEXT}>{String(row[fields[STATUS].key] ?? '')}</span>
      <span style={{ ...PILL, color: pill.tone, border: `1px solid ${pill.tone}` }}>{pill.text}</span>
    </div>
  )
}

export default function DeadlineListWidget(params: AgWidgetParams) {
  const data = useWidgetRows(params, COLS, MIN_FIELDS)
  return (
    <div data-widget-id={params.widgetId} style={LIST}>
      {data?.rows.map((row) => (
        <DeadlineRow key={String(row[data.fields[DISPUTE_ID].key])} params={params} fields={data.fields} row={row} />
      ))}
    </div>
  )
}
