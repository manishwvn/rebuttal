import { expect, test, type Page } from '@playwright/test'

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

test('the inbox grid is a named region', async ({ page }) => {
  await page.goto('/')
  await expect(page.getByRole('region', { name: 'Disputes inbox' })).toBeVisible()
})

test('Enter on a focused inbox row opens its case', async ({ page }) => {
  const disputeId = await createDispute(page)
  // A reload opens no case, so the keyboard is the only way to open this one.
  await page.reload()
  await expect(page.getByText('Pick a dispute in the inbox to see what the agent proposes.')).toBeVisible()
  await page.locator(`[row-id="${disputeId}"] [col-id="id"]`).focus()
  await page.keyboard.press('Enter')
  await expect(page.getByTestId('case-view')).toBeVisible()
})

test('Space on a focused inbox row opens its case', async ({ page }) => {
  const disputeId = await createDispute(page)
  await page.reload()
  await expect(page.getByText('Pick a dispute in the inbox to see what the agent proposes.')).toBeVisible()
  await page.locator(`[row-id="${disputeId}"] [col-id="id"]`).focus()
  await page.keyboard.press(' ')
  await expect(page.getByTestId('case-view')).toBeVisible()
})
