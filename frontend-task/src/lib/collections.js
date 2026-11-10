// lib/collections.js — money collected at shops and its place in BizAssist
// Billing. Modes use billing's words (backend-task/app/collections.py).

export const PAYMENT_MODES = ['Cash', 'UPI', 'Cheque', 'NEFT', 'Card']
export const PAYMENT_MODE_LABELS = { Cash: 'Cash', UPI: 'UPI', Cheque: 'Cheque', NEFT: 'Bank transfer (NEFT/IMPS)', Card: 'Card' }

const r2 = (n) => Math.round((Number(n) || 0) * 100) / 100

/** Where a finished collection stands in billing: null when it isn't one. */
export function billingStatus(task) {
  if (task.billing_confirmed == null) return null
  const got = r2(task.amount_collected)
  const done = r2(task.billing_confirmed)
  if (done >= got - 0.005) return { tone: 'success', text: 'Recorded in billing' }
  if (done > 0) return { tone: 'warning', text: `₹${done.toLocaleString('en-IN')} of ₹${got.toLocaleString('en-IN')} recorded in billing` }
  return { tone: 'muted', text: 'Waiting for you to confirm in billing' }
}
