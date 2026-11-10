// lib/invoices.js — what picked billing invoices fill in on a task.
// Same defaults as backend-task/app/invoices.py attach_invoices(); the server
// applies them too, so these only show the owner the values before saving.

// Task types that carry invoices: a bill is delivered once and collected once.
export const INVOICE_TASK_TYPES = ['delivery', 'payment_collect']

const REF_MAX = 200

export function summarizeInvoices(invoices) {
  const list = invoices || []
  const boxes = list.map(i => i.boxes).filter(b => b != null)
  const ref = list.map(i => i.number).join(', ')
  return {
    invoice_ids: list.map(i => i.id),
    reference: ref.length <= REF_MAX ? ref : ref.slice(0, REF_MAX - 1) + '…',
    boxes: boxes.length ? boxes.reduce((a, b) => a + b, 0) : null,
    orders_count: list.length,
    balance_due: Math.round(list.reduce((a, i) => a + (i.balance_due || 0), 0) * 100) / 100,
  }
}

// The live task of this kind that already carries the invoice, if any.
export function takenBy(invoice, taskType) {
  return (invoice.tasks || []).find(t => t.task_type === taskType) || null
}

const amount = value => {
  if (value == null || value === '') return null
  const parsed = Number(value)
  return Number.isFinite(parsed) && parsed >= 0 ? Math.round(parsed * 100) / 100 : null
}

// A task's amount_expected and invoice balances are planning snapshots. Once
// Billing records a payment, only its current balance can authorize collecting
// that money again. Missing live data must never fall back to a stale snapshot.
export function collectionAmounts(task) {
  const planned = amount(task?.amount_expected)
  const linked = Boolean(task?.invoices?.length) || typeof task?.billing_balance_available === 'boolean'
  if (!linked) return { linked: false, available: true, planned, currentDue: null, suggested: planned }
  const currentDue = amount(task?.current_amount_due)
  const available = task?.billing_balance_available === true && currentDue !== null
  return {
    linked: true,
    available,
    planned,
    currentDue: available ? currentDue : null,
    suggested: available ? Math.min(planned ?? currentDue, currentDue) : null,
  }
}
