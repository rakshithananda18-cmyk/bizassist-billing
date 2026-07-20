// ============================================================================
// AdjustStockModal — the "Adjust Stock" modal, extracted verbatim from
// pages/Stock.jsx (repo restructure). Form state stays with the page.
// ============================================================================
import React from 'react'
import CustomSelect from '../common/CustomSelect'
import { CheckIcon, CloseIcon, ZapIcon } from '../Icons'

export default function AdjustStockModal({ adjustForm, setAdjField, products, onSubmit, submitting, onClose }) {
  return (
    <div className="modal-overlay" onClick={e => e.target === e.currentTarget && onClose()}>
      <div className="modal">
        <div className="modal-header">
          <span className="modal-title"><ZapIcon size={14} style={{ marginRight: 6 }} /> Adjust Stock</span>
          <button className="btn btn-ghost btn-icon" onClick={onClose}><CloseIcon size={16} /></button>
        </div>
        <form onSubmit={onSubmit}>
          <div className="modal-body">
            <div className="form-group mb-4">
              <label className="form-label">Select Product *</label>
              <CustomSelect className="form-select" value={adjustForm.product_id} onChange={e => setAdjField('product_id', e.target.value)} required>
                <option value="">Choose a product…</option>
                {products.map(p => <option key={p.id} value={p.id}>{p.name} (Stock: {p.stock_qty ?? p.quantity ?? 0} {p.unit || ''})</option>)}
              </CustomSelect>
            </div>
            <div className="grid grid-2 gap-3 mb-4">
              <div className="form-group">
                <label className="form-label">Movement Type</label>
                <CustomSelect className="form-select" value={adjustForm.movement_type} onChange={e => setAdjField('movement_type', e.target.value)}>
                  <option value="stock_in">Stock In</option>
                  <option value="stock_out">Stock Out</option>
                  <option value="adjustment">Adjustment</option>
                </CustomSelect>
              </div>
              <div className="form-group">
                <label className="form-label">Quantity</label>
                <input type="number" className="form-input" placeholder="0" min="0" step="any" value={adjustForm.quantity} onChange={e => setAdjField('quantity', e.target.value)} required />
              </div>
            </div>
            <div className="form-group mb-4">
              <label className="form-label">Reason *</label>
              <input className="form-input" required placeholder="e.g. Damaged goods, count correction…" value={adjustForm.reason} onChange={e => setAdjField('reason', e.target.value)} />
            </div>
            <div className="form-group">
              <label className="form-label">Reference</label>
              <input className="form-input" placeholder="PO / GRN number…" value={adjustForm.reference} onChange={e => setAdjField('reference', e.target.value)} />
            </div>
          </div>
          <div className="modal-footer">
            <button type="button" className="btn btn-secondary" onClick={onClose}>Cancel</button>
            <button type="submit" className="btn btn-primary" disabled={submitting}>
              {submitting ? <><span className="spinner" style={{ width: 14, height: 14, borderWidth: 2 }} /> Adjusting…</> : <><CheckIcon size={14} /> Apply</>}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}
