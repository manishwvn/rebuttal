import { expect, test, type Page } from '@playwright/test'

// Keyboard use of the Desk / Analytics tabs and the confirm dialog. Enter outside a button never confirms. Enter, Space or
// a click on the focused confirm button does, and that is the human approval.

// Same helper as dispute-flow.spec.ts: simulates a case from the Desk and returns the new dispute id.
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

test('tabs: arrow keys, Home and End select and focus the tab, and the tab bar is one tab stop', async ({ page }) => {
  await page.goto('/')
  await expect(page.getByTestId('mode-badge')).toContainText('mock')

  await page.getByTestId('tab-desk').focus()
  await page.keyboard.press('ArrowRight')
  await expect(page.getByTestId('tab-analytics')).toHaveAttribute('aria-selected', 'true')
  await expect(page.getByTestId('tab-analytics')).toBeFocused()
  await expect(page).toHaveURL(/#analytics$/)
  await expect(page.getByTestId('tab-desk')).toHaveAttribute('tabindex', '-1')
  await expect(page.getByTestId('tab-analytics')).toHaveAttribute('tabindex', '0')

  // The arrows wrap: ArrowRight on the last tab goes back to Desk.
  await page.keyboard.press('ArrowRight')
  await expect(page.getByTestId('tab-desk')).toHaveAttribute('aria-selected', 'true')
  await expect(page.getByTestId('tab-desk')).toBeFocused()
  await expect(page.getByTestId('tab-analytics')).toHaveAttribute('tabindex', '-1')
  await expect(page).not.toHaveURL(/#analytics$/)

  await page.keyboard.press('End')
  await expect(page.getByTestId('tab-analytics')).toHaveAttribute('aria-selected', 'true')
  await expect(page.getByTestId('tab-analytics')).toBeFocused()

  await page.keyboard.press('Home')
  await expect(page.getByTestId('tab-desk')).toHaveAttribute('aria-selected', 'true')
  await expect(page.getByTestId('tab-desk')).toBeFocused()

  // Tab leaves the tab bar: only the selected tab is in the tab order.
  await page.keyboard.press('Tab')
  await expect(page.getByRole('tablist').locator(':focus')).toHaveCount(0)
})

test('approve dialog: Cancel has focus when it opens, Escape closes it, focus returns to Approve and nothing is sent', async ({ page }) => {
  await simulate(page, 'agent_wrong_size')
  const caseView = page.getByTestId('case-view')
  const dialog = page.getByRole('dialog')

  await caseView.getByRole('button', { name: 'Approve' }).click()
  await expect(dialog).toBeVisible()
  await expect(dialog).toHaveAttribute('aria-describedby', 'confirm-body')
  await expect(dialog).toHaveAttribute('aria-busy', 'false')
  await expect(dialog.getByRole('button', { name: 'Cancel' })).toBeFocused()

  await page.keyboard.press('Escape')
  await expect(dialog).toBeHidden()
  await expect(caseView.getByRole('button', { name: 'Approve' })).toBeFocused()
  await expect(page.getByTestId('case-status')).toHaveText('Pending')
})

test('approve dialog: Enter on Cancel cancels, and Enter on the body text does nothing', async ({ page }) => {
  await simulate(page, 'agent_wrong_size')
  const caseView = page.getByTestId('case-view')
  const dialog = page.getByRole('dialog')
  const status = page.getByTestId('case-status')

  // Enter on the focused Cancel button activates Cancel. It does not confirm.
  await caseView.getByRole('button', { name: 'Approve' }).click()
  await expect(dialog.getByRole('button', { name: 'Cancel' })).toBeFocused()
  await page.keyboard.press('Enter')
  await expect(dialog).toBeHidden()
  await expect(status).toHaveText('Pending')

  // Enter on the body text (not a button) does nothing: the dialog stays open and nothing is sent.
  await caseView.getByRole('button', { name: 'Approve' }).click()
  await expect(dialog).toBeVisible()
  await dialog.locator('#confirm-body').evaluate((el) => el.setAttribute('tabindex', '-1'))
  await dialog.locator('#confirm-body').focus()
  await page.keyboard.press('Enter')
  await expect(dialog).toBeVisible()
  await expect(status).toHaveText('Pending')

  await dialog.getByRole('button', { name: 'Cancel' }).click()
  await expect(dialog).toBeHidden()
  await expect(status).toHaveText('Pending')
})

test('reject dialog: the reason box takes Enter as a newline, and Escape closes it without sending', async ({ page }) => {
  await simulate(page, 'agent_wrong_size')
  const caseView = page.getByTestId('case-view')
  const dialog = page.getByRole('dialog')

  await caseView.getByRole('button', { name: 'Reject' }).click()
  const reason = dialog.getByLabel(/Reason/)
  // The reason box starts with focus, so the merchant can type straight away.
  await expect(reason).toBeFocused()
  await page.keyboard.type('I will call the buyer')
  await page.keyboard.press('Enter')
  await expect(reason).toHaveValue('I will call the buyer\n')
  await expect(dialog).toBeVisible()

  await page.keyboard.press('Escape')
  await expect(dialog).toBeHidden()
  await expect(caseView.getByRole('button', { name: 'Reject' })).toBeFocused()
  await expect(page.getByTestId('case-status')).toHaveText('Pending')
})

// Known gap: Chromium does not trap Tab inside a modal <dialog>, and ConfirmDialog no longer wraps focus itself (the
// audit asked for that code to go). Tab reaches the page outside the dialog, so this stays a fixme until the parent
// decides whether to restore a focus trap.
test.fixme('approve dialog: Tab never leaves the dialog', async ({ page }) => {
  await simulate(page, 'agent_wrong_size')
  const dialog = page.getByRole('dialog')
  const focusInDialog = () => page.evaluate(() => Boolean(document.activeElement?.closest('dialog')))

  await page.getByTestId('case-view').getByRole('button', { name: 'Approve' }).click()
  await expect(dialog).toBeVisible()

  for (let press = 0; press < 6; press += 1) {
    await page.keyboard.press('Tab')
    expect(await focusInDialog()).toBe(true)
  }
})
