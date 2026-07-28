// ============================================================================
// b2b/components/OrdersTab.jsx — the "Incoming Orders" and "Outgoing Orders" tabs.
// ----------------------------------------------------------------------------
// ONE component serves both directions. Incoming (I am the seller) and outgoing
// (I am the buyer) differ only in:
//   · which business is the counterparty          → counterpartyOf(order, dir)
//   · which status transitions are offered        → actionsFor(order, dir)
//   · the empty-state copy
// Everything else — filters, sorting, resizable columns, fullscreen, the detail
// modal — is identical, so duplicating it (as the old page did) would only
// guarantee the two copies drift.
//
// Pure renderer: all data and mutations arrive from useB2BOrders via props.
// ============================================================================
import React, { useMemo, useState } from 'react'
import {
  DownloadIcon, ImportIcon, OrderIcon, SearchIcon, ExpandIcon, FilterIcon, CloseIcon
} from '../../components/Icons'
import CustomSelect from '../../components/common/CustomSelect'
import ColumnResizer from '../../components/common/ColumnResizer'
import { useResizableColumns } from '../../hooks/useResizableColumns'
import { STATUS_FLOW } from '../orderStatus'
import { counterpartyOf } from '../useB2BOrders'

const fmt = (n) =>
  n != null ? `₹${Number(n).toLocaleString('en-IN', { maximumFractionDigits: 2 })}` : '—'

const COLUMNS = [
  { key: 'order_number', label: 'Order #', sortable: true },
  { key: 'date', label: 'Date', sortable: true },
  { key: 'party', label: null, sortable: true },          // label depends on direction
  { key: 'subtotal', label: 'Subtotal', sortable: true },
  { key: 'taxes', label: 'Taxes', sortable: true },
  { key: 'total_amount', label: 'Total', sortable: true },
  { key: 'status', label: 'Status', sortable: true },
  { key: 'actions', label: 'Actions', sortable: false },
]

/**
 * Which buttons a row offers. Kept as a pure function so the transition rules
 * are readable in one place and testable without a DOM.
 *   · seller drives the fulfilment rail (accept → pack → ship → deliver)
 *   · buyer may only cancel while the order hasn't been packed
 */
export function actionsFor(order, direction) {
  const flow = STATUS_FLOW[order.status] || {}
  const out = []
  if (direction === 'incoming') {
    if (flow.next) out.push({ key: flow.next, label: flow.nextLabel, variant: 'primary' })
    if (['pending', 'accepted'].includes(order.status)) {
      out.push({ key: 'rejected', label: 'Reject', variant: 'danger' })
    }
  } else if (['pending', 'accepted'].includes(order.status)) {
    out.push({ key: 'cancelled', label: 'Cancel', variant: 'danger' })
  }
  return out
}

function SortIndicator({ active, direction }) {
  return (
    <span className={`sort-indicator ${active && direction ? 'active' : ''}`}>
      {active && direction ? (direction === 'asc' ? '▲' : '▼') : '⇅'}
    </span>
  )
}

