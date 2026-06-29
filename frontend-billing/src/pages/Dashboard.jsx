// ============================================================================
// Page: Dashboard.jsx
// Description: Main Business Owner Dashboard. Renders high-level overview metrics,
//              sales performance charts, stock alerts, overdue invoice tracking,
//              and automated smart business insights.
// ============================================================================
import React, { useEffect, useState, useCallback, useRef } from 'react'
import AppLayout from '../layouts/AppLayout'
import { useAuth } from '../contexts/AuthContext'
import { logger } from '../utils/logger'
import {
  SummaryIcon,
  CounterIcon,
  InventoryIcon,
  AlertIcon,
  ContactsIcon,
  CashIcon,
  CheckIcon,
  BillsIcon,
} from '../components/Icons'

function StatCard({ icon, label, value, sub, variant = 'accent', badge, badgeType }) {
  return (
    <div className={`stat-card ${variant}`}>
      <div className="flex items-center justify-between">
        <div className={`stat-icon ${variant}`}>{icon}</div>
        {badge && <span className={`stat-badge ${badgeType}`}>{badge}</span>}
      </div>
      <div className="stat-label">{label}</div>
      <div className="stat-value">{value}</div>
      {sub && <div className="stat-sub">{sub}</div>}
    </div>
  )
}

