// ============================================================================
// Page: Reports.jsx
// Description: Financial & Operations Report Hub. Hosts and renders general P&L,
//              GST slab breakdowns (GSTR-1, GSTR-3B), and bookkeeping summaries
//              (Day Book, Trial Balance, General Ledger, Balance Sheet).
// ============================================================================
import React, { useState, useMemo, useEffect, useRef } from 'react'
import { useSearchParams } from 'react-router-dom'
import AppLayout from '../layouts/AppLayout'
import HeaderSearchSlot from '../components/common/HeaderSearchSlot'
import PageTabs from '../components/common/PageTabs'
import { useAuth } from '../contexts/AuthContext'
import {
  AlertIcon,
  BillsIcon,
  CashIcon,
  ChevronDownIcon,
  ChevronLeftIcon,
  ChevronRightIcon,
  CloseIcon,
  CounterIcon,
  DownloadIcon,
  InventoryIcon,
  SummaryIcon,
  TaxIcon,
  ExpandIcon,
  SyncIcon,
  SidebarToggleIcon,
} from '../components/Icons'
import DayBookView from '../components/reports/DayBookView'
import BalanceSheetView from '../components/reports/BalanceSheetView'
import TrialBalanceView from '../components/reports/TrialBalanceView'
import PartyLedgerView from '../components/reports/PartyLedgerView'
import JournalView from '../components/reports/JournalView'
import GeneralLedgerView from '../components/reports/GeneralLedgerView'
import RegisterView from '../components/reports/RegisterView'
import CustomSelect from '../components/common/CustomSelect'
import { reportPeriod } from '../utils/reportPeriods'
import './reports-shell.css'

export const REPORTS = [
  // ── GST & Compliance ──
  {
    id: 'gst',
    title: 'GST Report',
    description: 'GST summary with CGST, SGST, IGST breakdowns for filing.',
    endpoint: '/billing/reports/gst',
    color: 'warning',
    category: 'GST & Compliance',
  },
  {
    id: 'gstr1-b2b',
    title: 'GSTR-1 B2B',
    description: 'B2B outward supplies (sales to registered taxpayers) segmented by GSTIN and tax rate.',
    endpoint: '/billing/reports/gstr1-b2b',
    color: 'success',
    category: 'GST & Compliance',
  },
  {
    id: 'gstr1-b2cs',
    title: 'GSTR-1 B2CS',
    description: 'B2C outward supplies (sales to unregistered consumers) consolidated by POS and tax rate.',
    endpoint: '/billing/reports/gstr1-b2cs',
    color: 'success',
    category: 'GST & Compliance',
  },
  {
    id: 'gstr1-hsn',
    title: 'GSTR-1 HSN',
    description: 'HSN-wise summary of outward supplies, listing unit quantities and tax breakdowns.',
    endpoint: '/billing/reports/gstr1-hsn',
    color: 'success',
    category: 'GST & Compliance',
  },
  {
    id: 'gstr3b',
    title: 'GSTR-3B Summary',
    description: 'Monthly self-declaration summary of outward supplies, inward reverse charge, and Net ITC.',
    endpoint: '/billing/reports/gstr3b',
    color: 'info',
    category: 'GST & Compliance',
  },

  // ── Operations & Registers ──
  {
    id: 'sales-register',
    title: 'Sales Register',
    description: 'Itemized list of all sales invoices with totals and tax details.',
    endpoint: '/billing/reports/sales-register',
    color: 'success',
    category: 'Operations & Registers',
  },
  {
    id: 'purchase-register',
    title: 'Purchase Register',
    description: 'All purchase bills with supplier, items, and payment status.',
    endpoint: '/billing/reports/purchase-register',
    color: 'warning',
    category: 'Operations & Registers',
  },
  {
    id: 'day-book',
    title: 'Day Book',
    description: 'Chronological transaction registry for a specific day or date range — sales, purchases, opex, receipts.',
    endpoint: '/billing/reports/day-book',
    color: 'info',
    category: 'Operations & Registers',
  },
  {
    id: 'outstanding',
    title: 'Outstanding Ledger',
    description: 'Pending receivables from customers and payables to vendors.',
    endpoint: '/billing/reports/outstanding',
    color: 'danger',
    category: 'Operations & Registers',
  },
  {
    id: 'stock-movement',
    title: 'Stock Movement',
    description: 'Complete inventory movement history — in, out, and adjustments.',
    endpoint: '/billing/reports/stock-movement',
    color: 'info',
    category: 'Operations & Registers',
  },
  {
    id: 'shift-reconciliations',
    title: 'Shift Reconciliations',
    description: 'Register shifts — opening float, expected vs counted cash/UPI, and discrepancies.',
    endpoint: '/billing/reports/shift-reconciliations',
    color: 'danger',
    category: 'Operations & Registers',
  },

  // ── Financial Statements ──
  {
    id: 'pnl',
    title: 'P&L Statement',
    description: 'Profit & Loss overview — revenue, expenses, and net income for the period.',
    endpoint: '/billing/reports/profit-loss',
    color: 'accent',
    category: 'Financial Statements',
  },
  {
    id: 'balance-sheet',
    title: 'Balance Sheet',
    description: 'Real-time statement of assets (cash, receivables, stock) vs. liabilities (payables) and Net Worth.',
    endpoint: '/billing/reports/balance-sheet',
    color: 'accent',
    category: 'Financial Statements',
  },
  {
    id: 'trial-balance',
    title: 'Trial Balance',
    description: 'Every ledger account on its Dr/Cr side, with a Capital plug — books-balance check that Debits = Credits.',
    endpoint: '/billing/reports/trial-balance',
    color: 'accent',
    category: 'Financial Statements',
  },

  // ── Books & Ledgers ──
  {
    id: 'party-ledger',
    title: 'Party Ledger',
    description: 'A single customer or vendor’s running account statement with running balance.',
    endpoint: '/billing/reports/party-ledger',
    color: 'info',
    needsParty: true,
    category: 'Books & Ledgers',
  },
  {
    id: 'journal',
    title: 'General Journal',
    description: 'Every transaction as balanced double-entry Dr/Cr postings — sales, purchases, returns & expenses.',
    endpoint: '/billing/reports/journal',
    color: 'accent',
    category: 'Books & Ledgers',
  },
  {
    id: 'general-ledger',
    title: 'General Ledger',
    description: 'Journal postings regrouped per account (Cash, Sales, GST, parties…) with a running balance.',
    endpoint: '/billing/reports/general-ledger',
    color: 'accent',
    category: 'Books & Ledgers',
  },
  {
    id: 'audit-journal',
    title: 'Audit Journal',
    description: 'The POSTED journal — append-only, tamper-evident audit trail.',
    endpoint: '/billing/reports/audit-journal',
    color: 'accent',
    category: 'Books & Ledgers',
  },
]

