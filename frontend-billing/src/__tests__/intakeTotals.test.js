// utils/intakeTotals — the one place stock-intake money is added up.
// The same arithmetic used to be transcribed in Stock.jsx's printGRN and in
// IntakePurchasePanel, which is how a printed GRN and an on-screen summary end
// up disagreeing about what a delivery cost.
import { describe, it, expect } from 'vitest'
import { intakeTotals, gstRateOf } from '../utils/intakeTotals'

const row = (o) => ({ qty: 0, free: 0, cost_price: 0, cgst_rate: 0, sgst_rate: 0, igst_rate: 0, ...o })

describe('intakeTotals', () => {
  it('charges qty but NOT free stock', () => {
    // Free goods move inventory and carry no value — that is the column's
    // entire purpose. Charging them silently inflates every purchase.
    const t = intakeTotals([row({ qty: 10, free: 2, cost_price: 100 })])
    expect(t.gross).toBe(1000)
    expect(t.qty).toBe(10)
    expect(t.free).toBe(2)
  })

  it('splits CGST+SGST and IGST to the same effective rate', () => {
    const intra = intakeTotals([row({ qty: 1, cost_price: 100, cgst_rate: 9, sgst_rate: 9 })])
    const inter = intakeTotals([row({ qty: 1, cost_price: 100, igst_rate: 18 })])
    expect(intra.taxTotal).toBeCloseTo(18, 6)
    expect(inter.taxTotal).toBeCloseTo(18, 6)
  })

  it('groups tax into slabs and totals them', () => {
    const t = intakeTotals([
      row({ qty: 1, cost_price: 100, cgst_rate: 9, sgst_rate: 9 }),   // 18%
      row({ qty: 2, cost_price: 50, cgst_rate: 2.5, sgst_rate: 2.5 }), // 5%
      row({ qty: 1, cost_price: 100, igst_rate: 18 }),                 // 18%
    ])
    expect(t.slabs.map(s => s.rate)).toEqual([5, 18])
    expect(t.slabs.find(s => s.rate === 18).taxable).toBe(200)
    expect(t.taxTotal).toBeCloseTo(36 + 5, 6)
  })

  it('applies adjustments in order: gross − itemDisc + tax + cess − cashDisc', () => {
    const t = intakeTotals(
      [row({ qty: 10, cost_price: 100, cgst_rate: 9, sgst_rate: 9 })],
      { item_disc: 100, cess: 50, cash_disc: 25 },
    )
    expect(t.gross).toBe(1000)
    expect(t.taxable).toBe(900)
    expect(t.taxTotal).toBeCloseTo(180, 6)   // tax is on gross, not on the discounted base
    expect(t.payable).toBeCloseTo(900 + 180 + 50 - 25, 6)
  })

  it('ignores unpriced draft rows in the slab breakdown', () => {
    // A half-typed row must not invent a 0% slab in the GST summary.
    const t = intakeTotals([
      row({ qty: 0, cost_price: 0 }),
      row({ qty: 1, cost_price: 100, cgst_rate: 9, sgst_rate: 9 }),
    ])
    expect(t.slabs).toHaveLength(1)
    expect(t.slabs[0].rate).toBe(18)
  })

  it('survives junk without producing NaN', () => {
    const t = intakeTotals([row({ qty: 'abc', cost_price: undefined, free: null })], { cess: 'x' })
    for (const v of [t.gross, t.taxTotal, t.payable, t.qty, t.free]) {
      expect(Number.isFinite(v)).toBe(true)
    }
  })

  it('is empty-safe', () => {
    const t = intakeTotals()
    expect(t.gross).toBe(0)
    expect(t.payable).toBe(0)
    expect(t.lines).toEqual([])
  })

  it('gstRateOf prefers the CGST+SGST pair, else IGST', () => {
    expect(gstRateOf({ cgst_rate: 6, sgst_rate: 6, igst_rate: 12 })).toBe(12)
    expect(gstRateOf({ igst_rate: 5 })).toBe(5)
    expect(gstRateOf({})).toBe(0)
  })
})