export default function OrdersTab({
  direction,                 // 'incoming' | 'outgoing'
  userId,
  orders,                    // filtered + sorted list
  loading,
  stats,
  search, setSearch,
  statusFilter, setStatusFilter,
  sort, toggleSort,
  onChangeStatus,
  onOpenOrder,
  justInvoiced,              // Set<order_number> flagged live by SSE
  onGoToOrderDesk,
}) {
  const [fullScreen, setFullScreen] = useState(false)
  const [showFilterModal, setShowFilterModal] = useState(false)
  const [dateFilter, setDateFilter] = useState('all') // 'all' | 'today' | '7days' | '30days'

  const cols = useResizableColumns({
    tableId: `b2b.orders.${direction}`,
    userId,
    columns: COLUMNS.map(c => c.key),
  })

  const partyLabel = direction === 'incoming' ? 'Buyer' : 'Supplier'
  const title = direction === 'incoming' ? 'Incoming Orders' : 'Outgoing Orders'

  // Apply date range filter in addition to search + status
  const displayOrders = useMemo(() => {
    if (!dateFilter || dateFilter === 'all') return orders
    const now = new Date()
    return orders.filter(o => {
      const dt = new Date(o.created_at || o.order_date)
      if (Number.isNaN(dt.getTime())) return true
      if (dateFilter === 'today') {
        return dt.toDateString() === now.toDateString()
      }
      if (dateFilter === '7days') {
        return (now.getTime() - dt.getTime()) <= 7 * 24 * 60 * 60 * 1000
      }
      if (dateFilter === '30days') {
        return (now.getTime() - dt.getTime()) <= 30 * 24 * 60 * 60 * 1000
      }
      return true
    })
  }, [orders, dateFilter])

  const activeFilterCount = (statusFilter ? 1 : 0) + (dateFilter !== 'all' ? 1 : 0)

  const header = (
    <thead><tr>
      {COLUMNS.map(c => {
        const label = c.key === 'party' ? partyLabel : c.label
        const isSorted = sort.key === c.key
        return (
          <th
            key={c.key}
            {...cols.headerProps(c.key, {
              className: c.sortable ? 'sortable' : undefined,
              onClick: c.sortable ? () => toggleSort(c.key) : undefined,
            })}
          >
            {label}
            {c.sortable && <SortIndicator active={isSorted} direction={sort.direction} />}
            <ColumnResizer {...cols.resizerProps(c.key)} />
          </th>
        )
      })}
    </tr></thead>
  )

  const body = (
    <tbody>
      {displayOrders.length === 0 ? (
        <tr><td colSpan={COLUMNS.length}>
          <div className="empty-state">
            <div className="empty-icon"><OrderIcon size={24} /></div>
            <h3>No orders match</h3>
            <p>
              {direction === 'incoming'
                ? 'When a connected buyer orders from your catalogue, it lands here for you to accept and fulfil.'
                : "Orders you place with your suppliers show up here. Head to the Order tab to start one."}
            </p>
            {direction === 'outgoing' && (
              <button className="btn btn-primary btn-sm" style={{ marginTop: 10 }} onClick={onGoToOrderDesk}>
                Start an order
              </button>
            )}
          </div>
        </td></tr>
      ) : displayOrders.map(order => {
        const status = STATUS_FLOW[order.status] || { label: order.status, variant: 'secondary' }
        const cp = counterpartyOf(order, direction)
        const acts = actionsFor(order, direction)
        return (
          <tr key={order.id} style={{ cursor: 'pointer' }} onClick={() => onOpenOrder(order)}>
            <td className="td-mono td-primary">{order.order_number}</td>
            <td>{new Date(order.created_at || order.order_date).toLocaleDateString('en-IN')}</td>
            <td>
              <div style={{ fontWeight: 600 }}>{cp.name}</div>
              <div className="td-mono" style={{ fontSize: '0.72rem', color: 'var(--text-muted)' }}>{cp.bizid}</div>
            </td>
            <td>{fmt(order.subtotal)}</td>
            <td>{fmt((order.cgst_total || 0) + (order.sgst_total || 0) + (order.igst_total || 0))}</td>
            <td style={{ color: 'var(--text-primary)', fontWeight: 600 }}>{fmt(order.total_amount)}</td>
            <td>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 4, alignItems: 'flex-start' }}>
                <span className={`badge badge-${status.variant}`} style={{ textTransform: 'capitalize' }}>{status.label}</span>
                {direction === 'outgoing' && order.status === 'completed' &&
                  (order.seller_invoice_id || justInvoiced?.has(order.order_number)) && (
                  <span className="badge badge-success" style={{ fontSize: '0.66rem' }} title="These items were automatically added to your inventory as a purchase">
                    <ImportIcon size={12} style={{ marginRight: 4, verticalAlign: 'middle' }} />Stock received
                  </span>
                )}
              </div>
            </td>
            <td onClick={e => e.stopPropagation()}>
              <div style={{ display: 'flex', gap: 6, justifyContent: 'center', flexWrap: 'wrap' }}>
                {acts.map(a => (
                  <button
                    key={a.key}
                    className={a.variant === 'danger' ? 'btn btn-ghost btn-sm' : 'btn btn-primary btn-sm'}
                    style={a.variant === 'danger' ? { color: 'var(--danger)' } : undefined}
                    onClick={() => onChangeStatus(order.id, a.key)}
                  >{a.label}</button>
                ))}
                <button className="btn btn-secondary btn-sm" onClick={() => onOpenOrder(order)}>View</button>
              </div>
            </td>
          </tr>
        )
      })}
    </tbody>
  )

  const table = (
    <table ref={cols.tableRef} className={`data-table ${cols.tableClassName}`.trim()}>
      {header}
      {body}
    </table>
  )

  return (
    <div className="b2b-orders-tab">
      {/* ── BAR 1: Single Smart Stat Summary Card ────────────────────────────── */}
      <div className="card b2b-summary-card">
        <div className="b2b-stat-segment">
          <span className="b2b-stat-label">Total orders</span>
          <span className="b2b-stat-value">{stats.count}</span>
        </div>
        <div className="b2b-stat-divider" />
        <div className="b2b-stat-segment">
          <span className="b2b-stat-label">In progress</span>
          <span className="b2b-stat-value">{stats.open}</span>
        </div>
        <div className="b2b-stat-divider" />
        <div className="b2b-stat-segment">
          <span className="b2b-stat-label">Open value</span>
          <span className="b2b-stat-value">{fmt(stats.openValue)}</span>
        </div>
        {direction === 'incoming' && stats.awaitingMe > 0 && (
          <>
            <div className="b2b-stat-divider" />
            <div className="b2b-stat-segment is-alert">
              <span className="b2b-stat-label">Awaiting response</span>
              <span className="b2b-stat-value">{stats.awaitingMe}</span>
            </div>
          </>
        )}
      </div>

      {/* ── BAR 2: Toolbar (Search, Filter Modal, Status Select, Table Actions) ── */}
      <div className="b2b-filter-bar">
        <div className="search-bar" style={{ width: 240, height: 34, flexShrink: 0 }}>
          <span style={{ color: 'var(--text-muted)', display: 'flex', alignItems: 'center' }}><SearchIcon size={15} /></span>
          <input
            value={search}
            onChange={e => setSearch(e.target.value)}
            placeholder={`Search by # or ${partyLabel.toLowerCase()}…`}
          />
          {search && (
            <button
              type="button"
              onClick={() => setSearch('')}
              aria-label="Clear search"
              style={{ background: 'none', border: 'none', color: 'var(--text-muted)', cursor: 'pointer', padding: 2, display: 'flex' }}
            >
              <CloseIcon size={12} />
            </button>
          )}
        </div>

        <CustomSelect
          value={statusFilter}
          onChange={e => setStatusFilter(e.target.value)}
          style={{
            background: 'var(--bg-2)', border: '1px solid var(--border)',
            borderRadius: 'var(--radius-md)', color: 'var(--text-primary)',
            padding: '6px 12px', fontSize: '0.82rem', cursor: 'pointer', height: 34, width: 'auto', minWidth: 140, flexShrink: 0
          }}
        >
          <option value="">All statuses</option>
          {Object.entries(STATUS_FLOW).map(([k, v]) => <option key={k} value={k}>{v.label}</option>)}
        </CustomSelect>

        <button
          type="button"
          className={`btn btn-sm ${activeFilterCount > 0 ? 'btn-primary' : 'btn-secondary'}`}
          onClick={() => setShowFilterModal(true)}
          style={{ height: 34, gap: 6, display: 'inline-flex', alignItems: 'center', flexShrink: 0 }}
        >
          <FilterIcon size={14} />
          Filters
          {activeFilterCount > 0 && (
            <span style={{
              background: 'var(--accent)', color: '#fff', borderRadius: '50%',
              width: 18, height: 18, fontSize: '0.7rem', fontWeight: 700,
              display: 'inline-flex', alignItems: 'center', justifyContent: 'center', marginLeft: 2
            }}>
              {activeFilterCount}
            </span>
          )}
        </button>

        {dateFilter !== 'all' && (
          <span className="badge badge-secondary" style={{ height: 28, gap: 6, display: 'inline-flex', alignItems: 'center', fontSize: '0.75rem', padding: '0 8px' }}>
            Date: {dateFilter === 'today' ? 'Today' : dateFilter === '7days' ? 'Last 7d' : 'Last 30d'}
            <button
              type="button"
              onClick={() => setDateFilter('all')}
              style={{ background: 'none', border: 'none', cursor: 'pointer', padding: 0, color: 'inherit', display: 'inline-flex' }}
            >
              <CloseIcon size={12} />
            </button>
          </span>
        )}

        <div style={{ flex: 1 }} />

        <div style={{ display: 'flex', gap: 6, alignItems: 'center', flexShrink: 0 }}>
          <button type="button" className="col-layout-btn" onClick={() => cols.autoFitAll()} title="Size every column to fit its content">
            Fit columns
          </button>
          <button
            type="button"
            className="col-layout-btn"
            onClick={() => cols.resetWidths()}
            disabled={!cols.isCustomized}
            title={cols.isCustomized ? 'Restore default column widths' : 'Defaults active'}
          >
            Reset widths
          </button>
          <button type="button" className="col-layout-btn" onClick={() => setFullScreen(true)} title="Expand the table">
            <ExpandIcon size={13} /> Full screen
          </button>
        </div>
      </div>

      {loading ? (
        <div className="page-loader"><span className="spinner" /> Loading orders…</div>
      ) : fullScreen ? (
        <div className="table-fullscreen-overlay" onClick={e => { if (e.target === e.currentTarget) setFullScreen(false) }}>
          <div className="table-fullscreen-panel">
            <div className="table-fullscreen-header">
              <h3>{title}<span style={{ color: 'var(--text-muted)', fontWeight: 500 }}> · {displayOrders.length} shown</span></h3>
              <div className="table-fullscreen-actions">
                <button type="button" className="table-fullscreen-btn" onClick={() => cols.autoFitAll()}>Fit columns</button>
                <button type="button" className="table-fullscreen-btn" onClick={() => cols.resetWidths()} disabled={!cols.isCustomized}>Reset widths</button>
                <button type="button" className="table-fullscreen-btn" onClick={() => setFullScreen(false)}>✕ Close</button>
              </div>
            </div>
            <div className="data-table-wrap">{table}</div>
          </div>
        </div>
      ) : (
        <div className="data-table-wrap">{table}</div>
      )}

      {/* ── Filter Modal ─────────────────────────────────────────────────── */}
      {showFilterModal && (
        <div className="modal-backdrop" onClick={() => setShowFilterModal(false)}>
          <div className="modal" style={{ maxWidth: 440 }} onClick={e => e.stopPropagation()}>
            <div className="modal-header">
              <span className="modal-title" style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                <FilterIcon size={16} /> Filter {title}
              </span>
              <button className="btn btn-ghost btn-icon" onClick={() => setShowFilterModal(false)} aria-label="Close">
                <CloseIcon size={16} />
              </button>
            </div>

            <div className="modal-body" style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
              {/* Status Filter section */}
              <div>
                <label style={{ fontSize: '0.78rem', fontWeight: 700, textTransform: 'uppercase', color: 'var(--text-muted)', display: 'block', marginBottom: 8 }}>
                  Order Status
                </label>
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
                  <button
                    type="button"
                    className={`btn btn-sm ${!statusFilter ? 'btn-primary' : 'btn-secondary'}`}
                    onClick={() => setStatusFilter('')}
                  >
                    All Statuses
                  </button>
                  {Object.entries(STATUS_FLOW).map(([k, v]) => (
                    <button
                      key={k}
                      type="button"
                      className={`btn btn-sm ${statusFilter === k ? 'btn-primary' : 'btn-secondary'}`}
                      onClick={() => setStatusFilter(k)}
                    >
                      {v.label}
                    </button>
                  ))}
                </div>
              </div>

              {/* Date Filter section */}
              <div>
                <label style={{ fontSize: '0.78rem', fontWeight: 700, textTransform: 'uppercase', color: 'var(--text-muted)', display: 'block', marginBottom: 8 }}>
                  Date Range
                </label>
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
                  {[
                    { key: 'all', label: 'All Time' },
                    { key: 'today', label: 'Today' },
                    { key: '7days', label: 'Last 7 Days' },
                    { key: '30days', label: 'Last 30 Days' },
                  ].map(d => (
                    <button
                      key={d.key}
                      type="button"
                      className={`btn btn-sm ${dateFilter === d.key ? 'btn-primary' : 'btn-secondary'}`}
                      onClick={() => setDateFilter(d.key)}
                    >
                      {d.label}
                    </button>
                  ))}
                </div>
              </div>
            </div>

            <div className="modal-footer" style={{ justifyContent: 'space-between' }}>
              <button
                type="button"
                className="btn btn-ghost btn-sm"
                onClick={() => { setStatusFilter(''); setDateFilter('all') }}
              >
                Reset All Filters
              </button>
              <button
                type="button"
                className="btn btn-primary btn-sm"
                onClick={() => setShowFilterModal(false)}
              >
                Apply & Close
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
