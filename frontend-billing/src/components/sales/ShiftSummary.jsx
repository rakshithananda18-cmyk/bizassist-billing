// components/sales/ShiftSummary.jsx — printable end-of-shift summary.
// ====================================================================
// Shown after CloseShiftModal (and reusable anywhere a closed shift row is
// available). One screen = the whole shift: money reconciliation, cash
// movements, and every invoice that took a payment during the shift —
// clickable on screen, listed on paper.
//
// Print: the summary is ALSO rendered into a #shift-print-root portal on
// document.body; injected @media print CSS hides everything else. Same
// proven isolation pattern as the invoice PrintPortal.
import React, { useState, useEffect } from 'react'
import { createPortal } from 'react-dom'
import { Link } from 'react-router-dom'
import { useAuth } from '../../contexts/AuthContext'
import { logger } from '../../utils/logger'

const fmt = (n) => `₹${Number(n || 0).toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
const IST = { timeZone: 'Asia/Kolkata' }
const dt = (iso) => iso
  ? new Date(iso.endsWith('Z') || iso.includes('+') ? iso : iso + 'Z')
      .toLocaleString('en-IN', { ...IST, day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit', hour12: true })
  : '—'

const MOVE_LABELS = {
  change_top_up: 'Cash In — change top-up',
  bank_deposit: 'Paid Out — bank deposit',
  expense: 'Paid Out — expense',
  owner_withdrawal: 'Paid Out — owner withdrawal',
  opening_discrepancy: 'Opening float discrepancy',
}

const PRINT_CSS = `
@media print {
  body > *:not(#shift-print-root) { display: none !important; }
  #shift-print-root { display: block !important; position: static !important; }
}
#shift-print-root { display: none; }
`

function MoneyRow({ label, value, strong, danger, ok }) {
  return (
    <div style={{
      display: 'flex', justifyContent: 'space-between', padding: '5px 0',
      borderBottom: '1px dashed #ccc', fontSize: 13,
      fontWeight: strong ? 800 : 400,
      color: danger ? '#c53030' : ok ? '#22863a' : 'inherit',
    }}>
      <span>{label}</span><span style={{ fontVariantNumeric: 'tabular-nums' }}>{value}</span>
    </div>
  )
}

/** The summary body — rendered once on screen and once in the print portal.
 *  `printMode` swaps invoice links for plain text. */
function SummaryBody({ shift, invoices, businessName, operatorName, printMode = false }) {
  const cashDiff = (shift.closing_cash_actual ?? 0) - (shift.closing_cash_expected ?? 0)
  const upiDiff = (shift.closing_upi_actual ?? 0) - (shift.closing_upi_expected ?? 0)
  const removed = Math.max((shift.closing_cash_actual ?? 0) - (shift.closing_float ?? shift.closing_cash_actual ?? 0), 0)
  const t = shift.tally || {}

  return (
    <div style={{ fontFamily: "'DM Sans', Arial, sans-serif", color: '#111', background: '#fff', padding: printMode ? '10mm' : 0 }}>
      {/* Header */}
      <div style={{ textAlign: 'center', borderBottom: '2px solid #111', paddingBottom: 8, marginBottom: 12 }}>
        <div style={{ fontSize: 17, fontWeight: 800 }}>{businessName || 'Shift Summary'}</div>
        <div style={{ fontSize: 12, fontWeight: 700, letterSpacing: '0.08em', textTransform: 'uppercase', marginTop: 2 }}>
          End of Shift Report — #{shift.id}
        </div>
        <div style={{ fontSize: 11, color: '#555', marginTop: 2 }}>
          Operator: <b>{operatorName || `user #${shift.user_id}`}</b>
          {' · '}Opened {dt(shift.start_time)} · Closed {dt(shift.end_time)}
        </div>
      </div>

      {/* Money reconciliation */}
      <div style={{ fontSize: 11, fontWeight: 800, textTransform: 'uppercase', letterSpacing: '0.06em', color: '#555', marginBottom: 4 }}>
        Drawer reconciliation
      </div>
      <MoneyRow label="Opening float" value={fmt(shift.opening_cash)} />
      {t.sales_cash != null && <MoneyRow label="Cash sales collected" value={fmt(t.sales_cash)} />}
      {t.sales_upi != null && <MoneyRow label="UPI collected" value={fmt(t.sales_upi)} />}
      {t.sales_card > 0 && <MoneyRow label="Card collected" value={fmt(t.sales_card)} />}
      {(t.paid_in > 0 || t.paid_out > 0) && (
        <MoneyRow label="Cash in / out (non-sale)" value={`+${fmt(t.paid_in)} / −${fmt(t.paid_out)}`} />
      )}
      <MoneyRow label="Cash expected vs counted"
        value={`${fmt(shift.closing_cash_expected)} / ${fmt(shift.closing_cash_actual)}`} />
      <MoneyRow
        label="Cash result"
        value={Math.abs(cashDiff) < 0.005 ? '✓ tallies' : `${cashDiff > 0 ? 'OVER' : 'SHORT'} ${fmt(Math.abs(cashDiff))}`}
        strong ok={Math.abs(cashDiff) < 0.005} danger={Math.abs(cashDiff) >= 0.005}
      />
      <MoneyRow label="UPI expected vs per app"
        value={`${fmt(shift.closing_upi_expected)} / ${fmt(shift.closing_upi_actual)}`} />
      {Math.abs(upiDiff) >= 0.005 && (
        <MoneyRow label="UPI result" value={`${upiDiff > 0 ? 'OVER' : 'SHORT'} ${fmt(Math.abs(upiDiff))}`} strong danger />
      )}
      <MoneyRow label="Left in drawer (next shift float)" value={fmt(shift.closing_float ?? shift.closing_cash_actual)} strong />
      {removed > 0.004 && <MoneyRow label="Removed from drawer" value={fmt(removed)} />}
      {shift.notes && <MoneyRow label="Notes" value={shift.notes} />}

      {/* Movements */}
      {shift.movements?.length > 0 && (
        <>
          <div style={{ fontSize: 11, fontWeight: 800, textTransform: 'uppercase', letterSpacing: '0.06em', color: '#555', margin: '14px 0 4px' }}>
            Cash movements ({shift.movements.length})
          </div>
          {shift.movements.map((m, i) => (
            <div key={i} style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12, padding: '4px 0', borderBottom: '1px dashed #ddd' }}>
              <span>
                {MOVE_LABELS[m.category] || m.category || m.movement_type}
                {m.note ? <span style={{ color: '#777' }}> — {m.note}</span> : null}
              </span>
              <span style={{ fontWeight: 700, fontVariantNumeric: 'tabular-nums' }}>
                {m.movement_type === 'paid_in' ? '+' : '−'}{fmt(m.amount)}
              </span>
            </div>
          ))}
        </>
      )}

      {/* Invoices */}
      <div style={{ fontSize: 11, fontWeight: 800, textTransform: 'uppercase', letterSpacing: '0.06em', color: '#555', margin: '14px 0 4px' }}>
        Invoices this shift ({invoices?.invoices?.length ?? '…'})
      </div>
      {invoices == null ? (
        <div style={{ fontSize: 12, color: '#777' }}>Loading invoices…</div>
      ) : invoices.invoices.length === 0 ? (
        <div style={{ fontSize: 12, color: '#777' }}>No payments were taken during this shift.</div>
      ) : (
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
          <thead>
            <tr style={{ borderBottom: '1.5px solid #111', textAlign: 'left' }}>
              <th style={{ padding: '4px 6px 4px 0' }}>Invoice</th>
              <th style={{ padding: '4px 6px' }}>Customer</th>
              <th style={{ padding: '4px 6px' }}>Mode</th>
              <th style={{ padding: '4px 0 4px 6px', textAlign: 'right' }}>Collected</th>
            </tr>
          </thead>
          <tbody>
            {invoices.invoices.map((inv, i) => (
              <tr key={i} style={{ borderBottom: '1px dashed #ddd' }}>
                <td style={{ padding: '4px 6px 4px 0', fontWeight: 700 }}>
                  {printMode ? inv.invoice_no : (
                    <Link to={`/invoice/${encodeURIComponent(inv.invoice_no)}/view`}
                      style={{ color: 'var(--accent, #c2714f)', textDecoration: 'none' }}
                      title="Open invoice">
                      {inv.invoice_no}
                    </Link>
                  )}
                </td>
                <td style={{ padding: '4px 6px' }}>{inv.customer || '—'}</td>
                <td style={{ padding: '4px 6px', textTransform: 'uppercase', fontSize: 10.5 }}>{(inv.modes || []).join(', ') || '—'}</td>
                <td style={{ padding: '4px 0 4px 6px', textAlign: 'right', fontVariantNumeric: 'tabular-nums' }}>{fmt(inv.collected_in_shift)}</td>
              </tr>
            ))}
            <tr>
              <td colSpan={3} style={{ padding: '6px 6px 0 0', fontWeight: 800, borderTop: '1.5px solid #111' }}>Total collected this shift</td>
              <td style={{ padding: '6px 0 0 6px', textAlign: 'right', fontWeight: 800, borderTop: '1.5px solid #111', fontVariantNumeric: 'tabular-nums' }}>
                {fmt(invoices.total_collected)}
              </td>
            </tr>
          </tbody>
        </table>
      )}

      <div style={{ textAlign: 'center', fontSize: 9.5, color: '#777', marginTop: 14, borderTop: '1px solid #ccc', paddingTop: 6 }}>
        Generated by BizAssist · This is a computer generated shift report.
      </div>
    </div>
  )
}

