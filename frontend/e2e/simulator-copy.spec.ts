import { expect, test } from '@playwright/test'

// The simulator panel also renders in the hosted demo (asserted in demo.spec.ts, which already opens a demo session:
// the demo allows only 10 sessions a minute per client). Its copy must not claim that nothing leaves the machine.

test('the simulator on the dashboard says nothing is sent to PayPal', async ({ page }) => {
  await page.goto('/')
  await expect(page.getByTestId('mode-badge')).toContainText('mock')
  await expect(page.getByTestId('simulator')).toContainText('Nothing is sent to PayPal.')
  await expect(page.getByTestId('simulator')).not.toContainText('Nothing leaves this machine')
})
