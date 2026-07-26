// Unit tests for the B2B order cart maths (components/b2b/useOrderCart).
// These numbers become a real purchase order, so they get tested without a DOM.
import { describe, it, expect } from 'vitest'
import { computeLine, computeTotals } from '../b2b/useOrderCart'

const product = (over = {}) => ({
  product_id: 1, name: 'Asian Paints Apex 10L',
  selling_price: 100, cgst_rate: 9, sgst_rate: 9, igst_rate: 0,
  ...over,
})

describe('computeLine', () => {
  it('applies tax on the connection-discounted unit price × quantity', () => {
    const l = computeLine(product(), 3)
    expect(l.line_subtotal).toBe(300)
    expect(l.line_cgst).toBe(27)
    expect(l.line_sgst).toBe(27)
    expect(l.line_igst).toBe(0)
    expect(l.line_total).toBe(354)
  })

  it('handles an inter-state (IGST-only) product', () => {
    const l = computeLine(product({ cgst_rate: 0, sgst_rate: 0, igst_rate: 18 }), 2)
    expect(l.line_cgst).toBe(0)
    expect(l.line_igst).toBe(36)
    expect(l.line_total).toBe(236)
  })

  it('rounds to paise rather than carrying float noise', () => {
    const l = computeLine(product({ selling_price: 33.333 }), 3)
    expect(l.line_subtotal).toBe(100)
    expect(Number.isInteger(Math.round(l.line_total * 100))).toBe(true)
  })

  it('treats a missing or junk quantity as zero instead of NaN', () => {
    expect(computeLine(product(), undefined).line_total).toBe(0)
    expect(computeLine(product(), 'abc').line_total).toBe(0)
  })

  it('supports fractional quantities (loose goods sold by weight)', () => {
    expect(computeLine(product(), 2.5).line_subtotal).toBe(250)
  })
})

describe('computeTotals', () => {
  it('rolls up subtotal, each tax head, and the payable total', () => {
    const lines = [
      computeLine(product(), 2),
      computeLine(product({ product_id: 2, selling_price: 50, cgst_rate: 6, sgst_rate: 6 }), 4),
    ]
    const t = computeTotals(lines)
    expect(t.subtotal).toBe(400)     // 200 + 200
    expect(t.cgst).toBe(30)          // 18 + 12
    expect(t.sgst).toBe(30)
    expect(t.tax).toBe(60)
    expect(t.total).toBe(460)
  })

  it('is zero across the board for an empty cart', () => {
    expect(computeTotals([])).toEqual({ subtotal: 0, cgst: 0, sgst: 0, igst: 0, tax: 0, total: 0 })
  })

  it('keeps total === subtotal + tax exactly (no rounding drift)', () => {
    const lines = [
      computeLine(product({ selling_price: 19.99, cgst_rate: 2.5, sgst_rate: 2.5 }), 7),
      computeLine(product({ product_id: 3, selling_price: 3.33, cgst_rate: 9, sgst_rate: 9 }), 11),
    ]
    const t = computeTotals(lines)
    expect(t.total).toBeCloseTo(t.subtotal + t.tax, 2)
  })
})
