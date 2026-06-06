import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../contexts/AuthContext'
import { API_BASE } from '../config'
import { useDialog } from '../contexts/DialogContext'
import { Spinner, PageHeader } from '../components/ui'
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

// Donut Chart Component
function DonutChart({ paid, pending, overdue, healthPct }) {
  const total = paid + pending + overdue || 1
  const r = 36, cx = 44, cy = 44, stroke = 10
  const circ = 2 * Math.PI * r

  const paidPct = paid / total
  const pendPct = pending / total
  const overPct = Math.max(0, 1 - paidPct - pendPct)

  const paidDash = paidPct * circ
  const pendDash = pendPct * circ
  const overDash = overPct * circ
  const pendOffset = -(paidPct * circ)
  const overOffset = -((paidPct + pendPct) * circ)

  return (
    <div className="ip-donut-wrap" style={{ position: 'relative', width: 88, height: 88, flexShrink: 0 }}>
      <svg width="88" height="88" viewBox="0 0 88 88" style={{ transform: 'rotate(-90deg)' }}>
        <circle cx={cx} cy={cy} r={r} fill="none" stroke="var(--border-color)" strokeWidth={stroke} />
        <circle cx={cx} cy={cy} r={r} fill="none" stroke="#3a9a5c" strokeWidth={stroke}
          strokeDasharray={`${paidDash} ${circ}`} strokeDashoffset={0} />
        <circle cx={cx} cy={cy} r={r} fill="none" stroke="#c97c22" strokeWidth={stroke}
          strokeDasharray={`${pendDash} ${circ}`} strokeDashoffset={pendOffset} />
        <circle cx={cx} cy={cy} r={r} fill="none" stroke="#c94242" strokeWidth={stroke}
          strokeDasharray={`${overDash} ${circ}`} strokeDashoffset={overOffset} />
      </svg>
      <div className="ip-donut-center" style={{ position: 'absolute', inset: 0, display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 13, fontWeight: 700, color: 'var(--text-color)' }}>
        {healthPct}%
      </div>
    </div>
  )
}

// Area Chart Component
function AreaChart({ trends, sendChip }) {
  if (!trends || !trends.length || (trends.length === 1 && trends[0].revenue === 0)) {
    return <div style={{ color: 'var(--secondary-text)', fontSize: 12, textAlign: 'center', padding: '50px 0', width: '100%' }}>No revenue trends recorded yet</div>
  }

  const maxVal = Math.max(...trends.map(t => t.revenue), 1)
  const width = 500
  const height = 150
  const padding = { top: 20, right: 20, bottom: 25, left: 50 }

  const chartWidth = width - padding.left - padding.right
  const chartHeight = height - padding.top - padding.bottom

  const points = trends.map((t, idx) => {
    const x = padding.left + (idx / Math.max(trends.length - 1, 1)) * chartWidth
    const y = padding.top + chartHeight - (t.revenue / maxVal) * chartHeight
    return { x, y, label: t.month, val: t.revenue }
  })

  const linePath = points.map((p, idx) => `${idx === 0 ? 'M' : 'L'} ${p.x} ${p.y}`).join(' ')
  const firstP = points[0]
  const lastP = points[points.length - 1]
  const areaPath = `${linePath} L ${lastP.x} ${padding.top + chartHeight} L ${firstP.x} ${padding.top + chartHeight} Z`

  const gridLines = []
  for (let i = 0; i <= 3; i++) {
    const y = padding.top + (i / 3) * chartHeight
    const val = maxVal - (i / 3) * maxVal
    gridLines.push(
      <g key={i}>
        <line x1={padding.left} y1={y} x2={width - padding.right} y2={y} stroke="var(--border-color)" strokeDasharray="3 3" />
        <text x={padding.left - 8} y={y + 4} fill="var(--secondary-text)" fontSize="9" textAnchor="end">₹{(val / 1000).toFixed(0)}k</text>
      </g>
    )
  }

  let labelInterval = 1
  if (trends.length > 18) {
    labelInterval = 4
  } else if (trends.length > 12) {
    labelInterval = 3
  } else if (trends.length > 6) {
    labelInterval = 2
  }

  return (
    <svg viewBox={`0 0 ${width} ${height}`} width="100%" height="100%" className="area-chart-svg">
      <defs>
        <linearGradient id="chart-area-grad" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="var(--accent-color)" stopOpacity="0.25" />
          <stop offset="100%" stopColor="var(--accent-color)" stopOpacity="0.0" />
        </linearGradient>
      </defs>
      {gridLines}
      {points.map((p, idx) => {
        if (idx % labelInterval === 0 || idx === points.length - 1) {
          return (
            <text key={idx} x={p.x} y={height - 6} fill="var(--secondary-text)" fontSize="9" textAnchor="middle">
              {p.label}
            </text>
          )
        }
        return null
      })}
      <path d={areaPath} fill="url(#chart-area-grad)" style={{ opacity: 0.85 }} />
      <path d={linePath} fill="none" stroke="var(--accent-color)" strokeWidth="2.5" strokeLinecap="round" className="chart-line-path" />
      {points.map((p, idx) => (
        <g key={idx} className="chart-dot-group" style={{ cursor: 'pointer' }} onClick={() => sendChip(`Tell me about revenue in ${p.label}`)}>
          <circle cx={p.x} cy={p.y} r="4" fill="var(--card-color)" stroke="var(--accent-color)" strokeWidth="2" className="chart-dot" />
          <circle cx={p.x} cy={p.y} r={12} fill="transparent" className="chart-dot-hitbox" />
          <title>{p.label}: {fmtFull(p.val)}</title>
        </g>
      ))}
    </svg>
  )
}

