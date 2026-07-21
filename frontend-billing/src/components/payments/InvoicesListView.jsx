// ============================================================================
// InvoicesListView — all invoices with norms-aware Actions column.
// Filter bar matches Transactions tab: Search | Filters | Sort | [Customer chip] | Refresh
// ============================================================================
import React, { useEffect, useState, useCallback, useMemo } from 'react'
import { SyncIcon, SearchIcon } from '../Icons'
import InvoiceActions from '../invoice/InvoiceActions'
import FilterDropdown from '../common/FilterDropdown'
import SortDropdown from '../common/SortDropdown'
import { formatISTDateTime } from '../../utils/format'

const fmt = (n) => `₹${Number(n || 0).toLocaleString('en-IN', { maximumFractionDigits: 2 })}`

function StatusTag({ status }) {
  const s = (status || '').toLowerCase()
  const color = s === 'paid' ? '#166534' : s === 'partial' ? '#b45309' : s.includes('note') ? '#6d28d9' : '#b4462f'
  const bg   = s === 'paid' ? 'rgba(22,101,52,0.10)' : s === 'partial' ? 'rgba(180,83,9,0.10)' : 'rgba(180,70,47,0.10)'
  return <span style={{ padding: '2px 8px', borderRadius: 10, fontSize: '0.72rem', fontWeight: 700, color, background: bg }}>{status || '—'}</span>
}

// Status filter options — value '' = All (no badge on FilterDropdown)
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

  const load = useCallback(() => {
    setLoading(true)
    authFetch('/invoices?per_page=500')
      .then(r => r.ok ? r.json() : [])
      .then(data => setRows(Array.isArray(data) ? data : (data.invoices || [])))
      .catch(() => setRows([]))
      .finally(() => setLoading(false))
  }, [authFetch])

  useEffect(() => { load() }, [load, reloadKey])

  const matchesChip = (r) => {
    const st = (r.status || '').toLowerCase()
    switch (chip) {
      case 'Unpaid':  return r.outstanding > 0 && st !== 'partial' && !st.includes('note')
      case 'Partial': return st === 'partial'
      case 'Paid':    return st === 'paid'
      case 'Returns': return (r.invoice_type || '').includes('note')
      case 'Casual':  return !r.customer_id
      default:        return true
    }
  }

  const filtered = useMemo(() => {
    let items = rows.filter(r => {
      // Exact customer filter — case-insensitive, not substring
      if (customerFilter && (r.customer_name || '').toLowerCase() !== customerFilter.toLowerCase()) return false
      // Status chip
      if (showStatusChips && !matchesChip(r)) return false
      // Date range
      if (dateFilter.from && r.invoice_date && r.invoice_date < dateFilter.from) return false
      if (dateFilter.to   && r.invoice_date && r.invoice_date > dateFilter.to)   return false
      // Amount range
      const tot = parseFloat(r.total_amount ?? 0)
      if (amountFilter.min !== '' && amountFilter.min != null && tot < parseFloat(amountFilter.min)) return false
      if (amountFilter.max !== '' && amountFilter.max != null && tot > parseFloat(amountFilter.max)) return false
      // Search
      if (!q) return true
      const s = q.toLowerCase()
      if (customerFilter) return (r.invoice_no || '').toLowerCase().includes(s)
      return (r.invoice_no || '').toLowerCase().includes(s) || (r.customer_name || '').toLowerCase().includes(s)
    })

    // Sort
    if (sortConfig.key) {
      const dir = sortConfig.direction === 'asc' ? 1 : -1
      items = [...items].sort((a, b) => {
        let av = a[sortConfig.key] ?? ''
        let bv = b[sortConfig.key] ?? ''
        if (sortConfig.key === 'total_amount' || sortConfig.key === 'outstanding') {
          av = parseFloat(av) || 0
          bv = parseFloat(bv) || 0
          return (av - bv) * dir
        }
        return String(av).localeCompare(String(bv)) * dir
      })
    }
    return items
  }, [rows, customerFilter, showStatusChips, chip, dateFilter, amountFilter, q, sortConfig])

  if (loading) return <div style={{ padding: 20, color: 'var(--text-muted)', fontSize: '0.85rem' }}>Loading invoices…</div>

  return (
    <div>
      {/* ── Filter bar — matches Transactions: Search | Filters | Sort | [chip] | Refresh ── */}
      <div className="page-subbar" style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>

        {/* Search — always first */}
        <div className="search-bar" style={{ margin: 0, height: 34, boxSizing: 'border-box', display: 'flex', alignItems: 'center', flex: '1 1 200px', maxWidth: 320 }}>
          <span style={{ color: 'var(--text-muted)', display: 'flex', alignItems: 'center' }}><SearchIcon size={16} /></span>
          <input
            value={q}
            onChange={e => setQ(e.target.value)}
            placeholder={customerFilter ? 'Search by invoice #…' : 'Search invoice # or customer…'}
            style={{ fontSize: '0.82rem' }}
          />
        </div>

        {/* FilterDropdown — Status, Date range, Amount range */}
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

        {/* SortDropdown — same style as Transactions */}
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

        {/* Customer filter chip — inline pill when ?customer= is set */}
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

        {/* Refresh */}
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
            {filtered.length === 0 ? (
              <tr><td colSpan={7} style={{ textAlign: 'center', color: 'var(--text-muted)', padding: 24 }}>
                {customerFilter ? `No invoices found for "${customerFilter}".` : 'No invoices found.'}
              </td></tr>
            ) : filtered.map(inv => (
              <tr key={inv.id}>
                <td style={{ whiteSpace: 'nowrap', fontFamily: 'monospace', fontSize: '0.78rem', color: 'var(--accent-warm, #c2410c)', fontWeight: 600, cursor: 'pointer' }}
                  onClick={() => actions.view(inv.invoice_no)}>
                  {inv.invoice_no}
                </td>
                <td style={{ whiteSpace: 'nowrap', fontWeight: 600 }}>{inv.customer_name || '—'}</td>
                <td style={{ whiteSpace: 'nowrap', color: 'var(--text-muted)', fontSize: '0.78rem' }}>
                  {formatISTDateTime(inv.created_at || inv.invoice_date)}
                </td>
                <td style={{ textAlign: 'right', whiteSpace: 'nowrap' }}>{fmt(inv.total_amount)}</td>
                <td style={{ textAlign: 'right', whiteSpace: 'nowrap', color: inv.outstanding > 0 ? 'var(--warning, #b45309)' : 'var(--text-muted)', fontWeight: inv.outstanding > 0 ? 600 : 400 }}>
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
    </div>
  )
}
