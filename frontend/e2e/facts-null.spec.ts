import { expect, test, type Page, type Route } from '@playwright/test'

// A null fact is a neutral note, not a red finding against the merchant. The backend returns null when a check could
// not run (no order, so tracking was not checked) or when the answer is uncertain (the address is written differently).
// These tests rewrite the facts in the disputes response to produce those cases.

// The case view reads the proposal (and its facts) from the disputes list.
const DISPUTES = '**/api/disputes'

// Replaces the facts of every object in the response that carries a `facts` property.
function editFacts(node: unknown, edit: (facts: Record<string, unknown>) => Record<string, unknown>): void {
  if (Array.isArray(node)) {
    node.forEach((child) => editFacts(child, edit))
  } else if (node && typeof node === 'object') {
    const record = node as Record<string, unknown>
    if (record.facts && typeof record.facts === 'object') record.facts = edit(record.facts as Record<string, unknown>)
    Object.values(record).forEach((child) => editFacts(child, edit))
  }
}

async function routeFacts(page: Page, edit: (facts: Record<string, unknown>) => Record<string, unknown>) {
  await page.route(DISPUTES, async (route: Route) => {
    if (route.request().method() === 'OPTIONS') return route.continue()
    const response = await route.fetch()
    const body = await response.json()
    editFacts(body, edit)
    return route.fulfill({
      status: response.status(),
      contentType: 'application/json',
      headers: { 'Access-Control-Allow-Origin': '*' },
      body: JSON.stringify(body),
    })
  })
}

async function openCase(page: Page, caseId: string) {
  await page.goto('/')
  await page.getByLabel('Case').selectOption(caseId)
  await page.getByRole('button', { name: 'Create dispute' }).click()
  await expect(page.getByTestId('case-view')).toBeVisible()
}

test('a dispute with no order shows tracking as not checked, not as a finding against the merchant', async ({ page }) => {
  await routeFacts(page, () => ({ order_found: false, demo_fixture: false, tracking_uploaded_to_paypal: null }))
  await openCase(page, 'inr_delivered')
  const facts = page.getByTestId('facts')

  await expect(facts).not.toContainText('No tracking on the PayPal transaction')
  await expect(facts).toContainText('Tracking on the PayPal transaction was not checked')
  const row = facts.locator('li', { hasText: 'Tracking on the PayPal transaction was not checked' })
  await expect(row.locator('.sr-only')).toHaveText('Note: ')
})

test('an uncertain delivery address is a neutral note to check', async ({ page }) => {
  await routeFacts(page, (facts) => ({ ...facts, delivered_address_matches: null }))
  await openCase(page, 'inr_delivered')
  const facts = page.getByTestId('facts')

  await expect(facts).toContainText('Delivery address written differently; check it')
  const row = facts.locator('li', { hasText: 'Delivery address written differently; check it' })
  await expect(row.locator('.sr-only')).toHaveText('Note: ')
  await expect(facts).not.toContainText('Delivered to a different address than the order')
  await expect(facts).not.toContainText('Delivered to the address on the order')
})

test('a matching delivery address still shows as good for the merchant', async ({ page }) => {
  await openCase(page, 'inr_delivered')
  const facts = page.getByTestId('facts')

  await expect(facts).toContainText('Delivered to the address on the order')
  const row = facts.locator('li', { hasText: 'Delivered to the address on the order' })
  await expect(row.locator('.sr-only')).toHaveText('Good for you: ')
})
