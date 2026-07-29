// ============================================================================
// Page: B2B.jsx — the unified B2B workspace.
// ----------------------------------------------------------------------------
// Replaces the two old pages (B2BOrders + B2BNetwork) with one surface and four
// tabs:
//
//   Order              — browse a connected supplier's catalogue and place an order
//   Outgoing Orders    — orders I placed, and their fulfilment state
//   Incoming Orders    — orders placed with me, and the fulfilment rail I drive
//   Connections        — approved links, requests waiting on me, requests I sent
//
// Responsibilities are deliberately thin here. This file owns ONLY:
//   · which tab is showing (and the ?tab= deep link)
//   · the single realtime stream, fanned out to the hooks
//   · toasts / alerts
// Data lives in useB2BConnections + useB2BOrders, transport in api/b2bClient,
// and every pixel is rendered by a tab component. Nothing in this file knows an
// endpoint URL or a table column.
// ============================================================================
import React, { useCallback, useEffect, useMemo, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import AppLayout from '../layouts/AppLayout'
import { useAuth } from '../contexts/AuthContext'
import { useConfirm } from '../contexts/ConfirmContext'
import { logger } from '../utils/logger'
import {
  AlertIcon, BellIcon, CartIcon, CheckIcon, CloseIcon, ConnectionIcon,
  DownloadIcon, ImportIcon, TruckIcon,
} from '../components/Icons'
import WorkspaceTopBar, { WsDivider } from '../components/common/WorkspaceTopBar'
import { useForegroundRefresh } from '../hooks/useForegroundRefresh'
// One import surface for the whole B2B module (src/b2b/index.js). Keeping the
// page's knowledge of B2B down to this single line is what makes the module
// liftable into a future retail customer app.
import {
  b2bClient as b2b,
  useB2BConnections, useB2BOrders, useB2BRealtime,
  OrderDeskTab, OrdersTab, ConnectionsTab, OrderDetailModal, OfflineNotice,
} from '../b2b'

const fmt = (n) =>
  n != null ? `₹${Number(n).toLocaleString('en-IN', { maximumFractionDigits: 2 })}` : '—'

const TABS = [
  { key: 'order', label: 'Order', icon: CartIcon },
  { key: 'outgoing', label: 'Outgoing Orders', icon: DownloadIcon },
  { key: 'incoming', label: 'Incoming Orders', icon: ImportIcon },
  { key: 'connections', label: 'Connections', icon: ConnectionIcon },
]

export default function B2B() {
  const { authFetch, token, user, settings } = useAuth()
  const confirm = useConfirm()

  const [params, setParams] = useSearchParams()
  const urlTab = params.get('tab')
  const [tab, setTab] = useState(TABS.some(t => t.key === urlTab) ? urlTab : 'order')

  const [alert, setAlert] = useState(null)
  const [toast, setToast] = useState(null)
  const [myBizId, setMyBizId] = useState('')
  const [copied, setCopied] = useState(false)
  // Which mode B2B is in on this backend — drives the offline notice.
  const [b2bStatus, setB2bStatus] = useState(null)

  const notifyError = useCallback((msg) => setAlert({ type: 'danger', msg }), [])
  const notifyOk = useCallback((msg) => setAlert({ type: 'success', msg }), [])

  const showToast = useCallback((msg, type = 'info') => {
    setToast({ msg, type })
    setTimeout(() => setToast(null), 5000)
  }, [])

  const goTab = useCallback((key) => {
    setTab(key)
    setParams(prev => {
      const next = new URLSearchParams(prev)
      next.set('tab', key)
      return next
    }, { replace: true })
  }, [setParams])

  // ── Data ──────────────────────────────────────────────────────────────────
  const connections = useB2BConnections(authFetch, { onError: notifyError, onSuccess: notifyOk })
  const outgoing = useB2BOrders(authFetch, { direction: 'outgoing', onError: notifyError })
  const incoming = useB2BOrders(authFetch, { direction: 'incoming', onError: notifyError })

  useEffect(() => {
    let cancelled = false
    b2b.fetchMyBizId(authFetch)
      .then(d => { if (!cancelled && d?.public_id) setMyBizId(d.public_id) })
      .catch(err => logger.warn('[B2B] could not load BizID', err))
    b2b.fetchB2BStatus(authFetch)
      .then(st => { if (!cancelled) setB2bStatus(st) })
    return () => { cancelled = true }
  }, [authFetch])

  // ── Order desk state ──────────────────────────────────────────────────────
  const [selectedSupplier, setSelectedSupplier] = useState(null)
  const [catalog, setCatalog] = useState([])
  const [catalogLoading, setCatalogLoading] = useState(false)
  const [placing, setPlacing] = useState(false)

  const suppliers = connections.as_buyer

  // Auto-select the first supplier so the desk is never a dead end on arrival.
  useEffect(() => {
    if (!selectedSupplier && suppliers.length > 0) setSelectedSupplier(suppliers[0])
    if (selectedSupplier && !suppliers.some(s => s.id === selectedSupplier.id)) {
      setSelectedSupplier(suppliers[0] || null)   // link revoked while browsing
    }
  }, [suppliers, selectedSupplier])

  const loadCatalog = useCallback(async (supplier) => {
    if (!supplier) { setCatalog([]); return }
    setCatalogLoading(true)
    try {
      setCatalog(await b2b.fetchSupplierCatalog(authFetch, supplier.counterparty_bizid || supplier.seller_bizid))
    } catch (err) {
      notifyError(err.message || 'Failed to load the supplier catalogue.')
      setCatalog([])
    } finally {
      setCatalogLoading(false)
    }
  }, [authFetch, notifyError])

  useEffect(() => { loadCatalog(selectedSupplier) }, [selectedSupplier, loadCatalog])

  /**
   * Manual pull for the Order tab's refresh button.
   *
   * A supplier's prices, tier discount and stock counts live in THEIR database
   * and change while this page is open; nothing pushes those to us. The
   * connection list comes too, because the supplier dropdown is built from it —
   * a link approved (or revoked) a moment ago should show up in the same press
   * rather than needing a full page reload.
   */
  const refreshOrderDesk = useCallback(async () => {
    await Promise.all([
      loadCatalog(selectedSupplier),
      connections.reload(),
    ])
  }, [loadCatalog, selectedSupplier, connections])

  const handlePlaceOrder = useCallback(async ({ lines, totals, notes }) => {
    if (!selectedSupplier || lines.length === 0) return false

    const ok = await confirm({
      mode: 'create',
      title: 'Place this order?',
      entity: selectedSupplier.counterparty_name || selectedSupplier.seller_name,
      summary: [
        { key: 'supplier', label: 'Supplier', value: selectedSupplier.counterparty_name || selectedSupplier.seller_name || '—' },
        { key: 'items', label: 'Items', value: String(lines.length) },
        { key: 'total', label: 'Total', value: fmt(totals.total) },
      ],
      confirmText: 'Place order',
    })
    if (!ok) return false

    setPlacing(true)
    try {
      await b2b.placeOrder(authFetch, {
        sellerBizId: selectedSupplier.counterparty_bizid || selectedSupplier.seller_bizid,
        items: lines,
        notes,
      })
      notifyOk('Order placed — you can track it under Outgoing Orders.')
      outgoing.reload()
      goTab('outgoing')
      return true
    } catch (err) {
      notifyError(err.message || 'Could not place the order.')
      return false
    } finally {
      setPlacing(false)
    }
  }, [authFetch, confirm, selectedSupplier, notifyOk, notifyError, outgoing, goTab])

  // ── Realtime: ONE stream for the whole workspace ──────────────────────────
  const [justInvoiced, setJustInvoiced] = useState(() => new Set())
  const realtimeEnabled = settings?.general?.realtime_sync_global !== false

  const handleRealtime = useCallback((event) => {
    switch (event.type) {
      case 'order.created':
        showToast(`New order from ${event.buyer_name || 'a buyer'} · ${fmt(event.total_amount)}`, 'success')
        incoming.reload()
        break
      case 'order.status':
        showToast(`Order #${event.order_number} → ${event.status}`, 'info')
        incoming.reload()
        outgoing.reload()
        break
      case 'order.invoiced':
        setJustInvoiced(prev => new Set(prev).add(event.order_number))
        showToast(`Stock auto-received — order #${event.order_number} is in your inventory.`, 'success')
        outgoing.reload()
        break
      case 'connection.requested':
        showToast(`${event.from_name || 'A business'} wants to connect with you.`, 'info')
        connections.reload()
        break
      case 'connection.approved':
        showToast(`${event.from_name || 'They'} approved your connection request.`, 'success')
        connections.reload()
        break
      case 'connection.rejected':
        connections.reload()
        break
      default:
        break
    }
  }, [showToast, incoming, outgoing, connections])

  useB2BRealtime({ token, enabled: realtimeEnabled, onEvent: handleRealtime })

  // Cross-device sync events (the app-wide bus) — refresh what's affected.
  useEffect(() => {
    const onSync = (e) => {
      if (!realtimeEnabled) return
      const entity = e.detail?.entity
      if (['order', 'party', 'product'].includes(entity) || e.detail?.type === 'sync.reconnect') {
        incoming.reload()
        outgoing.reload()
      }
    }
    window.addEventListener('sync-event', onSync)
    return () => window.removeEventListener('sync-event', onSync)
  }, [realtimeEnabled, incoming, outgoing])

  useForegroundRefresh({
    onResume: () => { incoming.reload(); outgoing.reload(); connections.reload() },
  })

  // ── Order detail modal ────────────────────────────────────────────────────
  const [openOrder, setOpenOrder] = useState(null)
  const openOrderDirection = tab === 'incoming' ? 'incoming' : 'outgoing'

  const changeStatus = useCallback(async (direction, orderId, status) => {
    const queue = direction === 'incoming' ? incoming : outgoing
    const updated = await queue.changeStatus(orderId, status)
    if (updated) {
      showToast(`Order status updated to ${status}.`, 'success')
      setOpenOrder(prev => (prev && prev.id === orderId ? { ...prev, ...updated } : prev))
    }
  }, [incoming, outgoing, showToast])

  const [reconcilingOrderId, setReconcilingOrderId] = useState(null)
  const reconcilePurchaseBill = useCallback(async (order) => {
    const ok = await confirm({
      mode: 'create',
      title: 'Create the missing Purchase Bill?',
      entity: order.order_number,
      summary: [
        { key: 'order', label: 'B2B order', value: order.order_number },
        { key: 'supplier', label: 'Supplier', value: order.seller_name || '—' },
        { key: 'total', label: 'Total', value: fmt(order.total_amount) },
        { key: 'stock', label: 'Stock', value: order.buyer_stock_received
          ? 'Already received; stock will not change.'
          : 'This creates the bill only; stock will not change.' },
      ],
      confirmText: 'Create Purchase Bill',
    })
    if (!ok) return

    setReconcilingOrderId(order.id)
    try {
      const updated = await b2b.reconcilePurchaseBill(authFetch, order.id)
      setOpenOrder(prev => (prev && prev.id === order.id ? { ...prev, ...updated } : prev))
      await outgoing.reload()
      notifyOk(`Purchase Bill ${updated.buyer_purchase_invoice_number || ''} created. Stock was not received again.`)
    } catch (err) {
      notifyError(err.message || 'Could not create the missing B2B Purchase Bill.')
    } finally {
      setReconcilingOrderId(null)
    }
  }, [authFetch, confirm, notifyError, notifyOk, outgoing])

  const copyBizId = useCallback(() => {
    if (!myBizId) return
    navigator.clipboard.writeText(myBizId)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }, [myBizId])

  const pendingCount = connections.counts?.incoming || 0
  const badges = useMemo(() => ({
    incoming: incoming.stats.awaitingMe,
    connections: pendingCount,
  }), [incoming.stats.awaitingMe, pendingCount])

  return (
    <AppLayout title="B2B">
      {/* Same shell geometry as Stock & Purchases and Contacts & Payments:
          a full-height flex column whose top bar is the page heading, and whose
          body scrolls internally. Nothing above the bar, so the tabs sit at the
          same y as every other workspace. */}
      <div className="slide-up b2b-shell">
        {toast && (
          <div className="b2b-toast">
            <span style={{ display: 'inline-flex', alignItems: 'center' }}>
              {toast.type === 'success' ? <BellIcon size={16} /> : <TruckIcon size={16} />}
            </span>
            <span style={{ fontSize: '0.875rem', fontWeight: 500, color: 'var(--text-primary)' }}>{toast.msg}</span>
            <button onClick={() => setToast(null)} aria-label="Close"
              style={{ background: 'none', border: 'none', color: 'var(--text-secondary)', cursor: 'pointer', marginLeft: 'auto' }}>
              <CloseIcon size={16} />
            </button>
          </div>
        )}

        {alert && (
          <div className={`alert alert-${alert.type} mb-4`} style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
            {alert.type === 'success'
              ? <CheckIcon size={14} style={{ color: 'var(--success)' }} />
              : <AlertIcon size={14} style={{ color: 'var(--danger)' }} />}
            {alert.msg}
            <button onClick={() => setAlert(null)} aria-label="Close"
              style={{ marginLeft: 'auto', background: 'none', border: 'none', color: 'inherit', cursor: 'pointer' }}>
              <CloseIcon size={16} />
            </button>
          </div>
        )}

        {/* Signature Page Header */}
        <div className="page-header">
          <div className="page-header-left">
            <h1 className="page-title">
              <ConnectionIcon size={20} style={{ color: 'var(--accent)' }} /> B2B Network & Orders
            </h1>
            <p className="page-subtitle">Connect with suppliers & customers, manage purchase orders, and track live order status</p>
          </div>
          <div className="page-actions">
            <span style={{ fontSize: '0.78rem', color: 'var(--text-muted)', fontWeight: 600, whiteSpace: 'nowrap' }}>
              {myBizId ? <>BizID <span className="td-mono" style={{ color: 'var(--accent)', fontWeight: 700 }}>{myBizId}</span></> : null}
            </span>
          </div>
        </div>

        <WorkspaceTopBar
          windowControls={false}
        >
          <span className="ws-workspace-title">
            <ConnectionIcon size={16} /> B2B
          </span>
          <WsDivider />
          {TABS.map(({ key, label, icon: Icon }) => (
            <button
              key={key}
              className={`ws-tab ${tab === key ? 'active' : ''}`}
              onClick={() => goTab(key)}
            >
              <Icon size={14} />
              {label}
              {badges[key] > 0 && <span className="b2b-tab-count is-alert">{badges[key]}</span>}
            </button>
          ))}
        </WorkspaceTopBar>

        <div className="b2b-body">
        <OfflineNotice status={b2bStatus} />
        {tab === 'order' && (
          <OrderDeskTab
            suppliers={suppliers}
            selectedSupplier={selectedSupplier}
            onSelectSupplier={setSelectedSupplier}
            catalog={catalog}
            catalogLoading={catalogLoading}
            connectionsLoading={connections.loading}
            onPlaceOrder={handlePlaceOrder}
            placing={placing}
            onGoToConnections={() => goTab('connections')}
            onRefresh={refreshOrderDesk}
            userId={user?.id}
          />
        )}

        {tab === 'outgoing' && (
          <OrdersTab
            direction="outgoing"
            userId={user?.id}
            orders={outgoing.visible}
            loading={outgoing.loading}
            stats={outgoing.stats}
            search={outgoing.search} setSearch={outgoing.setSearch}
            statusFilter={outgoing.statusFilter} setStatusFilter={outgoing.setStatusFilter}
            sort={outgoing.sort} toggleSort={outgoing.toggleSort}
            onChangeStatus={(id, s) => changeStatus('outgoing', id, s)}
            onOpenOrder={setOpenOrder}
            justInvoiced={justInvoiced}
            onGoToOrderDesk={() => goTab('order')}
            onReconcilePurchaseBill={reconcilePurchaseBill}
            reconcilingOrderId={reconcilingOrderId}
          />
        )}

        {tab === 'incoming' && (
          <OrdersTab
            direction="incoming"
            userId={user?.id}
            orders={incoming.visible}
            loading={incoming.loading}
            stats={incoming.stats}
            search={incoming.search} setSearch={incoming.setSearch}
            statusFilter={incoming.statusFilter} setStatusFilter={incoming.setStatusFilter}
            sort={incoming.sort} toggleSort={incoming.toggleSort}
            onChangeStatus={(id, s) => changeStatus('incoming', id, s)}
            onOpenOrder={setOpenOrder}
            justInvoiced={justInvoiced}
            onGoToOrderDesk={() => goTab('order')}
          />
        )}

        {tab === 'connections' && (
          <ConnectionsTab
            myBizId={myBizId}
            connections={connections}
            onCopyBizId={copyBizId}
            copied={copied}
          />
        )}
        </div>

        {openOrder && (
          <OrderDetailModal
            selectedOrder={openOrder}
            setSelectedOrder={setOpenOrder}
            activeTab={openOrderDirection}
            notes={openOrder.notes || ''}
            handleStatusChange={(id, s) => changeStatus(openOrderDirection, id, s)}
          />
        )}
      </div>
    </AppLayout>
  )
}
