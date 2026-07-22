// ============================================================================
// SaleReturnModal — extracted verbatim from pages/Parties.jsx (repo restructure).
// State and handlers stay with the page and arrive as same-named props.
// ============================================================================
import React from 'react'
import CustomSelect from '../common/CustomSelect'
import { CheckIcon, CloseIcon, SyncIcon } from '../Icons'
import { useDocLabels } from '../../hooks/useDocLabels'

const fmt = (n) =>
  n != null ? `₹${Number(n).toLocaleString('en-IN', { maximumFractionDigits: 2 })}` : '—'

export default function SaleReturnModal({ returningInvoice, setReturningInvoice, returnLines, setReturnLines, returnNote, setReturnNote, handleSaveReturn, savingReturn, setShowReturnModal, form }) {
  const label = useDocLabels()
  return (
        <div className="modal-overlay" onClick={e => e.target === e.currentTarget && setShowReturnModal(false)}>
          <div className="modal modal-lg" style={{ maxWidth: '850px', width: '95%' }}>
            <div className="modal-header">
              <span className="modal-title"><SyncIcon size={16} style={{ marginRight: 6, display: 'inline-block', verticalAlign: 'middle' }} /> Record Sales Return ({label('sale_return')})</span>
              <button className="btn btn-ghost btn-icon" onClick={() => { setShowReturnModal(false); setReturningInvoice(null); }} aria-label="Close"><CloseIcon size={16} /></button>
            </div>
            <div className="modal-body">
              <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.85rem', borderBottom: '1px solid var(--border)', paddingBottom: 10, marginBottom: 15 }}>
                <div><strong>Customer:</strong> {returningInvoice.customer || 'Walk-in / Casual'}</div>
                <div><strong>Original Invoice:</strong> {returningInvoice.invoice_no} ({returningInvoice.invoice_date})</div>
              </div>

              <div className="data-table-wrap" style={{ maxHeight: '300px', overflowY: 'auto', marginBottom: 15 }}>
                <table className="data-table" style={{ fontSize: '0.82rem' }}>
                  <thead>
                    <tr>
                      <th>Item Name</th>
                      <th style={{ width: 100, textAlign: 'center' }}>Original Qty</th>
                      <th style={{ width: 120, textAlign: 'center' }}>Return Qty</th>
                      <th style={{ width: 100, textAlign: 'right' }}>Unit Price</th>
                      <th style={{ width: 100, textAlign: 'right' }}>GST Rate</th>
                      <th style={{ width: 120, textAlign: 'right' }}>Refund Total</th>
                    </tr>
                  </thead>
                  <tbody>
                    {returnLines.map((line, idx) => {
                      const taxRate = (line.cgst_rate || 0) + (line.sgst_rate || 0) + (line.igst_rate || 0)
                      const returnQty = parseFloat(line.quantity) || 0
                      const price = parseFloat(line.unit_price) || 0
                      const refundLineTotal = returnQty * price * (1 + taxRate / 100)

                      return (
                        <tr key={idx}>
                          <td className="td-primary">{line.product_name}</td>
                          <td style={{ textAlign: 'center' }}>{line.max_quantity}</td>
                          <td style={{ textAlign: 'center' }}>
                            <input
                              type="number"
                              className="form-input"
                              style={{ padding: '4px 6px', fontSize: '0.8rem', width: '80px', textAlign: 'center', margin: '0 auto' }}
                              min="0"
                              max={line.max_quantity}
                              step="any"
                              value={line.quantity || ''}
                              onChange={e => {
                                const val = Math.min(Math.max(parseFloat(e.target.value) || 0, 0), line.max_quantity)
                                setReturnLines(prev => {
                                  const updated = [...prev]
                                  updated[idx].quantity = val
                                  return updated
                                })
                              }}
                              placeholder="0"
                            />
                          </td>
                          <td style={{ textAlign: 'right' }}>{fmt(line.unit_price)}</td>
                          <td style={{ textAlign: 'right' }}>{taxRate}%</td>
                          <td style={{ textAlign: 'right', fontWeight: 600 }}>{fmt(refundLineTotal)}</td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </div>

              {/* Summary */}
              {(() => {
                let sub = 0, tax = 0
                returnLines.forEach(l => {
                  const qty = parseFloat(l.quantity) || 0
                  const p = parseFloat(l.unit_price) || 0
                  const taxRate = (l.cgst_rate || 0) + (l.sgst_rate || 0) + (l.igst_rate || 0)
                  const taxable = qty * p
                  sub += taxable
                  tax += taxable * (taxRate / 100)
                })
                const total = sub + tax
                return (
                  <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 20, fontSize: '0.85rem', fontWeight: 600, borderTop: '1px solid var(--border)', paddingTop: 10, marginBottom: 15 }}>
                    <div>Return Subtotal: <span style={{ color: 'var(--text-secondary)' }}>{fmt(sub)}</span></div>
                    <div>Return Tax: <span style={{ color: 'var(--text-secondary)' }}>{fmt(tax)}</span></div>
                    <div>Grand Total: <span style={{ color: 'var(--accent)', fontWeight: 700 }}>{fmt(total)}</span></div>
                  </div>
                )
              })()}

              <div className="form-group">
                <label className="form-label" style={{ fontWeight: 600 }}>Remarks / Reason for Return</label>
                <textarea
                  className="form-textarea"
                  style={{ minHeight: 60 }}
                  value={returnNote}
                  onChange={e => setReturnNote(e.target.value)}
                  placeholder="Reason for return, damaged goods, client change, etc..."
                />
              </div>
            </div>
            <div className="modal-footer">
              <button className="btn btn-secondary" onClick={() => { setShowReturnModal(false); setReturningInvoice(null); }} disabled={savingReturn}>Cancel</button>
              <button
                className="btn btn-primary"
                disabled={savingReturn || returnLines.every(l => !(parseFloat(l.quantity) > 0))}
                onClick={handleSaveReturn}
              >
                {savingReturn ? <><span className="spinner" style={{ width: 14, height: 14, borderWidth: 2 }} /> Saving…</> : <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}><CheckIcon size={14} /> Record Return</span>}
              </button>
            </div>
          </div>
        </div>
  )
}
