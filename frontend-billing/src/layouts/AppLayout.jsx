import React from 'react'
import { NavLink, useNavigate, useLocation } from 'react-router-dom'
import { useAuth } from '../contexts/AuthContext'
import { BuildingMark } from '../components/Logo'
import PageLoader from '../components/PageLoader'
import { BillsIcon, CashIcon, ChevronDownIcon, CloseIcon, ConnectionIcon, ContactsIcon, CounterIcon, DashboardIcon, HomeIcon, ImportIcon, InventoryIcon, LogoutIcon, OrderIcon, ReportsIcon, SettingsIcon, SummaryIcon, TaxIcon, ZapIcon, SunIcon, MoonIcon, MonitorIcon, UserIcon } from '../components/Icons'

const NAV = [
  {
    section: 'Supply & Inflow',
    items: [
      { to: '/orders', icon: <OrderIcon size={16} />, label: 'Supplier Orders' },
      { to: '/purchases', icon: <BillsIcon size={16} />, label: 'Purchase Bills' },
      { to: '/connections', icon: <ConnectionIcon size={16} />, label: 'Store Sync' },
      { to: '/import', icon: <ImportIcon size={16} />, label: 'Data Migration' },
    ]
  },
  {
    section: 'Hub',
    items: [
      { to: '/',          icon: <HomeIcon size={16} />, label: 'Home'      },
      { to: '/dashboard', icon: <DashboardIcon size={16} />, label: 'Dashboard' },
    ]
  },
  {
    section: 'Sales & Operations',
    items: [
      { to: '/sales', icon: <CounterIcon size={16} />, label: 'Billing Counter' },
      { to: '/payments', icon: <CashIcon size={16} />, label: 'Cash Book' },
      { to: '/parties', icon: <ContactsIcon size={16} />, label: 'Contacts & Dues' },
      { to: '/reports', icon: <ReportsIcon size={16} />, label: 'GST & Tax Reports' },
    ]
  }
]

// Flat list for sub-navbar (only key pages, grouped)
const SUBNAV = [
  { to: '/',           label: 'Home',         icon: <HomeIcon size={14} /> },
  { to: '/dashboard',  label: 'Dashboard',    icon: <DashboardIcon size={14} /> },
  { to: '/sales',      label: 'Billing',      icon: <CounterIcon size={14} /> },
  { to: '/payments',   label: 'Cash Book',    icon: <CashIcon size={14} /> },
  { to: '/parties',    label: 'Contacts',     icon: <ContactsIcon size={14} /> },
  { to: '/stock',      label: 'Inventory',    icon: <InventoryIcon size={14} /> },
  { to: '/purchases',  label: 'Purchases',    icon: <BillsIcon size={14} /> },
  { to: '/reports',    label: 'Reports',      icon: <ReportsIcon size={14} /> },
]

// Map route -> page title
const PAGE_TITLES = {
  '/':            'Home',
  '/dashboard':   'Dashboard',
  '/sales':       'Billing Counter',
  '/payments':    'Cash Book',
  '/parties':     'Contacts & Dues',
  '/stock':       'Inventory',
  '/purchases':   'Purchase Bills',
  '/connections': 'Store Sync',
  '/orders':      'Supplier Orders',
  '/reports':     'GST & Tax Reports',
  '/import':      'Data Migration',
  '/profile':     'My Profile',
  '/staff':       'Staff & Cashiers',
  '/settings':    'App Settings',
}

