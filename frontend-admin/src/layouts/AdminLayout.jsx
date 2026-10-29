import { NavLink, Outlet, useNavigate, useLocation } from 'react-router-dom'
import { useAuth } from '../contexts/AuthContext'
import { useState, useEffect, useRef } from 'react'
import { BuildingMark } from '../components/Logo'
import { Icon } from '../components/icons'
import { useAdminTheme } from '../utils/adminPreferences'

const NAV_SECTIONS = [
  {
    section: 'Core Operations',
    items: [
      { to: '/admin/dashboard',  icon: 'dashboard', label: 'Dashboard & Router' },
      { to: '/admin/businesses', icon: 'users',     label: 'Businesses & Fleet' },
    ]
  },
  {
    section: 'Growth & Limits',
    items: [
      { to: '/admin/campaigns',  icon: 'rocket',    label: 'In-App Campaigns' },
      { to: '/admin/metrics',    icon: 'sparkle',   label: 'Platform Metrics' },
      { to: '/admin/usage',      icon: 'chart',     label: 'Usage & API Limits' },
    ]
  },
  {
    section: 'System Ops & Logs',
    items: [
      { to: '/admin/health',     icon: 'shield',    label: 'Health & Audits' },
      { to: '/admin/telemetry',  icon: 'activity',  label: 'Telemetry & Logs' },
      { to: '/admin/cache',      icon: 'server',    label: 'System Cache' },
    ]
  }
]

const PAGE_TITLES = {
  '/admin/dashboard':  'Overview & AI Router',
  '/admin/businesses': 'Business Directory & Sandboxes',
  '/admin/campaigns':  'Growth Campaigns & Promos',
  '/admin/metrics':    'Fleet Growth & Metrics',
  '/admin/usage':      'API Usage & Rate Limits',
  '/admin/health':     'System Diagnostics & Audits',
  '/admin/telemetry':  'Live Telemetry & Logs',
  '/admin/cache':      'System Cache & Database Ops',
  '/admin/settings':   'System & Admin Settings',
}

