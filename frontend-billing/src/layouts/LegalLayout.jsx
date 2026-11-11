import React, { useRef, useEffect } from 'react'
import { Link, NavLink, useLocation } from 'react-router-dom'
import { BuildingMark } from '../components/Logo'
import { useAuth } from '../contexts/AuthContext'
import { BillsIcon, ShieldIcon, CashIcon, ContactsIcon } from '../components/Icons'
import './legal-layout.css'
import '../pages/phone-utilities.css'

export default function LegalLayout({ title, subtitle, lastUpdated, children }) {
  const location = useLocation()
  const { user } = useAuth()
  const scrollRef = useRef(null)

  // Scroll right document panel to top whenever navigating between legal sections
  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = 0
    }
  }, [location.pathname])

  const navItems = [
    {
      to: '/terms',
      label: 'Terms of Service',
      desc: 'User agreement & tax rules',
      icon: <BillsIcon size={18} />,
    },
    {
      to: '/privacy',
      label: 'Privacy Policy',
      desc: 'DPDP pledge & zero data sale',
      icon: <ShieldIcon size={18} />,
    },
    {
      to: '/refund-policy',
      label: 'Refund & Cancellation',
      desc: '14-day trial & guarantees',
      icon: <CashIcon size={18} />,
    },
    {
      to: '/contact',
      label: 'Contact & Support',
      desc: 'Operating hours & help desk',
      icon: <ContactsIcon size={18} />,
    },
  ]

  return (
    <div className="legal-shell">
      {/* ── Left Sidebar (Matching App Settings Sub-Sidebar) ── */}
      <aside className="legal-sidebar" aria-label="Documentation navigation">
        {/* Brand Header */}
        <div className="legal-sidebar-header">
          <Link to="/" style={{ display: 'flex', alignItems: 'center', gap: 12, textDecoration: 'none', color: 'inherit' }}>
            <BuildingMark size={32} accent="var(--accent, #c15f3c)" />
            <div style={{ display: 'flex', flexDirection: 'column', lineHeight: 1.1 }}>
              <span style={{ fontSize: '1.2rem', fontWeight: 900, letterSpacing: '0.06em', textTransform: 'uppercase' }}>
                STATER <span style={{ color: 'var(--accent, #c15f3c)', fontWeight: 600, textTransform: 'none', letterSpacing: 'normal' }}>Bill</span>
              </span>
              <span style={{ fontSize: '0.62rem', color: 'var(--text-muted, #777)', letterSpacing: '0.12em', textTransform: 'uppercase', marginTop: 2 }}>
                στατήρ • by ARES
              </span>
            </div>
          </Link>

          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginTop: 4 }}>
            <span style={{ fontSize: '0.72rem', fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.08em', color: 'var(--accent, #c15f3c)' }}>
              Trust & Legal Center
            </span>
            <span style={{ fontSize: '0.65rem', fontWeight: 600, padding: '2px 8px', borderRadius: 20, backgroundColor: 'var(--accent-glow, rgba(193, 95, 60, 0.1))', color: 'var(--accent, #c15f3c)' }}>
              v1.2
            </span>
          </div>
        </div>

        {/* Navigation list */}
        <div className="legal-sidebar-nav">
          <div className="legal-nav-group-label">
            Documentation
          </div>

          {navItems.map(item => (
            <NavLink
              key={item.to}
              to={item.to}
              className={({ isActive }) => `legal-nav-item${isActive ? ' active' : ''}`}
            >
              <span className="legal-nav-icon">{item.icon}</span>
              <div className="legal-nav-text">
                <span className="legal-nav-label">{item.label}</span>
                <span className="legal-nav-desc">{item.desc}</span>
              </div>
            </NavLink>
          ))}
        </div>

        {/* Bottom Actions */}
        <div className="legal-sidebar-footer">
          <Link
            to={user ? '/' : '/login'}
            style={{
              width: '100%',
              padding: '10px 14px',
              borderRadius: 'var(--radius-md, 8px)',
              backgroundColor: 'var(--accent, #c15f3c)',
              color: '#ffffff',
              fontWeight: 600,
              fontSize: '0.88rem',
              textAlign: 'center',
              textDecoration: 'none',
              boxSizing: 'border-box',
              display: 'block',
            }}
          >
            {user ? 'Open Workspace →' : 'Sign In to App →'}
          </Link>
          <div style={{ fontSize: '0.72rem', color: 'var(--text-muted, #9ca3af)', textAlign: 'center', lineHeight: 1.4 }}>
            © {new Date().getFullYear()} STATER Bill • ARES Pvt Ltd
          </div>
        </div>
      </aside>

      {/* ── Right Panel (Full Scrollable Document Area) ── */}
      <main
        ref={scrollRef}
        className="legal-doc-scroll"
        tabIndex={0}
        aria-label="Document content"
      >
        <div className="legal-doc-content">
          {title && (
            <div className="legal-doc-header">
              <h1 className="legal-doc-title">{title}</h1>
              {subtitle && <p className="legal-doc-subtitle">{subtitle}</p>}
              {lastUpdated && (
                <span className="legal-doc-badge">
                  Last Updated: {lastUpdated}
                </span>
              )}
            </div>
          )}

          <div className="legal-prose">
            {children}
          </div>

          <div style={{
            marginTop: 64,
            paddingTop: 24,
            borderTop: '1px solid var(--border, #e5e7eb)',
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
            fontSize: '0.82rem',
            color: 'var(--text-muted, #9ca3af)',
            flexWrap: 'wrap',
            gap: 12,
          }}>
            <span>STATER Bill — The Ancient Gold Standard of Trade (στατήρ)</span>
            <a href="mailto:rakshithananda18@gmail.com" style={{ color: 'var(--accent, #c15f3c)', textDecoration: 'none', fontWeight: 600 }}>
              rakshithananda18@gmail.com
            </a>
          </div>
        </div>
      </main>
    </div>
  )
}
