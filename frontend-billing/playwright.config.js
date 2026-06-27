// Playwright E2E config for frontend-billing.
// Run: npm run e2e  (headless) / npm run e2e:headed
// Docs: TESTING.md §3. Env: E2E_BASE_URL, E2E_USER, E2E_PASS, E2E_CLOUD_URL.
import { defineConfig, devices } from '@playwright/test'

const BASE_URL = process.env.E2E_BASE_URL || 'http://localhost:5174'

export default defineConfig({
  testDir: './e2e',
  timeout: 30_000,
  expect: { timeout: 10_000 },
  fullyParallel: false,            // sync tests share backend state; keep serial
  retries: process.env.CI ? 1 : 0,
  reporter: [['html', { open: 'never' }], ['list']],
  use: {
    baseURL: BASE_URL,
    trace: 'on-first-retry',       // trace viewer on failure
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',
  },
  projects: [
    { name: 'chromium', use: { ...devices['Desktop Chrome'] } },
  ],
  // Auto-start the Vite dev server unless one is already running.
  // NOTE: the backend(s) must be started separately (see spec headers).
  webServer: {
    command: 'npm run dev',
    url: BASE_URL,
    reuseExistingServer: true,
    timeout: 60_000,
  },
})
