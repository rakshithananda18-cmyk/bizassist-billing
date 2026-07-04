import { useState, useEffect, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../contexts/AuthContext'
import { useDialog } from '../contexts/DialogContext'
import { logger } from '../utils/logger'
import { API_BASE } from '../config'
import { PageHeader, Section } from '../components/ui'
import { Icon } from '../components/icons'

function fmtAmount(n) {
  if (!n && n !== 0) return '—'
  if (n >= 100000) return '₹' + (n / 100000).toFixed(1) + 'L'
  if (n >= 1000)   return '₹' + Math.round(n / 1000) + 'k'
  return '₹' + Math.round(n)
}

function fmtFull(n) {
  if (!n && n !== 0) return '—'
  return '₹' + Number(n).toLocaleString('en-IN')
}

function daysUntil(dateStr) {
  if (!dateStr) return null
  const d = new Date(dateStr)
  if (isNaN(d)) return null
  return Math.ceil((d - Date.now()) / 86400000)
}

export default function Alerts() {
  const { authFetch } = useAuth()
  const { showConfirm } = useDialog()
  const navigate = useNavigate()

  const [loading, setLoading] = useState(true)
  const [data, setData] = useState({ invoices: [], inventory: [], summary: {} })

  // Alert config state
  const [config, setConfig] = useState(null)
  const [form, setForm] = useState({
    active: false,
    email: '',
    whatsapp_number: '',
    alert_overdue: true,
    alert_low_stock: true,
    alert_expiry: true,
    alert_daily_summary: true,
    low_stock_threshold: 10,
    expiry_days_threshold: 30,
  })
  const [saveStatus, setSaveStatus] = useState('')
  const [savingConfig, setSavingConfig] = useState(false)
  const [tab, setTab] = useState('live')  // 'live' | 'config' | 'memory'

  // Memory distillation state
  const [memoryRunning, setMemoryRunning] = useState(false)
  const [memoryStatus, setMemoryStatus] = useState('')   // '' | 'success' | 'error'
  const [memoryFacts, setMemoryFacts] = useState(null)   // null = not loaded yet

  // intent set -> deterministic /intent (0 AI tokens); else natural-language AI query
  function sendChip(query, intent) {
    sessionStorage.setItem('prefill_query', query)
    window.dispatchEvent(new CustomEvent('ai-shortcut', { detail: { query, intent, label: query } }))
  }

  // Tier-3 gated action -> opens the preview/confirm modal in the assistant
  function sendAction(action, label, params) {
    window.dispatchEvent(new CustomEvent('ai-shortcut', { detail: { action, label, params } }))
  }

  useEffect(() => {
    loadAll()
  }, [])

  async function loadAll() {
    setLoading(true)
    try {
      const [dbRes, summaryRes, alertConfigRes] = await Promise.all([
        authFetch(`${API_BASE}/database`),
        authFetch(`${API_BASE}/dashboard-summary`),
        authFetch(`${API_BASE}/alerts/config`),
      ])
      const db = dbRes.ok ? await dbRes.json() : {}
      const summary = summaryRes.ok ? await summaryRes.json() : {}
      const alertCfg = alertConfigRes.ok ? await alertConfigRes.json() : {}

      setData({
        invoices: db.invoices || [],
        inventory: db.inventory || [],
        summary,
      })

      if (alertCfg.configured) {
        setConfig(alertCfg)
        setForm({
          active: alertCfg.active ?? true,
          email: alertCfg.email || '',
          whatsapp_number: alertCfg.whatsapp_number || '',
          alert_overdue: alertCfg.alert_overdue ?? true,
          alert_low_stock: alertCfg.alert_low_stock ?? true,
          alert_expiry: alertCfg.alert_expiry ?? true,
          alert_daily_summary: alertCfg.alert_daily_summary ?? true,
          low_stock_threshold: alertCfg.low_stock_threshold ?? 10,
          expiry_days_threshold: alertCfg.expiry_days_threshold ?? 30,
        })
      }
    } catch (e) {
      logger.error('Alerts load failed:', e)
    } finally {
      setLoading(false)
    }
  }

  async function saveConfig(e) {
    e.preventDefault()
    setSavingConfig(true)
    setSaveStatus('')
    try {
      const res = await authFetch(`${API_BASE}/alerts/config`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(form),
      })
      if (res.ok) {
        setSaveStatus('✓ Saved')
        setConfig({ configured: true, ...form })
        setTimeout(() => setSaveStatus(''), 3000)
      } else {
        setSaveStatus('✗ Failed to save')
      }
    } catch {
      setSaveStatus('✗ Error saving')
    } finally {
      setSavingConfig(false)
    }
  }

  async function runMemoryDistillation() {
    setMemoryRunning(true)
    setMemoryStatus('')
    try {
      const res = await authFetch(`${API_BASE}/alerts/test/memory_distillation`, { method: 'POST' })
      if (res.ok) {
        setMemoryStatus('success')
        // Auto-load updated facts
        await loadMemoryFacts()
      } else {
        setMemoryStatus('error')
      }
    } catch {
      setMemoryStatus('error')
    } finally {
      setMemoryRunning(false)
    }
  }

  async function loadMemoryFacts() {
    try {
      const res = await authFetch(`${API_BASE}/alerts/memory-facts`)
      if (res.ok) {
        const data = await res.json()
        setMemoryFacts(data.facts || [])
      }
    } catch (e) {
      logger.error('Failed to load memory facts:', e)
    }
  }

  async function deleteFact(id) {
    if (id == null) return
    if (!(await showConfirm('Delete this memory? The weekly job may re-derive it if the pattern still holds.'))) return
    try {
      const res = await authFetch(`${API_BASE}/alerts/memory-facts/${id}`, { method: 'DELETE' })
      if (res.ok) setMemoryFacts(prev => (prev || []).filter(f => f.id !== id))
    } catch (e) {
      logger.error('Failed to delete fact:', e)
    }
  }

  // Compute alert buckets from data
  const { invoices, inventory, summary } = data

  const overdueInvoices = invoices.filter(inv => (inv.status || '').toLowerCase() === 'overdue')
  const pendingInvoices = invoices.filter(inv => (inv.status || '').toLowerCase() === 'pending')

  const thresh = form.expiry_days_threshold || 30
  const stockThresh = form.low_stock_threshold || 10

  const expiringItems = inventory.filter(item => {
    const days = daysUntil(item.expiry_date || item.expiry)
    return days !== null && days >= 0 && days <= thresh
  }).sort((a, b) => {
    const da = daysUntil(a.expiry_date || a.expiry) ?? 999
    const db2 = daysUntil(b.expiry_date || b.expiry) ?? 999
    return da - db2
  })

  const expiredItems = inventory.filter(item => {
    const days = daysUntil(item.expiry_date || item.expiry)
    return days !== null && days < 0
  })

  const lowStockItems = inventory.filter(item =>
    item.stock !== null && item.stock !== undefined && Number(item.stock) <= stockThresh
  ).sort((a, b) => Number(a.stock) - Number(b.stock))

  const totalAlerts =
    overdueInvoices.length +
    expiringItems.length +
    expiredItems.length +
    lowStockItems.length

  if (loading) {
    return (
      <>
        <PageHeader title="Alerts" subtitle="Loading..." />
        <div className="widget">
          <div className="vskel" /><div className="vskel" /><div className="vskel" />
        </div>
      </>
    )
  }

  const isEmpty = invoices.length === 0 && inventory.length === 0

  return (
    <>
      {/* HEADER */}
      <PageHeader
        title={<>Alerts{totalAlerts > 0 && <span className="vbadge" style={{ background: 'rgba(192,42,42,0.15)', color: '#c02a2a' }}>{totalAlerts}</span>}</>}
        subtitle="Business health monitoring"
        actions={
          <>
            <button
              className="chip"
              style={{ opacity: tab === 'live' ? 1 : 0.55, fontWeight: tab === 'live' ? 700 : 400 }}
              onClick={() => setTab('live')}
            >
              Live Alerts
            </button>
            <button
              className="chip"
              style={{ opacity: tab === 'memory' ? 1 : 0.55, fontWeight: tab === 'memory' ? 700 : 400, display: 'inline-flex', alignItems: 'center', gap: 5 }}
              onClick={() => { setTab('memory'); if (!memoryFacts) loadMemoryFacts() }}
            >
              <Icon name="memory" size={13} /> Memory
            </button>
            <button
              className="chip"
              style={{ opacity: tab === 'config' ? 1 : 0.55, fontWeight: tab === 'config' ? 700 : 400, display: 'inline-flex', alignItems: 'center', gap: 5 }}
              onClick={() => setTab('config')}
            >
              <Icon name="settings" size={13} /> Configure
            </button>
          </>
        }
      />

      {/* SUMMARY STRIP */}
      {tab === 'live' && (
        <>
          <div className="vsummary-strip" style={{ marginBottom: 16 }}>
            <div className="vsummary-card" style={{ borderLeftColor: '#c02a2a' }} onClick={() => sendChip('List all overdue invoices with amounts and due dates', 'overdue_list')}>
              <div className="vsummary-label">Overdue</div>
              <div className="vsummary-value" style={{ color: '#c02a2a' }}>{overdueInvoices.length}</div>
              <div className="vsummary-sub">{fmtAmount(summary.overdue_amount)} at risk</div>
            </div>
            <div className="vsummary-card" style={{ borderLeftColor: '#c97c22' }} onClick={() => sendChip('List all pending invoices awaiting payment', 'pending_list')}>
              <div className="vsummary-label">Pending</div>
              <div className="vsummary-value">{pendingInvoices.length}</div>
              <div className="vsummary-sub">invoices awaiting</div>
            </div>
            <div className="vsummary-card" style={{ borderLeftColor: '#9b6ec9' }} onClick={() => sendChip(`Which products are expiring within ${thresh} days?`, 'expiring_soon')}>
              <div className="vsummary-label">Expiring Soon</div>
              <div className="vsummary-value" style={{ color: expiringItems.length > 0 ? '#9b6ec9' : undefined }}>
                {expiringItems.length}
              </div>
              <div className="vsummary-sub">within {thresh} days</div>
            </div>
            <div className="vsummary-card" style={{ borderLeftColor: '#4a90c9' }} onClick={() => sendChip(`Which products have low stock (${stockThresh} units or fewer) and need reordering?`, 'low_stock')}>
              <div className="vsummary-label">Low Stock</div>
              <div className="vsummary-value" style={{ color: lowStockItems.length > 0 ? '#4a90c9' : undefined }}>
                {lowStockItems.length}
              </div>
              <div className="vsummary-sub">≤ {stockThresh} units</div>
            </div>
          </div>

          {/* OVERDUE INVOICES */}
          {overdueInvoices.length > 0 && (
            <Section
              title="Overdue Invoices"
              count={overdueInvoices.length}
              icon={<Icon name="alert" size={16} />}
              collapsible
              noPad
              style={{ marginBottom: 12 }}
              actions={
                <button
                  className="chip"
                  style={{ fontSize: 11, padding: '3px 10px', display: 'inline-flex', alignItems: 'center', gap: 5 }}
                  onClick={() => sendAction('send_payment_reminders', 'Send payment reminders')}
                  title="Preview and log reminder drafts for overdue customers"
                >
                  <Icon name="bell" size={12} /> Send reminders
                </button>
              }
            >
              <div className="vtable-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>Customer</th>
                      <th>Invoice</th>
                      <th>Amount</th>
                      <th>Due</th>
                      <th></th>
                    </tr>
                  </thead>
                  <tbody>
                    {overdueInvoices.slice(0, 15).map((inv, i) => (
                      <tr key={inv.id || i}>
                        <td style={{ fontWeight: 600 }}>{inv.customer || '—'}</td>
                        <td style={{ color: 'var(--secondary-text)', fontFamily: 'monospace', fontSize: 12 }}>
                          {inv.invoice_id || '—'}
                        </td>
                        <td style={{ fontWeight: 700, color: '#c02a2a' }}>{fmtFull(inv.amount)}</td>
                        <td style={{ color: 'var(--secondary-text)', fontSize: 13 }}>{inv.due_date || '—'}</td>
                        <td>
                          <button
                            className="chip"
                            style={{ fontSize: 11, padding: '2px 8px' }}
                            onClick={() => sendChip(`Follow up with ${inv.customer} about overdue invoice ${inv.invoice_id || ''}`)}
                          >
                            Ask AI →
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </Section>
          )}

          {/* EXPIRING ITEMS */}
          {(expiringItems.length > 0 || expiredItems.length > 0) && (
            <Section
              title="Expiry Alerts"
              icon={<Icon name="clock" size={16} />}
              collapsible
              noPad
              style={{ marginBottom: 12 }}
              actions={
                <>
                  {expiredItems.length > 0 && (
                    <span className="vpill" style={{ color: '#c02a2a', background: 'rgba(192,42,42,0.10)' }}>
                      {expiredItems.length} expired
                    </span>
                  )}
                  {expiringItems.length > 0 && (
                    <span className="vpill" style={{ color: '#9b6ec9', background: 'rgba(155,110,201,0.10)' }}>
                      {expiringItems.length} expiring soon
                    </span>
                  )}
                </>
              }
            >
              <div className="vtable-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>Product</th>
                      <th>Stock</th>
                      <th>Expiry Date</th>
                      <th>Status</th>
                      <th></th>
                    </tr>
                  </thead>
                  <tbody>
                    {[...expiredItems, ...expiringItems].slice(0, 20).map((item, i) => {
                      const expDate = item.expiry_date || item.expiry
                      const days = daysUntil(expDate)
                      const expired = days !== null && days < 0
                      return (
                        <tr key={item.id || i}>
                          <td style={{ fontWeight: 600 }}>{item.product || item.product_name || '—'}</td>
                          <td style={{ fontFamily: 'monospace', fontSize: 13 }}>{item.stock ?? '—'}</td>
                          <td style={{ fontSize: 13 }}>{expDate || '—'}</td>
                          <td>
                            {expired ? (
                              <span className="vpill" style={{ color: '#c02a2a', background: 'rgba(192,42,42,0.10)' }}>
                                Expired {Math.abs(days)}d ago
                              </span>
                            ) : (
                              <span className="vpill" style={{ color: '#9b6ec9', background: 'rgba(155,110,201,0.10)' }}>
                                {days}d left
                              </span>
                            )}
                          </td>
                          <td>
                            <button
                              className="chip"
                              style={{ fontSize: 11, padding: '2px 8px' }}
                              onClick={() => sendChip(`What should I do with ${item.product || item.product_name} that ${expired ? 'expired' : 'expires in ' + days + ' days'}?`)}
                            >
                              Ask AI →
                            </button>
                          </td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </div>
            </Section>
          )}

          {/* LOW STOCK ITEMS */}
          {lowStockItems.length > 0 && (
            <Section
              title="Low Stock"
              count={lowStockItems.length}
              icon={<Icon name="package" size={16} />}
              collapsible
              noPad
              style={{ marginBottom: 12 }}
            >
              <div className="vtable-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>Product</th>
                      <th>Stock</th>
                      <th>Supplier</th>
                      <th></th>
                    </tr>
                  </thead>
                  <tbody>
                    {lowStockItems.slice(0, 20).map((item, i) => (
                      <tr key={item.id || i}>
                        <td style={{ fontWeight: 600 }}>{item.product || item.product_name || '—'}</td>
                        <td>
                          <span className="vpill" style={{
                            color: Number(item.stock) === 0 ? '#c02a2a' : '#4a90c9',
                            background: Number(item.stock) === 0 ? 'rgba(192,42,42,0.10)' : 'rgba(74,144,201,0.10)'
                          }}>
                            {item.stock} units
                          </span>
                        </td>
                        <td style={{ color: 'var(--secondary-text)', fontSize: 13 }}>{item.supplier || '—'}</td>
                        <td>
                          <button
                            className="chip"
                            style={{ fontSize: 11, padding: '2px 8px' }}
                            onClick={() => sendChip(`Reorder recommendation for ${item.product || item.product_name} — only ${item.stock} units left`)}
                          >
                            Ask AI →
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </Section>
          )}

          {/* ALL CLEAR */}
          {totalAlerts === 0 && !isEmpty && (
            <div className="vempty">
              <div className="vempty-icon">✓</div>
              <div className="vempty-title">All clear!</div>
              <div className="vempty-sub">No overdue invoices, expiring products, or low stock items.</div>
            </div>
          )}

          {isEmpty && (
            <div className="vempty">
              <div className="vempty-icon"><Icon name="bell" size={36} /></div>
              <div className="vempty-title">No data yet</div>
              <div className="vempty-sub">Upload invoices or inventory to monitor business alerts.</div>
              <button
                className="chip upload-btn-highlight"
                style={{ marginTop: 14 }}
                onClick={() => navigate('/upload')}
              >
                + Upload data
              </button>
            </div>
          )}
        </>
      )}

      {/* ALERT CONFIG TAB */}
      {tab === 'config' && (
        <div className="widget" style={{ maxWidth: 540 }}>
          <div className="widget-title" style={{ marginBottom: 16 }}>Alert Notification Settings</div>
          <form onSubmit={saveConfig} style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>

            {/* Active toggle */}
            <label style={{ display: 'flex', alignItems: 'center', gap: 10, cursor: 'pointer' }}>
              <input
                type="checkbox"
                checked={form.active}
                onChange={e => setForm(f => ({ ...f, active: e.target.checked }))}
                style={{ width: 16, height: 16, accentColor: 'var(--accent-color)' }}
              />
              <span style={{ fontWeight: 600, fontSize: 14 }}>Enable alerts</span>
            </label>

            {/* Email */}
            <div>
              <label style={{ fontSize: 12, color: 'var(--secondary-text)', display: 'block', marginBottom: 4 }}>Email address</label>
              <input
                type="email"
                className="vchat-input"
                placeholder="you@example.com"
                value={form.email}
                onChange={e => setForm(f => ({ ...f, email: e.target.value }))}
                style={{ width: '100%', padding: '8px 12px', borderRadius: 8, border: '1px solid var(--border-color)', background: 'var(--card-color)', color: 'var(--text-color)', fontSize: 14 }}
              />
            </div>

            {/* WhatsApp */}
            <div>
              <label style={{ fontSize: 12, color: 'var(--secondary-text)', display: 'block', marginBottom: 4 }}>WhatsApp number</label>
              <input
                type="tel"
                className="vchat-input"
                placeholder="+91 98765 43210"
                value={form.whatsapp_number}
                onChange={e => setForm(f => ({ ...f, whatsapp_number: e.target.value }))}
                style={{ width: '100%', padding: '8px 12px', borderRadius: 8, border: '1px solid var(--border-color)', background: 'var(--card-color)', color: 'var(--text-color)', fontSize: 14 }}
              />
            </div>

            {/* Alert type toggles */}
            <div style={{ borderTop: '1px solid var(--border-color)', paddingTop: 12 }}>
              <div style={{ fontSize: 12, color: 'var(--secondary-text)', marginBottom: 10, fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.06em' }}>Alert types</div>
              {[
                { key: 'alert_overdue', label: 'Overdue invoice alerts', icon: <Icon name="alert" size={14} style={{ color: 'var(--danger-color, #ef4444)' }} /> },
                { key: 'alert_low_stock', label: 'Low stock alerts', icon: <Icon name="package" size={14} /> },
                { key: 'alert_expiry', label: 'Product expiry alerts', icon: <Icon name="clock" size={14} /> },
                { key: 'alert_daily_summary', label: 'Daily business summary', icon: <Icon name="chart" size={14} /> },
              ].map(({ key, label, icon }) => (
                <label key={key} style={{ display: 'flex', alignItems: 'center', gap: 10, cursor: 'pointer', marginBottom: 8 }}>
                  <input
                    type="checkbox"
                    checked={form[key]}
                    onChange={e => setForm(f => ({ ...f, [key]: e.target.checked }))}
                    style={{ width: 16, height: 16, accentColor: 'var(--accent-color)' }}
                  />
                  <span style={{ fontSize: 14, display: 'inline-flex', alignItems: 'center', gap: 6 }}>
                    {icon}
                    {label}
                  </span>
                </label>
              ))}
            </div>

            {/* Threshold config */}
            <div style={{ borderTop: '1px solid var(--border-color)', paddingTop: 12, display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
              <div>
                <label style={{ fontSize: 12, color: 'var(--secondary-text)', display: 'block', marginBottom: 4 }}>
                  Low stock threshold (units)
                </label>
                <input
                  type="number"
                  min={1}
                  max={500}
                  value={form.low_stock_threshold}
                  onChange={e => setForm(f => ({ ...f, low_stock_threshold: Number(e.target.value) }))}
                  style={{ width: '100%', padding: '8px 12px', borderRadius: 8, border: '1px solid var(--border-color)', background: 'var(--card-color)', color: 'var(--text-color)', fontSize: 14 }}
                />
              </div>
              <div>
                <label style={{ fontSize: 12, color: 'var(--secondary-text)', display: 'block', marginBottom: 4 }}>
                  Expiry warning (days ahead)
                </label>
                <input
                  type="number"
                  min={1}
                  max={365}
                  value={form.expiry_days_threshold}
                  onChange={e => setForm(f => ({ ...f, expiry_days_threshold: Number(e.target.value) }))}
                  style={{ width: '100%', padding: '8px 12px', borderRadius: 8, border: '1px solid var(--border-color)', background: 'var(--card-color)', color: 'var(--text-color)', fontSize: 14 }}
                />
              </div>
            </div>

            <div style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
              <button
                type="submit"
                className="chip upload-btn-highlight"
                disabled={savingConfig}
                style={{ padding: '8px 20px', fontSize: 14 }}
              >
                {savingConfig ? 'Saving…' : 'Save settings'}
              </button>
              {saveStatus && (
                <span style={{ fontSize: 13, color: saveStatus.startsWith('✓') ? '#27864a' : '#c02a2a', fontWeight: 600 }}>
                  {saveStatus}
                </span>
              )}
            </div>
          </form>
        </div>
      )}

      {/* MEMORY TAB */}
      {tab === 'memory' && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>

          {/* Run button card */}
          <div className="widget" style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: 12 }}>
            <div>
              <div className="widget-title" style={{ marginBottom: 4, display: 'flex', alignItems: 'center', gap: 8 }}>
                <Icon name="memory" size={18} style={{ color: 'var(--accent-color)' }} />
                Business Memory Distillation
              </div>
              <div style={{ fontSize: 13, color: 'var(--secondary-text)', maxWidth: 420 }}>
                Analyses your invoices, inventory, and chat history using AI to extract stable business patterns.
                Runs automatically every Sunday — or trigger it manually below.
              </div>
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
              {memoryStatus === 'success' && (
                <span style={{ fontSize: 13, color: '#27864a', fontWeight: 600, display: 'inline-flex', alignItems: 'center', gap: 5 }}>
                  <Icon name="check" size={14} /> Distillation complete
                </span>
              )}
              {memoryStatus === 'error' && (
                <span style={{ fontSize: 13, color: '#c02a2a', fontWeight: 600, display: 'inline-flex', alignItems: 'center', gap: 5 }}>
                  <Icon name="x" size={14} /> Failed — check logs
                </span>
              )}
              <button
                id="run-memory-distillation-btn"
                className="chip upload-btn-highlight"
                style={{ padding: '9px 20px', fontSize: 14, display: 'inline-flex', alignItems: 'center', gap: 8, opacity: memoryRunning ? 0.7 : 1 }}
                onClick={runMemoryDistillation}
                disabled={memoryRunning}
              >
                {memoryRunning ? (
                  <>
                    <span style={{ display: 'inline-block', width: 14, height: 14, border: '2px solid currentColor', borderTopColor: 'transparent', borderRadius: '50%', animation: 'spin 0.7s linear infinite' }} />
                    Analysing…
                  </>
                ) : (
                  <><Icon name="memory" size={15} /> Run Now</>
                )}
              </button>
            </div>
          </div>

          {/* Facts display */}
          {memoryFacts === null && (
            <div className="widget" style={{ textAlign: 'center', color: 'var(--secondary-text)', padding: '32px 0' }}>
              <div style={{ marginBottom: 8, opacity: 0.4 }}><Icon name="memory" size={36} /></div>
              <div style={{ fontWeight: 600 }}>No facts loaded yet</div>
              <div style={{ fontSize: 13, marginTop: 4 }}>Click "Run Now" to distil your first business memories.</div>
            </div>
          )}

          {memoryFacts !== null && memoryFacts.length === 0 && (
            <div className="widget" style={{ textAlign: 'center', color: 'var(--secondary-text)', padding: '32px 0' }}>
              <div style={{ marginBottom: 8, opacity: 0.4 }}><Icon name="chat" size={36} /></div>
              <div style={{ fontWeight: 600 }}>No facts distilled yet</div>
              <div style={{ fontSize: 13, marginTop: 4 }}>Click "Run Now" to analyse your business data and extract insights.</div>
            </div>
          )}

          {memoryFacts !== null && memoryFacts.length > 0 && (
            <div className="widget">
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 16 }}>
                <div className="widget-title" style={{ marginBottom: 0, display: 'flex', alignItems: 'center', gap: 8 }}>
                  <Icon name="memory" size={16} style={{ color: 'var(--accent-color)' }} />
                  Distilled Facts <span className="vbadge" style={{ background: 'rgba(99,102,241,0.12)', color: '#6366f1' }}>{memoryFacts.length}</span>
                </div>
                <div style={{ fontSize: 12, color: 'var(--secondary-text)' }}>Injected into every AI response automatically</div>
              </div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
                {memoryFacts.map((fact, i) => {
                  const catColors = {
                    payment_delay:      { bg: 'rgba(192,42,42,0.08)',   color: '#c02a2a'  },
                    sales_pattern:      { bg: 'rgba(39,134,74,0.08)',   color: '#27864a'  },
                    concentration_risk: { bg: 'rgba(201,124,34,0.10)',  color: '#c97c22'  },
                    cash_flow:          { bg: 'rgba(74,144,201,0.08)',  color: '#4a90c9'  },
                    inventory_risk:     { bg: 'rgba(155,110,201,0.10)', color: '#9b6ec9'  },
                    other:              { bg: 'rgba(100,100,100,0.08)', color: 'var(--secondary-text)' },
                  }
                  const c = catColors[fact.category] || catColors.other
                  return (
                    <div key={i} style={{
                      display: 'flex', alignItems: 'flex-start', gap: 12,
                      padding: '12px 14px', borderRadius: 10,
                      background: 'var(--bg-color)', border: '1px solid var(--border-color)'
                    }}>
                      <span className="vpill" style={{ background: c.bg, color: c.color, fontSize: 11, whiteSpace: 'nowrap', marginTop: 1 }}>
                        {fact.category?.replace(/_/g, ' ')}
                      </span>
                      <div style={{ flex: 1 }}>
                        <div style={{ fontSize: 14, lineHeight: 1.5 }}>{fact.fact_text}</div>
                        <div style={{ fontSize: 11, color: 'var(--secondary-text)', marginTop: 4 }}>
                          Confidence: {Math.round((fact.confidence || 1) * 100)}%
                          {fact.updated_at && <> · Updated {new Date(fact.updated_at).toLocaleDateString('en-IN')}</>}
                        </div>
                      </div>
                      <button
                        title="Delete this memory"
                        onClick={() => deleteFact(fact.id)}
                        style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'var(--secondary-text)', padding: 4, marginTop: 1, lineHeight: 0 }}
                      >
                        <Icon name="x" size={14} />
                      </button>
                    </div>
                  )
                })}
              </div>
            </div>
          )}
        </div>
      )}
    </>
  )
}
