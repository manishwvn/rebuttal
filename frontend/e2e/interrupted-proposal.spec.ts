import { expect, test, type Page, type Route } from '@playwright/test'

// An interrupted proposal: a newer analysis stopped part-way, so the case still carries the previous proposal's fields
// but must read Interrupted, never claim it was sent, and offer Analyze again. The disputes response is rewritten to
// produce that state; the analyze call itself goes to the real mock backend (analysis is read-only).

// The case view reads the proposal from the disputes list.
const DISPUTES = '**/api/disputes'
const ANALYZE_PATH = /\/api\/disputes\/[^/]+\/analyze$/

// Sets the status of every proposal in the disputes response to INTERRUPTED.
async function routeInterrupted(page: Page) {
  await page.route(DISPUTES, async (route: Route) => {
    if (route.request().method() === 'OPTIONS') return route.continue()
    const response = await route.fetch()
    const disputes = (await response.json()) as { proposal: { status: string } | null }[]
    for (const dispute of disputes) {
      if (dispute.proposal) dispute.proposal.status = 'INTERRUPTED'
    }
    return route.fulfill({
      status: response.status(),
      contentType: 'application/json',
      headers: { 'Access-Control-Allow-Origin': '*' },
      body: JSON.stringify(disputes),
    })
  })
}

async function openInterruptedCase(page: Page) {
  await routeInterrupted(page)
  await page.goto('/')
  await page.getByLabel('Case').selectOption('inr_delivered')
  await page.getByRole('button', { name: 'Create dispute' }).click()
  await expect(page.getByTestId('case-view')).toBeVisible()
}

test('an interrupted proposal reads Interrupted and never claims it was sent', async ({ page }) => {
  await openInterruptedCase(page)
  const caseView = page.getByTestId('case-view')

  await expect(page.getByTestId('case-status')).toHaveText('Interrupted')
  await expect(caseView).toContainText('A newer analysis stopped part-way. Nothing new was sent.')
  await expect(caseView).not.toContainText('Sent to PayPal')
  await expect(page.getByRole('button', { name: 'Analyze again' })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Approve' })).toHaveCount(0)
})

test('Analyze again calls the analyze endpoint', async ({ page }) => {
  await openInterruptedCase(page)

  const analyzeRequest = page.waitForRequest((request) => request.method() === 'POST' && ANALYZE_PATH.test(new URL(request.url()).pathname))
  await page.getByRole('button', { name: 'Analyze again' }).click()
  await analyzeRequest
})
