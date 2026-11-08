import { test, expect } from '@playwright/test'
import { execFileSync } from 'node:child_process'

async function mountPrintFixture(page, { kind = 'a4', template = 'ClassicA4', size = '3inch', count = 1 } = {}) {
  page.on('pageerror', error => console.error('Print fixture:', error.message))
  await page.route('**/print-layout-fixture', route => route.fulfill({ contentType: 'text/html', body: `
    <!doctype html><html><head><link rel="stylesheet" href="/src/index.css">
    <script type="module">import RefreshRuntime from '/@react-refresh'; RefreshRuntime.injectIntoGlobalHook(window);
    window.$RefreshReg$ = () => {}; window.$RefreshSig$ = () => type => type; window.__vite_plugin_react_preamble_installed__ = true;</script></head><body>
    <div id="root">App controls</div><div id="fixture"></div><div id="other-portal">Unrelated popup</div>
    <script type="module">
      import React from '/node_modules/.vite/deps/react.js';
      import ReactDOMClient from '/node_modules/.vite/deps/react-dom_client.js';
      import PrintPortal from '/src/invoice/PrintPortal.jsx';
      import Template from '/src/invoice/templates/${template}.jsx';
      import ThermalReceipt from '/src/components/sales/ThermalReceipt.jsx';
      import { gstPayload } from '/src/__tests__/invoice/fixtures.js';
      const payload = gstPayload();
      payload.lines = Array.from({ length: ${count} }, (_, i) => ({ ...payload.lines[0], sno: i + 1, name: 'Printed item ' + (i + 1) }));
      const thermal = React.createElement(ThermalReceipt, {
        settings: { print: { thermal_page_size: '${size}' } }, profile: { business_name: 'Receipt fixture' },
        activeTab: { name: 'POS-PRINT' }, form: { items: [{ product: 'Saved Widget', qty: 1, price: 100 }], payment_mode: 'cash', amount_received: '100' },
        customers: [], user: { username: 'cashier' }, isIntrastate: true, subtotal: 100, billDiscountAmt: 0,
        cgstAmt: 0, sgstAmt: 0, igstAmt: 0, cashDiscountAmt: 0, roundOff: 0, grandTotal: 100, payable: 100,
        changeToReturn: 0, colFooter: { qty: 1, discount: 0 },
      });
      ReactDOMClient.createRoot(document.getElementById('fixture')).render(React.createElement(React.Fragment, null,
        thermal, ${kind === 'a4' ? "React.createElement(PrintPortal, null, React.createElement(Template, { payload }))" : 'null'}));
    </script></body></html>` }))
  await page.goto('/print-layout-fixture')
  await expect(page.locator(kind === 'a4' ? '#invoice-a4-root' : '#thermal-receipt')).toBeAttached()
  await page.emulateMedia({ media: 'print' })
}

for (const template of ['ClassicA4', 'ModernA4']) {
  test(`${template} isolates the invoice and releases the screen viewport for printing`, async ({ page }, testInfo) => {
    await mountPrintFixture(page, { template })
    await expect(page.locator('#invoice-a4-root')).toBeVisible()
    await expect(page.locator('#thermal-receipt')).toBeHidden()
    await expect(page.locator('#root')).toBeHidden()
    await expect(page.locator('#other-portal')).toBeHidden()
    expect(await page.evaluate(() => getComputedStyle(document.documentElement).overflow)).toBe('visible')
    expect(await page.evaluate(() => getComputedStyle(document.body).overflow)).toBe('visible')
    await page.locator('#invoice-a4-root').screenshot({ path: testInfo.outputPath('invoice-print.png') })
  })
}

for (const [size, width] of [['2inch', 54], ['3inch', 76]]) {
  test(`POS ${size} printing contains only the saved receipt`, async ({ page }, testInfo) => {
    await mountPrintFixture(page, { kind: 'thermal', size })
    await expect(page.locator('#thermal-receipt')).toBeVisible()
    await expect(page.locator('#root')).toBeHidden()
    await expect(page.locator('#other-portal')).toBeHidden()
    const actual = await page.locator('#thermal-receipt').evaluate(node => node.getBoundingClientRect().width)
    expect(Math.abs(actual - width * 96 / 25.4)).toBeLessThan(1)
    await expect(page.locator('#thermal-receipt')).toContainText('Powered by Stater')
    await page.locator('#thermal-receipt').screenshot({ path: testInfo.outputPath('receipt-print.png') })
  })
}

test('a long invoice prints its final item and footer across multiple pages', async ({ page }, testInfo) => {
  await mountPrintFixture(page, { count: 120 })
  const filename = testInfo.outputPath('long-invoice.pdf')
  await page.pdf({ path: filename, preferCSSPageSize: true, printBackground: true })
  const result = JSON.parse(execFileSync('python', ['-c',
    'import json,sys; from pypdf import PdfReader; r=PdfReader(sys.argv[1]); print(json.dumps({"pages":len(r.pages),"text":"".join(p.extract_text() or "" for p in r.pages)}))', filename], { encoding: 'utf8' }))
  expect(result.pages).toBeGreaterThan(1)
  expect(result.text.replace(/\s+/g, ' ')).toContain('Printed item 120')
  expect(result.text).toContain('This is a computer generated invoice.')
  expect(result.text).not.toContain('Unrelated popup')
  expect(result.text).not.toContain('App controls')
})
