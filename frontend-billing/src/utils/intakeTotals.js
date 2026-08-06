// utils/intakeTotals.js — the one place stock-intake money is added up.
// ----------------------------------------------------------------------------
// The same arithmetic was written out in Stock.jsx's printGRN and again in
// IntakePurchasePanel (a third copy sat in a dead fallback until it was
// deleted). Three transcriptions of one calculation is how a printed GRN and an
// on-screen summary end up disagreeing about what a delivery cost.
//
// `free` quantity is deliberately NOT charged — free goods move stock but carry
// no value, which is the whole point of the column.

export const gstRateOf = (r) =>
  (parseFloat(r?.cgst_rate) || 0) + (parseFloat(r?.sgst_rate) || 0) ||
  (parseFloat(r?.igst_rate) || 0)

const num = (v) => {
  const n = parseFloat(v)
  return Number.isFinite(n) ? n : 0
}

/**
 * Per-row and whole-sheet totals for a stock intake.
 *
 * Returns `{ lines, gross, slabs, taxTotal, itemDisc, taxable, cess, cashDisc,
 * payable, qty, free }` — `lines` mirrors `rows` 1:1 so a table can render
 * amounts without recomputing them per cell.
 */
export function intakeTotals(rows = [], adjustments = {}) {
  const lines = rows.map((r) => {
    const qty = num(r.qty)
    const free = num(r.free)
    const cost = num(r.cost_price)
    const rate = gstRateOf(r)
    const taxable = qty * cost
    const tax = taxable * rate / 100
    return { row: r, qty, free, cost, rate, taxable, tax, net: taxable + tax }
  })

  const gross = lines.reduce((s, l) => s + l.taxable, 0)
  const qty = lines.reduce((s, l) => s + l.qty, 0)
  const free = lines.reduce((s, l) => s + l.free, 0)

  // GST slab breakdown, keyed by rate. Zero-value rows are skipped so an
  // unpriced draft line doesn't invent a 0% slab.
  const slabMap = {}
  for (const l of lines) {
    if (l.qty <= 0 || l.cost <= 0) continue
    if (!slabMap[l.rate]) slabMap[l.rate] = { rate: l.rate, taxable: 0, tax: 0 }
    slabMap[l.rate].taxable += l.taxable
    slabMap[l.rate].tax += l.tax
  }
  const slabs = Object.values(slabMap).sort((a, b) => a.rate - b.rate)
  const taxTotal = slabs.reduce((s, x) => s + x.tax, 0)

  const itemDisc = num(adjustments?.item_disc)
  const cess = num(adjustments?.cess)
  const cashDisc = num(adjustments?.cash_disc)
  const taxable = gross - itemDisc

  return {
    lines, gross, slabs, taxTotal,
    itemDisc, taxable, cess, cashDisc,
    payable: taxable + taxTotal + cess - cashDisc,
    qty, free,
  }
}

export default intakeTotals
