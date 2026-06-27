import React, { useState } from 'react'
import AppLayout from '../layouts/AppLayout'
import { useAuth } from '../contexts/AuthContext'
import { AlertIcon, BillsIcon, CashIcon, ChevronDownIcon, ChevronRightIcon, CloseIcon, CounterIcon, DownloadIcon, InventoryIcon, SummaryIcon, TaxIcon } from '../components/Icons'
import DayBookView from '../components/reports/DayBookView'
import BalanceSheetView from '../components/reports/BalanceSheetView'
import TrialBalanceView from '../components/reports/TrialBalanceView'
import PartyLedgerView from '../components/reports/PartyLedgerView'
import JournalView from '../components/reports/JournalView'
import GeneralLedgerView from '../components/reports/GeneralLedgerView'
import RegisterView from '../components/reports/RegisterView'

const REPORTS = [
  {
    id: 'pnl',
    title: 'P&L Statement',
    description: 'Profit & Loss overview — revenue, expenses, and net income for the period.',
    endpoint: '/billing/reports/pnl',
    color: 'accent',
  },
  {
    id: 'gst',
    title: 'GST Report',
    description: 'GST summary with CGST, SGST, IGST breakdowns for filing.',
    endpoint: '/billing/reports/gst',
    color: 'warning',
  },
  {
    id: 'gstr1-b2b',
    title: 'GSTR-1 B2B',
    description: 'B2B outward supplies (sales to registered taxpayers) segmented by GSTIN and tax rate.',
    endpoint: '/billing/reports/gstr1-b2b',
    color: 'success',
  },
  {
    id: 'gstr1-b2cs',
    title: 'GSTR-1 B2CS',
    description: 'B2C outward supplies (sales to unregistered consumers) consolidated by POS and tax rate.',
    endpoint: '/billing/reports/gstr1-b2cs',
    color: 'success',
  },
  {
    id: 'gstr1-hsn',
    title: 'GSTR-1 HSN',
    description: 'HSN-wise summary of outward supplies, listing unit quantities and tax breakdowns.',
    endpoint: '/billing/reports/gstr1-hsn',
    color: 'success',
  },
  {
    id: 'gstr3b',
    title: 'GSTR-3B Summary',
    description: 'Monthly self-declaration summary of outward supplies, inward reverse charge, and Net ITC.',
    endpoint: '/billing/reports/gstr3b',
    color: 'info',
  },
  {
    id: 'stock-movement',
    title: 'Stock Movement',
    description: 'Complete inventory movement history — in, out, and adjustments.',
    endpoint: '/billing/reports/stock-movement',
    color: 'info',
  },
  {
    id: 'sales-register',
    title: 'Sales Register',
    description: 'Itemized list of all sales invoices with totals and tax details.',
    endpoint: '/billing/reports/sales-register',
    color: 'success',
  },
  {
    id: 'purchase-register',
    title: 'Purchase Register',
    description: 'All purchase bills with supplier, items, and payment status.',
    endpoint: '/billing/reports/purchase-register',
    color: 'warning',
  },
  {
    id: 'outstanding',
    title: 'Outstanding Ledger',
    description: 'Pending receivables from customers and payables to vendors.',
    endpoint: '/billing/reports/outstanding',
    color: 'danger',
  },
  {
    id: 'day-book',
    title: 'Day Book',
    description: 'Chronological transaction registry for a specific day or date range — sales, purchases, opex, receipts.',
    endpoint: '/billing/reports/day-book',
    color: 'info',
  },
  {
    id: 'balance-sheet',
    title: 'Balance Sheet',
    description: 'Real-time statement of assets (cash, receivables, stock) vs. liabilities (payables) and Net Worth.',
    endpoint: '/billing/reports/balance-sheet',
    color: 'accent',
  },
  {
    id: 'trial-balance',
    title: 'Trial Balance',
    description: 'Every ledger account on its Dr/Cr side, with a Capital plug — the books-balance check that Debits = Credits.',
    endpoint: '/billing/reports/trial-balance',
    color: 'accent',
  },
  {
    id: 'party-ledger',
    title: 'Party Ledger',
    description: 'A single customer or vendor’s running account statement — every bill, payment & return with a running balance.',
    endpoint: '/billing/reports/party-ledger',
    color: 'info',
    needsParty: true,
  },
  {
    id: 'journal',
    title: 'General Journal',
    description: 'Every transaction as balanced double-entry Dr/Cr postings — sales, purchases, returns & expenses.',
    endpoint: '/billing/reports/journal',
    color: 'accent',
  },
  {
    id: 'general-ledger',
    title: 'General Ledger',
    description: 'Journal postings regrouped per account (Cash, Sales, GST, parties…) with a running balance.',
    endpoint: '/billing/reports/general-ledger',
    color: 'accent',
  },
  {
    id: 'audit-journal',
    title: 'Audit Journal',
    description: 'The POSTED journal — written at transaction time, append-only. The permanent, tamper-evident audit trail.',
    endpoint: '/billing/reports/audit-journal',
    color: 'accent',
  },
]

