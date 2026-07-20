// ============================================================================
// Page: Orders.jsx
// Description: B2B Order Management module. Implements purchase order creation,
//              status transition tracking (draft, confirmed, shipped, received),
//              and digital supplier/buyer dispatch operations.
// ============================================================================
import React, { useEffect, useState, useCallback, useRef } from 'react'
import AppLayout from '../layouts/AppLayout'
import { useAuth } from '../contexts/AuthContext'
import { API_BASE } from '../config'
import { AlertIcon, BillsIcon, CheckIcon, CloseIcon, DownloadIcon, ImportIcon, OrderIcon, PackageIcon, PlusIcon, SummaryIcon, TruckIcon, BellIcon, SearchIcon, ExpandIcon } from '../components/Icons'
import { logger } from '../utils/logger'
import CustomSelect from '../components/common/CustomSelect'
import { STATUS_FLOW } from '../components/b2b/orderStatus'
import OrderDetailModal from '../components/b2b/OrderDetailModal'
import CatalogOrderModal from '../components/b2b/CatalogOrderModal'

const fmt = (n) =>
  n != null ? `₹${Number(n).toLocaleString('en-IN', { maximumFractionDigits: 2 })}` : '—'


// ============================================================================
// ── 2. STATE INITIALIZATION (ORDERS & TABS) ──
// ============================================================================
export default function B2BOrders() {
  const { authFetch, token, user, settings } = useAuth()

  const settingsRef = useRef(settings)
  useEffect(() => {
    settingsRef.current = settings
  }, [settings])

  // Layout & List State
  const [activeTab, setActiveTab] = useState('incoming') // 'incoming' (seller) | 'outgoing' (buyer)
  const [isFullScreen, setIsFullScreen] = useState(false)
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

  const [search, setSearch] = useState('')
  const [statusFilter, setStatusFilter] = useState('')
  const [sortConfig, setSortConfig] = useState({ key: '', direction: '' })

  const handleSort = (key) => {
    let direction = 'asc'
    if (sortConfig.key === key && sortConfig.direction === 'asc') {
      direction = 'desc'
    } else if (sortConfig.key === key && sortConfig.direction === 'desc') {
      setSortConfig({ key: '', direction: '' })
      return
    }
    setSortConfig({ key, direction })
  }

  const getFilteredOrders = () => {
    const q = search.toLowerCase()
    let items = orders.filter(o => {
      if (statusFilter && o.status !== statusFilter) return false
      const targetName = activeTab === 'incoming' ? o.buyer_name : o.seller_name
      const targetBiz = activeTab === 'incoming' ? o.buyer_bizid : o.seller_bizid
      return !q || 
        o.order_number?.toLowerCase().includes(q) || 
        targetName?.toLowerCase().includes(q) || 
        targetBiz?.toLowerCase().includes(q)
    })

    if (sortConfig.key && sortConfig.direction) {
      items.sort((a, b) => {
        let aVal = a[sortConfig.key]
        let bVal = b[sortConfig.key]

        if (sortConfig.key === 'party') {
          aVal = activeTab === 'incoming' ? a.buyer_name : a.seller_name
          bVal = activeTab === 'incoming' ? b.buyer_name : b.seller_name
        } else if (sortConfig.key === 'date') {
          aVal = a.created_at || a.order_date || ''
          bVal = b.created_at || b.order_date || ''
        }

        if (aVal === undefined || aVal === null) return 1
        if (bVal === undefined || bVal === null) return -1

        if (typeof aVal === 'string') {
          return sortConfig.direction === 'asc'
            ? aVal.localeCompare(bVal)
            : bVal.localeCompare(aVal)
        } else {
          return sortConfig.direction === 'asc'
            ? aVal - bVal
            : bVal - aVal
        }
      })
    }
    return items
  }

  const filteredOrders = getFilteredOrders()


  // SSE Stream Ref to clean up
  const eventSourceRef = useRef(null)

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
      logger.error('Error fetching orders:', err)
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
      logger.error('Error loading connected suppliers:', err)
    }
  }, [authFetch])

  // ============================================================================
  // ── 3. B2B NETWORK SYNC & SSE EFFECTS ──
  // ============================================================================
  useEffect(() => {
    loadOrders()
    const handleSync = (e) => {
      const currentSettings = settingsRef.current
      const isRealtimeGlobalEnabled = currentSettings?.general?.realtime_sync_global !== false
      if (!isRealtimeGlobalEnabled) return
      logger.debug('[ORDERS] Real-time sync event received:', e.detail)
      if (['order', 'party', 'product'].includes(e.detail.entity) || e.detail?.type === 'sync.reconnect') {
        loadOrders()
      }
    }
    window.addEventListener('focus', loadOrders)
    window.addEventListener('sync-event', handleSync)
    return () => {
      window.removeEventListener('focus', loadOrders)
      window.removeEventListener('sync-event', handleSync)
    }
  }, [loadOrders])

  // Handle SSE Realtime alerts
  useEffect(() => {
    if (!token) return

    let reconnectTimer = null
    let stopped = false

    const connectSSE = async () => {
      try {
        const ticketResponse = await fetch(`${API_BASE}/realtime/ticket`, {
          method: 'POST',
          headers: {
            'Authorization': `Bearer ${token}`
          }
        })

        if (!ticketResponse.ok) {
          throw new Error(`Failed to fetch SSE ticket: ${ticketResponse.statusText}`)
        }

        const { ticket } = await ticketResponse.json()
        const es = new EventSource(`${API_BASE}/realtime/events?ticket=${encodeURIComponent(ticket)}`)
        eventSourceRef.current = es

        es.onmessage = (e) => {
          try {
            const event = JSON.parse(e.data)
            handleRealtimeEvent(event)
          } catch (err) {
            logger.error('Failed to parse SSE event:', err)
          }
        }

        es.onerror = (err) => {
          es.close()
          if (eventSourceRef.current === es) {
            eventSourceRef.current = null
          }
          if (!stopped) {
            logger.warn('SSE disconnected, retrying in 5 seconds...', err)
            reconnectTimer = setTimeout(connectSSE, 5000)
          }
        }
      } catch (err) {
        if (!stopped) {
          logger.warn('SSE disconnected, retrying in 5 seconds...', err)
          reconnectTimer = setTimeout(connectSSE, 5000)
        }
      }
    }

    connectSSE()

    return () => {
      stopped = true
      if (reconnectTimer) {
        clearTimeout(reconnectTimer)
      }
      if (eventSourceRef.current) {
        eventSourceRef.current.close()
        eventSourceRef.current = null
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

  // ============================================================================
  // ── 4. ORDER DISPATCH & CONFIRMATION ACTIONS ──
  // ============================================================================
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

  // ============================================================================
  // ── 5. RENDER ORDERS CATALOG LAYOUT (JSX) ──
  // ============================================================================
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

        {/* Tabs & Search/Filter */}
        <div className="flex items-center justify-between page-subbar" style={{ flexWrap: 'wrap', gap: 12 }}>
          <div className="tabs" style={{ margin: 0 }}>
            <button className={`tab${activeTab === 'incoming' ? ' active' : ''}`} onClick={() => setActiveTab('incoming')}>
              <ImportIcon size={14} style={{ marginRight: 6, display: 'inline-block', verticalAlign: 'middle' }} /> Incoming Orders (Sales)
            </button>
            <button className={`tab${activeTab === 'outgoing' ? ' active' : ''}`} onClick={() => setActiveTab('outgoing')}>
              <DownloadIcon size={14} style={{ marginRight: 6, display: 'inline-block', verticalAlign: 'middle' }} /> Outgoing Orders (Purchases)
            </button>
          </div>
          <div style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
            <div className="search-bar" style={{ width: 180 }}>
              <span style={{ color: 'var(--text-muted)', display: 'flex', alignItems: 'center' }}><SearchIcon size={16} /></span>
              <input value={search} onChange={e => setSearch(e.target.value)} placeholder="Search orders…" />
            </div>
            <CustomSelect
              value={statusFilter}
              onChange={e => setStatusFilter(e.target.value)}
              style={{
                background: 'var(--bg-2)',
                border: '1px solid var(--border)',
                borderRadius: 'var(--radius-md)',
                color: 'var(--text-primary)',
                padding: '6px 12px',
                fontSize: '0.82rem',
                cursor: 'pointer'
              }}
            >
              <option value="">All Statuses</option>
              <option value="pending">Pending</option>
              <option value="accepted">Accepted</option>
              <option value="packed">Packed</option>
              <option value="dispatched">Dispatched</option>
              <option value="completed">Completed</option>
              <option value="cancelled">Cancelled</option>
              <option value="rejected">Rejected</option>
            </CustomSelect>
          </div>
        </div>

        {/* Orders Queue Table */}
        {(() => {
          const tableContent = (
            <table className="data-table">
              <thead><tr>
                <th className="sortable" onClick={() => handleSort('order_number')}>
                  Order #
                  <span className={`sort-indicator ${sortConfig.key === 'order_number' && sortConfig.direction ? 'active' : ''}`}>
                    {sortConfig.key === 'order_number' && sortConfig.direction ? (sortConfig.direction === 'asc' ? '▲' : '▼') : '⇅'}
                  </span>
                </th>
                <th className="sortable" onClick={() => handleSort('date')}>
                  Date
                  <span className={`sort-indicator ${sortConfig.key === 'date' && sortConfig.direction ? 'active' : ''}`}>
                    {sortConfig.key === 'date' && sortConfig.direction ? (sortConfig.direction === 'asc' ? '▲' : '▼') : '⇅'}
                  </span>
                </th>
                <th className="sortable" onClick={() => handleSort('party')}>
                  {activeTab === 'incoming' ? 'Buyer / Client' : 'Supplier'}
                  <span className={`sort-indicator ${sortConfig.key === 'party' && sortConfig.direction ? 'active' : ''}`}>
                    {sortConfig.key === 'party' && sortConfig.direction ? (sortConfig.direction === 'asc' ? '▲' : '▼') : '⇅'}
                  </span>
                </th>
                <th className="sortable" onClick={() => handleSort('subtotal')}>
                  Subtotal
                  <span className={`sort-indicator ${sortConfig.key === 'subtotal' && sortConfig.direction ? 'active' : ''}`}>
                    {sortConfig.key === 'subtotal' && sortConfig.direction ? (sortConfig.direction === 'asc' ? '▲' : '▼') : '⇅'}
                  </span>
                </th>
                <th className="sortable" onClick={() => handleSort('cgst_total')}>
                  Taxes
                  <span className={`sort-indicator ${sortConfig.key === 'cgst_total' && sortConfig.direction ? 'active' : ''}`}>
                    {sortConfig.key === 'cgst_total' && sortConfig.direction ? (sortConfig.direction === 'asc' ? '▲' : '▼') : '⇅'}
                  </span>
                </th>
                <th className="sortable" onClick={() => handleSort('total_amount')}>
                  Total Amount
                  <span className={`sort-indicator ${sortConfig.key === 'total_amount' && sortConfig.direction ? 'active' : ''}`}>
                    {sortConfig.key === 'total_amount' && sortConfig.direction ? (sortConfig.direction === 'asc' ? '▲' : '▼') : '⇅'}
                  </span>
                </th>
                <th className="sortable" onClick={() => handleSort('status')}>
                  Status
                  <span className={`sort-indicator ${sortConfig.key === 'status' && sortConfig.direction ? 'active' : ''}`}>
                    {sortConfig.key === 'status' && sortConfig.direction ? (sortConfig.direction === 'asc' ? '▲' : '▼') : '⇅'}
                  </span>
                </th>
                <th>Actions</th>
              </tr></thead>
              <tbody>
                {filteredOrders.length === 0 ? (
                  <tr><td colSpan={8}>
                    <div className="empty-state">
                      <div className="empty-icon"><OrderIcon size={24} /></div>
                      <h3>No orders found</h3>
                      <p>{activeTab === 'incoming' ? 'No buyers have placed orders with you yet.' : 'Click "Place B2B Order" to browse connected supplier catalogues.'}</p>
                    </div>
                  </td></tr>
                ) : filteredOrders.map(order => {
                  const status = STATUS_FLOW[order.status] || { label: order.status, variant: 'secondary' }
                  return (
                    <tr key={order.id} style={{ cursor: 'pointer' }} onClick={() => setSelectedOrder(order)}>
                      <td className="td-mono td-primary">{order.order_number}</td>
                      <td>{new Date(order.created_at || order.order_date).toLocaleDateString('en-IN')}</td>
                      <td>
                        <div style={{ fontWeight: 600 }}>{activeTab === 'incoming' ? order.buyer_name : order.seller_name}</div>
                        <div className="td-mono" style={{ fontSize: '0.72rem', color: 'var(--text-muted)' }}>{activeTab === 'incoming' ? order.buyer_bizid : order.seller_bizid}</div>
                      </td>
                      <td>{fmt(order.subtotal)}</td>
                      <td>{fmt(order.cgst_total + order.sgst_total + order.igst_total)}</td>
                      <td style={{ color: 'var(--text-primary)', fontWeight: 600 }}>{fmt(order.total_amount)}</td>
                      <td>
                        <div style={{ display: 'flex', flexDirection: 'column', gap: 4, alignItems: 'flex-start' }}>
                          <span className={`badge badge-${status.variant}`} style={{ textTransform: 'capitalize' }}>{status.label}</span>
                          {activeTab === 'outgoing' && order.status === 'completed' &&
                            (order.seller_invoice_id || justInvoiced.has(order.order_number)) && (
                            <span className="badge badge-success" style={{ fontSize: '0.68rem' }} title="Items were automatically added to your inventory as a PURCHASE">
                              <ImportIcon size={14} style={{ marginRight: 6, display: 'inline-block', verticalAlign: 'middle' }} /> Stock received
                            </span>
                          )}
                        </div>
                      </td>
                      <td onClick={e => e.stopPropagation()}>
                    <div style={{ display: 'flex', gap: 6, justifyContent: 'center' }}>
                          {activeTab === 'incoming' && status.next && (
                            <button className="btn btn-primary btn-sm" onClick={() => handleStatusChange(order.id, status.next)}>{status.nextLabel}</button>
                          )}
                          {activeTab === 'incoming' && ['pending', 'accepted'].includes(order.status) && (
                            <button className="btn btn-ghost btn-sm" style={{ color: 'var(--danger)' }} onClick={() => handleStatusChange(order.id, 'rejected')}>Reject</button>
                          )}
                          {activeTab === 'outgoing' && ['pending', 'accepted'].includes(order.status) && (
                            <button className="btn btn-ghost btn-sm" style={{ color: 'var(--danger)' }} onClick={() => handleStatusChange(order.id, 'cancelled')}>Cancel</button>
                          )}
                          <button className="btn btn-secondary btn-sm" onClick={() => setSelectedOrder(order)}>View</button>
                        </div>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          )
          if (loading) return <div className="page-loader"><span className="spinner" /> Loading order queue…</div>
          if (isFullScreen) return (
            <div className="table-fullscreen-overlay" onClick={e => { if (e.target === e.currentTarget) setIsFullScreen(false) }}>
              <div className="table-fullscreen-panel">
                <div className="table-fullscreen-header">
                  <h3>Supplier Orders — {activeTab === 'incoming' ? 'Incoming' : 'Outgoing'}</h3>
                  <button type="button" className="table-fullscreen-btn" onClick={() => setIsFullScreen(false)}>✕ Close</button>
                </div>
                <div className="data-table-wrap">{tableContent}</div>
              </div>
            </div>
          )
          return (
            <div style={{ position: 'relative', display: 'flex', flexDirection: 'column', flex: 1, minHeight: 0 }}>
              <button type="button" onClick={() => setIsFullScreen(true)} style={{ position: 'absolute', top: 6, right: 6, zIndex: 10, background: 'var(--bg-1)', border: '1px solid var(--border)', borderRadius: 'var(--radius-sm)', padding: 4, cursor: 'pointer', color: 'var(--text-secondary)' }} title="Full Screen">
                <ExpandIcon size={14} />
              </button>
              <div className="data-table-wrap">{tableContent}</div>
            </div>
          )
        })()}


        {/* Order Details Modal */}
        {/* Order Detail Modal — extracted to components/b2b/OrderDetailModal */}
        {selectedOrder && (
          <OrderDetailModal
            selectedOrder={selectedOrder} setSelectedOrder={setSelectedOrder}
            activeTab={activeTab} notes={notes}
            handleStatusChange={handleStatusChange}
          />
        )}

        {/* Place Order / Catalog Browser Modal */}
        {/* Place Order / Catalog Browser Modal — extracted to components/b2b/CatalogOrderModal */}
        {showCatalogModal && (
          <CatalogOrderModal
            setShowCatalogModal={setShowCatalogModal}
            suppliers={suppliers}
            selectedSupplier={selectedSupplier} handleSelectSupplier={handleSelectSupplier}
            catalog={catalog} catalogLoading={catalogLoading}
            cart={cart} updateCartQty={updateCartQty}
            cartItems={cartItems} cartSub={cartSub} cartCgst={cartCgst} cartSgst={cartSgst} cartIgst={cartIgst} cartTotal={cartTotal}
            notes={notes} setNotes={setNotes}
            handlePlaceOrder={handlePlaceOrder} placingOrder={placingOrder}
          />
        )}

      </div>
    </AppLayout>
  )
}
