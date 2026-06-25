import React, { useEffect, useState, useCallback, useRef } from 'react'
import AppLayout from '../layouts/AppLayout'
import { useAuth } from '../contexts/AuthContext'
import { API_BASE } from '../config'
import { AlertIcon, BillsIcon, CheckIcon, CloseIcon, DownloadIcon, ImportIcon, OrderIcon, PackageIcon, PlusIcon, SummaryIcon, TruckIcon, BellIcon } from '../components/Icons'
import { logger } from '../utils/logger'

const fmt = (n) =>
  n != null ? `₹${Number(n).toLocaleString('en-IN', { maximumFractionDigits: 2 })}` : '—'

const STATUS_FLOW = {
  pending: { label: 'Pending', variant: 'warning', next: 'accepted', nextLabel: 'Accept' },
  accepted: { label: 'Accepted', variant: 'info', next: 'packed', nextLabel: 'Pack' },
  packed: { label: 'Packed', variant: 'info', next: 'dispatched', nextLabel: 'Ship' },
  dispatched: { label: 'Dispatched', variant: 'info', next: 'completed', nextLabel: 'Deliver' },
  completed: { label: 'Completed', variant: 'success' },
  cancelled: { label: 'Cancelled', variant: 'danger' },
  rejected: { label: 'Rejected', variant: 'danger' }
}

