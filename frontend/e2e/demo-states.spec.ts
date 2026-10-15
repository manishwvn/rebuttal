import { expect, test, type Page } from '@playwright/test'

// The loading, busy and landmark states of the demo, the sign-in screen and the connecting screen. Runs against the
// mock backend (playwright.config.ts); the sign-in test mocks the backend's answers as signin.spec.ts does.
const TOKEN = 'e2e-token'
const cors = { 'Access-Control-Allow-Origin': '*', 'Access-Control-Allow-Headers': '*' }
const json = (body: unknown, status = 200) => ({ status, contentType: 'application/json', headers: cors, body: JSON.stringify(body) })

// Holds every request matching `pattern` until the returned release() is called. Preflights pass straight through.
async function holdRequests(page: Page, pattern: string): Promise<() => void> {
  let release: () => void = () => {}
  const gate = new Promise<void>((resolve) => {
    release = resolve
  })
  await page.route(pattern, async (route) => {
    if (route.request().method() === 'OPTIONS') return route.continue()
    await gate
    return route.continue()
  })
  return () => release()
}

async function mockSignInBackend(page: Page) {
  await page.route('**/api/health', (r) => r.fulfill(json({ ok: true, mode: 'sandbox / groq', auth: true, database: true })))
  await page.route('**/api/disputes', (r) => {
    if (r.request().method() === 'OPTIONS') return r.fulfill({ status: 204, headers: cors })
    return r.fulfill(
      r.request().headers().authorization === `Bearer ${TOKEN}` ? json([]) : json({ detail: 'Missing or wrong API token' }, 401),
    )
  })
}

test('the demo shows a loading status until its session starts', async ({ page }) => {
  const release = await holdRequests(page, '**/api/demo/sessions')
  await page.goto('/#demo')

  const loading = page.getByTestId('demo-loading')
  await expect(loading).toBeVisible()
  await expect(loading).toHaveRole('status')
  await expect(loading).toHaveText('Starting the demo…')

  release()
  await expect(loading).toHaveCount(0)
  await expect(page.getByTestId('mode-badge')).toContainText('demo · mock')
})

test('the demo banner is a note, and its reset button is not inside a paragraph', async ({ page }) => {
  await page.goto('/#demo')
  const banner = page.getByTestId('demo-banner')
  await expect(banner).toBeVisible()
  await expect(banner).toHaveRole('note')
  await expect(banner.locator('p', { hasText: 'This is a sandbox demo on an in-memory mock.' })).toHaveCount(1)
  await expect(banner.getByRole('button', { name: 'Reset demo' })).toHaveCount(1)
  await expect(page.getByTestId('demo-banner').locator('p').locator('button')).toHaveCount(0)
})

test('Reset demo reads Resetting… and is disabled until the reset completes', async ({ page }) => {
  await page.goto('/#demo')
  const reset = page.getByTestId('reset-demo')
  await expect(reset).toBeEnabled()

  const release = await holdRequests(page, '**/api/demo/*/reset')
  await reset.click()
  await expect(reset).toHaveText('Resetting…')
  await expect(reset).toBeDisabled()

  release()
  await expect(reset).toHaveText('Reset demo')
  await expect(reset).toBeEnabled()
})

test('the demo has one main landmark', async ({ page }) => {
  await page.goto('/#demo')
  await expect(page.getByTestId('mode-badge')).toContainText('demo · mock')
  await expect(page.getByRole('main')).toHaveCount(1)
})

test('the sign-in screen has one main landmark, focuses the token and flags a wrong one', async ({ page }) => {
  await mockSignInBackend(page)
  await page.goto('/')
  await expect(page.getByTestId('signin')).toBeVisible()
  await expect(page.getByRole('main')).toHaveCount(1)

  const token = page.getByTestId('signin-token')
  await expect(token).toBeFocused()
  await token.fill('wrong')
  await page.getByTestId('signin-submit').click()
  await expect(page.getByTestId('signin-error')).toBeVisible()
  await expect(token).toHaveAttribute('aria-invalid', 'true')
})

test('the connecting screen shows a status while the backend answers', async ({ page }) => {
  const release = await holdRequests(page, '**/api/health')
  await page.goto('/')

  const connecting = page.getByRole('status').filter({ hasText: /^Connecting…$/ })
  await expect(connecting).toBeVisible()

  release()
  await expect(connecting).toHaveCount(0)
})
