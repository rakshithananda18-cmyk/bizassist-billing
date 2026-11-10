import { beforeEach, describe, expect, it } from 'vitest'
import { handleDemoRequest, resetDemoData } from '../demo/demoEngine'
import { readAllPages, readList } from '../utils/readPages'
import { computeInvoiceTotals } from '../utils/invoiceMath'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import ClassicA4 from '../invoice/templates/ClassicA4'
import ModernA4 from '../invoice/templates/ModernA4'
import ThermalCompact from '../invoice/templates/ThermalCompact'

const read = path => handleDemoRequest(path).json()
const post = (path, body, headers) => handleDemoRequest(path, { method: 'POST', body: JSON.stringify(body), headers })
const demoFetch = async (path, opts) => handleDemoRequest(path, opts)
beforeEach(resetDemoData)

describe('production app demo data', () => {
  it('opens the real counter with an active shift instead of the register gate', async () => {
    const response = await demoFetch('/shifts/current')
    const data = await response.json()
    // Sales.refreshShift reads data.shift; a bare shift object locks billing.
    expect(data.shift).toMatchObject({ id: 101, status: 'open', user_id: 999999, opening_cash: 5000 })
    expect(data.shift.start_time).toBeTruthy()
  })

  it('serves real list contracts and product fields across API entry points', async () => {
    const products = await readAllPages(demoFetch, '/billing/products', { pageSize: 3 })
    expect(products).toHaveLength(8)
    expect(products[0]).toMatchObject({ selling_price: 620, cost_price: 500, stock_qty: 48, quantity: 48, cgst_rate: 2.5, sgst_rate: 2.5 })
    const absolute = await read('https://app.staterbill.com/api/billing/products?q=Royal')
    expect(absolute.items.map(p => p.id)).toEqual([1])
    expect(await readAllPages(demoFetch, '/billing/vendors')).toHaveLength(2)
    expect(await readList(demoFetch, '/purchases')).toHaveLength(2)
    expect(await readList(demoFetch, '/billing/stock-transfers')).toEqual([])
    const response = handleDemoRequest('/products')
    expect(JSON.parse(await response.text()).items).toHaveLength(8)
    expect(await response.clone().json()).toEqual(await response.json())
  })

  it('populates home, dashboard, charts, purchase details and the contact statement consistently', async () => {
    const summary = await read('/dashboard-summary')
    expect(summary).toMatchObject({ inventory_count: 8, pending_count: 1, pending_amount: 3200, low_stock_count: 2 })
    expect(summary.total_revenue).toBeGreaterThan(0)
    expect(summary.paid_today).toBeGreaterThan(0)
    expect(summary.recent_invoices[0]).toHaveProperty('invoice_number')
    const charts = await read('/dashboard-charts')
    expect(charts.monthly_revenue).toHaveLength(6)
    expect(charts.top_products[0].value).toBeGreaterThan(0)
    const purchases = await readList(demoFetch, '/purchases')
    expect(purchases.some(b => b.status === 'pending')).toBe(true)
    expect(purchases.some(b => b.status === 'confirmed')).toBe(true)
    const detail = await read('/purchases/' + purchases[0].id)
    expect(detail.lines[0]).toMatchObject({ product_id: 1, quantity: 12, unit_price: 500 })
    const statement = await read('/reports/party-ledger?party_type=customer&party_id=1')
    expect(statement.entries.length).toBeGreaterThan(1)
    expect(statement.summary).toMatchObject({ abs_closing: 3200, balance_type: 'Receivable' })
    const vendor = await read('/reports/party-ledger?party_type=vendor&party_id=3')
    expect(vendor.summary).toMatchObject({ abs_closing: purchases[0].total_amount, balance_type: 'Payable' })
  })

  it('renders sample invoices in every real invoice template with matching totals and payment history', async () => {
    const invoice = (await read('/invoices'))[0]
    const payload = await read('/sales/' + invoice.invoice_number + '/print-payload')
    expect(payload.invoice).toMatchObject({ number: invoice.invoice_number, id: invoice.id, uid_token: null })
    expect(payload.totals).toMatchObject({ grand_total: invoice.total_amount, amount_paid: invoice.paid_amount, balance_due: 0 })
    expect(payload.lines[0]).toMatchObject({ sno: 1, name: invoice.items[0].product_name, qty: 2 })
    expect(payload.totals.taxable_amount + payload.totals.cgst_total + payload.totals.sgst_total + payload.totals.round_off).toBeCloseTo(invoice.total_amount, 2)
    for (const template of [ClassicA4, ModernA4, ThermalCompact]) {
      const html = renderToStaticMarkup(createElement(template, { payload }))
      expect(html).toContain(invoice.invoice_number)
      expect(html).toContain(invoice.items[0].product_name)
      expect(html).not.toContain('NaN')
    }
    const account = await read('/invoices/' + invoice.id + '/account')
    expect(account.payments[0]).toMatchObject({ amount: invoice.paid_amount, method: invoice.payment_mode })
    expect((await read('/sales/DEMO-10488/print-payload')).totals.balance_due).toBe(3200)
  })

  it('saves actual counter totals, reduces stock and safely replays a retried save once', async () => {
    const items = [{ product_id: 1, product: 'Royal Heritage Basmati Rice 5kg', qty: 2, price: 620, cgst_rate: 2.5, sgst_rate: 2.5 }]
    const payload = { invoice_no: 'DEMO-10492', customer_id: 1, gst_enabled: true, items,
      bill_discount: 40, cash_discount: 2, mark_paid: false, paid_amount: 100, payment_mode: 'upi' }
    const expected = computeInvoiceTotals(items, { billDiscountValue: 40, cashDiscount: 2 }).payable
    const headers = { 'X-Client-Request-Id': 'demo-save-once' }
    const saved = await post('/billing/invoices', payload, headers).json()
    expect(saved).toMatchObject({ invoice_no: payload.invoice_no, total_amount: expected, paid_amount: 100, status: 'Partial' })
    expect((await read('/products/1/stock')).current_stock).toBe(46)
    expect((await read('/billing/customers')).items[0].outstanding_balance).toBe(3200 + expected - 100)
    expect((await post('/billing/invoices', payload, headers).json()).id).toBe(saved.id)
    expect((await read('/products/1/stock')).current_stock).toBe(46)
    expect((await read('/invoices')).filter(i => i.invoice_no === payload.invoice_no)).toHaveLength(1)
  })

  it('rejects overselling atomically and does not pretend unsupported writes succeeded', async () => {
    const before = (await read('/invoices')).length
    const response = post('/invoices', { items: [{ product_id: 1, qty: 100, price: 620 }], mark_paid: true })
    expect(response.status).toBe(422)
    expect((await read('/invoices')).length).toBe(before)
    expect((await read('/products/1/stock')).current_stock).toBe(48)
    expect(post('/purchases/upload', {}).status).toBe(403)
    expect(post('/unknown-demo-action', {}).status).toBe(403)
  })

  it('updates disposable stock, purchase bills and contacts through real endpoints', async () => {
    const adjustment = { qty_delta: 5, note: 'Demo delivery', batch_no: 'DEMO-LOT' }
    expect(post('/products/1/stock/adjustment', adjustment).ok).toBe(true)
    expect((await read('/products/1/stock')).batches[0]).toMatchObject({ stock: 53, batch_no: 'DEMO-LOT' })
    const contact = await post('/billing/customers', { name: 'Sample Corner Store', phone: '9000000000' }).json()
    expect((await read('/customers')).items.find(c => c.id === contact.id).name).toBe('Sample Corner Store')
    const purchase = await post('/purchases/confirm', { supplier_name: 'Metro Cash & Carry Wholesale',
      invoice_number: 'DEMO-PURCHASE', lines: [{ product_id: 1, quantity: 4, unit_price: 500 }] }).json()
    expect(purchase).toMatchObject({ invoice_number: 'DEMO-PURCHASE', total_amount: 2100, status: 'confirmed' })
    expect((await read('/products/1/stock')).current_stock).toBe(57)
    expect((await read('/purchases')).some(b => b.id === purchase.id)).toBe(true)
    resetDemoData()
    expect((await read('/products/1/stock')).current_stock).toBe(48)
    expect((await read('/customers')).items).toHaveLength(2)
    expect((await read('/purchases'))).toHaveLength(2)
  })

  it('returns independent response snapshots rather than shared mutable arrays', async () => {
    const response = handleDemoRequest('/customers')
    post('/customers', { name: 'Later Contact' })
    const original = await response.json()
    expect(original.items).toHaveLength(2)
    original.items[0].name = 'Changed outside engine'
    expect((await read('/customers')).items[0].name).toBe('Ramesh Kirana Store')
  })
})
