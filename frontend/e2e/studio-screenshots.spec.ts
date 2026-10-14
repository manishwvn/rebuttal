import { expect, test, type Locator, type Page } from '@playwright/test'

// Not part of the regular run: SCREENSHOTS=1 npx playwright test studio-screenshots writes one PNG per Studio widget
// and one for the assistant panel into docs/screenshots. Needs the backend in mock mode (see playwright.config.ts).
test.skip(!process.env.SCREENSHOTS, 'set SCREENSHOTS=1 to regenerate docs/screenshots')

// Copied from analytics.spec.ts: simulates a case from the Desk and returns the new dispute id.
async function simulate(page: Page, caseId: string): Promise<string> {
  await page.goto('/')
  await expect(page.getByTestId('mode-badge')).toContainText('mock')
  await page.getByLabel('Case').selectOption(caseId)
  await page.getByRole('button', { name: 'Create dispute' }).click()
  const caseView = page.getByTestId('case-view')
  await expect(caseView).toBeVisible()
  const disputeId = (await caseView.locator('.case-head .mono').innerText()).split(' ')[0]
  expect(disputeId).toMatch(/^PP-D-\d+$/)
  return disputeId
}

// Copied from analytics.spec.ts: two cases on the desk. The first is approved, so the summary has an executed
// dispute; the second stays pending.
async function createCases(page: Page) {
  await simulate(page, 'agent_wrong_size')
  await page.getByTestId('case-view').getByRole('button', { name: 'Approve' }).click()
  const dialog = page.getByRole('dialog')
  await dialog.getByRole('button', { name: 'Approve and send' }).click()
  await expect(page.getByTestId('case-status')).toHaveText('Executed')
  await simulate(page, 'inr_no_tracking')
}

// The card around a built-in KPI widget, found by its caption (the caption sits in the card's footer).
const kpiCard = (page: Page, caption: RegExp) =>
  page.locator('.ag-studio-layout-widget-container', {
    has: page.locator('.ag-studio-layout-widget-caption', { hasText: caption }),
  })

// The custom widgets carry data-widget-id equal to their dashboard id. Their card is the Studio container around them.
const customCard = (page: Page, id: string) =>
  page
    .locator(`[data-widget-id="${id}"]`)
    .locator('xpath=ancestor::*[contains(@class,"ag-studio-layout-widget-container")][1]')

// The deadlines list scrolls inside its card: studioConfig.ts gives the card ySpan 14 (224px), which fits about four
// rows, so the fifth is cut off. For this screenshot only, the card and its list grow to the list's full height so
// every row shows. The grid layout itself is unchanged. Remove this once studioConfig.ts gives the card enough height.
async function fitDeadlineRows(page: Page) {
  // Each element from the list up to the Studio widget frame gets the list's overflow added to its height. The Studio
  // wrappers are absolutely positioned, so auto heights would collapse them instead of growing the card.
  await page.locator('[data-widget-id="deadlines"]').evaluate((list) => {
    const extra = list.scrollHeight - list.clientHeight
    let el: HTMLElement | null = list as HTMLElement
    while (el) {
      el.style.height = `${el.getBoundingClientRect().height + extra}px`
      if (el.classList.contains('ag-studio-layout-widget')) break
      el = el.parentElement
    }
  })
  const cardBox = await customCard(page, 'deadlines').boundingBox()
  const rowBox = await page.locator('[data-widget-id="deadlines"]').getByTestId('deadline-row').last().boundingBox()
  expect(cardBox).not.toBeNull()
  expect(rowBox).not.toBeNull()
  expect(rowBox!.y + rowBox!.height).toBeLessThanOrEqual(cardBox!.y + cardBox!.height)
}

// One entry per widget on the Overview page (studioConfig.ts DASHBOARD_STATE). The file name is studio-<id>.png.
const WIDGETS: { id: string; card: (page: Page) => Locator; before?: (page: Page) => Promise<void> }[] = [
  { id: 'kpi-disputes', card: (page) => kpiCard(page, /^Disputes$/) },
  { id: 'kpi-disputed', card: (page) => kpiCard(page, /^Disputed \$$/) },
  { id: 'kpi-refunded', card: (page) => kpiCard(page, /^Refunded \$$/) },
  { id: 'kpi-kept', card: (page) => kpiCard(page, /^Kept \$$/) },
  { id: 'agreement', card: (page) => customCard(page, 'agreement') },
  { id: 'bar-reason', card: (page) => customCard(page, 'bar-reason') },
  { id: 'money-split', card: (page) => customCard(page, 'money-split') },
  { id: 'bar-product', card: (page) => customCard(page, 'bar-product') },
  { id: 'deadlines', card: (page) => customCard(page, 'deadlines'), before: fitDeadlineRows },
]

test('screenshot every Studio widget', async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 1100 })
  await page.emulateMedia({ colorScheme: 'light' })
  await createCases(page)

  await page.goto('/#analytics')
  await expect(kpiCard(page, /^Disputed \$$/).locator('.ag-studio-value-widget-content')).not.toBeEmpty()
  await expect(page.locator('[data-widget-id="deadlines"]').getByTestId('deadline-row').first()).toBeVisible()
  await expect(page.locator('[data-widget-id="money-split"]').getByTestId('money-part').first()).toBeVisible()
  await expect(page.locator('[data-widget-id="bar-reason"]').getByTestId('bar-row').first()).toBeVisible()
  await expect(page.locator('[data-widget-id="bar-product"]').getByTestId('bar-row').first()).toBeVisible()
  await page.waitForTimeout(800) // let the charts finish their entrance animation

  for (const { id, card, before } of WIDGETS) {
    await before?.(page)
    await card(page).screenshot({ path: `../docs/screenshots/studio-${id}.png` })
  }
})

// With the AI proxy reported enabled, Studio mounts with the assistant harness. The status route is stubbed and any
// POST to the proxy is aborted, so no model runs.
test('screenshot the Studio assistant panel', async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 1100 })
  await page.emulateMedia({ colorScheme: 'light' })
  await page.route('**/api/studio/ai/status', (route) => route.fulfill({ json: { enabled: true } }))
  await page.route('**/api/studio/ai', (route) =>
    route.request().method() === 'POST' ? route.abort() : route.continue(),
  )
  await createCases(page)

  await page.goto('/#analytics')
  await page.getByRole('button', { name: 'Ask the assistant' }).click()
  await expect(page.getByText('AI Assistant', { exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Top disputed products' })).toBeVisible()
  await page.screenshot({ path: '../docs/screenshots/studio-assistant.png' })
})
