import { expect, test, type Page } from '@playwright/test'

// The Analytics tab must show the numbers the API reports. The backend is shared by every spec in a run, so nothing
// here assumes absolute counts: each expectation is computed from the analytics API response.
// Needs the backend's GET /api/analytics/{rows,summary,deadlines} (mock mode, see playwright.config.ts).
const API = 'http://localhost:8000'

// Copied from dispute-flow.spec.ts: simulates a case from the Desk and returns the new dispute id.
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

// Two cases on the desk. The first is approved, so the summary has an executed dispute; the second stays pending.
async function createCases(page: Page) {
  await simulate(page, 'agent_wrong_size')
  await page.getByTestId('case-view').getByRole('button', { name: 'Approve' }).click()
  const dialog = page.getByRole('dialog')
  await dialog.getByRole('button', { name: 'Approve and send' }).click()
  await expect(page.getByTestId('case-status')).toHaveText('Executed')
  await simulate(page, 'inr_no_tracking')
}

// AG Studio prints its unlicensed-use banner as console errors: one line says "License", and the rule lines and the
// text lines around it do not. Those lines are the only console errors ignored.
const isLicenceBanner = (text: string) =>
  /licen/i.test(text) || /^\*+$/.test(text.trim()) || /AG Studio Core|unlocked for trial|watermark/.test(text)

// Studio renders each widget as .ag-studio-layout-widget. Its caption is in the footer and its value text is in
// .ag-studio-value-widget-content (DOM text, not canvas). Scoping by caption keeps repeated values apart: $48.00 is
// both the Refunded KPI and a deadline row.
const kpi = (page: Page, caption: RegExp) =>
  page
    .locator('.ag-studio-layout-widget', { has: page.locator('.ag-studio-layout-widget-caption', { hasText: caption }) })
    .locator('.ag-studio-value-widget-content')

// Formatted the way the dashboard's $#,##0.00 format prints money.
const usd = (n: number) => `$${n.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`

test('analytics shows the numbers the API reports', async ({ page, request }) => {
  await createCases(page)

  // Only errors from the Analytics tab count; the Desk is covered by its own specs.
  const errors: string[] = []
  page.on('console', (m) => {
    if (m.type() === 'error' && !isLicenceBanner(m.text())) errors.push(m.text())
  })
  page.on('pageerror', (e) => errors.push(e.message))

  await page.getByRole('tab', { name: 'Analytics' }).click()
  await expect(page).toHaveURL(/#analytics$/)

  // The truth comes from the API.
  const summary = await (await request.get(`${API}/api/analytics/summary`)).json()
  const deadlines = await (await request.get(`${API}/api/analytics/deadlines`)).json()
  const { totals, money, agreement } = summary

  // Status line: "3 disputes · 2 analyzed · 1 executed" (the singular only for one dispute).
  const noun = totals.disputes === 1 ? 'dispute' : 'disputes'
  await expect(page.getByTestId('analytics-status')).toHaveText(
    `${totals.disputes} ${noun} · ${totals.analyzed} analyzed · ${totals.executed} executed`,
  )

  // KPI values, formatted as the dashboard formats them: counts as integers, money as $#,##0.00.
  await expect(kpi(page, /^Disputes$/)).toHaveText(totals.disputes.toLocaleString('en-US'))
  await expect(kpi(page, /^Disputed \$$/)).toHaveText(usd(money.disputed))
  await expect(kpi(page, /^Refunded \$$/)).toHaveText(usd(money.refunded))
  await expect(kpi(page, /^Kept \$$/)).toHaveText(usd(money.kept))
  // The rate is 0..1; the dashboard shows percentage points to one decimal, and 0 when nothing was compared.
  const agreementPct = agreement.rate === null ? 0 : Math.round(agreement.rate * 1000) / 10
  await expect(kpi(page, /^Model vs final agreement$/)).toHaveText(`${agreementPct.toFixed(1)}%`)

  // Deadlines grid. AG Grid virtualises rows, so the DOM can hold fewer rows than the API returns; aria-rowcount
  // carries the total, counting the header row. The second case is still open with a due date, so the list is not
  // empty.
  expect(deadlines.length).toBeGreaterThan(0)
  const grid = page.locator('.analytics [role="grid"]')
  await expect(grid).toHaveAttribute('aria-rowcount', String(deadlines.length + 1))
  // Sorted by hours_left, most urgent first: the first data row is the first deadline.
  await expect(grid.locator('[role="row"][row-index="0"]')).toContainText(deadlines[0].dispute_id)

  expect(errors).toEqual([])
})

test('analytics screenshot for the PR', async ({ page }) => {
  test.skip(!process.env.SCREENSHOTS, 'set SCREENSHOTS=1 to regenerate docs/screenshots')
  await page.setViewportSize({ width: 1280, height: 1100 })
  await page.emulateMedia({ colorScheme: 'light' })
  await page.goto('/')
  await createCases(page)

  await page.goto('/#analytics')
  await expect(kpi(page, /^Disputed \$$/)).not.toBeEmpty()
  await expect(page.locator('.analytics [role="grid"] [role="row"][row-index="0"]')).toBeVisible()
  await expect(page.getByText('Kept vs refunded by product', { exact: true })).toBeVisible()
  await page.waitForTimeout(800) // let the charts finish their entrance animation
  await page.screenshot({ path: '../docs/screenshots/analytics.png', fullPage: true })
})
