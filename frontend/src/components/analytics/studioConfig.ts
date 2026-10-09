import type { AgAggregationFunction, AgDataSourcesDefinition, AgFieldDefinition, AgReportState, AgStudioTheme } from 'ag-studio'
import { studioTheme } from 'ag-studio'
import { reasonLabel } from '../../labels'
import type { AnalyticsOutcome, AnalyticsRow, AnalyticsSummary, DeadlineRow } from '../../types'

// Labels the dashboard shows in place of the backend's codes.
const OUTCOME_LABEL: Record<AnalyticsOutcome, string> = {
  not_analyzed: 'Not analyzed',
  awaiting_merchant: 'Awaiting you',
  rejected: 'Rejected',
  failed: 'Failed',
  refunded: 'Refunded',
  partially_refunded: 'Partly refunded',
  kept: 'Kept / defended',
}

const STATUS_LABEL: Partial<Record<string, string>> = {
  NOT_ANALYZED: 'Not analyzed',
  PENDING: 'Pending',
  APPROVED: 'Approved',
  EXECUTED: 'Executed',
  REJECTED: 'Rejected',
  FAILED: 'Failed',
  INTERRUPTED: 'Interrupted',
}

// Field metadata. Names become legends and column headers; formats decide how numbers, money and dates read.
const textField = (id: string, name: string): AgFieldDefinition => ({ id, name, format: 'textFormat' })
const wholeField = (id: string, name: string): AgFieldDefinition => ({ id, name, format: 'integerFormat' })
const moneyField = (id: string, name: string): AgFieldDefinition => ({
  id,
  name,
  format: 'currencyFormat',
  formatOptions: { format: '$#,##0.00' },
})
// The value is already in percentage points (66.7 is 66.7%), so the % sign is a literal and nothing is scaled.
const percentField = (id: string, name: string): AgFieldDefinition => ({
  id,
  name,
  format: 'decimalFormat',
  formatOptions: { format: '0.0"%"' },
})
const dateTimeField = (id: string, name: string): AgFieldDefinition => ({ id, name, format: 'dateTimeFormat' })

const DISPUTE_FIELDS: AgFieldDefinition[] = [
  textField('dispute_id', 'Dispute'),
  textField('reason', 'Buyer reason'),
  textField('outcome', 'Outcome'),
  textField('product', 'Product'),
  moneyField('amount', 'Disputed amount'),
  moneyField('refunded', 'Refunded'),
  moneyField('kept', 'Kept'),
  moneyField('open', 'Open'),
  wholeField('count', 'Disputes'),
  dateTimeField('due', 'Due'),
]

const DEADLINE_FIELDS: AgFieldDefinition[] = [
  textField('dispute_id', 'Dispute'),
  textField('reason', 'Buyer reason'),
  moneyField('amount', 'Amount'),
  textField('status', 'Status'),
  dateTimeField('due', 'Due'),
  wholeField('hours_left', 'Hours left'),
]

const KPI_FIELDS: AgFieldDefinition[] = [
  wholeField('disputes', 'Disputes'),
  moneyField('disputed', 'Disputed'),
  moneyField('refunded', 'Refunded'),
  moneyField('kept', 'Kept'),
  moneyField('open', 'Open'),
  percentField('agreement_pct', 'Model vs final agreement'),
  wholeField('guard_changes', 'Guard changes'),
]

const disputeRow = (row: AnalyticsRow) => ({ ...row, reason: reasonLabel(row.reason), outcome: OUTCOME_LABEL[row.outcome] })

const deadlineRow = (row: DeadlineRow) => ({ ...row, reason: reasonLabel(row.reason), status: STATUS_LABEL[row.status] ?? row.status })