export default function Dashboard() {
  const { authFetch, profile, settings } = useAuth()

  const settingsRef = useRef(settings)
  useEffect(() => {
    settingsRef.current = settings
  }, [settings])

  const [stats, setStats]       = useState(null)
  const [payments, setPayments] = useState([])
  const [loading, setLoading]   = useState(true)

  const load = useCallback(() => {
    setLoading(true)
    Promise.all([
      authFetch('/dashboard-summary').then(r => r.ok ? r.json() : null).catch(() => null),
      authFetch('/payments').then(r => r.ok ? r.json() : []).catch(() => [])
    ]).then(([summaryData, paymentsData]) => {
      setStats(summaryData)
      setPayments(Array.isArray(paymentsData) ? paymentsData : (paymentsData?.items ?? []))
    }).finally(() => setLoading(false))
  }, [authFetch])

  useEffect(() => {
    load()
    const handleSync = (e) => {
      const currentSettings = settingsRef.current
      const isRealtimeGlobalEnabled = currentSettings?.general?.realtime_sync_global !== false
      if (!isRealtimeGlobalEnabled) return
      logger.debug('[DASHBOARD] Real-time sync event received:', e.detail)
      load()
    }
    window.addEventListener('focus', load)
    window.addEventListener('sync-event', handleSync)
    return () => {
      window.removeEventListener('focus', load)
      window.removeEventListener('sync-event', handleSync)
    }
  }, [load])

  const s   = stats || {}
  const fmt = n => n != null ? `₹${Number(n).toLocaleString('en-IN', { maximumFractionDigits: 0 })}` : '—'

  const recentPayments = payments.slice(0, 5)
  const feedItems      = []

  if (s.recent_invoices) {
    s.recent_invoices.forEach(inv => {
      feedItems.push({
        type:         'invoice',
        icon:         <CounterIcon size={14} />,
        bg:           'var(--accent-dim)',
        color:        'var(--text-primary)',
        title:        `Sales Invoice ${inv.invoice_number || `#${inv.id}`}`,
        desc:         `Billed to ${inv.customer_name || 'Walk-in Customer'}`,
        amount:       inv.total_amount,
        amountPrefix: '+',
        amountColor:  'var(--text-primary)',
        timestamp:    'Recent'
      })
    })
  }

  recentPayments.forEach(pay => {
    const isReceived = pay.type === 'received'
    feedItems.push({
      type:         'payment',
      icon:         <CashIcon size={14} />,
      bg:           isReceived ? 'var(--success-dim)' : 'var(--danger-dim)',
      color:        isReceived ? 'var(--success)' : 'var(--danger)',
      title:        isReceived ? 'Payment Received' : 'Payment Made',
      desc:         `${isReceived ? 'From' : 'To'} invoice: ${pay.invoice_ref || 'General'} via ${pay.method}`,
      amount:       parseFloat(pay.amount),
      amountPrefix: isReceived ? '+' : '-',
      amountColor:  isReceived ? 'var(--success)' : 'var(--danger)',
      timestamp:    pay.date ? new Date(pay.date).toLocaleDateString('en-IN', { day: 'numeric', month: 'short' }) : 'Recent'
    })
  })

  if (s.low_stock_items) {
    s.low_stock_items.forEach(item => {
      feedItems.push({
        type:      'warning',
        icon:      <AlertIcon size={14} />,
        bg:        'var(--warning-dim)',
        color:     'var(--warning)',
        title:     'Low Stock Alert',
        desc:      `${item.name} is running low (${item.quantity} left)`,
        amount:    null,
        timestamp: 'Alert'
      })
    })
  }

  const dayFeed = feedItems.slice(0, 8)

  return (
    <AppLayout title="Dashboard">
      <div className="slide-up">
        {/* Header */}
        <div className="page-header" style={{ marginBottom: '20px' }}>
          <div className="page-header-left">
            <h1 className="page-title">Business Dashboard</h1>
            <p className="page-subtitle">
              {profile?.business_name
                ? `Live overview for ${profile.business_name.toUpperCase()}`
                : 'Live business overview — transactions, stock & payments'}
            </p>
          </div>
        </div>

        {loading ? (
          <div className="page-loader"><span className="spinner" />Loading business summary…</div>
        ) : (
          <>
            {/* KPI Summary Strip 1 */}
            <div className="vsummary-strip mb-6">
              <div className="vsummary-card" style={{ borderLeftColor: 'var(--accent)' }}>
                <div className="vsummary-label">Total Revenue</div>
                <div className="vsummary-value">{fmt(s.total_revenue)}</div>
                <div className="vsummary-sub">{s.invoice_count || 0} invoices</div>
              </div>
              <div className="vsummary-card" style={{ borderLeftColor: '#c97c22' }}>
                <div className="vsummary-label">Pending</div>
                <div className="vsummary-value">{s.pending_count ?? 0}</div>
                <div className="vsummary-sub">{s.pending_amount ? `${fmt(s.pending_amount)} outstanding` : 'invoices awaiting'}</div>
              </div>
              <div className="vsummary-card" style={{ borderLeftColor: '#c02a2a' }}>
                <div className="vsummary-label">Overdue</div>
                <div className="vsummary-value" style={{ color: '#c02a2a' }}>{fmt(s.overdue_amount)}</div>
                <div className="vsummary-sub">{s.overdue_count ?? 0} invoices at risk</div>
              </div>
              <div className="vsummary-card" style={{ borderLeftColor: '#3a9a5c' }}>
                <div className="vsummary-label">Inventory</div>
                <div className="vsummary-value">{s.inventory_count ?? 0}</div>
                <div className="vsummary-sub">products tracked</div>
              </div>
            </div>

            {/* KPI Summary Strip 2 */}
            <div className="vsummary-strip mb-6">
              <div className="vsummary-card" style={{ borderLeftColor: '#c97c22' }}>
                <div className="vsummary-label">Low Stock Items</div>
                <div className="vsummary-value">{s.low_stock_count ?? 0}</div>
                <div className="vsummary-sub">need restocking</div>
              </div>
              <div className="vsummary-card" style={{ borderLeftColor: 'var(--accent)' }}>
                <div className="vsummary-label">Purchases (30d)</div>
                <div className="vsummary-value">{fmt(s.purchases_30d)}</div>
                <div className="vsummary-sub">total purchase value</div>
              </div>
              <div className="vsummary-card" style={{ borderLeftColor: '#3a9a5c' }}>
                <div className="vsummary-label">Active Customers</div>
                <div className="vsummary-value">{s.active_customers ?? 0}</div>
                <div className="vsummary-sub">in last 30 days</div>
              </div>
              <div className="vsummary-card" style={{ borderLeftColor: 'var(--accent)' }}>
                <div className="vsummary-label">Gross Margin</div>
                <div className="vsummary-value">{s.gross_margin ? `${s.gross_margin}%` : '—'}</div>
                <div className="vsummary-sub">estimated margin</div>
              </div>
            </div>

            {/* Feed & Alerts grid */}
            <div className="dashboard-grid">

              {/* Business Day Feed */}
              <div className="card" style={{ display: 'flex', flexDirection: 'column', gap: '16px', minHeight: '400px' }}>
                <div className="flex items-center justify-between" style={{ borderBottom: '1px solid var(--border)', paddingBottom: '12px', marginBottom: '14px' }}>
                  <h2>Live Business Day Feed</h2>
                  <span className="badge badge-accent" style={{ fontSize: '0.7rem' }}>Real-time Feed</span>
                </div>
                {dayFeed.length === 0 ? (
                  <div className="empty-state" style={{ flex: 1 }}>
                    <div className="empty-icon"><SummaryIcon size={20} /></div>
                    <h3>No recent activity</h3>
                    <p>Transactions and stock updates will appear here.</p>
                  </div>
                ) : (
                  <div className="timeline-container" style={{ overflowY: 'auto', maxHeight: '420px', paddingRight: '4px' }}>
                    {dayFeed.map((item, idx) => (
                      <div key={idx} className="timeline-item">
                        <div className="timeline-marker" style={{ background: item.bg, color: item.color, borderColor: item.color }}>
                          {item.icon}
                        </div>
                        <div className="timeline-card">
                          <div style={{ flex: 1, textAlign: 'left' }}>
                            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline' }}>
                              <span style={{ fontWeight: 600, fontSize: '0.85rem', color: 'var(--text-primary)' }}>{item.title}</span>
                              <span style={{ fontSize: '0.7rem', color: 'var(--text-muted)' }}>{item.timestamp}</span>
                            </div>
                            <div style={{ fontSize: '0.78rem', color: 'var(--text-secondary)', marginTop: '2px' }}>{item.desc}</div>
                          </div>
                          {item.amount !== null && (
                            <div style={{ fontWeight: 700, fontSize: '0.88rem', color: item.amountColor, whiteSpace: 'nowrap', marginLeft: '8px' }}>
                              {item.amountPrefix} ₹{item.amount.toLocaleString('en-IN', { maximumFractionDigits: 0 })}
                            </div>
                          )}
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>

              {/* Right stacked */}
              <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>

                {/* Low Stock */}
                <div className="card" style={{ padding: '16px' }}>
                  <div className="flex items-center justify-between" style={{ marginBottom: '14px' }}>
                    <h2>Low Stock Warnings</h2>
                    <a href="/stock" style={{ fontSize: '0.72rem', color: 'var(--text-muted)', fontWeight: 600 }}>View Catalog</a>
                  </div>
                  {s.low_stock_items?.length ? (
                    <div className="data-table-wrap">
                      <table className="data-table" style={{ fontSize: '0.8rem' }}>
                        <thead><tr><th>Product</th><th>Stock</th><th>Min</th></tr></thead>
                        <tbody>
                          {s.low_stock_items.map((item, i) => (
                            <tr key={i}>
                              <td className="td-primary">{item.name}</td>
                              <td><span className="badge badge-danger">{item.quantity}</span></td>
                              <td style={{ color: 'var(--text-muted)' }}>{item.min_stock}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  ) : (
                    <div className="empty-state" style={{ minHeight: '120px', padding: '20px' }}>
                      <div className="empty-icon" style={{ width: '36px', height: '36px' }}><InventoryIcon size={16} /></div>
                      <p style={{ fontSize: '0.78rem', margin: 0 }}>All stock levels are safe.</p>
                    </div>
                  )}
                </div>

                {/* Recent Invoices */}
                <div className="card" style={{ padding: '16px' }}>
                  <div className="flex items-center justify-between" style={{ marginBottom: '14px' }}>
                    <h2>Recent Invoices</h2>
                    <a href="/sales" style={{ fontSize: '0.72rem', color: 'var(--text-muted)', fontWeight: 600 }}>Billing Counter</a>
                  </div>
                  {s.recent_invoices?.length ? (
                    <div className="data-table-wrap">
                      <table className="data-table" style={{ fontSize: '0.8rem' }}>
                        <thead>
                          <tr><th>Bill No</th><th>Amount</th><th>Status</th></tr>
                        </thead>
                        <tbody>
                          {s.recent_invoices.slice(0, 4).map(inv => (
                            <tr key={inv.id}>
                              <td className="td-mono">{inv.invoice_number}</td>
                              <td style={{ fontWeight: 600, color: 'var(--text-primary)' }}>₹{inv.total_amount?.toLocaleString('en-IN')}</td>
                              <td>
                                <span className={`badge badge-${inv.status === 'paid' ? 'success' : inv.status === 'overdue' ? 'danger' : 'warning'}`}
                                  style={{ fontSize: '0.65rem' }}>
                                  {inv.status}
                                </span>
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  ) : (
                    <div className="empty-state" style={{ minHeight: '120px', padding: '20px' }}>
                      <div className="empty-icon" style={{ width: '36px', height: '36px' }}><CounterIcon size={16} /></div>
                      <p style={{ fontSize: '0.78rem', margin: 0 }}>No recent invoices.</p>
                    </div>
                  )}
                </div>

              </div>
            </div>
          </>
        )}
      </div>
    </AppLayout>
  )
}
