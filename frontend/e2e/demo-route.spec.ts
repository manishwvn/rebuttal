import { expect, test } from '@playwright/test'

// '#demo' is a route of its own: the dashboard is not mounted there, so the demo never asks the dashboard's APIs for
// anything. The dashboard's 'Try the demo' link and Back button move between the two routes.

test('the demo route makes no /api/disputes or /api/health request', async ({ page }) => {
  const dashboardRequests: string[] = []
  page.on('request', (request) => {
    const { pathname } = new URL(request.url())
    if (pathname === '/api/disputes' || pathname === '/api/health') dashboardRequests.push(request.url())
  })

  await page.goto('/#demo')
  await page.waitForLoadState('networkidle')

  await expect(page).toHaveURL(/#demo$/)
  await expect(page.getByTestId('mode-badge')).toHaveCount(0)
  await expect(page.getByTestId('tab-desk')).toHaveCount(0)
  expect(dashboardRequests).toEqual([])
})

test('Try the demo opens the demo, and Back returns to the dashboard', async ({ page }) => {
  await page.goto('/')
  await expect(page.getByTestId('mode-badge')).toContainText('mock')

  const link = page.getByTestId('try-demo')
  await expect(link).toHaveText('Try the demo')
  await expect(link).toHaveAttribute('href', '#demo')

  await link.click()
  await expect(page).toHaveURL(/#demo$/)
  await expect(page.getByTestId('tab-desk')).toHaveCount(0)

  await page.goBack()
  await expect(page.getByTestId('mode-badge')).toContainText('mock')
  await expect(page.getByTestId('tab-desk')).toHaveAttribute('aria-selected', 'true')
})

test('Back from the demo returns to the Analytics tab it was opened from', async ({ page }) => {
  await page.goto('/#analytics')
  await expect(page.getByTestId('tab-analytics')).toHaveAttribute('aria-selected', 'true')

  await page.getByTestId('try-demo').click()
  await expect(page).toHaveURL(/#demo$/)

  await page.goBack()
  await expect(page).toHaveURL(/#analytics$/)
  await expect(page.getByTestId('tab-analytics')).toHaveAttribute('aria-selected', 'true')
})

test('a failing health check shows the backend detail in the error banner', async ({ page }) => {
  await page.route('**/api/health', (route) =>
    route.fulfill({
      status: 500,
      contentType: 'application/json',
      headers: { 'Access-Control-Allow-Origin': '*' },
      body: JSON.stringify({ detail: 'health check failed in this test' }),
    }),
  )

  await page.goto('/')
  await expect(page.getByTestId('app-error')).toHaveCount(1)
  await expect(page.getByTestId('app-error')).toContainText('health check failed in this test')
  await expect(page.getByTestId('mode-badge')).toHaveText('connecting…')
  // The disputes request still succeeds, so the desk itself loads.
  await expect(page.getByTestId('waiting')).toBeVisible()
})

// An empty detail (over HTTP/2 the status text is empty too) must still give the banner a message, not an empty alert.
test('a failing health check with no detail shows a fallback message in the banner', async ({ page }) => {
  await page.route('**/api/health', (route) =>
    route.fulfill({
      status: 500,
      contentType: 'application/json',
      headers: { 'Access-Control-Allow-Origin': '*' },
      body: JSON.stringify({ detail: '' }),
    }),
  )

  await page.goto('/')
  await expect(page.getByTestId('app-error')).toHaveText('The backend health check failed')
  await expect(page.getByTestId('mode-badge')).toHaveText('connecting…')
})

test('a failing disputes request with no detail shows a fallback message in the desk banner', async ({ page }) => {
  await page.route('**/api/disputes', (route) =>
    route.fulfill({
      status: 500,
      contentType: 'application/json',
      headers: { 'Access-Control-Allow-Origin': '*' },
      body: JSON.stringify({ detail: '' }),
    }),
  )

  await page.goto('/')
  await expect(page.getByTestId('app-error')).toHaveText('The request failed')
  // The health check still succeeds, so the mode badge is set.
  await expect(page.getByTestId('mode-badge')).toContainText('mock')
})