function kpiRow(summary: AnalyticsSummary) {
  const { totals, money, agreement } = summary
  return {
    disputes: totals.disputes,
    disputed: money.disputed,
    refunded: money.refunded,
    kept: money.kept,
    open: money.open,
    // The rate is 0..1. Show percentage points to one decimal, and 0 when nothing has been compared yet.
    agreement_pct: agreement.rate === null ? 0 : Math.round(agreement.rate * 1000) / 10,
    guard_changes: agreement.guard_changes,
  }
}

// The three sources. Studio ignores structural changes after init, so callers remount the dashboard to show new data.
export function dashboardData(rows: AnalyticsRow[], deadlines: DeadlineRow[], summary: AnalyticsSummary): AgDataSourcesDefinition {
  return {
    sources: [
      { id: 'disputes', name: 'Disputes', fields: DISPUTE_FIELDS, data: rows.map(disputeRow) },
      { id: 'deadlines', name: 'Deadlines', fields: DEADLINE_FIELDS, data: deadlines.map(deadlineRow) },
      { id: 'kpis', name: 'Summary', fields: KPI_FIELDS, data: [kpiRow(summary)] },
    ],
  }
}

const kpi = (caption: string, id: string, aggregation: AgAggregationFunction) => ({
  type: 'value' as const,
  dataMapping: { value: [{ id, aggregation }] },
  format: { caption: { enabled: true, text: caption } },
})

// One page in view mode with the filters panel collapsed. The track grid has 24 columns; rows are 16px tall.
// Row 1 is five KPIs, row 2 three charts, row 3 the deadlines table (most urgent first).
export const DASHBOARD_STATE: AgReportState = {
  pages: [
    {
      id: 'overview',
      widgets: {
        'kpi-disputes': kpi('Disputes', 'kpis.disputes', 'sum'),
        'kpi-disputed': kpi('Disputed $', 'kpis.disputed', 'sum'),
        'kpi-refunded': kpi('Refunded $', 'kpis.refunded', 'sum'),
        'kpi-kept': kpi('Kept $', 'kpis.kept', 'sum'),
        'kpi-agreement': kpi('Model vs final agreement', 'kpis.agreement_pct', 'avg'),
        'bar-reason': {
          type: 'bar-chart-grouped',
          dataMapping: {
            categoryKey: [{ id: 'disputes.reason' }],
            valueKey: [{ id: 'disputes.count', aggregation: 'sum' }],
          },
          format: { title: { enabled: true, text: 'Disputes by reason' } },
        },
        'donut-outcome': {
          type: 'donut-chart',
          dataMapping: {
            categoryKey: [{ id: 'disputes.outcome' }],
            valueKey: [{ id: 'disputes.amount', aggregation: 'sum' }],
          },
          format: { title: { enabled: true, text: 'Money by outcome' } },
        },
        'stacked-product': {
          type: 'bar-chart-stacked',
          dataMapping: {
            categoryKey: [{ id: 'disputes.product' }],
            valueKey: [
              { id: 'disputes.refunded', aggregation: 'sum' },
              { id: 'disputes.kept', aggregation: 'sum' },
              { id: 'disputes.open', aggregation: 'sum' },
            ],
          },
          // Three series, so the legend is what tells refunded, kept and open apart.
          format: {
            title: { enabled: true, text: 'Kept vs refunded by product' },
            style: { theme: { common: { legend: { enabled: true, position: 'bottom' } } } },
          },
        },
        deadlines: {
          type: 'grid',
          // Plain columns are grouped by, and dispute_id is unique, so each deadline is one row.
          dataMapping: {
            cols: [
              { id: 'deadlines.dispute_id' },
              { id: 'deadlines.reason' },
              { id: 'deadlines.amount' },
              { id: 'deadlines.status' },
              { id: 'deadlines.due' },
              { id: 'deadlines.hours_left' },
            ],
          },
          sort: [{ field: { id: 'deadlines.hours_left' }, direction: 'asc' }],
          format: { title: { enabled: true, text: 'Response deadlines' } },
        },
      },
      widgetLayout: {
        'kpi-disputes': { xTrack: 0, yTrack: 0, xSpan: 4, ySpan: 8 },
        'kpi-disputed': { xTrack: 4, yTrack: 0, xSpan: 5, ySpan: 8 },
        'kpi-refunded': { xTrack: 9, yTrack: 0, xSpan: 5, ySpan: 8 },
        'kpi-kept': { xTrack: 14, yTrack: 0, xSpan: 5, ySpan: 8 },
        'kpi-agreement': { xTrack: 19, yTrack: 0, xSpan: 5, ySpan: 8 },
        'bar-reason': { xTrack: 0, yTrack: 8, xSpan: 8, ySpan: 20 },
        'donut-outcome': { xTrack: 8, yTrack: 8, xSpan: 8, ySpan: 20 },
        'stacked-product': { xTrack: 16, yTrack: 8, xSpan: 8, ySpan: 20 },
        deadlines: { xTrack: 0, yTrack: 28, xSpan: 24, ySpan: 14 },
      },
    },
  ],
  selectedPageId: 'overview',
  panels: { filters: { collapsed: true } },
}

