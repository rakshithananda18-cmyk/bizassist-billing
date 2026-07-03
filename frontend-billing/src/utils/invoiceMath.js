// src/utils/invoiceMath.js — the invoice money-math, pure and unit-tested.
// ======================================================================
// Extracted verbatim from Sales.jsx so the totals/GST split can be tested in
// isolation (no React, no state) and reused by the print view, the payment
// panel, and any future quote/estimate screen. Logic is unchanged.
//
// Convention (matches the backend `create_sale_invoice`): intra-state = CGST+SGST,
// inter-state = IGST. The caller decides `isIntrastate` (buyer state vs merchant
// state) and passes it in — this module stays free of component state.

/** One line's net amount: qty × price − discount, floored at 0. */
export const lineTotal = (item) => {
  const q = parseFloat(item.qty) || 0
  const p = parseFloat(item.price) || 0
  const d = parseFloat(item.discount) || 0
  return Math.max(0, (q * p) - d)
}

/**
 * Totals for a whole invoice.
 * @param {Array} items - line items ({ qty, price, discount, cgst_rate, sgst_rate, igst_rate })
 * @param {{isIntrastate?: boolean}} opts
 * @returns {{subtotal,cgstAmt,sgstAmt,igstAmt,gstAmt,grandTotal}}
 */
/**
 * Resolve a bill-level discount to an absolute rupee amount, clamped to [0, subtotal].
 * `type` is 'amount' (flat ₹) or 'percent' (% of the pre-tax subtotal).
 * Pure so the counter, the breakdown card, and the save payload all agree.
 * @param {number} subtotal
 * @param {{type?: 'amount'|'percent', value?: number}} opts
 * @returns {number} discount in rupees, never more than the subtotal
 */
export function resolveBillDiscount(subtotal, { type = 'amount', value = 0 } = {}) {
  const s = parseFloat(subtotal) || 0
  const v = parseFloat(value) || 0
  if (v <= 0 || s <= 0) return 0
  const amt = type === 'percent' ? (s * v) / 100 : v
  return Math.min(Math.max(amt, 0), s)
}

/**
 * Totals for a whole invoice, with an optional bill-level discount.
 * The discount reduces the taxable base; GST is then charged on the NET, so the
 * raw per-line tax is scaled by the same factor (proportional apportionment) —
 * matching how the backend persists it. With no discount (default) this is the
 * original behaviour exactly.
 * @param {Array} items
 * @param {{isIntrastate?: boolean, billDiscountType?: 'amount'|'percent', billDiscountValue?: number}} opts
 * @returns {{subtotal,discount,discountedSubtotal,cgstAmt,sgstAmt,igstAmt,gstAmt,grandTotal}}
 */
export function computeInvoiceTotals(items = [], { isIntrastate = true, billDiscountType = 'amount', billDiscountValue = 0, cashDiscount = 0 } = {}) {
  const subtotal = items.reduce((sum, item) => sum + lineTotal(item), 0)

  const discount = resolveBillDiscount(subtotal, { type: billDiscountType, value: billDiscountValue })
  const factor = subtotal > 0 ? (subtotal - discount) / subtotal : 0
  const discountedSubtotal = subtotal - discount

  const rawCgst = items.reduce((sum, item) => {
    const rate = parseFloat(item.cgst_rate) || 0
    return sum + (isIntrastate ? lineTotal(item) * (rate / 100) : 0)
  }, 0)

  const rawSgst = items.reduce((sum, item) => {
    const rate = parseFloat(item.sgst_rate) || 0
    return sum + (isIntrastate ? lineTotal(item) * (rate / 100) : 0)
  }, 0)

  const rawIgst = items.reduce((sum, item) => {
    const cgstR = parseFloat(item.cgst_rate) || 0
    const sgstR = parseFloat(item.sgst_rate) || 0
    const rate = item.igst_rate ? parseFloat(item.igst_rate) : (cgstR + sgstR)
    return sum + (!isIntrastate ? lineTotal(item) * (rate / 100) : 0)
  }, 0)

  const cgstAmt = rawCgst * factor
  const sgstAmt = rawSgst * factor
  const igstAmt = rawIgst * factor
  const gstAmt = cgstAmt + sgstAmt + igstAmt
  const grandTotal = discountedSubtotal + gstAmt

  // Single post-tax cash discount: trims the PAYABLE only — never the taxable base
  // or GST (the "Cash Dis" line on real retail receipts). Clamped to [0, grandTotal].
  const cashDisc = Math.min(Math.max(parseFloat(cashDiscount) || 0, 0), grandTotal)

  // AUTOMATIC round-off: the grand total is rounded to the nearest rupee (matching
  // how the backend persists `grand = round(raw_total)`), so the counter always
  // shows a clean figure. roundOff is signed (negative if rounded down).
  const roundedGrandTotal = Math.round(grandTotal)
  const roundOff = +(roundedGrandTotal - grandTotal).toFixed(2)

  // Payable = the auto-rounded total minus the cash discount, floored at 0.
  const payable = Math.max(0, +(roundedGrandTotal - cashDisc).toFixed(2))
  return {
    subtotal, discount, discountedSubtotal, cgstAmt, sgstAmt, igstAmt, gstAmt,
    grandTotal, roundedGrandTotal, roundOff, cashDiscount: cashDisc, payable,
  }
}

