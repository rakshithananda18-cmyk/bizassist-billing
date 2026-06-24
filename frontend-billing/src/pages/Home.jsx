import React from 'react'
import { useNavigate } from 'react-router-dom'
import AppLayout from '../layouts/AppLayout'
import { useAuth } from '../contexts/AuthContext'
import { BuildingMark } from '../components/Logo'
import {
  CounterIcon,
  DashboardIcon,
  SummaryIcon,
  InventoryIcon,
  CashIcon,
  ContactsIcon,
  ReportsIcon,
  PhoneIcon,
  MailIcon,
  MapPinIcon
} from '../components/Icons'

const QUICK_LINKS = [
  { label: 'New Invoice', href: '/sales',     icon: <CounterIcon size={24} />,   desc: 'Open the billing counter' },
  { label: 'Dashboard',   href: '/dashboard', icon: <DashboardIcon size={24} />,   desc: 'View business summary' },
  { label: 'Inventory',   href: '/stock',     icon: <InventoryIcon size={24} />, desc: 'Manage your stock' },
  { label: 'Cash Book',   href: '/payments',  icon: <CashIcon size={24} />,      desc: 'Track payments' },
  { label: 'Contacts',    href: '/parties',   icon: <ContactsIcon size={24} />,   desc: 'Customers & suppliers' },
  { label: 'GST & Tax Reports', href: '/reports', icon: <ReportsIcon size={24} />, desc: 'View financial & tax statements' },
]

export default function Home() {
  const { profile, user } = useAuth()
  const navigate = useNavigate()

  const isCashier = (user?.role || '').toLowerCase() === 'cashier'
  const OWNER_ONLY_PATHS = React.useMemo(() => new Set(['/purchases', '/connections', '/orders', '/reports', '/import', '/staff', '/dashboard']), [])
  const visibleLinks = QUICK_LINKS.filter(link => !isCashier || !OWNER_ONLY_PATHS.has(link.href))

  const hour = new Date().getHours()
  const greeting = hour < 12 ? 'Good morning' : hour < 17 ? 'Good afternoon' : 'Good evening'
  const businessName = profile?.business_name || 'BizAssist User'
  const hasLogo = !!profile?.logo

  const formattedDate = new Date().toLocaleDateString('en-US', {
    weekday: 'long',
    month: 'long',
    day: 'numeric',
    year: 'numeric'
  }).toUpperCase()

  return (
    <AppLayout title="Home">
      <div className="slide-up" style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', padding: '40px 0', minHeight: '100%', justifyContent: 'center' }}>
        
        {/* Center Welcome Section */}
        <div style={{
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          textAlign: 'center',
          maxWidth: 480,
          padding: '0 20px',
          margin: 'auto 0'
        }}>
          {/* Symbol */}
          <div className="ces-symbol" style={{ marginBottom: 16 }}>
            <BuildingMark size={40} />
          </div>

          {/* Business Name (in large font place) */}
          <div className="ces-greeting" style={{ fontFamily: "'DM Sans', sans-serif" }}>
            {businessName.toUpperCase()}
          </div>

          {/* Date below Business Name */}
          <div style={{
            fontSize: '11px',
            fontWeight: 600,
            letterSpacing: '0.12em',
            textTransform: 'uppercase',
            color: 'var(--text-secondary)',
            marginTop: 6,
            marginBottom: 10
          }}>
            {formattedDate}
          </div>

          {/* Greeting below Date */}
          <div style={{
            fontFamily: "'DM Sans', sans-serif",
            fontSize: '15px',
            fontWeight: 600,
            color: 'var(--accent)',
            letterSpacing: '0.04em',
            marginBottom: 24
          }}>
            {greeting}
          </div>

          {/* Prompt Chips */}
          <div className="ces-chips" style={{ marginBottom: 32 }}>
            {visibleLinks.map(link => (
              <button
                key={link.href}
                className="chip"
                onClick={() => navigate(link.href)}
              >
                <span style={{ display: 'flex', alignItems: 'center', color: 'var(--accent)' }}>
                  {React.cloneElement(link.icon, { size: 15 })}
                </span>
                {link.label}
              </button>
            ))}
          </div>

          {/* Powered by footer directly below chips */}
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, color: 'var(--text-secondary)', fontSize: '0.72rem', justifyContent: 'center' }}>
            <div style={{ color: 'var(--accent)', opacity: 0.7, display: 'flex', alignItems: 'center' }}>
              <BuildingMark size={16} strokeWidth={2.2} />
            </div>
            Advanced Billing System · BizAssist
          </div>
        </div>

      </div>
    </AppLayout>
  )
}
