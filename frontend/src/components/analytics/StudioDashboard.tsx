import { useCallback, useEffect, useMemo, useState } from 'react'
import { AgStudioAiModule, createAiHarness, enableStudioDevValidations } from 'ag-studio'
import type { AgAiPromptStarter, AgStudioApi, AgStudioApiReadyEvent } from 'ag-studio'
import { AgStudio, AgStudioProvider } from 'ag-studio-react'
import { api } from '../../api'
import type { AnalyticsRow, AnalyticsSummary, DeadlineRow } from '../../types'
// The extension is explicit: on a case-insensitive disk './SavedViews' would resolve to savedViews.ts first.
import { SavedViews } from './SavedViews.tsx'
import { DASHBOARD_STATE, DASHBOARD_THEME, dashboardData } from './studioConfig'
import { createProxyAdapter } from './studioAiAdapter'
import { RB_WIDGETS, type RebuttalRegistry } from './widgets'

// Development-only checks that log Studio configuration mistakes to the console. Production builds leave them out.
if (import.meta.env.DEV) enableStudioDevValidations()

// Studio fills its parent, so the parent (.analytics-frame in analytics.css) has the height.
const STUDIO_STYLE = { height: '100%', width: '100%' }

const STUDIO_AI_MODULES = [AgStudioAiModule]

// One adapter for the page: it only forwards turns to the read-only backend proxy (POST /api/studio/ai).
const STUDIO_AI_ADAPTER = createProxyAdapter(api.studioAi)

const PROMPT_STARTERS: AgAiPromptStarter[] = [
  { label: 'Top disputed products', prompt: 'Which products have the most disputes?' },
  { label: 'Why buyers dispute', prompt: 'What are the main reasons buyers open disputes?' },
  { label: 'Money at risk', prompt: 'How much money is at risk in open disputes?' },
  { label: 'Deadlines', prompt: 'Which disputes have the nearest response deadlines?' },
]

interface Props {
  rows: AnalyticsRow[]
  deadlines: DeadlineRow[]
  summary: AnalyticsSummary
}

export function StudioDashboard({ rows, deadlines, summary }: Props) {
  // Memoised: Studio resets its state whenever a prop changes reference.
  const data = useMemo(() => dashboardData(rows, deadlines, summary), [rows, deadlines, summary])
  // Studio reads `ai` once, when it is created, so Studio mounts only after the proxy status is known. A failed
  // status call (proxy off, signed out) means no assistant; the dashboard itself is unaffected.
  const [aiEnabled, setAiEnabled] = useState<boolean | null>(null)
  useEffect(() => {
    let current = true
    api
      .studioAiStatus()
      .then((status) => current && setAiEnabled(status.enabled === true))
      .catch(() => current && setAiEnabled(false))
    return () => {
      current = false
    }
  }, [])
  // Studio shows the AI panel in edit mode only (AgEditModePanelType includes 'ai'; the view-mode panels are filters
  // only). So the assistant is opened by switching Studio to edit mode; the dashboard is read-only otherwise.
  const [asking, setAsking] = useState(false)
  // Studio passes its API once, in onApiReady. The saved-views toolbar needs it to read and set Studio's state.
  const [studioApi, setStudioApi] = useState<AgStudioApi<RebuttalRegistry> | null>(null)
  const onApiReady = useCallback(
    ({ api: readyApi }: AgStudioApiReadyEvent) => setStudioApi(readyApi as AgStudioApi<RebuttalRegistry>),
    [],
  )
  if (aiEnabled === null) {
    return (
      <div className="analytics-frame analytics-frame--loading" role="status" aria-label="Loading dashboard">
        <p className="note loading">Loading dashboard…</p>
      </div>
    )
  }

  return (
    <>
      <div className="studio-toolbar">
        {aiEnabled && (
          <button type="button" className="ghost studio-ai-toggle" aria-pressed={asking} onClick={() => setAsking((on) => !on)}>
            {asking ? 'Back to dashboard' : 'Ask the assistant'}
          </button>
        )}
        <SavedViews api={studioApi} />
      </div>
      <div className="analytics-frame">
        <AgStudioProvider modules={aiEnabled ? STUDIO_AI_MODULES : []}>
          <AgStudio<RebuttalRegistry>
            style={STUDIO_STYLE}
            data={data}
            initialState={DASHBOARD_STATE}
            theme={DASHBOARD_THEME}
            widgets={RB_WIDGETS}
            mode={asking ? 'edit' : 'view'}
            ai={
              aiEnabled
                ? ({ api: aiStudioApi }) =>
                    createAiHarness(aiStudioApi, { adapter: STUDIO_AI_ADAPTER, promptStarters: PROMPT_STARTERS })
                : undefined
            }
            onApiReady={onApiReady}
          />
        </AgStudioProvider>
      </div>
    </>
  )
}
