import React, { useEffect, useState, useCallback, useRef } from 'react'
import AppLayout from '../layouts/AppLayout'
import { useAuth } from '../contexts/AuthContext'
import { BillsIcon, CashIcon, CheckIcon, CloseIcon, PhoneIcon, PlusIcon, WarehouseIcon } from '../components/Icons'

import { logger } from '../utils/logger'

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
  const [loading, setLoading]       = useState(true)
  const [activeTab, setActiveTab]   = useState('All')
  const [showModal, setShowModal]   = useState(false)
  const [showExpenseModal, setShowExpenseModal] = useState(false)
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
      authFetch('/billing/expenses').then(r => r.ok ? r.json() : [])
    ])
      .then(([payData, expData]) => {
        setPayments(Array.isArray(payData) ? payData : [])
        setExpenses(Array.isArray(expData) ? expData : [])
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
      if (['payment', 'invoice', 'purchase'].includes(e.detail.entity)) {
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

  const filtered = payments.filter(p => {
    if (activeTab === 'Received' && p.type !== 'received') return false
    if (activeTab === 'Made' && p.type !== 'made') return false
    return true
  })

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
            <h1 className="page-title">{activeTab === 'Expenses' ? 'Expenses' : 'Payments'}</h1>
            <p className="page-subtitle">
              {activeTab === 'Expenses' 
                ? 'Track operational, rent, utility, and other business expenses' 
                : 'Track all money received and payments made'}
            </p>
          </div>
          <div className="page-actions">
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

        {/* Tabs */}
        <div className="flex items-center justify-between page-subbar" style={{ flexWrap: 'wrap', gap: 12 }}>
          <div className="tabs">
            {['All', 'Received', 'Made', 'Expenses'].map(t => (
              <button key={t} className={`tab${activeTab === t ? ' active' : ''}`} onClick={() => setActiveTab(t)}>
                {t}
              </button>
            ))}
          </div>
          {activeTab !== 'Expenses' ? (
            <div style={{ display: 'flex', gap: 16, fontSize: '0.82rem' }}>
              <span style={{ color: 'var(--success)' }}>↑ {fmt(totalReceived)} received</span>
              <span style={{ color: 'var(--danger)' }}>↓ {fmt(totalMade)} made</span>
            </div>
          ) : (
            <div style={{ display: 'flex', gap: 16, fontSize: '0.82rem' }}>
              <span style={{ color: 'var(--accent)' }}>Total: {fmt(expenses.reduce((s, e) => s + (parseFloat(e.amount) || 0), 0))} spent</span>
            </div>
          )}
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
            <div className="data-table-wrap">
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Date</th>
                    <th>Category</th>
                    <th>Type</th>
                    <th>Amount</th>
                    <th>Payment Mode</th>
                    <th>Notes / Reference</th>
                    <th>Action</th>
                  </tr>
                </thead>
                <tbody>
                  {expenses.length === 0 ? (
                    <tr><td colSpan={7}>
                      <div className="empty-state">
                        <div className="empty-icon"><CashIcon size={24} /></div>
                        <h3>No expenses logged</h3>
                        <p>Click "Log Expense" above to record your first operational outflow.</p>
                      </div>
                    </td></tr>
                  ) : expenses.map(e => (
                    <tr key={e.id}>
                      <td>{e.expense_date ? new Date(e.expense_date).toLocaleDateString('en-IN') : '—'}</td>
                      <td className="td-primary">{e.category}</td>
                      <td>
                        <span className={`badge ${e.expense_type === 'Direct' ? 'badge-warning' : 'badge-info'}`}>
                          {e.expense_type}
                        </span>
                      </td>
                      <td style={{ fontWeight: 600, color: 'var(--text-primary)' }}>{fmt(e.amount)}</td>
                      <td>
                        <span style={{ display: 'inline-flex', alignItems: 'center', gap: 5 }}>
                          <CashIcon size={14} style={{ display: 'inline', marginRight: 4, verticalAlign: 'middle' }} /> {e.payment_mode || '—'}
                        </span>
                      </td>
                      <td style={{ fontSize: '0.78rem', color: 'var(--text-secondary)' }}>{e.note || '—'}</td>
                      <td>
                        <button className="btn btn-secondary btn-sm" style={{ color: 'var(--danger)', borderColor: 'var(--danger-dim)' }} onClick={() => handleExpenseDelete(e.id)}>
                          ✕ Delete
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        ) : (
          <>
            <div className="data-table-wrap">
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Date</th>
                    <th>Invoice #</th>
                    <th>Customer / Supplier</th>
                    <th>Type</th>
                    <th>Amount</th>
                    <th>Method</th>
                    <th>Reference</th>
                  </tr>
                </thead>
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
                    <tr key={p.id}>
                      <td>{p.date ? new Date(p.date).toLocaleDateString('en-IN') : '—'}</td>
                      <td className="td-mono">{p.invoice_number || p.invoice_ref || '—'}</td>
                      <td className="td-primary">{p.party_name || p.customer_name || p.supplier_name || '—'}</td>
                      <td>
                        <span className={`badge ${p.type === 'received' ? 'badge-success' : 'badge-accent'}`}>
                          {p.type === 'received' ? '↓ Received' : '↑ Made'}
                        </span>
                      </td>
                      <td style={{ fontWeight: 600, color: p.type === 'received' ? 'var(--success)' : 'var(--danger)' }}>
                        {p.type === 'received' ? '+' : '-'}{fmt(p.amount)}
                      </td>
                      <td>
                        <span style={{ display: 'inline-flex', alignItems: 'center', gap: 5 }}>
                          <CashIcon size={14} style={{ display: 'inline', marginRight: 4, verticalAlign: 'middle' }} /> {p.method || '—'}
                        </span>
                      </td>
                      <td className="td-mono" style={{ fontSize: '0.78rem', color: 'var(--text-muted)' }}>{p.reference || '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            {/* Running totals bar */}
            <div className="card mt-6">
              <div className="flex items-center justify-between" style={{ flexWrap: 'wrap', gap: 16 }}>
                <div style={{ display: 'flex', gap: 32 }}>
                  <div>
                    <div className="stat-label">Total Received</div>
                    <div style={{ fontSize: '1.3rem', fontWeight: 700, color: 'var(--success)' }}>{fmt(totalReceived)}</div>
                  </div>
                  <div>
                    <div className="stat-label">Total Made</div>
                    <div style={{ fontSize: '1.3rem', fontWeight: 700, color: 'var(--danger)' }}>{fmt(totalMade)}</div>
                  </div>
                  <div>
                    <div className="stat-label">Net Balance</div>
                    <div style={{ fontSize: '1.3rem', fontWeight: 700, color: net >= 0 ? 'var(--success)' : 'var(--danger)' }}>
                      {net >= 0 ? '+' : ''}{fmt(Math.abs(net))}
                    </div>
                  </div>
                </div>
                <div style={{ flex: 1, maxWidth: 300 }}>
                  <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)', marginBottom: 6 }}>
                    Received vs Made
                  </div>
                  <div className="progress" style={{ height: 8 }}>
                    <div
                      className="progress-bar success"
                      style={{ width: `${totalReceived + totalMade > 0 ? (totalReceived / (totalReceived + totalMade)) * 100 : 0}%` }}
                    />
                  </div>
                </div>
              </div>
            </div>
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
                    <select className="form-select" value={form.type} onChange={e => setField('type', e.target.value)}>
                      <option value="received">Received (from customer)</option>
                      <option value="made">Made (to supplier)</option>
                    </select>
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
                    <select className="form-select" value={form.method} onChange={e => setField('method', e.target.value)}>
                      <option value="Cash"><CashIcon size={14} style={{ marginRight: 6, display: 'inline-block', verticalAlign: 'middle' }} /> Cash</option>
                      <option value="UPI"><PhoneIcon size={14} style={{ marginRight: 6, display: 'inline-block', verticalAlign: 'middle' }} /> UPI</option>
                      <option value="Bank"><WarehouseIcon size={14} style={{ marginRight: 6, display: 'inline-block', verticalAlign: 'middle' }} /> Bank Transfer</option>
                      <option value="Cheque"><BillsIcon size={14} style={{ marginRight: 6, display: 'inline-block', verticalAlign: 'middle' }} /> Cheque</option>
                    </select>
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
                    <select className="form-select" value={expenseForm.category} onChange={e => setExpenseField('category', e.target.value)}>
                      <option value="Rent">Rent</option>
                      <option value="Utilities">Utilities (Power, Water, Net)</option>
                      <option value="Salaries & Wages">Salaries & Wages</option>
                      <option value="Marketing & Advertising">Marketing & Ads</option>
                      <option value="Office Supplies">Office Supplies</option>
                      <option value="Travel & Conveyance">Travel & Conveyance</option>
                      <option value="Repair & Maintenance">Repair & Maintenance</option>
                      <option value="Others">Others</option>
                    </select>
                  </div>
                </div>

                <div className="grid grid-2 gap-3 mb-4">
                  <div className="form-group">
                    <label className="form-label">Expense Type</label>
                    <select className="form-select" value={expenseForm.expense_type} onChange={e => setExpenseField('expense_type', e.target.value)}>
                      <option value="Indirect">Indirect (Operating/Office Overhead)</option>
                      <option value="Direct">Direct (Cost of Production/Goods)</option>
                    </select>
                  </div>
                  <div className="form-group">
                    <label className="form-label">Payment Mode</label>
                    <select className="form-select" value={expenseForm.payment_mode} onChange={e => setExpenseField('payment_mode', e.target.value)}>
                      <option value="Cash"><CashIcon size={14} style={{ marginRight: 6, display: 'inline-block', verticalAlign: 'middle' }} /> Cash</option>
                      <option value="UPI"><PhoneIcon size={14} style={{ marginRight: 6, display: 'inline-block', verticalAlign: 'middle' }} /> UPI</option>
                      <option value="Bank"><WarehouseIcon size={14} style={{ marginRight: 6, display: 'inline-block', verticalAlign: 'middle' }} /> Bank Transfer</option>
                    </select>
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
    </AppLayout>
  )
}