export default function ShiftSummaryModal({ shift, onClose, authFetch, operatorName }) {
  const { profile } = useAuth()
  const [invoices, setInvoices] = useState(null)

  useEffect(() => {
    if (!shift?.id) return
    let cancelled = false
    authFetch(`/shifts/${shift.id}/invoices`)
      .then(r => (r.ok ? r.json() : null))
      .then(d => { if (!cancelled) setInvoices(d || { invoices: [], total_collected: 0 }) })
      .catch(err => {
        logger.warn('[SHIFT] invoices fetch failed', err)
        if (!cancelled) setInvoices({ invoices: [], total_collected: 0 })
      })
    return () => { cancelled = true }
  }, [shift?.id, authFetch])

  if (!shift) return null
  const businessName = profile?.business_name

  return (
    <>
      {/* Screen modal */}
      <div className="modal-overlay" style={{ zIndex: 3100 }} onClick={e => e.target === e.currentTarget && onClose?.()}>
        <div className="modal" style={{ maxWidth: 640, width: '95%', maxHeight: '88vh', overflowY: 'auto' }}>
          <div style={{ padding: '18px 22px', background: '#fff', color: '#111', borderRadius: 'inherit' }}>
            <SummaryBody shift={shift} invoices={invoices} businessName={businessName} operatorName={operatorName} />
            <div style={{ display: 'flex', gap: 8, marginTop: 16 }}>
              <button className="btn btn-secondary" style={{ flex: 1 }} onClick={onClose}>Close</button>
              <button className="btn btn-primary" style={{ flex: 2, fontWeight: 700 }} onClick={() => window.print()}>
                Print Shift Summary
              </button>
            </div>
          </div>
        </div>
      </div>

      {/* Print portal — only thing visible on paper */}
      {createPortal(
        <div id="shift-print-root">
          <style>{PRINT_CSS}</style>
          <SummaryBody shift={shift} invoices={invoices} businessName={businessName} operatorName={operatorName} printMode />
        </div>,
        document.body,
      )}
    </>
  )
}
