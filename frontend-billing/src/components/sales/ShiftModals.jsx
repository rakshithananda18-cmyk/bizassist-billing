// src/components/sales/ShiftModals.jsx
// ====================================
// Shift & Cash-Drawer Management (plan Phase 3 + 3b).
//
//   OpenShiftModal   — the billing GATEKEEPER: shown when GET /shifts/current
//                      returns none. The float is PREFILLED from the previous
//                      shift's "left in drawer" (Shopify model); editing it
//                      logs an opening-variance movement server-side.
//   CashMovementModal — mid-shift Paid In / Paid Out (Square model): change
//                      top-up, bank deposit, drawer expense (auto-creates a
//                      real Expense in the books), owner withdrawal.
//   CloseShiftModal  — count the FULL drawer (reconciliation), then choose how
//                      much to LEAVE for the next shift; the remainder is
//                      logged as moved to bank / owner.
//
// All are presentational + fetch wrappers; the money math is server-side
// (core/shifts/service.py) — the client never computes an expectation.
import React, { useEffect, useState } from 'react'
import { fmt } from '../../utils/format'

const inputStyle = {
  width: '100%', fontSize: '1.05rem', fontWeight: 700, textAlign: 'right',
}
const labelStyle = { display: 'block', fontSize: '0.78rem', fontWeight: 700, marginTop: 12 }

export function OpenShiftModal({ open, onOpened, authFetch, operatorName }) {
  const [openingCash, setOpeningCash] = useState('')
  const [suggestion, setSuggestion] = useState(null)   // {suggested, source_end_time}
  const [notes, setNotes] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState(null)

  useEffect(() => {
    if (!open) return
    setOpeningCash(''); setNotes(''); setError(null); setSuggestion(null)
    // Prefill the float from the previous shift's "left in drawer" (3b).
    authFetch('/shifts/suggested-float')
      .then(res => res.ok ? res.json() : null)
      .then(data => {
        if (data && data.suggested !== null && data.suggested !== undefined) {
          setSuggestion(data)
          setOpeningCash(String(data.suggested))
        }
      })
      .catch(() => { /* offline — manual entry */ })
  }, [open, authFetch])

  if (!open) return null

  const suggested = suggestion?.suggested
  const entered = parseFloat(openingCash)
  const differs = suggested !== null && suggested !== undefined
    && !isNaN(entered) && Math.abs(entered - suggested) >= 0.005

  const submit = async () => {
    const cash = parseFloat(openingCash)
    if (isNaN(cash) || cash < 0) {
      setError('Enter the counted opening cash (0 or more).')
      return
    }
    setSubmitting(true)
    setError(null)
    try {
      const res = await authFetch('/shifts/open', {
        method: 'POST',
        body: JSON.stringify({ opening_cash: cash, notes: notes || null }),
      })
      if (res.ok) {
        const data = await res.json().catch(() => null)
        onOpened?.(data?.shift || null)
      } else {
        const err = await res.json().catch(() => ({}))
        setError(err.detail || 'Could not open the shift.')
      }
    } catch {
      setError('Network error — the register needs a connection to open a shift.')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="modal-overlay" style={{ zIndex: 3000 }}>
      <div className="modal" style={{ maxWidth: 420 }} onKeyDown={e => { if (e.key === 'Enter') submit() }}>
        <div style={{ padding: '20px 22px' }}>
          <h3 style={{ margin: 0, fontSize: '1.05rem' }}>Open Register Shift</h3>
          <p style={{ color: 'var(--text-muted)', fontSize: '0.82rem', marginTop: 8 }}>
            {operatorName ? <strong>{operatorName}: </strong> : null}
            Count the cash in the drawer and confirm your opening float.
            Billing stays locked until a shift is open.
          </p>
          <label style={labelStyle}>Opening Cash Float (₹)</label>
          <input
            autoFocus
            type="number"
            min="0"
            step="any"
            className="form-input"
            style={inputStyle}
            placeholder="0.00"
            value={openingCash}
            onChange={e => setOpeningCash(e.target.value)}
          />
          {suggested !== null && suggested !== undefined && (
            <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)', marginTop: 6 }}>
              Carried forward from last shift close: <strong>{fmt(suggested)}</strong>
              {differs && (
                <span style={{ color: 'var(--warning, #f59e0b)', fontWeight: 700 }}>
                  {' '}· differs by {fmt(Math.abs(entered - suggested))} — this variance will be recorded.
                </span>
              )}
            </div>
          )}
          <label style={labelStyle}>Notes (optional)</label>
          <input
            type="text"
            className="form-input"
            style={{ width: '100%' }}
            placeholder="e.g. morning shift"
            value={notes}
            onChange={e => setNotes(e.target.value)}
          />
          {error && (
            <div style={{ color: 'var(--error)', fontSize: '0.8rem', marginTop: 10 }}>{error}</div>
          )}
          <button
            className="btn btn-primary"
            style={{ width: '100%', marginTop: 16, padding: '10px 0', fontWeight: 700 }}
            disabled={submitting}
            onClick={submit}
          >
            {submitting ? 'Opening…' : 'Open Shift & Start Billing'}
          </button>
        </div>
      </div>
    </div>
  )
}

