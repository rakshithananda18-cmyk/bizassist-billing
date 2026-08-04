// ============================================================================
// InvoicesListView — all invoices with norms-aware Actions column and 25-item pagination.
// Filter bar matches Transactions tab: Search | Filters | Sort | [Customer chip] | Refresh
// ============================================================================
import React, { useEffect, useState, useCallback, useMemo } from 'react'
import { SyncIcon, SearchIcon, CopyIcon } from '../Icons'
import InvoiceActions, { invoiceActionItems } from '../invoice/InvoiceActions'
import { useDocLabels } from '../../hooks/useDocLabels'
import FilterDropdown from '../common/FilterDropdown'
import SortDropdown from '../common/SortDropdown'
import ContextMenu from '../common/ContextMenu'
import { formatISTDateTime } from '../../utils/format'

const fmt = (n) => `₹${Number(n || 0).toLocaleString('en-IN', { maximumFractionDigits: 2 })}`

function StatusTag({ status }) {
  const s = (status || '').toLowerCase()
  const color = s === 'paid' ? 'var(--success, #166534)' : s === 'partial' ? 'var(--warning, #b45309)' : s.includes('note') ? '#6d28d9' : 'var(--danger, #b4462f)'
  const bg   = s === 'paid' ? 'rgba(22,101,52,0.10)' : s === 'partial' ? 'rgba(180,83,9,0.10)' : 'rgba(180,70,47,0.10)'
  return <span style={{ padding: '2px 8px', borderRadius: 10, fontSize: '0.72rem', fontWeight: 700, color, background: bg }}>{status || '—'}</span>
}

const STATUS_OPTIONS = [
  { value: '',         label: 'All' },
  { value: 'Unpaid',  label: 'Unpaid' },
  { value: 'Partial', label: 'Partial' },
  { value: 'Paid',    label: 'Paid' },
  { value: 'Returns', label: 'Returns' },
  { value: 'Casual',  label: 'Casual' },
]

