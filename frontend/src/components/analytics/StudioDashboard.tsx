import { useMemo } from 'react'
import { enableStudioDevValidations } from 'ag-studio'
import { AgStudio } from 'ag-studio-react'
import type { AnalyticsRow, AnalyticsSummary, DeadlineRow } from '../../types'
import { DASHBOARD_STATE, DASHBOARD_THEME, dashboardData } from './studioConfig'

// Development-only checks that log Studio configuration mistakes to the console. Production builds leave them out.
if (import.meta.env.DEV) enableStudioDevValidations()

// Studio fills its parent, so the parent (.analytics-frame in analytics.css) has the height.
const STUDIO_STYLE = { height: '100%', width: '100%' }

interface Props {
  rows: AnalyticsRow[]
  deadlines: DeadlineRow[]
  summary: AnalyticsSummary
}

export function StudioDashboard({ rows, deadlines, summary }: Props) {
  // Memoised: Studio resets its state whenever a prop changes reference.
  const data = useMemo(() => dashboardData(rows, deadlines, summary), [rows, deadlines, summary])
  return (
    <div className="analytics-frame">
      <AgStudio style={STUDIO_STYLE} data={data} initialState={DASHBOARD_STATE} theme={DASHBOARD_THEME} mode="view" />
    </div>
  )
}