// ── Mid-shift Paid In / Paid Out ─────────────────────────────────────────────

const MOVEMENT_OPTIONS = [
  { key: 'change_top_up', type: 'paid_in', label: 'Cash In — change top-up', hint: 'Cash added to the drawer to make change.' },
  { key: 'bank_deposit', type: 'paid_out', label: 'Paid Out — bank deposit', hint: 'Cash taken from the drawer to the bank.' },
  { key: 'expense', type: 'paid_out', label: 'Paid Out — expense', hint: 'Also creates an Expense record in your books.' },
  { key: 'owner_withdrawal', type: 'paid_out', label: 'Paid Out — owner withdrawal', hint: 'Owner drawings from the drawer.' },
]
const EXPENSE_CATEGORIES = ['Others', 'Rent', 'Utilities', 'Salaries', 'Marketing']

export function CashMovementModal({ open, onClose, onRecorded, authFetch }) {
  const [optKey, setOptKey] = useState('bank_deposit')
  const [amount, setAmount] = useState('')
  const [note, setNote] = useState('')
  const [expenseCategory, setExpenseCategory] = useState('Others')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState(null)

  useEffect(() => {
    if (open) { setOptKey('bank_deposit'); setAmount(''); setNote(''); setExpenseCategory('Others'); setError(null) }
  }, [open])

  if (!open) return null
  const opt = MOVEMENT_OPTIONS.find(o => o.key === optKey)

  const submit = async () => {
    const amt = parseFloat(amount)
    if (isNaN(amt) || amt <= 0) {
      setError('Enter an amount greater than 0.')
      return
    }
    setSubmitting(true)
    setError(null)
    try {
      const res = await authFetch('/shifts/movements', {
        method: 'POST',
        body: JSON.stringify({
          movement_type: opt.type,
          category: opt.key,
          amount: amt,
          note: note || null,
          expense_category: opt.key === 'expense' ? expenseCategory : null,
        }),
      })
      if (res.ok) {
        const data = await res.json().catch(() => null)
        onRecorded?.(data)
      } else {
        const err = await res.json().catch(() => ({}))
        setError(err.detail || 'Could not record the movement.')
      }
    } catch {
      setError('Network error — try again when the register is back online.')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="modal-overlay" style={{ zIndex: 3000 }} onClick={e => { if (e.target === e.currentTarget && !submitting) onClose?.() }}>
      <div className="modal" style={{ maxWidth: 420 }}>
        <div style={{ padding: '20px 22px' }}>
          <h3 style={{ margin: 0, fontSize: '1.05rem' }}>Cash In / Out</h3>
          <p style={{ color: 'var(--text-muted)', fontSize: '0.8rem', marginTop: 6 }}>
            Non-sale cash movement — it adjusts what the system expects in the drawer.
          </p>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6, marginTop: 12 }}>
            {MOVEMENT_OPTIONS.map(o => (
              <label key={o.key} style={{
                display: 'flex', alignItems: 'flex-start', gap: 8, padding: '8px 10px',
                borderRadius: 8, cursor: 'pointer', fontSize: '0.82rem',
                border: `1px solid ${optKey === o.key ? 'var(--accent)' : 'var(--border)'}`,
                background: optKey === o.key ? 'var(--bg-2)' : 'transparent',
              }}>
                <input type="radio" name="mv" checked={optKey === o.key} onChange={() => setOptKey(o.key)} style={{ marginTop: 2 }} />
                <span>
                  <strong>{o.label}</strong>
                  <span style={{ display: 'block', color: 'var(--text-muted)', fontSize: '0.72rem' }}>{o.hint}</span>
                </span>
              </label>
            ))}
          </div>
          {optKey === 'expense' && (
            <>
              <label style={labelStyle}>Expense Category</label>
              <select className="form-input" style={{ width: '100%' }}
                      value={expenseCategory} onChange={e => setExpenseCategory(e.target.value)}>
                {EXPENSE_CATEGORIES.map(c => <option key={c} value={c}>{c}</option>)}
              </select>
            </>
          )}
          <label style={labelStyle}>Amount (₹)</label>
          <input type="number" min="0" step="any" className="form-input" style={inputStyle}
                 placeholder="0.00" value={amount} onChange={e => setAmount(e.target.value)} autoFocus />
          <label style={labelStyle}>Note (optional)</label>
          <input type="text" className="form-input" style={{ width: '100%' }}
                 placeholder="e.g. tea & snacks, deposit slip #123"
                 value={note} onChange={e => setNote(e.target.value)} />
          {error && <div style={{ color: 'var(--error)', fontSize: '0.8rem', marginTop: 10 }}>{error}</div>}
          <div style={{ display: 'flex', gap: 8, marginTop: 16 }}>
            <button className="btn btn-secondary" style={{ flex: 1 }} disabled={submitting} onClick={onClose}>Cancel</button>
            <button className="btn btn-primary" style={{ flex: 2, fontWeight: 700 }} disabled={submitting} onClick={submit}>
              {submitting ? 'Recording…' : 'Record Movement'}
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}

