import { expect, test } from '@playwright/test'

// The simulator panel renders on the dashboard and in the hosted demo. Its copy must not claim that nothing leaves the
// machine, which is false in the demo.

test('the simulator on the dashboard says nothing is sent to PayPal', async ({ page }) => {
  await page.goto('/')
  await expect(page.getByTestId('mode-badge')).toContainText('mock')
  await expect(page.getByTestId('simulator')).toContainText('Nothing is sent to PayPal.')
  await expect(page.getByTestId('simulator')).not.toContainText('Nothing leaves this machine')
})

test('the simulator in the demo says nothing is sent to PayPal', async ({ page }) => {
  await page.goto('/#demo')
  await expect(page.getByTestId('demo-banner')).toBeVisible()
  await expect(page.getByTestId('simulator')).toContainText('Nothing is sent to PayPal.')
  await expect(page.getByTestId('simulator')).not.toContainText('Nothing leaves this machine')
})
