// ============================================================================
// PartyAccount — the drill-down: everything about one customer on ONE screen.
// Header (outstanding + advance), quick actions (Settle · Record Payment ·
// Remind), and their ledger of invoices/payments. Removes the tab-hopping.
// Reads GET /customers/:id/ledger (entries + credit_balance).
// ============================================================================
import React, { useEffect, useState, useCallback } from 'react'
import { CheckIcon, MessageIcon, CashIcon } from '../Icons'
import InvoiceActions from '../invoice/InvoiceActions'

const fmt = (n) => `₹${Number(n || 0).toLocaleString('en-IN', { maximumFractionDigits: 2 })}`

function StatusTag({ status }) {
  const s = (status || '').toLowerCase()
  const color = s === 'paid' ? '#166534' : s === 'partial' ? '#b45309' : '#b4462f'
  const bg = s === 'paid' ? 'rgba(22,101,52,0.10)' : s === 'partial' ? 'rgba(180,83,9,0.10)' : 'rgba(180,70,47,0.10)'
  return <span style={{ padding: '2px 8px', borderRadius: 10, fontSize: '0.72rem', fontWeight: 700, color, background: bg }}>{status || '—'}</span>
}

export default function PartyAccount({ authFetch, party, onBack, actions, onSettle, onRecordPayment, onReminder, reloadKey = 0 }) {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)

  const load = useCallback(() => {
    if (!party?.id) return
    setLoading(true)
    authFetch(`/customers/${party.id}/ledger`)
      .then(r => r.ok ? r.json() : null)
      .then(d => setData(d))
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [authFetch, party?.id])

  useEffect(() => { load() }, [load, reloadKey])

  const outstanding = data?.outstanding_total ?? party?.outstanding_balance ?? 0
  const credit = data?.credit_balance ?? party?.credit_balance ?? 0
  const entries = (data?.entries || []).filter(e => e.type === 'invoice')

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'flex-start', gap: 16, flexWrap: 'wrap' }}>
        <button className="btn btn-ghost btn-sm" onClick={onBack} aria-label="Back">← Back</button>
        <div style={{ flex: 1, minWidth: 200 }}>
          <div style={{ fontSize: '1.15rem', fontWeight: 800, color: 'var(--text-primary)' }}>{party?.name}</div>
          <div style={{ fontSize: '0.82rem', color: 'var(--text-muted)' }}>{party?.phone || '—'}</div>
        </div>
        <div style={{ display: 'flex', gap: 24 }}>
          <div style={{ textAlign: 'right' }}>
            <div style={{ fontSize: '0.7rem', color: 'var(--text-muted)', textTransform: 'uppercase' }}>Outstanding</div>
            <div style={{ fontSize: '1.1rem', fontWeight: 800, color: outstanding > 0 ? 'var(--warning, #b45309)' : 'var(--success, #166534)' }}>{fmt(outstanding)}</div>
          </div>
          {credit > 0 && (
            <div style={{ textAlign: 'right' }}>
              <div style={{ fontSize: '0.7rem', color: 'var(--text-muted)', textTransform: 'uppercase' }}>Advance</div>
              <div style={{ fontSize: '1.1rem', fontWeight: 800, color: 'var(--success, #166534)' }}>{fmt(credit)}</div>
            </div>
          )}
        </div>
      </div>

      {/* Actions */}
      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
        {outstanding > 0 && (
          <button className="btn btn-primary btn-sm" onClick={() => onSettle && onSettle(party)}><CheckIcon size={13} /> Settle dues</button>
        )}
        <button className="btn btn-secondary btn-sm" onClick={() => onRecordPayment && onRecordPayment(party)}><CashIcon size={13} /> Record payment</button>
        {outstanding > 0 && (
          <button className="btn btn-sm" style={{ backgroundColor: '#166534', color: '#fff', border: 'none' }} onClick={() => onReminder && onReminder(party)}><MessageIcon size={13} /> Send reminder</button>
        )}
      </div>

      {/* Ledger */}
      {loading ? (
        <div style={{ color: 'var(--text-muted)', fontSize: '0.85rem', padding: 12 }}>Loading account…</div>
      ) : (
        <div className="data-table-wrap" style={{ overflowX: 'auto' }}>
          <table className="data-table" style={{ width: '100%', fontSize: '0.84rem' }}>
            <thead>
              <tr>
                <th>Invoice</th>
                <th>Date</th>
                <th style={{ textAlign: 'right' }}>Total</th>
                <th style={{ textAlign: 'right' }}>Paid</th>
                <th style={{ textAlign: 'right' }}>Outstanding</th>
                <th>Status</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {entries.length === 0 ? (
                <tr><td colSpan={7} style={{ textAlign: 'center', color: 'var(--text-muted)', padding: 24 }}>No invoices for this customer.</td></tr>
              ) : entries.map(e => {
                // Ledger rows lack the backend norms flags; derive them the same
                // way the API does so InvoiceActions gates identically.
                const isNote = (e.status || '').toLowerCase().includes('note') || (e.invoice_type || '').includes('note')
                const inv = {
                  ...e,
                  invoice_no: e.invoice_no, invoice_number: e.invoice_no,
                  can_record_payment: e.outstanding > 0 && !isNote,
                  can_return: !isNote,
                }
                return (
                  <tr key={e.invoice_id}>
                    <td className="td-primary" style={{ fontWeight: 600 }}>{e.invoice_no}</td>
                    <td>{e.date || '—'}</td>
                    <td style={{ textAlign: 'right' }}>{fmt(e.total_amount)}</td>
                    <td style={{ textAlign: 'right' }}>{fmt(e.paid_amount)}</td>
                    <td style={{ textAlign: 'right', color: e.outstanding > 0 ? 'var(--warning, #b45309)' : 'var(--text-muted)' }}>{fmt(e.outstanding)}</td>
                    <td><StatusTag status={e.status} /></td>
                    <td style={{ textAlign: 'right' }}>
                      <InvoiceActions invoice={inv} actions={actions} customer={party} compact />
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
