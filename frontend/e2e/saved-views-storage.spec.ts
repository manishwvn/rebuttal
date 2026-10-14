import { expect, test } from '@playwright/test'
import { MAX_VIEW_NAME, SAVED_VIEWS_KEY, deleteView, listViews, saveView } from '../src/components/analytics/savedViews.ts'
import type { ViewStore } from '../src/components/analytics/savedViews.ts'

// Pure storage tests: no page and no browser. The fake store is a Map, and writes are counted.
function fakeStore(seed?: string) {
  const data = new Map<string, string>(seed === undefined ? [] : [[SAVED_VIEWS_KEY, seed]])
  let writes = 0
  const store: ViewStore = {
    getItem: (key) => data.get(key) ?? null,
    setItem: (key, value) => {
      writes += 1
      data.set(key, value)
    },
  }
  return { store, writes: () => writes }
}

function layout(status: string) {
  return { pages: [{ id: 'disputes' }], filters: { status } }
}

test('a saved view lists back with its name and a deep copy of its state', () => {
  const { store } = fakeStore()
  const state = layout('open')
  saveView('  Open cases  ', state, store)
  state.filters.status = 'closed'
  expect(listViews(store)).toEqual([{ name: 'Open cases', state: layout('open') }])
})

test('saving an existing name replaces it in place and a new name appends', () => {
  const { store } = fakeStore()
  saveView('Morning', layout('open'), store)
  saveView('Week', layout('won'), store)
  const views = saveView('Morning', layout('lost'), store)
  expect(views?.map((view) => view.name)).toEqual(['Morning', 'Week'])
  expect(listViews(store)).toEqual([
    { name: 'Morning', state: layout('lost') },
    { name: 'Week', state: layout('won') },
  ])
})

test('names are trimmed and empty or over-long names are refused without a write', () => {
  const { store, writes } = fakeStore()
  expect(saveView('   ', layout('open'), store)).toBeNull()
  expect(saveView('x'.repeat(MAX_VIEW_NAME + 1), layout('open'), store)).toBeNull()
  expect(writes()).toBe(0)
  expect(saveView('x'.repeat(MAX_VIEW_NAME), layout('open'), store)).not.toBeNull()
})

test('delete removes only the named view, and an unknown name is a no-op that does not write', () => {
  const { store, writes } = fakeStore()
  saveView('A', layout('open'), store)
  saveView('B', layout('won'), store)
  const writesBefore = writes()
  expect(deleteView('Missing', store)?.map((view) => view.name)).toEqual(['A', 'B'])
  expect(writes()).toBe(writesBefore)
  expect(deleteView('A', store)?.map((view) => view.name)).toEqual(['B'])
  expect(listViews(store).map((view) => view.name)).toEqual(['B'])
})

test('corrupt JSON, non-array JSON and invalid entries are dropped without throwing', () => {
  expect(listViews(fakeStore('{not json').store)).toEqual([])
  expect(listViews(fakeStore('{"name":"x"}').store)).toEqual([])
  const entries = [
    { name: 'ok', state: { pages: [] } },
    { name: '', state: { pages: [] } },
    { state: { pages: [] } },
    { name: 'no state' },
    { name: 'no pages', state: {} },
    null,
    'text',
    { name: 'also ok', state: { pages: [1] } },
  ]
  expect(listViews(fakeStore(JSON.stringify(entries)).store).map((view) => view.name)).toEqual(['ok', 'also ok'])
})

test('a null store lists nothing and refuses to save or delete', () => {
  expect(listViews(null)).toEqual([])
  expect(saveView('Morning', layout('open'), null)).toBeNull()
  expect(deleteView('Morning', null)).toBeNull()
})

test('a store whose setItem throws refuses to save or delete and keeps the previous list', () => {
  const seeded = JSON.stringify([{ name: 'A', state: layout('open') }])
  const store: ViewStore = {
    getItem: () => seeded,
    setItem: () => {
      throw new Error('QuotaExceededError')
    },
  }
  expect(saveView('B', layout('won'), store)).toBeNull()
  expect(deleteView('A', store)).toBeNull()
  expect(listViews(store)).toEqual([{ name: 'A', state: layout('open') }])
})

test('a store whose getItem throws lists nothing', () => {
  const store: ViewStore = {
    getItem: () => {
      throw new Error('access denied')
    },
    setItem: () => {},
  }
  expect(listViews(store)).toEqual([])
})

test('a store whose getItem throws refuses to save or delete, so no view is overwritten', () => {
  let writes = 0
  const store: ViewStore = {
    getItem: () => {
      throw new Error('access denied')
    },
    setItem: () => {
      writes += 1
    },
  }
  expect(saveView('B', layout('won'), store)).toBeNull()
  expect(deleteView('A', store)).toBeNull()
  expect(writes).toBe(0)
})

test('a state without a pages array is refused without a write', () => {
  const { store, writes } = fakeStore()
  expect(saveView('Bare', {}, store)).toBeNull()
  expect(saveView('Odd', { pages: 'disputes' }, store)).toBeNull()
  expect(writes()).toBe(0)
  expect(listViews(store)).toEqual([])
})
