// ============================================================================
// RecordPaymentModal — the "Record Payment" modal, extracted verbatim from
// pages/Payments.jsx (repo restructure). Form state stays with the page.
// ============================================================================
import React from 'react'
import CustomSelect from '../common/CustomSelect'
import { BillsIcon, CashIcon, CheckIcon, CloseIcon, PhoneIcon, WarehouseIcon } from '../Icons'

export default function RecordPaymentModal({ form, setField, onSubmit, submitting, onClose }) {
  return (
    <div className="modal-overlay" onClick={e => e.target === e.currentTarget && onClose()}>
      <div className="modal">
        <div className="modal-header">
          <span className="modal-title">💳 Record Payment</span>
          <button className="btn btn-ghost btn-icon" onClick={onClose} aria-label="Close"><CloseIcon size={16} /></button>
        </div>
        <form onSubmit={onSubmit}>
          <div className="modal-body">
            <div className="grid grid-2 gap-3 mb-4">
              <div className="form-group">
                <label className="form-label">Payment Type</label>
                <CustomSelect className="form-select" value={form.type} onChange={e => setField('type', e.target.value)}>
                  <option value="received">Received (from customer)</option>
                  <option value="made">Made (to supplier)</option>
                </CustomSelect>
              </div>
              <div className="form-group">
                <label className="form-label">Date</label>
                <input type="date" className="form-input" value={form.date} onChange={e => setField('date', e.target.value)} required />
              </div>
            </div>
            <div className="form-group mb-4">
              <label className="form-label">Invoice / Bill Reference</label>
              <input className="form-input" placeholder="INV-001 or bill number…" value={form.invoice_ref} onChange={e => setField('invoice_ref', e.target.value)} />
            </div>
            <div className="grid grid-2 gap-3 mb-4">
              <div className="form-group">
                <label className="form-label">Amount (₹)</label>
                <input type="number" className="form-input" placeholder="0.00" min="0" step="any" value={form.amount} onChange={e => setField('amount', e.target.value)} required />
              </div>
              <div className="form-group">
                <label className="form-label">Payment Method</label>
                <CustomSelect className="form-select" value={form.method} onChange={e => setField('method', e.target.value)}>
                  <option value="Cash"><CashIcon size={14} style={{ marginRight: 6, display: 'inline-block', verticalAlign: 'middle' }} /> Cash</option>
                  <option value="UPI"><PhoneIcon size={14} style={{ marginRight: 6, display: 'inline-block', verticalAlign: 'middle' }} /> UPI</option>
                  <option value="Bank"><WarehouseIcon size={14} style={{ marginRight: 6, display: 'inline-block', verticalAlign: 'middle' }} /> Bank Transfer</option>
                  <option value="Cheque"><BillsIcon size={14} style={{ marginRight: 6, display: 'inline-block', verticalAlign: 'middle' }} /> Cheque</option>
                </CustomSelect>
              </div>
            </div>
            <div className="form-group">
              <label className="form-label">Reference / UTR / Cheque No.</label>
              <input className="form-input" placeholder="Transaction reference…" value={form.reference} onChange={e => setField('reference', e.target.value)} />
            </div>
          </div>
          <div className="modal-footer">
            <button type="button" className="btn btn-secondary" onClick={onClose}>Cancel</button>
            <button type="submit" className="btn btn-primary" disabled={submitting}>
              {submitting ? <><span className="spinner" style={{ width: 14, height: 14, borderWidth: 2 }} /> Recording…</> : <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}><CheckIcon size={14} /> Record Payment</span>}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}
