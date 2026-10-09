import { useEffect, useMemo, useRef } from 'react'
import { AgGridProvider, AgGridReact } from 'ag-grid-react'
import {
  CellStyleModule,
  ClientSideRowModelModule,
  enableDevValidations,
  GridStateModule,
  RowApiModule,
  RowSelectionModule,
  themeQuartz,
  type CellClassParams,
  type ColDef,
  type GetRowIdParams,
  type GridApi,
  type GridReadyEvent,
  type GridState,
  type RowSelectionOptions,
  type ValueFormatterParams,
} from 'ag-grid-community'
import type { Dispute } from '../types'
import {
  ageHours,
  displayStatus,
  hoursLabel,
  money,
  reasonLabel,
  resolutionLabel,
  STATUS_LABEL,
  STATUS_TONE,
  type DisplayStatus,
} from '../labels'

// Only the grid features the inbox uses. A column or option whose module is missing here is silently inert (the
// dev build logs "error #200" naming the module), so add the module when you add the feature.
const modules = [
  ClientSideRowModelModule, // rowData, and the sorting and resizing the columns turn on
  RowSelectionModule, // rowSelection, node.setSelected
  RowApiModule, // api.forEachNode
  CellStyleModule, // colDef.cellClass
  GridStateModule, // initialState (the default sort)
]

if (import.meta.env.DEV) enableDevValidations()

// Same palette as preview/template.html. Light and dark both defined; `data-ag-theme-mode` picks one.
const theme = themeQuartz
  .withParams(
    {
      backgroundColor: '#ffffff',
      foregroundColor: '#14202e',
      accentColor: '#0e6b63',
      borderColor: '#d8dee6',
      headerBackgroundColor: '#f7f9fb',
      fontFamily: '"Public Sans", system-ui, -apple-system, "Segoe UI", sans-serif',
      fontSize: 14,
      browserColorScheme: 'light',
    },
    'light',
  )
  .withParams(
    {
      backgroundColor: '#161f29',
      foregroundColor: '#e5ebf1',
      accentColor: '#4cc2b4',
      borderColor: '#2a3643',
      headerBackgroundColor: '#1b2531',
      fontFamily: '"Public Sans", system-ui, -apple-system, "Segoe UI", sans-serif',
      fontSize: 14,
      browserColorScheme: 'dark',
    },
    'dark',
  )

interface InboxRow {
  id: string
  reason: string
  amount: number
  ageHours: number
  action: string
  status: DisplayStatus
}

const rowSelection: RowSelectionOptions = { mode: 'singleRow', checkboxes: false, enableClickSelection: false }

const columnDefs: ColDef<InboxRow>[] = [
  { field: 'id', headerName: 'Dispute', width: 150, cellClass: 'mono' },
  { field: 'reason', headerName: 'Buyer reason', flex: 1, minWidth: 150 },
  {
    field: 'amount',
    headerName: 'Amount',
    width: 110,
    type: 'rightAligned',
    valueFormatter: (p: ValueFormatterParams<InboxRow, number>) => (p.value == null ? '' : money(p.value)),
  },
  {
    field: 'ageHours',
    headerName: 'Age',
    width: 100,
    valueFormatter: (p: ValueFormatterParams<InboxRow, number>) => (p.value == null ? '' : hoursLabel(p.value)),
  },
  { field: 'action', headerName: 'Proposed action', flex: 2, minWidth: 220 },
  {
    field: 'status',
    headerName: 'Status',
    width: 140,
    valueFormatter: (p: ValueFormatterParams<InboxRow, DisplayStatus>) => (p.value ? STATUS_LABEL[p.value] : ''),
    cellClass: (p: CellClassParams<InboxRow, DisplayStatus>) => ['status-cell', `tone-${p.value ? STATUS_TONE[p.value] : 'neutral'}`],
  },
]

const defaultColDef: ColDef = { sortable: true, resizable: true }
const initialState: GridState = { sort: { sortModel: [{ colId: 'ageHours', sort: 'asc' }] } }
const getRowId = (p: GetRowIdParams<InboxRow>) => p.data.id

function toRows(disputes: Dispute[]): InboxRow[] {
  const now = Date.now()
  return disputes.map((d) => ({
    id: d.dispute_id,
    reason: reasonLabel(d.reason),
    amount: Number(d.dispute_amount.value),
    ageHours: ageHours(d.create_time, now),
    action: d.proposal ? resolutionLabel(d.proposal.decision.resolution) : 'Not analyzed yet',
    status: displayStatus(d.proposal),
  }))
}

interface Props {
  disputes: Dispute[]
  selectedId: string | null
  onSelect: (disputeId: string) => void
}

export function Inbox({ disputes, selectedId, onSelect }: Props) {
  const apiRef = useRef<GridApi<InboxRow> | null>(null)
  const rowData = useMemo(() => toRows(disputes), [disputes])

  // Light or dark grid follows the page (the page's CSS follows prefers-color-scheme).
  useEffect(() => {
    const query = window.matchMedia('(prefers-color-scheme: dark)')
    const apply = () => {
      document.documentElement.dataset.agThemeMode = query.matches ? 'dark' : 'light'
    }
    apply()
    query.addEventListener('change', apply)
    return () => query.removeEventListener('change', apply)
  }, [])

  // The open case is the selected row; this also covers a case opened from outside the grid (a new simulated dispute).
  useEffect(() => {
    apiRef.current?.forEachNode((node) => node.setSelected(node.data?.id === selectedId))
  }, [selectedId, rowData])

  const onGridReady = (event: GridReadyEvent<InboxRow>) => {
    apiRef.current = event.api
    event.api.forEachNode((node) => node.setSelected(node.data?.id === selectedId))
  }

  return (
    <div className="inbox-grid" data-testid="inbox">
      <AgGridProvider modules={modules}>
        <AgGridReact<InboxRow>
          theme={theme}
          rowData={rowData}
          columnDefs={columnDefs}
          defaultColDef={defaultColDef}
          rowSelection={rowSelection}
          getRowId={getRowId}
          onGridReady={onGridReady}
          onRowClicked={(e) => e.data && onSelect(e.data.id)}
          onCellKeyDown={(e) => {
            if ((e.event as KeyboardEvent | null)?.key === 'Enter' && e.data) onSelect(e.data.id)
          }}
          initialState={initialState}
          overlayNoRowsTemplate="No disputes yet."
        />
      </AgGridProvider>
    </div>
  )
}