// Aging Bars Component
function AgingBars({ aging, sendChip }) {
  if (!aging || !aging.length || aging.every(a => a.amount === 0)) {
    return <div style={{ color: 'var(--secondary-text)', fontSize: 12, padding: '50px 0', textAlign: 'center', width: '100%' }}>No outstanding debt recorded</div>
  }
  const maxVal = Math.max(...aging.map(a => a.amount), 1)
  const colors = ['#c97c22', '#c95e22', '#c94242', '#962424']

  return aging.map((a, i) => {
    const pct = Math.max(2, (a.amount / maxVal) * 100)
    return (
      <div key={i} className="bar-row" onClick={() => sendChip(`Tell me about overdue payments in range ${a.range}`)}
        title={`${a.range} — ${fmtFull(a.amount)}`} style={{ cursor: 'pointer' }}>
        <div className="bar-label">{a.range}</div>
        <div className="bar-track">
          <div className="bar-fill" style={{ width: `${pct}%`, background: colors[i] }}></div>
        </div>
        <div className="bar-value">₹{(a.amount / 1000).toFixed(1)}k</div>
      </div>
    )
  })
}

// Customers Bar Chart Component
function CustomersBarChart({ customers, sendChip }) {
  if (!customers.length) {
    return <div style={{ color: 'var(--secondary-text)', fontSize: 12, padding: '8px 0' }}>No data yet</div>
  }
  const max = customers[0].total || 1
  const colors = ['#c96442', '#c97c22', '#3a9a5c', '#4a90c9', '#9b6ec9']

  return customers.slice(0, 5).map((c, i) => {
    const pct = Math.max(4, (c.total / max) * 100)
    const label = c.customer.length > 14 ? c.customer.slice(0, 13) + '…' : c.customer
    return (
      <div key={i} className="bar-row" onClick={() => sendChip(`Tell me about ${c.customer} payment status and invoices`)}
        title={`${c.customer} — ${fmtFull(c.total)}`} style={{ cursor: 'pointer' }}>
        <div className="bar-label">{label}</div>
        <div className="bar-track">
          <div className="bar-fill" style={{ width: `${pct}%`, background: colors[i] }}></div>
        </div>
        <div className="bar-value">₹{(c.total / 1000).toFixed(0)}k</div>
      </div>
    )
  })
}

