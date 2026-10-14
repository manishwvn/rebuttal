import { expect, test, type Page } from '@playwright/test'

// Saved views are kept in the browser: localStorage holds a JSON array of { name, state }, where state is the AG Studio
// report state. The UI is frontend/src/components/analytics/SavedViews.tsx, shown on the Analytics tab.
const VIEWS_KEY = 'rebuttal.studio.views.v1'

// Copied from analytics.spec.ts: AG Studio prints its unlicensed-use banner as console errors. Only those are ignored.
const isLicenceBanner = (text: string) =>
  /licen/i.test(text) || /^\*+$/.test(text.trim()) || /AG Studio Core|unlocked for trial|watermark/.test(text)

// Copied from analytics.spec.ts style: a Studio widget caption, found by its text.
const caption = (page: Page, text: RegExp) => page.locator('.ag-studio-layout-widget-caption', { hasText: text })

const viewSelect = (page: Page) => page.getByLabel('Saved view', { exact: true })

const viewOption = (page: Page, name: string) => viewSelect(page).getByRole('option', { name, exact: true })

const button = (page: Page, name: string) => page.getByRole('button', { name, exact: true })

async function openAnalytics(page: Page) {
  await page.goto('/#analytics')
  await expect(page.getByTestId('saved-views')).toBeVisible()
  await expect(caption(page, /^Disputes$/)).toBeVisible()
}

async function saveView(page: Page, name: string) {
  await page.getByLabel('View name', { exact: true }).fill(name)
  await button(page, 'Save view').click()
}

async function storedViews(page: Page): Promise<unknown> {
  const raw = await page.evaluate((key) => localStorage.getItem(key), VIEWS_KEY)
  return JSON.parse(raw ?? 'null')
}

test('a saved view survives a reload and can be deleted', async ({ page }) => {
  await openAnalytics(page)
  await saveView(page, 'Weekly review')
  await expect(page.getByRole('status')).toHaveText('Saved "Weekly review".')
  await expect(viewOption(page, 'Weekly review')).toHaveCount(1)

  await page.reload()
  await expect(viewOption(page, 'Weekly review')).toHaveCount(1)
  await viewSelect(page).selectOption('Weekly review')
  await button(page, 'Delete').click()
  await expect(page.getByRole('status')).toHaveText('Deleted "Weekly review".')
  await expect(viewOption(page, 'Weekly review')).toHaveCount(0)
  expect(await storedViews(page)).toEqual([])
})

test('loading a saved view restores its layout state', async ({ page }) => {
  await openAnalytics(page)
  await saveView(page, 'Edited')
  await expect(page.getByRole('status')).toHaveText('Saved "Edited".')

  // Change the saved Disputes caption in storage, then reload so the page reads the edited view back.
  await page.evaluate((key) => {
    const views = JSON.parse(localStorage.getItem(key) ?? '[]')
    views[0].state.pages[0].widgets['kpi-disputes'].format.caption.text = 'My disputes'
    localStorage.setItem(key, JSON.stringify(views))
  }, VIEWS_KEY)
  await page.reload()
  await expect(caption(page, /^Disputes$/)).toBeVisible()

  await viewSelect(page).selectOption('Edited')
  await button(page, 'Load').click()
  await expect(caption(page, /^My disputes$/)).toBeVisible()
  await expect(caption(page, /^Disputes$/)).toHaveCount(0)
  await expect(page.getByRole('status')).toHaveText('Loaded "Edited".')
})

test('a loaded view stays applied when the assistant is opened and closed', async ({ page }) => {
  await page.route('**/api/studio/ai/status', (route) => route.fulfill({ json: { enabled: true } }))
  await openAnalytics(page)
  await saveView(page, 'Kept')
  await expect(page.getByRole('status')).toHaveText('Saved "Kept".')
  await page.evaluate((key) => {
    const views = JSON.parse(localStorage.getItem(key) ?? '[]')
    views[0].state.pages[0].widgets['kpi-disputes'].format.caption.text = 'My disputes'
    localStorage.setItem(key, JSON.stringify(views))
  }, VIEWS_KEY)
  await page.reload()
  await viewSelect(page).selectOption('Kept')
  await button(page, 'Load').click()
  await expect(caption(page, /^My disputes$/)).toBeVisible()

  // Switching Studio to edit mode and back must not rebuild the dashboard from its default state.
  await button(page, 'Ask the assistant').click()
  await expect(page.getByText('AI Assistant', { exact: true })).toBeVisible()
  await button(page, 'Back to dashboard').click()
  await expect(caption(page, /^My disputes$/)).toBeVisible()
  await expect(viewSelect(page)).toHaveValue('Kept')
})

test('a blocked storage shows an error instead of crashing', async ({ page }) => {
  await page.addInitScript(() => {
    Storage.prototype.setItem = () => {
      throw new DOMException('full', 'QuotaExceededError')
    }
  })
  const errors: string[] = []
  page.on('console', (m) => {
    if (m.type() === 'error' && !isLicenceBanner(m.text())) errors.push(m.text())
  })
  page.on('pageerror', (e) => errors.push(e.message))

  await openAnalytics(page)
  await saveView(page, 'Blocked')
  await expect(page.getByRole('alert').filter({ hasText: 'Could not save the view.' })).toHaveText(
    'Could not save the view. Browser storage is unavailable or full.',
  )
  expect(errors).toEqual([])
})

test('corrupt saved data is ignored', async ({ page }) => {
  await page.addInitScript((key) => {
    if (localStorage.getItem(key) === null) localStorage.setItem(key, '{not json')
  }, VIEWS_KEY)

  await openAnalytics(page)
  await expect(viewSelect(page).locator('option')).toHaveText(['Choose a view'])
  await expect(caption(page, /^Disputes$/)).toBeVisible()
})
