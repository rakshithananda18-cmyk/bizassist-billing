import React, { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import DashboardChartPanel from '../dashboard/DashboardChartPanel'
import TourPrivatePreview, { TourPrivateValue } from '../../demo/TourPrivatePreview'
import { CounterIcon, CashIcon, InventoryIcon, ChevronRightIcon, PlusIcon, AlertIcon } from '../Icons'

export default function PhoneDashboard({ stats: s, loading, summaryError, paymentsError, dayFeed, chartsData, privacyMode, protectTour, onRetry, isRefreshing }) {
  const [view, setView] = useState('overview')
  const navigate = useNavigate()
  const fmt = value => value == null ? '—' : `₹${Number(value).toLocaleString('en-IN', { maximumFractionDigits: 0 })}`
  const money = value => privacyMode ? '••••' : fmt(value)
  return <div className="phone-screen phone-dashboard">
    <header className="phone-screen-heading"><div><p className="phone-eyebrow">Business dashboard</p><h1>Overview</h1></div><button type="button" className="phone-primary-button" onClick={() => navigate('/sales')}><PlusIcon size={17} /> New bill</button></header>
    {isRefreshing && <p className="phone-helper" role="status">Refreshing your business…</p>}
    {loading ? <div className="phone-inline-notice" role="status">Loading business summary…</div> : summaryError ? <div className="phone-surface phone-empty" role="alert"><AlertIcon size={24} /><h2>Business summary is unavailable</h2><p>Refresh before relying on these figures.</p><button type="button" className="phone-primary-button" onClick={onRetry}>Retry dashboard</button></div> : <>
      <div className="phone-segments" role="group" aria-label="Dashboard view">{[['overview', 'Overview'], ['activity', 'Activity'], ['stock', 'Stock']].map(([id, text]) => <button type="button" key={id} aria-pressed={view === id} onClick={() => setView(id)}>{text}</button>)}</div>
      {view === 'overview' && <>
        <section className="phone-surface phone-revenue" aria-label="Revenue summary">
          <div className="phone-revenue-heading"><span>Total revenue</span><span className="phone-tag">All time</span></div>
          <button type="button" className="phone-revenue-value" onClick={() => navigate('/parties/invoices')} aria-label={`Total Revenue ${money(s.total_revenue)}`}>{money(s.total_revenue)}<ChevronRightIcon size={20} /></button>
          <p>{s.invoice_count || 0} invoices</p>
          <div className="phone-dues-split"><button type="button" onClick={() => navigate('/parties/invoices')}><span>Pending</span><strong>{money(s.pending_amount)}</strong><small>{s.pending_count ?? 0} bill{s.pending_count === 1 ? '' : 's'}</small></button><button type="button" onClick={() => navigate('/parties/invoices')}><span>Overdue</span><strong className={s.overdue_count > 0 ? "phone-danger" : undefined}>{money(s.overdue_amount)}</strong><small>{s.overdue_count ?? 0} bill{s.overdue_count === 1 ? '' : 's'}</small></button></div>
        </section>
        <section className="phone-surface" aria-label="Business measures">
          <button className="phone-list-row" type="button" onClick={() => navigate('/stock/purchase')}><span className="phone-row-icon"><CashIcon size={18} /></span><span className="phone-row-copy"><strong>Purchases</strong><small>Last 30 days</small></span><strong className="phone-row-value">{money(s.purchases_30d)}</strong><ChevronRightIcon size={15} /></button>
          <button className="phone-list-row" type="button" onClick={() => navigate('/parties')}><span className="phone-row-icon"><CounterIcon size={18} /></span><span className="phone-row-copy"><strong>Active customers</strong><small>Last 30 days</small></span><strong>{s.active_customers ?? 0}</strong><ChevronRightIcon size={15} /></button>
          <button className="phone-list-row" type="button" onClick={() => navigate('/reports')}><span className="phone-row-icon"><InventoryIcon size={18} /></span><span className="phone-row-copy"><strong>Gross margin</strong><small>{s.gross_margin == null ? 'Cost reconciliation needed' : 'Estimated'}</small></span><strong>{protectTour ? <TourPrivateValue /> : privacyMode ? '••••' : s.gross_margin == null ? '—' : `${s.gross_margin}%`}</strong><ChevronRightIcon size={15} /></button>
        </section>
        <details className="phone-disclosure phone-chart-disclosure"><summary>Sales & receivables charts <ChevronRightIcon size={17} /></summary>{protectTour ? <TourPrivatePreview /> : <DashboardChartPanel chartData={chartsData} privacyMode={privacyMode} onRetry={onRetry} />}</details>
      </>}
      {view === 'activity' && <section className="phone-surface" aria-label="Recent business activity">
        <div className="phone-section-heading"><h2>Recent activity</h2><span className="phone-tag">Latest updates</span></div>
        {paymentsError && <p className="phone-inline-notice" role="status">Payment activity couldn't refresh.<button type="button" onClick={onRetry}>Retry activity</button></p>}
        {!dayFeed.length && !paymentsError && <p className="phone-empty">No recent activity. Your transactions will appear here.</p>}
        {dayFeed.map((item, index) => <button key={`${item.title}:${index}`} type="button" className="phone-list-row" onClick={item.onClick}><span className="phone-row-icon" style={{ color: item.color }}>{item.icon}</span><span className="phone-row-copy"><strong>{item.title}</strong><small>{item.desc}</small><small>{item.timestamp}</small></span>{item.amount !== null && <strong className="phone-row-value">{privacyMode ? '••••' : `${item.amountPrefix} ${fmt(item.amount)}`}</strong>}<ChevronRightIcon size={15} /></button>)}
        <div className="phone-section-heading"><button type="button" onClick={() => navigate('/parties/invoices')}>All invoices <ChevronRightIcon size={14} /></button><button type="button" onClick={() => navigate('/parties/payments')}>Cash book <ChevronRightIcon size={14} /></button></div>
      </section>}
      {view === 'stock' && <>
        <div className="phone-stock-summary"><button type="button" onClick={() => navigate('/stock/inventory')}><InventoryIcon size={20} /><strong>{s.inventory_count ?? 0}</strong><span>Products</span></button><button type="button" onClick={() => navigate('/stock/inventory')}><AlertIcon size={20} /><strong>{s.low_stock_count ?? 0}</strong><span>Low stock</span></button></div>
        <section className="phone-surface" aria-label="Low stock items"><div className="phone-section-heading"><h2>Needs restocking</h2><button type="button" onClick={() => navigate('/stock/inventory')}>Inventory <ChevronRightIcon size={13} /></button></div>{s.low_stock_items?.length ? s.low_stock_items.map((item, index) => <button type="button" className="phone-list-row" key={`${item.name}:${index}`} onClick={() => navigate('/stock/inventory')}><span className="phone-row-copy"><strong>{item.name}</strong><small>Minimum {item.min_stock ?? '—'}</small></span><span className="phone-stock-count">{item.quantity} left</span><ChevronRightIcon size={15} /></button>) : <p className="phone-empty">All stock levels are safe.</p>}</section>
      </>}
    </>}
  </div>
}
