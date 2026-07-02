// src/invoice/formatters.js — presentation-only formatting for invoice templates.
// ==============================================================================
// Templates NEVER compute money: every figure arrives pre-computed in the
// InvoicePrintPayload. These helpers only FORMAT what the payload provides.

/** ₹ formatting with Indian digit grouping. `null/undefined` → em-dash. */
export function inr(v, { dash = '—' } = {}) {
  if (v === null || v === undefined) return dash
  const n = Number(v)
  if (Number.isNaN(n)) return dash
  return '₹' + n.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

/** Plain 2dp number (for tax columns where the ₹ repeats too much). */
export function n2(v) {
  const n = Number(v || 0)
  return n.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

/** Quantity without trailing zeros (4 → "4", 2.5 → "2.5"). */
export function qty(v) {
  const n = Number(v || 0)
  return String(parseFloat(n.toFixed(3)))
}

/** GST rate label: 18 → "18%", 0 → "0%". */
export function pct(v) {
  return `${parseFloat(Number(v || 0).toFixed(2))}%`
}

/** Payment status → chip descriptor (Modern template). */
export function statusChip(totals) {
  const due = Number(totals?.balance_due || 0)
  const paid = Number(totals?.amount_paid || 0)
  if (due <= 0.005) return { label: 'PAID', tone: 'success' }
  if (paid > 0) return { label: 'PARTIALLY PAID', tone: 'warning' }
  return { label: 'PAYMENT DUE', tone: 'danger' }
}

/** Column visibility helper: `has(payload, 'hsn')`. */
export function has(payload, col) {
  return (payload?.visibility?.columns || []).includes(col)
}
