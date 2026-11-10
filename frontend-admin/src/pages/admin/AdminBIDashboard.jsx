import { useState, useEffect, useCallback, useRef } from 'react'
import { Link } from 'react-router-dom'
import { useAuth } from '../../contexts/AuthContext'
import { API_BASE } from '../../config'
import { Icon } from '../../components/icons'
import { readableError } from '../../utils/httpErrors'
import '../../styles/infrastructure.css'

function formatCurrency(val) {
  if (val === null || val === undefined || isNaN(val)) return '₹0'
  return new Intl.NumberFormat('en-IN', {
    style: 'currency',
    currency: 'INR',
    maximumFractionDigits: 0
  }).format(val)
}

function StatCard({ label, value, sub, icon, trend, color }) {
  return (
    <div style={{
      background: 'var(--bg-2, #18191c)',
      border: '1px solid var(--border, rgba(255,255,255,0.08))',
      borderRadius: 14,
      padding: '20px',
      display: 'flex',
      flexDirection: 'column',
      gap: 10,
      boxShadow: '0 4px 20px rgba(0,0,0,0.15)'
    }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <span style={{ fontSize: 11, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.06em', color: 'var(--text-muted, #8e8e93)' }}>
          {label}
        </span>
        <div style={{
          width: 34, height: 34, borderRadius: 8,
          background: color ? `${color}18` : 'rgba(194, 113, 79, 0.12)',
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          color: color || 'var(--accent, #c2714f)'
        }}>
          <Icon name={icon || 'chart'} size={18} />
        </div>
      </div>
      <div style={{ fontSize: 26, fontWeight: 700, fontFamily: 'var(--font-mono, monospace)', color: 'var(--text-primary, #fff)' }}>
        {value}
      </div>
      {sub && (
        <div style={{ fontSize: 12, color: trend === 'up' ? '#38a169' : trend === 'down' ? '#e53e3e' : 'var(--text-muted, #8e8e93)', display: 'flex', alignItems: 'center', gap: 4 }}>
          {sub}
        </div>
      )}
    </div>
  )
}

export default function AdminBIDashboard() {
  const { authFetch } = useAuth()
  const [days, setDays] = useState(30)
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [refreshing, setRefreshing] = useState(false)
  const [hoveredPoint, setHoveredPoint] = useState(null)
  const mounted = useRef(true)

  const fetchBI = useCallback(async () => {
    setRefreshing(true)
    try {
      const res = await authFetch(`${API_BASE}/admin/bi-dashboard?days=${days}`)
      if (!res.ok) {
        const json = await res.json().catch(() => ({}))
        throw new Error(`HTTP ${res.status}: ${readableError(res.status, json)}`)
      }
      const json = await res.json()
      if (!mounted.current) return
      setData(json)
      setError(null)
    } catch (err) {
      if (mounted.current) setError(err.message || 'Failed to load BI analytics')
    } finally {
      if (mounted.current) {
        setLoading(false)
        setRefreshing(false)
      }
    }
  }, [authFetch, days])

  useEffect(() => {
    mounted.current = true
    fetchBI()
    return () => { mounted.current = false }
  }, [fetchBI])

  const kpis = data?.kpis || {}
  const daily = data?.daily_trends || []
  const payments = data?.payment_breakdown || []
  const topMerchants = data?.top_merchants || []

  // SVG Area Chart calculations
  const chartHeight = 220
  const chartWidth = 720
  const padding = 40
  const maxRevenue = Math.max(...daily.map(d => d.revenue), 1000)

  const points = daily.map((d, idx) => {
    const x = padding + (idx / Math.max(1, daily.length - 1)) * (chartWidth - padding * 2)
    const y = chartHeight - padding - (d.revenue / maxRevenue) * (chartHeight - padding * 2)
    return { x, y, ...d }
  })

  const pathD = points.length > 0
    ? `M ${points[0].x} ${points[0].y} ` + points.slice(1).map(p => `L ${p.x} ${p.y}`).join(' ')
    : ''

  const areaD = points.length > 0
    ? `${pathD} L ${points[points.length - 1].x} ${chartHeight - padding} L ${points[0].x} ${chartHeight - padding} Z`
    : ''

  return (
    <div className="admin-main">
      {/* Header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 28, flexWrap: 'wrap', gap: 16 }}>
        <div>
          <h1 style={{ fontSize: 26, fontWeight: 700, margin: 0, fontFamily: 'var(--font-serif, serif)', color: 'var(--text-primary, #fff)' }}>
            Business Intelligence & Analytics
          </h1>
          <p style={{ margin: '6px 0 0', color: 'var(--text-muted, #8e8e93)', fontSize: 13 }}>
            Platform sales velocity, merchant revenue distribution, and payment mode breakdown.
          </p>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          {/* Timeframe pill selector */}
          <div style={{ display: 'flex', background: 'var(--bg-2, #18191c)', border: '1px solid var(--border, rgba(255,255,255,0.08))', borderRadius: 10, padding: 3 }}>
            {[7, 30, 90].map(d => (
              <button
                key={d}
                type="button"
                onClick={() => setDays(d)}
                style={{
                  padding: '6px 14px',
                  borderRadius: 7,
                  border: 'none',
                  fontSize: 12,
                  fontWeight: 600,
                  cursor: 'pointer',
                  background: days === d ? 'var(--accent, #c2714f)' : 'transparent',
                  color: days === d ? '#fff' : 'var(--text-muted, #8e8e93)',
                  transition: 'all 0.2s ease'
                }}
              >
                {d} Days
              </button>
            ))}
          </div>

          <button
            type="button"
            onClick={fetchBI}
            disabled={refreshing}
            style={{
              display: 'flex', alignItems: 'center', gap: 6,
              padding: '8px 14px', borderRadius: 9,
              background: 'var(--bg-2, #18191c)', border: '1px solid var(--border, rgba(255,255,255,0.08))',
              color: 'var(--text-primary, #fff)', fontSize: 12, fontWeight: 600, cursor: 'pointer'
            }}
          >
            <Icon name="refresh" size={14} className={refreshing ? 'spinning' : ''} />
            {refreshing ? 'Refreshing…' : 'Refresh'}
          </button>
        </div>
      </div>

      {error && (
        <div style={{
          padding: '16px 20px', borderRadius: 12,
          background: 'rgba(229, 62, 62, 0.1)', border: '1px solid rgba(229, 62, 62, 0.3)',
          color: '#feb2b2', marginBottom: 24, fontSize: 13
        }}>
          <strong>Failed to load BI analytics:</strong> {error}
        </div>
      )}

      {/* Top Metric Cards */}
      <div style={{
        display: 'grid',
        gridTemplateColumns: 'repeat(auto-fit, minmax(210px, 1fr))',
        gap: 16,
        marginBottom: 28
      }}>
        <StatCard
          label="Total Gross Platform Sales"
          value={formatCurrency(kpis.total_revenue_all)}
          sub={`${days}-Day Window: ${formatCurrency(kpis.window_revenue)}`}
          icon="wallet"
          color="#c2714f"
        />
        <StatCard
          label="Total Invoices Rung"
          value={(kpis.total_invoices_all || 0).toLocaleString()}
          sub={`${days}-Day Window: ${(kpis.window_invoices || 0).toLocaleString()}`}
          icon="file"
          color="#3182ce"
        />
        <StatCard
          label="Average Order Value (AOV)"
          value={formatCurrency(kpis.average_order_value)}
          sub={`Recent: ${formatCurrency(kpis.window_average_order_value)}`}
          icon="chart"
          color="#38a169"
        />
        <StatCard
          label="Active Merchant Fleet"
          value={(kpis.total_merchants || 0).toLocaleString()}
          sub="Registered businesses"
          icon="users"
          color="#805ad5"
        />
        <StatCard
          label="Catalog Products"
          value={(kpis.total_products || 0).toLocaleString()}
          sub="Live SKU inventory"
          icon="package"
          color="#d69e2e"
        />
      </div>

      {/* Main Charts Row */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(min(100%, 540px), 1fr))', gap: 24, marginBottom: 28 }}>
        {/* Revenue Velocity Area Chart */}
        <div style={{
          background: 'var(--bg-2, #18191c)',
          border: '1px solid var(--border, rgba(255,255,255,0.08))',
          borderRadius: 14,
          padding: 24,
          boxShadow: '0 4px 20px rgba(0,0,0,0.15)'
        }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 20 }}>
            <div>
              <h2 style={{ fontSize: 16, fontWeight: 700, margin: 0, color: 'var(--text-primary, #fff)' }}>
                Sales Revenue Velocity (₹)
              </h2>
              <span style={{ fontSize: 12, color: 'var(--text-muted, #8e8e93)' }}>
                Daily gross sales across all merchants for the past {days} days
              </span>
            </div>
            {hoveredPoint && (
              <div style={{ textAlign: 'right', fontSize: 12 }}>
                <span style={{ color: 'var(--text-muted, #8e8e93)' }}>{hoveredPoint.display_date}: </span>
                <strong style={{ color: 'var(--accent, #c2714f)', fontFamily: 'var(--font-mono, monospace)' }}>
                  {formatCurrency(hoveredPoint.revenue)}
                </strong>
                <span style={{ color: 'var(--text-muted, #8e8e93)', marginLeft: 8 }}>({hoveredPoint.invoices} bills)</span>
              </div>
            )}
          </div>

          {loading && daily.length === 0 ? (
            <div style={{ height: chartHeight, display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--text-muted, #8e8e93)' }}>
              Loading sales trend…
            </div>
          ) : (
            <svg
              viewBox={`0 0 ${chartWidth} ${chartHeight}`}
              style={{ width: '100%', height: chartHeight, overflow: 'visible' }}
            >
              <defs>
                <linearGradient id="revenueGrad" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="#c2714f" stopOpacity="0.45" />
                  <stop offset="100%" stopColor="#c2714f" stopOpacity="0.0" />
                </linearGradient>
              </defs>

              {/* Grid lines */}
              {[0, 0.25, 0.5, 0.75, 1].map((ratio, i) => {
                const y = padding + ratio * (chartHeight - padding * 2)
                const val = Math.round(maxRevenue * (1 - ratio))
                return (
                  <g key={i}>
                    <line
                      x1={padding}
                      y1={y}
                      x2={chartWidth - padding}
                      y2={y}
                      stroke="rgba(255,255,255,0.06)"
                      strokeDasharray="4 4"
                    />
                    <text
                      x={padding - 6}
                      y={y + 3}
                      fill="var(--text-muted, #8e8e93)"
                      fontSize="9"
                      textAnchor="end"
                      fontFamily="var(--font-mono, monospace)"
                    >
                      {val >= 1000 ? `₹${(val / 1000).toFixed(0)}k` : `₹${val}`}
                    </text>
                  </g>
                )
              })}

              {/* Area & Line */}
              {areaD && <path d={areaD} fill="url(#revenueGrad)" />}
              {pathD && <path d={pathD} fill="none" stroke="#c2714f" strokeWidth="2.5" strokeLinecap="round" />}

              {/* Data points */}
              {points.map((p, idx) => (
                <circle
                  key={idx}
                  cx={p.x}
                  cy={p.y}
                  r={hoveredPoint?.date === p.date ? 5 : 3}
                  fill={hoveredPoint?.date === p.date ? '#fff' : '#c2714f'}
                  stroke="#c2714f"
                  strokeWidth="2"
                  style={{ cursor: 'pointer', transition: 'r 0.15s ease' }}
                  onMouseEnter={() => setHoveredPoint(p)}
                  onMouseLeave={() => setHoveredPoint(null)}
                />
              ))}
            </svg>
          )}
        </div>

        {/* Payment Modes & Split */}
        <div style={{
          background: 'var(--bg-2, #18191c)',
          border: '1px solid var(--border, rgba(255,255,255,0.08))',
          borderRadius: 14,
          padding: 24,
          boxShadow: '0 4px 20px rgba(0,0,0,0.15)',
          display: 'flex',
          flexDirection: 'column'
        }}>
          <div style={{ marginBottom: 20 }}>
            <h2 style={{ fontSize: 16, fontWeight: 700, margin: 0, color: 'var(--text-primary, #fff)' }}>
              Payment Methods Breakdown
            </h2>
            <span style={{ fontSize: 12, color: 'var(--text-muted, #8e8e93)' }}>
              Tender type distribution across processed transactions
            </span>
          </div>

          <div style={{ display: 'flex', flexDirection: 'column', gap: 16, flex: 1, justifyContent: 'center' }}>
            {payments.map((pm, idx) => {
              const colors = ['#c2714f', '#38a169', '#3182ce', '#805ad5', '#d69e2e']
              const color = colors[idx % colors.length]
              return (
                <div key={pm.mode}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 13, marginBottom: 6 }}>
                    <span style={{ fontWeight: 600, color: 'var(--text-primary, #fff)', display: 'flex', alignItems: 'center', gap: 8 }}>
                      <span style={{ width: 8, height: 8, borderRadius: '50%', background: color }} />
                      {pm.mode}
                    </span>
                    <span style={{ color: 'var(--text-muted, #8e8e93)', fontFamily: 'var(--font-mono, monospace)' }}>
                      {formatCurrency(pm.amount)} ({pm.percentage}%)
                    </span>
                  </div>
                  <div style={{ height: 8, borderRadius: 4, background: 'rgba(255,255,255,0.06)', overflow: 'hidden' }}>
                    <div style={{
                      width: `${pm.percentage}%`,
                      height: '100%',
                      background: color,
                      borderRadius: 4,
                      transition: 'width 0.4s ease'
                    }} />
                  </div>
                </div>
              )
            })}
          </div>
        </div>
      </div>

      {/* Top 10 Merchants Leaderboard */}
      <div style={{
        background: 'var(--bg-2, #18191c)',
        border: '1px solid var(--border, rgba(255,255,255,0.08))',
        borderRadius: 14,
        padding: 24,
        boxShadow: '0 4px 20px rgba(0,0,0,0.15)'
      }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 20 }}>
          <div>
            <h2 style={{ fontSize: 16, fontWeight: 700, margin: 0, color: 'var(--text-primary, #fff)' }}>
              Top Performing Merchants
            </h2>
            <span style={{ fontSize: 12, color: 'var(--text-muted, #8e8e93)' }}>
              Leading retail and wholesale businesses ranked by gross turnover
            </span>
          </div>
          <Link
            to="/admin/businesses"
            style={{ fontSize: 12, fontWeight: 600, color: 'var(--accent, #c2714f)', textDecoration: 'none', display: 'flex', alignItems: 'center', gap: 4 }}
          >
            View all fleet <Icon name="chevronRight" size={14} />
          </Link>
        </div>

        <div style={{ overflowX: 'auto' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', textAlign: 'left', fontSize: 13 }}>
            <thead>
              <tr style={{ borderBottom: '1px solid var(--border, rgba(255,255,255,0.08))', color: 'var(--text-muted, #8e8e93)' }}>
                <th style={{ padding: '10px 12px', fontWeight: 600 }}>#</th>
                <th style={{ padding: '10px 12px', fontWeight: 600 }}>Merchant Name</th>
                <th style={{ padding: '10px 12px', fontWeight: 600 }}>BizID</th>
                <th style={{ padding: '10px 12px', fontWeight: 600, textAlign: 'right' }}>Bills Rung</th>
                <th style={{ padding: '10px 12px', fontWeight: 600, textAlign: 'right' }}>Gross Revenue</th>
                <th style={{ padding: '10px 12px', fontWeight: 600, textAlign: 'right' }}>AOV</th>
                <th style={{ padding: '10px 12px', textAlign: 'right' }}>Action</th>
              </tr>
            </thead>
            <tbody>
              {topMerchants.map((m, idx) => (
                <tr
                  key={m.id}
                  style={{
                    borderBottom: '1px solid rgba(255,255,255,0.04)',
                    transition: 'background 0.15s ease'
                  }}
                  onMouseEnter={e => e.currentTarget.style.background = 'rgba(255,255,255,0.02)'}
                  onMouseLeave={e => e.currentTarget.style.background = 'transparent'}
                >
                  <td style={{ padding: '14px 12px', color: 'var(--text-muted, #8e8e93)', fontWeight: 600 }}>{idx + 1}</td>
                  <td style={{ padding: '14px 12px', fontWeight: 600, color: 'var(--text-primary, #fff)' }}>
                    {m.business_name}
                  </td>
                  <td style={{ padding: '14px 12px', fontFamily: 'var(--font-mono, monospace)', color: 'var(--text-muted, #8e8e93)', fontSize: 12 }}>
                    {m.public_id}
                  </td>
                  <td style={{ padding: '14px 12px', textAlign: 'right', fontFamily: 'var(--font-mono, monospace)' }}>
                    {m.invoice_count.toLocaleString()}
                  </td>
                  <td style={{ padding: '14px 12px', textAlign: 'right', fontWeight: 700, color: '#38a169', fontFamily: 'var(--font-mono, monospace)' }}>
                    {formatCurrency(m.revenue)}
                  </td>
                  <td style={{ padding: '14px 12px', textAlign: 'right', fontFamily: 'var(--font-mono, monospace)', color: 'var(--text-muted, #8e8e93)' }}>
                    {formatCurrency(m.arpu)}
                  </td>
                  <td style={{ padding: '14px 12px', textAlign: 'right' }}>
                    <Link
                      to={`/admin/businesses/${m.id}`}
                      style={{
                        padding: '4px 10px', borderRadius: 6,
                        background: 'rgba(255,255,255,0.06)',
                        color: 'var(--text-primary, #fff)',
                        textDecoration: 'none', fontSize: 11, fontWeight: 600
                      }}
                    >
                      Inspect
                    </Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}
