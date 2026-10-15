import { expect, test } from '@playwright/test'

// The Analytics tab's loading, error and progress states. The backend is the real mock backend (see playwright.config.ts);
// the analytics GET is held or failed by route stubs so each state can be seen.

// A promise gate: requests that wait on it are released by calling release().
function gate() {
  let release!: () => void
  const open = new Promise<void>((resolve) => {
    release = resolve
  })
  return { wait: () => open, release }
}

test('the Analytics tab shows a loading status while the first load is held', async ({ page }) => {
  const held = gate()
  await page.route('**/api/analytics*', async (route) => {
    if (route.request().method() === 'OPTIONS') return route.continue()
    await held.wait()
    return route.continue()
  })

  await page.goto('/#analytics')
  const loading = page.getByRole('status').filter({ hasText: 'Loading analytics…' })
  await expect(loading).toBeVisible()

  held.release()
  await expect(loading).toHaveCount(0)
  await expect(page.getByTestId('analytics-status')).not.toBeEmpty()
})

test('a failed first analytics load shows the error and Retry loads again', async ({ page }) => {
  let gets = 0
  await page.route('**/api/analytics*', (route) => {
    if (route.request().method() === 'OPTIONS') return route.continue()
    gets += 1
    if (gets === 1) {
      return route.fulfill({
        status: 500,
        contentType: 'application/json',
        headers: { 'Access-Control-Allow-Origin': '*' },
        body: JSON.stringify({ detail: 'analytics down in this test' }),
      })
    }
    return route.continue()
  })

  await page.goto('/#analytics')
  await expect(page.getByRole('alert').filter({ hasText: 'analytics down in this test' })).toBeVisible()
  await expect(page.getByTestId('analytics-retry')).toBeVisible()

  await page.getByTestId('analytics-retry').click()
  await expect(page.getByTestId('analytics-retry')).toHaveCount(0)
  await expect(page.getByTestId('analytics-status')).not.toBeEmpty()
})

test('Refresh says Refreshing while it loads and is disabled until the load ends', async ({ page }) => {
  await page.goto('/#analytics')
  await expect(page.getByTestId('analytics-status')).not.toBeEmpty()

  const held = gate()
  await page.route('**/api/analytics*', async (route) => {
    if (route.request().method() === 'OPTIONS') return route.continue()
    await held.wait()
    return route.continue()
  })

  await page.getByRole('button', { name: 'Refresh', exact: true }).click()
  const busy = page.getByRole('button', { name: 'Refreshing…', exact: true })
  await expect(busy).toBeDisabled()

  held.release()
  await expect(page.getByRole('button', { name: 'Refresh', exact: true })).toBeEnabled()
})

test('the Analytics tab takes keyboard focus', async ({ page }) => {
  await page.goto('/')
  const tab = page.getByTestId('tab-analytics')
  await tab.focus()
  await expect(tab).toBeFocused()
})
