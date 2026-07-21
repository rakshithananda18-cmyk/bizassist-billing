// ============================================================================
// Page: Payments.jsx
// Description: Payment Journals and Expense Tracker. Registers cash/bank inflows
//              and outflows, records general expenses, and tracks credit note returns.
// ============================================================================
import React, { useEffect, useState, useCallback, useRef } from 'react'
import { useSearchParams, useNavigate } from 'react-router-dom'
import PageShell from '../components/common/PageShell'
import WorkspaceTopBar, { WsDivider } from '../components/common/WorkspaceTopBar'
import { useAuth } from '../contexts/AuthContext'
import { BillsIcon, CashIcon, CheckIcon, CloseIcon, PhoneIcon, PlusIcon, WarehouseIcon, SearchIcon, ExpandIcon, SummaryIcon, SparkleIcon, InfoIcon, AlertIcon, ChevronDownIcon } from '../components/Icons'

import { logger } from '../utils/logger'
import CustomSelect from '../components/common/CustomSelect'
import FilterDropdown from '../components/common/FilterDropdown'
import SortDropdown from '../components/common/SortDropdown'
import { formatISTDate, formatISTDateTime } from '../utils/format'
import InvoiceViewerModal from '../components/invoice/InvoiceViewerModal'
import RecordPaymentModal from '../components/payments/RecordPaymentModal'
import SettleDuesModal from '../components/payments/SettleDuesModal'
import InvoicesListView from '../components/payments/InvoicesListView'
import LogExpenseModal from '../components/payments/LogExpenseModal'
import { buildWhatsAppLink, buildPublicInvoiceLink } from '../invoice/share'
import { usePageLifecycle } from '../hooks/usePageLifecycle'
import ContextMenu from '../components/common/ContextMenu'
import UnsavedChangesModal from '../components/common/UnsavedChangesModal'



const fmt = (n) =>
  n != null ? `₹${Number(n).toLocaleString('en-IN', { maximumFractionDigits: 2 })}` : '₹0'

const METHOD_ICON = { Cash: '', UPI: '', Bank: '', Cheque: '' }

const defaultForm = {
  type: 'received',
  invoice_ref: '',
  amount: '',
  method: 'UPI',
  reference: '',
  date: new Date().toISOString().slice(0, 10),
}

