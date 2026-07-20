// ============================================================================
// TransferStockModal — the godown-to-godown "Transfer Stock" modal, extracted
// verbatim from pages/Stock.jsx (repo restructure). Form state stays with the
// page.
// ============================================================================
import React from 'react'
import CustomSelect from '../common/CustomSelect'
import { CheckIcon, CloseIcon, SyncIcon } from '../Icons'

export default function TransferStockModal({ transferForm, setTrsfField, products, godowns, onSubmit, submitting, onClose }) {
  return (
    <div className="modal-overlay" onClick={e => e.target === e.currentTarget && onClose()}>
      <div className="modal">
        <div className="modal-header">
          <span className="modal-title"><SyncIcon size={14} style={{ marginRight: 6 }} /> Transfer Stock</span>
          <button className="btn btn-ghost btn-icon" onClick={onClose}><CloseIcon size={16} /></button>
        </div>
        <form onSubmit={onSubmit}>
          <div className="modal-body">
            <div className="form-group mb-4">
              <label className="form-label">Select Product *</label>
              <CustomSelect className="form-select" value={transferForm.product_id} onChange={e => setTrsfField('product_id', e.target.value)} required>
                <option value="">Choose a product…</option>
                {products.map(p => <option key={p.id} value={p.id}>{p.name} (Total Stock: {p.stock_qty ?? p.quantity ?? 0} {p.unit || ''})</option>)}
              </CustomSelect>
            </div>
            <div className="grid grid-2 gap-3 mb-4">
              <div className="form-group">
                <label className="form-label">From Godown *</label>
                <CustomSelect className="form-select" value={transferForm.from_godown_id} onChange={e => setTrsfField('from_godown_id', e.target.value)} required>
                  <option value="">Select source…</option>
                  {godowns.map(g => <option key={g.id} value={g.id}>{g.name}</option>)}
                </CustomSelect>
              </div>
              <div className="form-group">
                <label className="form-label">To Godown *</label>
                <CustomSelect className="form-select" value={transferForm.to_godown_id} onChange={e => setTrsfField('to_godown_id', e.target.value)} required>
                  <option value="">Select destination…</option>
                  {godowns.map(g => <option key={g.id} value={g.id}>{g.name}</option>)}
                </CustomSelect>
              </div>
            </div>
            <div className="form-group mb-4">
              <label className="form-label">Quantity *</label>
              <input type="number" className="form-input" placeholder="0" min="0.001" step="any" value={transferForm.quantity} onChange={e => setTrsfField('quantity', e.target.value)} required />
            </div>
            <div className="form-group">
              <label className="form-label">Notes</label>
              <input className="form-input" placeholder="Reason for transfer…" value={transferForm.notes} onChange={e => setTrsfField('notes', e.target.value)} />
            </div>
          </div>
          <div className="modal-footer">
            <button type="button" className="btn btn-secondary" onClick={onClose}>Cancel</button>
            <button type="submit" className="btn btn-primary" disabled={submitting}>
              {submitting ? <><span className="spinner" style={{ width: 14, height: 14, borderWidth: 2 }} /> Transferring…</> : <><CheckIcon size={14} /> Transfer Stock</>}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}