const REPORT_CATEGORIES = [
  {
    title: 'GST & Compliance',
    ids: ['gst', 'gstr1-b2b', 'gstr1-b2cs', 'gstr1-hsn', 'gstr3b'],
  },
  {
    title: 'Operations & Registers',
    ids: ['sales-register', 'purchase-register', 'day-book', 'outstanding', 'stock-movement', 'shift-reconciliations'],
  },
  {
    title: 'Financial Statements',
    ids: ['pnl', 'balance-sheet', 'trial-balance'],
  },
  {
    title: 'Books & Ledgers',
    ids: ['party-ledger', 'journal', 'general-ledger', 'audit-journal'],
  },
]

const REPORTS_BY_ID = Object.fromEntries(REPORTS.map(r => [r.id, r]))

const reportIcons = {
  pnl: <SummaryIcon size={16} />,
  gst: <TaxIcon size={16} />,
  'gstr1-b2b': <TaxIcon size={16} />,
  'gstr1-b2cs': <TaxIcon size={16} />,
  'gstr1-hsn': <TaxIcon size={16} />,
  gstr3b: <TaxIcon size={16} />,
  'stock-movement': <InventoryIcon size={16} />,
  'sales-register': <CounterIcon size={16} />,
  'purchase-register': <BillsIcon size={16} />,
  outstanding: <CashIcon size={16} />,
  'day-book': <CounterIcon size={16} />,
  'shift-reconciliations': <CashIcon size={16} />,
  'balance-sheet': <SummaryIcon size={16} />,
  'trial-balance': <SummaryIcon size={16} />,
  'party-ledger': <CashIcon size={16} />,
  journal: <BillsIcon size={16} />,
  'general-ledger': <SummaryIcon size={16} />,
  'audit-journal': <BillsIcon size={16} />,
}

const getThisMonth = () => reportPeriod('month')
const getLastMonth = () => reportPeriod('lastMonth')
const getThisQuarter = () => reportPeriod('quarter')
const getThisFY = () => reportPeriod('financialYear')
const getPreviousFY = () => reportPeriod('previousFinancialYear')

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