// Reports grouped into clean, recommended-order categories for the selector.
// (Source of intra-group order — does NOT touch the REPORTS array above.)
const REPORT_GROUPS = [
  { label: 'Operations', ids: ['day-book', 'sales-register', 'purchase-register', 'outstanding', 'stock-movement'] },
  { label: 'GST & Compliance', ids: ['gst', 'gstr1-b2b', 'gstr1-b2cs', 'gstr1-hsn', 'gstr3b'] },
  { label: 'Financial Statements', ids: ['pnl', 'balance-sheet', 'trial-balance'] },
  { label: 'Books & Ledgers', ids: ['party-ledger', 'journal', 'general-ledger', 'audit-journal'] },
]
const REPORTS_BY_ID = Object.fromEntries(REPORTS.map(r => [r.id, r]))

const reportIcons = {
  pnl: <SummaryIcon size={18} />,
  gst: <TaxIcon size={18} />,
  'gstr1-b2b': <TaxIcon size={18} />,
  'gstr1-b2cs': <TaxIcon size={18} />,
  'gstr1-hsn': <TaxIcon size={18} />,
  gstr3b: <TaxIcon size={18} />,
  'stock-movement': <InventoryIcon size={18} />,
  'sales-register': <CounterIcon size={18} />,
  'purchase-register': <BillsIcon size={18} />,
  outstanding: <CashIcon size={18} />,
  'day-book': <CounterIcon size={18} />,
  'balance-sheet': <SummaryIcon size={18} />,
  'trial-balance': <SummaryIcon size={18} />,
  'party-ledger': <CashIcon size={18} />,
  journal: <BillsIcon size={18} />,
  'general-ledger': <SummaryIcon size={18} />,
  'audit-journal': <BillsIcon size={18} />
}

function getThisMonth() {
  const now = new Date()
  const from = new Date(now.getFullYear(), now.getMonth(), 1).toISOString().slice(0, 10)
  const to   = new Date(now.getFullYear(), now.getMonth() + 1, 0).toISOString().slice(0, 10)
  return { from, to }
}

function getLastMonth() {
  const now = new Date()
  const from = new Date(now.getFullYear(), now.getMonth() - 1, 1).toISOString().slice(0, 10)
  const to   = new Date(now.getFullYear(), now.getMonth(), 0).toISOString().slice(0, 10)
  return { from, to }
}

function getThisQuarter() {
  const now = new Date()
  const q = Math.floor(now.getMonth() / 3)
  const from = new Date(now.getFullYear(), q * 3, 1).toISOString().slice(0, 10)
  const to   = new Date(now.getFullYear(), q * 3 + 3, 0).toISOString().slice(0, 10)
  return { from, to }
}

function getThisFY() {
  const now = new Date()
  const fyStart = now.getMonth() >= 3 ? now.getFullYear() : now.getFullYear() - 1
  return {
    from: `${fyStart}-04-01`,
    to: `${fyStart + 1}-03-31`,
  }
}

