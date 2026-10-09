import { expect, test } from '@playwright/test'

// The Vite dev server runs React StrictMode, which mounts, unmounts and re-mounts every effect. The dashboard's
// production build does not, so this is the only place that catches effect bugs of that kind.
test.use({ baseURL: 'http://localhost:5174' })

test('under the dev server (StrictMode) the confirm dialog stays open until dismissed', async ({ page }) => {
  await page.goto('/')
  await expect(page.getByTestId('mode-badge')).toContainText('mock')
  await page.getByLabel('Case').selectOption('inr_no_tracking')
  await page.getByRole('button', { name: 'Create dispute' }).click()
  const caseView = page.getByTestId('case-view')
  await expect(caseView).toBeVisible()

  await caseView.getByRole('button', { name: 'Approve' }).click()
  const dialog = page.getByRole('dialog')
  await expect(dialog.getByTestId('send-summary')).toBeVisible()
  // The bug closed it on the next tick; give a stray close event time to arrive.
  await page.waitForTimeout(500)
  await expect(dialog).toBeVisible()

  await dialog.getByRole('button', { name: 'Cancel' }).click()
  await expect(dialog).toBeHidden()
  await expect(page.getByTestId('case-status')).toHaveText('Pending')
})
