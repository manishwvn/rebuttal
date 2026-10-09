import { expect, test } from '@playwright/test'

// Not part of the regular run: SCREENSHOTS=1 npx playwright test screenshots writes the PR screenshots.
test.skip(!process.env.SCREENSHOTS, 'set SCREENSHOTS=1 to regenerate docs/screenshots')

test('inbox and hero case screenshots', async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 900 })
  await page.emulateMedia({ colorScheme: 'light' })
  await page.goto('/')
  for (const id of ['inr_no_tracking', 'snad_damaged_low_value', 'agent_wrong_size']) {
    await page.getByLabel('Case').selectOption(id)
    await page.getByRole('button', { name: 'Create dispute' }).click()
    await expect(page.getByTestId('case-view')).toBeVisible()
    await expect(page.getByRole('button', { name: 'Create dispute' })).toBeEnabled()
  }
  await expect(page.getByTestId('assistant-panel')).toBeVisible()
  await page.waitForTimeout(800) // let the grid finish animating rows into sorted order
  await page.locator('section', { has: page.getByRole('heading', { name: 'Inbox' }) }).screenshot({ path: '../docs/screenshots/inbox.png' })
  await page.getByTestId('case-view').screenshot({ path: '../docs/screenshots/hero-case.png' })
})