function downloadCSV(data, filename) {
  if (!data?.length) return
  const headers = Object.keys(data[0]).join(',')
  const rows = data.map(row => Object.values(row).map(v => `"${String(v ?? '').replace(/"/g, '""')}"`).join(','))
  const csv = [headers, ...rows].join('\n')
  const blob = new Blob([csv], { type: 'text/csv' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.click()
  URL.revokeObjectURL(url)
}

const fmt = (val) => {
  if (val === undefined || val === null || isNaN(Number(val))) return '₹0.00'
  return `₹${Number(val).toFixed(2)}`
}

export default function Reports() {
  const { authFetch } = useAuth()

  const [dateRange, setDateRange] = useState(getThisMonth())
  const [activeReport, setActiveReport] = useState(null)
  const [isFullScreen, setIsFullScreen] = useState(false)
  const [isMenuCollapsed, setIsMenuCollapsed] = useState(false)
  const [reportData, setReportData] = useState(null)
  const [generating, setGenerating] = useState(null)
  const [alert, setAlert] = useState(null)

  // Recently-used reports (persisted) for the left rail quick-access.
  const [recent, setRecent] = useState(() => {
    try { return JSON.parse(localStorage.getItem('reports_recent') || '[]') } catch { return [] }
  })
  const reportById = (id) => REPORTS.find(r => r.id === id)
  const pushRecent = (id) => setRecent(prev => {
    const next = [id, ...prev.filter(x => x !== id)].slice(0, 6)
    try { localStorage.setItem('reports_recent', JSON.stringify(next)) } catch { /* ignore */ }
    return next
  })

  // Party Ledger picker state
  const [openGroup, setOpenGroup] = useState('Operations')
  const [partyType, setPartyType] = useState('customer')
  const [partyId, setPartyId] = useState('')
  const [parties, setParties] = useState([])
  const [partiesLoading, setPartiesLoading] = useState(false)

  const loadParties = async (type) => {
    setPartiesLoading(true)
    setPartyId('')
    try {
      const res = await authFetch(`/billing/${type === 'vendor' ? 'vendors' : 'customers'}`)
      const data = res.ok ? await res.json() : []
      setParties(Array.isArray(data) ? data : (data.items || []))
    } catch {
      setParties([])
    } finally {
      setPartiesLoading(false)
    }
  }

  const setDate = (k, v) => setDateRange(d => ({ ...d, [k]: v }))

  const applyQuick = (fn) => {
    const range = fn()
    setDateRange(range)
  }

  // Selecting a report from the nav: party reports wait for a party pick in the
  // left rail; everything else generates immediately.
  const selectReport = (report) => {
    setActiveReport(report)
    if (report.needsParty) {
      setReportData(null)
      if (!parties.length) loadParties(partyType)
    } else {
      handleGenerate(report)
    }
  }

  const handleGenerate = async (report) => {
    if (report.needsParty && !partyId) {
      setAlert({ type: 'warning', msg: 'Select a customer or vendor first.' })
      return
    }
    setGenerating(report.id)
    setReportData(null)
    setAlert(null)
    try {
      const params = new URLSearchParams({ from: dateRange.from, to: dateRange.to })
      if (report.needsParty) {
        params.set('party_type', partyType)
        params.set('party_id', partyId)
      }
      // Paginated endpoints (registers, stock ledger, day book) cap at the
      // server max; request it so we don't silently drop rows, then warn the
      // user to narrow the date range if the result is still truncated.
      const PAGE_MAX = 2000
      params.set('limit', String(PAGE_MAX))
      const res = await authFetch(`${report.endpoint}?${params}`)
      if (res.ok) {
        const data = await res.json()
        setActiveReport(report)
        pushRecent(report.id)
        setIsMenuCollapsed(true)
        if (['day-book', 'balance-sheet', 'trial-balance', 'party-ledger', 'journal', 'general-ledger', 'audit-journal'].includes(report.id)) {
          setReportData(data)
        } else {
          const rows = Array.isArray(data) ? data : (data.rows || data.data || data.items || [data])
          setReportData(rows)
        }
        // Truncation notice: total comes from X-Total-Count header (arrays) or
        // the `total` field (day-book object).
        const headerTotal = parseInt(res.headers.get('X-Total-Count'), 10)
        const total = Number.isFinite(headerTotal) ? headerTotal
          : (data && typeof data.total === 'number' ? data.total : null)
        const shown = report.id === 'day-book'
          ? (data?.transactions?.length || 0)
          : (Array.isArray(data) ? data.length : 0)
        if (total != null && total > shown) {
          setAlert({ type: 'warning', msg: `Showing first ${shown} of ${total} rows. Narrow the date range to see the rest.` })
        }
      } else if (res.status === 404) {
        setAlert({ type: 'warning', msg: `${report.title} endpoint is not yet available on the server.` })
      } else {
        setAlert({ type: 'danger', msg: 'Failed to generate report.' })
      }
    } catch {
      setAlert({ type: 'danger', msg: 'Network error. Please check server.' })
    } finally {
      setGenerating(null)
    }
  }

  const colKeys = reportData?.length ? Object.keys(reportData[0]) : []

  return (
    <AppLayout title="GST & Tax Reports">
      <div className="slide-up">

        {alert && (
          <div className={`alert alert-${alert.type} mb-4`} style={{ alignItems: 'center' }}>
            <AlertIcon size={16} style={{ flexShrink: 0 }} />
            <span style={{ marginLeft: 4 }}>{alert.msg}</span>
            <button onClick={() => setAlert(null)} style={{ marginLeft: 'auto', background: 'none', border: 'none', color: 'inherit', cursor: 'pointer' }} aria-label="Close"><CloseIcon size={16} /></button>
          </div>
        )}

        {/* Header */}
        <div className="page-header">
          <div className="page-header-left">
            <h1 className="page-title">GST & Tax Reports</h1>
            <p className="page-subtitle">Generate financial statements and tax filings for your business</p>
          </div>
        </div>

        {/* Container 1 — filters + report selector, pinned under the header. */}
        <div className="reports-controls">
          {/* Filters */}
          <div className="reports-filterbar">
            <div className="reports-filterbar-dates">
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, flex: 1 }}>
                <span style={{ fontSize: '0.82rem', color: 'var(--text-secondary)', whiteSpace: 'nowrap' }}>From</span>
                <input type="date" className="form-input" style={{ width: 155 }} value={dateRange.from} onChange={e => setDate('from', e.target.value)} />
              </div>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, flex: 1 }}>
                <span style={{ fontSize: '0.82rem', color: 'var(--text-secondary)', whiteSpace: 'nowrap' }}>To</span>
                <input type="date" className="form-input" style={{ width: 155 }} value={dateRange.to} onChange={e => setDate('to', e.target.value)} />
              </div>
            </div>
            <div className="divider filterbar-divider" style={{ width: 1, height: 32, margin: 0 }} />
            <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
              {[
                { label: 'This Month', fn: getThisMonth },
                { label: 'Last Month', fn: getLastMonth },
                { label: 'This Quarter', fn: getThisQuarter },
                { label: 'This FY', fn: getThisFY },
              ].map(({ label, fn }) => (
                <button
                  key={label}
                  className="btn btn-secondary btn-sm"
                  onClick={() => applyQuick(fn)}
                >
                  {label}
                </button>
              ))}
            </div>
            {activeReport?.needsParty && (
              <div className="reports-filterbar-party" style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
                <div className="divider filterbar-divider" style={{ width: 1, height: 32, margin: 0 }} />
                <div style={{ display: 'flex', gap: 4 }}>
                  {['customer', 'vendor'].map(t => (
                    <button
                      key={t}
                      type="button"
                      className={`btn btn-xs ${partyType === t ? 'btn-primary' : 'btn-secondary'}`}
                      style={{ textTransform: 'capitalize', padding: '2px 8px', fontSize: '0.72rem' }}
                      onClick={() => { setPartyType(t); loadParties(t) }}
                    >
                      {t}
                    </button>
                  ))}
                </div>
                <select
                  className="form-input"
                  value={partyId}
                  onChange={e => setPartyId(e.target.value)}
                  style={{ fontSize: '0.8rem', height: 32, width: 160 }}
                >
                  <option value="">
                    {partiesLoading ? 'Loading…' : (parties.length ? `Select ${partyType}…` : `No ${partyType}s`)}
                  </option>
                  {parties.map(p => (
                    <option key={p.id} value={p.id}>{p.name}</option>
                  ))}
                </select>
                <button
                  className="btn btn-primary btn-sm"
                  disabled={!partyId || generating === activeReport.id}
                  onClick={() => handleGenerate(activeReport)}
                >
                  {generating === activeReport.id ? 'Generating…' : 'Generate'}
                </button>
              </div>
            )}
          </div>

          {/* Report selector — group buttons in one row; click to expand one (others close). */}
          {!isMenuCollapsed && (
            <div className="report-nav-groups" style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
              {/* Row of group tab-buttons */}
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
                {REPORT_GROUPS.map(group => {
                  const reports = group.ids.map(id => REPORTS_BY_ID[id]).filter(Boolean)
                  if (!reports.length) return null
                  const isOpen = openGroup === group.label
                  const activeInGroup = reports.some(r => r.id === activeReport?.id)
                  return (
                    <button
                      key={group.label}
                      type="button"
                      onClick={() => setOpenGroup(o => (o === group.label ? null : group.label))}
                      aria-expanded={isOpen}
                      style={{
                        display: 'flex', alignItems: 'center', gap: 8, padding: '8px 14px',
                        borderRadius: 'var(--radius-md)', cursor: 'pointer', fontWeight: 700, fontSize: '0.8rem',
                        border: `1px solid ${isOpen ? 'var(--accent)' : 'var(--border)'}`,
                        background: isOpen ? 'var(--accent)' : 'var(--bg-2)',
                        color: isOpen ? '#fff' : 'var(--text-primary)',
                      }}
                    >
                      <span>{group.label}</span>
                      <span style={{
                        fontSize: '0.66rem', fontWeight: 600, borderRadius: 10, padding: '1px 7px',
                        color: isOpen ? '#fff' : 'var(--text-muted)',
                        background: isOpen ? 'rgba(255,255,255,0.22)' : 'var(--bg-3)',
                      }}>{reports.length}</span>
                      {activeInGroup && !isOpen && (
                        <span title="Active report in this group" style={{ width: 6, height: 6, borderRadius: '50%', background: 'var(--accent)' }} />
                      )}
                      <span style={{ display: 'inline-flex', color: isOpen ? '#fff' : 'var(--text-muted)', transition: 'transform .18s ease', transform: isOpen ? 'rotate(180deg)' : 'none' }}>
                        <ChevronDownIcon size={14} />
                      </span>
                    </button>
                  )
                })}
              </div>

              {/* Chips for the currently-open group */}
              {(() => {
                const group = REPORT_GROUPS.find(g => g.label === openGroup)
                if (!group) return null
                const reports = group.ids.map(id => REPORTS_BY_ID[id]).filter(Boolean)
                return (
                  <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
                    {reports.map(report => (
                      <button
                        key={report.id}
                        className={`report-chip ${activeReport?.id === report.id ? 'active' : ''}`}
                        disabled={generating === report.id}
                        onClick={() => selectReport(report)}
                        title={report.description}
                      >
                        <span className="report-chip-icon">{reportIcons[report.id]}</span>
                        <span>{report.title}</span>
                        {generating === report.id && (
                          <span className="spinner" style={{ width: 12, height: 12, borderWidth: 2 }} />
                        )}
                      </button>
                    ))}
                  </div>
                )
              })()}
            </div>
          )}

          {(recent.length > 0 || isMenuCollapsed) && (
            <div className="reports-recent-strip" style={{ display: 'flex', alignItems: 'center', gap: 12, borderTop: '1px solid var(--border)', paddingTop: 12, marginTop: 12, flexWrap: 'wrap', justifyContent: 'space-between' }}>
              {recent.length > 0 && (
                <div style={{ display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
                  <span style={{ fontSize: '0.72rem', fontWeight: 700, textTransform: 'uppercase', color: 'var(--text-muted)' }}>Recently Used:</span>
                  <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
                    {recent.map(id => {
                      const r = reportById(id)
                      if (!r) return null
                      return (
                        <button
                          key={id}
                          type="button"
                          className={`btn btn-xs ${activeReport?.id === id ? 'btn-primary' : 'btn-secondary'}`}
                          style={{ fontSize: '0.75rem', padding: '4px 10px', display: 'inline-flex', alignItems: 'center', gap: 4 }}
                          onClick={() => selectReport(r)}
                        >
                          <span>{reportIcons[id]}</span>
                          <span>{r.title}</span>
                        </button>
                      )
                    })}
                  </div>
                </div>
              )}
              {isMenuCollapsed && (
                <button
                  type="button"
                  className="btn btn-secondary btn-sm"
                  onClick={() => setIsMenuCollapsed(false)}
                  style={{ marginLeft: 'auto', display: 'inline-flex', alignItems: 'center', gap: 4, fontWeight: 700, padding: '4px 12px' }}
                >
                  Show All Reports ▾
                </button>
              )}
            </div>
          )}
        </div>{/* /reports-controls (container 1) */}

        {/* Container 2 — report output (100% width) */}
        {isFullScreen ? (
          <div className="table-fullscreen-overlay" onClick={e => { if (e.target === e.currentTarget) setIsFullScreen(false) }}>
            <div className="table-fullscreen-panel report-fullscreen-panel">
              <div className="table-fullscreen-header">
                <h3>{activeReport?.title || 'Report'}</h3>
                <button type="button" className="table-fullscreen-btn" onClick={() => setIsFullScreen(false)}>✕ Close</button>
              </div>
              <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden', padding: '16px 20px' }}>
                {reportData === null ? (
                  <div className="empty-state card">
                    <div className="empty-icon"><TaxIcon size={32} /></div>
                    <h3>Select a report</h3>
                    <p>Pick a report above and set your date range — the results appear here.</p>
                  </div>
                ) : (() => {
                  const View = {
                    'day-book': DayBookView, 'balance-sheet': BalanceSheetView, 'trial-balance': TrialBalanceView,
                    'party-ledger': PartyLedgerView, 'journal': JournalView, 'audit-journal': JournalView, 'general-ledger': GeneralLedgerView,
                  }[activeReport?.id]
                  return View
                    ? <View reportData={reportData} fmt={fmt} isAudit={activeReport?.id === 'audit-journal'} />
                    : <RegisterView reportData={reportData} colKeys={colKeys} />
                })()}
              </div>
            </div>
          </div>
        ) : (
          <div className="reports-panel reports-workarea">
            <section className="reports-output-col" style={{ flex: 1, width: '100%', display: 'flex', flexDirection: 'column', height: '100%' }}>
        {reportData === null ? (
          <div className="empty-state card">
            <div className="empty-icon"><TaxIcon size={32} /></div>
            <h3>Select a report</h3>
            <p>Pick a report above and set your date range — the results appear here.</p>
          </div>
        ) : (
          <div className="slide-up" style={{ display: 'flex', flexDirection: 'column', flex: 1, height: '100%', overflow: 'hidden' }}>
            <div className="flex items-center justify-between mb-4" style={{ flexShrink: 0 }}>
              <h2 style={{ fontSize: '1.05rem', fontWeight: 700, color: 'var(--text-primary)', display: 'flex', alignItems: 'center', gap: 8 }}>
                {reportIcons[activeReport?.id]}
                <span>{activeReport?.title}</span>
                <span style={{ fontSize: '0.78rem', color: 'var(--text-muted)', fontWeight: 400, marginLeft: 10 }}>
                  ({dateRange.from} to {dateRange.to})
                </span>
              </h2>
              <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                <button
                  type="button"
                  className="table-fullscreen-btn"
                  onClick={() => setIsFullScreen(true)}
                >
                  ⛶ Fullscreen
                </button>

                <button
                  className="btn btn-primary btn-sm"
                onClick={() => {
                  if (activeReport?.id === 'day-book') {
                    downloadCSV(reportData.transactions, `day_book_${dateRange.from}_${dateRange.to}.csv`)
                  } else if (activeReport?.id === 'balance-sheet') {
                    downloadCSV([
                      { SECTION: 'ASSETS', ITEM: 'Cash & Bank Balance', AMOUNT: reportData.assets?.cash_bank },
                      { SECTION: 'ASSETS', ITEM: 'Accounts Receivable', AMOUNT: reportData.assets?.receivables },
                      { SECTION: 'ASSETS', ITEM: 'Inventory Valuation', AMOUNT: reportData.assets?.inventory_valuation },
                      { SECTION: 'ASSETS', ITEM: 'TOTAL ASSETS', AMOUNT: reportData.assets?.total_assets },
                      { SECTION: 'LIABILITIES', ITEM: 'Accounts Payable', AMOUNT: reportData.liabilities?.payables },
                      { SECTION: 'LIABILITIES', ITEM: 'Total Liabilities', AMOUNT: reportData.liabilities?.total_liabilities },
                      { SECTION: 'EQUITY', ITEM: 'Net Worth / Equity', AMOUNT: reportData.net_worth }
                    ], `balance_sheet_${dateRange.from}_${dateRange.to}.csv`)
                  } else if (activeReport?.id === 'trial-balance') {
                    downloadCSV([
                      ...reportData.accounts.map(a => ({
                        ACCOUNT: a.account, GROUP: a.group, DEBIT: a.debit, CREDIT: a.credit,
                      })),
                      { ACCOUNT: 'TOTAL', GROUP: '', DEBIT: reportData.totals?.total_debit, CREDIT: reportData.totals?.total_credit },
                    ], `trial_balance_${dateRange.from}_${dateRange.to}.csv`)
                  } else if (activeReport?.id === 'party-ledger') {
                    downloadCSV([
                      { DATE: '', TYPE: 'Opening Balance', REF: '', DEBIT: '', CREDIT: '', BALANCE: reportData.opening_balance },
                      ...reportData.entries.map(e => ({
                        DATE: e.date, TYPE: e.type, REF: e.ref_no, DEBIT: e.debit, CREDIT: e.credit, BALANCE: e.balance,
                      })),
                      { DATE: '', TYPE: `Closing (${reportData.summary?.balance_type})`, REF: '', DEBIT: reportData.summary?.total_debit, CREDIT: reportData.summary?.total_credit, BALANCE: reportData.summary?.closing_balance },
                    ], `party_ledger_${reportData.party?.name}_${dateRange.from}_${dateRange.to}.csv`)
                  } else if (activeReport?.id === 'journal' || activeReport?.id === 'audit-journal') {
                    downloadCSV(
                      reportData.entries.flatMap(e => e.lines.map(l => ({
                        DATE: e.date, TYPE: e.type, REF: e.ref_no, NARRATION: e.narration,
                        ACCOUNT: l.account, DEBIT: l.debit, CREDIT: l.credit,
                      }))),
                      `${activeReport.id}_${dateRange.from}_${dateRange.to}.csv`)
                  } else if (activeReport?.id === 'general-ledger') {
                    downloadCSV(
                      reportData.ledgers.flatMap(g => g.postings.map(p => ({
                        ACCOUNT: g.account, DATE: p.date, TYPE: p.type, REF: p.ref_no,
                        DEBIT: p.debit, CREDIT: p.credit, BALANCE: p.balance,
                      }))),
                      `general_ledger_${dateRange.from}_${dateRange.to}.csv`)
                  } else {
                    downloadCSV(reportData, `${activeReport?.id}_${dateRange.from}_${dateRange.to}.csv`)
                  }
                }}
              >
                <DownloadIcon size={14} />
                <span>Export CSV</span>
              </button>
            </div>
          </div>

            {(() => {
              // Registry replaces the old 7-branch render ternary: pick the view
              // for the active report, else fall back to the generic register table.
              const View = {
                'day-book': DayBookView,
                'balance-sheet': BalanceSheetView,
                'trial-balance': TrialBalanceView,
                'party-ledger': PartyLedgerView,
                'journal': JournalView,
                'audit-journal': JournalView,
                'general-ledger': GeneralLedgerView,
              }[activeReport?.id]
              return View
                ? <View reportData={reportData} fmt={fmt} isAudit={activeReport?.id === 'audit-journal'} />
                : <RegisterView reportData={reportData} colKeys={colKeys} />
            })()}
          </div>
        )}
          </section>
        </div>
        )}
      </div>
    </AppLayout>
  )
}
