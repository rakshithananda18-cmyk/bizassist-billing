// utils/fieldCollections.js — the owner's split of a field collection.
import { describe, it, expect } from 'vitest'
import { checkSplit, startingSplit } from '../utils/fieldCollections'

const collection = {
  remaining: 1300,
  bills: [
    { invoice_id: 1, number: 'INV-0150', balance_due: 1180 },
    { invoice_id: 2, number: 'INV-0201', balance_due: 236 },
  ],
  suggested: [{ invoice_id: 1, amount: 1180 }, { invoice_id: 2, amount: 120 }],
}

describe('field collection split', () => {
  it('starts from the oldest-bill-first suggestion and accepts it', () => {
    const s = checkSplit(collection, startingSplit(collection))
    expect(s.problem).toBeNull()
    expect(s.total).toBe(1300)
    expect(s.left).toBe(0)
    expect(s.allocations).toEqual([{ invoice_id: 1, amount: 1180 }, { invoice_id: 2, amount: 120 }])
  })

  it('allows confirming part now', () => {
    const s = checkSplit(collection, { 1: '500', 2: '' })
    expect(s.problem).toBeNull()
    expect(s.left).toBe(800)
    expect(s.allocations).toEqual([{ invoice_id: 1, amount: 500 }])
  })

  it('refuses more than a bill owes, or more than was collected', () => {
    expect(checkSplit(collection, { 1: '0', 2: '300' }).problem).toContain('INV-0201')
    expect(checkSplit(collection, { 1: '1180', 2: '200' }).problem).toContain('left to confirm')
    expect(checkSplit(collection, { 1: '', 2: '0' }).problem).toContain('at least one')
  })
})
