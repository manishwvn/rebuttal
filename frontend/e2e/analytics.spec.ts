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

// The custom widgets (frontend/src/components/analytics/widgets/) each carry data-widget-id equal to their dashboard id.
const widget = (page: Page, id: string) => page.locator(`[data-widget-id="${id}"]`)

// The agreement rate as a percentage with one decimal, or n/a when no decision was compared.
const pct = (rate: number) => `${(Math.round(rate * 1000) / 10).toFixed(1)}%`

// The agreement detail line, worded as the dashboard words it.
const agreementDetail = (a: { compared: number; agreed: number; guard_changes: number }) =>
  a.compared === 0
    ? 'No decisions compared yet'
    : `${a.agreed} of ${a.compared} ${a.compared === 1 ? 'decision' : 'decisions'} kept as the model chose · ${a.guard_changes} changed by the guard`

type Bar = { label: string | null; value: number }

// The rows of a bar widget, in the order the page shows them.
const readBars = (page: Page, id: string): Promise<Bar[]> =>
  widget(page, id)
    .locator('[data-testid="bar-row"]')
    .evaluateAll((rows) =>
      rows.map((row) => ({ label: row.getAttribute('data-label'), value: Number(row.getAttribute('data-value')) })),
    )

const sum = (values: number[]) => values.reduce((total, value) => total + value, 0)

// The agreement widget's card is Studio's .ag-studio-layout-widget-container (the plain .ag-studio-layout-widget is
// transparent); its background is the theme's widget background, so it changes with the colour scheme.
const widgetBackground = (page: Page) =>
  widget(page, 'agreement').evaluate((el) => {
    const box = el.closest('.ag-studio-layout-widget-container')
    if (!box) throw new Error('the agreement widget is not inside a Studio widget')
    return getComputedStyle(box).backgroundColor
  })

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
  const { totals, money, agreement, by_reason, by_product } = summary

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

  // Model vs final agreement: the rate is 0..1 and shows as percentage points to one decimal, n/a when nothing was
  // compared.
  const rate = agreement.compared === 0 ? 'n/a' : pct(agreement.rate)
  await expect(widget(page, 'agreement').getByTestId('agreement-rate')).toHaveText(rate)
  await expect(widget(page, 'agreement').getByTestId('agreement-detail')).toHaveText(agreementDetail(agreement))

  // Disputes by reason: the labels are human text, so the counts are compared. Most disputes first.
  const reasonCounts = by_reason.map((r: { count: number }) => r.count)
  await expect.poll(async () => (await readBars(page, 'bar-reason')).map((bar) => bar.value)).toEqual(reasonCounts)
  const reasonBars = await readBars(page, 'bar-reason')
  expect(reasonBars.map((bar) => bar.value)).toEqual([...reasonCounts].sort((a, b) => b - a))
  expect(sum(reasonBars.map((bar) => bar.value))).toBe(totals.disputes)

  // Disputes by product: label and count, in any order among equal counts.
  const byLabel = (bars: Bar[]) => [...bars].sort((a, b) => String(a.label).localeCompare(String(b.label)))
  const productBars: Bar[] = by_product.map((p: { product: string; count: number }) => ({
    label: p.product,
    value: p.count,
  }))
  await expect.poll(async () => byLabel(await readBars(page, 'bar-product'))).toEqual(byLabel(productBars))
  const shownProducts = await readBars(page, 'bar-product')
  const shownCounts = shownProducts.map((bar) => bar.value)
  expect(shownCounts).toEqual([...shownCounts].sort((a, b) => b - a))
  expect(sum(shownCounts)).toBe(totals.disputes)

  // Money split: kept, refunded, open, in that order.
  const parts = widget(page, 'money-split').getByTestId('money-part')
  await expect(parts).toHaveCount(3)
  const split = [
    ['Kept', money.kept],
    ['Refunded', money.refunded],
    ['Open', money.open],
  ] as const
  for (const [index, [label, value]] of split.entries()) {
    await expect(parts.nth(index)).toHaveAttribute('data-label', label)
    await expect(parts.nth(index)).toHaveAttribute('data-value', String(value))
  }

  // Deadlines: one row per API entry, in the API's order (most urgent first). The second case is still open with a
  // due date, so the list is not empty.
  expect(deadlines.length).toBeGreaterThan(0)
  const deadlineRows = widget(page, 'deadlines').getByTestId('deadline-row')
  await expect(deadlineRows).toHaveCount(deadlines.length)
  for (const [index, deadline] of deadlines.entries()) {
    await expect(deadlineRows.nth(index)).toHaveAttribute('data-dispute-id', deadline.dispute_id)
    await expect(deadlineRows.nth(index)).toHaveAttribute('data-hours-left', String(deadline.hours_left))
  }

  expect(errors).toEqual([])
})

test('analytics widgets follow the colour scheme', async ({ page }) => {
  await page.emulateMedia({ colorScheme: 'dark' })
  await createCases(page)
  await page.getByRole('tab', { name: 'Analytics' }).click()
  await expect(page).toHaveURL(/#analytics$/)
  await expect(widget(page, 'agreement')).toBeVisible()
  await expect.poll(() => page.evaluate(() => matchMedia('(prefers-color-scheme: dark)').matches)).toBe(true)
  const darkBackground = await widgetBackground(page)

  await page.emulateMedia({ colorScheme: 'light' })
  await expect.poll(() => page.evaluate(() => matchMedia('(prefers-color-scheme: light)').matches)).toBe(true)
  await expect.poll(() => widgetBackground(page)).not.toBe(darkBackground)
})

test('analytics screenshot for the PR', async ({ page }) => {
  test.skip(!process.env.SCREENSHOTS, 'set SCREENSHOTS=1 to regenerate docs/screenshots')
  await page.setViewportSize({ width: 1280, height: 1100 })
  await page.emulateMedia({ colorScheme: 'light' })
  await page.goto('/')
  await createCases(page)

  await page.goto('/#analytics')
  await expect(kpi(page, /^Disputed \$$/)).not.toBeEmpty()
  await expect(widget(page, 'deadlines').getByTestId('deadline-row').first()).toBeVisible()
  await expect(widget(page, 'money-split')).toBeVisible()
  await page.waitForTimeout(800) // let the charts finish their entrance animation
  await page.screenshot({ path: '../docs/screenshots/analytics.png', fullPage: true })
})

// With the AI proxy reported enabled, Studio mounts with the assistant harness. No model runs in tests: the status
// route is stubbed and any POST to the proxy is aborted and counted.
test('the Studio assistant mounts when the proxy is enabled', async ({ page }) => {
  await page.route('**/api/studio/ai/status', (route) => route.fulfill({ json: { enabled: true } }))
  let proxyCalls = 0
  await page.route('**/api/studio/ai', (route) => {
    proxyCalls += 1
    return route.abort()
  })
  const errors: string[] = []
  page.on('console', (m) => {
    if (m.type() === 'error' && !isLicenceBanner(m.text())) errors.push(m.text())
  })
  page.on('pageerror', (e) => errors.push(e.message))

  await page.goto('/#analytics')
  await expect(kpi(page, /^Disputes$/)).toBeVisible()
  // View mode has no assistant. The toggle switches Studio to edit mode, where its AI panel lives.
  await page.getByRole('button', { name: 'Ask the assistant' }).click()
  await expect(page.getByText('AI Assistant', { exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Back to dashboard' })).toBeVisible()
  expect(proxyCalls).toBe(0)
  expect(errors).toEqual([])
})
