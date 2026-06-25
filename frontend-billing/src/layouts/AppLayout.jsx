import React from 'react'
import { NavLink, useNavigate, useLocation } from 'react-router-dom'
import { useAuth } from '../contexts/AuthContext'
import { useLock } from '../contexts/LockContext'
import { API_BASE } from '../config'
import { BuildingMark } from '../components/Logo'
import PageLoader from '../components/PageLoader'
import { BillsIcon, CashIcon, ChevronDownIcon, CloseIcon, ConnectionIcon, ContactsIcon, CounterIcon, DashboardIcon, HomeIcon, ImportIcon, InventoryIcon, LockIcon, LogoutIcon, OrderIcon, ReportsIcon, SettingsIcon, SummaryIcon, TaxIcon, ZapIcon, SunIcon, MoonIcon, MonitorIcon, UserIcon, CheckIcon, AlertIcon, SyncIcon } from '../components/Icons'


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
      { to: '/sales',    icon: <CounterIcon size={16} />,   label: 'Billing Counter' },
      { to: '/payments', icon: <CashIcon size={16} />,      label: 'Cash Book' },
      { to: '/parties',  icon: <ContactsIcon size={16} />,  label: 'Contacts & Dues' },
      { to: '/stock',    icon: <InventoryIcon size={16} />, label: 'Inventory' },
      { to: '/reports',  icon: <ReportsIcon size={16} />,   label: 'GST & Tax Reports' },
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
  const { user, logout, profile, token, businessConfig, appReady, setAppReady, settings } = useAuth()
  const { hasLock, lock, resetInactivityTimer } = useLock()
  const navigate = useNavigate()
  const location = useLocation()

  const hostingMode = settings?.general?.hosting_mode || 'local'
  const isSyncOn = hostingMode === 'cloud' || hostingMode === 'hybrid'

  const [queueDepth, setQueueDepth] = React.useState({
    pending_count: 0,
    last_sync_time: null,
    last_status: 'idle',
    last_error: null
  })
  const [flushing, setFlushing] = React.useState(false)

  const handleSyncFlush = React.useCallback(async () => {
    if (!token) return
    setFlushing(true)
    try {
      const res = await fetch(`${API_BASE}/api/sync/flush`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}` }
      })
      if (res.ok) {
        setTimeout(async () => {
          try {
            const r = await fetch(`${API_BASE}/api/sync/queue-depth`, {
              headers: { Authorization: `Bearer ${token}` }
            })
            if (r.ok) {
              const data = await r.json()
              setQueueDepth(data)
            }
          } catch (e) {}
          setFlushing(false)
        }, 1500)
      } else {
        setFlushing(false)
      }
    } catch (err) {
      console.error('Failed to trigger manual sync flush:', err)
      setFlushing(false)
    }
  }, [token])

  React.useEffect(() => {
    if (hostingMode !== 'hybrid' || !token) return

    const fetchQueueDepth = async () => {
      try {
        const res = await fetch(`${API_BASE}/api/sync/queue-depth`, {
          headers: { Authorization: `Bearer ${token}` }
        })
        if (res.ok) {
          const data = await res.json()
          setQueueDepth(data)
        }
      } catch (err) {
        console.error('Failed to fetch sync queue depth:', err)
      }
    }

    fetchQueueDepth()
    const interval = setInterval(fetchQueueDepth, 10000)
    return () => clearInterval(interval)
  }, [hostingMode, token])

  const [syncHealth, setSyncHealth] = React.useState(() => {
    if (window.__syncStatus) {
      return window.__syncStatus
    }
    const isOnline = typeof navigator !== 'undefined' ? navigator.onLine : true
    const userId = user?.id || 'default'
    return {
      status: isOnline ? 'connecting' : 'error',
      error: isOnline ? null : 'No internet connection. Client is offline.',
      lastSyncTime: localStorage.getItem(`sync_last_time_${userId}`),
      lastEntity: localStorage.getItem(`sync_last_entity_${userId}`),
      isOnline
    }
  })
  const [showSyncPopover, setShowSyncPopover] = React.useState(false)
  const syncPopoverRef = React.useRef(null)
  const syncBtnRef = React.useRef(null)

  React.useEffect(() => {
    const handleStatusChange = (e) => {
      setSyncHealth(e.detail)
    }
    window.addEventListener('sync-status-change', handleStatusChange)

    // Request fresh status from active listener on mount
    window.dispatchEvent(new CustomEvent('sync-status-request'))

    // Handle clicks outside the popover to close it
    const handleOutsideClick = (e) => {
      if (
        syncPopoverRef.current &&
        !syncPopoverRef.current.contains(e.target) &&
        syncBtnRef.current &&
        !syncBtnRef.current.contains(e.target)
      ) {
        setShowSyncPopover(false)
      }
    }
    document.addEventListener('mousedown', handleOutsideClick)

    return () => {
      window.removeEventListener('sync-status-change', handleStatusChange)
      document.removeEventListener('mousedown', handleOutsideClick)
    }
  }, [])



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
  const OWNER_ONLY_PATHS = React.useMemo(() => new Set(['/purchases', '/connections', '/orders', '/reports', '/import', '/staff', '/dashboard']), [])

  React.useEffect(() => {
    if (isCashier && OWNER_ONLY_PATHS.has(location.pathname)) {
      navigate('/sales', { replace: true })
    }
  }, [isCashier, location.pathname, navigate, OWNER_ONLY_PATHS])

  const visibleNav = isCashier
    ? NAV.map(s => ({ ...s, items: s.items.filter(i => !OWNER_ONLY_PATHS.has(i.to)) })).filter(s => s.items.length > 0)
    : NAV

  const visibleSubnav = isCashier
    ? SUBNAV.filter(item => !OWNER_ONLY_PATHS.has(item.to))
    : SUBNAV

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
      'Hub': false,
      'Sales & Operations': false,
      'Supply & Inflow': false,
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
    const uid = user?.id
    if (!uid) {
      setMinimizedBill(null)
      return
    }
    const isMinimized = localStorage.getItem(`pos_minimized_${uid}`) === 'true'
    const savedTabsStr = localStorage.getItem(`pos_minimized_tabs_${uid}`)
    if (isMinimized && savedTabsStr) {
      try {
        const savedTabs = JSON.parse(savedTabsStr)
        if (Array.isArray(savedTabs) && savedTabs.length > 0) {
          const activeId = localStorage.getItem(`pos_minimized_active_id_${uid}`)
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
  }, [user?.id])

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

  // ── App zoom: apply from settings whenever businessConfig changes ─────────
  React.useEffect(() => {
    // Try localStorage first (instant, before API resolves)
    const stored = localStorage.getItem('billing_app_zoom')
    const zoom = businessConfig?.general?.app_zoom
      ?? (stored ? parseInt(stored, 10) : null)
      ?? 100
    // Apply zoom + compensate minHeight so page always fills the viewport
    // at zoom < 100%, content shrinks → gap appears; minHeight = 100/zoom × 100%
    // Apply zoom to html, and simultaneously set --zoom so CSS layout
    // heights (calc(100vh / var(--zoom))) invert the zoom and panels
    // always render exactly at viewport height — no gap at low zoom,
    // no overflow/clipped footer at high zoom.
    document.documentElement.style.zoom = `${zoom}%`
    document.documentElement.style.setProperty('--zoom', zoom / 100)
    // Remove old minHeight hack — the --zoom formula handles this correctly
    document.documentElement.style.minHeight = ''
    if (stored !== String(zoom)) {
      localStorage.setItem('billing_app_zoom', String(zoom))
    }
  }, [businessConfig])

  // ── Inactivity timer: wire to LockContext ─────────────────────────────────
  React.useEffect(() => {
    const timeoutMinutes = businessConfig?.general?.lock_timeout_minutes ?? 60
    const timeoutMs = timeoutMinutes > 0 ? timeoutMinutes * 60 * 1000 : 0
    if (!hasLock || timeoutMs === 0) return

    const reset = () => resetInactivityTimer(timeoutMs)
    // Reset timer on any user activity
    const events = ['mousemove', 'keydown', 'touchstart', 'click', 'scroll']
    events.forEach(ev => window.addEventListener(ev, reset, { passive: true }))
    reset() // start immediately
    return () => events.forEach(ev => window.removeEventListener(ev, reset))
  }, [hasLock, resetInactivityTimer, businessConfig])

  const toggleSection = (section) => {
    setCollapsed(prev => ({ ...prev, [section]: !prev[section] }))
  }

  // ── Global Toast Notifications ─────────────────────────────────────────────
  const [toasts, setToasts] = React.useState([])

  React.useEffect(() => {
    const handleToast = (e) => {
      const { type, msg, duration = 4000 } = e.detail || {}
      if (!msg) return
      const id = Math.random().toString(36).slice(2, 9)
      setToasts(prev => [...prev, { id, type, msg }])
      
      setTimeout(() => {
        setToasts(prev => prev.filter(t => t.id !== id))
      }, duration)
    }
    window.addEventListener('show_toast', handleToast)
    return () => window.removeEventListener('show_toast', handleToast)
  }, [])

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
              {isSyncOn && (
                <div
                  ref={syncBtnRef}
                  className={`brand-tag sync-health-pill ${syncHealth.status}`}
                  onClick={(e) => {
                    e.stopPropagation()
                    setShowSyncPopover(!showSyncPopover)
                  }}
                  style={{
                    cursor: 'pointer',
                    display: 'inline-flex',
                    alignItems: 'center',
                    gap: '4px',
                    padding: '2px 8px',
                    borderRadius: '12px',
                    fontSize: '0.68rem',
                    fontWeight: '600',
                    marginTop: '4px',
                    width: 'fit-content',
                    transition: 'all 0.2s ease',
                    backgroundColor: hostingMode === 'hybrid'
                      ? (queueDepth.last_status === 'failed' && queueDepth.pending_count > 0 ? 'rgba(239, 68, 68, 0.1)' :
                         queueDepth.pending_count > 0 ? 'rgba(245, 158, 11, 0.1)' : 'rgba(34, 197, 94, 0.1)')
                      : (syncHealth.status === 'connected' ? 'rgba(34, 197, 94, 0.1)' :
                         syncHealth.status === 'connecting' ? 'rgba(245, 158, 11, 0.1)' :
                         'rgba(239, 68, 68, 0.1)'),
                    color: hostingMode === 'hybrid'
                      ? (queueDepth.last_status === 'failed' && queueDepth.pending_count > 0 ? 'var(--danger, #ef4444)' :
                         queueDepth.pending_count > 0 ? 'var(--warning, #f59e0b)' : 'var(--success, #22c55e)')
                      : (syncHealth.status === 'connected' ? 'var(--success, #22c55e)' :
                         syncHealth.status === 'connecting' ? 'var(--warning, #f59e0b)' :
                         'var(--danger, #ef4444)'),
                    border: '1px solid currentColor',
                    textTransform: 'none',
                    letterSpacing: 'normal'
                  }}
                  title="Click to view sync health check details"
                >
                  {hostingMode === 'hybrid' ? (
                    <>
                      {queueDepth.last_status === 'failed' && queueDepth.pending_count > 0 ? (
                        <>
                          <AlertIcon size={10} strokeWidth={2.5} />
                          <span>Sync Error</span>
                        </>
                      ) : queueDepth.pending_count > 0 ? (
                        <>
                          <span className="sync-spinner-small" />
                          <span>{queueDepth.pending_count} pending</span>
                        </>
                      ) : (
                        <>
                          <CheckIcon size={10} strokeWidth={2.5} />
                          <span>Sync Live</span>
                        </>
                      )}
                    </>
                  ) : (
                    <>
                      {syncHealth.status === 'connected' && (
                        <>
                          <CheckIcon size={10} strokeWidth={2.5} />
                          <span>Sync Live</span>
                        </>
                      )}
                      {syncHealth.status === 'connecting' && (
                        <>
                          <span className="sync-spinner-small" />
                          <span>Connecting...</span>
                        </>
                      )}
                      {syncHealth.status === 'error' && (
                        <>
                          <AlertIcon size={10} strokeWidth={2.5} />
                          <span>Sync Error</span>
                        </>
                      )}
                      {syncHealth.status === 'disconnected' && (
                        <>
                          <span>Disconnected</span>
                        </>
                      )}
                    </>
                  )}
                </div>
              )}
            </div>
            
            {isSyncOn && showSyncPopover && (
              <div
                ref={syncPopoverRef}
                className="sync-health-popover fade-in"
                style={{
                  position: 'absolute',
                  top: '100%',
                  left: '16px',
                  right: '16px',
                  zIndex: 1000,
                  background: 'var(--bg-3, #fff)',
                  border: '1px solid var(--border, #e2e8f0)',
                  borderRadius: 'var(--radius-md, 8px)',
                  boxShadow: 'var(--shadow-lg, 0 10px 15px -3px rgba(0,0,0,0.1))',
                  padding: '16px',
                  marginTop: '8px',
                  display: 'flex',
                  flexDirection: 'column',
                  gap: '12px'
                }}
              >
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <span style={{ fontSize: '0.8rem', fontWeight: '700', color: 'var(--text-primary)' }}>Sync Health Details</span>
                  <button
                    style={{
                      background: 'none',
                      border: 'none',
                      color: 'var(--text-muted)',
                      cursor: 'pointer',
                      padding: '2px',
                      display: 'flex',
                      alignItems: 'center'
                    }}
                    onClick={(e) => { e.stopPropagation(); setShowSyncPopover(false); }}
                    aria-label="Close Popover"
                  >
                    <CloseIcon size={14} />
                  </button>
                </div>

                <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', fontSize: '0.78rem' }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                    <span style={{ color: 'var(--text-secondary)' }}>Hosting Mode</span>
                    <span style={{ fontWeight: '600', color: 'var(--text-primary)', textTransform: 'capitalize' }}>
                      {hostingMode}
                    </span>
                  </div>
                  
                  <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                    <span style={{ color: 'var(--text-secondary)' }}>Status</span>
                    <span style={{
                      fontWeight: '700',
                      color: hostingMode === 'hybrid'
                        ? (queueDepth.last_status === 'failed' && queueDepth.pending_count > 0 ? 'var(--danger)' :
                           queueDepth.pending_count > 0 ? 'var(--warning)' : 'var(--success)')
                        : (syncHealth.status === 'connected' ? 'var(--success)' :
                           syncHealth.status === 'connecting' ? 'var(--warning)' : 'var(--danger)')
                    }}>
                      {hostingMode === 'hybrid'
                        ? (queueDepth.last_status === 'failed' && queueDepth.pending_count > 0 ? 'Sync Error' :
                           queueDepth.pending_count > 0 ? 'Syncing...' : 'Synced')
                        : (syncHealth.status === 'connected' ? 'Connected' :
                           syncHealth.status === 'connecting' ? 'Reconnecting...' : 'Error / Offline')}
                    </span>
                  </div>

                  <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                    <span style={{ color: 'var(--text-secondary)' }}>Network State</span>
                    <span style={{ fontWeight: '600', color: syncHealth.isOnline ? 'var(--success)' : 'var(--danger)' }}>
                      {syncHealth.isOnline ? 'Online' : 'Offline'}
                    </span>
                  </div>

                  {hostingMode === 'hybrid' && (
                    <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                      <span style={{ color: 'var(--text-secondary)' }}>Sync Outbox</span>
                      <span style={{ fontWeight: '600', color: queueDepth.pending_count > 0 ? 'var(--warning)' : 'var(--success)' }}>
                        {queueDepth.pending_count > 0 ? `${queueDepth.pending_count} pending` : 'Fully Synced'}
                      </span>
                    </div>
                  )}

                  {hostingMode !== 'hybrid' && (
                    <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                      <span style={{ color: 'var(--text-secondary)' }}>Last Sync Message</span>
                      <span style={{ fontWeight: '600', color: 'var(--text-primary)', textTransform: 'capitalize' }}>
                        {syncHealth.lastEntity ? `${syncHealth.lastEntity} updated` : 'None'}
                      </span>
                    </div>
                  )}

                  {hostingMode === 'hybrid' && queueDepth.last_sync_time && (
                    <div style={{ display: 'flex', flexDirection: 'column', gap: '2px', borderTop: '1px solid var(--border)', paddingTop: '6px' }}>
                      <span style={{ color: 'var(--text-secondary)' }}>Last Synced At</span>
                      <span style={{ fontWeight: '500', color: 'var(--text-muted)', fontSize: '0.72rem' }}>
                        {new Date(queueDepth.last_sync_time).toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit', second: '2-digit' })}
                        {' '}
                        ({new Date(queueDepth.last_sync_time).toLocaleDateString()})
                      </span>
                    </div>
                  )}

                  {hostingMode !== 'hybrid' && syncHealth.lastSyncTime && (
                    <div style={{ display: 'flex', flexDirection: 'column', gap: '2px', borderTop: '1px solid var(--border)', paddingTop: '6px' }}>
                      <span style={{ color: 'var(--text-secondary)' }}>Last Synced At</span>
                      <span style={{ fontWeight: '500', color: 'var(--text-muted)', fontSize: '0.72rem' }}>
                        {new Date(syncHealth.lastSyncTime).toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit', second: '2-digit' })}
                        {' '}
                        ({new Date(syncHealth.lastSyncTime).toLocaleDateString()})
                      </span>
                    </div>
                  )}
                </div>

                {hostingMode === 'hybrid' && queueDepth.last_error && (
                  <div style={{
                    backgroundColor: 'rgba(239, 68, 68, 0.05)',
                    border: '1px solid rgba(239, 68, 68, 0.2)',
                    borderRadius: 'var(--radius-sm, 4px)',
                    padding: '8px',
                    fontSize: '0.75rem',
                    color: 'var(--danger)',
                    wordBreak: 'break-word',
                    lineHeight: '1.3'
                  }}>
                    <strong>Sync Worker Log:</strong><br />
                    {queueDepth.last_error}
                  </div>
                )}

                {hostingMode !== 'hybrid' && syncHealth.error && (
                  <div style={{
                    backgroundColor: 'rgba(239, 68, 68, 0.05)',
                    border: '1px solid rgba(239, 68, 68, 0.2)',
                    borderRadius: 'var(--radius-sm, 4px)',
                    padding: '8px',
                    fontSize: '0.75rem',
                    color: 'var(--danger)',
                    wordBreak: 'break-word',
                    lineHeight: '1.3'
                  }}>
                    <strong>Diagnostic Log:</strong><br />
                    {syncHealth.error}
                  </div>
                )}

                {hostingMode === 'hybrid' && (
                  <button
                    onClick={(e) => {
                      e.stopPropagation()
                      handleSyncFlush()
                    }}
                    disabled={flushing}
                    style={{
                      width: '100%',
                      padding: '6px 12px',
                      backgroundColor: flushing ? 'rgba(255,255,255,0.08)' : 'var(--accent, #3b82f6)',
                      color: flushing ? 'var(--text-muted)' : '#fff',
                      border: 'none',
                      borderRadius: 'var(--radius-sm, 4px)',
                      cursor: flushing ? 'not-allowed' : 'pointer',
                      fontWeight: '600',
                      fontSize: '0.75rem',
                      transition: 'background-color 0.2s',
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      gap: '6px'
                    }}
                  >
                    <SyncIcon size={12} className={flushing ? 'sync-spinner-small' : ''} />
                    {flushing ? 'Syncing Now...' : 'Sync Now'}
                  </button>
                )}

                {hostingMode !== 'hybrid' && (syncHealth.status === 'error' || syncHealth.status === 'connecting') && (
                  <button
                    onClick={(e) => {
                      e.stopPropagation()
                      window.dispatchEvent(new CustomEvent('sync-reconnect-request'))
                    }}
                    style={{
                      width: '100%',
                      padding: '6px 12px',
                      backgroundColor: 'var(--accent, #3b82f6)',
                      color: '#fff',
                      border: 'none',
                      borderRadius: 'var(--radius-sm, 4px)',
                      cursor: 'pointer',
                      fontWeight: '600',
                      fontSize: '0.75rem',
                      transition: 'background-color 0.2s',
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      gap: '6px'
                    }}
                  >
                    <SyncIcon size={12} /> Force Reconnect
                  </button>
                )}
              </div>
            )}

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
              <div
                className="pos-minimized-card"
                onClick={() => {
                  if (user?.id) {
                    localStorage.removeItem(`pos_minimized_${user.id}`);
                  }
                  window.dispatchEvent(new Event('pos_minimized_changed'));
                  navigate('/sales');
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
                        if (user?.id) {
                          localStorage.removeItem(`pos_minimized_${user.id}`);
                          localStorage.removeItem(`pos_minimized_tabs_${user.id}`);
                          localStorage.removeItem(`pos_minimized_active_id_${user.id}`);
                        }
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
                <button className="profile-menu-item" onClick={() => { setShowProfileMenu(false); navigate('/settings?tab=lock'); }}>
                  <ContactsIcon size={14} /> Staff & Cashiers
                </button>
                <button
                  className="profile-menu-item"
                  onClick={() => {
                    setShowProfileMenu(false)
                    if (hasLock) {
                      lock()
                    } else {
                      // No PIN set yet — take them to Settings to set one up
                      navigate('/settings')
                    }
                  }}
                  style={{ color: 'var(--warning, #f59e0b)', display: 'flex', alignItems: 'center', gap: 8 }}
                >
                  <LockIcon size={14} /> {hasLock ? 'Lock Session' : 'Lock App (Set PIN)'}
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
                  <img src={profile.logo} alt="Logo" />
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
        {/* Mobile horizontal nav strip */}
        {!isSalesPage && (
          <div className="mobile-nav-bar">
            {visibleSubnav.map(item => {
              const isActive = location.pathname === item.to;
              return (
                <NavLink
                  key={item.to}
                  to={item.to}
                  end={item.to === '/'}
                  className={`mobile-nav-link ${isActive ? 'active' : ''}`}
                >
                  {item.icon}
                  <span>{item.label}</span>
                </NavLink>
              );
            })}
          </div>
        )}

        {/* ── Page content ── */}
        <main className="page-content">
          {children}
        </main>
      </div>

      {toasts.length > 0 && (
        <div style={{
          position: 'fixed',
          bottom: 24,
          right: 24,
          zIndex: 10000,
          display: 'flex',
          flexDirection: 'column',
          gap: 10,
          maxWidth: 360,
          pointerEvents: 'none'
        }}>
          {toasts.map(toast => (
            <div key={toast.id} style={{
              pointerEvents: 'auto',
              background: 'var(--bg-3, #fff)',
              border: '1px solid var(--border, #e2e8f0)',
              borderLeft: `4px solid ${
                toast.type === 'success' ? 'var(--success, #22c55e)' :
                toast.type === 'error' ? 'var(--danger, #ef4444)' :
                toast.type === 'warning' ? 'var(--warning, #f59e0b)' : 'var(--accent, #3b82f6)'
              }`,
              padding: '12px 16px',
              borderRadius: 'var(--radius-md, 8px)',
              boxShadow: 'var(--shadow-lg, 0 10px 15px -3px rgba(0,0,0,0.1))',
              display: 'flex',
              alignItems: 'center',
              gap: 12,
              animation: 'slideIn 0.2s ease-out'
            }}>
              <span style={{ display: 'inline-flex', alignItems: 'center' }}>
                {toast.type === 'success' ? <CheckIcon size={16} style={{ color: 'var(--success, #22c55e)' }} /> :
                 toast.type === 'error' ? <AlertIcon size={16} style={{ color: 'var(--danger, #ef4444)' }} /> :
                 <SummaryIcon size={16} style={{ color: 'var(--accent, #3b82f6)' }} />}
              </span>
              <span style={{ fontSize: '0.82rem', fontWeight: 500, color: 'var(--text, #1e293b)', lineHeight: 1.4 }}>
                {toast.msg}
              </span>
              <button
                onClick={() => setToasts(prev => prev.filter(t => t.id !== toast.id))}
                style={{
                  background: 'none',
                  border: 'none',
                  color: 'var(--text-muted, #64748b)',
                  cursor: 'pointer',
                  marginLeft: 'auto',
                  display: 'flex',
                  alignItems: 'center',
                  padding: 0
                }}
                aria-label="Close"
              >
                <CloseIcon size={14} />
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
