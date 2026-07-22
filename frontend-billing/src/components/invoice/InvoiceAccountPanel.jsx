// ============================================================================
// InvoiceAccountPanel — the money view for a single invoice (screen-only, not
// printed): each payment received and any linked returns (credit notes).
// Reads GET /invoices/:id/account. Fails soft.
//
// Renders as themed side-panel SECTIONS (reuses the .ivp-label / .ivp-card look
// of the invoice viewer's right panel), so it sits inside that panel rather than
// as a full-width strip. Returns null when there's nothing to show.
// ============================================================================
import React, { useEffect, useState } from 'react'
import { useDocLabels } from '../../hooks/useDocLabels'

const fmt = (n) => `₹${Number(n || 0).toLocaleString('en-IN', { maximumFractionDigits: 2 })}`

export default function InvoiceAccountPanel({ authFetch, invoiceId }) {
  const label = useDocLabels()
  const [acct, setAcct] = useState(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    if (!invoiceId) { setLoading(false); return }
    let cancelled = false
    setLoading(true)
    authFetch(`/invoices/${invoiceId}/account`)
      .then(r => r.ok ? r.json() : null)
      .then(d => { if (!cancelled) setAcct(d) })
      .catch(() => {})
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [authFetch, invoiceId])

  if (loading) {
    return (
      <div>
        <div className="ivp-label">Payments</div>
        <div className="ivp-card">
          <span style={{ fontSize: '0.8rem', color: 'var(--text-muted)' }}>Loading…</span>
        </div>
      </div>
    )
  }
  if (!acct) return null

  const hasPayments = acct.payments?.length > 0
  const hasReturns = acct.returns?.length > 0
  if (!hasPayments && !hasReturns) return null

  return (
    <>
      {hasPayments && (
        <div>
          <div className="ivp-label">Payments Received</div>
          <div className="ivp-card" style={{ gap: 0, padding: 0, overflow: 'hidden' }}>
            {acct.payments.map((p, i) => (
              <div key={p.id} style={{
                display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start',
                padding: '9px 13px', gap: 10,
                borderTop: i > 0 ? '1px solid var(--border)' : 'none',
              }}>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 2, minWidth: 0 }}>
                  <span style={{ fontSize: '0.8rem', fontWeight: 600, color: 'var(--text-primary)' }}>{p.date}</span>
                  <span style={{ fontSize: '0.7rem', color: 'var(--text-muted)', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                    {p.method}{p.note ? ` · ${p.note}` : ''}
                  </span>
                </div>
                <span style={{ fontSize: '0.85rem', fontWeight: 700, color: 'var(--success)', whiteSpace: 'nowrap' }}>
                  {fmt(p.amount)}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      {hasReturns && (
        <div>
          <div className="ivp-label">Returns ({label('sale_return')}s)</div>
          <div className="ivp-card" style={{ gap: 0, padding: 0, overflow: 'hidden' }}>
            {acct.returns.map((r, i) => (
              <div key={r.id} style={{
                display: 'flex', justifyContent: 'space-between', alignItems: 'center',
                padding: '9px 13px', gap: 10,
                borderTop: i > 0 ? '1px solid var(--border)' : 'none',
              }}>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
                  <span style={{ fontSize: '0.8rem', fontWeight: 600, color: 'var(--text-primary)' }}>{r.credit_note_no}</span>
                  <span style={{ fontSize: '0.7rem', color: 'var(--text-muted)' }}>{r.date}</span>
                </div>
                <span style={{ fontSize: '0.85rem', fontWeight: 700, color: 'var(--danger)', whiteSpace: 'nowrap' }}>
                  −{fmt(r.amount)}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}
    </>
  )
}