function ReportPlaceholder({ report, onGenerate, generating }) {
  return (
    <div className="empty-state card" style={{ margin: 'auto', maxWidth: 440, padding: 32, textAlign: 'center' }}>
      <div className="empty-icon" style={{ display: 'inline-flex', marginBottom: 12 }}><TaxIcon size={32} /></div>
      <h3 style={{ fontSize: '1.1rem', fontWeight: 700, color: 'var(--text-primary)', marginBottom: 6 }}>
        {report ? `Run ${report.title}` : 'Select a report'}
      </h3>
      <p style={{ fontSize: '0.84rem', color: 'var(--text-muted)', lineHeight: 1.5, margin: 0 }}>
        {report
          ? 'Generate the report to see detailed metrics and ledger records for the selected period.'
          : 'Pick a report from the directory on the left and set your date range to begin.'}
      </p>
      {report && (
        <button
          type="button"
          className="btn btn-primary"
          style={{ marginTop: 16, display: 'inline-flex', alignItems: 'center', gap: 6 }}
          onClick={onGenerate}
          disabled={generating}
        >
          {generating
            ? <><span className="spinner" style={{ width: 13, height: 13, borderWidth: 2 }} /> Generating…</>
            : `Generate ${report.title}`}
        </button>
      )}
    </div>
  )
}

