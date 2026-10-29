import React, { useEffect, useRef, useState } from 'react'
import { Link, NavLink, Outlet, useLocation } from 'react-router-dom'
import { useAuth } from '../lib/auth'
import { planBanner } from '../lib/plan'
import { getTheme, setTheme } from '../lib/theme'
import { BuildingMark } from '../components/Logo'
import { useToast } from '../components/ui'
import {
  AwardIcon, CheckIcon, ClipboardIcon, ClockIcon, CloseIcon, ContactsIcon, CopyIcon, DashboardIcon,
  ListIcon, LogoutIcon, MapPinIcon, MenuIcon, MonitorIcon, MoonIcon, OrderIcon, RouteIcon,
  SettingsIcon, SunIcon, TruckIcon, UserIcon,
} from '../components/Icons'
import WorkspaceSwitcher from '../components/WorkspaceSwitcher'

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

function BusinessName({ children }) {
  const ref = useRef(null)
  const [distance, setDistance] = useState(0)
  useEffect(() => {
    const element = ref.current
    if (!element || !element.firstElementChild) return undefined
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
  const businessName = me?.billing_business?.business_name || me?.business_name || 'Your business'
  const toast = useToast()
  const location = useLocation()
  const [theme, setThemeState] = useState(getTheme())
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false)
  const [showProfileMenu, setShowProfileMenu] = useState(false)
  const [copiedBizId, setCopiedBizId] = useState(false)
  const [isMobileViewport, setIsMobileViewport] = useState(() => {
    try { return window.matchMedia('(max-width: 860px)').matches } catch { return false }
  })
  const [sidebarCollapsed, setSidebarCollapsed] = useState(() => {
    try { return localStorage.getItem('task_sidebar_collapsed') === 'true' } catch { return false }
  })
  const sidebarRef = useRef(null)
  const profileMenuRef = useRef(null)
  const mobileProfileMenuRef = useRef(null)

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

  // Close mobile drawer and profile popover on route change
  useEffect(() => {
    setMobileMenuOpen(false)
    setShowProfileMenu(false)
  }, [location.pathname])

  // Close profile popover when clicking outside or pressing Escape
  useEffect(() => {
    function handleClickOutside(e) {
      if (
        profileMenuRef.current &&
        !profileMenuRef.current.contains(e.target) &&
        !e.target.closest('.user-chip') &&
        !e.target.closest('.mobile-user-avatar')
      ) {
        setShowProfileMenu(false)
      }
    }
    function handleKeyDown(e) {
      if (e.key === 'Escape') {
        setShowProfileMenu(false)
      }
    }
    document.addEventListener('mousedown', handleClickOutside)
    document.addEventListener('keydown', handleKeyDown)
    return () => {
      document.removeEventListener('mousedown', handleClickOutside)
      document.removeEventListener('keydown', handleKeyDown)
    }
  }, [])

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
      await navigator.clipboard.writeText(me?.public_id || '')
      setCopiedBizId(true)
      toast('BizID copied — share it with your staff', 'success')
      setTimeout(() => setCopiedBizId(false), 2000)
    } catch { /* ignore */ }
  }

  const handleSetTheme = (mode) => {
    setTheme(mode)
    setThemeState(mode)
  }

  const displayName = me?.billing_business?.business_name || me?.business_name || me?.name || 'Owner'
  const initials = (displayName || 'FT')
    .split(' ')
    .filter(Boolean)
    .slice(0, 2)
    .map(w => w[0]?.toUpperCase())
    .join('') || 'FT'
  const logo = me?.billing_business?.logo || me?.logo || null

  const renderProfileMenu = (isMobileDropdown = false) => (
    <div
      className={`profile-menu ${isMobileDropdown ? 'mobile-dropdown' : ''}`}
      ref={isMobileDropdown ? mobileProfileMenuRef : profileMenuRef}
      onClick={e => e.stopPropagation()}
      onMouseDown={e => e.stopPropagation()}
    >
      <div className="profile-menu-header">
        <div className="profile-menu-biz" title={businessName}>{businessName}</div>
        <div className="profile-menu-sub">Field Team Workspace</div>
      </div>

      <div className="profile-menu-sep" />

      {/* Workspace Switcher Pill */}
      <div style={{ padding: '8px 12px', display: 'flex', justifyContent: 'center' }}>
        <WorkspaceSwitcher activeWorkspace="field" />
      </div>

      <div className="profile-menu-sep" />

      {/* BizID Click-to-copy */}
      {me?.public_id && (
        <button
          type="button"
          className="profile-menu-item"
          onClick={copyBizId}
          title="Click to copy BizID"
          style={{ fontFamily: 'var(--font-mono, monospace)', fontSize: '0.82rem' }}
        >
          {copiedBizId ? <CheckIcon size={14} style={{ color: 'var(--success, #16a34a)' }} /> : <CopyIcon size={14} />}
          <span>BizID: {me.public_id}</span>
        </button>
      )}

      <div className="profile-menu-sep" />

      {/* Menu items */}
      <Link
        className="profile-menu-item"
        to="/settings"
        onClick={() => setShowProfileMenu(false)}
      >
        <SettingsIcon size={14} /> <span>App Settings</span>
      </Link>

      <Link
        className="profile-menu-item"
        to="/activity"
        onClick={() => setShowProfileMenu(false)}
      >
        <ListIcon size={14} /> <span>Activity Log</span>
      </Link>

      <Link
        className="profile-menu-item"
        to="/attendance"
        onClick={() => setShowProfileMenu(false)}
      >
        <ClockIcon size={14} /> <span>Attendance</span>
      </Link>

      <Link
        className="profile-menu-item"
        to="/scorecard"
        onClick={() => setShowProfileMenu(false)}
      >
        <AwardIcon size={14} /> <span>Scorecard</span>
      </Link>

      <button
        type="button"
        className="profile-menu-item logout"
        onClick={() => {
          setShowProfileMenu(false)
          logout()
        }}
      >
        <LogoutIcon size={14} /> <span>Sign Out</span>
      </button>

      {/* Theme Selector */}
      <div className="profile-menu-theme">
        <span className="profile-menu-theme-label">Theme</span>
        <div className="profile-theme-toggle">
          <button
            type="button"
            className={`theme-opt-btn ${theme === 'light' ? 'active' : ''}`}
            onClick={() => handleSetTheme('light')}
            title="Light Mode"
          >
            <SunIcon size={14} />
          </button>
          <button
            type="button"
            className={`theme-opt-btn ${theme === 'dark' ? 'active' : ''}`}
            onClick={() => handleSetTheme('dark')}
            title="Dark Mode"
          >
            <MoonIcon size={14} />
          </button>
          <button
            type="button"
            className={`theme-opt-btn ${theme === 'system' ? 'active' : ''}`}
            onClick={() => handleSetTheme('system')}
            title="System Mode"
          >
            <MonitorIcon size={14} />
          </button>
        </div>
      </div>
    </div>
  )

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

        {/* Sidebar Footer with User Profile Chip & Popover */}
        <div className="sidebar-footer">
          {showProfileMenu && !isMobileViewport && renderProfileMenu(false)}

          <div className="sidebar-profile-row">
            <button
              type="button"
              className="user-chip"
              title="Settings & Profile Menu"
              aria-label="Settings and profile menu"
              aria-expanded={showProfileMenu}
              onClick={() => setShowProfileMenu(prev => !prev)}
            >
              <div className="user-avatar">
                {logo ? (
                  <img src={logo} alt="Logo" style={{ width: '100%', height: '100%', objectFit: 'contain', borderRadius: '50%' }} />
                ) : (
                  initials
                )}
              </div>
              {(!sidebarCollapsed || isMobileViewport) && (
                <div className="user-info">
                  <div className="user-name">
                    <BusinessName>{businessName}</BusinessName>
                  </div>
                  <div className="user-role">Settings Menu</div>
                </div>
              )}
            </button>
          </div>
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
        <div className="row" style={{ gap: 6, position: 'relative' }}>
          <button
            type="button"
            className="user-avatar mobile-user-avatar"
            onClick={() => setShowProfileMenu(prev => !prev)}
            style={{ width: 32, height: 32, fontSize: 12, cursor: 'pointer' }}
            title="Settings & Profile Menu"
            aria-label="Settings and profile menu"
            aria-expanded={showProfileMenu}
          >
            {logo ? (
              <img src={logo} alt="Logo" style={{ width: '100%', height: '100%', objectFit: 'contain', borderRadius: '50%' }} />
            ) : (
              initials
            )}
          </button>
          {isMobileViewport && showProfileMenu && renderProfileMenu(true)}
        </div>
      </header>

      {/* Main Content Area — No top bar, clean aligned layout */}
      <div className="main-area">
        <main className="page-content">
          {planBanner(me?.plan) && (
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
