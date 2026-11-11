import React from 'react'
import { useNavigate } from 'react-router-dom'
import { fmt } from '../../utils/format'
import AnnouncementsCard from '../AnnouncementsCard'
import { CounterIcon, CashIcon, ContactsIcon, InventoryIcon, ReportsIcon, DashboardIcon, ChevronRightIcon, PlusIcon, AlertIcon, OrderIcon } from '../Icons'

const WORKSPACES = [
  { title: 'Stock', detail: 'Inventory', path: '/stock/inventory', icon: InventoryIcon },
  { title: 'Purchases', detail: 'Supplier bills', path: '/stock/purchase', icon: OrderIcon, owner: true },
  { title: 'Contacts', detail: 'People & dues', path: '/parties', icon: ContactsIcon },
  { title: 'Cash book', detail: 'Payments', path: '/parties/payments', icon: CashIcon },
  { title: 'Overview', detail: 'Performance', path: '/dashboard', icon: DashboardIcon, owner: true },
  { title: 'Reports', detail: 'Statements', path: '/reports', icon: ReportsIcon, owner: true },
]

export default function PhoneHome({ greeting, isCashier, today, todayError, onRetry }) {
  const navigate = useNavigate()
  const day = new Date().toLocaleDateString('en-IN', { weekday: 'long', day: 'numeric', month: 'short' })
  return (
    <div className="phone-screen phone-home">
      <header className="phone-screen-heading">
        <div><p className="phone-eyebrow">{day}</p><h1>{greeting}</h1></div>
        <span className="phone-day-mark" aria-hidden="true"><CounterIcon size={22} /></span>
      </header>

      <button className="phone-bill-launch" type="button" onClick={() => navigate('/sales')}>
        <span className="phone-bill-launch-icon"><PlusIcon size={24} /></span>
        <span><strong>New bill</strong><small>Open your billing counter</small></span>
        <ChevronRightIcon size={20} />
      </button>

      {!isCashier && <section className="phone-surface phone-today" aria-labelledby="phone-today-title">
        <div className="phone-section-heading"><h2 id="phone-today-title">Today at a glance</h2><button type="button" onClick={() => navigate('/dashboard')}>Overview <ChevronRightIcon size={13} /></button></div>
        {todayError ? <div className="phone-inline-notice" role="status">Totals couldn't refresh.<button type="button" onClick={onRetry}>Retry totals</button></div> : <>
          <button type="button" className="phone-collected" onClick={() => navigate('/parties/payments')}><span>Collected today</span><strong>{today ? fmt(today.paid_today) : '—'}</strong><small>View cash book <ChevronRightIcon size={12} /></small></button>
          <div className="phone-dues-split">
            <button type="button" onClick={() => navigate('/parties/invoices')}><span>Pending</span><strong>{today ? fmt(today.pending_amount) : '—'}</strong><small>{today ? `${today.pending_count} bill${today.pending_count === 1 ? '' : 's'}` : 'Loading totals'}</small></button>
            <button type="button" onClick={() => navigate('/parties/invoices')}><span>Overdue</span><strong className={today?.overdue_count ? 'phone-danger' : ''}>{today ? fmt(today.overdue_amount) : '—'}</strong><small>{today ? `${today.overdue_count} bill${today.overdue_count === 1 ? '' : 's'}` : 'Loading totals'}</small></button>
          </div>
        </>}
      </section>}

      <section aria-labelledby="phone-workspaces-title">
        <div className="phone-section-heading"><h2 id="phone-workspaces-title">Your workspaces</h2></div>
        <div className="phone-workspace-grid">
          {WORKSPACES.filter(item => !isCashier || !item.owner).map(({ title, detail, path, icon: Icon }) => <button className="phone-workspace" type="button" key={path} onClick={() => navigate(path)}><span className="phone-workspace-icon"><Icon size={21} /></span><strong>{title}</strong><small>{detail}</small></button>)}
        </div>
      </section>

      {!isCashier && <section className="phone-surface phone-attention" aria-label="Stock attention">
        <button className="phone-list-row" type="button" onClick={() => navigate('/stock/inventory')}><span className="phone-row-icon"><AlertIcon size={18} /></span><span className="phone-row-copy"><strong>Stock to check</strong><small>{today ? `${today.low_stock_count} item${today.low_stock_count === 1 ? '' : 's'} below minimum` : 'Review your inventory'}</small></span><ChevronRightIcon size={17} /></button>
      </section>}
      {isCashier && <p className="phone-helper">Ready to bill. Search items or scan a barcode at the counter.</p>}
      {!isCashier && <details className="phone-disclosure"><summary>Offers & updates <ChevronRightIcon size={17} /></summary><div style={{ padding: 14 }}><AnnouncementsCard /></div></details>}
    </div>
  )
}
