import { describe, expect, it } from 'vitest'
import { summarizeInvoices, takenBy } from './invoices'

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
