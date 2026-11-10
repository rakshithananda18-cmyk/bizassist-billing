// src/components/dashboard/DashboardCharts.jsx
// Lightweight, responsive, zero-dependency SVG charts for executive dashboard
import React, { useState } from 'react'

export default function DashboardCharts({ chartData }) {
  const [hoveredMonth, setHoveredMonth] = useState(null)

  const revenueSeries = chartData?.monthly_revenue || []
  const agingList = chartData?.aging_overview || []
  const topProducts = chartData?.top_products || []

  // SVG Area Chart calculations
  const maxRev = Math.max(...revenueSeries.map(d => Number(d.revenue) || 0), 1000)
  const chartHeight = 150
  const chartWidth = 500
  const padX = 35
  const padY = 20

  const points = revenueSeries.map((d, idx) => {
    const rev = Number(d.revenue) || 0
    const x = revenueSeries.length === 1
      ? chartWidth / 2
      : padX + (idx / Math.max(revenueSeries.length - 1, 1)) * (chartWidth - padX * 2)
    const y = chartHeight - padY - (rev / maxRev) * (chartHeight - padY * 2)
    return { x, y, ...d, revenue: rev }
  })

  const pathD = points.length > 1
    ? points.reduce((acc, p, i) => `${acc} ${i === 0 ? 'M' : 'L'} ${p.x} ${p.y}`, '')
    : ''
  const areaD = points.length > 1
    ? `${pathD} L ${points[points.length - 1].x} ${chartHeight - padY} L ${points[0].x} ${chartHeight - padY} Z`
    : ''

  const totalOverdue = agingList.reduce((acc, a) => acc + (Number(a.amount) || 0), 0)

  if (!chartData) {
    return (
      <div className="card" style={{ padding: '16px 20px', marginBottom: 20 }}>
        <p className="muted" style={{ margin: 0, fontSize: '0.85rem' }}>
          Charts could not load. Refresh the page to try again.
        </p>
      </div>
    )
  }

  return (
    <div style={{
      display: 'grid',
      gridTemplateColumns: 'repeat(auto-fit, minmax(min(100%, 320px), 1fr))',
      gap: 16,
      marginBottom: 20
    }}>
      {/* ── Monthly Revenue Area Chart ── */}
      <div className="card" style={{ padding: '16px 20px', display: 'flex', flexDirection: 'column' }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12 }}>
          <div>
            <h2 style={{ fontSize: '0.92rem', fontWeight: 700, margin: 0 }}>Monthly Revenue Trajectory</h2>
            <p style={{ fontSize: '0.72rem', color: 'var(--text-muted)', margin: '2px 0 0 0' }}>Sales performance across recent operating months</p>
          </div>
          {hoveredMonth ? (
            <div style={{ textAlign: 'right' }}>
              <span style={{ fontSize: '0.7rem', color: 'var(--text-muted)' }}>{hoveredMonth.month}</span>
              <div style={{ fontWeight: 800, fontSize: '0.92rem', color: 'var(--accent)' }}>
                ₹{hoveredMonth.revenue.toLocaleString('en-IN')}
              </div>
            </div>
          ) : (
            <span className="badge badge-accent" style={{ fontSize: '0.7rem' }}>Live Trend</span>
          )}
        </div>

        <div style={{ flex: 1, position: 'relative', width: '100%', minHeight: 160 }}>
          {points.length === 0 ? (
            <div style={{
              display: 'flex',
              flexDirection: 'column',
              alignItems: 'center',
              justifyContent: 'center',
              height: '100%',
              minHeight: 160,
              color: 'var(--text-muted)',
              fontSize: '0.82rem',
              textAlign: 'center',
              padding: '16px'
            }}>
              <span>No revenue data recorded yet.</span>
              <span style={{ fontSize: '0.74rem', marginTop: 4 }}>Invoices created in POS will automatically graph here.</span>
            </div>
          ) : (
            <svg viewBox={`0 0 ${chartWidth} ${chartHeight}`} style={{ width: '100%', height: '100%', overflow: 'visible' }}>
              <defs>
                <linearGradient id="revGrad" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="var(--accent)" stopOpacity="0.22" />
                  <stop offset="100%" stopColor="var(--accent)" stopOpacity="0.0" />
                </linearGradient>
              </defs>
              {/* Guide Gridlines */}
              <line x1={padX} y1={padY} x2={chartWidth - padX} y2={padY} stroke="var(--border)" strokeDasharray="3 3" opacity={0.6} />
              <line x1={padX} y1={chartHeight / 2} x2={chartWidth - padX} y2={chartHeight / 2} stroke="var(--border)" strokeDasharray="3 3" opacity={0.6} />
              <line x1={padX} y1={chartHeight - padY} x2={chartWidth - padX} y2={chartHeight - padY} stroke="var(--border)" />

              {/* Gradient Area & Stroke */}
              {points.length > 1 && (
                <>
                  <path d={areaD} fill="url(#revGrad)" />
                  <path d={pathD} fill="none" stroke="var(--accent)" strokeWidth="2.5" strokeLinecap="round" />
                </>
              )}

              {/* Single Month Pillar */}
              {points.length === 1 && (
                <line
                  x1={points[0].x}
                  y1={chartHeight - padY}
                  x2={points[0].x}
                  y2={points[0].y}
                  stroke="var(--accent)"
                  strokeWidth="3.5"
                  strokeLinecap="round"
                />
              )}

              {/* Interactive Data Points */}
              {points.map((p, idx) => (
                <g key={idx}>
                  <circle
                    cx={p.x}
                    cy={p.y}
                    r={hoveredMonth?.month === p.month ? 5 : 3.5}
                    fill="var(--bg-1)"
                    stroke="var(--accent)"
                    strokeWidth="2"
                    style={{ cursor: 'pointer', transition: 'r 0.15s ease' }}
                    onMouseEnter={() => setHoveredMonth(p)}
                    onMouseLeave={() => setHoveredMonth(null)}
                  />
                  <text
                    x={p.x}
                    y={chartHeight - 4}
                    textAnchor="middle"
                    fontSize="9.5"
                    fill="var(--text-muted)"
                    fontWeight={500}
                  >
                    {p.month}
                  </text>
                </g>
              ))}
            </svg>
          )}
        </div>
      </div>

      {/* ── Receivables Aging Risk & Top Drivers ── */}
      <div className="card" style={{ padding: '16px 20px', display: 'flex', flexDirection: 'column', gap: 14 }}>
        {/* Receivables Aging Header */}
        <div>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 8 }}>
            <h2 style={{ fontSize: '0.88rem', fontWeight: 700, margin: 0 }}>Receivables Aging Risk</h2>
            <span style={{ fontSize: '0.74rem', color: totalOverdue > 0 ? 'var(--danger)' : 'var(--success)', fontWeight: 700 }}>
              ₹{totalOverdue.toLocaleString('en-IN')} Overdue
            </span>
          </div>

          <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
            {agingList.map((tier) => {
              const amt = Number(tier.amount) || 0
              const pct = totalOverdue > 0 ? ((amt / totalOverdue) * 100).toFixed(0) : 0
              const color = tier.range.includes('90+')
                ? 'var(--danger)'
                : tier.range.includes('61-90')
                ? '#ea580c'
                : tier.range.includes('31-60')
                ? 'var(--warning)'
                : 'var(--success)'

              return (
                <div key={tier.range}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.72rem', marginBottom: 2 }}>
                    <span style={{ color: 'var(--text-secondary)' }}>{tier.range}</span>
                    <span style={{ fontWeight: 600 }}>₹{amt.toLocaleString('en-IN')} ({pct}%)</span>
                  </div>
                  <div style={{ height: 5, background: 'var(--bg-3)', borderRadius: 3, overflow: 'hidden' }}>
                    <div style={{ width: `${pct}%`, height: '100%', background: color, borderRadius: 3, transition: 'width 0.3s ease' }} />
                  </div>
                </div>
              )
            })}
          </div>
        </div>

        {/* Top Product Drivers */}
        <div style={{ borderTop: '1px solid var(--border)', paddingTop: 10 }}>
          <div style={{ fontSize: '0.74rem', fontWeight: 700, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.04em', marginBottom: 6 }}>
            Top Revenue Contributors
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 5 }}>
            {topProducts.length === 0 ? (
              <div style={{ fontSize: '0.74rem', color: 'var(--text-muted)' }}>No product sales recorded yet.</div>
            ) : (
              topProducts.slice(0, 3).map((item, i) => (
                <div key={i} style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', fontSize: '0.75rem' }}>
                  <span style={{ color: 'var(--text-primary)', fontWeight: 500, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', maxWidth: '65%' }}>
                    {item.name}
                  </span>
                  <span style={{ fontWeight: 700, color: 'var(--text-secondary)' }}>
                    ₹{Number(item.value).toLocaleString('en-IN')}
                  </span>
                </div>
              ))
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
