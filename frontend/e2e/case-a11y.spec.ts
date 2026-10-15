import { expect, test, type Page } from '@playwright/test'

async function openCase(page: Page, caseId: string) {
  await page.goto('/')
  await page.getByLabel('Case').selectOption(caseId)
  await page.getByRole('button', { name: 'Create dispute' }).click()
  await expect(page.getByTestId('case-view')).toBeVisible()
}

test('facts say in text whether each row is good, bad or neutral', async ({ page }) => {
  await openCase(page, 'agent_wrong_size')
  const facts = page.getByTestId('facts')

  // Every row carries its meaning as text for a screen reader (the ✓ / ✕ glyph beside it is aria-hidden).
  await expect(facts.locator('li').first().locator('.sr-only')).toHaveText(/^(Good for you|Against you|Note): $/)

  const delivered = facts.locator('li', { hasText: 'Delivered to the address on the order' })
  await expect(delivered.locator('.sr-only')).toHaveText('Good for you: ')
})

test('the confidence bar is a meter with its value', async ({ page }) => {
  await openCase(page, 'agent_wrong_size')
  const meter = page.getByRole('meter', { name: 'Confidence' })

  await expect(meter).toBeVisible()
  await expect(meter).toHaveAttribute('aria-valuenow', /^\d+$/)
  await expect(meter).toHaveAttribute('aria-valuemax', '100')
})

test('a status change is announced politely through the status pill', async ({ page }) => {
  await openCase(page, 'agent_wrong_size')
  await expect(page.getByTestId('case-status')).toHaveAttribute('role', 'status')
})

test('the draft says how many characters it has', async ({ page }) => {
  await openCase(page, 'agent_wrong_size')
  await expect(page.getByLabel(/Message the buyer will receive/)).toHaveAccessibleDescription(/characters/)
})

test('opening the approve dialog and cancelling it sends nothing', async ({ page }) => {
  await openCase(page, 'agent_wrong_size')
  const caseView = page.getByTestId('case-view')

  await caseView.getByRole('button', { name: 'Approve' }).click()
  const dialog = page.getByRole('dialog')
  await expect(dialog).toBeVisible()
  await dialog.getByRole('button', { name: 'Cancel' }).click()

  await expect(page.getByTestId('case-status')).toHaveText('Pending')
})
