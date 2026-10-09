import { expect, test } from '@playwright/test'

// A backend that needs a token shows the sign-in screen. The token is checked, kept in sessionStorage and never sent
// to the demo. Backend answers are mocked: the suite's real backend runs open (no token).
const TOKEN = 'e2e-token'
const cors = { 'Access-Control-Allow-Origin': '*', 'Access-Control-Allow-Headers': '*' }
const json = (body: unknown, status = 200) => ({ status, contentType: 'application/json', headers: cors, body: JSON.stringify(body) })

test.beforeEach(async ({ page }) => {
  await page.route('**/api/health', (r) => r.fulfill(json({ ok: true, mode: 'sandbox / groq', auth: true, database: true })))
  await page.route('**/api/disputes', (r) => {
    if (r.request().method() === 'OPTIONS') return r.fulfill({ status: 204, headers: cors })
    return r.fulfill(
      r.request().headers().authorization === `Bearer ${TOKEN}` ? json([]) : json({ detail: 'Missing or wrong API token' }, 401),
    )
  })
})

test('sign-in rejects a wrong token, accepts the right one, and sign out returns to it', async ({ page }) => {
  await page.goto('/')
  await expect(page.getByTestId('signin')).toBeVisible()
  await expect(page.getByTestId('try-demo')).toHaveAttribute('href', '#demo')

  await page.getByTestId('signin-token').fill('wrong')
  await page.getByTestId('signin-submit').click()
  await expect(page.getByTestId('signin-error')).toBeVisible()
  expect(await page.evaluate(() => sessionStorage.getItem('rebuttal.token'))).toBeNull()

  await page.getByTestId('signin-token').fill(TOKEN)
  await page.getByTestId('signin-submit').click()
  await expect(page.getByTestId('tab-desk')).toBeVisible()
  expect(await page.evaluate(() => sessionStorage.getItem('rebuttal.token'))).toBe(TOKEN)

  await page.reload() // the token survives a reload in the same tab
  await expect(page.getByTestId('tab-desk')).toBeVisible()

  await page.getByTestId('sign-out').click()
  await expect(page.getByTestId('signin')).toBeVisible()
  expect(await page.evaluate(() => sessionStorage.getItem('rebuttal.token'))).toBeNull()
})

test('the Try the demo link on the sign-in screen opens the demo without a token', async ({ page }) => {
  await page.goto('/')
  await page.getByTestId('try-demo').click()
  await expect(page).toHaveURL(/#demo$/)
  await expect(page.getByTestId('mode-badge')).toContainText('demo')
})

test('the built bundle does not contain the dev token variable', async ({ request }) => {
  const html = await (await request.get('/')).text()
  const asset = /src="(\/assets\/[^"]+\.js)"/.exec(html)?.[1]
  expect(asset).toBeTruthy()
  expect(await (await request.get(asset!)).text()).not.toContain('VITE_API_TOKEN')
})
