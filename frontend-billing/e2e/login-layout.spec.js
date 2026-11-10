import { test, expect } from '@playwright/test'

for (const viewport of [{ width: 320, height: 568 }, { width: 390, height: 844 }, { width: 1920, height: 1080 }]) {
  for (const route of ['login', 'register']) {
    test(`${route} remains reachable at ${viewport.width}×${viewport.height}`, async ({ page }) => {
      await page.setViewportSize(viewport)
      await page.route('**/business/templates', request => request.fulfill({ json: { templates: [{ key: 'general', label: 'General Business' }] } }))
      await page.route('**/health', request => request.fulfill({ json: { status: 'ok' } }))
      await page.goto(`/${route}`)
      const card = page.locator('.login-card')
      await expect(card).toBeVisible()
      const bounds = await card.boundingBox()
      expect(bounds.x).toBeGreaterThanOrEqual(0)
      expect(bounds.x + bounds.width).toBeLessThanOrEqual(viewport.width + 1)
      expect(bounds.y).toBeGreaterThanOrEqual(0)
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
      await page.screenshot({ path: `test-results/${route}-${viewport.width}x${viewport.height}-top.png`, fullPage: true })
      if (route === 'login') {
        const footer = page.locator('.login-footer')
        await footer.scrollIntoViewIfNeeded()
        const footerBounds = await footer.boundingBox()
        expect(Math.abs(footerBounds.width - bounds.width)).toBeLessThanOrEqual(1)
        const check = page.getByText('⚙ System check', { exact: true })
        await check.click()
        await expect(page.locator('.login-system-check')).toHaveAttribute('open', '')
      } else {
        await page.locator('#register-form button[type="submit"]').scrollIntoViewIfNeeded()
        await expect(page.locator('#register-form button[type="submit"]')).toBeInViewport()
      }
      await page.screenshot({ path: `test-results/${route}-${viewport.width}x${viewport.height}.png`, fullPage: true })
    })
  }
}
