// ============================================================================
// Page: Home.jsx
// Description: Cashier landing portal. Provides quick nav cards to the POS counter,
//              inventory, and reports. Scopes features based on staff credentials.
// ============================================================================
import React, { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import AppLayout from '../layouts/AppLayout'
import { useAuth } from '../contexts/AuthContext'
import { fmt } from '../utils/format'
import { BuildingMark } from '../components/Logo'
import AnnouncementsCard from '../components/AnnouncementsCard'
import {
  CounterIcon,
  DashboardIcon,
  InventoryIcon,
  CashIcon,
  ContactsIcon,
  ReportsIcon
} from '../components/Icons'

const QUICK_LINKS = [
  { label: 'New Invoice', href: '/sales',     icon: <CounterIcon size={24} />,   desc: 'Open the billing counter' },
  { label: 'Dashboard',   href: '/dashboard', icon: <DashboardIcon size={24} />,   desc: 'View business summary' },
  { label: 'Inventory',   href: '/stock',     icon: <InventoryIcon size={24} />, desc: 'Manage your stock' },
  // /payments was never a route (it fell through to Home); payments live here.
  { label: 'Cash Book',   href: '/parties/payments', icon: <CashIcon size={24} />, desc: 'Track payments' },
  { label: 'Contacts',    href: '/parties',   icon: <ContactsIcon size={24} />,   desc: 'Customers & suppliers' },
  { label: 'GST & Tax Reports', href: '/reports', icon: <ReportsIcon size={24} />, desc: 'View financial & tax statements' },
]

export default function Home() {
  const { profile, user, authFetch } = useAuth()
  const navigate = useNavigate()

  const isCashier = (user?.role || '').toLowerCase() === 'cashier'
  const OWNER_ONLY_PATHS = React.useMemo(() => new Set(['/purchases', '/b2b', '/b2b-network', '/b2b-orders', '/reports', '/import', '/staff', '/dashboard']), [])
  const visibleLinks = QUICK_LINKS.filter(link => !isCashier || !OWNER_ONLY_PATHS.has(link.href))

  // Today at a glance - owners only (business totals), from the same summary
  // the Dashboard uses. A failed load just hides the numbers.
  const [today, setToday] = useState(null)
  useEffect(() => {
    if (isCashier || !authFetch) return undefined
    let live = true
    authFetch('/dashboard-summary')
      .then(r => (r.ok ? r.json() : null))
      .then(s => { if (live) setToday(s) })
      .catch(() => {})
    return () => { live = false }
  }, [isCashier, authFetch])

  const hour = new Date().getHours()
  const greeting = hour < 12 ? 'Good morning' : hour < 17 ? 'Good afternoon' : 'Good evening'
  const businessName = profile?.business_name || 'BizAssist User'

  // Indian order, day before month: SUNDAY 25 OCTOBER, 2026.
  const formattedDate = new Date().toLocaleDateString('en-IN', {
    weekday: 'long',
    day: 'numeric',
    month: 'long',
    year: 'numeric'
  }).toUpperCase()

  return (
    <AppLayout title="Home">
      <div className="home-page slide-up">
        <section className="home-hero" aria-labelledby="home-title">
          <div className="home-hero-copy">
            <div className="home-eyebrow">
              <BuildingMark size={16} strokeWidth={2.2} />
              {formattedDate}
            </div>
            <h1 id="home-title">{greeting}, <span>{businessName}</span></h1>
            <p>Choose a workspace to start billing, review your business, or stay on top of today&apos;s operations.</p>
          </div>
          <div className="home-hero-actions">
            <button type="button" className="home-primary-action" onClick={() => navigate('/sales')}>
              <CounterIcon size={18} /> New invoice
            </button>
            {!isCashier && (
              <button type="button" className="home-secondary-action" onClick={() => navigate('/dashboard')}>
                <DashboardIcon size={17} /> View dashboard
              </button>
            )}
          </div>
        </section>

        <section className="home-actions-section" aria-labelledby="home-actions-title">
          <div className="home-section-heading">
            <div>
              <p className="home-section-kicker">Workspace</p>
              <h2 id="home-actions-title">Start a task</h2>
            </div>
            <p>Everything you need for the next step is one click away.</p>
          </div>
          <div className="home-actions-grid">
            {visibleLinks.map(link => (
              <button
                key={link.href}
                type="button"
                className="home-action-card"
                onClick={() => navigate(link.href)}
              >
                <span className="home-action-icon" aria-hidden="true">{link.icon}</span>
                <span className="home-action-copy">
                  <strong>{link.label}</strong>
                  <small>{link.desc}</small>
                </span>
                <span className="home-action-arrow" aria-hidden="true">→</span>
              </button>
            ))}
          </div>
        </section>

        <div className="home-lower-grid">
          {isCashier ? (
            <section className="home-routine-card" aria-labelledby="home-routine-title">
              <div className="home-routine-icon" aria-hidden="true"><CounterIcon size={22} /></div>
              <div>
                <p className="home-section-kicker">Counter</p>
                <h2 id="home-routine-title">Ready to bill</h2>
                <p>Open a new invoice to start. Search products by name or scan a barcode at the counter.</p>
              </div>
            </section>
          ) : (
            <section className="home-today-card" aria-labelledby="home-today-title">
              <p className="home-section-kicker">Today</p>
              <h2 id="home-today-title">Your business at a glance</h2>
              <div className="home-today-grid">
                <button type="button" className="home-today-stat" onClick={() => navigate('/parties/payments')}>
                  <small>Collected today</small>
                  <strong>{today ? fmt(today.paid_today) : '—'}</strong>
                </button>
                <button type="button" className="home-today-stat" onClick={() => navigate('/parties/invoices')}>
                  <small>Pending</small>
                  <strong>{today ? fmt(today.pending_amount) : '—'}</strong>
                  {today && <span>{today.pending_count} bill{today.pending_count === 1 ? '' : 's'}</span>}
                </button>
                <button type="button" className="home-today-stat" onClick={() => navigate('/parties/invoices')}>
                  <small>Overdue</small>
                  <strong className={today?.overdue_count > 0 ? 'is-overdue' : undefined}>
                    {today ? fmt(today.overdue_amount) : '—'}
                  </strong>
                  {today && <span>{today.overdue_count} bill{today.overdue_count === 1 ? '' : 's'}</span>}
                </button>
                <button type="button" className="home-today-stat" onClick={() => navigate('/stock/inventory')}>
                  <small>Low stock</small>
                  <strong>{today ? today.low_stock_count : '—'}</strong>
                  {today && <span>item{today.low_stock_count === 1 ? '' : 's'}</span>}
                </button>
              </div>
            </section>
          )}
          {!isCashier && (
            <section className="home-announcements" aria-label="Offers and updates">
              <p className="home-section-kicker">Offers and updates</p>
              <AnnouncementsCard />
            </section>
          )}
        </div>

        <footer className="home-footer">
          <BuildingMark size={15} strokeWidth={2.2} /> Advanced Billing System · BizAssist
        </footer>
      </div>
    </AppLayout>
  )
}
