import React, { useState } from 'react'
import AppLayout from '../layouts/AppLayout'
import { useAuth } from '../contexts/AuthContext'
import {
  SummaryIcon,
  CounterIcon,
  InventoryIcon,
  TaxIcon,
  AlertIcon,
  CashIcon,
  BillsIcon,
  DownloadIcon,
  ChevronRightIcon
} from '../components/Icons'

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
  const [navExpanded, setNavExpanded] = useState(false)
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
    <AppLayout title="Tax & Profit Books">
      <div className="slide-up">

        {alert && (
          <div className={`alert alert-${alert.type} mb-4`} style={{ alignItems: 'center' }}>
            <AlertIcon size={16} style={{ flexShrink: 0 }} />
            <span style={{ marginLeft: 4 }}>{alert.msg}</span>
            <button onClick={() => setAlert(null)} style={{ marginLeft: 'auto', background: 'none', border: 'none', color: 'inherit', cursor: 'pointer' }}>✕</button>
          </div>
        )}

        {/* Header */}
        <div className="page-header">
          <div className="page-header-left">
            <h1 className="page-title">Tax & Profit Books</h1>
            <p className="page-subtitle">Generate financial statements and tax filings for your business</p>
          </div>
        </div>

        {/* Container 1 — filters + report selector, pinned under the header. */}
        <div className="reports-controls">
          {/* Filters */}
          <div className="reports-filterbar">
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <span style={{ fontSize: '0.82rem', color: 'var(--text-secondary)', whiteSpace: 'nowrap' }}>From</span>
              <input type="date" className="form-input" style={{ width: 155 }} value={dateRange.from} onChange={e => setDate('from', e.target.value)} />
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <span style={{ fontSize: '0.82rem', color: 'var(--text-secondary)', whiteSpace: 'nowrap' }}>To</span>
              <input type="date" className="form-input" style={{ width: 155 }} value={dateRange.to} onChange={e => setDate('to', e.target.value)} />
            </div>
            <div className="divider" style={{ width: 1, height: 32, margin: 0 }} />
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
          </div>

          {/* Report selector — single row by default, manually expandable to all */}
          <div className="report-nav-row">
            <div className={`report-nav ${navExpanded ? 'expanded' : ''}`}>
              {REPORTS.map(report => (
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
            <button
              className="report-nav-toggle"
              onClick={() => setNavExpanded(v => !v)}
              title={navExpanded ? 'Collapse to one row' : 'Show all reports'}
            >
              {navExpanded ? 'Collapse ▲' : 'All ▾'}
            </button>
          </div>
        </div>{/* /reports-controls (container 1) */}

        {/* Container 2 — recently used (left 25%) + report output (right 75%). */}
        <div className="reports-panel reports-workarea">
        {/* 25 / 75 working area: left = context + recently used, right = output */}
        <div className="reports-split">
          <aside className="reports-aside">
            {activeReport?.needsParty && (
              <div className="card" style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                <div style={{ fontWeight: 600, fontSize: '0.86rem', color: 'var(--text-primary)' }}>
                  {activeReport.title}
                </div>
                <div style={{ display: 'flex', gap: 6 }}>
                  {['customer', 'vendor'].map(t => (
                    <button
                      key={t}
                      className={`btn btn-sm ${partyType === t ? 'btn-primary' : 'btn-secondary'}`}
                      style={{ flex: 1, justifyContent: 'center', textTransform: 'capitalize' }}
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
                  style={{ fontSize: '0.82rem' }}
                >
                  <option value="">
                    {partiesLoading ? 'Loading…' : (parties.length ? `Select ${partyType}…` : `No ${partyType}s — pick a type above`)}
                  </option>
                  {parties.map(p => (
                    <option key={p.id} value={p.id}>{p.name}</option>
                  ))}
                </select>
                <button
                  className="btn btn-primary btn-sm w-full"
                  disabled={!partyId || generating === activeReport.id}
                  onClick={() => handleGenerate(activeReport)}
                  style={{ justifyContent: 'center' }}
                >
                  {generating === activeReport.id ? 'Generating…' : 'Generate'}
                </button>
              </div>
            )}

            <div className="card reports-recent">
              <div className="reports-recent-title">Recently used</div>
              {recent.length === 0 ? (
                <p style={{ fontSize: '0.8rem', color: 'var(--text-muted)', margin: 0 }}>
                  Generate a report and it'll show here for quick access.
                </p>
              ) : (
                <div className="reports-recent-list">
                  {recent.map(id => {
                    const r = reportById(id)
                    if (!r) return null
                    return (
                      <button
                        key={id}
                        className={`report-recent-item ${activeReport?.id === id ? 'active' : ''}`}
                        onClick={() => selectReport(r)}
                      >
                        <span className="report-chip-icon">{reportIcons[id]}</span>
                        <span>{r.title}</span>
                      </button>
                    )
                  })}
                </div>
              )}
            </div>
          </aside>

          {/* Right 75% — the table / output */}
          <section className="reports-output-col">
        {reportData === null ? (
          <div className="empty-state card">
            <div className="empty-icon"><TaxIcon size={32} /></div>
            <h3>Select a report</h3>
            <p>Pick a report above and set your date range — the results appear here.</p>
          </div>
        ) : (
          <div className="slide-up">
            <div className="flex items-center justify-between mb-4">
              <h2 style={{ fontSize: '1.05rem', fontWeight: 700, color: 'var(--text-primary)', display: 'flex', alignItems: 'center', gap: 8 }}>
                {reportIcons[activeReport?.id]}
                <span>{activeReport?.title}</span>
                <span style={{ fontSize: '0.78rem', color: 'var(--text-muted)', fontWeight: 400, marginLeft: 10 }}>
                  ({dateRange.from} to {dateRange.to})
                </span>
              </h2>
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

            {activeReport?.id === 'day-book' ? (
              <div className="card" style={{ padding: '20px 24px' }}>
                {/* Summary Cards */}
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(5, 1fr)', gap: 16, marginBottom: 24 }}>
                  <div className="stat-card" style={{ background: 'var(--bg-3)', padding: 12, borderRadius: 8, border: '1px solid var(--border)' }}>
                    <div style={{ fontSize: '0.72rem', color: 'var(--text-secondary)' }}>Total Sales</div>
                    <div style={{ fontSize: '1.1rem', fontWeight: 700, color: 'var(--text-primary)', marginTop: 4 }}>
                      {fmt(reportData.summary?.total_sales)}
                    </div>
                  </div>
                  <div className="stat-card" style={{ background: 'var(--bg-3)', padding: 12, borderRadius: 8, border: '1px solid var(--border)' }}>
                    <div style={{ fontSize: '0.72rem', color: 'var(--text-secondary)' }}>Total Purchases</div>
                    <div style={{ fontSize: '1.1rem', fontWeight: 700, color: 'var(--text-primary)', marginTop: 4 }}>
                      {fmt(reportData.summary?.total_purchases)}
                    </div>
                  </div>
                  <div className="stat-card" style={{ background: 'var(--bg-3)', padding: 12, borderRadius: 8, border: '1px solid var(--border)' }}>
                    <div style={{ fontSize: '0.72rem', color: 'var(--text-secondary)' }}>Total OPEX</div>
                    <div style={{ fontSize: '1.1rem', fontWeight: 700, color: 'var(--text-primary)', marginTop: 4 }}>
                      {fmt(reportData.summary?.total_expenses)}
                    </div>
                  </div>
                  <div className="stat-card" style={{ background: 'var(--bg-3)', padding: 12, borderRadius: 8, border: '1px solid var(--border)' }}>
                    <div style={{ fontSize: '0.72rem', color: 'var(--text-secondary)' }}>Total Receipts</div>
                    <div style={{ fontSize: '1.1rem', fontWeight: 700, color: 'var(--text-primary)', marginTop: 4 }}>
                      {fmt(reportData.summary?.total_receipts)}
                    </div>
                  </div>
                  <div className="stat-card" style={{ 
                    background: reportData.summary?.net_cash_flow >= 0 ? 'rgba(46, 125, 50, 0.05)' : 'rgba(211, 47, 47, 0.05)', 
                    padding: 12, 
                    borderRadius: 8, 
                    border: '1px solid var(--border)' 
                  }}>
                    <div style={{ fontSize: '0.72rem', color: 'var(--text-secondary)' }}>Net Cash Flow</div>
                    <div style={{ 
                      fontSize: '1.1rem', 
                      fontWeight: 700, 
                      color: reportData.summary?.net_cash_flow >= 0 ? '#2e7d32' : '#d32f2f', 
                      marginTop: 4 
                    }}>
                      {fmt(reportData.summary?.net_cash_flow)}
                    </div>
                  </div>
                </div>

                {/* Transactions List */}
                {reportData.transactions?.length === 0 ? (
                  <div style={{ textAlign: 'center', color: 'var(--text-muted)', padding: '24px 0' }}>
                    No transactions recorded for this period.
                  </div>
                ) : (
                  <div className="data-table-wrap">
                    <table className="data-table">
                      <thead>
                        <tr>
                          <th>Date</th>
                          <th>Type</th>
                          <th>Reference No</th>
                          <th>Entity / Category</th>
                          <th>Payment Mode</th>
                          <th>Status</th>
                          <th style={{ textAlign: 'right' }}>Amount</th>
                        </tr>
                      </thead>
                      <tbody>
                        {reportData.transactions.map((tx, idx) => {
                          let badgeColor = 'secondary'
                          if (tx.type === 'Sale' || tx.type === 'Receipt') badgeColor = 'success'
                          if (tx.type === 'Purchase' || tx.type === 'Expense') badgeColor = 'danger'
                          
                          return (
                            <tr key={idx}>
                              <td className="td-mono" style={{ fontSize: '0.8rem' }}>{tx.date}</td>
                              <td>
                                <span className={`badge badge-${badgeColor}`} style={{ fontSize: '0.72rem', fontWeight: 600 }}>
                                  {tx.type}
                                </span>
                              </td>
                              <td className="td-mono" style={{ fontSize: '0.8rem' }}>{tx.ref_no}</td>
                              <td>{tx.entity_name}</td>
                              <td>{tx.payment_mode}</td>
                              <td style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>{tx.status}</td>
                              <td style={{ textAlign: 'right', fontWeight: 600, color: 'var(--text-primary)' }}>
                                {fmt(tx.amount)}
                              </td>
                            </tr>
                          )
                        })}
                      </tbody>
                    </table>
                  </div>
                )}
              </div>
            ) : activeReport?.id === 'balance-sheet' ? (
              <div className="card" style={{ padding: '24px 32px' }}>
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: 32 }}>
                  {/* Assets Side */}
                  <div>
                    <h3 style={{ fontSize: '0.95rem', fontWeight: 700, color: 'var(--text-primary)', borderBottom: '2px solid var(--border)', paddingBottom: 8, marginBottom: 12 }}>
                      ASSETS
                    </h3>
                    <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                      <tbody>
                        <tr style={{ borderBottom: '1px solid var(--border)' }}>
                          <td style={{ padding: '10px 0', fontSize: '0.88rem' }}>Cash & Bank Balance</td>
                          <td style={{ padding: '10px 0', textAlign: 'right', fontWeight: 600 }}>{fmt(reportData.assets?.cash_bank)}</td>
                        </tr>
                        <tr style={{ borderBottom: '1px solid var(--border)' }}>
                          <td style={{ padding: '10px 0', fontSize: '0.88rem' }}>Accounts Receivable (Dues)</td>
                          <td style={{ padding: '10px 0', textAlign: 'right', fontWeight: 600 }}>{fmt(reportData.assets?.receivables)}</td>
                        </tr>
                        <tr style={{ borderBottom: '1px solid var(--border)' }}>
                          <td style={{ padding: '10px 0', fontSize: '0.88rem' }}>Inventory Valuation (Cost)</td>
                          <td style={{ padding: '10px 0', textAlign: 'right', fontWeight: 600 }}>{fmt(reportData.assets?.inventory_valuation)}</td>
                        </tr>
                        <tr style={{ fontWeight: 700, fontSize: '0.95rem', color: 'var(--text-primary)' }}>
                          <td style={{ padding: '14px 0' }}>TOTAL ASSETS</td>
                          <td style={{ padding: '14px 0', textAlign: 'right' }}>{fmt(reportData.assets?.total_assets)}</td>
                        </tr>
                      </tbody>
                    </table>
                  </div>

                  {/* Liabilities & Equity Side */}
                  <div>
                    <h3 style={{ fontSize: '0.95rem', fontWeight: 700, color: 'var(--text-primary)', borderBottom: '2px solid var(--border)', paddingBottom: 8, marginBottom: 12 }}>
                      LIABILITIES & EQUITY
                    </h3>
                    <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                      <tbody>
                        <tr style={{ borderBottom: '1px solid var(--border)' }}>
                          <td style={{ padding: '10px 0', fontSize: '0.88rem' }}>Accounts Payable (Vendor Dues)</td>
                          <td style={{ padding: '10px 0', textAlign: 'right', fontWeight: 600 }}>{fmt(reportData.liabilities?.payables)}</td>
                        </tr>
                        <tr style={{ borderBottom: '1px solid var(--border)', color: 'var(--text-muted)' }}>
                          <td style={{ padding: '10px 0', fontSize: '0.88rem' }}>Total Liabilities</td>
                          <td style={{ padding: '10px 0', textAlign: 'right', fontWeight: 600 }}>{fmt(reportData.liabilities?.total_liabilities)}</td>
                        </tr>
                        <tr style={{ borderBottom: '1px solid var(--border)' }}>
                          <td style={{ padding: '10px 0', fontSize: '0.88rem', color: 'var(--text-secondary)' }}>Equity / Net Worth</td>
                          <td style={{ padding: '10px 0', textAlign: 'right', fontWeight: 600, color: '#2e7d32' }}>{fmt(reportData.net_worth)}</td>
                        </tr>
                        <tr style={{ fontWeight: 700, fontSize: '0.95rem', color: 'var(--text-primary)' }}>
                          <td style={{ padding: '14px 0' }}>TOTAL LIABILITIES & EQUITY</td>
                          <td style={{ padding: '14px 0', textAlign: 'right' }}>{fmt((reportData.liabilities?.total_liabilities || 0) + (reportData.net_worth || 0))}</td>
                        </tr>
                      </tbody>
                    </table>
                  </div>
                </div>

                {/* Equity Callout */}
                <div style={{
                  marginTop: 24,
                  background: 'var(--bg-3)',
                  padding: '16px 20px',
                  borderRadius: 'var(--radius-md)',
                  border: '1px solid var(--border)',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'space-between'
                }}>
                  <div>
                    <div style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', fontWeight: 600 }}>Net Asset Equity (Net Worth)</div>
                    <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)', marginTop: 2 }}>Assets minus liabilities represents the current net worth of the business.</div>
                  </div>
                  <div style={{ fontSize: '1.4rem', fontWeight: 800, color: '#2e7d32' }}>
                    {fmt(reportData.net_worth)}
                  </div>
                </div>
              </div>
            ) : activeReport?.id === 'trial-balance' ? (
              <div className="card" style={{ padding: '20px 24px' }}>
                <div className="data-table-wrap">
                  <table className="data-table">
                    <thead>
                      <tr>
                        <th>Account</th>
                        <th>Group</th>
                        <th style={{ textAlign: 'right' }}>Debit (₹)</th>
                        <th style={{ textAlign: 'right' }}>Credit (₹)</th>
                      </tr>
                    </thead>
                    <tbody>
                      {reportData.accounts?.map((a, i) => (
                        <tr key={i}>
                          <td style={{ fontWeight: 500 }}>{a.account}</td>
                          <td style={{ color: 'var(--text-secondary)', fontSize: '0.82rem' }}>{a.group}</td>
                          <td style={{ textAlign: 'right' }}>{a.debit ? fmt(a.debit) : '—'}</td>
                          <td style={{ textAlign: 'right' }}>{a.credit ? fmt(a.credit) : '—'}</td>
                        </tr>
                      ))}
                      <tr style={{ fontWeight: 700, color: 'var(--text-primary)', borderTop: '2px solid var(--border)' }}>
                        <td>TOTAL</td>
                        <td />
                        <td style={{ textAlign: 'right' }}>{fmt(reportData.totals?.total_debit)}</td>
                        <td style={{ textAlign: 'right' }}>{fmt(reportData.totals?.total_credit)}</td>
                      </tr>
                    </tbody>
                  </table>
                </div>
                <div style={{
                  marginTop: 16, padding: '12px 16px', borderRadius: 'var(--radius-md)',
                  display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                  background: reportData.totals?.balanced ? 'rgba(46, 125, 50, 0.08)' : 'rgba(220, 38, 38, 0.08)',
                  border: `1px solid ${reportData.totals?.balanced ? 'rgba(46, 125, 50, 0.2)' : 'rgba(220, 38, 38, 0.2)'}`,
                  color: reportData.totals?.balanced ? '#2e7d32' : 'var(--danger)',
                }}>
                  <span style={{ fontWeight: 600, fontSize: '0.85rem' }}>
                    {reportData.totals?.balanced ? '✓ Balanced — Debits equal Credits' : '⚠ Out of balance — check data'}
                  </span>
                  <span style={{ fontSize: '0.78rem', color: 'var(--text-secondary)' }}>
                    Capital / Owner's Equity: {fmt(reportData.memo?.capital_owner_equity)}
                  </span>
                </div>
              </div>
            ) : activeReport?.id === 'party-ledger' ? (
              <div className="card" style={{ padding: '20px 24px' }}>
                <div className="flex items-center justify-between mb-4" style={{ flexWrap: 'wrap', gap: 8 }}>
                  <div>
                    <div style={{ fontWeight: 700, fontSize: '0.95rem' }}>{reportData.party?.name}</div>
                    <div style={{ fontSize: '0.78rem', color: 'var(--text-muted)', textTransform: 'capitalize' }}>{reportData.party?.type} statement</div>
                  </div>
                  <div style={{ textAlign: 'right' }}>
                    <div style={{ fontSize: '0.72rem', color: 'var(--text-secondary)' }}>Closing {reportData.summary?.balance_type}</div>
                    <div style={{ fontSize: '1.2rem', fontWeight: 800, color: reportData.summary?.balance_type === 'Payable' ? 'var(--danger)' : '#2e7d32' }}>
                      {fmt(reportData.summary?.abs_closing)}
                    </div>
                  </div>
                </div>
                <div className="data-table-wrap">
                  <table className="data-table">
                    <thead>
                      <tr>
                        <th>Date</th>
                        <th>Type</th>
                        <th>Reference</th>
                        <th style={{ textAlign: 'right' }}>Debit</th>
                        <th style={{ textAlign: 'right' }}>Credit</th>
                        <th style={{ textAlign: 'right' }}>Balance</th>
                      </tr>
                    </thead>
                    <tbody>
                      <tr style={{ color: 'var(--text-muted)', fontStyle: 'italic' }}>
                        <td colSpan={5}>Opening Balance</td>
                        <td style={{ textAlign: 'right' }}>{fmt(reportData.opening_balance)}</td>
                      </tr>
                      {reportData.entries?.map((e, i) => (
                        <tr key={i}>
                          <td>{e.date}</td>
                          <td>{e.type}</td>
                          <td className="td-mono">{e.ref_no}</td>
                          <td style={{ textAlign: 'right' }}>{e.debit ? fmt(e.debit) : '—'}</td>
                          <td style={{ textAlign: 'right' }}>{e.credit ? fmt(e.credit) : '—'}</td>
                          <td style={{ textAlign: 'right', fontWeight: 600 }}>{fmt(e.balance)}</td>
                        </tr>
                      ))}
                      {(!reportData.entries || reportData.entries.length === 0) && (
                        <tr><td colSpan={6} style={{ textAlign: 'center', color: 'var(--text-muted)' }}>No transactions in this period.</td></tr>
                      )}
                      <tr style={{ fontWeight: 700, borderTop: '2px solid var(--border)' }}>
                        <td colSpan={3}>TOTAL</td>
                        <td style={{ textAlign: 'right' }}>{fmt(reportData.summary?.total_debit)}</td>
                        <td style={{ textAlign: 'right' }}>{fmt(reportData.summary?.total_credit)}</td>
                        <td style={{ textAlign: 'right' }}>{fmt(reportData.summary?.closing_balance)}</td>
                      </tr>
                    </tbody>
                  </table>
                </div>
              </div>
            ) : (activeReport?.id === 'journal' || activeReport?.id === 'audit-journal') ? (
              <div className="card" style={{ padding: '20px 24px' }}>
                {activeReport?.id === 'audit-journal' && (
                  <div style={{ fontSize: '0.78rem', color: 'var(--text-muted)', marginBottom: 12 }}>
                    🔒 Posted at transaction time · append-only audit trail
                  </div>
                )}
                <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
                  {reportData.entries?.map((e, i) => (
                    <div key={i} style={{ border: '1px solid var(--border)', borderRadius: 'var(--radius-md)', overflow: 'hidden' }}>
                      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '8px 14px', background: 'var(--bg-3)', fontSize: '0.82rem' }}>
                        <span style={{ fontWeight: 600 }}>{e.date} · {e.type}</span>
                        <span className="td-mono" style={{ color: 'var(--text-muted)' }}>{e.ref_no}</span>
                      </div>
                      <div style={{ padding: '4px 0' }}>
                        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.84rem' }}>
                          <tbody>
                            {e.lines?.map((l, j) => (
                              <tr key={j}>
                                <td style={{ padding: '4px 14px', paddingLeft: l.credit ? 36 : 14, color: l.credit ? 'var(--text-secondary)' : 'var(--text-primary)' }}>{l.account}</td>
                                <td style={{ padding: '4px 14px', textAlign: 'right', width: 130 }}>{l.debit ? fmt(l.debit) : ''}</td>
                                <td style={{ padding: '4px 14px', textAlign: 'right', width: 130 }}>{l.credit ? fmt(l.credit) : ''}</td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                      <div style={{ padding: '4px 14px', fontSize: '0.72rem', color: 'var(--text-muted)', fontStyle: 'italic', borderTop: '1px dashed var(--border)' }}>{e.narration}</div>
                    </div>
                  ))}
                </div>
                <div style={{
                  marginTop: 16, padding: '12px 16px', borderRadius: 'var(--radius-md)',
                  display: 'flex', justifyContent: 'space-between', alignItems: 'center',
                  background: reportData.totals?.balanced ? 'rgba(46, 125, 50, 0.08)' : 'rgba(220, 38, 38, 0.08)',
                  color: reportData.totals?.balanced ? '#2e7d32' : 'var(--danger)',
                  border: `1px solid ${reportData.totals?.balanced ? 'rgba(46, 125, 50, 0.2)' : 'rgba(220, 38, 38, 0.2)'}`,
                }}>
                  <span style={{ fontWeight: 600, fontSize: '0.85rem' }}>
                    {reportData.totals?.balanced ? '✓ Balanced' : '⚠ Out of balance'} · {reportData.entries?.length || 0} entries
                  </span>
                  <span style={{ fontSize: '0.82rem' }}>Dr {fmt(reportData.totals?.total_debit)} · Cr {fmt(reportData.totals?.total_credit)}</span>
                </div>
              </div>
            ) : activeReport?.id === 'general-ledger' ? (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
                {reportData.ledgers?.map((g, i) => (
                  <div key={i} className="card" style={{ padding: '16px 20px' }}>
                    <div className="flex items-center justify-between mb-2">
                      <h3 style={{ fontWeight: 700, fontSize: '0.92rem' }}>{g.account}</h3>
                      <span style={{ fontSize: '0.82rem', color: 'var(--text-secondary)' }}>
                        Closing: <strong style={{ color: 'var(--text-primary)' }}>{fmt(g.closing_balance)}</strong>
                      </span>
                    </div>
                    <div className="data-table-wrap">
                      <table className="data-table">
                        <thead>
                          <tr>
                            <th>Date</th><th>Type</th><th>Reference</th>
                            <th style={{ textAlign: 'right' }}>Debit</th>
                            <th style={{ textAlign: 'right' }}>Credit</th>
                            <th style={{ textAlign: 'right' }}>Balance</th>
                          </tr>
                        </thead>
                        <tbody>
                          {g.postings?.map((p, j) => (
                            <tr key={j}>
                              <td>{p.date}</td>
                              <td>{p.type}</td>
                              <td className="td-mono">{p.ref_no}</td>
                              <td style={{ textAlign: 'right' }}>{p.debit ? fmt(p.debit) : '—'}</td>
                              <td style={{ textAlign: 'right' }}>{p.credit ? fmt(p.credit) : '—'}</td>
                              <td style={{ textAlign: 'right', fontWeight: 600 }}>{fmt(p.balance)}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </div>
                ))}
                {(!reportData.ledgers || reportData.ledgers.length === 0) && (
                  <div className="empty-state card"><h3>No postings for this period</h3></div>
                )}
              </div>
            ) : reportData.length === 0 ? (
              <div className="empty-state card">
                <div className="empty-icon">
                  <SummaryIcon size={32} />
                </div>
                <h3>No data for this period</h3>
                <p>Try a different date range or check if there are transactions in this period.</p>
              </div>
            ) : (
              <div className="data-table-wrap">
                <table className="data-table">
                  <thead>
                    <tr>
                      {colKeys.map(k => (
                        <th key={k}>{k.replace(/_/g, ' ').toUpperCase()}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {reportData.map((row, i) => (
                      <tr key={i}>
                        {colKeys.map(k => (
                          <td key={k}>
                            {typeof row[k] === 'number' && (k.includes('amount') || k.includes('price') || k.includes('total') || k.includes('value'))
                              ? `₹${Number(row[k]).toLocaleString('en-IN', { maximumFractionDigits: 2 })}`
                              : String(row[k] ?? '—')}
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        )}
          </section>
        </div>
        </div>{/* /reports-panel */}
      </div>
    </AppLayout>
  )
}
