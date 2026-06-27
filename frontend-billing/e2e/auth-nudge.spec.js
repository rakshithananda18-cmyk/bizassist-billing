// E2E — Scenario C: fresh-device login + "Cloud data available" nudge.
// Mirrors MANUAL_TEST_PLAN.md §2c. Automates: login on the local app as an
// account that already has cloud data → the nudge appears → × is the only
// dismiss → Sync now merges.
//
// PRECONDITIONS (set as env vars; do NOT hardcode creds):
//   E2E_USER / E2E_PASS  — an owner that EXISTS on the cloud WITH >=1 record,
//                          and is NOT yet on this local device (fresh-device path).
//   Local backend on :8001 and the cloud (HF Space) reachable; JWT_SECRET matched.
// If E2E_USER is unset the test is skipped (so CI without a seeded account stays green).
import { test, expect } from '@playwright/test'

const USER = process.env.E2E_USER
const PASS = process.env.E2E_PASS

test.describe('Scenario C — fresh-device login + cloud-data nudge', () => {
  test.skip(!USER || !PASS, 'set E2E_USER / E2E_PASS for the cloud-seeded owner')

  test('nudge appears, dismisses only via ×, and Sync now merges', async ({ page }) => {
    // 1. Log in on the local app.
    await page.goto('/login')
    await page.getByPlaceholder('e.g. store').fill(USER)
    await page.getByPlaceholder('••••••••').fill(PASS)
    await page.getByRole('button', { name: /^Sign In$/ }).click()

    // 2. Lands on the dashboard/home (fresh-device mirror created in the background).
    await expect(page).toHaveURL(/\/(home|dashboard)?$/, { timeout: 15_000 })

    // 3. The divergence-sense nudge appears (cloud has more than this device).
    const nudge = page.getByText('Cloud data available')
    await expect(nudge).toBeVisible({ timeout: 15_000 })

    // 4. Accidental dismissal must NOT close it: clicking the dim backdrop is a no-op.
    await page.mouse.click(5, 5) // far corner = backdrop
    await expect(nudge).toBeVisible()

    // 5. The × (aria-label="Close") is the only dismiss — verify it closes...
    //    then re-trigger by reloading so we can exercise Sync now.
    await page.getByRole('button', { name: 'Close' }).click()
    await expect(nudge).toBeHidden()

    await page.reload()
    await expect(page.getByText('Cloud data available')).toBeVisible({ timeout: 15_000 })

    // 6. Sync now → merge completes (the modal closes after BackupModal finishes).
    await page.getByRole('button', { name: /Sync now/ }).click()
    await expect(page.getByText('Cloud data available')).toBeHidden({ timeout: 30_000 })

    // 7. Sanity: cloud records are now visible locally (adjust route/selector to your UI).
    await page.goto('/parties')
    await expect(page.getByRole('row')).not.toHaveCount(0)
  })
})
