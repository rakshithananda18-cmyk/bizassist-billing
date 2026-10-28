import React, { useEffect, useRef, useState } from 'react'
import { Link, NavLink, Outlet, useLocation } from 'react-router-dom'
import { useAuth } from '../lib/auth'
import { planBanner } from '../lib/plan'
import { cycleTheme, getBillingUrl, getTheme } from '../lib/theme'
import { BuildingMark } from '../components/Logo'
import { useToast } from '../components/ui'
import {
  AwardIcon, ClipboardIcon, ClockIcon, CloseIcon, ContactsIcon, DashboardIcon, ListIcon, LogoutIcon, MapPinIcon,
  MenuIcon, MonitorIcon, MoonIcon, OrderIcon, RouteIcon, SettingsIcon, SunIcon, TruckIcon, UserIcon,
} from '../components/Icons'

const NAV = [
  { section: 'Today', items: [
    { to: '/', icon: <DashboardIcon size={18} />, label: 'Dashboard', end: true },
    { to: '/live', icon: <MapPinIcon size={18} />, label: 'Live map' },
    { to: '/plan', icon: <TruckIcon size={18} />, label: 'Day plan' },
    { to: '/tasks', icon: <ClipboardIcon size={18} />, label: 'Tasks' },
    { to: '/requests', icon: <OrderIcon size={18} />, label: 'Shop requests' },
  ] },
  { section: 'Setup', items: [
    { to: '/shops', icon: <ContactsIcon size={18} />, label: 'Shops' },
    { to: '/routes', icon: <RouteIcon size={18} />, label: 'Routes' },
    { to: '/staff', icon: <UserIcon size={18} />, label: 'Staff' },
  ] },
  { section: 'Records', items: [
    { to: '/attendance', icon: <ClockIcon size={18} />, label: 'Attendance' },
    { to: '/scorecard', icon: <AwardIcon size={18} />, label: 'Scorecard' },
    { to: '/activity', icon: <ListIcon size={18} />, label: 'Activity' },
    { to: '/settings', icon: <SettingsIcon size={18} />, label: 'Settings' },
  ] },
]

const THEME_ICON = { system: <MonitorIcon size={16} />, light: <SunIcon size={16} />, dark: <MoonIcon size={16} /> }

function BusinessName({ children }) {
  const ref = useRef(null)
  const [distance, setDistance] = useState(0)
  useEffect(() => {
    const element = ref.current
    const measure = () => setDistance(Math.max(0, element.firstElementChild.scrollWidth - element.clientWidth))
    measure()
    if (typeof ResizeObserver === 'undefined') return undefined
    const observer = new ResizeObserver(measure)
    observer.observe(element)
    observer.observe(element.firstElementChild)
    return () => observer.disconnect()
  }, [children])
  return (
    <span ref={ref} className={`business-name-scroll${distance > 0 ? ' is-overflowing' : ''}`}
      title={children} tabIndex={distance > 0 ? 0 : undefined}
      style={{ '--name-travel': `-${distance}px`, '--name-duration': `${Math.min(18, Math.max(4, distance / 28 + 2))}s` }}>
      <span className="business-name-track">{children}</span>
    </span>
  )
}

