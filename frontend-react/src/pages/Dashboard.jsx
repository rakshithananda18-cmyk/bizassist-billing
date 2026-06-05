import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../contexts/AuthContext'
import { API_BASE } from '../config'

// ── Helper ────────────────────────────────────────────────────────────
function fmt(n)   { return Number(n || 0).toLocaleString('en-IN') }
function fmtL(n)  { return `₹${(Number(n || 0) / 100000).toFixed(1)}L` }
function fmtK(n)  { return `₹${Math.round(Number(n || 0) / 1000)}k` }

// ── Donut SVG ─────────────────────────────────────────────────────────
function DonutChart({ paid, pending, overdue }) {
  const total = (paid + pending + overdue) || 1
  const r = 36, circ = 2 * Math.PI * r

  const paidPct  = paid    / total
  const pendPct  = pending / total
  const overPct  = Math.max(0, 1 - paidPct - pendPct)

  const paidDash   = paidPct  * circ
  const pendDash   = pendPct  * circ
  const overDash   = overPct  * circ
  const pendOffset = -(paidPct * circ)
  const overOffset = -((paidPct + pendPct) * circ)
  const healthPct  = total > 0 ? Math.round((paid / total) * 100) : 0

  return (
    <div style={{ position: 'relative', width: 68, height: 68, flexShrink: 0 }}>
      <svg width="68" height="68" viewBox="0 0 88 88" style={{ transform: 'rotate(-90deg)' }}>
        <circle cx="44" cy="44" r={r} fill="none" stroke="var(--border)" strokeWidth="10" />
        <circle cx="44" cy="44" r={r} fill="none" stroke="#3a9a5c" strokeWidth="10"
          strokeDasharray={`${paidDash} ${circ}`} strokeDashoffset="0" />
        <circle cx="44" cy="44" r={r} fill="none" stroke="#c97c22" strokeWidth="10"
          strokeDasharray={`${pendDash} ${circ}`} strokeDashoffset={pendOffset} />
        <circle cx="44" cy="44" r={r} fill="none" stroke="#c94242" strokeWidth="10"
          strokeDasharray={`${overDash} ${circ}`} strokeDashoffset={overOffset} />
      </svg>
      <div style={{
        position: 'absolute', inset: 0,
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        fontSize: 12, fontWeight: 700, color: 'var(--text)'
      }}>
        {healthPct}%
      </div>
    </div>
  )
}

// ── Bar row ───────────────────────────────────────────────────────────
function BarRow({ label, value, max, color = 'var(--accent)', onClick }) {
  const pct = Math.max(4, (value / Math.max(max, 1)) * 100)
  const short = label.length > 14 ? label.slice(0, 13) + '…' : label
  return (
    <div className="bar-row" onClick={onClick} title={label} style={{ cursor: onClick ? 'pointer' : 'default' }}>
      <div className="bar-label">{short}</div>
      <div className="bar-track">
        <div className="bar-fill" style={{ width: `${pct}%`, background: color }} />
      </div>
      <div className="bar-value">{fmtK(value)}</div>
    </div>
  )
}

// ── Stat card ─────────────────────────────────────────────────────────
function StatCard({ label, value, sub, color = 'var(--accent)' }) {
  return (
    <div className="stat-card" style={{ borderLeftColor: color }}>
      <div className="stat-label">{label}</div>
      <div className="stat-value">{value}</div>
      {sub && <div className="stat-sub">{sub}</div>}
    </div>
  )
}

// ── Alert row ─────────────────────────────────────────────────────────
function AlertRow({ icon, title, sub, color, onClick }) {
  return (
    <div className="alert-row" onClick={onClick} style={{ borderLeftColor: color }}>
      <span className="alert-icon">{icon}</span>
      <div className="alert-text">
        <strong>{title}</strong>
        <span>{sub}</span>
      </div>
      <span className="alert-arrow">›</span>
    </div>
  )
}

