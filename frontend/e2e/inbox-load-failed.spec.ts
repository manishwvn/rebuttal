import { expect, test } from '@playwright/test'

// A failed first inbox load must not leave the desk on 'Loading disputes…' forever: it shows a failed state with a
// Retry that loads the disputes again.

test('a failed first inbox load shows a failed state and Retry loads the disputes', async ({ page }) => {
  let disputeGets = 0
  await page.route('**/api/disputes', (route) => {
    if (route.request().method() === 'OPTIONS') return route.continue()
    disputeGets += 1
    if (disputeGets === 1) {
      return route.fulfill({
        status: 500,
        contentType: 'application/json',
        headers: { 'Access-Control-Allow-Origin': '*' },
        body: JSON.stringify({ detail: 'inbox down in this test' }),
      })
    }
    return route.continue()
  })

  await page.goto('/')
  await expect(page.getByTestId('app-error')).toContainText('inbox down in this test')
  await expect(page.locator('body')).toContainText('Could not load disputes.')
  await expect(page.locator('body')).not.toContainText('Loading disputes…')
  await expect(page.getByTestId('inbox-retry')).toBeVisible()

  await page.getByTestId('inbox-retry').click()
  await expect(page.getByTestId('waiting')).toBeVisible()
  await expect(page.getByTestId('inbox-retry')).toHaveCount(0)
  await expect(page.getByTestId('app-error')).toHaveCount(0)
  // selectedId is null on a fresh load, so this text shows only once the disputes have loaded.
  await expect(page.getByText('Pick a dispute in the inbox to see what the agent proposes.')).toBeVisible()
})