export default function AppLayout({ children, title }) {
  const { user, logout, profile, token, businessConfig, appReady, setAppReady } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()

  React.useEffect(() => {
    if (appReady) return

    let minElapsed = false
    let maxElapsed = false

    const checkReady = () => {
      const dataLoaded = token ? (profile !== null && businessConfig !== null) : true
      if ((dataLoaded && minElapsed) || maxElapsed) {
        setAppReady(true)
      }
    }

    const minTimer = setTimeout(() => {
      minElapsed = true
      checkReady()
    }, 1000)

    const maxTimer = setTimeout(() => {
      maxElapsed = true
      setAppReady(true)
    }, 5000)

    checkReady()

    return () => {
      clearTimeout(minTimer)
      clearTimeout(maxTimer)
    }
  }, [appReady, setAppReady, token, profile, businessConfig])

  // Role gating (defense-in-depth — the backend restrict_cashier guard is the
  // real authority; this just hides owner-only destinations from cashiers).
  const isCashier = (user?.role || '').toLowerCase() === 'cashier'
  const OWNER_ONLY_PATHS = new Set(['/purchases', '/connections', '/orders', '/reports', '/import', '/settings', '/staff'])
  const visibleNav = isCashier
    ? NAV.map(s => ({ ...s, items: s.items.filter(i => !OWNER_ONLY_PATHS.has(i.to)) })).filter(s => s.items.length > 0)
    : NAV

  // Track collapsed state per section with localStorage persistence
  const [collapsed, setCollapsed] = React.useState(() => {
    try {
      const saved = localStorage.getItem('sidebar_collapsed_sections')
      if (saved) {
        return JSON.parse(saved)
      }
    } catch (e) {
      console.error(e)
    }
    return {
      'Hub': true,
      'Sales & Operations': true,
      'Supply & Inflow': true,
    }
  })

  // Persist collapsed state to localStorage
  React.useEffect(() => {
    try {
      localStorage.setItem('sidebar_collapsed_sections', JSON.stringify(collapsed))
    } catch (e) {
      console.error(e)
    }
  }, [collapsed])

  // Auto-expand a collapsed section if one of its child routes is active
  React.useEffect(() => {
    NAV.forEach(({ section, items }) => {
      const hasActiveChild = items.some(item => location.pathname === item.to)
      if (hasActiveChild && collapsed[section]) {
        setCollapsed(prev => ({ ...prev, [section]: false }))
      }
    })
  }, [location.pathname])

  // Theme support
  const [theme, setTheme] = React.useState(() => {
    return localStorage.getItem('billing_theme') || 'light'
  })

  React.useEffect(() => {
    const root = document.documentElement
    root.classList.remove('dark-mode')
    
    const applyTheme = (t) => {
      if (t === 'dark') {
        root.classList.add('dark-mode')
      } else if (t === 'light') {
        root.classList.remove('dark-mode')
      } else if (t === 'system') {
        const isSystemDark = window.matchMedia('(prefers-color-scheme: dark)').matches
        if (isSystemDark) {
          root.classList.add('dark-mode')
        } else {
          root.classList.remove('dark-mode')
        }
      }
    }
    
    applyTheme(theme)
    localStorage.setItem('billing_theme', theme)
    
    if (theme === 'system') {
      const mediaQuery = window.matchMedia('(prefers-color-scheme: dark)')
      const handler = (e) => {
        if (e.matches) {
          root.classList.add('dark-mode')
        } else {
          root.classList.remove('dark-mode')
        }
      }
      mediaQuery.addEventListener('change', handler)
      return () => mediaQuery.removeEventListener('change', handler)
    }
  }, [theme])

  // Profile popover menu
  const [showProfileMenu, setShowProfileMenu] = React.useState(false)
  const profileMenuRef = React.useRef(null)
  const userChipRef = React.useRef(null)

  React.useEffect(() => {
    const handleOutsideClick = (e) => {
      if (
        profileMenuRef.current &&
        !profileMenuRef.current.contains(e.target) &&
        userChipRef.current &&
        !userChipRef.current.contains(e.target)
      ) {
        setShowProfileMenu(false)
      }
    }
    document.addEventListener('mousedown', handleOutsideClick)
    return () => document.removeEventListener('mousedown', handleOutsideClick)
  }, [])

  const [minimizedBill, setMinimizedBill] = React.useState(null)

  const checkMinimized = React.useCallback(() => {
    const isMinimized = localStorage.getItem('pos_minimized') === 'true'
    const savedTabsStr = localStorage.getItem('pos_minimized_tabs')
    if (isMinimized && savedTabsStr) {
      try {
        const savedTabs = JSON.parse(savedTabsStr)
        if (Array.isArray(savedTabs) && savedTabs.length > 0) {
          const activeId = localStorage.getItem('pos_minimized_active_id')
          const activeTab = savedTabs.find(t => t.id === activeId) || savedTabs[0]
          
          const itemsCount = activeTab.form?.items?.length || 0
          const totalAmt = activeTab.form?.items?.reduce((sum, item) => {
            const q = parseFloat(item.qty) || 0
            const p = parseFloat(item.price) || 0
            const d = parseFloat(item.discount) || 0
            return sum + Math.max(0, (q * p) - d)
          }, 0) || 0

          setMinimizedBill({
            name: activeTab.name,
            itemsCount,
            totalAmt,
            tabsCount: savedTabs.length
          })
          return
        }
      } catch (e) {
        console.error(e)
      }
    }
    setMinimizedBill(null)
  }, [])

  React.useEffect(() => {
    checkMinimized()
    window.addEventListener('pos_minimized_changed', checkMinimized)
    return () => window.removeEventListener('pos_minimized_changed', checkMinimized)
  }, [checkMinimized])

  React.useEffect(() => {
    if (location.pathname !== '/sales') {
      sessionStorage.setItem('last_page', location.pathname)
    }
  }, [location.pathname])

  React.useEffect(() => {
    if (title) {
      document.title = `${title} | BizAssist`
    }
  }, [title])

  const toggleSection = (section) => {
    setCollapsed(prev => ({ ...prev, [section]: !prev[section] }))
  }

  const initials = user?.username
    ? user.username.slice(0, 2).toUpperCase()
    : 'BZ'

  const isSalesPage = location.pathname === '/sales'
  const pageTitle = title || PAGE_TITLES[location.pathname] || 'BizAssist'

  return (
    <div className={`app-shell ${isSalesPage ? 'pos-layout-shell' : ''}`}>
      {!appReady && <PageLoader />}
      {/* ── Sidebar ── */}
      {!isSalesPage && (
        <aside className="sidebar">
          {/* Brand */}
          <div className="sidebar-brand">
            {profile?.logo ? (
              <img src={profile.logo} alt="Logo" style={{ width: 36, height: 36, objectFit: 'contain', borderRadius: 'var(--radius-sm)' }} />
            ) : (
              <BuildingMark size={30} />
            )}
            <div>
              <div className="brand-name">{profile?.business_name || user?.business_name || 'BizAssist'}</div>
              <div className="brand-tag">
                Auto Sync
                <span className="sync-pulse" title="Auto Sync Active" />
              </div>
            </div>
          </div>

          {/* Nav */}
          <nav className="sidebar-nav">
            {visibleNav.map(({ section, items }) => {
              const isCollapsed = collapsed[section]
              return (
                <React.Fragment key={section}>
                  <div
                    className="nav-section-label"
                    onClick={() => toggleSection(section)}
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'space-between',
                      cursor: 'pointer',
                      userSelect: 'none',
                      padding: '8px 10px',
                      borderRadius: 'var(--radius-sm)',
                      transition: 'background var(--dur) var(--ease)'
                    }}
                    onMouseEnter={e => e.currentTarget.style.backgroundColor = 'var(--accent-dim)'}
                    onMouseLeave={e => e.currentTarget.style.backgroundColor = 'transparent'}
                  >
                    <span>{section}</span>
                    <span style={{
                      display: 'flex',
                      alignItems: 'center',
                      color: 'var(--text-secondary)',
                      transition: 'transform var(--dur) var(--ease)',
                      transform: isCollapsed ? 'rotate(-90deg)' : 'rotate(0deg)'
                    }}>
                      <ChevronDownIcon size={12} />
                    </span>
                  </div>

                  {!isCollapsed && items.map(({ to, icon, label }) => (
                    <NavLink
                      key={to}
                      to={to}
                      end={to === '/'}
                      className={({ isActive }) =>
                        'nav-link' + (isActive ? ' active' : '')
                      }
                    >
                      <span className="nav-icon">{icon}</span>
                      {label}
                    </NavLink>
                  ))}
                </React.Fragment>
              )
            })}
          </nav>

          {/* Footer / User */}
          <div className="sidebar-footer">
            {minimizedBill && (
              <div style={{
                background: 'var(--accent-dim)',
                border: '1.5px solid var(--accent)',
                borderRadius: 'var(--radius-md)',
                padding: '10px 12px',
                marginBottom: '12px',
                display: 'flex',
                flexDirection: 'column',
                gap: 6,
                boxShadow: 'var(--shadow-sm)',
                cursor: 'pointer',
                position: 'relative',
                transition: 'transform var(--dur) var(--ease), border-color var(--dur) var(--ease)'
              }}
              onClick={() => {
                localStorage.removeItem('pos_minimized');
                window.dispatchEvent(new Event('pos_minimized_changed'));
                navigate('/sales');
              }}
              onMouseEnter={e => {
                e.currentTarget.style.borderColor = 'var(--accent-light)';
                e.currentTarget.style.transform = 'translateY(-1px)';
              }}
              onMouseLeave={e => {
                e.currentTarget.style.borderColor = 'var(--accent)';
                e.currentTarget.style.transform = 'translateY(0)';
              }}
              >
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <span style={{ fontSize: '0.78rem', fontWeight: 700, color: 'var(--accent)', letterSpacing: '0.02em' }}>
                    <ZapIcon size={14} style={{ color: 'var(--accent)', marginRight: 6, display: 'inline-block', verticalAlign: 'middle' }} /> Minimized Invoice
                  </span>
                  <button
                    style={{
                      background: 'none',
                      border: 'none',
                      color: 'var(--text-muted)',
                      cursor: 'pointer',
                      fontSize: '0.75rem',
                      padding: '2px 4px',
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      lineHeight: 1
                    }}
                    onClick={(e) => {
                      e.stopPropagation();
                      if (window.confirm('Discard active draft billing session?')) {
                        localStorage.removeItem('pos_minimized');
                        localStorage.removeItem('pos_minimized_tabs');
                        localStorage.removeItem('pos_minimized_active_id');
                        window.dispatchEvent(new Event('pos_minimized_changed'));
                      }
                    }}
                   aria-label="Close"><CloseIcon size={16} /></button>
                </div>
                <div style={{ fontSize: '0.82rem', fontWeight: 600, color: 'var(--text-primary)' }}>
                  {minimizedBill.name} {minimizedBill.tabsCount > 1 ? `(+${minimizedBill.tabsCount - 1} tabs)` : ''}
                </div>
                <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.72rem', color: 'var(--text-secondary)', marginTop: 2 }}>
                  <span>{minimizedBill.itemsCount} items</span>
                  <span style={{ fontWeight: 700, color: 'var(--success)' }}>
                    ₹{minimizedBill.totalAmt.toLocaleString('en-IN', { maximumFractionDigits: 2 })}
                  </span>
                </div>
              </div>
            )}
            
            {showProfileMenu && (
              <div className="profile-menu" ref={profileMenuRef}>
                <div className="profile-menu-header">
                  <div className="profile-menu-biz">{profile?.business_name || user?.username || 'BizAssist User'}</div>
                  <div className="profile-menu-sub">Enterprise Account</div>
                </div>
                <div className="profile-menu-sep" />
                <button className="profile-menu-item" onClick={() => { setShowProfileMenu(false); navigate('/profile'); }}>
                  <UserIcon size={14} /> My Profile
                </button>
                <button className="profile-menu-item" onClick={() => { setShowProfileMenu(false); navigate('/settings'); }}>
                  <SettingsIcon size={14} /> App Settings
                </button>
                <button className="profile-menu-item" onClick={() => { setShowProfileMenu(false); navigate('/staff'); }}>
                  <ContactsIcon size={14} /> Staff & Cashiers
                </button>
                <button className="profile-menu-item logout" onClick={() => { setShowProfileMenu(false); logout(); navigate('/login'); }}>
                  <LogoutIcon size={14} /> Sign Out
                </button>
                <div className="profile-menu-theme">
                  <span className="profile-menu-theme-label">Theme</span>
                  <div className="profile-theme-toggle">
                    <button className={`theme-opt-btn ${theme === 'light' ? 'active' : ''}`} onClick={() => setTheme('light')} title="Light Mode">
                      <SunIcon size={14} />
                    </button>
                    <button className={`theme-opt-btn ${theme === 'dark' ? 'active' : ''}`} onClick={() => setTheme('dark')} title="Dark Mode">
                      <MoonIcon size={14} />
                    </button>
                    <button className={`theme-opt-btn ${theme === 'system' ? 'active' : ''}`} onClick={() => setTheme('system')} title="System Mode">
                      <MonitorIcon size={14} />
                    </button>
                  </div>
                </div>
              </div>
            )}

            <div className="user-chip" title="Settings & Profile" ref={userChipRef} onClick={() => setShowProfileMenu(!showProfileMenu)}>
              <div className="user-avatar">
                {profile?.logo ? (
                  <img src={profile.logo} alt="Logo" style={{ width: '100%', height: '100%', objectFit: 'contain', borderRadius: '50%' }} />
                ) : (
                  initials
                )}
              </div>
              <div className="user-info">
                <div className="user-name">{profile?.business_name || user?.username || 'User'}</div>
                <div className="user-role">
                  Settings Menu
                </div>
              </div>
            </div>
          </div>
        </aside>
      )}

      {/* ── Main area ── */}
      <div className="main-area">
        {/* ── Page content ── */}
        <main className="page-content">
          {children}
        </main>
      </div>
    </div>
  )
}