/**
 * Signed payment balance for the counter: amountReceived − payable.
 *   > 0 → change to return to the customer
 *   < 0 → still owed (show in red)
 *   = 0 → exact
 * (Unlike `changeDue`, this is NOT floored at 0 — the UI needs the shortfall.)
 */
export function paymentBalance(amountReceived, payable) {
  return +(((parseFloat(amountReceived) || 0) - (parseFloat(payable) || 0)).toFixed(2))
}

/**
 * The discount that rounds a grand total DOWN to the nearest rupee. Retained as a
 * pure helper (round-off is now automatic in computeInvoiceTotals).
 */
export function roundOffDiscount(grandTotal) {
  const g = parseFloat(grandTotal) || 0
  if (g <= 0) return 0
  return Math.max(0, +(g - Math.floor(g)).toFixed(2))
}

/**
 * Per-slab GST breakdown for the receipt's tax table (matches the retail receipt:
 * one row per GST rate with taxable value + CGST/SGST/IGST). Tax-exclusive — the
 * line total is the taxable base and GST sits on top, same as computeInvoiceTotals.
 * @returns {Array<{rate,taxable,cgst,sgst,igst,gst}>} sorted by rate ascending
 */
export function gstSlabBreakdown(items = [], { isIntrastate = true } = {}) {
  const slabs = {}
  for (const it of items) {
    const taxable = lineTotal(it)
    const cgstR = parseFloat(it.cgst_rate) || 0
    const sgstR = parseFloat(it.sgst_rate) || 0
    const igstR = it.igst_rate ? parseFloat(it.igst_rate) : (cgstR + sgstR)
    const rate = isIntrastate ? (cgstR + sgstR) : igstR
    if (!slabs[rate]) slabs[rate] = { rate, taxable: 0, cgst: 0, sgst: 0, igst: 0 }
    const s = slabs[rate]
    s.taxable += taxable
    if (isIntrastate) { s.cgst += taxable * cgstR / 100; s.sgst += taxable * sgstR / 100 }
    else { s.igst += taxable * igstR / 100 }
  }
  return Object.values(slabs)
    .sort((a, b) => a.rate - b.rate)
    .map(s => ({
      rate: s.rate,
      taxable: +s.taxable.toFixed(2),
      cgst: +s.cgst.toFixed(2),
      sgst: +s.sgst.toFixed(2),
      igst: +s.igst.toFixed(2),
      gst: +(s.cgst + s.sgst + s.igst).toFixed(2),
    }))
}

/** Cash to hand back: max(0, received − grandTotal). */
export const changeDue = (amountReceived, grandTotal) =>
  Math.max(0, (parseFloat(amountReceived) || 0) - grandTotal)

/**
 * Per-column totals for the cart footer row: summed quantity, summed discount,
 * and the summed line totals (= the pre-tax subtotal). Pure so the footer can't
 * drift from the real numbers.
 */
export function columnTotals(items = []) {
  return items.reduce(
    (acc, item) => {
      acc.qty += parseFloat(item.qty) || 0
      acc.discount += parseFloat(item.discount) || 0
      acc.total += lineTotal(item)
      return acc
    },
    { qty: 0, discount: 0, total: 0 },
  )
}

