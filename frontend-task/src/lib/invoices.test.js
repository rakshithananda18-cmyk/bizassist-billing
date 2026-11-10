import { describe, expect, it } from 'vitest'
import { collectionAmounts, summarizeInvoices, takenBy } from './invoices'

const inv = (id, number, boxes, balance_due, tasks = []) => ({ id, number, boxes, balance_due, tasks })

describe('summarizeInvoices', () => {
  it('fills numbers, boxes, orders and the amount due', () => {
    expect(summarizeInvoices([inv(1, 'INV-201', 4, 2360), inv(2, 'INV-202', null, 300.5)])).toEqual({
      invoice_ids: [1, 2], reference: 'INV-201, INV-202', boxes: 4, orders_count: 2, balance_due: 2660.5,
    })
  })
  it('leaves boxes blank when no bill counts boxes', () => {
    expect(summarizeInvoices([inv(1, 'INV-1', null, 0)]).boxes).toBeNull()
    expect(summarizeInvoices([]).reference).toBe('')
  })
  it('keeps the numbers within the 200-character reference', () => {
    const many = Array.from({ length: 40 }, (_, i) => inv(i, `INVOICE-${1000 + i}`, 1, 0))
    const ref = summarizeInvoices(many).reference
    expect(ref).toHaveLength(200)
    expect(ref.endsWith('…')).toBe(true)
  })
})

describe('takenBy', () => {
  it('finds the live task of the same kind only', () => {
    const i = inv(1, 'INV-1', 1, 0, [{ task_id: 9, task_type: 'delivery', status: 'pending' }])
    expect(takenBy(i, 'delivery').task_id).toBe(9)
    expect(takenBy(i, 'payment_collect')).toBeNull()
  })
})

describe('collectionAmounts', () => {
  const linked = (current_amount_due, amount_expected = 1000, billing_balance_available = true) => ({
    amount_expected, current_amount_due, billing_balance_available,
    invoices: [{ id: 1, balance_due: 1000 }],
  })

  it('reduces the suggested collection after Billing records a payment', () => {
    expect(collectionAmounts(linked(300))).toEqual({
      linked: true, available: true, planned: 1000, currentDue: 300, suggested: 300,
    })
  })

  it('keeps a fully paid balance at zero rather than falling back to the planned amount', () => {
    expect(collectionAmounts(linked(0)).suggested).toBe(0)
  })

  it('respects a smaller owner-planned target while limiting it to current due', () => {
    expect(collectionAmounts(linked(1000, 100)).suggested).toBe(100)
    expect(collectionAmounts(linked(40, 100)).suggested).toBe(40)
    expect(collectionAmounts(linked(1000, 0)).suggested).toBe(0)
  })

  it('uses the current balance when no amount was planned', () => {
    expect(collectionAmounts(linked(252.23, null)).suggested).toBe(252.23)
  })

  it('does not use a historical balance if Billing reports a missing or unavailable invoice', () => {
    expect(collectionAmounts(linked(null, 1000, false))).toEqual({
      linked: true, available: false, planned: 1000, currentDue: null, suggested: null,
    })
  })

  it('requires the live contract for invoice-linked tasks when an older backend has only snapshots', () => {
    expect(collectionAmounts({ amount_expected: 1000, invoices: [{ balance_due: 1000 }] }).available).toBe(false)
  })

  it.each([null, '', -1, NaN, Infinity, 'not money'])('rejects invalid live amounts (%s) without a stale fallback', value => {
    expect(collectionAmounts(linked(value)).suggested).toBeNull()
  })

  it('keeps manual tasks without linked invoices usable', () => {
    expect(collectionAmounts({ amount_expected: 90, invoices: [], billing_balance_available: null })).toEqual({
      linked: false, available: true, planned: 90, currentDue: null, suggested: 90,
    })
    expect(collectionAmounts({ amount_expected: null }).suggested).toBeNull()
  })

  it('does not treat an explicit unavailable flag as a manual task', () => {
    expect(collectionAmounts({ amount_expected: 1000, billing_balance_available: false }).available).toBe(false)
  })
})
