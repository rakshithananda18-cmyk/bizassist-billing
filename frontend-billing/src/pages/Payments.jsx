// ============================================================================
// Page: Payments.jsx
// Description: Payment Journals and Expense Tracker. Registers cash/bank inflows
//              and outflows, records general expenses, and tracks credit note returns.
// ============================================================================
import React, { useEffect, useState, useCallback, useRef } from 'react'
import { createPortal } from 'react-dom'
import AppLayout from '../layouts/AppLayout'
import { useAuth } from '../contexts/AuthContext'
import { BillsIcon, CashIcon, CheckIcon, CloseIcon, PhoneIcon, PlusIcon, WarehouseIcon, SearchIcon, ExpandIcon, SummaryIcon, SparkleIcon, InfoIcon, AlertIcon, ChevronDownIcon } from '../components/Icons'

import { logger } from '../utils/logger'
import CustomSelect from '../components/common/CustomSelect'
import { formatISTDate } from '../utils/format'
import InvoiceViewer from '../invoice/InvoiceViewer'
import { buildWhatsAppLink, buildPublicInvoiceLink } from '../invoice/share'



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

export default function Payments() {
  const { authFetch, settings } = useAuth()

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
      const mappedPayments = payments.map(p => ({ ...p, _sortDate: p.date }))
      const mappedExpenses = expenses.map(e => ({
        id: `exp-${e.id}`,
        date: e.expense_date,
        party_name: e.category,
        type: 'expense',
        amount: e.amount,
        method: e.payment_mode,
        reference: e.note,
        _sortDate: e.expense_date
      }))
      const mappedDues = pendingDues.map(d => ({
        id: `due-${d.id}`,
        date: d.invoice_date || d.due_date,
        invoice_number: d.invoice_id,
        party_name: d.customer,
        type: 'pending_due',
        amount: d.balance_due,
        method: '—',
        reference: `Pending Balance (Due: ${d.due_date ? formatISTDate(d.due_date) : '—'})`,
        _sortDate: d.invoice_date || d.due_date
      }))
      const mappedCreditNotes = creditNotes.map(cn => ({
        id: `cn-${cn.id}`,
        date: cn.date,
        invoice_number: cn.invoice_id,
        party_name: cn.customer,
        type: 'credit_note',
        amount: cn.amount,
        method: '—',
        reference: cn.note ? `Credit Note: ${cn.note}` : `Credit Note for ${cn.reference_invoice || '—'}`,
        _sortDate: cn.date
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
        if (activeTab === 'Received' && p.type !== 'received') return false
        if (activeTab === 'Made' && p.type !== 'made') return false
        return true
      }).map(p => ({ ...p, _sortDate: p.date }))
    }

    let items = baseItems.filter(p => {
      if (modeFilter && p.method !== modeFilter) return false

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
      if (modeFilter && e.payment_mode !== modeFilter) return false

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
      const res = await authFetch('/billing/payments', {
        method: 'POST',
        body: JSON.stringify({ ...form, amount: parseFloat(form.amount) }),
      })
      if (res.ok) {
        setAlert({ type: 'success', msg: 'Payment recorded successfully!' })
        setShowModal(false)
        setForm(defaultForm)
        load()
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
      const res = await authFetch('/billing/expenses', {
        method: 'POST',
        body: JSON.stringify({
          ...expenseForm,
          amount: parseFloat(expenseForm.amount)
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
    <AppLayout title="Payments">
      <>
      <div className="slide-up">


        {alert && (
          <div className={`alert alert-${alert.type} mb-4`}>
            {alert.type === 'success' ? '✅' : '❌'} {alert.msg}
            <button onClick={() => setAlert(null)} style={{ marginLeft: 'auto', background: 'none', border: 'none', color: 'inherit', cursor: 'pointer' }} aria-label="Close"><CloseIcon size={16} /></button>
          </div>
        )}

        {/* Header */}
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

        {/* Sub-filters (left of search) & Search/Filter */}
        <div className="flex items-center justify-between page-subbar" style={{ display: 'flex', flexFlow: 'row wrap', gap: 12, alignItems: 'center' }}>
          <div style={{ display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap' }}>
            <div style={{ display: 'flex', gap: 4, alignItems: 'center' }}>
              {(['Made', 'Expenses'].includes(activeTab)
                ? ['Made', 'Expenses']
                : ['All', 'Received', 'Pending Dues', 'Credit Notes']
              ).map(t => (
                <button key={t} className={`tab${activeTab === t ? ' active' : ''}`} onClick={() => setActiveTab(t)} style={{ margin: 0, padding: '4px 10px', fontSize: '0.8rem' }}>
                  {t}
                </button>
              ))}
            </div>
            <div className="search-bar" style={{ width: 180, margin: 0, height: '34px', boxSizing: 'border-box', display: 'flex', alignItems: 'center' }}>
              <span style={{ color: 'var(--text-muted)', display: 'flex', alignItems: 'center' }}><SearchIcon size={16} /></span>
              <input 
                value={search} 
                onChange={e => setSearch(e.target.value)} 
                placeholder={activeTab === 'Expenses' ? "Search expenses…" : "Search transactions…"} 
                style={{ fontSize: '0.82rem' }}
              />
            </div>
            <CustomSelect
              value={modeFilter}
              onChange={e => setModeFilter(e.target.value)}
              style={{
                background: 'var(--bg-2)',
                border: '1px solid var(--border)',
                borderRadius: 'var(--radius-md)',
                color: 'var(--text-primary)',
                padding: '0 12px',
                fontSize: '0.82rem',
                cursor: 'pointer',
                width: '130px',
                height: '34px',
                boxSizing: 'border-box',
                display: 'inline-flex',
                alignItems: 'center'
              }}
            >
              <option value="">All Modes</option>
              <option value="UPI">UPI</option>
              <option value="Cash">Cash</option>
              <option value="Bank Transfer">Bank Transfer</option>
              <option value="Card">Card</option>
            </CustomSelect>
          </div>
        </div>

        {/* Table & Content */}
        {loading ? (
          <div className="page-loader"><span className="spinner" /> Loading…</div>
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
                      <tr key={d.id} style={{ cursor: 'pointer' }} onClick={() => setViewingInvoiceNo(d.invoice_id)}>
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
                      <tr key={cn.id} style={{ cursor: 'pointer' }} onClick={() => setViewingInvoiceNo(cn.invoice_id)}>
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
                <table className="data-table">
                  <thead><tr>
                    <th className="sortable" onClick={() => handleSort('date')}>
                      Date
                      <span className={`sort-indicator ${sortConfig.key === 'date' && sortConfig.direction ? 'active' : ''}`}>
                        {sortConfig.key === 'date' && sortConfig.direction ? (sortConfig.direction === 'asc' ? '▲' : '▼') : '⇅'}
                      </span>
                    </th>
                    <th className="sortable" onClick={() => handleSort('invoice_number')}>
                      Invoice #
                      <span className={`sort-indicator ${sortConfig.key === 'invoice_number' && sortConfig.direction ? 'active' : ''}`}>
                        {sortConfig.key === 'invoice_number' && sortConfig.direction ? (sortConfig.direction === 'asc' ? '▲' : '▼') : '⇅'}
                      </span>
                    </th>
                    <th className="sortable" onClick={() => handleSort('party_name')}>
                      Customer / Supplier
                      <span className={`sort-indicator ${sortConfig.key === 'party_name' && sortConfig.direction ? 'active' : ''}`}>
                        {sortConfig.key === 'party_name' && sortConfig.direction ? (sortConfig.direction === 'asc' ? '▲' : '▼') : '⇅'}
                      </span>
                    </th>
                    <th className="sortable" onClick={() => handleSort('type')}>
                      Type
                      <span className={`sort-indicator ${sortConfig.key === 'type' && sortConfig.direction ? 'active' : ''}`}>
                        {sortConfig.key === 'type' && sortConfig.direction ? (sortConfig.direction === 'asc' ? '▲' : '▼') : '⇅'}
                      </span>
                    </th>
                    <th className="sortable" onClick={() => handleSort('amount')}>
                      Amount
                      <span className={`sort-indicator ${sortConfig.key === 'amount' && sortConfig.direction ? 'active' : ''}`}>
                        {sortConfig.key === 'amount' && sortConfig.direction ? (sortConfig.direction === 'asc' ? '▲' : '▼') : '⇅'}
                      </span>
                    </th>
                    <th className="sortable" onClick={() => handleSort('method')}>
                      Method
                      <span className={`sort-indicator ${sortConfig.key === 'method' && sortConfig.direction ? 'active' : ''}`}>
                        {sortConfig.key === 'method' && sortConfig.direction ? (sortConfig.direction === 'asc' ? '▲' : '▼') : '⇅'}
                      </span>
                    </th>
                    <th>Reference</th>
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
                      <tr key={p.id} style={{ cursor: (p.invoice_number || p.invoice_ref) ? 'pointer' : 'default' }} onClick={() => { if (p.invoice_number || p.invoice_ref) setViewingInvoiceNo(p.invoice_number || p.invoice_ref) }}>
                        <td>{p.date ? formatISTDate(p.date) : '—'}</td>
                        <td className="td-mono">
                          {(p.invoice_number || p.invoice_ref) ? (
                            <span 
                              className="link" 
                              style={{ color: 'var(--accent)', textDecoration: 'underline' }}
                            >
                              {p.invoice_number || p.invoice_ref}
                            </span>
                          ) : '—'}
                        </td>
                        <td className="td-primary">{p.party_name || p.customer_name || p.supplier_name || '—'}</td>
                        <td>
                          <span className={`badge ${p.type === 'received' ? 'badge-success' : (p.type === 'expense' ? 'badge-warning' : p.type === 'pending_due' ? 'badge-danger' : p.type === 'credit_note' ? 'badge-info' : 'badge-accent')}`}>
                            {p.type === 'received' ? '↓ Received' : (p.type === 'expense' ? '↑ Expense' : p.type === 'pending_due' ? '⚠ Pending' : p.type === 'credit_note' ? '⟲ Credit Note' : '↑ Made')}
                          </span>
                        </td>
                        <td style={{ fontWeight: 600, color: p.type === 'received' ? 'var(--success)' : (p.type === 'pending_due' ? 'var(--warning)' : (p.type === 'credit_note' ? 'var(--info)' : 'var(--danger)')) }}>
                          {(p.type === 'received' || p.type === 'pending_due') ? '+' : '−'}{fmt(p.amount)}
                        </td>
                        <td><span style={{ display: 'inline-flex', alignItems: 'center', gap: 5 }}><CashIcon size={14} style={{ display: 'inline', marginRight: 4, verticalAlign: 'middle' }} /> {p.method || '—'}</span></td>
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
      {showModal && (
        <div className="modal-overlay" onClick={e => e.target === e.currentTarget && setShowModal(false)}>
          <div className="modal">
            <div className="modal-header">
              <span className="modal-title">💳 Record Payment</span>
              <button className="btn btn-ghost btn-icon" onClick={() => setShowModal(false)} aria-label="Close"><CloseIcon size={16} /></button>
            </div>
            <form onSubmit={handleSubmit}>
              <div className="modal-body">
                <div className="grid grid-2 gap-3 mb-4">
                  <div className="form-group">
                    <label className="form-label">Payment Type</label>
                    <CustomSelect className="form-select" value={form.type} onChange={e => setField('type', e.target.value)}>
                      <option value="received">Received (from customer)</option>
                      <option value="made">Made (to supplier)</option>
                    </CustomSelect>
                  </div>
                  <div className="form-group">
                    <label className="form-label">Date</label>
                    <input type="date" className="form-input" value={form.date} onChange={e => setField('date', e.target.value)} required />
                  </div>
                </div>
                <div className="form-group mb-4">
                  <label className="form-label">Invoice / Bill Reference</label>
                  <input className="form-input" placeholder="INV-001 or bill number…" value={form.invoice_ref} onChange={e => setField('invoice_ref', e.target.value)} />
                </div>
                <div className="grid grid-2 gap-3 mb-4">
                  <div className="form-group">
                    <label className="form-label">Amount (₹)</label>
                    <input type="number" className="form-input" placeholder="0.00" min="0" step="any" value={form.amount} onChange={e => setField('amount', e.target.value)} required />
                  </div>
                  <div className="form-group">
                    <label className="form-label">Payment Method</label>
                    <CustomSelect className="form-select" value={form.method} onChange={e => setField('method', e.target.value)}>
                      <option value="Cash"><CashIcon size={14} style={{ marginRight: 6, display: 'inline-block', verticalAlign: 'middle' }} /> Cash</option>
                      <option value="UPI"><PhoneIcon size={14} style={{ marginRight: 6, display: 'inline-block', verticalAlign: 'middle' }} /> UPI</option>
                      <option value="Bank"><WarehouseIcon size={14} style={{ marginRight: 6, display: 'inline-block', verticalAlign: 'middle' }} /> Bank Transfer</option>
                      <option value="Cheque"><BillsIcon size={14} style={{ marginRight: 6, display: 'inline-block', verticalAlign: 'middle' }} /> Cheque</option>
                    </CustomSelect>
                  </div>
                </div>
                <div className="form-group">
                  <label className="form-label">Reference / UTR / Cheque No.</label>
                  <input className="form-input" placeholder="Transaction reference…" value={form.reference} onChange={e => setField('reference', e.target.value)} />
                </div>
              </div>
              <div className="modal-footer">
                <button type="button" className="btn btn-secondary" onClick={() => setShowModal(false)}>Cancel</button>
                <button type="submit" className="btn btn-primary" disabled={submitting}>
                  {submitting ? <><span className="spinner" style={{ width: 14, height: 14, borderWidth: 2 }} /> Recording…</> : <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}><CheckIcon size={14} /> Record Payment</span>}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* 💸 Log Expense Modal */}
      {showExpenseModal && (
        <div className="modal-overlay" onClick={e => e.target === e.currentTarget && setShowExpenseModal(false)}>
          <div className="modal">
            <div className="modal-header">
              <span className="modal-title"><CashIcon size={16} style={{ marginRight: 6, display: 'inline-block', verticalAlign: 'middle' }} /> Log Business Expense</span>
              <button className="btn btn-ghost btn-icon" onClick={() => setShowExpenseModal(false)} aria-label="Close"><CloseIcon size={16} /></button>
            </div>
            <form onSubmit={handleExpenseSubmit}>
              <div className="modal-body">
                <div className="grid grid-2 gap-3 mb-4">
                  <div className="form-group">
                    <label className="form-label">Expense Date</label>
                    <input type="date" className="form-input" value={expenseForm.expense_date} onChange={e => setExpenseField('expense_date', e.target.value)} required />
                  </div>
                  <div className="form-group">
                    <label className="form-label">Expense Category</label>
                    <CustomSelect className="form-select" value={expenseForm.category} onChange={e => setExpenseField('category', e.target.value)}>
                      <option value="Rent">Rent</option>
                      <option value="Utilities">Utilities (Power, Water, Net)</option>
                      <option value="Salaries & Wages">Salaries & Wages</option>
                      <option value="Marketing & Advertising">Marketing & Ads</option>
                      <option value="Office Supplies">Office Supplies</option>
                      <option value="Travel & Conveyance">Travel & Conveyance</option>
                      <option value="Repair & Maintenance">Repair & Maintenance</option>
                      <option value="Others">Others</option>
                    </CustomSelect>
                  </div>
                </div>

                <div className="grid grid-2 gap-3 mb-4">
                  <div className="form-group">
                    <label className="form-label">Expense Type</label>
                    <CustomSelect className="form-select" value={expenseForm.expense_type} onChange={e => setExpenseField('expense_type', e.target.value)}>
                      <option value="Indirect">Indirect (Operating/Office Overhead)</option>
                      <option value="Direct">Direct (Cost of Production/Goods)</option>
                    </CustomSelect>
                  </div>
                  <div className="form-group">
                    <label className="form-label">Payment Mode</label>
                    <CustomSelect className="form-select" value={expenseForm.payment_mode} onChange={e => setExpenseField('payment_mode', e.target.value)}>
                      <option value="Cash"><CashIcon size={14} style={{ marginRight: 6, display: 'inline-block', verticalAlign: 'middle' }} /> Cash</option>
                      <option value="UPI"><PhoneIcon size={14} style={{ marginRight: 6, display: 'inline-block', verticalAlign: 'middle' }} /> UPI</option>
                      <option value="Bank"><WarehouseIcon size={14} style={{ marginRight: 6, display: 'inline-block', verticalAlign: 'middle' }} /> Bank Transfer</option>
                    </CustomSelect>
                  </div>
                </div>

                <div className="form-group mb-4">
                  <label className="form-label">Amount (₹)</label>
                  <input type="number" className="form-input" placeholder="0.00" min="0" step="any" value={expenseForm.amount} onChange={e => setExpenseField('amount', e.target.value)} required />
                </div>

                <div className="form-group">
                  <label className="form-label">Description / Remarks</label>
                  <textarea className="form-input" placeholder="e.g. Electricity bill for June…" rows={2} value={expenseForm.note} onChange={e => setExpenseField('note', e.target.value)} />
                </div>
              </div>
              <div className="modal-footer">
                <button type="button" className="btn btn-secondary" onClick={() => setShowExpenseModal(false)}>Cancel</button>
                <button type="submit" className="btn btn-primary" disabled={submitting}>
                  {submitting ? <><span className="spinner" style={{ width: 14, height: 14, borderWidth: 2 }} /> Saving…</> : <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}><CheckIcon size={14} /> Save Expense</span>}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}



      {/* ── Invoice modal portal ────────────────────────────────────── */}
      {viewingInvoiceNo && createPortal(
        <div
          role="dialog"
          aria-modal="true"
          aria-label="Invoice viewer"
          className="no-print"
          style={{
            position: 'fixed', inset: 0, zIndex: 1200,
            display: 'flex', flexDirection: 'column',
            background: 'rgba(0,0,0,0.55)',
            backdropFilter: 'blur(4px)',
            animation: 'fadeInBackdrop 0.18s ease',
          }}
          onClick={(e) => { if (e.target === e.currentTarget) setViewingInvoiceNo(null) }}
        >
          <style>{`
            @keyframes fadeInBackdrop { from { opacity: 0 } to { opacity: 1 } }
            @keyframes slideUpModal { from { transform: translateY(32px); opacity: 0 } to { transform: none; opacity: 1 } }
          `}</style>

          {/* Modal shell */}
          <div style={{
            margin: 'auto',
            width: '96vw', maxWidth: 1200,
            height: '92vh',
            background: 'var(--bg-2)',
            borderRadius: 'var(--radius-lg, 14px)',
            border: '1px solid var(--border)',
            boxShadow: '0 24px 80px rgba(0,0,0,0.45)',
            display: 'flex', flexDirection: 'column',
            overflow: 'hidden',
            animation: 'slideUpModal 0.22s cubic-bezier(0.34,1.56,0.64,1)',
          }}>
            {/* Close strip */}
            <div style={{
              display: 'flex', justifyContent: 'flex-end', alignItems: 'center',
              padding: '6px 10px 0',
              flexShrink: 0,
            }}>
              <button
                onClick={() => setViewingInvoiceNo(null)}
                aria-label="Close invoice viewer"
                style={{
                  background: 'var(--bg-3)', border: '1px solid var(--border)',
                  borderRadius: '50%', width: 28, height: 28,
                  display: 'flex', alignItems: 'center', justifyContent: 'center',
                  cursor: 'pointer', color: 'var(--text-secondary)',
                  fontSize: '1.1rem', lineHeight: 1, flexShrink: 0,
                  transition: 'background 0.15s, color 0.15s',
                }}
                onMouseEnter={e => { e.currentTarget.style.background = 'var(--danger-dim)'; e.currentTarget.style.color = 'var(--danger)' }}
                onMouseLeave={e => { e.currentTarget.style.background = 'var(--bg-3)'; e.currentTarget.style.color = 'var(--text-secondary)' }}
              >
                ×
              </button>
            </div>

            {/* The full InvoiceViewer — embedded mode so Back/× both close the modal */}
            <div style={{ flex: 1, minHeight: 0, overflow: 'hidden' }}>
              <InvoiceViewer
                key={viewingInvoiceNo}
                invoiceNo={viewingInvoiceNo}
                embedded
                onBack={() => setViewingInvoiceNo(null)}
              />
            </div>
          </div>
        </div>,
        document.body
      )}
      </>
    </AppLayout>
  )
}
