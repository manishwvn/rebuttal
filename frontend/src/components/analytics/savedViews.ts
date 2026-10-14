// Saved AG Studio dashboard views, kept per browser in localStorage. Every read and write tolerates a missing,
// blocked or throwing store, so the dashboard still renders without one.

export const SAVED_VIEWS_KEY = 'rebuttal.studio.views.v1'
export const MAX_VIEW_NAME = 40

export interface SavedView<S extends object = object> {
  name: string
  state: S
}

export type ViewStore = Pick<Storage, 'getItem' | 'setItem'>

export function browserStore(): ViewStore | null {
  try {
    return typeof window === 'undefined' ? null : window.localStorage
  } catch {
    return null
  }
}

function isSavedView(value: unknown): value is SavedView {
  if (typeof value !== 'object' || value === null) return false
  const { name, state } = value as Partial<Record<keyof SavedView, unknown>>
  return (
    typeof name === 'string' &&
    name.length > 0 &&
    typeof state === 'object' &&
    state !== null &&
    Array.isArray((state as { pages?: unknown }).pages)
  )
}

// Null when the store cannot be read, so a save or delete never overwrites views it could not see.
function readViews(store: ViewStore): SavedView[] | null {
  let raw: string | null
  try {
    raw = store.getItem(SAVED_VIEWS_KEY)
  } catch {
    return null
  }
  try {
    const parsed: unknown = JSON.parse(raw ?? '[]')
    return Array.isArray(parsed) ? parsed.filter(isSavedView) : []
  } catch {
    return []
  }
}

export function listViews<S extends object = object>(store: ViewStore | null = browserStore()): SavedView<S>[] {
  const views = store ? readViews(store) : null
  return (views ?? []) as SavedView<S>[]
}

// Returns a parsed copy of what was written, so callers never hold the objects they passed in.
function write<S extends object>(store: ViewStore, views: SavedView[]): SavedView<S>[] | null {
  try {
    const json = JSON.stringify(views)
    store.setItem(SAVED_VIEWS_KEY, json)
    return JSON.parse(json) as SavedView<S>[]
  } catch {
    return null
  }
}

export function saveView<S extends object>(
  name: string,
  state: S,
  store: ViewStore | null = browserStore(),
): SavedView<S>[] | null {
  const trimmed = name.trim()
  if (!store || trimmed.length === 0 || trimmed.length > MAX_VIEW_NAME || !isSavedView({ name: trimmed, state })) {
    return null
  }
  const views = readViews(store)
  if (!views) return null
  const next: SavedView[] = views.some((view) => view.name === trimmed)
    ? views.map((view) => (view.name === trimmed ? { name: trimmed, state } : view))
    : [...views, { name: trimmed, state }]
  return write<S>(store, next)
}

export function deleteView(name: string, store: ViewStore | null = browserStore()): SavedView[] | null {
  if (!store) return null
  const views = readViews(store)
  if (!views) return null
  if (!views.some((view) => view.name === name)) return views
  return write(store, views.filter((view) => view.name !== name))
}