export default function Payments({ embedded = false, headerTabs = null }) {
  const { authFetch, settings, user } = useAuth()
  const isCashier = (user?.role || '').toLowerCase() === 'cashier'
  const [searchParams] = useSearchParams()
  const navigate = useNavigate()

  // ?customer= param — set by Parties.jsx when "Settle" is clicked on a contact.
  // Acts as a locked filter (shows a clearable chip); clearing navigates back to
  // /parties/payments without the param so all transactions are shown again.
  const customerFilter = searchParams.get('customer') || null

  const settingsRef = useRef(settings)
  useEffect(() => {
    settingsRef.current = settings
  }, [settings])

  const [payments, setPayments]     = useState([])
  const [expenses, setExpenses]     = useState([])
  const [pendingDues, setPendingDues] = useState([])
  const [creditNotes, setCreditNotes] = useState([])
  const [loading, setLoading]       = useState(true)
  const [activeTab, setActiveTab]   = useState('All')
  const [isFullScreen, setIsFullScreen] = useState(false)
  const [showModal, setShowModal]   = useState(false)
  const [showExpenseModal, setShowExpenseModal] = useState(false)
  const [showSettleModal, setShowSettleModal] = useState(false)
  const [invoicesReloadKey, setInvoicesReloadKey] = useState(0)
  // In-page invoice viewer (full InvoiceViewer feature set, no route change)
  const [viewingInvoiceNo, setViewingInvoiceNo] = useState(null)
  const [showStats, setShowStats] = useState(false)
  const [form, setForm]             = useState(defaultForm)
  
  const defaultExpenseForm = {
    expense_date: new Date().toISOString().slice(0, 10),
    category: 'Rent',
    expense_type: 'Indirect',
    amount: '',
    payment_mode: 'UPI',
    note: '',
  }
  const [expenseForm, setExpenseForm] = useState(defaultExpenseForm)
  const [submitting, setSubmitting] = useState(false)
  const [alert, setAlert]           = useState(null)

  // Right-click context menu
  const [ctxMenu, setCtxMenu] = useState(null)


  const load = useCallback(() => {
    setLoading(true)
    Promise.all([
      authFetch('/billing/payments').then(r => r.ok ? r.json() : []),
      authFetch('/billing/expenses').then(r => r.ok ? r.json() : []),
      authFetch('/billing/pending-invoices').then(r => r.ok ? r.json() : []),
      authFetch('/billing/credit-notes').then(r => r.ok ? r.json() : [])
    ])
      .then(([payData, expData, duesData, cnData]) => {
        setPayments(Array.isArray(payData) ? payData : [])
        setExpenses(Array.isArray(expData) ? expData : [])
        setPendingDues(Array.isArray(duesData) ? duesData : [])
        setCreditNotes(Array.isArray(cnData) ? cnData : [])
      })
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [authFetch])

  // Page lifecycle: guard form + silent refresh on tab resume
  const { blocker, isRefreshing, dirtyMessage } = usePageLifecycle({
    isDirty:      () => (showModal && form.amount !== '') || (showExpenseModal && expenseForm.amount !== ''),
    dirtyMessage: 'You have an unsaved payment entry. Leave this page?',
    onResume:     load,
  })

  useEffect(() => {
    load()
    const handleSync = (e) => {
      const currentSettings = settingsRef.current
      const isRealtimeGlobalEnabled = currentSettings?.general?.realtime_sync_global !== false
      if (!isRealtimeGlobalEnabled) return
      logger.debug('[PAYMENTS] Real-time sync event received:', e.detail)
      if (['payment', 'invoice', 'purchase'].includes(e.detail.entity) || e.detail?.type === 'sync.reconnect') {
        load()
      }
    }
    window.addEventListener('focus', load)
    window.addEventListener('sync-event', handleSync)
    return () => {
      window.removeEventListener('focus', load)
      window.removeEventListener('sync-event', handleSync)
    }
  }, [load])

  const [search, setSearch] = useState('')
  const [modeFilter, setModeFilter] = useState('')
  const [dateFilter, setDateFilter] = useState({ from: '', to: '' })
  const [amountFilter, setAmountFilter] = useState({ min: '', max: '' })
  const [customerNameFilter, setCustomerNameFilter] = useState('')
  const [groupBy, setGroupBy] = useState('')
  // settlePreset: when a Pending row is clicked, pre-fill the SettleDuesModal.
  const [settlePreset, setSettlePreset] = useState(null)
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

  const getFilteredPayments = () => {
    let baseItems = []
    
    if (activeTab === 'All') {
      const mappedPayments = payments.map(p => {
        const ts = p.created_at || p.payment_date || p.date
        return { ...p, date: ts, _sortDate: ts }
      })
      const mappedExpenses = expenses.map(e => ({
        id: `exp-${e.id}`,
        date: e.created_at || e.expense_date,
        party_name: e.category,
        type: 'expense',
        amount: e.amount,
        method: e.payment_mode,
        reference: e.note,
        _sortDate: e.created_at || e.expense_date
      }))
      const mappedDues = pendingDues.map(d => ({
        id: `due-${d.id}`,
        _rawDueId: d.id,           // keep for settle preset lookup
        _customerId: d.customer_id, // keep for SettleDuesModal preset
        date: d.created_at || d.invoice_date || d.due_date,
        invoice_number: d.invoice_id,
        party_name: d.customer,
        type: 'pending_due',
        amount: d.balance_due,
        method: '—',
        reference: `Pending Balance (Due: ${d.due_date ? formatISTDate(d.due_date) : '—'})`,
        _sortDate: d.created_at || d.invoice_date || d.due_date
      }))
      const mappedCreditNotes = creditNotes.map(cn => ({
        id: `cn-${cn.id}`,
        date: cn.created_at || cn.date,
        invoice_number: cn.invoice_id,
        party_name: cn.customer,
        type: 'credit_note',
        amount: cn.amount,
        method: '—',
        reference: cn.note ? `Credit Note: ${cn.note}` : `Credit Note for ${cn.reference_invoice || '—'}`,
        _sortDate: cn.created_at || cn.date
      }))
      baseItems = [...mappedPayments, ...mappedExpenses, ...mappedDues, ...mappedCreditNotes]
      
      // Sort by date descending by default
      if (!sortConfig.key) {
        baseItems.sort((a, b) => {
          const da = new Date(a._sortDate || 0)
          const db = new Date(b._sortDate || 0)
          return db - da
        })
      }
    } else {
      baseItems = payments.filter(p => {
        if (activeTab === 'Received' && p.type !== 'received' && p.type !== 'settlement') return false
        if (activeTab === 'Made' && p.type !== 'made') return false
        return true
      }).map(p => {
        const ts = p.created_at || p.payment_date || p.date
        return { ...p, date: ts, _sortDate: ts }
      })
    }

    let items = baseItems.filter(p => {
      // Exact customer filter from URL (?customer=)
      if (customerFilter) {
        const party = (p.party_name || p.customer_name || p.supplier_name || '').toLowerCase()
        if (party !== customerFilter.toLowerCase()) return false
      }

      // Customer name filter from the FilterDropdown combobox
      if (customerNameFilter) {
        const party = (p.party_name || p.customer_name || p.supplier_name || '').toLowerCase()
        if (party !== customerNameFilter.toLowerCase()) return false
      }

      if (modeFilter && (p.method || '').toLowerCase() !== modeFilter.toLowerCase()) return false

      // Date range filter
      if (dateFilter.from && p.date && p.date < dateFilter.from) return false
      if (dateFilter.to   && p.date && p.date > dateFilter.to)   return false

      // Amount range filter
      const amt = parseFloat(p.amount ?? 0)
      if (amountFilter.min !== '' && amountFilter.min != null && amt < parseFloat(amountFilter.min)) return false
      if (amountFilter.max !== '' && amountFilter.max != null && amt > parseFloat(amountFilter.max)) return false

      const q = search.toLowerCase()
      const party = p.party_name || p.customer_name || p.supplier_name || ''
      return !q ||
        p.invoice_number?.toLowerCase().includes(q) ||
        p.invoice_ref?.toLowerCase().includes(q) ||
        party.toLowerCase().includes(q) ||
        p.reference?.toLowerCase().includes(q)
    })

    if (sortConfig.key && sortConfig.direction) {
      items.sort((a, b) => {
        let aVal = a[sortConfig.key]
        let bVal = b[sortConfig.key]

        if (sortConfig.key === 'party_name') {
          aVal = a.party_name || a.customer_name || a.supplier_name || ''
          bVal = b.party_name || b.customer_name || b.supplier_name || ''
        } else if (sortConfig.key === 'amount') {
          aVal = parseFloat(a.amount ?? 0)
          bVal = parseFloat(b.amount ?? 0)
        } else if (sortConfig.key === 'date') {
          aVal = a.date || ''
          bVal = b.date || ''
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

  const getFilteredExpenses = () => {
    let items = expenses.filter(e => {
      if (modeFilter && (e.payment_mode || '').toLowerCase() !== modeFilter.toLowerCase()) return false

      const q = search.toLowerCase()
      return !q || 
        e.category?.toLowerCase().includes(q) || 
        e.expense_type?.toLowerCase().includes(q) || 
        e.note?.toLowerCase().includes(q)
    })

    if (sortConfig.key && sortConfig.direction) {
      items.sort((a, b) => {
        let aVal = a[sortConfig.key]
        let bVal = b[sortConfig.key]

        if (sortConfig.key === 'amount') {
          aVal = parseFloat(a.amount ?? 0)
          bVal = parseFloat(b.amount ?? 0)
        } else if (sortConfig.key === 'expense_date') {
          aVal = a.expense_date || ''
          bVal = b.expense_date || ''
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

  const getFilteredPendingDues = () => {
    let items = pendingDues.filter(d => {
      const q = search.toLowerCase()
      const party = d.customer || ''
      return !q || 
        d.invoice_id?.toLowerCase().includes(q) || 
        party.toLowerCase().includes(q)
    })
    if (sortConfig.key && sortConfig.direction) {
      items.sort((a, b) => {
        let aVal = a[sortConfig.key]
        let bVal = b[sortConfig.key]
        if (sortConfig.key === 'customer') {
          aVal = a.customer || ''
          bVal = b.customer || ''
        } else if (sortConfig.key === 'balance_due') {
          aVal = parseFloat(a.balance_due ?? 0)
          bVal = parseFloat(b.balance_due ?? 0)
        } else if (sortConfig.key === 'due_date') {
          aVal = a.due_date || ''
          bVal = b.due_date || ''
        }
        if (aVal === undefined || aVal === null) return 1
        if (bVal === undefined || bVal === null) return -1
        if (typeof aVal === 'string') {
          return sortConfig.direction === 'asc' ? aVal.localeCompare(bVal) : bVal.localeCompare(aVal)
        } else {
          return sortConfig.direction === 'asc' ? aVal - bVal : bVal - aVal
        }
      })
    }
    return items
  }

  const getFilteredCreditNotes = () => {
    let items = creditNotes.filter(cn => {
      const q = search.toLowerCase()
      const party = cn.customer || ''
      return !q || 
        cn.invoice_id?.toLowerCase().includes(q) || 
        cn.reference_invoice?.toLowerCase().includes(q) || 
        party.toLowerCase().includes(q) || 
        cn.note?.toLowerCase().includes(q)
    })
    if (sortConfig.key && sortConfig.direction) {
      items.sort((a, b) => {
        let aVal = a[sortConfig.key]
        let bVal = b[sortConfig.key]
        if (sortConfig.key === 'customer') {
          aVal = a.customer || ''
          bVal = b.customer || ''
        } else if (sortConfig.key === 'amount') {
          aVal = parseFloat(a.amount ?? 0)
          bVal = parseFloat(b.amount ?? 0)
        } else if (sortConfig.key === 'date') {
          aVal = a.date || ''
          bVal = b.date || ''
        }
        if (aVal === undefined || aVal === null) return 1
        if (bVal === undefined || bVal === null) return -1
        if (typeof aVal === 'string') {
          return sortConfig.direction === 'asc' ? aVal.localeCompare(bVal) : bVal.localeCompare(aVal)
        } else {
          return sortConfig.direction === 'asc' ? aVal - bVal : bVal - aVal
        }
      })
    }
    return items
  }

  const generateCashFlowInsights = () => {
    const insights = []
    
    // 1. UPI vs Cash Collections
    const receivedPayments = payments.filter(p => p.type === 'received')
    const totalRecv = receivedPayments.reduce((s, p) => s + (parseFloat(p.amount) || 0), 0)
    
    if (totalRecv > 0) {
      const upiRecv = receivedPayments.filter(p => p.method === 'UPI').reduce((s, p) => s + (parseFloat(p.amount) || 0), 0)
      const upiPct = Math.round((upiRecv / totalRecv) * 100)
      if (upiPct > 50) {
        insights.push({
          type: 'info',
          title: 'Digital Inflows',
          text: `UPI is your primary collections method, accounting for ${upiPct}% of total received payments.`,
        })
      }
    }
    
    // 2. Overdue Receivables Risk
    const overdueList = pendingDues.filter(d => d.status === 'Overdue')
    const totalOverdue = overdueList.reduce((s, d) => s + parseFloat(d.balance_due || 0), 0)
    if (totalOverdue > 0) {
      insights.push({
        type: 'warning',
        title: 'Outstanding Receivables',
        text: `${fmt(totalOverdue)} is currently overdue across ${overdueList.length} outstanding invoices. Consider sending reminders.`,
      })
    }
    
    // 3. Expense Breakdown
    const totalExp = expenses.reduce((s, e) => s + (parseFloat(e.amount) || 0), 0)
    if (totalExp > 0) {
      const categories = {}
      expenses.forEach(e => {
        categories[e.category] = (categories[e.category] || 0) + (parseFloat(e.amount) || 0)
      })
      let topCat = ''
      let maxAmt = 0
      Object.entries(categories).forEach(([cat, amt]) => {
        if (amt > maxAmt) {
          maxAmt = amt
          topCat = cat
        }
      })
      if (topCat) {
        const catPct = Math.round((maxAmt / totalExp) * 100)
        insights.push({
          type: 'expense',
          title: 'Overhead Focus',
          text: `Your highest expense category is "${topCat}" at ${fmt(maxAmt)} (${catPct}% of total overheads).`,
        })
      }
    }
    
    // 4. Burn Rate / Runway
    if (totalRecv > 0 && totalExp > totalRecv) {
      insights.push({
        type: 'danger',
        title: 'Cash Deficit',
        text: `Your business expenses (${fmt(totalExp)}) exceed your recorded payments received (${fmt(totalRecv)}) during this period.`,
      })
    } else if (totalRecv > 0 && totalExp > 0) {
      insights.push({
        type: 'success',
        title: 'Healthy Margin',
        text: `Operating margins are positive. General overheads eat up ${Math.round((totalExp / totalRecv) * 100)}% of sales inflows.`,
      })
    }
    
    if (insights.length === 0) {
      insights.push({
        type: 'info',
        title: 'Operational Baseline',
        text: 'Insufficient transaction history to construct advanced analytics. Record more payments and log expenses to populate insights.',
      })
    }
    
    return insights
  }

  const filtered = getFilteredPayments()
  const filteredExpenses = getFilteredExpenses()
  const filteredPendingDues = getFilteredPendingDues()
  const filteredCreditNotes = getFilteredCreditNotes()

  const totalReceived = payments.filter(p => p.type === 'received').reduce((s, p) => s + (parseFloat(p.amount) || 0), 0)
  const totalMade     = payments.filter(p => p.type === 'made').reduce((s, p) => s + (parseFloat(p.amount) || 0), 0)
  const net = totalReceived - totalMade

  const setField = (k, v) => setForm(f => ({ ...f, [k]: v }))

  const handleSubmit = async (e) => {
    e.preventDefault()
    setSubmitting(true)
    try {
      const nowIso = new Date().toISOString()
      const res = await authFetch('/billing/payments', {
        method: 'POST',
        body: JSON.stringify({
          ...form,
          amount: parseFloat(form.amount),
          created_at: nowIso,
          payment_date: nowIso,
        }),
      })
      if (res.ok) {
        setAlert({ type: 'success', msg: 'Payment recorded successfully!' })
        setShowModal(false)
        setForm(defaultForm)
        load()
        setInvoicesReloadKey(k => k + 1)
      } else {
        const err = await res.json().catch(() => ({}))
        setAlert({ type: 'danger', msg: err.detail || 'Failed to record payment.' })
      }
    } catch {
      setAlert({ type: 'danger', msg: 'Network error.' })
    } finally {
      setSubmitting(false)
    }
  }

  // Expense Handlers
  const handleExpenseSubmit = async (e) => {
    e.preventDefault()
    setSubmitting(true)
    try {
      const nowIso = new Date().toISOString()
      const res = await authFetch('/billing/expenses', {
        method: 'POST',
        body: JSON.stringify({
          ...expenseForm,
          amount: parseFloat(expenseForm.amount),
          created_at: nowIso,
          expense_date: nowIso,
        }),
      })
      if (res.ok) {
        setAlert({ type: 'success', msg: 'Expense logged successfully!' })
        setShowExpenseModal(false)
        setExpenseForm(defaultExpenseForm)
        load()
      } else {
        const err = await res.json().catch(() => ({}))
        setAlert({ type: 'danger', msg: err.detail || 'Failed to log expense.' })
      }
    } catch {
      setAlert({ type: 'danger', msg: 'Network error.' })
    } finally {
      setSubmitting(false)
    }
  }

  const handleExpenseDelete = async (id) => {
    if (!window.confirm('Are you sure you want to delete this expense record?')) return
    try {
      const res = await authFetch(`/billing/expenses/${id}`, {
        method: 'DELETE',
      })
      if (res.ok) {
        setAlert({ type: 'success', msg: 'Expense record deleted.' })
        load()
      } else {
        setAlert({ type: 'danger', msg: 'Failed to delete expense.' })
      }
    } catch {
      setAlert({ type: 'danger', msg: 'Network error.' })
    }
  }

  const setExpenseField = (k, v) => setExpenseForm(f => ({ ...f, [k]: v }))

  return (
    <PageShell embedded={embedded} title="Payments">
      <>
      <div className={`slide-up${headerTabs ? ' ws-embed' : ''}`}>


        {alert && (
          <div className={`alert alert-${alert.type} mb-4`}>
            {alert.type === 'success' ? '✅' : '❌'} {alert.msg}
            <button onClick={() => setAlert(null)} style={{ marginLeft: 'auto', background: 'none', border: 'none', color: 'inherit', cursor: 'pointer' }} aria-label="Close"><CloseIcon size={16} /></button>
          </div>
        )}

        {/* Embedded (Khata): the SAME 48px workspace bar as Godown's tabs —
            workspace tabs · divider · group switch · actions · window controls. */}
        {headerTabs && (
          <WorkspaceTopBar
            windowControls={false}
            actions={
              <>
                <button
                  onClick={() => setShowStats(!showStats)}
                  className={`ws-tab ${showStats ? 'active' : ''}`}
                  style={{ padding: '6px 10px' }}
                >
                  <SummaryIcon size={12} /> {showStats ? 'Hide Summary' : 'Show Summary'}
                </button>
                {activeTab === 'Expenses' ? (
                  <button className="btn btn-primary btn-sm" style={{ display: 'inline-flex', alignItems: 'center', gap: 5 }} onClick={() => { setExpenseForm(defaultExpenseForm); setShowExpenseModal(true) }}>
                    <PlusIcon size={13} /> Log Expense
                  </button>
                ) : (
                  <>
                    {/* Settle Dues — only shown when there are pending dues in the current filtered view */}
                    {!isCashier && getFilteredPayments().some(p => p.type === 'pending_due') && (
                      <button className="btn btn-secondary btn-sm" style={{ display: 'inline-flex', alignItems: 'center', gap: 5 }} onClick={() => {
                        // Arrived via "Settle" on a contact (?customer=Name): carry
                        // that customer into the modal so it's pre-selected + locked
                        // instead of forcing a re-pick from the dropdown.
                        setSettlePreset(customerFilter ? { customerName: customerFilter } : null)
                        setShowSettleModal(true)
                      }}>
                        <CheckIcon size={13} /> Settle Dues
                      </button>
                    )}
                    <button className="btn btn-primary btn-sm" style={{ display: 'inline-flex', alignItems: 'center', gap: 5 }} onClick={() => { setForm(defaultForm); setShowModal(true) }}>
                      <PlusIcon size={13} /> Record Payment
                    </button>
                  </>
                )}
              </>
            }
          >
            {headerTabs}
            <WsDivider />
            {[
              { key: 'general', label: 'General Operations', firstTab: 'All' },
              { key: 'expenses', label: 'Expenses & Purchases', firstTab: 'Made' },
            ].map(g => {
              const active = (g.key === 'expenses') === ['Made', 'Expenses'].includes(activeTab)
              return (
                <button
                  key={g.key}
                  className={`ws-tab ${active ? 'active' : ''}`}
                  onClick={() => { if (!active) setActiveTab(g.firstTab) }}
                >
                  {g.label}
                </button>
              )
            })}
          </WorkspaceTopBar>
        )}

        {/* Standalone header (legacy /payments route only) */}
        {!headerTabs && (
        <div className="page-header">
          <div className="page-header-left">
            <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
              <h1 className="page-title">{activeTab === 'Expenses' ? 'Expenses' : 'Payments'}</h1>
              <button
                onClick={() => setShowStats(!showStats)}
                style={{
                  display: 'inline-flex',
                  alignItems: 'center',
                  gap: 5,
                  fontSize: '0.72rem',
                  fontWeight: 700,
                  color: showStats ? 'var(--accent)' : 'var(--text-secondary)',
                  padding: '4px 10px',
                  borderRadius: '16px',
                  background: 'var(--bg-3)',
                  border: '1px solid var(--border)',
                  cursor: 'pointer',
                  transition: 'all 0.15s ease',
                }}
              >
                <SummaryIcon size={12} />
                <span>{showStats ? 'Hide Summary' : 'Show Summary'}</span>
                <span style={{
                  display: 'inline-flex',
                  transition: 'transform 0.18s ease',
                  transform: showStats ? 'rotate(180deg)' : 'none'
                }}>
                  <ChevronDownIcon size={12} />
                </span>
              </button>
            </div>
            <p className="page-subtitle">
              {activeTab === 'Expenses'
                ? 'Track operational, rent, utility, and other business expenses'
                : 'Track all money received and payments made'}
            </p>
          </div>
          <div className="page-actions" style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
            {/* Group switch — lives in the header; sub-filters sit next to search */}
            <div style={{
              background: 'var(--bg-3)', border: '1px solid var(--border)',
              borderRadius: 'var(--radius-lg)', padding: 3,
              display: 'flex', gap: 3, alignItems: 'center',
            }}>
              {[
                { key: 'general', label: 'General Operations', firstTab: 'All' },
                { key: 'expenses', label: 'Expenses & Purchases', firstTab: 'Made' },
              ].map(g => {
                const active = (g.key === 'expenses') === ['Made', 'Expenses'].includes(activeTab)
                return (
                  <button
                    key={g.key}
                    className={`tab${active ? ' active' : ''}`}
                    onClick={() => { if (!active) setActiveTab(g.firstTab) }}
                    style={{ margin: 0, padding: '5px 12px', fontSize: '0.8rem', fontWeight: 600 }}
                  >
                    {g.label}
                  </button>
                )
              })}
            </div>
            {activeTab === 'Expenses' ? (
              <button className="btn btn-primary" onClick={() => { setExpenseForm(defaultExpenseForm); setShowExpenseModal(true) }}>
                <PlusIcon size={14} /> Log Expense
              </button>
            ) : (
              <button className="btn btn-primary" onClick={() => { setForm(defaultForm); setShowModal(true) }}>
                <PlusIcon size={14} /> Record Payment
              </button>
            )}
          </div>
        </div>
        )}

        {/* Cash Flow Summary Cards */}
        <div style={{
          maxHeight: showStats ? '500px' : '0px',
          overflow: 'hidden',
          transition: 'max-height 0.3s cubic-bezier(0.4, 0, 0.2, 1), opacity 0.2s ease, margin-bottom 0.3s ease',
          opacity: showStats ? 1 : 0,
          marginBottom: showStats ? 20 : 0,
        }}>
          <div style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))',
            gap: 16,
            paddingBottom: 4
          }}>
            {/* Card 1: Received */}
            <div style={{
              background: 'var(--bg-1)',
              border: '1px solid var(--border)',
              borderRadius: 'var(--radius-lg, 12px)',
              padding: '16px 20px',
              display: 'flex',
              flexDirection: 'column',
              gap: 4,
              boxShadow: 'var(--shadow-sm)'
            }}>
              <div style={{ fontSize: '0.72rem', textTransform: 'uppercase', letterSpacing: '0.6px', color: 'var(--text-muted)', fontWeight: 700 }}>Total Received</div>
              <div style={{ fontSize: '1.4rem', fontWeight: 800, color: 'var(--success)', marginTop: 2 }}>{fmt(totalReceived)}</div>
            </div>

            {/* Card 2: Spent */}
            <div style={{
              background: 'var(--bg-1)',
              border: '1px solid var(--border)',
              borderRadius: 'var(--radius-lg, 12px)',
              padding: '16px 20px',
              display: 'flex',
              flexDirection: 'column',
              gap: 4,
              boxShadow: 'var(--shadow-sm)'
            }}>
              <div style={{ fontSize: '0.72rem', textTransform: 'uppercase', letterSpacing: '0.6px', color: 'var(--text-muted)', fontWeight: 700 }}>Total Outflow</div>
              <div style={{ fontSize: '1.4rem', fontWeight: 800, color: 'var(--danger)', marginTop: 2 }}>{fmt(totalMade)}</div>
            </div>

            {/* Card 3: Net Balance */}
            <div style={{
              background: 'var(--bg-1)',
              border: '1px solid var(--border)',
              borderRadius: 'var(--radius-lg, 12px)',
              padding: '16px 20px',
              display: 'flex',
              justifyContent: 'space-between',
              alignItems: 'center',
              boxShadow: 'var(--shadow-sm)'
            }}>
              <div>
                <div style={{ fontSize: '0.72rem', textTransform: 'uppercase', letterSpacing: '0.6px', color: 'var(--text-muted)', fontWeight: 700, marginBottom: 2 }}>Net Balance</div>
                <div style={{ fontSize: '1.4rem', fontWeight: 800, color: net >= 0 ? 'var(--success)' : 'var(--danger)' }}>
                  {net >= 0 ? '+' : ''}{fmt(net)}
                </div>
              </div>
              <div style={{
                textTransform: 'uppercase', fontSize: '0.65rem', fontWeight: 700,
                padding: '4px 10px', borderRadius: '99px',
                background: net >= 0 ? 'var(--success-dim)' : 'var(--danger-dim)',
                color: net >= 0 ? 'var(--success)' : 'var(--danger)',
                border: '1px solid currentColor',
              }}>
                {net >= 0 ? 'Surplus' : 'Deficit'}
              </div>
            </div>

            {/* Card 4: Ratio & Distribution */}
            <div style={{
              background: 'var(--bg-1)',
              border: '1px solid var(--border)',
              borderRadius: 'var(--radius-lg, 12px)',
              padding: '16px 20px',
              display: 'flex',
              flexDirection: 'column',
              justifyContent: 'center',
              gap: 6,
              boxShadow: 'var(--shadow-sm)'
            }}>
              <div style={{ fontSize: '0.72rem', color: 'var(--text-muted)', display: 'flex', justifyContent: 'space-between' }}>
                <span>Inflow Distribution</span>
                <span style={{ fontWeight: 600, color: 'var(--text-primary)' }}>
                  {totalReceived + totalMade > 0 ? Math.round((totalReceived / (totalReceived + totalMade)) * 100) : 0}% Inflow
                </span>
              </div>
              <div style={{ height: 6, background: 'var(--bg-3)', borderRadius: '99px', overflow: 'hidden' }}>
                <div
                  style={{
                    height: '100%', borderRadius: '99px', background: 'var(--success)',
                    width: `${totalReceived + totalMade > 0 ? (totalReceived / (totalReceived + totalMade)) * 100 : 0}%`,
                    transition: 'width 0.4s ease',
                  }}
                />
              </div>
              <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.68rem', color: 'var(--text-muted)' }}>
                <span>Received ({fmt(totalReceived)})</span>
                <span>Outflow ({fmt(totalMade)})</span>
              </div>
            </div>
          </div>
        </div>

        {/* ── Unified filter bar: Search | Sub-tabs | FilterDropdown ── */}
        <div className="page-subbar" style={{ display: 'flex', flexFlow: 'row wrap', gap: 8, alignItems: 'center' }}>
          {/* Search — always first */}
          <div className="search-bar" style={{ margin: 0, height: 34, boxSizing: 'border-box', display: 'flex', alignItems: 'center', minWidth: 180, flex: '0 0 auto' }}>
            <span style={{ color: 'var(--text-muted)', display: 'flex', alignItems: 'center' }}><SearchIcon size={16} /></span>
            <input
              value={search}
              onChange={e => setSearch(e.target.value)}
              placeholder={activeTab === 'Expenses' ? 'Search expenses…' : 'Search transactions…'}
              style={{ fontSize: '0.82rem' }}
            />
          </div>
          {/* Sub-tabs */}
          <div style={{ display: 'flex', gap: 4, alignItems: 'center', flexWrap: 'wrap' }}>
            {(['Made', 'Expenses'].includes(activeTab)
              ? ['Made', 'Expenses']
              : ['All', 'Invoices', 'Received', 'Pending Dues', 'Credit Notes']
            ).map(t => (
              headerTabs ? (
                <button key={t} className={`ws-tab ${activeTab === t ? 'active' : ''}`} onClick={() => setActiveTab(t)}>
                  {t}
                </button>
              ) : (
                <button key={t} className={`tab${activeTab === t ? ' active' : ''}`} onClick={() => setActiveTab(t)} style={{ margin: 0, padding: '4px 10px', fontSize: '0.8rem' }}>
                  {t}
                </button>
              )
            ))}
          </div>
          {/* FilterDropdown — Customer, Date range, Mode, Amount range */}
          <FilterDropdown
            filters={[
              {
                key: 'customer',
                label: 'Customer',
                type: 'select',
                value: customerNameFilter,
                onChange: setCustomerNameFilter,
                options: [
                  { value: '', label: 'All Customers' },
                  ...[...new Set(
                    [...payments, ...pendingDues].map(p =>
                      p.party_name || p.customer_name || p.supplier_name || p.customer || ''
                    ).filter(Boolean)
                  )].sort().map(name => ({ value: name, label: name })),
                ],
              },
              {
                key: 'date',
                label: 'Date Range',
                type: 'daterange',
                value: dateFilter,
                onChange: setDateFilter,
              },
              {
                key: 'mode',
                label: 'Payment Mode',
                type: 'chips',
                value: modeFilter,
                onChange: setModeFilter,
                options: [
                  { value: '', label: 'All Modes' },
                  { value: 'UPI', label: 'UPI' },
                  { value: 'Cash', label: 'Cash' },
                  { value: 'Bank', label: 'Bank Transfer' },
                  { value: 'Cheque', label: 'Cheque' },
                ],
              },
              {
                key: 'amount',
                label: 'Amount Range',
                type: 'amountrange',
                value: amountFilter,
                onChange: setAmountFilter,
              },
            ]}
          />
          {/* SortDropdown — sort + group-by, reusable common component */}
          <SortDropdown
            fields={[
              { value: 'date',       label: 'Date' },
              { value: 'party_name', label: 'Customer' },
              { value: 'amount',     label: 'Amount' },
            ]}
            sortConfig={sortConfig}
            onSortChange={setSortConfig}
            groupFields={[
              { value: '',           label: 'None' },
              { value: 'party_name', label: 'Customer' },
              { value: 'date',       label: 'Date' },
            ]}
            groupBy={groupBy}
            onGroupChange={setGroupBy}
          />
          {/* Customer filter chip — shown inline when ?customer= param is set */}
          {customerFilter && (
            <span style={{
              display: 'inline-flex', alignItems: 'center', gap: 6,
              padding: '4px 12px', borderRadius: 20, height: 34, boxSizing: 'border-box',
              background: 'rgba(99,102,241,0.12)',
              border: '1px solid rgba(99,102,241,0.45)',
              color: '#6366f1', fontSize: '0.82rem', fontWeight: 600, flexShrink: 0,
            }}>
              {customerFilter}
              <button
                onClick={() => navigate('/parties/payments', { replace: true })}
                title="Clear — show all transactions"
                style={{ background: 'none', border: 'none', cursor: 'pointer', color: '#6366f1', padding: 0, fontSize: '1.1rem', lineHeight: 1, display: 'flex', alignItems: 'center' }}
                aria-label="Clear customer filter"
              >×</button>
            </span>
          )}
          {isRefreshing && (
            <span className="toolbar-refresh-spinner">
              <span className="spin" /> Refreshing…
            </span>
          )}
        </div>

        {/* Table & Content */}
        {loading ? (
          <div className="page-loader"><span className="spinner" /> Loading…</div>
        ) : activeTab === 'Invoices' ? (
          <div className="slide-up">
            <InvoicesListView
              authFetch={authFetch}
              reloadKey={invoicesReloadKey}
              onView={(no) => setViewingInvoiceNo(no)}
              onRecordPayment={(inv) => {
                setForm({ ...defaultForm, type: 'received', invoice_ref: inv.invoice_no, amount: String(inv.outstanding || '') })
                setShowModal(true)
              }}
              onReturn={(inv) => setViewingInvoiceNo(inv.invoice_no)}
            />
          </div>
        ) : activeTab === 'Expenses' ? (
          <div className="slide-up">
            {/* Expense Cards */}
            <div className="grid grid-3 mb-6">
              <div className="card">
                <div className="stat-label">Direct Expenses</div>
                <div style={{ fontSize: '1.4rem', fontWeight: 700, color: 'var(--text-secondary)' }}>
                  {fmt(expenses.filter(e => e.expense_type === 'Direct').reduce((s, e) => s + (parseFloat(e.amount) || 0), 0))}
                </div>
                <div style={{ fontSize: '0.72rem', color: 'var(--text-muted)', marginTop: 4 }}>Production/Service related</div>
              </div>
              <div className="card">
                <div className="stat-label">Indirect Expenses</div>
                <div style={{ fontSize: '1.4rem', fontWeight: 700, color: 'var(--text-secondary)' }}>
                  {fmt(expenses.filter(e => e.expense_type === 'Indirect').reduce((s, e) => s + (parseFloat(e.amount) || 0), 0))}
                </div>
                <div style={{ fontSize: '0.72rem', color: 'var(--text-muted)', marginTop: 4 }}>Operating/Office overheads</div>
              </div>
              <div className="card">
                <div className="stat-label">Total Expenses (OPEX)</div>
                <div style={{ fontSize: '1.4rem', fontWeight: 700, color: 'var(--accent)' }}>
                  {fmt(expenses.reduce((s, e) => s + (parseFloat(e.amount) || 0), 0))}
                </div>
                <div style={{ fontSize: '0.72rem', color: 'var(--text-muted)', marginTop: 4 }}>Sum of all operational outflows</div>
              </div>
            </div>

            {/* Expenses Table */}
            {(() => {
              const tableContent = (
                <table className="data-table">
                  <thead><tr>
                    <th className="sortable" onClick={() => handleSort('expense_date')}>
                      Date
                      <span className={`sort-indicator ${sortConfig.key === 'expense_date' && sortConfig.direction ? 'active' : ''}`}>
                        {sortConfig.key === 'expense_date' && sortConfig.direction ? (sortConfig.direction === 'asc' ? '▲' : '▼') : '⇅'}
                      </span>
                    </th>
                    <th className="sortable" onClick={() => handleSort('category')}>
                      Category
                      <span className={`sort-indicator ${sortConfig.key === 'category' && sortConfig.direction ? 'active' : ''}`}>
                        {sortConfig.key === 'category' && sortConfig.direction ? (sortConfig.direction === 'asc' ? '▲' : '▼') : '⇅'}
                      </span>
                    </th>
                    <th className="sortable" onClick={() => handleSort('expense_type')}>
                      Type
                      <span className={`sort-indicator ${sortConfig.key === 'expense_type' && sortConfig.direction ? 'active' : ''}`}>
                        {sortConfig.key === 'expense_type' && sortConfig.direction ? (sortConfig.direction === 'asc' ? '▲' : '▼') : '⇅'}
                      </span>
                    </th>
                    <th className="sortable" onClick={() => handleSort('amount')}>
                      Amount
                      <span className={`sort-indicator ${sortConfig.key === 'amount' && sortConfig.direction ? 'active' : ''}`}>
                        {sortConfig.key === 'amount' && sortConfig.direction ? (sortConfig.direction === 'asc' ? '▲' : '▼') : '⇅'}
                      </span>
                    </th>
                    <th>Payment Mode</th>
                    <th>Notes / Reference</th>
                    <th>Action</th>
                  </tr></thead>
                  <tbody>
                    {filteredExpenses.length === 0 ? (
                      <tr><td colSpan={7}>
                        <div className="empty-state">
                          <div className="empty-icon"><CashIcon size={24} /></div>
                          <h3>No expenses logged</h3>
                          <p>Click "Log Expense" above to record your first operational outflow.</p>
                        </div>
                      </td></tr>
                    ) : filteredExpenses.map(e => (
                      <tr key={e.id}>
                        <td>{e.expense_date ? formatISTDate(e.expense_date) : '—'}</td>
                        <td className="td-primary">{e.category}</td>
                        <td><span className={`badge ${e.expense_type === 'Direct' ? 'badge-warning' : 'badge-info'}`}>{e.expense_type}</span></td>
                        <td style={{ fontWeight: 600, color: 'var(--text-primary)' }}>{fmt(e.amount)}</td>
                        <td><span style={{ display: 'inline-flex', alignItems: 'center', gap: 5 }}><CashIcon size={14} style={{ display: 'inline', marginRight: 4, verticalAlign: 'middle' }} /> {e.payment_mode || '—'}</span></td>
                        <td style={{ fontSize: '0.78rem', color: 'var(--text-secondary)' }}>{e.note || '—'}</td>
                        <td><button className="btn btn-secondary btn-sm" style={{ color: 'var(--danger)', borderColor: 'var(--danger-dim)' }} onClick={() => handleExpenseDelete(e.id)}>✕ Delete</button></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )
              if (isFullScreen) return (
                <div className="table-fullscreen-overlay" onClick={e => { if (e.target === e.currentTarget) setIsFullScreen(false) }}>
                  <div className="table-fullscreen-panel">
                    <div className="table-fullscreen-header">
                      <h3>Expense Ledger</h3>
                      <button type="button" className="table-fullscreen-btn" onClick={() => setIsFullScreen(false)}>✕ Close</button>
                    </div>
                    <div className="data-table-wrap">{tableContent}</div>
                  </div>
                </div>
              )
              return (
                <div style={{ position: 'relative', display: 'flex', flexDirection: 'column', flex: 1, minHeight: 0 }}>
                  <button 
                    type="button" 
                    onClick={() => setIsFullScreen(true)} 
                    style={{ position: 'absolute', top: 6, right: 6, zIndex: 10, background: 'var(--bg-1)', border: '1px solid var(--border)', borderRadius: 'var(--radius-sm)', padding: 4, cursor: 'pointer', color: 'var(--text-secondary)' }} 
                    title="Full Screen"
                  >
                    <ExpandIcon size={14} />
                  </button>
                  <div className="data-table-wrap">{tableContent}</div>
                </div>
              )
            })()}
          </div>
        ) : activeTab === 'Pending Dues' ? (
          <div className="slide-up">
            <div className="grid grid-3 mb-6">
              <div className="card">
                <div className="stat-label">Total Overdue</div>
                <div style={{ fontSize: '1.4rem', fontWeight: 700, color: 'var(--danger)' }}>
                  {fmt(pendingDues.filter(d => d.status === 'Overdue').reduce((s, d) => s + parseFloat(d.balance_due || 0), 0))}
                </div>
              </div>
              <div className="card">
                <div className="stat-label">Total Pending</div>
                <div style={{ fontSize: '1.4rem', fontWeight: 700, color: 'var(--accent)' }}>
                  {fmt(pendingDues.filter(d => d.status === 'Pending').reduce((s, d) => s + parseFloat(d.balance_due || 0), 0))}
                </div>
              </div>
              <div className="card">
                <div className="stat-label">Total Outstanding</div>
                <div style={{ fontSize: '1.4rem', fontWeight: 700, color: 'var(--text-secondary)' }}>
                  {fmt(pendingDues.reduce((s, d) => s + parseFloat(d.balance_due || 0), 0))}
                </div>
              </div>
            </div>
            {(() => {
              const tableContent = (
                <table className="data-table">
                  <thead><tr>
                    <th className="sortable" onClick={() => handleSort('due_date')}>
                      Due Date
                      <span className={`sort-indicator ${sortConfig.key === 'due_date' && sortConfig.direction ? 'active' : ''}`}>
                        {sortConfig.key === 'due_date' && sortConfig.direction ? (sortConfig.direction === 'asc' ? '▲' : '▼') : '⇅'}
                      </span>
                    </th>
                    <th>Invoice #</th>
                    <th className="sortable" onClick={() => handleSort('customer')}>
                      Customer
                      <span className={`sort-indicator ${sortConfig.key === 'customer' && sortConfig.direction ? 'active' : ''}`}>
                        {sortConfig.key === 'customer' && sortConfig.direction ? (sortConfig.direction === 'asc' ? '▲' : '▼') : '⇅'}
                      </span>
                    </th>
                    <th>Total</th>
                    <th>Paid</th>
                    <th className="sortable" onClick={() => handleSort('balance_due')}>
                      Balance
                      <span className={`sort-indicator ${sortConfig.key === 'balance_due' && sortConfig.direction ? 'active' : ''}`}>
                        {sortConfig.key === 'balance_due' && sortConfig.direction ? (sortConfig.direction === 'asc' ? '▲' : '▼') : '⇅'}
                      </span>
                    </th>
                    <th>Status</th>
                  </tr></thead>
                  <tbody>
                    {filteredPendingDues.length === 0 ? (
                      <tr><td colSpan={7}>
                        <div className="empty-state">
                          <div className="empty-icon"><CashIcon size={24} /></div>
                          <h3>No pending dues</h3>
                          <p>All invoices are fully paid.</p>
                        </div>
                      </td></tr>
                    ) : filteredPendingDues.map(d => (
                      <tr key={d.id}
                        style={{ cursor: 'pointer' }}
                        onClick={() => setViewingInvoiceNo(d.invoice_id)}
                        onContextMenu={e => {
                          e.preventDefault()
                          setCtxMenu({ x: e.clientX, y: e.clientY, items: [
                            { label: 'View Invoice', icon: <BillsIcon size={13} />, action: () => setViewingInvoiceNo(d.invoice_id) },
                            { label: 'Copy Invoice No', icon: <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>, action: () => navigator.clipboard.writeText(d.invoice_id || '') },
                            { label: 'Copy Customer Name', icon: <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>, action: () => navigator.clipboard.writeText(d.customer_name || '') },
                          ]})
                        }}
                      >
                        <td>{d.due_date ? formatISTDate(d.due_date) : '—'}</td>
                        <td className="td-mono">
                          {d.invoice_id ? (
                            <span 
                              className="link" 
                              style={{ color: 'var(--accent)', textDecoration: 'underline' }}
                            >
                              {d.invoice_id}
                            </span>
                          ) : '—'}
                        </td>
                        <td className="td-primary">{d.customer || '—'}</td>
                        <td style={{ color: 'var(--text-primary)' }}>{fmt(d.total_amount)}</td>
                        <td style={{ color: 'var(--success)' }}>{fmt(d.paid_amount)}</td>
                        <td style={{ fontWeight: 600, color: d.status === 'Overdue' ? 'var(--danger)' : 'var(--accent)' }}>{fmt(d.balance_due)}</td>
                        <td>
                          <span className={`badge ${d.status === 'Overdue' ? 'badge-danger' : d.status === 'Paid' ? 'badge-success' : d.status === 'partial' ? 'badge-warning' : 'badge-info'}`}>
                            {d.status}
                          </span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )
              if (isFullScreen) return (
                <div className="table-fullscreen-overlay" onClick={e => { if (e.target === e.currentTarget) setIsFullScreen(false) }}>
                  <div className="table-fullscreen-panel">
                    <div className="table-fullscreen-header">
                      <h3>Pending Dues</h3>
                      <button type="button" className="table-fullscreen-btn" onClick={() => setIsFullScreen(false)}>✕ Close</button>
                    </div>
                    <div className="data-table-wrap">{tableContent}</div>
                  </div>
                </div>
              )
              return (
                <div style={{ position: 'relative', display: 'flex', flexDirection: 'column', flex: 1, minHeight: 0 }}>
                  <button 
                    type="button" 
                    onClick={() => setIsFullScreen(true)} 
                    style={{ position: 'absolute', top: 6, right: 6, zIndex: 10, background: 'var(--bg-1)', border: '1px solid var(--border)', borderRadius: 'var(--radius-sm)', padding: 4, cursor: 'pointer', color: 'var(--text-secondary)' }} 
                    title="Full Screen"
                  >
                    <ExpandIcon size={14} />
                  </button>
                  <div className="data-table-wrap">{tableContent}</div>
                </div>
              )
            })()}
          </div>
        ) : activeTab === 'Credit Notes' ? (
          <div className="slide-up">
            {(() => {
              const tableContent = (
                <table className="data-table">
                  <thead><tr>
                    <th className="sortable" onClick={() => handleSort('date')}>
                      Date
                      <span className={`sort-indicator ${sortConfig.key === 'date' && sortConfig.direction ? 'active' : ''}`}>
                        {sortConfig.key === 'date' && sortConfig.direction ? (sortConfig.direction === 'asc' ? '▲' : '▼') : '⇅'}
                      </span>
                    </th>
                    <th>Credit Note #</th>
                    <th>Ref Invoice</th>
                    <th className="sortable" onClick={() => handleSort('customer')}>
                      Customer
                      <span className={`sort-indicator ${sortConfig.key === 'customer' && sortConfig.direction ? 'active' : ''}`}>
                        {sortConfig.key === 'customer' && sortConfig.direction ? (sortConfig.direction === 'asc' ? '▲' : '▼') : '⇅'}
                      </span>
                    </th>
                    <th className="sortable" onClick={() => handleSort('amount')}>
                      Amount
                      <span className={`sort-indicator ${sortConfig.key === 'amount' && sortConfig.direction ? 'active' : ''}`}>
                        {sortConfig.key === 'amount' && sortConfig.direction ? (sortConfig.direction === 'asc' ? '▲' : '▼') : '⇅'}
                      </span>
                    </th>
                    <th>Status</th>
                    <th>Notes</th>
                  </tr></thead>
                  <tbody>
                    {filteredCreditNotes.length === 0 ? (
                      <tr><td colSpan={7}>
                        <div className="empty-state">
                          <div className="empty-icon"><CashIcon size={24} /></div>
                          <h3>No credit notes</h3>
                          <p>You haven't issued any credit notes or returns yet.</p>
                        </div>
                      </td></tr>
                    ) : filteredCreditNotes.map(cn => (
                      <tr key={cn.id}
                        style={{ cursor: 'pointer' }}
                        onClick={() => setViewingInvoiceNo(cn.invoice_id)}
                        onContextMenu={e => {
                          e.preventDefault()
                          setCtxMenu({ x: e.clientX, y: e.clientY, items: [
                            { label: 'View Ref Invoice', icon: <BillsIcon size={13} />, action: () => setViewingInvoiceNo(cn.invoice_id) },
                            { label: 'Copy CN No', icon: <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>, action: () => navigator.clipboard.writeText(cn.credit_note_number || cn.invoice_id || '') },
                            { label: 'Copy Customer Name', icon: <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>, action: () => navigator.clipboard.writeText(cn.customer_name || '') },
                          ]})
                        }}
                      >
                        <td>{cn.date ? formatISTDate(cn.date) : '—'}</td>
                        <td className="td-mono">
                          {cn.invoice_id ? (
                            <span 
                              className="link" 
                              style={{ color: 'var(--accent)', textDecoration: 'underline' }}
                            >
                              {cn.invoice_id}
                            </span>
                          ) : '—'}
                        </td>
                        <td className="td-mono">
                          {cn.reference_invoice ? (
                            <span 
                              className="link" 
                              onClick={(e) => { e.stopPropagation(); setViewingInvoiceNo(cn.reference_invoice) }}
                              style={{ cursor: 'pointer', color: 'var(--accent)', textDecoration: 'underline' }}
                            >
                              {cn.reference_invoice}
                            </span>
                          ) : '—'}
                        </td>
                        <td className="td-primary">{cn.customer || '—'}</td>
                        <td style={{ fontWeight: 600, color: 'var(--danger)' }}>{fmt(cn.amount)}</td>
                        <td><span className="badge badge-info">{cn.status || 'Issued'}</span></td>
                        <td style={{ fontSize: '0.78rem', color: 'var(--text-secondary)' }}>{cn.note || '—'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )
              if (isFullScreen) return (
                <div className="table-fullscreen-overlay" onClick={e => { if (e.target === e.currentTarget) setIsFullScreen(false) }}>
                  <div className="table-fullscreen-panel">
                    <div className="table-fullscreen-header">
                      <h3>Credit Notes</h3>
                      <button type="button" className="table-fullscreen-btn" onClick={() => setIsFullScreen(false)}>✕ Close</button>
                    </div>
                    <div className="data-table-wrap">{tableContent}</div>
                  </div>
                </div>
              )
              return (
                <div style={{ position: 'relative', display: 'flex', flexDirection: 'column', flex: 1, minHeight: 0 }}>
                  <button 
                    type="button" 
                    onClick={() => setIsFullScreen(true)} 
                    style={{ position: 'absolute', top: 6, right: 6, zIndex: 10, background: 'var(--bg-1)', border: '1px solid var(--border)', borderRadius: 'var(--radius-sm)', padding: 4, cursor: 'pointer', color: 'var(--text-secondary)' }} 
                    title="Full Screen"
                  >
                    <ExpandIcon size={14} />
                  </button>
                  <div className="data-table-wrap">{tableContent}</div>
                </div>
              )
            })()}
          </div>
        ) : (
          <>
            {(() => {
              const tableContent = (
                <table className="data-table" style={{ width: '100%', fontSize: '0.82rem' }}>
                  <thead><tr>
                    <th style={{ whiteSpace: 'nowrap' }}>Date</th>
                    <th style={{ whiteSpace: 'nowrap' }}>Invoice #</th>
                    <th style={{ whiteSpace: 'nowrap' }}>Customer / Supplier</th>
                    <th style={{ whiteSpace: 'nowrap' }}>Type</th>
                    <th style={{ textAlign: 'right', whiteSpace: 'nowrap' }}>Amount</th>
                    <th style={{ whiteSpace: 'nowrap' }}>Method</th>
                    <th style={{ whiteSpace: 'nowrap' }}>Reference</th>
                  </tr></thead>
                  <tbody>
                    {filtered.length === 0 ? (
                      <tr><td colSpan={7}>
                        <div className="empty-state">
                          <div className="empty-icon"><CashIcon size={24} /></div>
                          <h3>No payments yet</h3>
                          <p>Record your first payment using the button above.</p>
                        </div>
                      </td></tr>
                    ) : filtered.map(p => (
                      <tr
                        key={p.id}
                        style={{
                          cursor: p.type === 'pending_due' || p.invoice_number || p.invoice_ref ? 'pointer' : 'default',
                          background: p.type === 'pending_due' ? 'rgba(180,83,9,0.04)' : undefined,
                        }}
                        title={p.type === 'pending_due' ? 'Click to settle this due' : undefined}
                        onClick={() => {
                          if (p.type === 'pending_due' && !isCashier) {
                            // p._customerId is stored at mapping time from d.customer_id
                            setSettlePreset({
                              customerId:   p._customerId ?? null,
                              customerName: p.party_name || p.customer_name || '',
                              outstanding:  parseFloat(p.amount ?? 0),
                            })
                            setShowSettleModal(true)
                          } else if (p.invoice_number || p.invoice_ref) {
                            setViewingInvoiceNo(p.invoice_number || p.invoice_ref)
                          }
                        }}
                        onContextMenu={e => {
                          e.preventDefault()
                          setCtxMenu({ x: e.clientX, y: e.clientY, items: [
                            ...(p.invoice_number || p.invoice_ref ? [{ label: 'View Invoice', icon: <BillsIcon size={13} />, action: () => setViewingInvoiceNo(p.invoice_number || p.invoice_ref) }] : []),
                            { label: 'Copy Reference', icon: <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>, action: () => navigator.clipboard.writeText(p.reference || p.invoice_number || '') },
                            { label: 'Copy Amount', icon: <CashIcon size={13} />, action: () => navigator.clipboard.writeText(String(p.amount || '')) },
                          ]})
                        }}
                      >
                        <td style={{ whiteSpace: 'nowrap', color: 'var(--text-muted)', fontSize: '0.78rem' }}>{p.date ? formatISTDateTime(p.date) : '—'}</td>
                        <td className="td-mono" style={{ whiteSpace: 'nowrap' }}>
                          {(p.invoice_number || p.invoice_ref) ? (
                            <span 
                              className="link" 
                              style={{ color: 'var(--accent)', textDecoration: 'underline' }}
                            >
                              {p.invoice_number || p.invoice_ref}
                            </span>
                          ) : '—'}
                        </td>
                        <td style={{ whiteSpace: 'nowrap', fontWeight: 600 }}>{p.party_name || p.customer_name || p.supplier_name || '—'}</td>
                        <td style={{ whiteSpace: 'nowrap' }}>
                          <span className={`badge ${p.type === 'received' || p.type === 'settlement' ? 'badge-success' : (p.type === 'expense' ? 'badge-warning' : p.type === 'pending_due' ? 'badge-danger' : p.type === 'credit_note' ? 'badge-info' : 'badge-accent')}`}>
                            {p.type === 'received' ? '↓ Received' : p.type === 'settlement' ? '↓ Settlement' : (p.type === 'expense' ? '↑ Expense' : p.type === 'pending_due' ? '⚠ Pending' : p.type === 'credit_note' ? '⟲ Credit Note' : '↑ Made')}
                          </span>
                        </td>
                        <td style={{ textAlign: 'right', whiteSpace: 'nowrap', fontWeight: 600, color: (p.type === 'received' || p.type === 'settlement') ? 'var(--success)' : (p.type === 'pending_due' ? 'var(--warning)' : (p.type === 'credit_note' ? 'var(--info)' : 'var(--danger)')) }}>
                          {(p.type === 'received' || p.type === 'settlement' || p.type === 'pending_due') ? '+' : '−'}{fmt(p.amount)}
                        </td>
                        <td style={{ whiteSpace: 'nowrap' }}><span style={{ display: 'inline-flex', alignItems: 'center', gap: 5 }}><CashIcon size={14} style={{ display: 'inline', marginRight: 4, verticalAlign: 'middle' }} /> {p.method || '—'}</span></td>
                        <td className="td-mono" style={{ fontSize: '0.78rem', color: 'var(--text-muted)' }}>{p.reference || '—'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )
              if (isFullScreen) return (
                <div className="table-fullscreen-overlay" onClick={e => { if (e.target === e.currentTarget) setIsFullScreen(false) }}>
                  <div className="table-fullscreen-panel">
                    <div className="table-fullscreen-header">
                      <h3>Cash Book</h3>
                      <button type="button" className="table-fullscreen-btn" onClick={() => setIsFullScreen(false)}>✕ Close</button>
                    </div>
                    <div className="data-table-wrap">{tableContent}</div>
                  </div>
                </div>
              )
              return (
                <div style={{ position: 'relative', display: 'flex', flexDirection: 'column', flex: 1, minHeight: 0 }}>
                  <button 
                    type="button" 
                    onClick={() => setIsFullScreen(true)} 
                    style={{ position: 'absolute', top: 6, right: 6, zIndex: 10, background: 'var(--bg-1)', border: '1px solid var(--border)', borderRadius: 'var(--radius-sm)', padding: 4, cursor: 'pointer', color: 'var(--text-secondary)' }} 
                    title="Full Screen"
                  >
                    <ExpandIcon size={14} />
                  </button>
                  <div className="data-table-wrap">{tableContent}</div>
                </div>
              )
            })()}
          </>
        )}
      </div>

      {/* Record Payment Modal */}
      {/* 💳 Record Payment Modal — extracted to components/payments/RecordPaymentModal */}
      {showModal && (
        <RecordPaymentModal
          form={form}
          setField={setField}
          onSubmit={handleSubmit}
          submitting={submitting}
          onClose={() => setShowModal(false)}
        />
      )}

      {/* Settle Dues Modal — presets when a Pending row was clicked */}
      {showSettleModal && (
        <SettleDuesModal
          authFetch={authFetch}
          presetCustomerId={settlePreset?.customerId ?? null}
          presetCustomerName={settlePreset?.customerName ?? null}
          presetOutstanding={settlePreset?.outstanding ?? null}
          onClose={() => { setShowSettleModal(false); setSettlePreset(null) }}
          onDone={() => { load(); setSettlePreset(null) }}
        />
      )}

      {/* 💸 Log Expense Modal — extracted to components/payments/LogExpenseModal */}
      {showExpenseModal && (
        <LogExpenseModal
          expenseForm={expenseForm}
          setExpenseField={setExpenseField}
          onSubmit={handleExpenseSubmit}
          submitting={submitting}
          onClose={() => setShowExpenseModal(false)}
        />
      )}



      {/* ── Invoice modal portal — extracted to components/invoice/InvoiceViewerModal ── */}
      <InvoiceViewerModal invoiceNo={viewingInvoiceNo} onClose={() => setViewingInvoiceNo(null)} />
      </>
      <ContextMenu menu={ctxMenu} onClose={() => setCtxMenu(null)} />
      <UnsavedChangesModal blocker={blocker} message={dirtyMessage} />
    </PageShell>
  )
}