// ── Main Dashboard ────────────────────────────────────────────────────
export default function Dashboard() {
  const { authFetch, user } = useAuth()
  const navigate = useNavigate()

  const [summary,   setSummary]   = useState(null)
  const [customers, setCustomers] = useState([])
  const [loading,   setLoading]   = useState(true)
  const [error,     setError]     = useState('')

  useEffect(() => {
    async function load() {
      try {
        const [sRes, cRes] = await Promise.all([
          authFetch(`${API_BASE}/dashboard-summary`),
          authFetch(`${API_BASE}/top-customers`)
        ])
        if (!sRes.ok || !cRes.ok) throw new Error('Failed to load dashboard')
        const [s, c] = await Promise.all([sRes.json(), cRes.json()])
        setSummary(s)
        setCustomers(c)
      } catch (e) {
        setError('Could not load dashboard. Is the backend running?')
      } finally {
        setLoading(false)
      }
    }
    load()
  }, [])

  function goToChat(msg) {
    sessionStorage.setItem('prefill_query', msg)
    navigate('/chat')
  }

  if (loading) return <div className="page-loading">Loading dashboard...</div>
  if (error)   return <div className="page"><div className="error-box">{error}</div></div>

  const revenue    = summary.total_revenue    || 0
  const overdue    = summary.overdue_amount   || 0
  const pending    = summary.pending_invoices || 0
  const total      = summary.invoice_count    || 0
  const inventory  = summary.inventory_count  || 0

  // Estimate paid/pending/overdue invoice counts for donut
  const overdueCount = overdue > 0 && revenue > 0
    ? Math.round((overdue / revenue) * total) : 0
  const paidCount    = Math.max(0, total - pending - overdueCount)

  const AGING_COLORS = ['#c97c22', '#c95e22', '#c94242', '#962424']

  return (
    <div className="page">
      {/* Header */}
      <div className="page-header" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
        <div>
          <h1>Dashboard</h1>
          <p>{user?.business_name} — live business overview</p>
        </div>
        <button className="btn-secondary" onClick={() => window.location.reload()}>
          Refresh ⟳
        </button>
      </div>

      {/* Stat cards */}
      <div className="stat-grid">
        <StatCard
          label="Total Revenue"
          value={`₹${fmt(revenue)}`}
          sub={`${total} invoices`}
          color="var(--accent)"
        />
        <StatCard
          label="Overdue"
          value={`₹${fmt(overdue)}`}
          sub={`${overdueCount} invoice(s)`}
          color="#c94242"
        />
        <StatCard
          label="Pending"
          value={pending}
          sub="awaiting payment"
          color="#c97c22"
        />
        <StatCard
          label="Inventory"
          value={inventory}
          sub="products tracked"
          color="#3a9a5c"
        />
      </div>

      {/* Main grid */}
      <div className="dashboard-grid">

        {/* Revenue card + donut */}
        <div className="dash-card" style={{ cursor: 'pointer' }}
          onClick={() => goToChat('Give me a complete revenue breakdown — paid, pending and overdue')}>
          <div className="dash-card-header">
            <span className="dash-card-title">Revenue Health</span>
            <span className="dash-card-sub">Tap to analyse →</span>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 20, marginTop: 12 }}>
            <DonutChart paid={paidCount} pending={pending} overdue={overdueCount} />
            <div style={{ flex: 1 }}>
              <div style={{ fontSize: 26, fontWeight: 700 }}>{fmtL(revenue)}</div>
              <div style={{ fontSize: 12, color: 'var(--text-2)', marginTop: 4 }}>total tracked revenue</div>
              <div style={{ display: 'flex', gap: 12, marginTop: 10, fontSize: 11 }}>
                <span><span style={{ color: '#3a9a5c' }}>●</span> Paid</span>
                <span><span style={{ color: '#c97c22' }}>●</span> Pending</span>
                <span><span style={{ color: '#c94242' }}>●</span> Overdue</span>
              </div>
            </div>
          </div>
        </div>

        {/* Overdue card */}
        <div className="dash-card" style={{ cursor: 'pointer' }}
          onClick={() => goToChat('List all overdue invoices with amounts and due dates')}>
          <div className="dash-card-header">
            <span className="dash-card-title">Overdue Amount</span>
            <span className="dash-card-sub">Tap to see list →</span>
          </div>
          <div style={{ fontSize: 28, fontWeight: 700, color: '#c94242', marginTop: 12 }}>
            ₹{fmt(overdue)}
          </div>
          <div style={{ fontSize: 12, color: 'var(--text-2)', marginTop: 4 }}>
            {pending} pending · {overdueCount} overdue
          </div>
          <div style={{ marginTop: 14, height: 6, background: 'var(--accent-soft)', borderRadius: 3 }}>
            <div style={{
              height: '100%', borderRadius: 3, background: '#c94242',
              width: `${Math.min(100, revenue > 0 ? (overdue / revenue) * 100 : 0)}%`,
              transition: 'width 0.6s ease'
            }} />
          </div>
          <div style={{ fontSize: 11, color: 'var(--text-2)', marginTop: 4 }}>
            {revenue > 0 ? `${((overdue / revenue) * 100).toFixed(0)}% of total revenue at risk` : ''}
          </div>
        </div>

        {/* Top customers */}
        <div className="dash-card" style={{ cursor: 'pointer' }}
          onClick={() => goToChat('Who are my top customers by revenue? Give full details')}>
          <div className="dash-card-header">
            <span className="dash-card-title">Top Customers</span>
            <span className="dash-card-sub">View all →</span>
          </div>
          <div style={{ marginTop: 12, display: 'flex', flexDirection: 'column', gap: 8 }}>
            {customers.slice(0, 5).map((c, i) => (
              <BarRow
                key={c.customer}
                label={c.customer}
                value={c.total}
                max={customers[0]?.total || 1}
                color={['#c96442','#c97c22','#3a9a5c','#4a90c9','#9b6ec9'][i]}
              />
            ))}
            {customers.length === 0 && (
              <div style={{ color: 'var(--text-2)', fontSize: 12 }}>No customer data yet.</div>
            )}
          </div>
        </div>

        {/* Quick actions */}
        <div className="dash-card">
          <div className="dash-card-header">
            <span className="dash-card-title">Quick Actions</span>
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8, marginTop: 12 }}>
            <AlertRow icon="⏰" title="Expiry check"
              sub="Items expiring soon"   color="#c97c22"
              onClick={() => goToChat('Which medicines and products are expiring in the next 30 days?')} />
            <AlertRow icon="📦" title="Low stock"
              sub="Items needing reorder" color="#4a90c9"
              onClick={() => goToChat('Which products have low stock and need reordering?')} />
            <AlertRow icon="🔴" title="Overdue invoices"
              sub={`₹${fmt(overdue)} pending`} color="#c94242"
              onClick={() => goToChat('List all overdue invoices with amounts and due dates')} />
            <AlertRow icon="🏆" title="Top customers"
              sub={customers[0] ? `${customers[0].customer} leads` : 'See rankings'} color="#3a9a5c"
              onClick={() => goToChat('Who are my top 5 customers by revenue?')} />
            <AlertRow icon="🧠" title="Growth plan"
              sub="Full Q1 analysis"      color="var(--accent)"
              onClick={() => goToChat('Analyse my business and give me a growth plan')} />
          </div>
        </div>

      </div>
    </div>
  )
}
