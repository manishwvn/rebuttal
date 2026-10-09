import { expect, test, type Page } from '@playwright/test'

// The demo is an isolated session of the dashboard with six seeded disputes. Its calls go only to /api/demo/...
// and never to the real API. Runs against the mock backend (playwright.config.ts).
const SEEDED = Array.from({ length: 6 }, (_, i) => `PP-D-${2000 + i}`)
// Assistant said medium, shipped L; already analyzed and pending.
const HERO = 'PP-D-2000'
const REAL_API = ['/api/disputes', '/api/health', '/api/proposals', '/api/analytics', '/api/simulator']

interface Sent {
  method: string
  path: string
  authorized: boolean
}

const statusCell = (page: Page, disputeId: string) => page.locator(`[row-id="${disputeId}"] [col-id="status"]`)

// Records every request the page makes from now on.
function recordRequests(page: Page): Sent[] {
  const sent: Sent[] = []
  page.on('request', (request) => {
    sent.push({
      method: request.method(),
      path: new URL(request.url()).pathname,
      authorized: 'authorization' in request.headers(),
    })
  })
  return sent
}

// Opens the demo from the landing page. The recorder starts just before the click, after the landing page has
// loaded, so it records only what the demo sends.
async function enterDemo(page: Page): Promise<Sent[]> {
  await page.goto('/')
  await expect(page.getByTestId('mode-badge')).toContainText('mock')
  const sent = recordRequests(page)
  await page.getByTestId('try-demo').click()
  await expect(page).toHaveURL(/#demo$/)
  await expect(page.getByTestId('demo-banner')).toBeVisible()
  await expect(page.getByTestId('mode-badge')).toContainText('demo')
  return sent
}

// Approves the open case through the same confirm dialog as dispute-flow.spec.ts.
async function approveOpenCase(page: Page) {
  await page.getByTestId('case-view').getByRole('button', { name: 'Approve' }).click()
  const dialog = page.getByRole('dialog')
  await expect(dialog.getByTestId('send-summary')).toBeVisible()
  await dialog.getByRole('button', { name: 'Approve and send' }).click()
}

// Every API call is a demo call and none reaches a real endpoint; no request carries an Authorization header.
function expectIsolated(sent: Sent[]) {
  const api = sent.filter((r) => r.path.startsWith('/api/'))
  const isSessionCall = (r: Sent) => r.method === 'POST' && r.path === '/api/demo/sessions'
  expect(api.some(isSessionCall)).toBe(true)
  expect(api.filter((r) => !isSessionCall(r) && !r.path.startsWith('/api/demo/')).map((r) => `${r.method} ${r.path}`)).toEqual([])
  expect(api.filter((r) => REAL_API.some((prefix) => r.path.startsWith(prefix))).map((r) => r.path)).toEqual([])
  expect(sent.filter((r) => r.authorized)).toEqual([])
}

test('Try the demo opens the isolated demo and approves the hero case', async ({ page }) => {
  const sent = await enterDemo(page)

  await expect(page.getByTestId('inbox').locator('.ag-row')).toHaveCount(6)
  for (const id of SEEDED) await expect(page.locator(`[row-id="${id}"]`)).toBeVisible()

  await page.locator(`[row-id="${HERO}"]`).click()
  const panel = page.getByTestId('assistant-panel')
  await expect(panel.getByTestId('assistant-instruction')).toContainText('medium')
  await expect(panel.getByTestId('assistant-shipped')).toContainText('Size L')

  await approveOpenCase(page)
  await expect(statusCell(page, HERO)).toHaveText('Executed')
  expectIsolated(sent)
})

test('Simulator inside the demo adds a case', async ({ page }) => {
  await enterDemo(page)
  await page.getByLabel('Case').selectOption('inr_no_tracking')
  await page.getByRole('button', { name: 'Create dispute' }).click()

  const caseView = page.getByTestId('case-view')
  await expect(caseView).toBeVisible()
  const disputeId = (await caseView.locator('.case-head .mono').innerText()).split(' ')[0]
  expect(disputeId).toMatch(/^PP-D-\d+$/)
  await expect(page.locator(`[row-id="${disputeId}"]`)).toHaveAttribute('aria-selected', 'true')
  await expect(page.getByTestId('case-status')).toHaveText('Pending')
})

test('Reset demo restores the seeded state', async ({ page }) => {
  await enterDemo(page)
  await page.locator(`[row-id="${HERO}"]`).click()
  await approveOpenCase(page)
  await expect(statusCell(page, HERO)).toHaveText('Executed')

  await page.getByTestId('reset-demo').click()
  await expect(statusCell(page, HERO)).toHaveText('Pending')
})

test('Opening #demo directly never calls the real API', async ({ page }) => {
  const sent = recordRequests(page)
  await page.goto('/#demo')
  await expect(page.getByTestId('demo-banner')).toBeVisible()
  // Wait for the demo's inbox to load, so the calls it makes on load are recorded too.
  await expect(page.getByTestId('inbox').locator('.ag-row')).toHaveCount(6)
  const paths = sent.map((r) => r.path)
  expect(paths).not.toContain('/api/disputes')
  expect(paths).not.toContain('/api/health')
})

test('The real dashboard still works after visiting the demo', async ({ page }) => {
  await enterDemo(page)
  await page.getByTestId('exit-demo').click()
  await expect(page.getByTestId('tab-desk')).toBeVisible()
  const badge = page.getByTestId('mode-badge')
  await expect(badge).toContainText('mock')
  await expect(badge).not.toContainText('demo')
})
