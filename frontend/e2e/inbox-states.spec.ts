import { expect, test, type Page } from '@playwright/test'
import { inboxCell } from './inbox-rows.js'

// The inbox says what it is doing: while the first load is in flight it shows 'Loading disputes…' (never 'No disputes
// yet.'), an empty inbox gives the next step, the grid is a named region, and Enter or Space opens the focused row.

const DISPUTES = '**/api/disputes'

// Creates a dispute with the simulator and returns its id. Creating it also opens its case.
async function createDispute(page: Page): Promise<string> {
  await page.goto('/')
  await expect(page.getByTestId('mode-badge')).toContainText('mock')
  await page.getByLabel('Case').selectOption('inr_no_tracking')
  await page.getByRole('button', { name: 'Create dispute' }).click()
  const caseView = page.getByTestId('case-view')
  await expect(caseView).toBeVisible()
  return (await caseView.locator('.case-head .mono').innerText()).split(' ')[0]
}

test('while the first inbox load is in flight the grid shows Loading, not No disputes yet', async ({ page }) => {
  let release!: () => void
  const gate = new Promise<void>((resolve) => (release = resolve))
  let held = false
  await page.route(DISPUTES, async (route) => {
    if (route.request().method() === 'OPTIONS') return route.continue()
    if (!held) {
      held = true
      await gate
    }
    return route.continue()
  })
  try {
    await page.goto('/')
    await expect(page.getByRole('status').filter({ hasText: 'Loading disputes…' })).toBeVisible()
    await expect(page.getByTestId('inbox')).toContainText('Loading disputes…')
    await expect(page.locator('body')).not.toContainText('No disputes yet.')

    release()
    await expect(page.locator('body')).not.toContainText('Loading disputes…')
  } finally {
    release()
    await page.unroute(DISPUTES)
  }
})

test('an empty inbox says no disputes yet and gives the next step', async ({ page }) => {
  await page.route(DISPUTES, (route) => {
    if (route.request().method() === 'OPTIONS') return route.continue()
    return route.fulfill({
      status: 200,
      contentType: 'application/json',
      headers: { 'Access-Control-Allow-Origin': '*' },
      body: '[]',
    })
  })
  try {
    await page.goto('/')
    await expect(page.getByTestId('inbox')).toContainText('No disputes yet.')
    await expect(page.getByText('Use the simulator above to create one')).toBeVisible()
    await expect(page.getByText('Pick a dispute in the inbox')).toHaveCount(0)
  } finally {
    await page.unroute(DISPUTES)
  }
})

test('a failed first inbox load shows the error, and a Retry that finds no disputes shows the No disputes yet overlay', async ({ page }) => {
  let gets = 0
  await page.route(DISPUTES, (route) => {
    if (route.request().method() === 'OPTIONS') return route.continue()
    gets += 1
    if (gets === 1) {
      return route.fulfill({
        status: 500,
        contentType: 'application/json',
        headers: { 'Access-Control-Allow-Origin': '*' },
        body: JSON.stringify({ detail: 'inbox down in this test' }),
      })
    }
    if (gets === 2) {
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        headers: { 'Access-Control-Allow-Origin': '*' },
        body: '[]',
      })
    }
    return route.continue()
  })
  try {
    await page.goto('/')
    await expect(page.getByTestId('app-error')).toContainText('inbox down in this test')
    await expect(page.getByTestId('inbox')).not.toContainText('No disputes yet.')
    await expect(page.getByTestId('inbox')).not.toContainText('Loading disputes…')
    await expect(page.getByTestId('inbox-retry')).toBeVisible()

    // The Retry loads an empty inbox: suppressOverlays goes back to none at runtime, so the grid's No disputes yet
    // overlay must reappear (it was suppressed while the load failed).
    await page.getByTestId('inbox-retry').click()
    await expect(page.getByTestId('app-error')).toHaveCount(0)
    await expect(page.getByTestId('inbox')).toContainText('No disputes yet.')
    await expect(page.getByTestId('inbox')).not.toContainText('Loading disputes…')
  } finally {
    await page.unroute(DISPUTES)
  }
})

test('the inbox grid is a named region', async ({ page }) => {
  await page.goto('/')
  await expect(page.getByRole('region', { name: 'Disputes inbox' })).toBeVisible()
})

test('Enter on a focused inbox row opens its case', async ({ page }) => {
  const disputeId = await createDispute(page)
  // A reload opens no case, so the keyboard is the only way to open this one.
  await page.reload()
  await expect(page.getByText('Pick a dispute in the inbox to see what the agent proposes.')).toBeVisible()
  await (await inboxCell(page, disputeId, 'id')).focus()
  await page.keyboard.press('Enter')
  await expect(page.getByTestId('case-view')).toBeVisible()
})

test('Space on a focused inbox row opens its case', async ({ page }) => {
  const disputeId = await createDispute(page)
  await page.reload()
  await expect(page.getByText('Pick a dispute in the inbox to see what the agent proposes.')).toBeVisible()
  await (await inboxCell(page, disputeId, 'id')).focus()
  await page.keyboard.press(' ')
  await expect(page.getByTestId('case-view')).toBeVisible()
})

test('at phone width the simulator card keeps its controls inside the page', async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 812 })
  await page.goto('/')
  const create = page.getByRole('button', { name: 'Create dispute' })
  await expect(create).toBeVisible()
  const box = await create.boundingBox()
  expect(box!.x + box!.width).toBeLessThanOrEqual(375)
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true)
})

test('the inbox grid follows the OS colour scheme', async ({ page }) => {
  await page.emulateMedia({ colorScheme: 'dark' })
  await page.goto('/')
  await expect(page.getByTestId('inbox')).toBeVisible()
  await expect(page.locator('html')).toHaveAttribute('data-ag-theme-mode', 'dark')
  await page.emulateMedia({ colorScheme: 'light' })
  await expect(page.locator('html')).toHaveAttribute('data-ag-theme-mode', 'light')
})
