// ============================================================================
// PurchaseDetailModal — extracted verbatim from pages/Purchases.jsx (repo restructure).
// All state and handlers stay with the page and arrive as same-named props,
// so the JSX body is byte-identical to the original.
// ============================================================================
import React from 'react'
import CustomSelect from '../common/CustomSelect'
import { BillsIcon, CloseIcon, SyncIcon } from '../Icons'
import { useDocLabels } from '../../hooks/useDocLabels'

const fmt = (n) =>
  n != null ? `₹${Number(n).toLocaleString('en-IN', { maximumFractionDigits: 2 })}` : '—'

export default function PurchaseDetailModal({ selectedDetail, setShowDetailModal }) {
  const label = useDocLabels()
  return (
        <div className="modal-overlay" onClick={e => e.target === e.currentTarget && setShowDetailModal(false)}>
          <div className="modal" style={{ maxWidth: '750px', width: '95%' }}>
            <div className="modal-header">
              <span className="modal-title">
                {selectedDetail.invoice_type === 'debit_note' ? <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}><SyncIcon size={14} /> {label('purchase_return')} Details</span> : <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}><BillsIcon size={14} /> {label('purchase')} Details</span>}
              </span>
              <button className="btn btn-ghost btn-icon" onClick={() => setShowDetailModal(false)} aria-label="Close"><CloseIcon size={16} /></button>
            </div>

            <div className="modal-body" style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
              {/* Document Header */}
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: 16, borderBottom: '1px solid var(--border)', paddingBottom: 16 }}>
                <div>
                  <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>Document Number</div>
                  <div style={{ fontWeight: 700, color: 'var(--text-primary)', fontFamily: 'monospace' }}>
                    {selectedDetail.invoice_number || selectedDetail.bill_number || `#${selectedDetail.id}`}
                  </div>
                </div>
                <div>
                  <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>Supplier</div>
                  <div style={{ fontWeight: 600, color: 'var(--text-primary)' }}>{selectedDetail.supplier_name || '—'}</div>
                </div>
                <div>
                  <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>Date</div>
                  <div style={{ color: 'var(--text-primary)' }}>
                    {selectedDetail.date || selectedDetail.invoice_date ? new Date(selectedDetail.date || selectedDetail.invoice_date).toLocaleDateString('en-IN') : '—'}
                  </div>
                </div>
                <div>
                  <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>Type & Status</div>
                  <div>
                    <span className={`badge ${selectedDetail.invoice_type === 'debit_note' ? 'badge-accent' : (selectedDetail.status === 'confirmed' ? 'badge-success' : 'badge-warning')}`}>
                      {selectedDetail.invoice_type === 'debit_note' ? `${label('purchase_return')} (Return)` : `Bill: ${selectedDetail.status || 'pending'}`}
                    </span>
                  </div>
                </div>
              </div>

              {/* Items Table */}
              <div>
                <h3 style={{ fontSize: '0.9rem', fontWeight: 700, color: 'var(--text-secondary)', marginBottom: 10 }}>Line Items</h3>
                <div className="data-table-wrap">
                  <table className="data-table" style={{ fontSize: '0.8rem' }}>
                    <thead>
                      <tr>
                        <th>Item Description</th>
                        <th>HSN/SAC</th>
                        <th style={{ textAlign: 'center' }}>Qty</th>
                        <th style={{ textAlign: 'right' }}>Price</th>
                        <th style={{ textAlign: 'center' }}>Tax Rates</th>
                        <th style={{ textAlign: 'right' }}>Line Total</th>
                      </tr>
                    </thead>
                    <tbody>
                      {(selectedDetail.lines || selectedDetail.items || []).map((li, idx) => {
                        const taxDesc = li.igst_rate > 0 
                          ? `IGST ${li.igst_rate}%` 
                          : `CGST ${li.cgst_rate}% + SGST ${li.sgst_rate}%`
                        return (
                          <tr key={idx}>
                            <td className="td-primary" style={{ fontWeight: 500 }}>
                              {li.product_name}
                              {li.batch && <span style={{ display: 'block', fontSize: '0.7rem', color: 'var(--text-muted)' }}>Batch: {li.batch} {li.expiry ? `(Exp: ${li.expiry})` : ''}</span>}
                            </td>
                            <td className="td-mono">{li.hsn_sac || '—'}</td>
                            <td style={{ textAlign: 'center' }}>{li.quantity} {li.purchase_unit || li.unit || 'Nos'}</td>
                            <td style={{ textAlign: 'right' }}>{fmt(li.unit_price)}</td>
                            <td style={{ textAlign: 'center', color: 'var(--text-muted)' }}>{taxDesc}</td>
                            <td style={{ textAlign: 'right', fontWeight: 600, color: 'var(--text-primary)' }}>{fmt(li.line_total)}</td>
                          </tr>
                        )
                      })}
                    </tbody>
                  </table>
                </div>
              </div>

              {/* Summary Breakdown */}
              <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: 8, borderTop: '1px solid var(--border)', paddingTop: 16 }}>
                <div style={{ display: 'flex', width: '280px', justifyContent: 'space-between', fontSize: '0.82rem' }}>
                  <span style={{ color: 'var(--text-secondary)' }}>Subtotal:</span>
                  <span style={{ fontWeight: 600, color: 'var(--text-primary)' }}>{fmt(selectedDetail.subtotal)}</span>
                </div>
                {selectedDetail.cgst_total > 0 && (
                  <>
                    <div style={{ display: 'flex', width: '280px', justifyContent: 'space-between', fontSize: '0.82rem' }}>
                      <span style={{ color: 'var(--text-secondary)' }}>CGST Total:</span>
                      <span style={{ fontWeight: 600, color: 'var(--text-primary)' }}>{fmt(selectedDetail.cgst_total)}</span>
                    </div>
                    <div style={{ display: 'flex', width: '280px', justifyContent: 'space-between', fontSize: '0.82rem' }}>
                      <span style={{ color: 'var(--text-secondary)' }}>SGST Total:</span>
                      <span style={{ fontWeight: 600, color: 'var(--text-primary)' }}>{fmt(selectedDetail.sgst_total)}</span>
                    </div>
                  </>
                )}
                {selectedDetail.igst_total > 0 && (
                  <div style={{ display: 'flex', width: '280px', justifyContent: 'space-between', fontSize: '0.82rem' }}>
                    <span style={{ color: 'var(--text-secondary)' }}>IGST Total:</span>
                    <span style={{ fontWeight: 600, color: 'var(--text-primary)' }}>{fmt(selectedDetail.igst_total)}</span>
                  </div>
                )}
                <div style={{ display: 'flex', width: '280px', justifyContent: 'space-between', fontSize: '1.0rem', fontWeight: 700, borderTop: '1px solid var(--border)', paddingTop: 8, marginTop: 4 }}>
                  <span style={{ color: 'var(--text-primary)' }}>Grand Total:</span>
                  <span style={{ color: 'var(--success)' }}>{fmt(selectedDetail.total_amount)}</span>
                </div>
              </div>

              {/* Notes */}
              {selectedDetail.notes && (
                <div style={{ background: 'var(--bg-3)', padding: 12, borderRadius: 'var(--radius-sm)', fontSize: '0.8rem', color: 'var(--text-secondary)', borderLeft: '3px solid var(--border)' }}>
                  <strong>Note:</strong> {selectedDetail.notes}
                </div>
              )}
            </div>

            <div className="modal-footer">
              <button className="btn btn-primary" onClick={() => setShowDetailModal(false)}>Close</button>
            </div>
          </div>
        </div>
  )
}
