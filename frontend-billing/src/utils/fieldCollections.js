// utils/fieldCollections.js — checking the owner's split of a Field Team
// collection across bills before it is sent. The server (core/field_team.py)
// enforces the same rules; this only explains a refusal before it happens.

const CENT = 0.005
const r2 = (n) => Math.round((Number(n) || 0) * 100) / 100

/**
 * @param collection  one row of GET /field-collections
 * @param amounts     { [invoice_id]: string|number } the owner's split
 */
export function checkSplit(collection, amounts) {
  const rows = collection.bills.map(b => ({ ...b, amount: r2(amounts[b.invoice_id]) }))
  const total = r2(rows.reduce((a, b) => a + b.amount, 0))
  const overBill = rows.filter(b => b.amount > b.balance_due + CENT).map(b => b.number)
  const over = total > collection.remaining + CENT
  const allocations = rows.filter(b => b.amount > 0).map(b => ({ invoice_id: b.invoice_id, amount: b.amount }))
  let problem = null
  if (overBill.length) problem = `More than is due on ${overBill.join(', ')}`
  else if (over) problem = `Only ₹${collection.remaining.toLocaleString('en-IN')} of this collection is left to confirm`
  else if (!allocations.length) problem = 'Enter an amount for at least one bill'
  return { total, left: r2(collection.remaining - total), allocations, problem }
}

/** The server's oldest-bill-first suggestion as the form's starting values. */
export function startingSplit(collection) {
  return Object.fromEntries(collection.suggested.map(s => [s.invoice_id, String(s.amount)]))
}
