import { useId, useState } from 'react'
import type { AgReportState, AgStudioApi } from 'ag-studio'
import { MAX_VIEW_NAME, deleteView, listViews, saveView } from './savedViews'
import type { SavedView } from './savedViews'
import type { RebuttalRegistry } from './widgets'

interface Message {
  tone: 'status' | 'error'
  text: string
}

const SAVE_ERROR = 'Could not save the view. Browser storage is unavailable or full.'
const DELETE_ERROR = 'Could not delete the view. Browser storage is unavailable.'
const LOAD_ERROR = 'Could not load the view.'

interface Props {
  // Null until AG Studio reports that its API is ready.
  api: AgStudioApi<RebuttalRegistry> | null
}

// Toolbar for named Studio views. Views are kept in this browser only (see savedViews.ts).
export function SavedViews({ api }: Props) {
  // Read once on mount. Each save and delete then uses the list its storage call returns.
  const [views, setViews] = useState<SavedView[]>(() => listViews())
  const [selected, setSelected] = useState('')
  const [name, setName] = useState('')
  const [message, setMessage] = useState<Message | null>(null)
  const selectId = useId()
  const nameId = useId()
  const trimmedName = name.trim()

  function load() {
    const view = views.find((candidate) => candidate.name === selected)
    if (!api || !view) return
    try {
      // Stored state is only shape-checked on read, so setState may throw for a view Studio cannot use.
      api.setState(view.state as AgReportState<RebuttalRegistry>)
      setMessage({ tone: 'status', text: `Loaded "${view.name}".` })
    } catch {
      setMessage({ tone: 'error', text: LOAD_ERROR })
    }
  }

  function remove() {
    const next = deleteView(selected)
    if (!next) {
      setMessage({ tone: 'error', text: DELETE_ERROR })
      return
    }
    setViews(next)
    setSelected('')
    setMessage({ tone: 'status', text: `Deleted "${selected}".` })
  }

  function save() {
    if (!api) return
    const saved = saveView(trimmedName, api.getState())
    if (!saved) {
      setMessage({ tone: 'error', text: SAVE_ERROR })
      return
    }
    setViews(saved)
    setSelected(trimmedName)
    setName('')
    setMessage({ tone: 'status', text: `Saved "${trimmedName}".` })
  }

  return (
    <div className="saved-views" data-testid="saved-views">
      <label htmlFor={selectId} className="label">
        Saved view
      </label>
      <select id={selectId} value={selected} onChange={(event) => setSelected(event.target.value)}>
        <option value="">Choose a view</option>
        {views.map((view) => (
          <option key={view.name} value={view.name}>
            {view.name}
          </option>
        ))}
      </select>
      <button type="button" className="ghost" disabled={!api || selected === ''} onClick={load}>
        Load
      </button>
      <button type="button" className="ghost" disabled={selected === ''} onClick={remove}>
        Delete
      </button>
      <label htmlFor={nameId} className="label">
        View name
      </label>
      <input
        id={nameId}
        type="text"
        maxLength={MAX_VIEW_NAME}
        value={name}
        onChange={(event) => setName(event.target.value)}
      />
      <button type="button" className="ghost" disabled={!api || trimmedName === ''} onClick={save}>
        Save view
      </button>
      {message?.tone === 'error' && (
        <p role="alert" className="error">
          {message.text}
        </p>
      )}
      {message?.tone === 'status' && (
        <p role="status" className="note">
          {message.text}
        </p>
      )}
    </div>
  )
}
