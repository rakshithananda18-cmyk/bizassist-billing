// src/__tests__/sync_pending_invoices.test.js
// R7b Slice 3c — offline bills must feed back into invoice-number allocation so
// two queued bills never collide on the same number (the backend's inner
// invoice_no wall would silently drop the second).
import { describe, it, expect } from 'vitest'
import { pendingInvoiceNumbers, pendingInvoiceRows } from '../sync/pendingInvoices'

const op = (invoice_no) => ({ method: 'POST', path: '/invoices', body: { invoice_no } })

describe('pendingInvoiceNumbers', () => {
  it('extracts invoice_no from queued ops', () => {
    expect(pendingInvoiceNumbers([op('INV-0039'), op('INV-0040')])).toEqual(['INV-0039', 'INV-0040'])
  })

  it('ignores ops without an invoice number', () => {
    expect(pendingInvoiceNumbers([op('INV-0039'), { body: {} }, {}, null])).toEqual(['INV-0039'])
    expect(pendingInvoiceNumbers([])).toEqual([])
    expect(pendingInvoiceNumbers(undefined)).toEqual([])
  })

  it('tolerates the camelCase key too', () => {
    expect(pendingInvoiceNumbers([{ body: { invoiceNo: 'INV-0050' } }])).toEqual(['INV-0050'])
  })
})

describe('pendingInvoiceRows', () => {
  it('shapes numbers like server invoice rows for the allocator', () => {
    expect(pendingInvoiceRows([op('INV-0039'), op('INV-0040')])).toEqual([
      { invoice_number: 'INV-0039' },
      { invoice_number: 'INV-0040' },
    ])
  })

  it('merged with the server list, the next number skips queued bills', () => {
    // Simulate the allocator input: server knows up to INV-0038; two bills queued.
    const server = [{ invoice_number: 'INV-0038' }]
    const merged = [...server, ...pendingInvoiceRows([op('INV-0039'), op('INV-0040')])]
    const used = new Set(merged.map((r) => r.invoice_number))
    // Next allocation must land on 0041, not re-issue 0039/0040.
    expect(used.has('INV-0039')).toBe(true)
    expect(used.has('INV-0040')).toBe(true)
    expect(used.has('INV-0041')).toBe(false)
  })
})
