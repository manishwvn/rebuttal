/// <reference types="node" />
import { defineConfig } from '@playwright/test'

// Google Chrome is on developer machines, as in frontend/playwright.config.ts, so no browser download is needed.
// No webServer here: scripts/make_video.sh starts the backend and the dashboard before it runs this recorder.
export default defineConfig({
  testDir: '.',
  testMatch: 'record.spec.ts',
  fullyParallel: false,
  workers: 1,
  retries: 0,
  timeout: 600_000,
  reporter: 'list',
  outputDir: `${process.env.VIDEO_WORK_DIR ?? 'test-results'}/pw-output`,
  use: {
    baseURL: process.env.VIDEO_BASE_URL ?? 'http://localhost:4273',
    channel: 'chrome',
    viewport: { width: 1280, height: 720 },
    colorScheme: 'light',
  },
})