export default function OwnerLayout() {
  const { me, logout } = useAuth()
  const businessName = me.billing_business?.business_name || me.business_name || 'Your business'
  const toast = useToast()
  const location = useLocation()
  const [theme, setThemeState] = useState(getTheme())
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false)
  const [isMobileViewport, setIsMobileViewport] = useState(() => {
    try { return window.matchMedia('(max-width: 860px)').matches } catch { return false }
  })
  const [sidebarCollapsed, setSidebarCollapsed] = useState(() => {
    try { return localStorage.getItem('task_sidebar_collapsed') === 'true' } catch { return false }
  })
  const sidebarRef = useRef(null)

  // Sync theme changes if triggered externally
  useEffect(() => {
    const onThemeChange = (e) => setThemeState(e.detail || getTheme())
    window.addEventListener('task-theme-change', onThemeChange)
    return () => window.removeEventListener('task-theme-change', onThemeChange)
  }, [])

  // Responsive listener
  useEffect(() => {
    const mql = window.matchMedia('(max-width: 860px)')
    const handler = (e) => {
      setIsMobileViewport(e.matches)
      if (!e.matches) setMobileMenuOpen(false)
    }
    mql.addEventListener('change', handler)
    return () => mql.removeEventListener('change', handler)
  }, [])

  // Close mobile drawer on route change
  useEffect(() => {
    setMobileMenuOpen(false)
  }, [location.pathname])

  // Mobile drawer focus trap & Escape key
  useEffect(() => {
    if (!isMobileViewport || !mobileMenuOpen) return undefined
    const previousFocus = document.activeElement
    const sidebar = sidebarRef.current
    const focusTimer = setTimeout(() => {
      sidebar?.querySelector('button[aria-label="Close menu"]')?.focus()
    }, 0)

    const onKeyDown = (e) => {
      if (e.key === 'Escape') {
        e.preventDefault()
        setMobileMenuOpen(false)
        return
      }
      if (e.key !== 'Tab' || !sidebar) return
      const controls = [...sidebar.querySelectorAll('a[href], button:not([disabled]), [tabindex="0"]')]
        .filter(c => c.getClientRects().length > 0)
      if (!controls.length) { e.preventDefault(); sidebar.focus(); return }
      const first = controls[0]
      const last = controls[controls.length - 1]
      if (!sidebar.contains(document.activeElement)) {
        e.preventDefault()
        ;(e.shiftKey ? last : first).focus()
      } else if (e.shiftKey && document.activeElement === first) {
        e.preventDefault()
        last.focus()
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault()
        first.focus()
      }
    }

    document.addEventListener('keydown', onKeyDown)
    return () => {
      clearTimeout(focusTimer)
      document.removeEventListener('keydown', onKeyDown)
      if (previousFocus?.isConnected) previousFocus.focus()
    }
  }, [isMobileViewport, mobileMenuOpen])

  const toggleSidebar = () => {
    const next = !sidebarCollapsed
    setSidebarCollapsed(next)
    try { localStorage.setItem('task_sidebar_collapsed', String(next)) } catch { /* ignore */ }
  }

  const copyBizId = async () => {
    try {
      await navigator.clipboard.writeText(me.public_id)
      toast('BizID copied — share it with your staff', 'success')
    } catch { /* ignore */ }
  }

  return (
    <div className="app-shell">
      {/* Mobile Drawer Overlay */}
      <div
        className={`mobile-drawer-overlay ${mobileMenuOpen ? 'open' : ''}`}
        onClick={() => setMobileMenuOpen(false)}
        aria-hidden="true"
      />

      {/* Primary Sidebar / Mobile Drawer */}
      <aside
        ref={sidebarRef}
        id="owner-navigation"
        className={`sidebar ${mobileMenuOpen ? 'open' : ''} ${sidebarCollapsed && !isMobileViewport ? 'collapsed' : ''}`}
        role={isMobileViewport ? 'dialog' : undefined}
        aria-label={isMobileViewport ? 'Navigation menu' : undefined}
        aria-modal={isMobileViewport && mobileMenuOpen ? true : undefined}
        aria-hidden={isMobileViewport && !mobileMenuOpen ? true : undefined}
        inert={isMobileViewport && !mobileMenuOpen ? '' : undefined}
        tabIndex={isMobileViewport ? -1 : undefined}
      >
        <div className="sidebar-brand">
          <BuildingMark size={32} />
          {(!sidebarCollapsed || isMobileViewport) && (
            <div style={{ flex: 1, minWidth: 0 }}>
              <div className="brand-name"><BusinessName>{businessName}</BusinessName></div>
              <div className="brand-tag">Field Team</div>
            </div>
          )}
          {isMobileViewport ? (
            <button
              type="button"
              className="btn btn-ghost btn-sm"
              onClick={() => setMobileMenuOpen(false)}
              aria-label="Close menu"
              style={{ padding: 6, marginLeft: 'auto' }}
            >
              <CloseIcon size={18} />
            </button>
          ) : (
            <button
              type="button"
              className="sidebar-collapse-btn"
              onClick={toggleSidebar}
              aria-label={sidebarCollapsed ? 'Expand sidebar' : 'Collapse sidebar'}
              title={sidebarCollapsed ? 'Expand sidebar' : 'Collapse sidebar'}
            >
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <rect x="3" y="3" width="18" height="18" rx="2" />
                <line x1="9" y1="3" x2="9" y2="21" />
              </svg>
            </button>
          )}
        </div>

        <nav className="sidebar-nav">
          {NAV.map(sec => (
            <div key={sec.section}>
              {(!sidebarCollapsed || isMobileViewport) && (
                <div className="nav-section-label">{sec.section}</div>
              )}
              {sec.items.map(it => (
                <NavLink
                  key={it.to}
                  to={it.to}
                  end={it.end}
                  title={sidebarCollapsed && !isMobileViewport ? it.label : undefined}
                  className={({ isActive }) => `nav-link${isActive ? ' active' : ''}`}
                  onClick={() => { if (isMobileViewport) setMobileMenuOpen(false) }}
                >
                  <span className="nav-icon">{it.icon}</span>
                  {(!sidebarCollapsed || isMobileViewport) && <span>{it.label}</span>}
                </NavLink>
              ))}
            </div>
          ))}
        </nav>

        <div className="sidebar-footer">
          {(!sidebarCollapsed || isMobileViewport) ? (
            <>
              <div className="business-profile-name"><BusinessName>{businessName}</BusinessName></div>
              <div className="row" style={{ gap: 6 }}>
                <button type="button" className="bizid-chip" onClick={copyBizId} title="Copy BizID">
                  {me.public_id}
                </button>
                <span className="xs muted">tap to copy</span>
              </div>
              <div className="row-between" style={{ marginTop: 2 }}>
                <button
                  type="button"
                  className="btn btn-ghost btn-sm"
                  onClick={() => setThemeState(cycleTheme())}
                  title={`Current theme: ${theme}`}
                >
                  {THEME_ICON[theme]} <span style={{ textTransform: 'capitalize' }}>{theme}</span>
                </button>
                <button type="button" className="btn btn-ghost btn-sm" onClick={logout}>
                  <LogoutIcon size={15} /> Sign out
                </button>
              </div>
            </>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 10 }}>
              <button
                type="button"
                className="btn btn-ghost btn-sm"
                onClick={() => setThemeState(cycleTheme())}
                title={`Theme: ${theme}`}
                style={{ padding: 6 }}
              >
                {THEME_ICON[theme]}
              </button>
              <button
                type="button"
                className="btn btn-ghost btn-sm"
                onClick={logout}
                title="Sign out"
                style={{ padding: 6 }}
              >
                <LogoutIcon size={16} />
              </button>
            </div>
          )}
        </div>
      </aside>

      {/* Mobile Topbar */}
      <header className="mobile-topbar">
        <div className="row" style={{ gap: 8 }}>
          <button
            type="button"
            className="mobile-menu-toggle"
            onClick={() => setMobileMenuOpen(true)}
            aria-label="Open navigation menu"
            aria-expanded={mobileMenuOpen}
            aria-controls="owner-navigation"
          >
            <MenuIcon size={20} />
          </button>
          <BuildingMark size={24} />
          <strong className="ellipsis" title={businessName} style={{ fontSize: '0.95rem' }}>{businessName}</strong>
        </div>
        <div className="row" style={{ gap: 6 }}>
          <button type="button" className="bizid-chip" onClick={copyBizId} title="Copy BizID">
            {me.public_id}
          </button>
          <button
            type="button"
            className="btn btn-ghost btn-sm"
            onClick={() => setThemeState(cycleTheme())}
            title={`Theme: ${theme}`}
            style={{ padding: 6 }}
          >
            {THEME_ICON[theme]}
          </button>
        </div>
      </header>

      {/* Main Content Area */}
      <div className="main-area">
        <div className="workspace-context">
          <div className="workspace-business"><BusinessName>{businessName}</BusinessName></div>
          <nav className="workspace-switch" aria-label="BizAssist workspaces">
            <a href={getBillingUrl()}><MonitorIcon size={15} /><span>Billing</span></a>
            <Link to="/" className="active" aria-current="page"><TruckIcon size={15} /><span>Field Team</span></Link>
          </nav>
        </div>
        <main className="page-content">
          {planBanner(me.plan) && (
            <div className="alert alert-warning" role="status" style={{ margin: '14px 0 6px' }}>
              {planBanner(me.plan)}
            </div>
          )}
          <Outlet />
        </main>
      </div>
    </div>
  )
}