// ── Close shift ──────────────────────────────────────────────────────────────

function DiffRow({ label, expected, actual }) {
  const diff = (actual ?? 0) - (expected ?? 0)
  const ok = Math.abs(diff) < 0.005
  return (
    <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.85rem', padding: '6px 0', borderBottom: '1px dashed var(--border)' }}>
      <span style={{ color: 'var(--text-muted)' }}>{label}</span>
      <span>
        expected <strong>{fmt(expected ?? 0)}</strong> · counted <strong>{fmt(actual ?? 0)}</strong>{' '}
        <span style={{ fontWeight: 800, color: ok ? 'var(--success, #22c55e)' : 'var(--error)' }}>
          {ok ? '✓ tallies' : `${diff > 0 ? 'OVER' : 'SHORT'} ${fmt(Math.abs(diff))}`}
        </span>
      </span>
    </div>
  )
}

export function CloseShiftModal({ open, onClose, onClosed, authFetch, shift }) {
  const [cashActual, setCashActual] = useState('')
  const [upiActual, setUpiActual] = useState('')
  const [leaveInDrawer, setLeaveInDrawer] = useState('')
  const [destination, setDestination] = useState('bank_deposit')
  const [notes, setNotes] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState(null)
  const [result, setResult] = useState(null)   // the CLOSED shift row from the server

  useEffect(() => {
    if (open) {
      setCashActual(''); setUpiActual(''); setLeaveInDrawer('')
      setDestination('bank_deposit'); setNotes(''); setError(null); setResult(null)
    }
  }, [open])

  if (!open) return null

  const tally = shift?.tally
  const counted = parseFloat(cashActual)
  const left = leaveInDrawer === '' ? counted : parseFloat(leaveInDrawer)
  const removed = (!isNaN(counted) && !isNaN(left)) ? Math.max(counted - left, 0) : 0

  const submit = async () => {
    if (isNaN(counted) || counted < 0) {
      setError('Enter the counted drawer cash (0 or more).')
      return
    }
    if (leaveInDrawer !== '' && (isNaN(left) || left < 0 || left > counted)) {
      setError('“Leave in drawer” must be between 0 and the counted cash.')
      return
    }
    setSubmitting(true)
    setError(null)
    try {
      const res = await authFetch('/shifts/close', {
        method: 'POST',
        body: JSON.stringify({
          closing_cash_actual: counted,
          closing_upi_actual: parseFloat(upiActual) || 0,
          leave_in_drawer: leaveInDrawer === '' ? null : left,
          removal_destination: destination,
          notes: notes || null,
        }),
      })
      if (res.ok) {
        const data = await res.json().catch(() => null)
        setResult(data?.shift || null)
      } else {
        const err = await res.json().catch(() => ({}))
        setError(err.detail || 'Could not close the shift.')
      }
    } catch {
      setError('Network error — try again when the register is back online.')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="modal-overlay" style={{ zIndex: 3000 }} onClick={e => { if (e.target === e.currentTarget && !submitting) onClose?.() }}>
      <div className="modal" style={{ maxWidth: 480 }}>
        <div style={{ padding: '20px 22px' }}>
          <h3 style={{ margin: 0, fontSize: '1.05rem' }}>
            {result ? 'Shift Closed — Reconciliation' : 'Close Register / End Shift'}
          </h3>

          {!result && (
            <>
              <p style={{ color: 'var(--text-muted)', fontSize: '0.82rem', marginTop: 8 }}>
                Count everything physically in the drawer first — the reconciliation
                always runs on the full count. Then choose what stays for the next shift.
              </p>
              {tally && (
                <div style={{ background: 'var(--bg-2)', borderRadius: 8, padding: '10px 12px', marginTop: 10, fontSize: '0.8rem' }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                    <span>Opening float</span><strong>{fmt(tally.opening_cash)}</strong>
                  </div>
                  <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                    <span>Cash sales this shift</span><strong>{fmt(tally.sales_cash)}</strong>
                  </div>
                  {(tally.paid_in > 0 || tally.paid_out > 0) && (
                    <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                      <span>Cash in / out</span>
                      <strong>+{fmt(tally.paid_in)} / −{fmt(tally.paid_out)}</strong>
                    </div>
                  )}
                  <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                    <span>UPI received this shift</span><strong>{fmt(tally.sales_upi)}</strong>
                  </div>
                </div>
              )}
              <label style={labelStyle}>Counted Cash in Drawer (₹)</label>
              <input
                autoFocus type="number" min="0" step="any" className="form-input"
                style={inputStyle} placeholder="0.00"
                value={cashActual} onChange={e => setCashActual(e.target.value)}
              />
              <label style={labelStyle}>UPI Received per App Statement (₹)</label>
              <input
                type="number" min="0" step="any" className="form-input"
                style={inputStyle} placeholder="0.00"
                value={upiActual} onChange={e => setUpiActual(e.target.value)}
              />
              <label style={labelStyle}>Leave in Drawer for Next Shift (₹)</label>
              <input
                type="number" min="0" step="any" className="form-input"
                style={inputStyle} placeholder={isNaN(counted) ? '0.00' : counted.toFixed(2)}
                value={leaveInDrawer} onChange={e => setLeaveInDrawer(e.target.value)}
              />
              <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)', marginTop: 6 }}>
                {removed > 0
                  ? <>Removing <strong>{fmt(removed)}</strong> from the drawer as:</>
                  : 'Leave blank to keep everything in the drawer.'}
              </div>
              {removed > 0 && (
                <div style={{ display: 'flex', gap: 6, marginTop: 6 }}>
                  {[['bank_deposit', 'Bank Deposit'], ['owner_withdrawal', 'Owner Withdrawal']].map(([k, l]) => (
                    <button key={k} type="button"
                            className={`btn btn-sm ${destination === k ? 'btn-primary' : 'btn-secondary'}`}
                            style={{ fontSize: '0.74rem', padding: '4px 10px' }}
                            onClick={() => setDestination(k)}>
                      {l}
                    </button>
                  ))}
                </div>
              )}
              <label style={labelStyle}>Notes (optional)</label>
              <input
                type="text" className="form-input" style={{ width: '100%' }}
                placeholder="e.g. deposit slip #123"
                value={notes} onChange={e => setNotes(e.target.value)}
              />
              {error && (
                <div style={{ color: 'var(--error)', fontSize: '0.8rem', marginTop: 10 }}>{error}</div>
              )}
              <div style={{ display: 'flex', gap: 8, marginTop: 16 }}>
                <button className="btn btn-secondary" style={{ flex: 1 }} disabled={submitting} onClick={onClose}>
                  Cancel
                </button>
                <button className="btn btn-primary" style={{ flex: 2, fontWeight: 700 }} disabled={submitting} onClick={submit}>
                  {submitting ? 'Closing…' : 'Close Shift'}
                </button>
              </div>
            </>
          )}

          {result && (
            <>
              <div style={{ marginTop: 12 }}>
                <DiffRow label="Cash" expected={result.closing_cash_expected} actual={result.closing_cash_actual} />
                <DiffRow label="UPI" expected={result.closing_upi_expected} actual={result.closing_upi_actual} />
                <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.85rem', padding: '6px 0', borderBottom: '1px dashed var(--border)' }}>
                  <span style={{ color: 'var(--text-muted)' }}>Left in drawer (next shift's float)</span>
                  <strong>{fmt(result.closing_float ?? result.closing_cash_actual ?? 0)}</strong>
                </div>
                {(result.closing_cash_actual ?? 0) - (result.closing_float ?? result.closing_cash_actual ?? 0) > 0.004 && (
                  <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.85rem', padding: '6px 0', borderBottom: '1px dashed var(--border)' }}>
                    <span style={{ color: 'var(--text-muted)' }}>Moved out of drawer</span>
                    <strong>{fmt((result.closing_cash_actual ?? 0) - (result.closing_float ?? 0))}</strong>
                  </div>
                )}
              </div>
              <p style={{ color: 'var(--text-muted)', fontSize: '0.78rem', marginTop: 10 }}>
                Saved. The left-in-drawer amount will prefill the next shift's opening
                float. Full history: Reports → Shift Reconciliations.
              </p>
              <button
                className="btn btn-primary"
                style={{ width: '100%', marginTop: 12, fontWeight: 700 }}
                onClick={() => onClosed?.(result)}
              >
                Done
              </button>
            </>
          )}
        </div>
      </div>
    </div>
  )
}
