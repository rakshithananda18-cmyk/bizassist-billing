// ============================================================================
// FieldCollections — Contacts & Payments → "Field collections" (owner only).
// ----------------------------------------------------------------------------
// Money Field Team staff collected at shops, waiting for the owner. Confirming
// records one payment per bill through billing's own payment command
// (core/field_team.py): journal, paid status and desktop sync as usual, and
// never twice for the same collection and bill.
// ============================================================================
import React, { useCallback, useEffect, useState } from 'react'
import api from '../../api/client'
import { fmt } from '../../utils/format'
import { checkSplit, startingSplit } from '../../utils/fieldCollections'
import { CheckIcon, CloseIcon } from '../Icons'

const SMALL = { fontSize: 'var(--fs-sm)' }
const NOTE = { fontSize: 'var(--fs-xs)', color: 'var(--text-muted)' }

function ConfirmModal({ collection, onClose, onDone }) {
  const [amounts, setAmounts] = useState(() => startingSplit(collection))
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const split = checkSplit(collection, amounts)

  const submit = async (e) => {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      const r = await api.post(`/field-collections/${collection.task_uid}/confirm`, { allocations: split.allocations })
      onDone(r)
    } catch (err) {
      setError(err.detail || err.message || 'Could not record the payments.')
      setBusy(false)
    }
  }

  return (
    <div className="modal-overlay" onClick={e => e.target === e.currentTarget && onClose()}>
      <div className="modal">
        <div className="modal-header">
          <span className="modal-title">Confirm field collection</span>
          <button className="btn btn-ghost btn-icon" onClick={onClose} aria-label="Close"><CloseIcon size={16} /></button>
        </div>
        <form onSubmit={submit}>
          <div className="modal-body">
            <p style={{ ...SMALL, marginTop: 0 }}>
              <strong>{fmt(collection.remaining)}</strong> {collection.payment_mode}
              {collection.payment_ref && <> · ref {collection.payment_ref}</>} collected by {collection.staff || 'staff'} at {collection.shop || 'a shop'}
              {collection.collected_on && <> on {collection.collected_on}</>}. Each bill gets a payment of the amount below.
            </p>
            <div className="data-table-wrap">
              <table className="data-table">
                <thead><tr><th>Bill</th><th>Date</th><th style={{ textAlign: 'right' }}>Due</th><th style={{ textAlign: 'right' }}>Pay</th></tr></thead>
                <tbody>
                  {collection.bills.map(b => (
                    <tr key={b.invoice_id}>
                      <td>{b.number}</td>
                      <td>{b.date || '—'}</td>
                      <td style={{ textAlign: 'right' }}>{fmt(b.balance_due)}</td>
                      <td style={{ textAlign: 'right' }}>
                        <input className="form-input" type="number" min="0" step="0.01" style={{ width: 120, textAlign: 'right' }}
                          value={amounts[b.invoice_id] ?? ''} aria-label={`Amount for ${b.number}`}
                          onChange={e => setAmounts({ ...amounts, [b.invoice_id]: e.target.value })} />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <p style={{ ...SMALL, marginBottom: 0 }}>
              Total {fmt(split.total)}{split.left > 0 && <> · {fmt(split.left)} stays here to confirm later</>}
            </p>
            {collection.unallocated > 0 && (
              <div className="alert alert-warning" style={{ marginTop: 12 }}>
                {fmt(collection.unallocated)} is more than these bills owe. Record it in billing yourself (for example as an advance); it stays listed here until then.
              </div>
            )}
            {(split.problem || error) && <div className="alert alert-danger" style={{ marginTop: 12 }}>{error || split.problem}</div>}
          </div>
          <div className="modal-footer">
            <button type="button" className="btn btn-secondary" onClick={onClose}>Cancel</button>
            <button type="submit" className="btn btn-primary" disabled={busy || !!split.problem}>
              <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}><CheckIcon size={14} /> {busy ? 'Recording…' : `Record ${fmt(split.total)}`}</span>
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}

export default function FieldCollections() {
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)
  const [open, setOpen] = useState(null)
  const [notice, setNotice] = useState(null)

  const load = useCallback(async () => {
    try {
      setData(await api.get('/field-collections'))
      setError(null)
    } catch (err) {
      setError(err.detail || err.message || 'Could not load field collections.')
    }
  }, [])
  useEffect(() => { load() }, [load])

  if (error) return <div className="alert alert-danger">{error}</div>
  if (!data) return <div className="empty-state">Loading…</div>
  if (!data.available) {
    return <div className="empty-state card">Field Team collections appear in the BizAssist web app, where Field Team runs.</div>
  }
  return (
    <div>
      {notice && <div className="alert alert-success" style={{ marginBottom: 12 }}>{notice}</div>}
      {data.collections.length === 0 ? (
        <div className="empty-state card">Nothing to confirm. Money your Field Team staff collect at shops appears here until you record it.</div>
      ) : (
        <div className="data-table-wrap">
          <table className="data-table">
            <thead>
              <tr><th>Collected</th><th>Shop</th><th>By</th><th>Mode</th><th style={{ textAlign: 'right' }}>To confirm</th><th>Bills</th><th /></tr>
            </thead>
            <tbody>
              {data.collections.map(c => (
                <tr key={c.task_uid}>
                  <td>{c.collected_on || '—'}</td>
                  <td>{c.shop || '—'}</td>
                  <td>{c.staff || '—'}</td>
                  <td>{c.payment_mode}{c.payment_ref && <div style={NOTE}>{c.payment_ref}</div>}</td>
                  <td style={{ textAlign: 'right' }}>
                    {fmt(c.remaining)}
                    {c.already_confirmed > 0 && <div style={NOTE}>{fmt(c.already_confirmed)} already recorded</div>}
                  </td>
                  <td style={SMALL}>
                    {c.bills.length ? c.bills.map(b => b.number).join(', ')
                      : c.shop_linked ? 'No unpaid bills'
                      : 'Shop not linked to a customer'}
                  </td>
                  <td>
                    <button className="btn btn-primary btn-sm" disabled={!c.bills.length} onClick={() => { setNotice(null); setOpen(c) }}>Confirm</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {open && (
        <ConfirmModal collection={open} onClose={() => setOpen(null)}
          onDone={(r) => {
            setOpen(null)
            setNotice(`Recorded ${fmt(r.recorded.reduce((a, p) => a + p.amount, 0))} against ${r.recorded.length} bill(s).`)
            load()
          }} />
      )}
    </div>
  )
}