export default function Dashboard() {
  const { authFetch } = useAuth()
  const { showAlert, showConfirm, showError } = useDialog()
  const navigate = useNavigate()
  const [summary, setSummary] = useState(null)
  const [customers, setCustomers] = useState([])
  const [charts, setCharts] = useState(null)
  const [loading, setLoading] = useState(true)
  const [uploading, setUploading] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    loadDashboard()
    const handleDataUpdated = () => {
      loadDashboard()
    }
    window.addEventListener('data-updated', handleDataUpdated)
    return () => {
      window.removeEventListener('data-updated', handleDataUpdated)
    }
  }, [])

  async function loadDashboard() {
    setLoading(true)
    try {
      const [summaryRes, customersRes, chartsRes] = await Promise.all([
        authFetch(`${API_BASE}/dashboard-summary`),
        authFetch(`${API_BASE}/top-customers`),
        authFetch(`${API_BASE}/dashboard-charts`)
      ])
      if (!summaryRes.ok || !customersRes.ok || !chartsRes.ok) throw new Error('Failed to load dashboard data')
      
      const [s, c, ch] = await Promise.all([
        summaryRes.json(),
        customersRes.json(),
        chartsRes.json()
      ])
      
      setSummary(s)
      setCustomers(c)
      setCharts(ch)
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  function sendChip(query) {
    sessionStorage.setItem('prefill_query', query)
    window.dispatchEvent(new CustomEvent('ai-shortcut', { detail: { query } }))
  }

  function handleQuickNav(tabName) {
    navigate(`/${tabName}`)
  }

  async function handleFileUpload(e) {
    const file = e.target.files[0]
    if (!file) return

    setUploading(true)
    const formData = new FormData()
    formData.append('file', file)

    try {
      const res = await authFetch(`${API_BASE}/upload`, {
        method: 'POST',
        body: formData,
      })
      const resp = await res.json()
      if (!res.ok || resp.error) {
        throw new Error(resp.error || 'Upload failed')
      }
      showAlert(`File type: ${resp.file_type}\nRows processed: ${resp.rows}`)
      loadDashboard()
      // Dispatch event to reload global stat cards in layout
      window.dispatchEvent(new CustomEvent('data-updated'))
    } catch (err) {
      showError(err, 'Upload failed')
    } finally {
      setUploading(false)
      e.target.value = ''
    }
  }

  if (loading) {
    return (
      <>
        <PageHeader title="Dashboard" subtitle="Your business at a glance" />
        <div className="widget">
          <div className="vskel"></div>
          <div className="vskel"></div>
        </div>
      </>
    )
  }

  if (error || !summary || !charts) {
    return (
      <div className="vempty">
        <div className="vempty-icon"><Icon name="chart" size={36} /></div>
        <div className="vempty-title">No data yet</div>
        <div className="vempty-sub">{error || 'Upload invoices or inventory to see your dashboard.'}</div>
        <button
          className="chip upload-btn-highlight"
          style={{ marginTop: 14 }}
          disabled={uploading}
          onClick={() => !uploading && document.getElementById('file-upload-dash').click()}
        >
          {uploading ? (
            <Spinner />
          ) : (
            '+ Upload data'
          )}
        </button>
        <input type="file" id="file-upload-dash" accept=".csv,.xlsx,.pdf" onChange={handleFileUpload} hidden />
      </div>
    )
  }

  const isDbEmpty = summary.invoice_count === 0 && summary.inventory_count === 0

  const totalVal = summary.invoice_count || 0
  const pendingVal = summary.pending_invoices || 0
  const overdueVal = Math.round((summary.overdue_amount || 0) / ((summary.total_revenue || 1) / totalVal)) || 0
  const paidVal = Math.max(0, totalVal - pendingVal - overdueVal)
  const collectedAmt = summary.total_revenue - summary.overdue_amount
  const healthPct = summary.total_revenue > 0 ? Math.round((collectedAmt / summary.total_revenue) * 100) : 0

  return (
    <>
      <PageHeader title="Dashboard" subtitle="Your business at a glance" style={{ marginBottom: 0 }} />

      {/* STAT STRIP */}
      <div className="vsummary-strip" style={{ marginBottom: 12 }}>
        <div className="vsummary-card" style={{ borderLeftColor: 'var(--accent-color)' }} onClick={() => sendChip('What is my total revenue?')}>
          <div className="vsummary-label">Total Revenue</div>
          <div className="vsummary-value">{fmtAmount(summary.total_revenue)}</div>
          <div className="vsummary-sub">{summary.invoice_count} invoices</div>
        </div>
        <div className="vsummary-card" style={{ borderLeftColor: '#c97c22' }} onClick={() => sendChip('List all pending invoices')}>
          <div className="vsummary-label">Pending</div>
          <div className="vsummary-value">{summary.pending_invoices}</div>
          <div className="vsummary-sub">invoices awaiting</div>
        </div>
        <div className="vsummary-card" style={{ borderLeftColor: '#c02a2a' }} onClick={() => sendChip('Show me all overdue invoices with amounts')}>
          <div className="vsummary-label">Overdue</div>
          <div className="vsummary-value" style={{ color: '#c02a2a' }}>{fmtAmount(summary.overdue_amount)}</div>
          <div className="vsummary-sub">needs recovery</div>
        </div>
        <div className="vsummary-card" style={{ borderLeftColor: '#3a9a5c' }} onClick={() => sendChip('How many products are in inventory?')}>
          <div className="vsummary-label">Inventory</div>
          <div className="vsummary-value">{summary.inventory_count}</div>
          <div className="vsummary-sub">products tracked</div>
        </div>
      </div>

      {/* QUICK ACTIONS */}
      <div className="widget" style={{ marginBottom: 12 }}>
        <div className="widget-title">Quick Actions</div>
        <div className="vactions" style={{ marginTop: 12, display: 'flex', gap: 10 }}>
          <button
            className={`vaction-btn ${isDbEmpty ? 'upload-btn-highlight' : ''}`}
            disabled={uploading}
            onClick={() => !uploading && document.getElementById('file-upload-dash').click()}
          >
            {uploading ? (
              <Spinner />
            ) : (
              <><span className="vaction-icon">↑</span> Upload Data</>
            )}
          </button>
          <input type="file" id="file-upload-dash" accept=".csv,.xlsx,.pdf" onChange={handleFileUpload} hidden />
          <button className="vaction-btn" onClick={() => sendChip('Generate a business summary')}>
            <span className="vaction-icon">✦</span> Business Summary
          </button>
          <button className="vaction-btn" onClick={() => handleQuickNav('invoices')}>
            <span className="vaction-icon">◫</span> View Invoices
          </button>
        </div>
      </div>

      {/* BUSINESS INSIGHTS & GRAPHS */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(300px, 1fr))', gap: 12 }}>
        {/* Donut Chart */}
        <div className="widget" style={{ display: 'flex', flexDirection: 'column', justifyContent: 'space-between', minHeight: 240 }}>
          <div className="widget-title" style={{ marginBottom: 16 }}>Revenue Distribution</div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 20, justifyContent: 'center', flex: 1 }}>
            <DonutChart paid={paidVal} pending={pendingVal} overdue={overdueVal} healthPct={healthPct} />
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8, fontSize: 13 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, cursor: 'pointer' }} onClick={() => sendChip('List all paid invoices')}>
                <span style={{ display: 'inline-block', width: 8, height: 8, borderRadius: '50%', background: '#3a9a5c' }}></span>
                <span style={{ color: 'var(--secondary-text)' }}>Paid:</span>
                <strong style={{ color: '#3a9a5c' }}>{paidVal} invoices</strong>
              </div>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, cursor: 'pointer' }} onClick={() => sendChip('List all pending invoices')}>
                <span style={{ display: 'inline-block', width: 8, height: 8, borderRadius: '50%', background: '#c97c22' }}></span>
                <span style={{ color: 'var(--secondary-text)' }}>Pending:</span>
                <strong style={{ color: '#c97c22' }}>{pendingVal} invoices</strong>
              </div>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, cursor: 'pointer' }} onClick={() => sendChip('List all overdue invoices')}>
                <span style={{ display: 'inline-block', width: 8, height: 8, borderRadius: '50%', background: '#c94242' }}></span>
                <span style={{ color: 'var(--secondary-text)' }}>Overdue:</span>
                <strong style={{ color: '#c94242' }}>{overdueVal} invoices</strong>
              </div>
            </div>
          </div>
        </div>

        {/* Top Customers Bar Chart */}
        <div className="widget" style={{ minHeight: 240, display: 'flex', flexDirection: 'column' }}>
          <div className="widget-title" style={{ marginBottom: 16 }}>Top Customers</div>
          <div className="ip-bars" style={{ flex: 1, display: 'flex', flexDirection: 'column', justifyContent: 'center' }}>
            <CustomersBarChart customers={customers} sendChip={sendChip} />
          </div>
        </div>
      </div>

      {/* SECOND ROW CHART GRID */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(300px, 1fr))', gap: 12, marginTop: 12 }}>
        {/* Monthly Revenue Trends */}
        <div className="widget" style={{ minHeight: 240, display: 'flex', flexDirection: 'column' }}>
          <div className="widget-title" style={{ marginBottom: 16 }}>Monthly Revenue Trend</div>
          <div id="monthly-trend-chart" style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', minHeight: 150 }}>
            <AreaChart trends={charts.monthly_revenue} sendChip={sendChip} />
          </div>
        </div>

        {/* Invoice Aging */}
        <div className="widget" style={{ minHeight: 240, display: 'flex', flexDirection: 'column' }}>
          <div className="widget-title" style={{ marginBottom: 16 }}>Overdue Debt Aging</div>
          <div id="aging-overview-chart" style={{ flex: 1, display: 'flex', flexDirection: 'column', justifyContent: 'center' }}>
            <AgingBars aging={charts.aging_overview} sendChip={sendChip} />
          </div>
        </div>
      </div>
    </>
  )
}