export default function AdminLayout() {
  const { adminUser, adminLogout } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()

  // Sidebar whole collapse (rail mode) - persisted in localStorage like billing
  const [sidebarCollapsed, setSidebarCollapsed] = useState(() => {
    try {
      return localStorage.getItem('admin_sidebar_collapsed') === 'true'
    } catch {
      return false
    }
  })

  const [mobileMenuOpen, setMobileMenuOpen] = useState(false)
  const [showProfileMenu, setShowProfileMenu] = useState(false)
  const [isDark, setTheme] = useAdminTheme()
  const [isMobile, setIsMobile] = useState(() => window.innerWidth <= 1024)
  const [copiedBizId, setCopiedBizId] = useState(false)
  const [copyError, setCopyError] = useState(null)
  const profileMenuRef = useRef(null)
  const sidebarRef = useRef(null)
  const mobileTriggerRef = useRef(null)
  const mobileCloseRef = useRef(null)
  const adminBizId = adminUser?.public_id || adminUser?.bizid || null

  function toggleSidebarCollapsed() {
    setSidebarCollapsed(prev => {
      const next = !prev
      try {
        localStorage.setItem('admin_sidebar_collapsed', String(next))
      } catch {}
      return next
    })
  }

  function toggleTheme(targetDark) {
    const nextDark = typeof targetDark === 'boolean' ? targetDark : !isDark
    setTheme(nextDark)
  }

  function handleLogout() {
    setShowProfileMenu(false)
    adminLogout()
    navigate('/admin/login')
  }

  async function copyAdminBizId(e) {
    if (e && e.stopPropagation) e.stopPropagation()
    if (!adminBizId) return
    setCopyError(null)
    try {
      if (!navigator.clipboard?.writeText) throw new Error('Clipboard unavailable')
      await navigator.clipboard.writeText(adminBizId)
      setCopiedBizId(true)
      setTimeout(() => setCopiedBizId(false), 2000)
    } catch { setCopyError('Could not copy. Select the BizID to copy it manually.') }
  }

  useEffect(() => {
    const onResize = () => { setIsMobile(window.innerWidth <= 1024); setMobileMenuOpen(false) }
    const onKey = event => {
      if (event.key === 'Escape') { setMobileMenuOpen(false); setShowProfileMenu(false) }
    }
    window.addEventListener('resize', onResize)
    document.addEventListener('keydown', onKey)
    return () => { window.removeEventListener('resize', onResize); document.removeEventListener('keydown', onKey) }
  }, [])

  // Close profile popover when clicking outside
  useEffect(() => {
    function handleClickOutside(e) {
      if (profileMenuRef.current && !profileMenuRef.current.contains(e.target) && !e.target.closest('.user-chip')) {
        setShowProfileMenu(false)
      }
    }
    document.addEventListener('mousedown', handleClickOutside)
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [])

  // Auto-close mobile drawer on route change
  useEffect(() => {
    setMobileMenuOpen(false)
    setShowProfileMenu(false)
  }, [location.pathname])

  useEffect(() => {
    if (!isMobile || !mobileMenuOpen) return undefined
    const sidebar = sidebarRef.current
    const trigger = mobileTriggerRef.current
    mobileCloseRef.current?.focus()
    const controls = () => Array.from(sidebar?.querySelectorAll('a[href], button:not([disabled]), [tabindex="0"]') || [])
      .filter(control => !control.closest('[hidden], [inert]') && getComputedStyle(control).display !== 'none' && getComputedStyle(control).visibility !== 'hidden')
    const onKey = event => {
      if (event.key === 'Escape') {
        event.preventDefault()
        event.stopImmediatePropagation()
        setMobileMenuOpen(false)
        setShowProfileMenu(false)
      } else if (event.key === 'Tab') {
        const buttons = controls()
        const first = buttons[0]
        const last = buttons[buttons.length - 1]
        if (!sidebar?.contains(document.activeElement)) {
          event.preventDefault()
          ;(event.shiftKey ? last : first)?.focus()
        } else if (event.shiftKey && document.activeElement === first) {
          event.preventDefault(); last?.focus()
        } else if (!event.shiftKey && document.activeElement === last) {
          event.preventDefault(); first?.focus()
        }
      }
    }
    const keepFocus = event => {
      if (!sidebar?.contains(event.target)) mobileCloseRef.current?.focus()
    }
    document.addEventListener('keydown', onKey, true)
    document.addEventListener('focusin', keepFocus, true)
    return () => {
      document.removeEventListener('keydown', onKey, true)
      document.removeEventListener('focusin', keepFocus, true)
      if (trigger?.isConnected) trigger.focus()
    }
  }, [isMobile, mobileMenuOpen])

  const currentTitle = PAGE_TITLES[location.pathname] || 'Admin Console'

  return (
    <div className="app-shell">
      {/* ── SIDEBAR (Matching frontend-billing Architecture) ── */}
      <aside
        ref={sidebarRef}
        id="admin-sidebar"
        className={`sidebar ${mobileMenuOpen ? 'open' : ''} ${sidebarCollapsed && !isMobile ? 'collapsed' : ''}`}
        aria-label="Admin Navigation"
        role={isMobile ? 'dialog' : undefined}
        aria-modal={isMobile && mobileMenuOpen ? true : undefined}
        aria-hidden={isMobile && !mobileMenuOpen ? true : undefined}
        inert={isMobile && !mobileMenuOpen ? '' : undefined}
        tabIndex={isMobile ? -1 : undefined}
      >
        {/* Rail Collapse Button */}
        {!isMobile && <button
          type="button"
          className="sidebar-collapse-btn"
          onClick={toggleSidebarCollapsed}
          aria-label={sidebarCollapsed ? 'Expand sidebar' : 'Collapse sidebar'}
          title={sidebarCollapsed ? 'Expand sidebar' : 'Collapse sidebar'}
        >
          <Icon name="sidebarCollapse" size={17} />
        </button>}
        {isMobile && <button type="button" ref={mobileCloseRef} className="sidebar-mobile-close" aria-label="Close navigation menu" onClick={() => setMobileMenuOpen(false)}>
          <Icon name="x" size={18} />
        </button>}

        {/* Brand Block */}
        <div className="sidebar-brand">
          <BuildingMark size={28} />
          <div style={{ flex: 1, minWidth: 0 }}>
            <div className="brand-name">BIZASSIST</div>
            <div className="brand-tag">ADMIN CONSOLE</div>
          </div>
        </div>

        {/* Navigation Sections */}
        <nav className="sidebar-nav">
          {NAV_SECTIONS.map((group) => (
            <div key={group.section} style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
              <div className="nav-section-label">{group.section}</div>
              {group.items.map((item) => (
                <NavLink
                  key={item.to}
                  to={item.to}
                  className="nav-link"
                  data-label={item.label}
                  aria-label={item.label}
                  title={item.label}
                  onClick={() => { setMobileMenuOpen(false); setShowProfileMenu(false) }}
                >
                  <span className="nav-icon">
                    <Icon name={item.icon} size={16} />
                  </span>
                  <span className="nav-label">{item.label}</span>
                </NavLink>
              ))}
            </div>
          ))}

          {/* Preferences Section */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
            <div className="nav-section-label">Preferences</div>
            <NavLink
              to="/admin/settings"
              className="nav-link"
              data-label="Admin Settings"
              aria-label="Admin Settings"
              title="Admin Settings"
              onClick={() => { setMobileMenuOpen(false); setShowProfileMenu(false) }}
            >
              <span className="nav-icon">
                <Icon name="settings" size={16} />
              </span>
              <span className="nav-label">Admin Settings</span>
            </NavLink>
          </div>
        </nav>

        {/* Sidebar Footer with Operator Profile & Settings Menu */}
        <div className="sidebar-footer">
          {/* Profile Menu Popover */}
          {showProfileMenu && (
            <div className="profile-menu" id="admin-profile-menu" ref={profileMenuRef}>
              <div className="profile-menu-header">
                <div className="profile-menu-biz">{adminUser?.username || 'admin'}</div>
                <div className="profile-menu-sub">Super Administrator</div>
              </div>

              {/* BizID Copy Affordance */}
              <button
                type="button"
                disabled={!adminBizId}
                onClick={copyAdminBizId}
                className="profile-menu-item"
                style={{ fontFamily: 'var(--font-mono)', fontSize: 12 }}
                title="Click to copy Admin BizID"
              >
                <Icon name={copiedBizId ? "check" : "copy"} size={13} style={{ color: copiedBizId ? 'var(--success)' : 'inherit' }} />
                <span>BizID: {adminBizId || 'Unavailable'}</span>
                {copiedBizId && <span style={{ marginLeft: 'auto', fontSize: 10, color: 'var(--success)' }}>Copied</span>}
              </button>
              {copyError && <p role="status" style={{ fontSize: 12, padding: '0 10px', color: 'var(--danger)' }}>{copyError}</p>}

              <NavLink
                to="/admin/settings"
                className="profile-menu-item"
                onClick={() => setShowProfileMenu(false)}
              >
                <Icon name="settings" size={14} />
                <span>System Settings</span>
              </NavLink>

              <div className="profile-theme-toggle">
                <button
                  type="button"
                  className={`profile-theme-btn ${!isDark ? 'active' : ''}`}
                  onClick={() => toggleTheme(false)}
                  title="Light Theme"
                >
                  <Icon name="sun" size={13} />
                  <span>Light</span>
                </button>
                <button
                  type="button"
                  className={`profile-theme-btn ${isDark ? 'active' : ''}`}
                  onClick={() => toggleTheme(true)}
                  title="Dark Theme"
                >
                  <Icon name="moon" size={13} />
                  <span>Dark</span>
                </button>
              </div>

              <button
                type="button"
                onClick={handleLogout}
                className="profile-menu-item logout"
              >
                <Icon name="logout" size={14} />
                <span>Sign Out</span>
              </button>
            </div>
          )}

          {/* User Profile Chip */}
          <button
            type="button"
            className="user-chip"
            title="Settings & Profile Menu"
            aria-label="Settings and profile menu"
            aria-expanded={showProfileMenu}
            aria-controls="admin-profile-menu"
            onClick={() => setShowProfileMenu(prev => !prev)}
          >
            <div className="user-avatar">
              AD
            </div>
            <div className="user-info">
              <div className="user-name">{adminUser?.username || 'admin'}</div>
              <div className="user-role">Super Admin</div>
            </div>
          </button>
        </div>
      </aside>

      {/* Backdrop for Mobile Drawer */}
      {mobileMenuOpen && (
        <div
          className="sidebar-backdrop"
          onClick={() => setMobileMenuOpen(false)}
        />
      )}

      {/* ── RIGHT MAIN AREA ── */}
      <div className="main-area" inert={isMobile && mobileMenuOpen ? '' : undefined} aria-hidden={isMobile && mobileMenuOpen ? true : undefined}>
        {/* Top Header Bar */}
        <header className="topbar">
          <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
            {/* Mobile Hamburger Menu Toggle */}
            {isMobile && <button
              ref={mobileTriggerRef}
              type="button"
              className="admin-hamburger"
              onClick={() => setMobileMenuOpen(prev => !prev)}
              style={{
                background: 'transparent',
                border: '1px solid var(--border)',
                borderRadius: 'var(--radius-md, 8px)',
                padding: '6px',
                cursor: 'pointer',
                color: 'var(--text-primary)'
              }}
              title="Open Navigation Menu"
              aria-label="Open navigation menu"
              aria-expanded={mobileMenuOpen}
              aria-controls="admin-sidebar"
            >
              <Icon name="menu" size={18} />
            </button>}

            {/* Breadcrumb & Title */}
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <span style={{ fontSize: 13, fontWeight: 500, color: 'var(--text-muted)' }}>BizAssist Admin</span>
              <span style={{ color: 'var(--border)' }}>/</span>
              <span style={{ fontSize: 13.5, fontWeight: 600, color: 'var(--text-primary)' }}>{currentTitle}</span>
            </div>
          </div>

          {/* Quick Actions & Status */}
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            {/* System Status Indicator */}
            <div style={{
              display: 'inline-flex',
              alignItems: 'center',
              gap: 6,
              padding: '3px 9px',
              borderRadius: 999,
              background: 'var(--accent-dim)',
              border: '1px solid var(--border)',
              fontSize: 11,
              fontWeight: 600,
              color: 'var(--text-secondary)',
              letterSpacing: '0.02em'
            }}>
              <span>Admin Console</span>
            </div>

            {/* Quick Settings Icon */}
            <NavLink
              to="/admin/settings"
              className="btn-flush"
              style={{
                padding: '6px 8px',
                borderRadius: 'var(--radius-md, 8px)',
                display: 'inline-flex',
                alignItems: 'center',
                justifyContent: 'center',
                color: 'var(--text-secondary)'
              }}
              title="Admin Settings"
            >
              <Icon name="settings" size={16} />
            </NavLink>

            {/* Quick Theme Toggle */}
            <button
              type="button"
              onClick={() => toggleTheme()}
              className="btn-flush"
              style={{
                padding: '6px 8px',
                borderRadius: 'var(--radius-md, 8px)',
                display: 'inline-flex',
                alignItems: 'center',
                justifyContent: 'center',
                color: 'var(--text-secondary)'
              }}
              title={isDark ? 'Switch to Light Theme' : 'Switch to Dark Theme'}
            >
              <Icon name={isDark ? 'sun' : 'moon'} size={16} />
            </button>

            {/* Exit / Sign Out */}
            <button
              type="button"
              onClick={handleLogout}
              className="btn-flush"
              style={{
                padding: '6px 12px',
                fontSize: 12.5,
                borderRadius: 'var(--radius-md, 8px)',
                gap: 6,
              }}
              title="Sign Out of Admin Console"
            >
              <Icon name="logout" size={14} />
              <span>Exit</span>
            </button>
          </div>
        </header>

        {/* Main Routed Content */}
        <main className={`app-main ${location.pathname === '/admin/settings' ? 'app-main-split' : ''}`}>
          <Outlet />
        </main>
      </div>
    </div>
  )
}
