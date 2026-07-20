// ============================================================================
// CatalogOrderModal — extracted verbatim from pages/B2BOrders.jsx (repo restructure).
// State and handlers stay with the page and arrive as same-named props.
// ============================================================================
import React from 'react'
import { CheckIcon, CloseIcon, SummaryIcon, TruckIcon } from '../Icons'

const fmt = (n) =>
  n != null ? `₹${Number(n).toLocaleString('en-IN', { maximumFractionDigits: 2 })}` : '—'

export default function CatalogOrderModal({ setShowCatalogModal, suppliers, selectedSupplier, handleSelectSupplier, catalog, catalogLoading, cart, updateCartQty, cartItems, cartSub, cartCgst, cartSgst, cartIgst, cartTotal, notes, setNotes, handlePlaceOrder, placingOrder }) {
  return (
          <div className="modal-overlay" onClick={e => e.target === e.currentTarget && setShowCatalogModal(false)}>
            <div className="modal modal-lg" style={{ maxWidth: '90%' }}>
              <div className="modal-header">
                <span className="modal-title"><TruckIcon size={16} style={{ marginRight: 6, display: 'inline-block', verticalAlign: 'middle' }} /> Create B2B Purchase Order</span>
                <button className="btn btn-ghost btn-icon" onClick={() => setShowCatalogModal(false)} aria-label="Close"><CloseIcon size={16} /></button>
              </div>
              <div className="modal-body" style={{ display: 'flex', gap: 16, height: '70vh', overflow: 'hidden' }}>
                
                {/* Left panel: Supplier list */}
                <div style={{ width: '25%', borderRight: '1px solid var(--border)', paddingRight: 16, overflowY: 'auto' }}>
                  <h3 style={{ fontSize: '0.82rem', textTransform: 'uppercase', color: 'var(--text-secondary)', marginBottom: 8 }}>Choose Supplier</h3>
                  {suppliers.length === 0 ? (
                    <div style={{ fontSize: '0.82rem', color: 'var(--text-muted)' }}>
                      No connected suppliers. Add one in the Connections panel first.
                    </div>
                  ) : (
                    <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                      {suppliers.map(sup => (
                        <div
                          key={sup.id}
                          onClick={() => handleSelectSupplier(sup)}
                          style={{
                            background: selectedSupplier?.id === sup.id ? 'var(--accent-dim)' : 'var(--bg-3)',
                            border: selectedSupplier?.id === sup.id ? '1px solid var(--accent)' : '1px solid var(--border)',
                            padding: '8px 12px',
                            borderRadius: 'var(--radius-md)',
                            cursor: 'pointer',
                            transition: 'all var(--dur) var(--ease)'
                          }}
                        >
                          <div style={{ fontWeight: 600, fontSize: '0.875rem' }}>{sup.seller_name}</div>
                          <div className="td-mono" style={{ fontSize: '0.7rem', color: 'var(--text-muted)' }}>{sup.seller_bizid}</div>
                        </div>
                      ))}
                    </div>
                  )}
                </div>

                {/* Middle panel: Catalog List */}
                <div style={{ width: '45%', overflowY: 'auto', paddingRight: 8 }}>
                  <h3 style={{ fontSize: '0.82rem', textTransform: 'uppercase', color: 'var(--text-secondary)', marginBottom: 8 }}>
                    {selectedSupplier ? `${selectedSupplier.seller_name}'s Catalogue` : 'Select a supplier'}
                  </h3>
                  
                  {catalogLoading ? (
                    <div className="page-loader"><span className="spinner" /> Loading catalogue items…</div>
                  ) : selectedSupplier && catalog.length === 0 ? (
                    <div className="empty-state">
                      <div className="empty-icon"><SummaryIcon size={24} /></div>
                      <h4>No products available</h4>
                      <p>This supplier hasn't added any active products matching your connection scope.</p>
                    </div>
                  ) : (
                    <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                      {catalog.map(p => {
                        const qty = cart[p.product_id] || 0
                        return (
                          <div key={p.product_id} className="card" style={{ padding: '10px 14px' }}>
                            <div className="flex justify-between items-start">
                              <div>
                                <div style={{ fontWeight: 600, fontSize: '0.92rem' }}>{p.name}</div>
                                {p.description && <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary)' }}>{p.description}</div>}
                                <div style={{ display: 'flex', gap: 8, marginTop: 4, alignItems: 'center' }}>
                                  <span className="badge badge-info" style={{ fontSize: '0.7rem' }}>{p.category}</span>
                                  {p.stock !== undefined && (
                                    <span className={`badge ${p.stock === 'Out of Stock' ? 'badge-danger' : 'badge-success'}`} style={{ fontSize: '0.7rem' }}>
                                      Stock: {p.stock}
                                    </span>
                                  )}
                                </div>
                              </div>
                              <div style={{ textAlign: 'right' }}>
                                <div style={{ fontWeight: 600, color: 'var(--accent-light)' }}>
                                  {fmt(p.selling_price)}
                                </div>
                                {p.discount_pct > 0 && (
                                  <div style={{ fontSize: '0.72rem', color: 'var(--text-muted)', textDecoration: 'line-through' }}>
                                    {fmt(p.original_selling_price)}
                                  </div>
                                )}
                              </div>
                            </div>
                            
                            <div className="flex justify-end items-center gap-2 mt-2">
                              {qty > 0 && (
                                <button className="btn btn-secondary btn-sm" onClick={() => updateCartQty(p.product_id, qty - 1)} style={{ padding: '2px 8px' }}>-</button>
                              )}
                              {qty > 0 ? (
                                <span style={{ fontWeight: 600, minWidth: 20, textAlign: 'center' }}>{qty}</span>
                              ) : (
                                <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>Not in cart</span>
                              )}
                              <button className="btn btn-primary btn-sm" onClick={() => updateCartQty(p.product_id, qty + 1)} style={{ padding: '2px 8px' }}>+</button>
                            </div>
                          </div>
                        )
                      })}
                    </div>
                  )}
                </div>

                {/* Right panel: Cart summary */}
                <div style={{ width: '30%', borderLeft: '1px solid var(--border)', paddingLeft: 16, display: 'flex', flexDirection: 'column', justifyContent: 'space-between' }}>
                  <div>
                    <h3 style={{ fontSize: '0.82rem', textTransform: 'uppercase', color: 'var(--text-secondary)', marginBottom: 8 }}>Purchase Order Summary</h3>
                    {cartItems.length === 0 ? (
                      <div style={{ color: 'var(--text-muted)', fontSize: '0.85rem', textAlign: 'center', padding: '40px 0' }}>
                        Your cart is empty. Add quantities from the catalogue list.
                      </div>
                    ) : (
                      <div style={{ maxHeight: '30vh', overflowY: 'auto', marginBottom: 12, display: 'flex', flexDirection: 'column', gap: 6 }}>
                        {cartItems.map(item => (
                          <div key={item.product_id} className="flex justify-between items-center" style={{
                            background: 'var(--bg-2)',
                            padding: '6px 10px',
                            borderRadius: 'var(--radius-sm)',
                            fontSize: '0.82rem'
                          }}>
                            <div>
                              <div style={{ fontWeight: 500 }}>{item.name}</div>
                              <div style={{ color: 'var(--text-muted)' }}>{item.quantity} × {fmt(item.selling_price)}</div>
                            </div>
                            <div style={{ fontWeight: 600 }}>{fmt(item.line_total)}</div>
                          </div>
                        ))}
                      </div>
                    )}

                    <div className="form-group mb-2">
                      <label className="form-label" style={{ fontSize: '0.75rem' }}>Shipping Notes / Instructions</label>
                      <textarea
                        className="form-textarea"
                        style={{ minHeight: 60, fontSize: '0.8rem' }}
                        placeholder="Provide any custom notes or instructions..."
                        value={notes}
                        onChange={e => setNotes(e.target.value)}
                      />
                    </div>
                  </div>

                  <div style={{
                    background: 'var(--bg-3)',
                    padding: 12,
                    borderRadius: 'var(--radius-md)',
                    border: '1px solid var(--border)',
                    display: 'flex',
                    flexDirection: 'column',
                    gap: 6
                  }}>
                    <div className="flex justify-between" style={{ fontSize: '0.8rem' }}>
                      <span style={{ color: 'var(--text-secondary)' }}>Subtotal:</span>
                      <span>{fmt(cartSub)}</span>
                    </div>
                    {(cartCgst + cartSgst + cartIgst) > 0 && (
                      <div className="flex justify-between" style={{ fontSize: '0.8rem' }}>
                        <span style={{ color: 'var(--text-secondary)' }}>GST:</span>
                        <span>{fmt(cartCgst + cartSgst + cartIgst)}</span>
                      </div>
                    )}
                    <div style={{ borderTop: '1px solid var(--border)', margin: '4px 0' }} />
                    <div className="flex justify-between" style={{ fontWeight: 600, fontSize: '0.95rem', color: 'var(--accent-light)' }}>
                      <span>Total:</span>
                      <span>{fmt(cartTotal)}</span>
                    </div>
                    
                    <button
                      className="btn btn-primary"
                      style={{ marginTop: 8 }}
                      onClick={handlePlaceOrder}
                      disabled={cartItems.length === 0 || placingOrder}
                    >
                      {placingOrder ? 'Submitting PO...' : <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}><CheckIcon size={14} /> Submit Purchase Order</span>}
                    </button>
                  </div>
                </div>

              </div>
              <div className="modal-footer">
                <button className="btn btn-secondary" onClick={() => setShowCatalogModal(false)}>Close</button>
              </div>
            </div>
          </div>
  )
}
