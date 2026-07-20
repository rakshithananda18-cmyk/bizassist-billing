// ============================================================================
// PartyFormModal — extracted verbatim from pages/Parties.jsx (repo restructure).
// State and handlers stay with the page and arrive as same-named props.
// ============================================================================
import React from 'react'
import CustomSelect from '../common/CustomSelect'
import { CheckIcon, CloseIcon, HandshakeIcon, UserIcon, WarehouseIcon } from '../Icons'

export default function PartyFormModal({ form, setField, handleSubmit, submitting, setShowModal }) {
  return (
        <div className="modal-overlay" onClick={e => e.target === e.currentTarget && setShowModal(false)}>
          <div className="modal modal-lg">
            <div className="modal-header">
              <span className="modal-title"><HandshakeIcon size={16} style={{ marginRight: 6, display: 'inline-block', verticalAlign: 'middle' }} /> Add Party</span>
              <button className="btn btn-ghost btn-icon" onClick={() => setShowModal(false)} aria-label="Close"><CloseIcon size={16} /></button>
            </div>
            <form onSubmit={handleSubmit}>
              <div className="modal-body">
                {/* Type toggle */}
                <div className="flex items-center gap-2 mb-4">
                  <span style={{ fontSize: '0.82rem', color: 'var(--text-secondary)' }}>Type:</span>
                  <div className="tabs">
                    <button type="button" className={`tab${form.party_type === 'customer' ? ' active' : ''}`} onClick={() => setField('party_type', 'customer')}>
                      <UserIcon size={14} style={{ marginRight: 6, display: 'inline-block', verticalAlign: 'middle' }} /> Customer
                    </button>
                    <button type="button" className={`tab${form.party_type === 'vendor' ? ' active' : ''}`} onClick={() => setField('party_type', 'vendor')}>
                      <WarehouseIcon size={14} style={{ marginRight: 6, display: 'inline-block', verticalAlign: 'middle' }} /> Vendor
                    </button>
                  </div>
                </div>
                <div className="grid grid-2 gap-3 mb-4">
                  <div className="form-group">
                    <label className="form-label">Name *</label>
                    <input className="form-input" placeholder="Full name or business name" value={form.name} onChange={e => setField('name', e.target.value)} required />
                  </div>
                  <div className="form-group">
                    <label className="form-label">Phone</label>
                    <input className="form-input" placeholder="+91 98765 43210" value={form.phone} onChange={e => setField('phone', e.target.value)} />
                  </div>
                  <div className="form-group">
                    <label className="form-label">Email</label>
                    <input type="email" className="form-input" placeholder="email@example.com" value={form.email} onChange={e => setField('email', e.target.value)} />
                  </div>
                  <div className="form-group">
                    <label className="form-label">GSTIN</label>
                    <input className="form-input" placeholder="22AAAAA0000A1Z5" value={form.gstin} onChange={e => setField('gstin', e.target.value)} />
                  </div>
                  <div className="form-group">
                    <label className="form-label">Credit Limit (₹)</label>
                    <input type="number" className="form-input" placeholder="e.g. 50000" min="0" step="any" value={form.credit_limit} onChange={e => setField('credit_limit', e.target.value)} />
                  </div>
                  <div className="form-group">
                    <label className="form-label">Payment Terms</label>
                    <CustomSelect className="form-select" value={form.payment_terms} onChange={e => setField('payment_terms', e.target.value)}>
                      <option value="immediate">Immediate</option>
                      <option value="net7">Net 7 days</option>
                      <option value="net15">Net 15 days</option>
                      <option value="net30">Net 30 days</option>
                      <option value="net45">Net 45 days</option>
                      <option value="net60">Net 60 days</option>
                    </CustomSelect>
                  </div>
                </div>
                <div className="form-group">
                  <label className="form-label">Address</label>
                  <textarea className="form-textarea" style={{ minHeight: 70 }} placeholder="Full address…" value={form.address} onChange={e => setField('address', e.target.value)} />
                </div>
              </div>
              <div className="modal-footer">
                <button type="button" className="btn btn-secondary" onClick={() => setShowModal(false)}>Cancel</button>
                <button type="submit" className="btn btn-primary" disabled={submitting}>
                  {submitting ? <><span className="spinner" style={{ width: 14, height: 14, borderWidth: 2 }} /> Saving…</> : <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}><CheckIcon size={14} /> Add Party</span>}
                </button>
              </div>
            </form>
          </div>
        </div>
  )
}