export default function InvoicesListView({
  authFetch, actions, reloadKey = 0, showStatusChips = false,
  customerFilter = null, onClearCustomerFilter = null,
}) {
  const [rows, setRows]       = useState([])
  const [loading, setLoading] = useState(true)
  const [q, setQ]             = useState('')
  const [chip, setChip]       = useState('')  // '' = All (no badge)
  const [dateFilter, setDateFilter] = useState({ from: '', to: '' })
  const [amountFilter, setAmountFilter] = useState({ min: '', max: '' })
  const [sortConfig, setSortConfig] = useState({ key: 'invoice_date', direction: 'desc' })
  const [ctxMenu, setCtxMenu] = useState(null)  // { x, y, items } for right-click
  const label = useDocLabels()

  // ── Pagination State (25 items per page) ──────────────────────────
  const PAGE_SIZE = 25
  const [currentPage, setCurrentPage] = useState(1)

  const load = useCallback(() => {
    setLoading(true)
    authFetch('/invoices?per_page=500')
      .then(r => r.ok ? r.json() : [])
      .then(data => setRows(Array.isArray(data) ? data : (data.invoices || [])))
      .catch(() => setRows([]))
      .finally(() => setLoading(false))
  }, [authFetch])

  useEffect(() => { load() }, [load, reloadKey])

  useEffect(() => {
    setCurrentPage(1)
  }, [q, chip, dateFilter, amountFilter, customerFilter, sortConfig])

  const matchesChip = (r) => {
    const st = (r.status || '').toLowerCase()
    switch (chip) {
      case 'Unpaid':  return r.outstanding > 0 && st !== 'partial' && !st.includes('note')
      case 'Partial': return st === 'partial'
      case 'Paid':    return st === 'paid'
      case 'Returns': return (r.invoice_type || '').includes('note')
      case 'Casual':  return st.includes('casual')
      default:        return true
    }
  }

  const filtered = useMemo(() => {
    let items = [...rows]

    if (customerFilter) {
      const cf = customerFilter.toLowerCase()
      items = items.filter(r => (r.customer_name || '').toLowerCase().includes(cf))
    }

    if (showStatusChips && chip) {
      items = items.filter(matchesChip)
    }

    if (dateFilter.from) {
      items = items.filter(r => (r.invoice_date || r.created_at || '').slice(0, 10) >= dateFilter.from)
    }
    if (dateFilter.to) {
      items = items.filter(r => (r.invoice_date || r.created_at || '').slice(0, 10) <= dateFilter.to)
    }

    if (amountFilter.min !== '' && !isNaN(Number(amountFilter.min))) {
      items = items.filter(r => Number(r.total_amount || 0) >= Number(amountFilter.min))
    }
    if (amountFilter.max !== '' && !isNaN(Number(amountFilter.max))) {
      items = items.filter(r => Number(r.total_amount || 0) <= Number(amountFilter.max))
    }

    if (q.trim()) {
      const term = q.trim().toLowerCase()
      items = items.filter(r =>
        (r.invoice_no || '').toLowerCase().includes(term) ||
        (r.customer_name || '').toLowerCase().includes(term)
      )
    }

    const { key, direction } = sortConfig
    const mult = direction === 'asc' ? 1 : -1
    items.sort((a, b) => {
      let va = a[key] ?? ''
      let vb = b[key] ?? ''
      if (typeof va === 'number' && typeof vb === 'number') return (va - vb) * mult
      return String(va).localeCompare(String(vb)) * mult
    })

    return items
  }, [rows, customerFilter, showStatusChips, chip, dateFilter, amountFilter, q, sortConfig])

  const totalPages = Math.ceil(filtered.length / PAGE_SIZE) || 1
  const paginatedRows = useMemo(() => {
    const start = (currentPage - 1) * PAGE_SIZE
    return filtered.slice(start, start + PAGE_SIZE)
  }, [filtered, currentPage])

  if (loading) return <div style={{ padding: 20, color: 'var(--text-muted)', fontSize: '0.85rem' }}>Loading invoices…</div>

  return (
    <div>
      {/* Filter bar — matches Transactions */}
      <div className="page-subbar" style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
        <div className="search-bar" style={{ margin: 0, height: 34, boxSizing: 'border-box', display: 'flex', alignItems: 'center', flex: '1 1 200px', maxWidth: 320 }}>
          <span style={{ color: 'var(--text-muted)', display: 'flex', alignItems: 'center' }}><SearchIcon size={16} /></span>
          <input
            value={q}
            onChange={e => setQ(e.target.value)}
            placeholder={customerFilter ? 'Search by invoice #…' : 'Search invoice # or customer…'}
            style={{ fontSize: '0.82rem' }}
          />
        </div>

        <FilterDropdown
          filters={[
            ...(showStatusChips ? [{
              key: 'status',
              label: 'Status',
              type: 'chips',
              value: chip,
              onChange: setChip,
              options: STATUS_OPTIONS,
            }] : []),
            {
              key: 'date',
              label: 'Date Range',
              type: 'daterange',
              value: dateFilter,
              onChange: setDateFilter,
            },
            {
              key: 'amount',
              label: 'Total Amount Range',
              type: 'amountrange',
              value: amountFilter,
              onChange: setAmountFilter,
            },
          ]}
        />

        <SortDropdown
          fields={[
            { value: 'invoice_date',  label: 'Date' },
            { value: 'invoice_no',    label: 'Invoice #' },
            { value: 'customer_name', label: 'Customer' },
            { value: 'total_amount',  label: 'Total' },
            { value: 'outstanding',   label: 'Outstanding' },
            { value: 'status',        label: 'Status' },
          ]}
          sortConfig={sortConfig}
          onSortChange={setSortConfig}
        />

        {customerFilter && (
          <span style={{
            display: 'inline-flex', alignItems: 'center', gap: 6,
            padding: '4px 12px', borderRadius: 20, height: 34, boxSizing: 'border-box',
            background: 'rgba(99,102,241,0.12)', border: '1px solid rgba(99,102,241,0.45)',
            color: '#6366f1', fontSize: '0.82rem', fontWeight: 600, flexShrink: 0,
          }}>
            {customerFilter}
            {onClearCustomerFilter && (
              <button onClick={onClearCustomerFilter} title="Clear — show all invoices"
                style={{ background: 'none', border: 'none', cursor: 'pointer', color: '#6366f1', padding: 0, fontSize: '1.1rem', lineHeight: 1, display: 'flex', alignItems: 'center' }}
                aria-label="Clear customer filter">×</button>
            )}
          </span>
        )}

        <button className="btn btn-ghost btn-sm" onClick={load} title="Refresh"
          style={{ height: 34, display: 'inline-flex', alignItems: 'center', gap: 4 }}>
          <SyncIcon size={14} />
        </button>
      </div>

      <div className="data-table-wrap" style={{ overflowX: 'auto' }}>
        <table className="data-table" style={{ width: '100%', fontSize: '0.82rem' }}>
          <thead>
            <tr>
              <th style={{ whiteSpace: 'nowrap' }}>Invoice #</th>
              <th style={{ whiteSpace: 'nowrap' }}>Customer</th>
              <th style={{ whiteSpace: 'nowrap' }}>Date</th>
              <th style={{ textAlign: 'right', whiteSpace: 'nowrap' }}>Total</th>
              <th style={{ textAlign: 'right', whiteSpace: 'nowrap' }}>Outstanding</th>
              <th style={{ whiteSpace: 'nowrap' }}>Status</th>
              <th style={{ textAlign: 'right', whiteSpace: 'nowrap' }}>Actions</th>
            </tr>
          </thead>
          <tbody>
            {paginatedRows.length === 0 ? (
              <tr><td colSpan={7} style={{ textAlign: 'center', color: 'var(--text-muted)', padding: 24 }}>
                {customerFilter ? `No invoices found for "${customerFilter}".` : 'No invoices found.'}
              </td></tr>
            ) : paginatedRows.map(inv => (
              <tr key={inv.id}
                style={{ cursor: 'context-menu' }}
                onContextMenu={e => {
                  e.preventDefault()
                  setCtxMenu({ x: e.clientX, y: e.clientY, items: [
                    // Same norms-gated list the Actions column renders as buttons.
                    ...invoiceActionItems(inv, actions, null, label),
                    { divider: true },
                    { label: 'Copy Invoice No', icon: <CopyIcon size={13} />, action: () => navigator.clipboard.writeText(inv.invoice_no || '') },
                    { label: 'Copy Customer Name', icon: <CopyIcon size={13} />, action: () => navigator.clipboard.writeText(inv.customer_name || '') },
                  ]})
                }}
              >
                <td style={{ whiteSpace: 'nowrap', fontFamily: 'monospace', fontSize: '0.78rem', color: 'var(--accent-warm, #c2410c)', fontWeight: 600, cursor: 'pointer' }}
                  onClick={() => actions.view(inv.invoice_no)}>
                  {inv.invoice_no}
                </td>
                <td style={{ whiteSpace: 'nowrap', fontWeight: 600 }}>{inv.customer_name || '—'}</td>
                <td style={{ whiteSpace: 'nowrap', color: 'var(--text-muted)', fontSize: '0.78rem' }}>
                  {formatISTDateTime(inv.created_at || inv.invoice_date)}
                </td>
                <td className="td-mono" style={{ textAlign: 'right', whiteSpace: 'nowrap' }}>{fmt(inv.total_amount)}</td>
                <td className="td-mono" style={{ textAlign: 'right', whiteSpace: 'nowrap', color: inv.outstanding > 0 ? 'var(--warning, #b45309)' : 'var(--text-muted)', fontWeight: inv.outstanding > 0 ? 600 : 400 }}>
                  {fmt(inv.outstanding)}
                </td>
                <td style={{ whiteSpace: 'nowrap' }}>
                  <StatusTag status={inv.status} />
                  {(inv.paid_at || inv.payment_date) && (
                    <div style={{ fontSize: '0.7rem', color: 'var(--success)', marginTop: 2 }}>
                      Paid: {formatISTDateTime(inv.paid_at || inv.payment_date)}
                    </div>
                  )}
                </td>
                <td style={{ whiteSpace: 'nowrap' }}>
                  <InvoiceActions invoice={inv} actions={actions} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* 25-Item Pagination Controls */}
      {filtered.length > PAGE_SIZE && (
        <div className="pagination-bar" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginTop: 12, padding: '8px 12px', background: 'var(--bg-2)', border: '1px solid var(--border)', borderRadius: 'var(--radius-md)' }}>
          <span style={{ fontSize: '0.8rem', color: 'var(--text-muted)' }}>
            Showing {((currentPage - 1) * PAGE_SIZE) + 1}–{Math.min(currentPage * PAGE_SIZE, filtered.length)} of {filtered.length} invoices
          </span>
          <div style={{ display: 'flex', gap: 6 }}>
            <button
              className="btn btn-ghost btn-xs"
              disabled={currentPage <= 1}
              style={{ opacity: currentPage <= 1 ? 0.4 : 1, cursor: currentPage <= 1 ? 'not-allowed' : 'pointer' }}
              onClick={() => setCurrentPage(p => Math.max(1, p - 1))}
            >
              ← Previous 25
            </button>
            <span style={{ fontSize: '0.8rem', fontWeight: 600, display: 'flex', alignItems: 'center', padding: '0 6px' }}>
              {currentPage} / {totalPages}
            </span>
            <button
              className="btn btn-ghost btn-xs"
              disabled={currentPage >= totalPages}
              style={{ opacity: currentPage >= totalPages ? 0.4 : 1, cursor: currentPage >= totalPages ? 'not-allowed' : 'pointer' }}
              onClick={() => setCurrentPage(p => Math.min(totalPages, p + 1))}
            >
              Next 25 →
            </button>
          </div>
        </div>
      )}

      <ContextMenu menu={ctxMenu} onClose={() => setCtxMenu(null)} />
    </div>
  )
}
