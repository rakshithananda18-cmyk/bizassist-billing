// ============================================================================
// SettleDuesModal — owner-only "customer pays a lump sum" flow.
// Applies one receipt across the customer's outstanding invoices oldest-first
// (FIFO) via POST /customers/:id/settle, then shows the per-invoice allocation
// and any advance banked as credit for the next bill.
// ============================================================================
import React, { useEffect, useState } from 'react'
import CustomSelect from '../common/CustomSelect'
import { CheckIcon, CloseIcon } from '../Icons'

const fmt = (n) => `₹${Number(n || 0).toLocaleString('en-IN', { maximumFractionDigits: 2 })}`

export default function SettleDuesModal({ authFetch, onClose, onDone, presetCustomerId = null, presetCustomerName = null, presetOutstanding = null, presetCreditBalance = 0 }) {
  const [customers, setCustomers] = useState(
    presetCustomerId ? [{ id: presetCustomerId, name: presetCustomerName || 'Customer' }] : []
  )
  const [customerId, setCustomerId] = useState(presetCustomerId ? String(presetCustomerId) : '')
  const [amount, setAmount] = useState(presetOutstanding != null ? String(presetOutstanding) : '')
  const [method, setMethod] = useState('Cash')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState('')
  const [result, setResult] = useState(null)

  useEffect(() => {
    // Case 1: customer id already known — lock it, skip list fetch
    if (presetCustomerId) return
    // Case 2: only name known — fetch list and auto-select by name
    let cancelled = false
    authFetch('/customers?per_page=500')
      .then(r => r.ok ? r.json() : null)
      .then(data => {
        if (cancelled || !data) return
        const list = Array.isArray(data) ? data : (data.customers || data.items || [])
        setCustomers(list)
        // Auto-select the customer whose name matches the preset (case-insensitive)
        if (presetCustomerName && !customerId) {
          const match = list.find(c =>
            (c.name || c.customer_name || '').toLowerCase() === presetCustomerName.toLowerCase()
          )
          if (match) setCustomerId(String(match.id))
        }
      })
      .catch(() => {})
    return () => { cancelled = true }
  }, [authFetch, presetCustomerId, presetCustomerName])

  const selected = customers.find(c => String(c.id) === String(customerId))

  const submit = async () => {
    setError('')
    const amt = parseFloat(amount)
    if (!customerId) { setError('Choose a customer.'); return }
    if (!amt || amt <= 0) { setError('Enter an amount greater than 0.'); return }
    setSubmitting(true)
    try {
      // Don't send a client-computed date: the browser's local/UTC "today" can
      // be a day off from the business (IST) date near midnight. The backend
      // stamps the receipt with the business-timezone date (biz_today_str).
      const res = await authFetch(`/customers/${customerId}/settle`, {
        method: 'POST',
        body: JSON.stringify({
          amount: amt, payment_mode: method,
          idempotency_key: `settle-${customerId}-${Date.now()}`,
        }),
      })
      const data = await res.json().catch(() => ({}))
      if (!res.ok) { setError(data.detail || 'Could not settle dues.'); return }
      setResult(data)
      onDone && onDone(data)
    } catch {
      setError('Network error — please try again.')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="modal-overlay" onClick={e => e.target === e.currentTarget && onClose()}>
      <div className="modal" style={{ maxWidth: 560 }}>
        <div className="modal-header">
          <span className="modal-title">Settle Customer Dues</span>
          <button className="btn btn-ghost btn-icon" onClick={onClose} aria-label="Close"><CloseIcon size={16} /></button>
        </div>

        {!result ? (
          <>
            <div className="modal-body">
              <div className="form-group mb-4">
                <label className="form-label">Customer</label>
                {/* Lock the field when we have a preset (either by id or by name-auto-select) */}
                {(presetCustomerId || presetCustomerName) ? (
                  <>
                    <input className="form-input" value={presetCustomerName || presetCustomerId || 'Customer'} disabled />
                    <div style={{ fontSize: '0.78rem', color: 'var(--text-muted)', marginTop: 4 }}>
                      Outstanding: <strong>{fmt(presetOutstanding || 0)}</strong>
                      {presetCreditBalance > 0 && <> · Advance on account: <strong>{fmt(presetCreditBalance)}</strong></>}
                    </div>
                  </>
                ) : (
                  <CustomSelect className="form-select" value={customerId} onChange={e => setCustomerId(e.target.value)}>
                    <option value="">Choose a customer…</option>
                    {customers.map(c => (
                      <option key={c.id} value={c.id}>
                        {c.name}{c.outstanding ? ` — due ${fmt(c.outstanding)}` : ''}
                      </option>
                    ))}
                  </CustomSelect>
                )}
                {/* Show outstanding from API data when no preset (free-pick mode) */}
                {!presetCustomerId && !presetCustomerName && selected && (
                  <div style={{ fontSize: '0.78rem', color: 'var(--text-muted)', marginTop: 4 }}>
                    Outstanding: <strong>{fmt(selected.outstanding || 0)}</strong>
                    {selected.credit_balance > 0 && <> · Advance on account: <strong>{fmt(selected.credit_balance)}</strong></>}
                  </div>
                )}
              </div>
              <div className="grid grid-2 gap-3 mb-4">
                <div className="form-group">
                  <label className="form-label">
                    Amount received (₹)
                    {presetOutstanding != null && (
                      <span style={{ fontWeight: 400, color: 'var(--text-muted)', marginLeft: 6, fontSize: '0.75rem' }}>
                        · pre-filled from due
                      </span>
                    )}
                  </label>
                  <input type="number" className="form-input" placeholder="0.00" min="0" step="any"
                         value={amount} onChange={e => setAmount(e.target.value)} />
                </div>
                <div className="form-group">
                  <label className="form-label">Method</label>
                  <CustomSelect className="form-select" value={method} onChange={e => setMethod(e.target.value)}>
                    <option value="Cash">Cash</option>
                    <option value="UPI">UPI</option>
                    <option value="Bank">Bank Transfer</option>
                    <option value="Cheque">Cheque</option>
                  </CustomSelect>
                </div>
              </div>
              <div style={{ fontSize: '0.78rem', color: 'var(--text-muted)', lineHeight: 1.5 }}>
                Clears the oldest bills first. Any extra beyond all dues is kept as an advance and auto-applied to the next bill.
              </div>
              {error && <div className="alert alert-danger mt-3" style={{ padding: '8px 12px', fontSize: '0.82rem' }}>{error}</div>}
            </div>
            <div className="modal-footer">
              <button className="btn btn-secondary" onClick={onClose}>Cancel</button>
              <button className="btn btn-primary" disabled={submitting} onClick={submit}>
                {submitting ? 'Settling…' : <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}><CheckIcon size={14} /> Settle</span>}
              </button>
            </div>
          </>
        ) : (
          <>
            <div className="modal-body">
              <div className="alert alert-success mb-3" style={{ padding: '8px 12px', fontSize: '0.84rem' }}>
                Applied {fmt(result.total_applied)} across {result.allocations.length} invoice(s).
                {result.advance > 0 && <> Advance kept for next bill: <strong>{fmt(result.advance)}</strong>.</>}
              </div>
              <div className="data-table-wrap" style={{ maxHeight: 260, overflowY: 'auto' }}>
                <table className="data-table" style={{ fontSize: '0.82rem' }}>
                  <thead><tr>
                    <th>Invoice</th>
                    <th style={{ textAlign: 'right' }}>Applied</th>
                    <th style={{ textAlign: 'right' }}>Remaining</th>
                    <th>Status</th>
                  </tr></thead>
                  <tbody>
                    {result.allocations.map(a => (
                      <tr key={a.invoice_id}>
                        <td className="td-primary">{a.invoice_no}</td>
                        <td style={{ textAlign: 'right' }}>{fmt(a.applied)}</td>
                        <td style={{ textAlign: 'right' }}>{fmt(a.remaining_after)}</td>
                        <td>{a.status}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
            <div className="modal-footer">
              <button className="btn btn-primary" onClick={onClose}>Done</button>
            </div>
          </>
        )}
      </div>
    </div>
  )
}