/**
 * The auto "MRP-as-price" scheme discount for a whole line.
 * ------------------------------------------------------------------
 * The counter shows MRP as the unit price and books the gap to the chosen price
 * as a discount, so the bill displays the customer's saving. Because the line
 * total is `qty × price − discount`, that discount is an ABSOLUTE amount and so
 * MUST scale with qty — `(MRP − chosenPrice) × qty`. Keeping this in one pure,
 * tested place is the whole point: it previously lived inline in 5 spots and the
 * qty field forgot to rescale it, which silently overcharged toward MRP.
 *
 * Returns 0 when there is no scheme: no MRP, or the chosen price is above MRP
 * (then the chosen price is used directly with no discount).
 * @param {number} mrp           the product MRP (per unit)
 * @param {number} chosenPrice   the price the cashier actually selected (per unit)
 * @param {number} qty           line quantity
 * @returns {number} absolute discount for the line, floored at 0
 */
export function schemeDiscount(mrp, chosenPrice, qty) {
  const m = parseFloat(mrp) || 0
  const c = parseFloat(chosenPrice) || 0
  const q = parseFloat(qty) || 0
  if (m <= 0 || c > m) return 0
  return Math.max(0, (m - c) * q)
}

/**
 * Smart cash-tender chips for the payment popup: the exact amount, then a few
 * sensible round-ups / common notes ABOVE the total, so the cashier taps once
 * instead of typing. Always returns `count` ascending, de-duplicated values
 * starting at the exact (ceil'd) amount. e.g. 1377 → [1377, 1380, 1400, 1500].
 */
export function suggestedTenders(grandTotal, count = 4) {
  const exact = Math.ceil((Number(grandTotal) || 0) - 1e-9)
  if (exact <= 0) return []
  const ceilTo = (step) => Math.ceil(exact / step) * step
  const notes = [50, 100, 200, 500, 2000].filter((n) => n >= exact)
  const candidates = [exact, ceilTo(10), ceilTo(50), ceilTo(100), ceilTo(500), ...notes]
  const seen = new Set()
  const out = []
  for (const v of candidates.sort((a, b) => a - b)) {
    if (!seen.has(v)) { seen.add(v); out.push(v) }
    if (out.length >= count) break
  }
  return out
}

/**
 * Build the exact body POSTed to /billing/invoices — the money contract with the
 * backend. Pure so it can be unit-tested (a bug here means a wrong bill saved).
 * `price` is sent as the per-unit price AFTER spreading the line discount across
 * the quantity (effectivePrice), matching what the counter showed.
 * @param {{invoiceNo:string, form:object, gstEnabled:boolean}} args
 */
export function buildInvoicePayload({ invoiceNo, form, gstEnabled, billDiscount = 0, cashDiscount = 0, paidAmount = 0, markPaid = false }) {
  return {
    invoice_no: invoiceNo,
    customer_id: form.customer_id ? parseInt(form.customer_id) : null,
    godown_id: form.godown_id ? parseInt(form.godown_id) : null,
    due_date: form.due_date || null,
    gst_enabled: gstEnabled,
    bill_discount: parseFloat(billDiscount) || 0,   // whole-invoice PRE-tax discount (absolute ₹)
    cash_discount: parseFloat(cashDiscount) || 0,   // POST-tax cash discount / round-off (absolute ₹)
    paid_amount: parseFloat(paidAmount) || 0,       // amount received now → drives Paid/Partial/Unpaid status
    mark_paid: !!markPaid,                           // "Paid & Print" → settle full payable exactly
    payment_mode: form.payment_mode || null,         // cash|upi|card|credit — drives shift drawer tallies (Phase 3)
    notes: form.notes || null,
    items: form.items.map((it) => {
      const q = parseFloat(it.qty) || 1
      const p = parseFloat(it.price) || 0
      const d = parseFloat(it.discount) || 0
      const effectivePrice = Math.max(0, (q * p - d) / q)
      return {
        product_id: it.product_id ? parseInt(it.product_id) : null,
        product: it.product,
        qty: q,
        price: effectivePrice,
        batch_no: it.batch_no || null,
        expiry_date: it.expiry_date || null,
        serial_no: it.serial_no || null,   // electronics/mobile/repair verticals (Phase 2 line fields)
        // Dynamic vertical fields (size/colour/warranty…) — packed as a JSON
        // blob; presentation-only, never enters the money math.
        attributes: (it.attributes && Object.keys(it.attributes).length > 0) ? it.attributes : null,
        cgst_rate: parseFloat(it.cgst_rate) || 0,
        sgst_rate: parseFloat(it.sgst_rate) || 0,
        igst_rate: it.igst_rate
          ? parseFloat(it.igst_rate)
          : ((parseFloat(it.cgst_rate) || 0) + (parseFloat(it.sgst_rate) || 0)),
      }
    }),
  }
}
