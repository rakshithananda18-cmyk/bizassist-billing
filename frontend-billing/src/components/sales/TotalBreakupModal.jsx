// src/components/sales/TotalBreakupModal.jsx
// ==========================================
// The "Total Breakup Details" popup, lifted out of Sales.jsx unchanged. Pure
// presentation: it receives the already-computed amounts and renders the
// subtotal / GST split / grand total / change / UPI QR. No business logic here.
// First step of decomposing the Sales god-component — behaviour is identical.
import React from 'react'
import { CloseIcon, SummaryIcon } from '../../components/Icons'
import { fmt } from '../../utils/format'
import { buildUpiUri, qrImageUrl } from '../../utils/share'

export default function TotalBreakupModal({
  open,
  onClose,
  subtotal,
  gstAmt,
  isIntrastate,
  cgstAmt,
  sgstAmt,
  igstAmt,
  grandTotal,
  amountReceived,
  changeToReturn,
  paymentMode,
  upiVpa,
}) {
  if (!open) return null

  const businessName = localStorage.getItem('billing_user')
    ? JSON.parse(localStorage.getItem('billing_user')).business_name || 'BizAssist Merchant'
    : 'BizAssist Merchant'

  return (
    <div className="modal-overlay" onClick={e => e.target === e.currentTarget && onClose()}>
      <div className="modal" style={{ maxWidth: 400 }}>
        <div className="modal-header">
          <span className="modal-title" style={{ color: 'var(--text-primary)', fontWeight: 700 }}><SummaryIcon size={16} style={{ marginRight: 6, display: 'inline-block', verticalAlign: 'middle' }} /> Total Breakup Details</span>
          <button className="btn btn-ghost btn-icon" onClick={onClose} style={{ color: 'var(--text-muted)' }} aria-label="Close"><CloseIcon size={16} /></button>
        </div>
        <div className="modal-body" style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.9rem', color: 'var(--text-secondary)' }}>
            <span>Subtotal (Without Tax):</span>
            <span style={{ fontWeight: 600 }}>{fmt(subtotal)}</span>
          </div>
          {gstAmt > 0 ? (
            <>
              {isIntrastate ? (
                <>
                  <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.82rem', color: 'var(--text-muted)', paddingLeft: 12 }}>
                    <span>CGST:</span>
                    <span>{fmt(cgstAmt)}</span>
                  </div>
                  <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.82rem', color: 'var(--text-muted)', paddingLeft: 12 }}>
                    <span>SGST:</span>
                    <span>{fmt(sgstAmt)}</span>
                  </div>
                </>
              ) : (
                <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.82rem', color: 'var(--text-muted)', paddingLeft: 12 }}>
                  <span>IGST:</span>
                  <span>{fmt(igstAmt)}</span>
                </div>
              )}
              <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.9rem', color: 'var(--text-secondary)' }}>
                <span>Total Tax:</span>
                <span style={{ fontWeight: 600 }}>{fmt(gstAmt)}</span>
              </div>
            </>
          ) : (
            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.9rem', color: 'var(--text-secondary)' }}>
              <span>Tax (GST 0%):</span>
              <span style={{ fontWeight: 600 }}>{fmt(0)}</span>
            </div>
          )}
          <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '1rem', color: 'var(--accent)', fontWeight: 800, borderTop: '1px solid var(--border)', paddingTop: 8 }}>
            <span>Grand Total:</span>
            <span>{fmt(grandTotal)}</span>
          </div>
          <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.9rem', color: 'var(--text-secondary)', borderTop: '1px dashed var(--border)', paddingTop: 8 }}>
            <span>Amount Received:</span>
            <span style={{ fontWeight: 600 }}>{fmt(amountReceived)}</span>
          </div>
          <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.9rem', color: 'var(--success)', fontWeight: 700 }}>
            <span>Change to Return:</span>
            <span>{fmt(changeToReturn)}</span>
          </div>
          {paymentMode === 'upi' && grandTotal > 0 && (
            <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 6, padding: '10px 0', borderTop: '1px dashed var(--border)' }}>
              <div style={{ fontSize: '0.75rem', fontWeight: 700, color: 'var(--accent)' }}>Scan to pay ₹{grandTotal.toFixed(2)}</div>
              <img
                src={qrImageUrl(buildUpiUri({ vpa: upiVpa, payeeName: businessName, amount: grandTotal, note: 'POS-Invoicing' }))}
                alt="UPI QR Code"
                style={{ width: 120, height: 120, border: '1px solid var(--border)', borderRadius: '4px' }}
              />
              <span style={{ fontSize: '0.7rem', color: 'var(--text-muted)' }}>UPI: {upiVpa}</span>
            </div>
          )}
          <div style={{ display: 'flex', justifyContent: 'flex-end', marginTop: 12, borderTop: '1px solid var(--border)', paddingTop: 8 }}>
            <button type="button" className="btn btn-primary btn-sm" onClick={onClose}>
              Close
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
