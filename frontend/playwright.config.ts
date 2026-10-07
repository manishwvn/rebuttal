import { defineConfig } from '@playwright/test'

// The suite starts the real backend in mock mode (in-memory PayPal sandbox, rules baseline, no model key, no
// database, no tracing) and serves the production build of the dashboard against it.
const BACKEND_PORT = 8000
const APP_PORT = 4173
const APP_ORIGIN = `http://localhost:${APP_PORT}`

export default defineConfig({
  testDir: './e2e',
  fullyParallel: false,
  workers: 1,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [['github'], ['list']] : 'list',
  use: {
    baseURL: APP_ORIGIN,
    // Google Chrome is on developer machines and GitHub's ubuntu runners, so no browser download is needed.
    channel: 'chrome',
    trace: 'retain-on-failure',
  },
  webServer: [
    {
      command: `uv run uvicorn rebuttal.app:app --port ${BACKEND_PORT}`,
      cwd: '../backend',
      url: `http://localhost:${BACKEND_PORT}/api/health`,
      reuseExistingServer: false,
      timeout: 60_000,
      env: {
        REBUTTAL_MOCK: '1',
        REBUTTAL_REASONER: 'rules',
        REBUTTAL_PROVIDER: '',
        REBUTTAL_TRACING: '0',
        REBUTTAL_ALLOW_OPEN_API: '1',
        REBUTTAL_API_TOKEN: '',
        DATABASE_URL: '',
        REBUTTAL_CHECKPOINT_URL: '',
        REBUTTAL_AUDIT_PATH: '../frontend/test-results/audit.jsonl',
        REBUTTAL_CORS_ORIGINS: `${APP_ORIGIN},http://127.0.0.1:${APP_PORT}`,
      },
    },
    {
      command: `npm run build && npx vite preview --port ${APP_PORT} --strictPort`,
      url: APP_ORIGIN,
      reuseExistingServer: false,
      timeout: 120_000,
    },
  ],
})
