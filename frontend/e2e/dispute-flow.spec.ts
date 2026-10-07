import { expect, test, type Page } from '@playwright/test'

const EDITED = 'Hi Lena, sorry about the mix-up. Send the shirt back and we will ship a medium right away. Juniper & Oak'

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

const statusCell = (page: Page, disputeId: string) => page.locator(`[row-id="${disputeId}"] [col-id="status"]`)
const auditSteps = (page: Page) => page.getByTestId('audit-trail').locator('li').evaluateAll((items) => items.map((li) => li.getAttribute('data-step')))

test('hero case: assistant said medium, shipped L; guard note; approve with an edited message', async ({ page }) => {
  const disputeId = await simulate(page, 'agent_wrong_size')
  const caseView = page.getByTestId('case-view')

  // The new dispute is in the inbox, pending, and is the open row.
  await expect(statusCell(page, disputeId)).toHaveText('Pending')
  await expect(page.locator(`[row-id="${disputeId}"]`)).toHaveAttribute('aria-selected', 'true')

  // Assistant instruction vs what shipped, side by side.
  const panel = page.getByTestId('assistant-panel')
  await expect(panel.getByTestId('assistant-instruction')).toContainText('navy linen shirt in medium')
  await expect(panel.getByTestId('assistant-shipped')).toContainText('Size L')
  await expect(panel).toContainText('did not match the instruction')

  // The reasoner picked a replacement, PayPal does not allow one here, so the guard changed it.
  await expect(page.getByTestId('reasoner-choice')).toHaveText('Offer a free replacement')
  await expect(page.getByTestId('final-action')).toHaveText('Refund after the item is returned')
  await expect(page.getByTestId('guard-notes')).toContainText('OFFER_REPLACEMENT is not possible on this dispute')
  await expect(page.getByTestId('facts')).toContainText('Delivered to the address on the order')

  const stepsBefore = await auditSteps(page)
  expect(stepsBefore).toEqual(['gather', 'decide', 'guard', 'propose'])

  // Edit the message, then approve: the confirm dialog states exactly what goes to PayPal.
  await caseView.getByLabel(/Message the buyer will receive/).fill(EDITED)
  await caseView.getByRole('button', { name: 'Approve with my edits' }).click()
  const dialog = page.getByRole('dialog')
  const summary = dialog.getByTestId('send-summary')
  await expect(summary).toContainText(`POST /v1/customer/disputes/${disputeId}/make-offer`)
  await expect(summary).toContainText('REFUND_WITH_RETURN')
  await expect(summary).toContainText('$48.00')
  await expect(dialog.getByTestId('send-message')).toHaveText(EDITED)
  await dialog.getByRole('button', { name: 'Approve and send' }).click()

  // Status changes in the case and the inbox, and the audit trail gains the approval and the execution.
  await expect(dialog).toBeHidden()
  await expect(page.getByTestId('case-status')).toHaveText('Executed')
  await expect(statusCell(page, disputeId)).toHaveText('Executed')
  await expect(caseView.getByLabel(/Message the buyer will receive/)).toHaveValue(EDITED)
  await expect(caseView.getByRole('button', { name: /Approve|Reject/ })).toHaveCount(0)
  await expect.poll(() => auditSteps(page)).toEqual(['gather', 'decide', 'guard', 'propose', 'approve', 'execute', 'record'])
  await expect(page.getByTestId('audit-trail')).toContainText('Merchant approved with an edited message')
})

test('reject: nothing is sent to PayPal and the reason lands in the audit trail', async ({ page }) => {
  const disputeId = await simulate(page, 'inr_no_tracking')
  const caseView = page.getByTestId('case-view')
  await expect(statusCell(page, disputeId)).toHaveText('Pending')

  await caseView.getByRole('button', { name: 'Reject' }).click()
  const dialog = page.getByRole('dialog')
  await expect(dialog).toContainText('Nothing will be sent to PayPal')
  await dialog.getByLabel(/Reason/).fill('I will call the buyer myself')
  await dialog.getByRole('button', { name: 'Reject' }).click()

  await expect(dialog).toBeHidden()
  await expect(page.getByTestId('case-status')).toHaveText('Rejected')
  await expect(statusCell(page, disputeId)).toHaveText('Rejected')
  await expect(caseView).toContainText('Nothing was sent to PayPal')
  await expect(page.getByTestId('audit-trail')).toContainText('I will call the buyer myself')
  await expect(caseView.getByRole('button', { name: 'Approve' })).toHaveCount(0)
})

test('a proposal that is no longer approvable shows the 409 plainly', async ({ page, request }) => {
  const disputeId = await simulate(page, 'agent_wrong_size')
  const caseView = page.getByTestId('case-view')

  // Someone else decides it first (here: straight through the API), so this screen is now stale.
  const pending = await (await request.get('http://localhost:8000/api/proposals/pending')).json()
  const proposal = pending.find((p: { dispute_id: string }) => p.dispute_id === disputeId)
  await request.post(`http://localhost:8000/api/proposals/${proposal.id}/reject`, { data: { reason: 'handled elsewhere' } })

  await caseView.getByRole('button', { name: 'Approve' }).click()
  const dialog = page.getByRole('dialog')
  await dialog.getByRole('button', { name: 'Approve and send' }).click()
  await expect(dialog.getByTestId('confirm-error')).toContainText('REJECTED')

  // The screen catches up with the server once the dialog is dismissed.
  await dialog.getByRole('button', { name: 'Cancel' }).click()
  await expect(page.getByTestId('case-status')).toHaveText('Rejected')
})
