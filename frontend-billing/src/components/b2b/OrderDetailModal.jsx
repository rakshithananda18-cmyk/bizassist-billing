// ============================================================================
// OrderDetailModal — extracted verbatim from pages/B2BOrders.jsx (repo restructure).
// State and handlers stay with the page and arrive as same-named props.
// ============================================================================
import React from 'react'
import { BillsIcon, CheckIcon, CloseIcon, PackageIcon } from '../Icons'
import { STATUS_FLOW } from './orderStatus'

const fmt = (n) =>
  n != null ? `₹${Number(n).toLocaleString('en-IN', { maximumFractionDigits: 2 })}` : '—'

export default function OrderDetailModal({ selectedOrder, setSelectedOrder, activeTab, notes, handleStatusChange }) {
  return (
          <div className="modal-overlay" onClick={e => e.target === e.currentTarget && setSelectedOrder(null)}>
            <div className="modal modal-lg">
              <div className="modal-header">
                <div>
                  <span className="modal-title">Order Details: {selectedOrder.order_number}</span>
                  <div className="td-mono" style={{ fontSize: '0.75rem', color: 'var(--text-muted)', marginTop: 2 }}>
                    ID: {selectedOrder.id} · Date: {selectedOrder.order_date}
                  </div>
                </div>
                <button className="btn btn-ghost btn-icon" onClick={() => setSelectedOrder(null)} aria-label="Close"><CloseIcon size={16} /></button>
              </div>
              <div className="modal-body">
                {/* Meta details */}
                <div className="grid grid-2 gap-4 mb-4" style={{
                  background: 'var(--bg-3)',
                  padding: '12px 16px',
                  borderRadius: 'var(--radius-md)',
                  border: '1px solid var(--border)'
                }}>
                  <div>
                    <div style={{ fontSize: '0.72rem', textTransform: 'uppercase', color: 'var(--text-secondary)' }}>Buyer / Client</div>
                    <div style={{ fontWeight: 600, fontSize: '0.95rem' }}>{selectedOrder.buyer_name}</div>
                    <div className="td-mono" style={{ fontSize: '0.78rem', color: 'var(--text-muted)' }}>{selectedOrder.buyer_bizid}</div>
                  </div>
                  <div>
                    <div style={{ fontSize: '0.72rem', textTransform: 'uppercase', color: 'var(--text-secondary)' }}>Supplier / Vendor</div>
                    <div style={{ fontWeight: 600, fontSize: '0.95rem' }}>{selectedOrder.seller_name}</div>
                    <div className="td-mono" style={{ fontSize: '0.78rem', color: 'var(--text-muted)' }}>{selectedOrder.seller_bizid}</div>
                  </div>
                </div>

                {/* B2B Sync Status */}
                {selectedOrder.status === 'completed' && (
                  <div style={{
                    background: 'rgba(46, 125, 50, 0.08)',
                    color: '#2e7d32',
                    padding: '12px 16px',
                    borderRadius: 'var(--radius-md)',
                    border: '1px solid rgba(46, 125, 50, 0.2)',
                    fontSize: '0.82rem',
                    marginBottom: '16px',
                    display: 'flex',
                    flexDirection: 'column',
                    gap: '4px'
                  }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '6px', fontWeight: 600 }}>
                      <span><PackageIcon size={16} style={{ marginRight: 6, display: 'inline-block', verticalAlign: 'middle' }} /> B2B Sync Status: Completed</span>
                    </div>
                    {activeTab === 'outgoing' ? (
                      <div style={{ color: 'var(--text-secondary)', fontSize: '0.8rem' }}>
                        All items have been automatically recorded as a <strong>PURCHASE</strong> stock movement and added to your inventory.
                      </div>
                    ) : (
                      <div style={{ color: 'var(--text-secondary)', fontSize: '0.8rem' }}>
                        This order has generated a matching sale invoice and deducted items from your inventory.
                      </div>
                    )}
                    {selectedOrder.seller_invoice_id && (
                      <div style={{ marginTop: '4px', fontSize: '0.78rem', fontWeight: 500, color: 'var(--text-primary)' }}>
                        <BillsIcon size={14} style={{ marginRight: 6, display: 'inline-block', verticalAlign: 'middle' }} /> Seller Invoice Number: <span className="td-mono" style={{ background: 'var(--bg-2)', padding: '2px 4px', borderRadius: 4 }}>B2B-{selectedOrder.order_number}</span>
                      </div>
                    )}
                  </div>
                )}

                {/* Items list */}
                <h3 style={{ fontSize: '0.85rem', textTransform: 'uppercase', color: 'var(--text-secondary)', marginBottom: 8 }}>Order Line Items</h3>
                <div className="data-table-wrap mb-4">
                  <table className="data-table">
                    <thead>
                      <tr>
                        <th>Product / Item</th>
                        <th>HSN/SAC</th>
                        <th>Unit</th>
                        <th style={{ textAlign: 'right' }}>Qty</th>
                        <th style={{ textAlign: 'right' }}>Price</th>
                        <th style={{ textAlign: 'right' }}>GST Rate</th>
                        <th style={{ textAlign: 'right' }}>Total</th>
                      </tr>
                    </thead>
                    <tbody>
                      {selectedOrder.items.map(li => (
                        <tr key={li.id}>
                          <td>
                            <div style={{ fontWeight: 500 }}>{li.product_name}</div>
                          </td>
                          <td className="td-mono">{li.hsn_sac || '—'}</td>
                          <td>{li.unit}</td>
                          <td style={{ textAlign: 'right', fontWeight: 600 }}>{li.quantity}</td>
                          <td style={{ textAlign: 'right' }}>{fmt(li.unit_price)}</td>
                          <td style={{ textAlign: 'right', color: 'var(--text-secondary)' }}>
                            {li.cgst_rate + li.sgst_rate + li.igst_rate}%
                          </td>
                          <td style={{ textAlign: 'right', fontWeight: 600, color: 'var(--text-primary)' }}>{fmt(li.line_total)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>

                {/* Notes + Totals split */}
                <div className="grid grid-2 gap-4">
                  <div>
                    <h3 style={{ fontSize: '0.85rem', textTransform: 'uppercase', color: 'var(--text-secondary)', marginBottom: 6 }}>Buyer Notes</h3>
                    <div style={{
                      background: 'var(--bg-2)',
                      padding: 12,
                      borderRadius: 'var(--radius-md)',
                      fontSize: '0.85rem',
                      color: selectedOrder.notes ? 'var(--text-primary)' : 'var(--text-muted)',
                      minHeight: 60,
                      border: '1px solid var(--border)'
                    }}>
                      {selectedOrder.notes || 'No notes attached to this order.'}
                    </div>
                  </div>
                  <div style={{
                    display: 'flex',
                    flexDirection: 'column',
                    gap: 8,
                    background: 'var(--bg-3)',
                    padding: 16,
                    borderRadius: 'var(--radius-md)',
                    border: '1px solid var(--border)'
                  }}>
                    <div className="flex justify-between" style={{ fontSize: '0.87rem' }}>
                      <span style={{ color: 'var(--text-secondary)' }}>Subtotal:</span>
                      <span>{fmt(selectedOrder.subtotal)}</span>
                    </div>
                    {selectedOrder.cgst_total > 0 && (
                      <div className="flex justify-between" style={{ fontSize: '0.82rem', color: 'var(--text-secondary)' }}>
                        <span>CGST:</span>
                        <span>{fmt(selectedOrder.cgst_total)}</span>
                      </div>
                    )}
                    {selectedOrder.sgst_total > 0 && (
                      <div className="flex justify-between" style={{ fontSize: '0.82rem', color: 'var(--text-secondary)' }}>
                        <span>SGST:</span>
                        <span>{fmt(selectedOrder.sgst_total)}</span>
                      </div>
                    )}
                    {selectedOrder.igst_total > 0 && (
                      <div className="flex justify-between" style={{ fontSize: '0.82rem', color: 'var(--text-secondary)' }}>
                        <span>IGST:</span>
                        <span>{fmt(selectedOrder.igst_total)}</span>
                      </div>
                    )}
                    <div style={{ borderTop: '1px solid var(--border)', margin: '4px 0' }} />
                    <div className="flex justify-between" style={{ fontWeight: 600, fontSize: '1.05rem', color: 'var(--accent-light)' }}>
                      <span>Total Amount:</span>
                      <span>{fmt(selectedOrder.total_amount)}</span>
                    </div>
                  </div>
                </div>
              </div>
              <div className="modal-footer">
                {activeTab === 'incoming' && STATUS_FLOW[selectedOrder.status]?.next && (
                  <button
                    className="btn btn-primary"
                    onClick={() => handleStatusChange(selectedOrder.id, STATUS_FLOW[selectedOrder.status].next)}
                  >
                    <CheckIcon size={14} style={{ marginRight: 6, display: 'inline-block', verticalAlign: 'middle' }} /> {STATUS_FLOW[selectedOrder.status].nextLabel} Order
                  </button>
                )}
                {activeTab === 'outgoing' && ['pending', 'accepted'].includes(selectedOrder.status) && (
                  <button
                    className="btn btn-primary"
                    style={{ backgroundColor: 'var(--danger)', borderColor: 'var(--danger)' }}
                    onClick={() => handleStatusChange(selectedOrder.id, 'cancelled')}
                  >
                    Cancel Order
                  </button>
                )}
                <button className="btn btn-secondary" onClick={() => setSelectedOrder(null)}>Close</button>
              </div>
            </div>
          </div>
  )
}