// Base colours are the Inbox grid theme's light and dark palettes. Chart series use the accent teal, then the good,
// warn and bad tones from index.css, then two neutrals. Strokes match the fills, since Studio's default stroke is blue.
// The Studio theme names the grid header colour gridHeaderBackgroundColor.
export const DASHBOARD_THEME: AgStudioTheme = studioTheme
  .withParams(
    {
      backgroundColor: '#ffffff',
      foregroundColor: '#14202e',
      accentColor: '#0e6b63',
      borderColor: '#d8dee6',
      gridHeaderBackgroundColor: '#f7f9fb',
      browserColorScheme: 'light',
      fontFamily: '"Public Sans", system-ui, -apple-system, "Segoe UI", sans-serif',
      chartPaletteFills1Color: '#0e6b63',
      chartPaletteFills2Color: '#1d7a3d',
      chartPaletteFills3Color: '#985a00',
      chartPaletteFills4Color: '#b3262d',
      chartPaletteFills5Color: '#5a6777',
      chartPaletteFills6Color: '#4fa39a',
      chartPaletteFills7Color: '#9aa4b1',
      chartPaletteStrokes1Color: '#0e6b63',
      chartPaletteStrokes2Color: '#1d7a3d',
      chartPaletteStrokes3Color: '#985a00',
      chartPaletteStrokes4Color: '#b3262d',
      chartPaletteStrokes5Color: '#5a6777',
      chartPaletteStrokes6Color: '#4fa39a',
      chartPaletteStrokes7Color: '#9aa4b1',
    },
    'light',
  )
  .withParams(
    {
      backgroundColor: '#161f29',
      foregroundColor: '#e5ebf1',
      accentColor: '#4cc2b4',
      borderColor: '#2a3643',
      gridHeaderBackgroundColor: '#1b2531',
      browserColorScheme: 'dark',
      fontFamily: '"Public Sans", system-ui, -apple-system, "Segoe UI", sans-serif',
      chartPaletteFills1Color: '#4cc2b4',
      chartPaletteFills2Color: '#5bc983',
      chartPaletteFills3Color: '#e6a84a',
      chartPaletteFills4Color: '#f07178',
      chartPaletteFills5Color: '#93a0ae',
      chartPaletteFills6Color: '#86d8cd',
      chartPaletteFills7Color: '#c4cdd8',
      chartPaletteStrokes1Color: '#4cc2b4',
      chartPaletteStrokes2Color: '#5bc983',
      chartPaletteStrokes3Color: '#e6a84a',
      chartPaletteStrokes4Color: '#f07178',
      chartPaletteStrokes5Color: '#93a0ae',
      chartPaletteStrokes6Color: '#86d8cd',
      chartPaletteStrokes7Color: '#c4cdd8',
    },
    'dark',
  )
