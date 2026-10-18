import { expect, test, type Page } from '@playwright/test'

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

test('the approve dialog says a replacement is not possible, and the executed case shows the approved text', async ({ page }) => {
  await simulate(page, 'agent_wrong_size')
  const caseView = page.getByTestId('case-view')
  const drafted = await caseView.getByLabel(/Message the buyer will receive/).inputValue()
  expect(drafted.trim()).not.toBe('')

  await caseView.getByRole('button', { name: 'Approve', exact: true }).click()
  const dialog = page.getByRole('dialog')
  await expect(dialog.getByTestId('replacement-note')).toBeVisible()
  await expect(dialog.getByTestId('replacement-note')).toContainText('PayPal takes no replacement offer')
  await dialog.getByRole('button', { name: 'Approve and send' }).click()

  await expect(page.getByTestId('case-status')).toHaveText('Executed')
  await expect(caseView.getByText('Message you approved')).toBeVisible()
  await expect(caseView.getByTestId('approved-text')).not.toBeEmpty()
  await expect(caseView.getByTestId('approved-text')).toContainText(drafted)
  await expect(caseView.getByText('Message the buyer will receive')).toHaveCount(0)
})

test('the approve dialog has no replacement note when the guard did not convert a replacement', async ({ page }) => {
  await simulate(page, 'inr_no_tracking')
  const caseView = page.getByTestId('case-view')

  await caseView.getByRole('button', { name: 'Approve', exact: true }).click()
  const dialog = page.getByRole('dialog')
  await expect(dialog.getByTestId('send-summary')).toBeVisible()
  // The case has no OFFER_REPLACEMENT guard note (the guard notes, when shown, are the only place one would appear).
  const notes = await caseView.getByTestId('guard-notes').allTextContents()
  expect(notes.join(' ')).not.toContain('OFFER_REPLACEMENT is not possible')
  await expect(dialog.getByTestId('replacement-note')).toHaveCount(0)
  await dialog.getByRole('button', { name: 'Cancel' }).click()
  await expect(dialog).toBeHidden()
})

test('the Reasoner row says so when the audit has no decide entry', async ({ page }) => {
  await page.route('**/api/audit/*', async (route) => {
    if (route.request().method() === 'OPTIONS') return route.continue()
    const res = await route.fetch()
    const body = (await res.json()) as { step: string }[]
    await route.fulfill({ response: res, json: body.filter((e) => e.step !== 'decide') })
  })
  await simulate(page, 'agent_wrong_size')

  await expect(page.getByTestId('case-view').getByTestId('reasoner-choice')).toHaveText('Not in the audit trail')
})
