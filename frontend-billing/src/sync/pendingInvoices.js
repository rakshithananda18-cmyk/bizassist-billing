// src/sync/pendingInvoices.js — feed queued offline bills back into numbering.
// ===========================================================================
// Offline bills sit in the outbox until reconnect. The POS allocates the next
// invoice number from the SERVER's invoice list — which, while offline, is stale
// and does NOT include the bills still in the queue. If we ignored them, two
// offline bills would compute the SAME `invoice_no` and the backend's inner
// idempotency wall (`invoice_no`) would silently DROP the second one.
//
// So we extract the invoice numbers already sitting in the outbox and merge them
// into the "known invoices" the allocator sees — making each offline bill's
// number unique, exactly as if the server already had it.

/** Invoice numbers carried by queued (pending) outbox ops. */
export function pendingInvoiceNumbers(ops = []) {
  return (ops || [])
    .map((o) => o && o.body && (o.body.invoice_no || o.body.invoiceNo))
    .filter((n) => typeof n === 'string' && n.length > 0)
}

/** Shape the queued numbers like the server invoice rows the allocator expects,
 * so they can be concatenated with the real list. */
export function pendingInvoiceRows(ops = []) {
  return pendingInvoiceNumbers(ops).map((n) => ({ invoice_number: n }))
}
