// E2E — Scenario B: multi-terminal real-time sync (the trust test).
// Mirrors MANUAL_TEST_PLAN.md §2. Two independent browser contexts = two
// "terminals" (A and B) logged into the SAME business in Cloud mode. A writes,
// B must auto-refresh within ~1s via the SSE sync.trigger — no manual reload.
//
// PRECONDITIONS (env): E2E_USER / E2E_PASS for a CLOUD account; both contexts
// point at the cloud. Skipped if creds unset.
import { test, expect, chromium } from '@playwright/test'

const USER = process.env.E2E_USER
const PASS = process.env.E2E_PASS

async function login(page) {
  await page.goto('/login')
  await page.getByPlaceholder('e.g. store').fill(USER)
  await page.getByPlaceholder('••••••••').fill(PASS)
  await page.getByRole('button', { name: /^Sign In$/ }).click()
  await expect(page).toHaveURL(/\/(home|dashboard)?$/, { timeout: 15_000 })
}

test.describe('Scenario B — two-terminal real-time sync', () => {
  test.skip(!USER || !PASS, 'set E2E_USER / E2E_PASS for the cloud owner')

  test('A creates a record → B list auto-refreshes (no reload)', async () => {
    const browser = await chromium.launch()
    const ctxA = await browser.newContext()
    const ctxB = await browser.newContext()
    const A = await ctxA.newPage()
    const B = await ctxB.newPage()
    try {
      await login(A)
      await login(B)

      // B watches the parties/customers list.
      await B.goto('/parties')
      const rowsBefore = await B.getByRole('row').count()

      // A creates a new customer (adjust selectors to your "Add party" flow).
      await A.goto('/parties')
      await A.getByRole('button', { name: /Add|New/ }).first().click()
      const uniqueName = `E2E_${Date.now()}`
      await A.getByLabel(/Name/i).first().fill(uniqueName)
      await A.getByRole('button', { name: /Save|Create/ }).first().click()

      // B should reflect it WITHOUT a manual reload (SSE sync.trigger → refetch).
      await expect(B.getByText(uniqueName)).toBeVisible({ timeout: 8_000 })
      expect(await B.getByRole('row').count()).toBeGreaterThan(rowsBefore)
    } finally {
      await browser.close()
    }
  })
})
