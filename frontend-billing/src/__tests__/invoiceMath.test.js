// Tests for the invoice money-math extracted from Sales.jsx.
// Money is the most important thing to get right — these lock the totals, the
// intra/inter-state GST split, discounts, the negative-guard, and change due.
import { describe, it, expect } from 'vitest'
import { lineTotal, computeInvoiceTotals, changeDue, buildInvoicePayload, columnTotals, suggestedTenders, schemeDiscount, resolveBillDiscount, roundOffDiscount, paymentBalance, gstSlabBreakdown } from '../utils/invoiceMath'

describe('lineTotal', () => {
  it('qty × price − discount', () => {
    expect(lineTotal({ qty: 2, price: 100, discount: 0 })).toBe(200)
    expect(lineTotal({ qty: 2, price: 100, discount: 50 })).toBe(150)
  })
  it('never goes negative', () => {
    expect(lineTotal({ qty: 1, price: 10, discount: 50 })).toBe(0)
  })
  it('tolerates missing/blank fields', () => {
    expect(lineTotal({})).toBe(0)
    expect(lineTotal({ qty: '3', price: '20' })).toBe(60)
  })
})

describe('schemeDiscount — MRP-as-price scheme (the qty-overcharge bug guard)', () => {
  it('scales with qty: (MRP − chosen) × qty', () => {
    // Sugar 5kg: MRP 240, chosen 200, qty 4 → discount 160 (NOT the buggy 40)
    expect(schemeDiscount(240, 200, 4)).toBe(160)
    expect(schemeDiscount(240, 200, 1)).toBe(40)
  })
  it('with MRP as the unit price, the line bills the chosen price × qty', () => {
    const disc = schemeDiscount(240, 200, 4)
    expect(lineTotal({ qty: 4, price: 240, discount: disc })).toBe(800) // = 200 × 4
  })
  it('no scheme when chosen price is at/above MRP', () => {
    expect(schemeDiscount(240, 240, 4)).toBe(0)
    expect(schemeDiscount(240, 260, 4)).toBe(0)
  })
  it('no scheme when there is no MRP', () => {
    expect(schemeDiscount(0, 200, 4)).toBe(0)
    expect(schemeDiscount(null, 200, 4)).toBe(0)
  })
  it('tolerates string inputs and never goes negative', () => {
    expect(schemeDiscount('240', '200', '3')).toBe(120)
    expect(schemeDiscount(240, 200, 0)).toBe(0)
  })
})

describe('computeInvoiceTotals — intra-state (CGST + SGST)', () => {
  const items = [{ qty: 2, price: 100, discount: 0, cgst_rate: 9, sgst_rate: 9 }]
  const t = computeInvoiceTotals(items, { isIntrastate: true })
  it('splits tax into CGST + SGST, no IGST', () => {
    expect(t.subtotal).toBe(200)
    expect(t.cgstAmt).toBeCloseTo(18, 6)
    expect(t.sgstAmt).toBeCloseTo(18, 6)
    expect(t.igstAmt).toBe(0)
  })
  it('grand total = subtotal + gst', () => {
    expect(t.gstAmt).toBeCloseTo(36, 6)
    expect(t.grandTotal).toBeCloseTo(236, 6)
  })
})

describe('resolveBillDiscount', () => {
  it('flat amount, clamped to [0, subtotal]', () => {
    expect(resolveBillDiscount(380, { type: 'amount', value: 50 })).toBe(50)
    expect(resolveBillDiscount(380, { type: 'amount', value: 9999 })).toBe(380) // capped at subtotal
    expect(resolveBillDiscount(380, { type: 'amount', value: -5 })).toBe(0)
  })
  it('percentage of subtotal', () => {
    expect(resolveBillDiscount(380, { type: 'percent', value: 10 })).toBe(38)
    expect(resolveBillDiscount(380, { type: 'percent', value: 0 })).toBe(0)
  })
  it('zero on empty bill', () => {
    expect(resolveBillDiscount(0, { type: 'percent', value: 10 })).toBe(0)
  })
})

describe('computeInvoiceTotals — bill-level discount (tax on net)', () => {
  const items = [{ qty: 2, price: 240, discount: 100, cgst_rate: 2.5, sgst_rate: 2.5 }] // lineTotal 380, 5% GST
  it('no discount is unchanged (grand = 399)', () => {
    const t = computeInvoiceTotals(items, { isIntrastate: true })
    expect(t.subtotal).toBe(380)
    expect(t.discount).toBe(0)
    expect(t.grandTotal).toBeCloseTo(399, 6)
  })
  it('10% discount reduces taxable AND tax proportionally', () => {
    const t = computeInvoiceTotals(items, { isIntrastate: true, billDiscountType: 'percent', billDiscountValue: 10 })
    expect(t.discount).toBe(38)
    expect(t.discountedSubtotal).toBe(342)
    expect(t.gstAmt).toBeCloseTo(17.1, 6)   // 19 × 0.9
    expect(t.grandTotal).toBeCloseTo(359.1, 6)
  })
  it('flat ₹50 discount', () => {
    const t = computeInvoiceTotals(items, { isIntrastate: true, billDiscountType: 'amount', billDiscountValue: 50 })
    expect(t.discountedSubtotal).toBe(330)
    expect(t.grandTotal).toBeCloseTo(346.5, 6)
  })
})

