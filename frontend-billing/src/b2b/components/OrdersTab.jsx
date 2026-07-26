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
import React, { useState } from 'react'
import {
  DownloadIcon, ImportIcon, OrderIcon, SearchIcon, ExpandIcon,
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
  const cols = useResizableColumns({
    tableId: `b2b.orders.${direction}`,
    userId,
    columns: COLUMNS.map(c => c.key),
  })

  const partyLabel = direction === 'incoming' ? 'Buyer' : 'Supplier'
  const title = direction === 'incoming' ? 'Incoming Orders' : 'Outgoing Orders'

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
      {orders.length === 0 ? (
        <tr><td colSpan={COLUMNS.length}>
          <div className="empty-state">
            <div className="empty-icon"><OrderIcon size={24} /></div>
            <h3>No orders here</h3>
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
      ) : orders.map(order => {
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
      {/* Summary strip — the three numbers that decide what to do next. */}
      <div className="b2b-stat-strip">
        <div className="b2b-stat">
          <span className="b2b-stat-value">{stats.count}</span>
          <span className="b2b-stat-label">Total orders</span>
        </div>
        <div className="b2b-stat">
          <span className="b2b-stat-value">{stats.open}</span>
          <span className="b2b-stat-label">In progress</span>
        </div>
        <div className="b2b-stat">
          <span className="b2b-stat-value">{fmt(stats.openValue)}</span>
          <span className="b2b-stat-label">Open value</span>
        </div>
        {direction === 'incoming' && stats.awaitingMe > 0 && (
          <div className="b2b-stat is-alert">
            <span className="b2b-stat-value">{stats.awaitingMe}</span>
            <span className="b2b-stat-label">Awaiting your response</span>
          </div>
        )}
      </div>

      <div className="b2b-filter-bar">
        <div className="search-bar" style={{ width: 220, height: 34 }}>
          <span style={{ color: 'var(--text-muted)', display: 'flex', alignItems: 'center' }}><SearchIcon size={15} /></span>
          <input value={search} onChange={e => setSearch(e.target.value)} placeholder={`Search by order # or ${partyLabel.toLowerCase()}…`} />
        </div>
        <CustomSelect
          value={statusFilter}
          onChange={e => setStatusFilter(e.target.value)}
          style={{
            background: 'var(--bg-2)', border: '1px solid var(--border)',
            borderRadius: 'var(--radius-md)', color: 'var(--text-primary)',
            padding: '6px 12px', fontSize: '0.82rem', cursor: 'pointer',
          }}
        >
          <option value="">All statuses</option>
          {Object.entries(STATUS_FLOW).map(([k, v]) => <option key={k} value={k}>{v.label}</option>)}
        </CustomSelect>
        <div style={{ flex: 1 }} />
        <button type="button" className="col-layout-btn" onClick={() => cols.autoFitAll()} title="Size every column to fit its content">
          Fit columns
        </button>
        <button
          type="button"
          className="col-layout-btn"
          onClick={() => cols.resetWidths()}
          disabled={!cols.isCustomized}
          title={cols.isCustomized ? 'Restore the default column widths' : 'Column widths are already at their defaults'}
        >
          Reset widths
        </button>
        <button type="button" className="col-layout-btn" onClick={() => setFullScreen(true)} title="Expand the table">
          <ExpandIcon size={13} /> Full screen
        </button>
      </div>

      {loading ? (
        <div className="page-loader"><span className="spinner" /> Loading orders…</div>
      ) : fullScreen ? (
        <div className="table-fullscreen-overlay" onClick={e => { if (e.target === e.currentTarget) setFullScreen(false) }}>
          <div className="table-fullscreen-panel">
            <div className="table-fullscreen-header">
              <h3>{title}<span style={{ color: 'var(--text-muted)', fontWeight: 500 }}> · {orders.length} shown</span></h3>
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
    </div>
  )
}