export default function Reports() {
  const { authFetch } = useAuth()
  const [searchParams, setSearchParams] = useSearchParams()
  const reportRequestRef = useRef(0)
  const reportAbortRef = useRef(null)
  const partyRequestRef = useRef(0)
  const partyAbortRef = useRef(null)

  // Initial tab resolution: supports ?tab=gst or bare /reports
  const [activeReport, setActiveReport] = useState(() => {
    try {
      const tab = searchParams.get('tab')
      return REPORTS.find(r => r.id === tab) || null
    } catch {
      return null
    }
  })

  // Active category for mobile switcher
  const [mobileCategory, setMobileCategory] = useState(activeReport?.category || 'Operations & Registers')
  const activeCategory = mobileCategory

  const [dateRange, setDateRange] = useState(getThisMonth)
  const [isFullScreen, setIsFullScreen] = useState(false)
  const [sidebarCollapsed, setSidebarCollapsed] = useState(() => {
    try {
      return localStorage.getItem('reports_sidebar_collapsed') === 'true'
    } catch {
      return false
    }
  })

  const toggleSidebar = () => {
    setSidebarCollapsed(prev => {
      const next = !prev
      try {
        localStorage.setItem('reports_sidebar_collapsed', String(next))
      } catch {
        // ignore
      }
      return next
    })
  }

  // Vertical collapse state per head topic
  const [collapsedCategories, setCollapsedCategories] = useState(() => {
    try {
      return JSON.parse(localStorage.getItem('reports_collapsed_categories')) || {}
    } catch {
      return {}
    }
  })

  const toggleCategory = (title) => {
    setCollapsedCategories(prev => {
      const next = { ...prev, [title]: !prev[title] }
      try {
        localStorage.setItem('reports_collapsed_categories', JSON.stringify(next))
      } catch {
        // ignore
      }
      return next
    })
  }

  // Recent reports tracked on top of directory
  const [recentReportIds, setRecentReportIds] = useState(() => {
    try {
      const saved = JSON.parse(localStorage.getItem('reports_recent_ids'))
      return Array.isArray(saved) ? saved : []
    } catch {
      return []
    }
  })

  const recordRecentReport = (id) => {
    if (!id) return
    setRecentReportIds(prev => {
      const filtered = prev.filter(rId => rId !== id)
      const next = [id, ...filtered].slice(0, 4)
      try {
        localStorage.setItem('reports_recent_ids', JSON.stringify(next))
      } catch {
        // ignore
      }
      return next
    })
  }

  const recentReports = useMemo(() => {
    return recentReportIds.map(id => REPORTS_BY_ID[id]).filter(Boolean)
  }, [recentReportIds])

  const [reportData, setReportData] = useState(null)
  const [generating, setGenerating] = useState(null)
  const [alert, setAlert] = useState(null)

  // Party Ledger picker state
  const [partyType, setPartyType] = useState('customer')
  const [partyId, setPartyId] = useState('')
  const [parties, setParties] = useState([])
  const [partiesLoading, setPartiesLoading] = useState(false)

  const invalidateReport = () => {
    reportRequestRef.current += 1
    reportAbortRef.current?.abort()
    setGenerating(null)
    setReportData(null)
  }

  useEffect(() => () => {
    reportRequestRef.current += 1
    partyRequestRef.current += 1
    reportAbortRef.current?.abort()
    partyAbortRef.current?.abort()
  }, [])

  const loadParties = async (type) => {
    const request = ++partyRequestRef.current
    partyAbortRef.current?.abort()
    const controller = new AbortController()
    partyAbortRef.current = controller
    invalidateReport()
    setPartiesLoading(true)
    setPartyId('')
    setParties([])
    try {
      const res = await authFetch(`/billing/${type === 'vendor' ? 'vendors' : 'customers'}`, { signal: controller.signal })
      const data = res.ok ? await res.json() : []
      if (request !== partyRequestRef.current) return
      setParties(Array.isArray(data) ? data : (data.items || []))
    } catch {
      if (request === partyRequestRef.current) setParties([])
    } finally {
      if (request === partyRequestRef.current) setPartiesLoading(false)
    }
  }

  // Query changes from search/deep links must also update an already mounted
  // reports page; window.history alone leaves React Router out of sync.
  useEffect(() => {
    const report = REPORTS_BY_ID[searchParams.get('tab')] || null
    if (report?.id !== activeReport?.id) {
      invalidateReport()
      setActiveReport(report)
      setAlert(null)
      if (report) setMobileCategory(report.category)
    }
  }, [searchParams])

  useEffect(() => {
    if (activeReport?.needsParty) loadParties(partyType)
  }, [activeReport?.needsParty])

  // Range change drops stale report data
  const changeRange = (next) => {
    invalidateReport()
    setDateRange(next)
  }

  const setDate = (k, v) => changeRange(d => ({ ...d, [k]: v }))
  const applyQuick = (fn) => changeRange(fn())

  const setTabInUrl = (tabId) => {
    setSearchParams(previous => {
      const next = new URLSearchParams(previous)
      next.set('tab', tabId)
      return next
    }, { replace: true })
  }

  const selectReport = (report) => {
    if (!report) return
    invalidateReport()
    recordRecentReport(report.id)
    setActiveReport(report)
    setMobileCategory(report.category)
    setTabInUrl(report.id)
    if (report.needsParty) {
      setReportData(null)
    } else {
      handleGenerate(report)
    }
  }

  const handleGenerate = async (report) => {
    if (!report) return
    if (report.needsParty && !partyId) {
      setAlert({ type: 'warning', msg: 'Select a customer or vendor first.' })
      return
    }
    const request = ++reportRequestRef.current
    reportAbortRef.current?.abort()
    const controller = new AbortController()
    reportAbortRef.current = controller
    setGenerating(report.id)
    setReportData(null)
    setAlert(null)
    try {
      const params = new URLSearchParams({ from: dateRange.from, to: dateRange.to })
      if (report.needsParty) {
        params.set('party_type', partyType)
        params.set('party_id', partyId)
      }
      const PAGE_MAX = 2000
      params.set('limit', String(PAGE_MAX))
      const res = await authFetch(`${report.endpoint}?${params}`, { signal: controller.signal })
      if (request !== reportRequestRef.current) return
      if (res.ok) {
        const data = await res.json()
        if (request !== reportRequestRef.current) return
        if (['day-book', 'balance-sheet', 'trial-balance', 'party-ledger', 'journal', 'general-ledger', 'audit-journal'].includes(report.id)) {
          setReportData(data)
        } else {
          const rows = Array.isArray(data) ? data : (data.rows || data.data || data.items || [data])
          setReportData(rows)
        }

        const headerTotal = parseInt(res.headers?.get?.('X-Total-Count'), 10)
        const total = Number.isFinite(headerTotal) ? headerTotal
          : (data && typeof data.total === 'number' ? data.total : null)
        const shownRows = Array.isArray(data) ? data
          : data?.transactions || data?.rows || data?.data || data?.items || data?.entries || data?.ledgers
        const shown = Array.isArray(shownRows) ? shownRows.length : 0
        if (total != null && total > shown) {
          setAlert({ type: 'warning', msg: `Showing first ${shown} of ${total} rows. Narrow the date range to see the rest.` })
        }
      } else if (res.status === 404) {
        setAlert({ type: 'warning', msg: `${report.title} endpoint is not yet available on the server.` })
      } else {
        setAlert({ type: 'danger', msg: 'Failed to generate report.' })
      }
    } catch {
      if (request === reportRequestRef.current) setAlert({ type: 'danger', msg: 'Network error. Please check server.' })
    } finally {
      if (request === reportRequestRef.current) setGenerating(null)
    }
  }

  const triggerExport = () => {
    if (!reportData || !activeReport) return
    const id = activeReport.id
    const from = dateRange.from
    const to = dateRange.to
    if (id === 'day-book') {
      downloadCSV(reportData.transactions, `day_book_${from}_${to}.csv`)
    } else if (id === 'balance-sheet') {
      downloadCSV([
        { SECTION: 'ASSETS', ITEM: 'Cash & Bank Balance', AMOUNT: reportData.assets?.cash_bank },
        { SECTION: 'ASSETS', ITEM: 'Accounts Receivable', AMOUNT: reportData.assets?.receivables },
        { SECTION: 'ASSETS', ITEM: 'Inventory Valuation', AMOUNT: reportData.assets?.inventory_valuation },
        { SECTION: 'ASSETS', ITEM: 'TOTAL ASSETS', AMOUNT: reportData.assets?.total_assets },
        { SECTION: 'LIABILITIES', ITEM: 'Accounts Payable', AMOUNT: reportData.liabilities?.payables },
        { SECTION: 'LIABILITIES', ITEM: 'Total Liabilities', AMOUNT: reportData.liabilities?.total_liabilities },
        { SECTION: 'EQUITY', ITEM: 'Net Worth / Equity', AMOUNT: reportData.net_worth },
      ], `balance_sheet_${from}_${to}.csv`)
    } else if (id === 'trial-balance') {
      downloadCSV([
        ...reportData.accounts.map(a => ({
          ACCOUNT: a.account, GROUP: a.group, DEBIT: a.debit, CREDIT: a.credit,
        })),
        { ACCOUNT: 'TOTAL', GROUP: '', DEBIT: reportData.totals?.total_debit, CREDIT: reportData.totals?.total_credit },
      ], `trial_balance_${from}_${to}.csv`)
    } else if (id === 'party-ledger') {
      downloadCSV([
        { DATE: '', TYPE: 'Opening Balance', REF: '', DEBIT: '', CREDIT: '', BALANCE: reportData.opening_balance },
        ...reportData.entries.map(e => ({
          DATE: e.date, TYPE: e.type, REF: e.ref_no, DEBIT: e.debit, CREDIT: e.credit, BALANCE: e.balance,
        })),
        { DATE: '', TYPE: `Closing (${reportData.summary?.balance_type})`, REF: '', DEBIT: reportData.summary?.total_debit, CREDIT: reportData.summary?.total_credit, BALANCE: reportData.summary?.closing_balance },
      ], `party_ledger_${reportData.party?.name || 'statement'}_${from}_${to}.csv`)
    } else if (id === 'journal' || id === 'audit-journal') {
      downloadCSV(
        reportData.entries.flatMap(e => e.lines.map(l => ({
          DATE: e.date, TYPE: e.type, REF: e.ref_no, NARRATION: e.narration,
          ACCOUNT: l.account, DEBIT: l.debit, CREDIT: l.credit,
        }))),
        `${id}_${from}_${to}.csv`
      )
    } else if (id === 'general-ledger') {
      downloadCSV(
        reportData.ledgers.flatMap(g => g.postings.map(p => ({
          ACCOUNT: g.account, DATE: p.date, TYPE: p.type, REF: p.ref_no,
          DEBIT: p.debit, CREDIT: p.credit, BALANCE: p.balance,
        }))),
        `general_ledger_${from}_${to}.csv`
      )
    } else {
      downloadCSV(reportData, `${id}_${from}_${to}.csv`)
    }
  }

  const colKeys = reportData?.length ? Object.keys(reportData[0]) : []

  const reportGroups = useMemo(() => {
    return REPORT_CATEGORIES.map(cat => ({
      title: cat.title,
      reports: cat.ids.map(id => REPORTS_BY_ID[id]).filter(Boolean),
    })).filter(g => g.reports.length > 0)
  }, [])

  return (
    <AppLayout title="GST & Tax Reports">
      <div className="slide-up reports-shell">

        {/* Header */}
        <div className="page-header" style={{ flexShrink: 0 }}>
          <div className="page-header-left">
            <h1 className="page-title">
              <TaxIcon size={20} style={{ color: 'var(--accent)' }} /> GST &amp; Tax Reports
            </h1>
            <p className="page-subtitle">Generate financial statements, tax filings, and bookkeeping ledgers</p>
          </div>
          <div className="page-actions"><HeaderSearchSlot /></div>
        </div>

        {alert && (
          <div className={`alert alert-${alert.type} mb-3`} style={{ alignItems: 'center', flexShrink: 0 }}>
            <AlertIcon size={16} style={{ flexShrink: 0 }} />
            <span style={{ marginLeft: 4 }}>{alert.msg}</span>
            <button onClick={() => setAlert(null)} style={{ marginLeft: 'auto', background: 'none', border: 'none', color: 'inherit', cursor: 'pointer' }} aria-label="Close">
              <CloseIcon size={16} />
            </button>
          </div>
        )}

        {/* Master-Detail Split Layout */}
        <div className="card reports-panel reports-split-layout">
          {/* Mobile-only tab strip */}
          <div className="reports-mobile-tabs">
            <PageTabs
              label="Report categories"
              tabs={REPORT_CATEGORIES.map(c => ({ id: c.title, label: c.title }))}
              active={activeCategory}
              onChange={setMobileCategory}
            />
            <div style={{ marginTop: 8 }}>
              <CustomSelect
                className="form-input"
                style={{ width: '100%', height: 34, fontSize: '0.84rem' }}
                value={activeReport?.id || ''}
                onChange={e => selectReport(REPORTS_BY_ID[e.target.value])}
              >
                <option value="">Select a report…</option>
                {REPORT_CATEGORIES.find(c => c.title === activeCategory)?.ids.map(id => {
                  const r = REPORTS_BY_ID[id]
                  return <option key={id} value={id}>{r.title}</option>
                })}
              </CustomSelect>
            </div>
          </div>

          {/* Desktop & Tablet: Left Directory Sub-Sidebar */}
          <aside className={`reports-sub-sidebar${sidebarCollapsed ? ' is-collapsed' : ''}`} aria-label="Reports directory">
            <div className="reports-sub-sidebar-header">
              <span className="reports-sub-sidebar-title">Reports Directory</span>
              <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                <span className="reports-sub-sidebar-count">{REPORTS.length} reports</span>
                <button
                  type="button"
                  className="reports-sidebar-toggle-btn"
                  onClick={toggleSidebar}
                  title="Collapse Reports Directory"
                  aria-label="Collapse Reports Directory"
                  style={{
                    background: 'none',
                    border: 'none',
                    padding: '3px 5px',
                    cursor: 'pointer',
                    color: 'var(--text-muted)',
                    display: 'inline-flex',
                    alignItems: 'center',
                    borderRadius: 4,
                  }}
                >
                  <SidebarToggleIcon size={16} />
                </button>
              </div>
            </div>

            <nav className="reports-nav-groups" role="tablist" aria-label="Reports sections">
              {/* On top: Recently viewed reports */}
              {recentReports.length > 0 && (
                <div className="reports-nav-group reports-recent-group">
                  <div className="reports-nav-group-label" style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '2px 6px' }}>
                    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 5 }}>
                      <SummaryIcon size={11} style={{ opacity: 0.8 }} />
                      <span>Recent</span>
                    </span>
                    <span style={{ fontSize: '0.65rem', textTransform: 'none', color: 'var(--text-muted)' }}>{recentReports.length}</span>
                  </div>
                  <div className="reports-nav-items">
                    {recentReports.map(r => {
                      const isSelected = activeReport?.id === r.id
                      return (
                        <button
                          key={`recent-${r.id}`}
                          type="button"
                          role="tab"
                          aria-selected={isSelected}
                          className={`reports-nav-item reports-recent-item${isSelected ? ' active' : ''}`}
                          onClick={() => selectReport(r)}
                          disabled={generating === r.id}
                          title={r.description}
                        >
                          <span className="reports-nav-icon">{reportIcons[r.id]}</span>
                          <div className="reports-nav-text">
                            <span className="reports-nav-label" style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 6 }}>
                              <span>{r.title}</span>
                              {generating === r.id && (
                                <span className="spinner" style={{ width: 11, height: 11, borderWidth: 2 }} />
                              )}
                            </span>
                            <span className="reports-nav-desc">{r.category}</span>
                          </div>
                        </button>
                      )
                    })}
                  </div>
                  <div style={{ height: 1, background: 'var(--border)', margin: '8px 4px 4px' }} />
                </div>
              )}

              {/* Head Topics with Vertical Collapse */}
              {reportGroups.map(group => {
                const isGroupCollapsed = Boolean(collapsedCategories[group.title])
                return (
                  <div key={group.title} className="reports-nav-group">
                    <button
                      type="button"
                      className="reports-nav-group-header"
                      onClick={() => toggleCategory(group.title)}
                      aria-expanded={!isGroupCollapsed}
                      title={`${isGroupCollapsed ? 'Expand' : 'Collapse'} ${group.title}`}
                      style={{
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'space-between',
                        width: '100%',
                        background: 'none',
                        border: 'none',
                        padding: '4px 6px',
                        cursor: 'pointer',
                        borderRadius: 4,
                        textAlign: 'left',
                      }}
                    >
                      <span className="reports-nav-group-label" style={{ margin: 0 }}>{group.title}</span>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                        <span style={{ fontSize: '0.68rem', color: 'var(--text-muted)' }}>{group.reports.length}</span>
                        <ChevronDownIcon
                          size={12}
                          style={{
                            color: 'var(--text-muted)',
                            transform: isGroupCollapsed ? 'rotate(-90deg)' : 'rotate(0deg)',
                            transition: 'transform 0.15s ease',
                          }}
                        />
                      </div>
                    </button>

                    {!isGroupCollapsed && (
                      <div className="reports-nav-items">
                        {group.reports.map(r => {
                          const isSelected = activeReport?.id === r.id
                          return (
                            <button
                              key={r.id}
                              type="button"
                              role="tab"
                              aria-selected={isSelected}
                              className={`reports-nav-item${isSelected ? ' active' : ''}`}
                              onClick={() => selectReport(r)}
                              disabled={generating === r.id}
                              title={r.description}
                            >
                              <span className="reports-nav-icon">{reportIcons[r.id]}</span>
                              <div className="reports-nav-text">
                                <span className="reports-nav-label" style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 6 }}>
                                  <span>{r.title}</span>
                                  {generating === r.id && (
                                    <span className="spinner" style={{ width: 11, height: 11, borderWidth: 2 }} />
                                  )}
                                </span>
                                <span className="reports-nav-desc">{r.description}</span>
                              </div>
                            </button>
                          )
                        })}
                      </div>
                    )}
                  </div>
                )
              })}
            </nav>
          </aside>

          {/* Right: Working Canvas */}
          <main className="reports-canvas">
            {/* Sticky Canvas Toolbar */}
            <div className="reports-canvas-toolbar">
              <div style={{ display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
                {sidebarCollapsed && (
                  <button
                    type="button"
                    className="btn btn-secondary btn-sm reports-sidebar-toggle-btn"
                    onClick={toggleSidebar}
                    title="Expand Reports Directory"
                    aria-label="Expand Reports Directory"
                    style={{ height: 32, padding: '0 8px', display: 'inline-flex', alignItems: 'center', gap: 5, fontSize: '0.78rem' }}
                  >
                    <SidebarToggleIcon size={15} />
                    <span>Reports</span>
                  </button>
                )}
                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <span style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', fontWeight: 600 }}>From</span>
                  <input
                    aria-label="From date"
                    type="date"
                    className="form-input"
                    style={{ width: 140, height: 32, fontSize: '0.8rem', padding: '0 8px' }}
                    value={dateRange.from}
                    onChange={e => setDate('from', e.target.value)}
                  />
                </div>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <span style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', fontWeight: 600 }}>To</span>
                  <input
                    aria-label="To date"
                    type="date"
                    className="form-input"
                    style={{ width: 140, height: 32, fontSize: '0.8rem', padding: '0 8px' }}
                    value={dateRange.to}
                    onChange={e => setDate('to', e.target.value)}
                  />
                </div>

                <div style={{ width: 1, height: 22, background: 'var(--border)', margin: '0 4px' }} />

                <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
                  {[
                    { label: 'Today', fn: () => reportPeriod('today') },
                    { label: 'This Month', fn: getThisMonth },
                    { label: 'Last Month', fn: getLastMonth },
                    { label: 'This Quarter', fn: getThisQuarter },
                    { label: 'This FY', fn: getThisFY },
                    { label: 'Previous FY', fn: getPreviousFY },
                  ].map(({ label, fn }) => (
                    <button
                      key={label}
                      type="button"
                      className="btn btn-secondary btn-sm"
                      style={{ height: 32, padding: '0 9px', fontSize: '0.75rem' }}
                      onClick={() => applyQuick(fn)}
                    >
                      {label}
                    </button>
                  ))}
                </div>

                {activeReport?.needsParty && (
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
                    <div style={{ width: 1, height: 22, background: 'var(--border)', margin: '0 4px' }} />
                    <div style={{ display: 'flex', gap: 4 }}>
                      {['customer', 'vendor'].map(t => (
                        <button
                          key={t}
                          type="button"
                          className={`btn btn-xs ${partyType === t ? 'btn-primary' : 'btn-secondary'}`}
                          style={{ textTransform: 'capitalize', padding: '2px 8px', fontSize: '0.72rem', height: 30 }}
                          onClick={() => { setPartyType(t); loadParties(t) }}
                        >
                          {t}
                        </button>
                      ))}
                    </div>
                    <CustomSelect
                      className="form-input"
                      value={partyId}
                      onChange={e => { invalidateReport(); setPartyId(e.target.value) }}
                      style={{ fontSize: '0.8rem', height: 32, width: 160 }}
                    >
                      <option value="">
                        {partiesLoading ? 'Loading…' : (parties.length ? `Select ${partyType}…` : `No ${partyType}s`)}
                      </option>
                      {parties.map(p => (
                        <option key={p.id} value={p.id}>{p.name}</option>
                      ))}
                    </CustomSelect>
                    <button
                      type="button"
                      className="btn btn-primary btn-sm"
                      style={{ height: 32 }}
                      disabled={!partyId || generating === activeReport.id}
                      onClick={() => handleGenerate(activeReport)}
                    >
                      {generating === activeReport.id ? 'Generating…' : 'Generate'}
                    </button>
                  </div>
                )}
              </div>

              {/* Right: Actions */}
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                {reportData !== null && (
                  <>
                    <button
                      type="button"
                      className="btn btn-primary btn-sm"
                      style={{ height: 32, display: 'inline-flex', alignItems: 'center', gap: 6 }}
                      onClick={triggerExport}
                    >
                      <DownloadIcon size={14} />
                      <span>Export CSV</span>
                    </button>
                    <button
                      type="button"
                      className="btn btn-secondary btn-sm"
                      style={{ height: 32, width: 34, padding: 0, justifyContent: 'center' }}
                      onClick={() => setIsFullScreen(true)}
                      title="Full Screen View"
                    >
                      <ExpandIcon size={14} />
                    </button>
                  </>
                )}
                {activeReport && (
                  <button
                    type="button"
                    className="btn btn-secondary btn-sm"
                    style={{ height: 32, display: 'inline-flex', alignItems: 'center', gap: 5 }}
                    onClick={() => handleGenerate(activeReport)}
                    disabled={generating === activeReport.id}
                    title="Re-run this report for the selected dates"
                  >
                    <SyncIcon size={13} className={generating === activeReport.id ? 'spin' : ''} />
                    <span>{generating === activeReport.id ? 'Loading…' : 'Refresh'}</span>
                  </button>
                )}
              </div>
            </div>

            {/* Scrollable Canvas Body */}
            <div className="reports-canvas-body">
              {activeReport && (
                <div className="reports-canvas-header">
                  <div>
                    <h2 className="reports-canvas-title">
                      {reportIcons[activeReport.id]}
                      <span>{activeReport.title}</span>
                      <span className="reports-canvas-period-badge">
                        {dateRange.from} to {dateRange.to}
                      </span>
                    </h2>
                    <p className="reports-canvas-desc">{activeReport.description}</p>
                  </div>
                </div>
              )}

              {/* Data View or Placeholder */}
              {reportData === null ? (
                <ReportPlaceholder
                  report={activeReport}
                  onGenerate={() => activeReport && handleGenerate(activeReport)}
                  generating={generating === activeReport?.id}
                />
              ) : (
                <div style={{ flex: 1, minHeight: 0, display: 'flex', flexDirection: 'column' }}>
                  {(() => {
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
            </div>
          </main>
        </div>

        {/* Fullscreen Modal View */}
        {isFullScreen && (
          <div className="table-fullscreen-overlay" onClick={e => { if (e.target === e.currentTarget) setIsFullScreen(false) }}>
            <div className="table-fullscreen-panel report-fullscreen-panel">
              <div className="table-fullscreen-header">
                <h3>{activeReport?.title || 'Report'}</h3>
                <button type="button" className="table-fullscreen-btn" onClick={() => setIsFullScreen(false)}>✕ Close</button>
              </div>
              <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden', padding: '16px 20px' }}>
                {reportData === null ? (
                  <ReportPlaceholder report={activeReport} onGenerate={() => activeReport && handleGenerate(activeReport)} generating={generating === activeReport?.id} />
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
        )}

      </div>
    </AppLayout>
  )
}
