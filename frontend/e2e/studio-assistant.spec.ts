import { expect, test, type Page, type Request } from '@playwright/test'

// The Studio assistant's prompt starters. They are defined in StudioDashboard.tsx (PROMPT_STARTERS) and shown above
// the message box of an empty conversation. No model runs here: the status route is stubbed, and every POST to the
// proxy is stubbed (or aborted and counted), so these tests never reach the backend's assistant.

// Copied from analytics.spec.ts: AG Studio prints its unlicensed-use banner as console errors.
const isLicenceBanner = (text: string) =>
  /licen/i.test(text) || /^\*+$/.test(text.trim()) || /AG Studio Core|unlocked for trial|watermark/.test(text)

const STARTERS = [
  { label: 'Top disputed products', prompt: 'Which products have the most disputes?' },
  { label: 'Why buyers dispute', prompt: 'What are the main reasons buyers open disputes?' },
  { label: 'Money at risk', prompt: 'How much money is at risk in open disputes?' },
  { label: 'Deadlines', prompt: 'Which disputes have the nearest response deadlines?' },
]

// Opens Studio in edit mode, where the AI panel lives, and waits for the assistant to show.
async function openAssistant(page: Page) {
  await page.route('**/api/studio/ai/status', (route) => route.fulfill({ json: { enabled: true } }))
  await page.goto('/#analytics')
  await page.getByRole('button', { name: 'Ask the assistant' }).click()
  await expect(page.getByText('AI Assistant', { exact: true })).toBeVisible()
}

test('the assistant offers the four prompt starters', async ({ page }) => {
  await page.route('**/api/studio/ai/status', (route) => route.fulfill({ json: { enabled: true } }))
  let proxyCalls = 0
  await page.route('**/api/studio/ai', (route) => {
    proxyCalls += 1
    return route.abort()
  })
  const errors: string[] = []
  page.on('console', (m) => {
    if (m.type() === 'error' && !isLicenceBanner(m.text())) errors.push(m.text())
  })
  page.on('pageerror', (e) => errors.push(e.message))

  await openAssistant(page)
  // Studio renders the starters as buttons in the AI panel.
  for (const starter of STARTERS) {
    await expect(page.getByRole('button', { name: starter.label, exact: true })).toBeVisible()
  }
  expect(proxyCalls).toBe(0)
  expect(errors).toEqual([])
})

test('clicking a starter asks that question', async ({ page }) => {
  await page.route('**/api/studio/ai/status', (route) => route.fulfill({ json: { enabled: true } }))
  const bodies: Record<string, unknown>[] = []
  await page.route('**/api/studio/ai', (route, request: Request) => {
    bodies.push(request.postDataJSON() as Record<string, unknown>)
    return route.fulfill({
      json: {
        message: { content: 'Stub answer.', tool_calls: [] },
        finish_reason: 'stop',
        usage: null,
        model: 'stub',
      },
    })
  })
  const errors: string[] = []
  page.on('pageerror', (e) => errors.push(e.message))

  await openAssistant(page)
  const [topProducts] = STARTERS
  await page.getByRole('button', { name: topProducts.label, exact: true }).click()

  await expect(page.getByText('Stub answer.', { exact: true })).toBeVisible()
  // The first turn carries the starter's prompt as a user message.
  const first = bodies[0] as { messages: { role: string; content: string | null }[] }
  const userMessages = first.messages.filter((message) => message.role === 'user')
  expect(userMessages.some((message) => message.content?.includes(topProducts.prompt))).toBe(true)
  // The proxy owns the model and its sampling settings, so the browser never sends them.
  for (const body of bodies) {
    expect(body).not.toHaveProperty('model')
    expect(body).not.toHaveProperty('temperature')
    expect(body).not.toHaveProperty('stream')
  }
  // Starters show only in a conversation nobody has spoken in.
  for (const starter of STARTERS) {
    await expect(page.getByRole('button', { name: starter.label, exact: true })).toHaveCount(0)
  }
  expect(errors).toEqual([])
})

test('a proxy failure shows an error, not a crash', async ({ page }) => {
  await page.route('**/api/studio/ai/status', (route) => route.fulfill({ json: { enabled: true } }))
  let proxyCalls = 0
  await page.route('**/api/studio/ai', (route) => {
    proxyCalls += 1
    return route.fulfill({ status: 502, json: { detail: 'The assistant is unavailable.' } })
  })
  const errors: string[] = []
  page.on('pageerror', (e) => errors.push(e.message))

  await openAssistant(page)
  await page.getByRole('button', { name: STARTERS[0].label, exact: true }).click()
  // The click must reach the proxy, otherwise this test would not exercise the failure path.
  await expect.poll(() => proxyCalls).toBeGreaterThan(0)

  // Studio shows its own error text for a failed turn; the wording is not asserted. The panel stays usable.
  await expect(page.getByRole('button', { name: 'Back to dashboard' })).toBeVisible()
  await expect(page.getByRole('textbox').first()).toBeVisible()
  expect(errors).toEqual([])
})
