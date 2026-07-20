// ============================================================================
// LogExpenseModal — the "Log Business Expense" modal, extracted verbatim from
// pages/Payments.jsx (repo restructure). Form state stays with the page.
// ============================================================================
import React from 'react'
import CustomSelect from '../common/CustomSelect'
import { CashIcon, CheckIcon, CloseIcon, PhoneIcon, WarehouseIcon } from '../Icons'

export default function LogExpenseModal({ expenseForm, setExpenseField, onSubmit, submitting, onClose }) {
  return (
    <div className="modal-overlay" onClick={e => e.target === e.currentTarget && onClose()}>
      <div className="modal">
        <div className="modal-header">
          <span className="modal-title"><CashIcon size={16} style={{ marginRight: 6, display: 'inline-block', verticalAlign: 'middle' }} /> Log Business Expense</span>
          <button className="btn btn-ghost btn-icon" onClick={onClose} aria-label="Close"><CloseIcon size={16} /></button>
        </div>
        <form onSubmit={onSubmit}>
          <div className="modal-body">
            <div className="grid grid-2 gap-3 mb-4">
              <div className="form-group">
                <label className="form-label">Expense Date</label>
                <input type="date" className="form-input" value={expenseForm.expense_date} onChange={e => setExpenseField('expense_date', e.target.value)} required />
              </div>
              <div className="form-group">
                <label className="form-label">Expense Category</label>
                <CustomSelect className="form-select" value={expenseForm.category} onChange={e => setExpenseField('category', e.target.value)}>
                  <option value="Rent">Rent</option>
                  <option value="Utilities">Utilities (Power, Water, Net)</option>
                  <option value="Salaries & Wages">Salaries & Wages</option>
                  <option value="Marketing & Advertising">Marketing & Ads</option>
                  <option value="Office Supplies">Office Supplies</option>
                  <option value="Travel & Conveyance">Travel & Conveyance</option>
                  <option value="Repair & Maintenance">Repair & Maintenance</option>
                  <option value="Others">Others</option>
                </CustomSelect>
              </div>
            </div>

            <div className="grid grid-2 gap-3 mb-4">
              <div className="form-group">
                <label className="form-label">Expense Type</label>
                <CustomSelect className="form-select" value={expenseForm.expense_type} onChange={e => setExpenseField('expense_type', e.target.value)}>
                  <option value="Indirect">Indirect (Operating/Office Overhead)</option>
                  <option value="Direct">Direct (Cost of Production/Goods)</option>
                </CustomSelect>
              </div>
              <div className="form-group">
                <label className="form-label">Payment Mode</label>
                <CustomSelect className="form-select" value={expenseForm.payment_mode} onChange={e => setExpenseField('payment_mode', e.target.value)}>
                  <option value="Cash"><CashIcon size={14} style={{ marginRight: 6, display: 'inline-block', verticalAlign: 'middle' }} /> Cash</option>
                  <option value="UPI"><PhoneIcon size={14} style={{ marginRight: 6, display: 'inline-block', verticalAlign: 'middle' }} /> UPI</option>
                  <option value="Bank"><WarehouseIcon size={14} style={{ marginRight: 6, display: 'inline-block', verticalAlign: 'middle' }} /> Bank Transfer</option>
                </CustomSelect>
              </div>
            </div>

            <div className="form-group mb-4">
              <label className="form-label">Amount (₹)</label>
              <input type="number" className="form-input" placeholder="0.00" min="0" step="any" value={expenseForm.amount} onChange={e => setExpenseField('amount', e.target.value)} required />
            </div>

            <div className="form-group">
              <label className="form-label">Description / Remarks</label>
              <textarea className="form-input" placeholder="e.g. Electricity bill for June…" rows={2} value={expenseForm.note} onChange={e => setExpenseField('note', e.target.value)} />
            </div>
          </div>
          <div className="modal-footer">
            <button type="button" className="btn btn-secondary" onClick={onClose}>Cancel</button>
            <button type="submit" className="btn btn-primary" disabled={submitting}>
              {submitting ? <><span className="spinner" style={{ width: 14, height: 14, borderWidth: 2 }} /> Saving…</> : <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}><CheckIcon size={14} /> Save Expense</span>}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}