describe('computeInvoiceTotals — inter-state (IGST)', () => {
  it('uses IGST (cgst+sgst when igst_rate absent), zero CGST/SGST', () => {
    const items = [{ qty: 2, price: 100, discount: 0, cgst_rate: 9, sgst_rate: 9 }]
    const t = computeInvoiceTotals(items, { isIntrastate: false })
    expect(t.cgstAmt).toBe(0)
    expect(t.sgstAmt).toBe(0)
    expect(t.igstAmt).toBeCloseTo(36, 6)
    expect(t.grandTotal).toBeCloseTo(236, 6)
  })
  it('honours an explicit igst_rate', () => {
    const items = [{ qty: 1, price: 1000, discount: 0, igst_rate: 12 }]
    const t = computeInvoiceTotals(items, { isIntrastate: false })
    expect(t.igstAmt).toBeCloseTo(120, 6)
  })
})

describe('computeInvoiceTotals — edge cases', () => {
  it('empty cart → all zero', () => {
    const t = computeInvoiceTotals([], { isIntrastate: true })
    expect(t).toMatchObject({ subtotal: 0, cgstAmt: 0, sgstAmt: 0, igstAmt: 0, gstAmt: 0, grandTotal: 0 })
  })
  it('discount reduces the taxable base', () => {
    const items = [{ qty: 2, price: 100, discount: 100, cgst_rate: 9, sgst_rate: 9 }]
    const t = computeInvoiceTotals(items, { isIntrastate: true })
    expect(t.subtotal).toBe(100)
    expect(t.cgstAmt).toBeCloseTo(9, 6)
  })
})

describe('changeDue', () => {
  it('received − total, floored at 0', () => {
    expect(changeDue(500, 236)).toBe(264)
    expect(changeDue(200, 236)).toBe(0)
    expect(changeDue('', 236)).toBe(0)
  })
})

describe('columnTotals (cart footer row)', () => {
  it('sums qty, discount and line totals', () => {
    const items = [
      { qty: 2, price: 400, discount: 0 },
      { qty: 3, price: 120, discount: 20 },
      { qty: 2, price: 45, discount: 0 },
    ]
    expect(columnTotals(items)).toEqual({ qty: 7, discount: 20, total: 1230 })
  })
  it('empty cart → all zero', () => {
    expect(columnTotals([])).toEqual({ qty: 0, discount: 0, total: 0 })
  })
})

describe('suggestedTenders (payment chips)', () => {
  it('starts with the exact amount, then ascending round-ups', () => {
    expect(suggestedTenders(1377)).toEqual([1377, 1380, 1400, 1500])
  })
  it('collapses duplicates for a round total', () => {
    expect(suggestedTenders(1000)).toEqual([1000, 2000])
  })
  it('small total → round-up ladder', () => {
    expect(suggestedTenders(236)).toEqual([236, 240, 250, 300])
  })
  it('zero / empty → no chips', () => {
    expect(suggestedTenders(0)).toEqual([])
  })
})

describe('buildInvoicePayload (the money contract sent to the backend)', () => {
  const form = {
    customer_id: '5', godown_id: '', due_date: '', notes: '',
    items: [
      { product_id: '12', product: 'Rice', qty: 2, price: 100, discount: 50, cgst_rate: 9, sgst_rate: 9 },
    ],
  }
  const p = buildInvoicePayload({ invoiceNo: 'INV-1001', form, gstEnabled: true })

  it('maps header fields, coercing ids and nulling blanks', () => {
    expect(p.invoice_no).toBe('INV-1001')
    expect(p.customer_id).toBe(5)        // '5' → 5
    expect(p.godown_id).toBeNull()       // '' → null
    expect(p.due_date).toBeNull()
    expect(p.gst_enabled).toBe(true)
  })
  it('sends explicit price and discount directly', () => {
    expect(p.items[0].price).toBe(100)
    expect(p.items[0].discount).toBe(50)
    expect(p.items[0].qty).toBe(2)
    expect(p.items[0].product_id).toBe(12)
  })
  it('derives igst from cgst+sgst when not explicitly set', () => {
    expect(p.items[0].igst_rate).toBe(18)
  })
  it('honours an explicit igst_rate', () => {
    const f = { items: [{ product: 'X', qty: 1, price: 100, igst_rate: 12 }] }
    const out = buildInvoicePayload({ invoiceNo: 'INV-2', form: f, gstEnabled: true })
    expect(out.items[0].igst_rate).toBe(12)
  })
  it('sends cash_discount (0 by default, passed through when given)', () => {
    expect(p.cash_discount).toBe(0)
    const out = buildInvoicePayload({ invoiceNo: 'INV-3', form, gstEnabled: true, cashDiscount: 3 })
    expect(out.cash_discount).toBe(3)
  })
  it('sends paid_amount (0 by default → unpaid; passed through to drive Paid status)', () => {
    expect(p.paid_amount).toBe(0)
    const out = buildInvoicePayload({ invoiceNo: 'INV-4', form, gstEnabled: true, paidAmount: 250 })
    expect(out.paid_amount).toBe(250)
  })
})

