import { expect, test } from '@playwright/test'
import { backendName } from '../src/labels.ts'

// A same-origin build has an empty API base, so the unreachable-backend message names the page origin, not an empty
// string ('Cannot reach the backend at . Is it running?').

test('backendName names the page origin when the API base is empty, otherwise the base', () => {
  expect(backendName('', 'https://x.example')).toBe('https://x.example')
  expect(backendName('http://localhost:8000', 'https://x.example')).toBe('http://localhost:8000')
})

test('an unreachable backend names the API base in the error, never an empty name', async ({ page }) => {
  await page.route('**/api/disputes', (route) => {
    if (route.request().method() === 'OPTIONS') return route.continue()
    return route.abort()
  })

  await page.goto('/')
  await expect(page.getByTestId('app-error')).toContainText('Cannot reach the backend at http://localhost:8000. Is it running?')
  await expect(page.getByTestId('app-error')).not.toContainText('at . Is it')
})