export default function Orders() {
  const { authFetch, token, user } = useAuth()

  // Layout & List State
  const [activeTab, setActiveTab] = useState('incoming') // 'incoming' (seller) | 'outgoing' (buyer)
  const [orders, setOrders] = useState([])
  const [loading, setLoading] = useState(true)
  const [alert, setAlert] = useState(null)
  const [toast, setToast] = useState(null) // { msg, type }
  // Order numbers that just had stock auto-received via SSE (live badge until reload)
  const [justInvoiced, setJustInvoiced] = useState(() => new Set())

  // Details Modal State
  const [selectedOrder, setSelectedOrder] = useState(null)
  
  // Placement/Catalog Modal State
  const [showCatalogModal, setShowCatalogModal] = useState(false)
  const [suppliers, setSuppliers] = useState([])
  const [selectedSupplier, setSelectedSupplier] = useState(null) // B2BConnection object
  const [catalog, setCatalog] = useState([])
  const [catalogLoading, setCatalogLoading] = useState(false)
  
  // Cart state
  const [cart, setCart] = useState({}) // { product_id: quantity }
  const [notes, setNotes] = useState('')
  const [placingOrder, setPlacingOrder] = useState(false)

  // SSE Stream Ref to clean up
  const sseAbortControllerRef = useRef(null)

  // Load orders depending on active tab
  const loadOrders = useCallback(async () => {
    setLoading(true)
    const role = activeTab === 'incoming' ? 'seller' : 'buyer'
    try {
      const res = await authFetch(`/connections/orders?role=${role}`)
      if (res.ok) {
        const data = await res.json()
        setOrders(data)
      } else {
        setAlert({ type: 'danger', msg: 'Failed to fetch orders.' })
      }
    } catch (err) {
      console.error('Error fetching orders:', err)
      setAlert({ type: 'danger', msg: 'Network error loading orders.' })
    } finally {
      setLoading(false)
    }
  }, [activeTab, authFetch])

  // Load suppliers connected to this business (buyer role)
  const loadSuppliers = useCallback(async () => {
    try {
      const res = await authFetch('/connections/connections')
      if (res.ok) {
        const data = await res.json()
        setSuppliers(data.as_buyer || [])
      }
    } catch (err) {
      console.error('Error loading connected suppliers:', err)
    }
  }, [authFetch])

  useEffect(() => {
    loadOrders()
    const handleSync = (e) => {
      logger.info('[ORDERS] Real-time sync event received:', e.detail)
      if (['order', 'party', 'product'].includes(e.detail.entity)) {
        loadOrders()
      }
    }
    window.addEventListener('sync-event', handleSync)
    return () => {
      window.removeEventListener('sync-event', handleSync)
    }
  }, [loadOrders])

  // Handle SSE Realtime alerts
  useEffect(() => {
    if (!token) return

    // Set up AbortController to terminate fetch stream on cleanup
    const controller = new AbortController()
    sseAbortControllerRef.current = controller

    const connectSSE = async () => {
      try {
        const response = await fetch(`${API_BASE}/connections/realtime/events`, {
          headers: {
            'Authorization': `Bearer ${token}`
          },
          signal: controller.signal
        })

        if (!response.ok) {
          throw new Error('SSE connection failed')
        }

        const reader = response.body.getReader()
        const decoder = new TextDecoder()
        let buffer = ''

        while (true) {
          const { value, done } = await reader.read()
          if (done) break

          buffer += decoder.decode(value, { stream: true })
          const lines = buffer.split('\n')
          buffer = lines.pop()

          for (const line of lines) {
            if (line.startsWith('data: ')) {
              const dataStr = line.slice(6)
              try {
                const event = JSON.parse(dataStr)
                handleRealtimeEvent(event)
              } catch (e) {
                console.error('Failed to parse SSE event:', e)
              }
            }
          }
        }
      } catch (err) {
        if (err.name !== 'AbortError') {
          console.warn('SSE disconnected, retrying in 5 seconds...', err)
          setTimeout(connectSSE, 5000)
        }
      }
    }

    connectSSE()

    return () => {
      if (sseAbortControllerRef.current) {
        sseAbortControllerRef.current.abort()
      }
    }
  }, [token])

  const handleRealtimeEvent = (event) => {
    if (event.type === 'order.created') {
      logger.info('[ORDER] order.created received', event.order_number)
      showToast(`<PackageIcon size={16} style={{ marginRight: 6, display: 'inline-block', verticalAlign: 'middle' }} /> New B2B Order placed by ${event.buyer_name} for ${fmt(event.total_amount)}!`, 'success')
      if (activeTab === 'incoming') {
        loadOrders()
      }
    } else if (event.type === 'order.status') {
      logger.info('[ORDER] order.status received', event.order_number, '→', event.status)
      showToast(`<TruckIcon size={16} style={{ marginRight: 6, display: 'inline-block', verticalAlign: 'middle' }} /> Order #${event.order_number} status updated to: ${event.status}`, 'info')
      loadOrders()
    } else if (event.type === 'order.invoiced') {
      // Phase 4: the buyer's stock-in landed. Surface it + flag the row live.
      logger.info('[ORDER] order.invoiced received — stock auto-received', event.order_number, 'inv', event.seller_invoice_id)
      setJustInvoiced(prev => {
        const next = new Set(prev)
        next.add(event.order_number)
        return next
      })
      showToast(`<DownloadIcon size={32} style={{ color: 'var(--accent)' }} /> Stock auto-received — order #${event.order_number} stocked into your inventory.`, 'success')
      loadOrders()
    }
  }

  const showToast = (msg, type = 'info') => {
    setToast({ msg, type })
    setTimeout(() => setToast(null), 5000)
  }

  // Browse supplier catalog
  const handleSelectSupplier = async (supplier) => {
    setSelectedSupplier(supplier)
    setCatalog([])
    setCart({})
    setCatalogLoading(true)
    try {
      const res = await authFetch(`/connections/catalog/${supplier.seller_bizid}`)
      if (res.ok) {
        const data = await res.json()
        setCatalog(data.items || [])
      } else {
        setAlert({ type: 'danger', msg: 'Failed to retrieve supplier catalog.' })
      }
    } catch {
      setAlert({ type: 'danger', msg: 'Network error retrieving catalog.' })
    } finally {
      setCatalogLoading(false)
    }
  }

  // Add/Remove from cart
  const updateCartQty = (prodId, qty) => {
    setCart(prev => {
      const newQty = Math.max(0, qty)
      if (newQty === 0) {
        const next = { ...prev }
        delete next[prodId]
        return next
      }
      return { ...prev, [prodId]: newQty }
    })
  }

  // Calculate cart sums
  const getCartTotals = () => {
    let subtotal = 0
    let cgst = 0
    let sgst = 0
    let igst = 0
    
    const items = []
    
    Object.entries(cart).forEach(([prodId, qty]) => {
      const p = catalog.find(x => x.product_id === parseInt(prodId))
      if (!p) return
      
      const lineSub = p.selling_price * qty
      subtotal += lineSub
      cgst += lineSub * (p.cgst_rate / 100)
      sgst += lineSub * (p.sgst_rate / 100)
      igst += lineSub * (p.igst_rate / 100)
      
      items.push({
        ...p,
        quantity: qty,
        line_subtotal: lineSub,
        line_total: lineSub + (lineSub * ((p.cgst_rate + p.sgst_rate + p.igst_rate) / 100))
      })
    })

    const total = subtotal + cgst + sgst + igst
    return { subtotal, cgst, sgst, igst, total, items }
  }

  // Place B2B Order
  const handlePlaceOrder = async () => {
    const { items, total } = getCartTotals()
    if (items.length === 0 || !selectedSupplier) return
    
    setPlacingOrder(true)
    try {
      const res = await authFetch('/connections/orders', {
        method: 'POST',
        body: JSON.stringify({
          seller_bizid: selectedSupplier.seller_bizid,
          items: items.map(x => ({ product_id: x.product_id, quantity: x.quantity })),
          notes: notes.trim() || null
        })
      })
      if (res.ok) {
        setAlert({ type: 'success', msg: 'Order placed successfully!' })
        setShowCatalogModal(false)
        setCart({})
        setNotes('')
        setSelectedSupplier(null)
        loadOrders()
      } else {
        const err = await res.json().catch(() => ({}))
        setAlert({ type: 'danger', msg: err.detail || 'Could not place order.' })
      }
    } catch {
      setAlert({ type: 'danger', msg: 'Network error placing order.' })
    } finally {
      setPlacingOrder(false)
    }
  }

  // Handle status transitions
  const handleStatusChange = async (orderId, newStatus) => {
    try {
      const res = await authFetch(`/connections/orders/${orderId}/status`, {
        method: 'POST',
        body: JSON.stringify({ status: newStatus })
      })
      if (res.ok) {
        const updated = await res.json()
        showToast(`Order status updated to: ${newStatus}`, 'success')
        loadOrders()
        // Update details modal if open
        if (selectedOrder && selectedOrder.id === orderId) {
          setSelectedOrder(updated)
        }
      } else {
        const err = await res.json().catch(() => ({}))
        setAlert({ type: 'danger', msg: err.detail || 'Failed to update order status.' })
      }
    } catch {
      setAlert({ type: 'danger', msg: 'Network error updating status.' })
    }
  }

  const handleOpenCatalogModal = () => {
    loadSuppliers()
    setSelectedSupplier(null)
    setCatalog([])
    setCart({})
    setShowCatalogModal(true)
  }

  const { subtotal: cartSub, cgst: cartCgst, sgst: cartSgst, igst: cartIgst, total: cartTotal, items: cartItems } = getCartTotals()

  return (
    <AppLayout title="B2B Orders">
      <div className="slide-up">

        {/* Global SSE Toast Notification */}
        {toast && (
          <div className="toast-notification" style={{
            position: 'fixed',
            bottom: 24,
            right: 24,
            background: 'var(--bg-3)',
            border: '1px solid var(--border)',
            borderLeft: `4px solid ${toast.type === 'success' ? 'var(--success)' : 'var(--accent)'}`,
            padding: '16px 20px',
            borderRadius: 'var(--radius-md)',
            boxShadow: 'var(--shadow-lg)',
            zIndex: 9999,
            display: 'flex',
            alignItems: 'center',
            gap: 12,
            maxWidth: 400,
            animation: 'slideIn 0.3s var(--ease)'
          }}>
            <span style={{ display: 'inline-flex', alignItems: 'center' }}>{toast.type === 'success' ? <BellIcon size={16} /> : <TruckIcon size={16} />}</span>
            <span style={{ fontSize: '0.875rem', fontWeight: 500, color: 'var(--text-primary)' }}>{toast.msg}</span>
            <button onClick={() => setToast(null)} style={{ background: 'none', border: 'none', color: 'var(--text-secondary)', cursor: 'pointer', marginLeft: 'auto' }} aria-label="Close"><CloseIcon size={16} /></button>
          </div>
        )}

        {alert && (
          <div className={`alert alert-${alert.type} mb-4`} style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
            {alert.type === 'success' ? <CheckIcon size={14} style={{ color: 'var(--success)' }} /> : <AlertIcon size={14} style={{ color: 'var(--danger)' }} />} {alert.msg}
            <button onClick={() => setAlert(null)} style={{ marginLeft: 'auto', background: 'none', border: 'none', color: 'inherit', cursor: 'pointer' }} aria-label="Close"><CloseIcon size={16} /></button>
          </div>
        )}

        {/* Header */}
        <div className="page-header">
          <div className="page-header-left">
            <h1 className="page-title">B2B Orders</h1>
            <p className="page-subtitle">Track incoming sales and manage outgoing supplier restocks</p>
          </div>
          {activeTab === 'outgoing' && (
            <div className="page-actions">
              <button className="btn btn-primary" onClick={handleOpenCatalogModal}>
                <PlusIcon size={14} /> Place B2B Order
              </button>
            </div>
          )}
        </div>

        {/* Tabs */}
        <div className="tabs page-subbar">
          <button className={`tab${activeTab === 'incoming' ? ' active' : ''}`} onClick={() => setActiveTab('incoming')}>
            <ImportIcon size={14} style={{ marginRight: 6, display: 'inline-block', verticalAlign: 'middle' }} /> Incoming Orders (Sales)
          </button>
          <button className={`tab${activeTab === 'outgoing' ? ' active' : ''}`} onClick={() => setActiveTab('outgoing')}>
            <DownloadIcon size={14} style={{ marginRight: 6, display: 'inline-block', verticalAlign: 'middle' }} /> Outgoing Orders (Purchases)
          </button>
        </div>

        {/* Orders Queue Table */}
        {loading ? (
          <div className="page-loader"><span className="spinner" /> Loading order queue…</div>
        ) : (
          <div className="data-table-wrap">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Order #</th>
                  <th>Date</th>
                  <th>{activeTab === 'incoming' ? 'Buyer / Client' : 'Supplier'}</th>
                  <th>Subtotal</th>
                  <th>Taxes</th>
                  <th>Total Amount</th>
                  <th>Status</th>
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                {orders.length === 0 ? (
                  <tr>
                    <td colSpan={8}>
                      <div className="empty-state">
                        <div className="empty-icon"><OrderIcon size={24} /></div>
                        <h3>No orders found</h3>
                        <p>{activeTab === 'incoming' ? 'No buyers have placed orders with you yet.' : 'Click "Place B2B Order" to browse connected supplier catalogues.'}</p>
                      </div>
                    </td>
                  </tr>
                ) : (
                  orders.map(order => {
                    const status = STATUS_FLOW[order.status] || { label: order.status, variant: 'secondary' }
                    return (
                      <tr key={order.id} style={{ cursor: 'pointer' }} onClick={() => setSelectedOrder(order)}>
                        <td className="td-mono td-primary">{order.order_number}</td>
                        <td>{new Date(order.created_at || order.order_date).toLocaleDateString('en-IN')}</td>
                        <td>
                          <div style={{ fontWeight: 600 }}>
                            {activeTab === 'incoming' ? order.buyer_name : order.seller_name}
                          </div>
                          <div className="td-mono" style={{ fontSize: '0.72rem', color: 'var(--text-muted)' }}>
                            {activeTab === 'incoming' ? order.buyer_bizid : order.seller_bizid}
                          </div>
                        </td>
                        <td>{fmt(order.subtotal)}</td>
                        <td>{fmt(order.cgst_total + order.sgst_total + order.igst_total)}</td>
                        <td style={{ color: 'var(--text-primary)', fontWeight: 600 }}>{fmt(order.total_amount)}</td>
                        <td>
                          <div style={{ display: 'flex', flexDirection: 'column', gap: 4, alignItems: 'flex-start' }}>
                            <span className={`badge badge-${status.variant}`} style={{ textTransform: 'capitalize' }}>
                              {status.label}
                            </span>
                            {/* Buyer: stock auto-received on completion (Phase 4 sync) */}
                            {activeTab === 'outgoing' && order.status === 'completed' &&
                              (order.seller_invoice_id || justInvoiced.has(order.order_number)) && (
                              <span className="badge badge-success" style={{ fontSize: '0.68rem' }} title="Items were automatically added to your inventory as a PURCHASE">
                                <ImportIcon size={14} style={{ marginRight: 6, display: 'inline-block', verticalAlign: 'middle' }} /> Stock received
                              </span>
                            )}
                          </div>
                        </td>
                        <td onClick={e => e.stopPropagation()}>
                          <div className="flex gap-1">
                            {/* Seller Status Progression Action */}
                            {activeTab === 'incoming' && status.next && (
                              <button
                                className="btn btn-primary btn-sm"
                                onClick={() => handleStatusChange(order.id, status.next)}
                              >
                                {status.nextLabel}
                              </button>
                            )}

                            {/* Seller Reject Action */}
                            {activeTab === 'incoming' && ['pending', 'accepted'].includes(order.status) && (
                              <button
                                className="btn btn-ghost btn-sm"
                                style={{ color: 'var(--danger)' }}
                                onClick={() => handleStatusChange(order.id, 'rejected')}
                              >
                                Reject
                              </button>
                            )}

                            {/* Buyer Cancel Action */}
                            {activeTab === 'outgoing' && ['pending', 'accepted'].includes(order.status) && (
                              <button
                                className="btn btn-ghost btn-sm"
                                style={{ color: 'var(--danger)' }}
                                onClick={() => handleStatusChange(order.id, 'cancelled')}
                              >
                                Cancel
                              </button>
                            )}
                            
                            <button className="btn btn-secondary btn-sm" onClick={() => setSelectedOrder(order)}>
                              View
                            </button>
                          </div>
                        </td>
                      </tr>
                    )
                  })
                )}
              </tbody>
            </table>
          </div>
        )}

        {/* Order Details Modal */}
        {selectedOrder && (
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
        )}

        {/* Place Order / Catalog Browser Modal */}
        {showCatalogModal && (
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
        )}

      </div>
    </AppLayout>
  )
}