describe('computeInvoiceTotals — single post-tax discount + auto round-off (R4)', () => {
  const items = [{ qty: 2, price: 100, discount: 0, cgst_rate: 9, sgst_rate: 9 }] // grand 236 (whole)

  it('zero discount, whole total: payable === grandTotal, no round-off', () => {
    const t = computeInvoiceTotals(items, { isIntrastate: true })
    expect(t.grandTotal).toBeCloseTo(236, 6)
    expect(t.roundedGrandTotal).toBe(236)
    expect(t.roundOff).toBe(0)
    expect(t.cashDiscount).toBe(0)
    expect(t.payable).toBe(236)
  })
  it('reduces the payable but NOT the taxable base or GST', () => {
    const t = computeInvoiceTotals(items, { isIntrastate: true, cashDiscount: 6 })
    expect(t.subtotal).toBe(200)          // taxable unchanged
    expect(t.gstAmt).toBeCloseTo(36, 6)   // GST unchanged
    expect(t.cashDiscount).toBe(6)
    expect(t.payable).toBe(230)           // 236 − 6
  })
  it('auto round-off: a fractional grand total rounds to the nearest rupee', () => {
    // 5% GST on 380 → 19; grand 399 is whole. Use a fractional case:
    const frac = [{ qty: 1, price: 100, discount: 0, cgst_rate: 1.2, sgst_rate: 1.2 }] // taxable 100, gst 2.4 → 102.4
    const t = computeInvoiceTotals(frac, { isIntrastate: true })
    expect(t.grandTotal).toBeCloseTo(102.4, 6)
    expect(t.roundedGrandTotal).toBe(102)
    expect(t.roundOff).toBeCloseTo(-0.4, 6)  // rounded DOWN
    expect(t.payable).toBe(102)
  })
  it('clamps the discount to [0, grandTotal] (never negative)', () => {
    const t = computeInvoiceTotals(items, { isIntrastate: true, cashDiscount: 9999 })
    expect(t.cashDiscount).toBeCloseTo(236, 6)
    expect(t.payable).toBe(0)
  })
})

describe('paymentBalance (signed — shortfall shows red in the UI)', () => {
  it('positive = change to return', () => {
    expect(paymentBalance(500, 236)).toBe(264)
  })
  it('negative = still owed', () => {
    expect(paymentBalance(200, 236)).toBe(-36)
  })
  it('zero = exact', () => {
    expect(paymentBalance(236, 236)).toBe(0)
    expect(paymentBalance('', 0)).toBe(0)
  })
})

describe('gstSlabBreakdown (per-rate receipt tax table)', () => {
  const items = [
    { qty: 1, price: 100, discount: 0, cgst_rate: 9, sgst_rate: 9 },   // 18% slab, taxable 100
    { qty: 2, price: 100, discount: 0, cgst_rate: 2.5, sgst_rate: 2.5 }, // 5% slab, taxable 200
    { qty: 1, price: 50, discount: 0, cgst_rate: 0, sgst_rate: 0 },     // 0% slab, taxable 50
  ]
  it('groups by rate ascending with CGST=SGST and correct taxable', () => {
    const slabs = gstSlabBreakdown(items, { isIntrastate: true })
    expect(slabs.map(s => s.rate)).toEqual([0, 5, 18])
    const s18 = slabs.find(s => s.rate === 18)
    expect(s18.taxable).toBe(100)
    expect(s18.cgst).toBe(9); expect(s18.sgst).toBe(9); expect(s18.gst).toBe(18)
    const s5 = slabs.find(s => s.rate === 5)
    expect(s5.taxable).toBe(200); expect(s5.cgst).toBe(5); expect(s5.sgst).toBe(5)
    const s0 = slabs.find(s => s.rate === 0)
    expect(s0.gst).toBe(0)
  })
  it('inter-state uses IGST, zero CGST/SGST', () => {
    const slabs = gstSlabBreakdown([{ qty: 1, price: 1000, discount: 0, igst_rate: 12 }], { isIntrastate: false })
    expect(slabs[0].igst).toBe(120); expect(slabs[0].cgst).toBe(0); expect(slabs[0].gst).toBe(120)
  })
})

describe('roundOffDiscount', () => {
  it('is the fractional part — rounds the bill down to the nearest rupee', () => {
    expect(roundOffDiscount(1123.40)).toBeCloseTo(0.40, 6)
    expect(roundOffDiscount(236)).toBe(0)
    expect(roundOffDiscount(0)).toBe(0)
  })
})
