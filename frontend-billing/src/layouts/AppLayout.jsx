import React from 'react'
import { createPortal } from 'react-dom'
import { NavLink, Link, useNavigate, useLocation } from 'react-router-dom'
import { useAuth } from '../contexts/AuthContext'
import { useLock } from '../contexts/LockContext'
import { API_BASE, IS_LOCAL_APP } from '../config'
import { logger } from '../utils/logger'
import { formatIST } from '../utils/format'
import { getAiDashboardUrl, openAiDashboard } from '../config/aiDashboard'
import { IS_DESKTOP_APP, openDownloadPage } from '../config/downloadApp'
import { BuildingMark } from '../components/Logo'
import PageLoader from '../components/PageLoader'
import PageHelp from '../components/PageHelp'
import SyncNudgeModal from '../components/hosting/SyncNudgeModal'
import WebLocalOnlyNotice from '../components/hosting/WebLocalOnlyNotice'
// HostingOnboardingModal removed: hosting is now chosen once, in Register.
// The post-login onboarding pop-up duplicated that choice and was intrusive.
import { BillsIcon, CashIcon, ChevronDownIcon, CloseIcon, ConnectionIcon, ContactsIcon, CounterIcon, DashboardIcon, HomeIcon, ImportIcon, InventoryIcon, LockIcon, LogoutIcon, OrderIcon, ReportsIcon, SettingsIcon, SummaryIcon, TaxIcon, ZapIcon, SunIcon, MoonIcon, MonitorIcon, UserIcon, CheckIcon, AlertIcon, SyncIcon, DownloadIcon } from '../components/Icons'


const NAV = [
  {
    section: 'Supply & Inflow',
    items: [
      { to: '/b2b-orders', icon: <OrderIcon size={16} className="nav-anim-b2border" />, label: 'B2B Orders' },
      { to: '/purchases', icon: <BillsIcon size={16} className="nav-anim-purchase" />, label: 'Purchase Bills' },
      { to: '/b2b-network', icon: <ConnectionIcon size={16} className="nav-anim-b2bnet" />, label: 'B2B Network' },
      { to: '/import', icon: <ImportIcon size={16} className="nav-anim-import" />, label: 'Data Migration' },
    ]
  },
  {
    section: 'Hub',
    items: [
      { to: '/',          icon: <HomeIcon size={16} className="nav-anim-home" />, label: 'Home'      },
      { to: '/dashboard', icon: <DashboardIcon size={16} className="nav-anim-dash" />, label: 'Dashboard' },
      // External: the bundled frontend-ai app (opens in its own window in the
      // desktop app). Gated behind subscription in future — see aiDashboard.js.
      { external: true, ownerOnly: true, icon: <ZapIcon size={16} />, label: 'Dashboard BIZASSIST' },
    ]
  },
  {
    section: 'Sales & Operations',
    items: [
      { to: '/sales',    icon: <CounterIcon size={16} className="nav-anim-bill" />,   label: 'Billing Counter' },
      { to: '/pos-live-counter', icon: <MonitorIcon size={16} />,   label: 'POS Live Counter' },
      { to: '/payments', icon: <CashIcon size={16} className="nav-anim-cash" />,      label: 'Transactions' },
      { to: '/parties',  icon: <ContactsIcon size={16} className="nav-anim-contact" />,  label: 'Contacts & Dues' },
      { to: '/stock',    icon: <InventoryIcon size={16} className="nav-anim-inventory" />, label: 'Inventory' },
      { to: '/reports',  icon: <ReportsIcon size={16} className="nav-anim-report" />,   label: 'GST & Tax Reports' },
    ]
  }
]

// Flat list for sub-navbar (only key pages, grouped)
const SUBNAV = [
  { to: '/',           label: 'Home',         icon: <HomeIcon size={14} /> },
  { to: '/dashboard',  label: 'Dashboard',    icon: <DashboardIcon size={14} /> },
  { to: '/sales',      label: 'Billing',      icon: <CounterIcon size={14} /> },
  { to: '/payments',   label: 'Transactions', icon: <CashIcon size={14} /> },
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
  '/payments':    'Transactions',
  '/parties':     'Contacts & Dues',
  '/stock':       'Inventory',
  '/purchases':   'Purchase Bills',
  '/b2b-network': 'B2B Network',
  '/b2b-orders':  'B2B Orders',
  '/reports':     'GST & Tax Reports',
  '/import':      'Data Migration',
  '/profile':     'My Profile',
  '/staff':       'Staff & Cashiers',
  '/settings':    'App Settings',
}

export default function AppLayout({ children, title }) {
  const { user, logout, profile, token, businessConfig, appReady, setAppReady, settings, fetchSettings } = useAuth()
  const { hasLock, lock, resetInactivityTimer } = useLock()
  const navigate = useNavigate()
  const location = useLocation()

  const hostingMode = settings?.general?.hosting_mode || 'local'
  const effectiveMode = !IS_LOCAL_APP
    ? 'cloud'
    : (localStorage.getItem('bizassist_hosting_mode') || hostingMode)
  const isSyncOn = effectiveMode === 'cloud' || effectiveMode === 'hybrid'

  // Subscription gate (Admin Console plan, Phase B.5): the backend's /settings
  // response carries the business's real plan + whether enforcement is live.
  // Replaces the old hardcoded AI_DASHBOARD_GATED const.
  const subscription = settings?.subscription
  const aiGated = !subscription?.plan || subscription?.plan !== 'pro'

  const isFreePlan = !subscription?.plan || subscription?.plan !== 'pro'
  const isSyncPaused = isSyncOn && isFreePlan

  const [sessionExpired, setSessionExpired] = React.useState(false)
  const [checkingPlan, setCheckingPlan] = React.useState(false)

  const handleCheckPlan = async (e) => {
    if (e && e.stopPropagation) e.stopPropagation()
    setCheckingPlan(true)
    try {
      await fetchSettings(true)
    } catch (err) {
      console.error('[SETTINGS] Failed to refresh plan status:', err)
    } finally {
      setCheckingPlan(false)
    }
  }

  React.useEffect(() => {
    // Session expiration applies only to the WEB (cloud) app when the user is not on a Pro plan.
    // If the subscription is enforced (or if we want to follow the 5 min preview rule on cloud),
    // we block the view after 5 minutes of continuous session.
    if (IS_LOCAL_APP) return

    // Allow admins to bypass
    const isOwnerOrStaff = user?.role !== 'admin'
    const isFree = !subscription?.plan || subscription?.plan !== 'pro'
    
    if (isOwnerOrStaff && isFree) {
      let sessionStart = sessionStorage.getItem('bizassist_session_start_time')
      if (!sessionStart) {
        sessionStart = String(Date.now())
        sessionStorage.setItem('bizassist_session_start_time', sessionStart)
      }
      
      const checkExpiry = () => {
        const elapsed = Date.now() - Number(sessionStart)
        if (elapsed >= 300000) { // 5 minutes = 300,000 ms
          setSessionExpired(true)
        }
      }
      
      checkExpiry()
      const interval = setInterval(checkExpiry, 5000)
      return () => clearInterval(interval)
    } else {
      setSessionExpired(false)
    }
  }, [user, subscription])

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
          // Notify the queue-depth effect listener so it refreshes immediately
          // without waiting for the next 30s poll tick.
          window.dispatchEvent(new CustomEvent('sync-flushed'))
        }, 1500)
      } else {
        setFlushing(false)
      }
    } catch (err) {
      logger.error('Failed to trigger manual sync flush:', err)
      setFlushing(false)
    }
  }, [token])

  React.useEffect(() => {
    if (effectiveMode !== 'hybrid' || !token) return

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
        logger.error('Failed to fetch sync queue depth:', err)
      }
    }

    fetchQueueDepth()
    // Poll every 30s (reduced from 10s) — the 'sync-flushed' event triggers an
    // immediate refresh after a manual flush so the counter doesn't feel stale.
    const interval = setInterval(fetchQueueDepth, 30000)
    const handleSyncFlushed = () => { fetchQueueDepth() }
    window.addEventListener('sync-flushed', handleSyncFlushed)
    return () => {
      clearInterval(interval)
      window.removeEventListener('sync-flushed', handleSyncFlushed)
    }
  }, [effectiveMode, token])

  const userId = user?.id || 'default'

  const [syncHealth, setSyncHealth] = React.useState(() => {
    if (window.__syncStatus) {
      return window.__syncStatus
    }
    const isOnline = typeof navigator !== 'undefined' ? navigator.onLine : true
    return {
      status: isOnline ? 'connecting' : 'error',
      error: isOnline ? null : 'No internet connection. Client is offline.',
      lastSyncTime: localStorage.getItem(`sync_last_time_${userId}`),
      lastEntity: localStorage.getItem(`sync_last_entity_${userId}`),
      isOnline
    }
  })

  // Live sync progress from SSE sync.progress events
  // { entities: ['invoices','customers'], done: 3, total: 7 } | null
  const [syncProgress, setSyncProgress] = React.useState(null)
  const syncProgressTimerRef = React.useRef(null)

  const [lastAutoRefresh, setLastAutoRefresh] = React.useState(() => {
    return localStorage.getItem(`sync_last_autorefresh_${userId}`) || null
  })
  const [showRefreshFlash, setShowRefreshFlash] = React.useState(false)

  const [showSyncPopover, setShowSyncPopover] = React.useState(false)
  const syncPopoverRef = React.useRef(null)
  const syncBtnRef = React.useRef(null)

  React.useEffect(() => {
    const handleStatusChange = (e) => {
      setSyncHealth(e.detail)
    }
    // Consume sync.progress SSE events (emitted by sync_worker per chunk)
    const handleSyncProgress = (e) => {
      const d = e.detail || {}
      if (d.type === 'sync.progress') {
        setSyncProgress({ entities: d.entities || [], done: d.done || 0, total: d.total || 0, phase: d.phase || 'push' })
        // Auto-clear progress banner 2.5s after the batch completes
        if (d.done >= d.total && d.total > 0) {
          clearTimeout(syncProgressTimerRef.current)
          syncProgressTimerRef.current = setTimeout(() => setSyncProgress(null), 2500)
        }
      } else if (d.type === 'sync.reconnect') {
        const nowStr = new Date().toISOString()
        localStorage.setItem(`sync_last_autorefresh_${userId}`, nowStr)
        setLastAutoRefresh(nowStr)
        setShowRefreshFlash(true)
        setTimeout(() => setShowRefreshFlash(false), 4000)
      }
    }
    window.addEventListener('sync-status-change', handleStatusChange)
    window.addEventListener('sync-event', handleSyncProgress)

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

    // ── Tab visibility refresh ──────────────────────────────────────────────
    // When user comes back to a tab hidden for > 5 min, silently re-fetch all
    // page list data (invoices, stock, etc.). Draft/form state is never reset
    // — pages only call their fetchData() when they receive sync.reconnect.
    // This mirrors the behaviour of Google Docs, Notion, and most modern apps.
    const STALE_THRESHOLD_MS = 5 * 60 * 1000   // 5 minutes
    let hiddenAt = null
    const handleVisibilityChange = () => {
      if (document.visibilityState === 'hidden') {
        hiddenAt = Date.now()
      } else if (document.visibilityState === 'visible' && hiddenAt) {
        const hiddenFor = Date.now() - hiddenAt
        hiddenAt = null
        if (hiddenFor >= STALE_THRESHOLD_MS) {
          window.dispatchEvent(new CustomEvent('sync-event', {
            detail: { type: 'sync.reconnect' }
          }))
        }
      }
    }
    document.addEventListener('visibilitychange', handleVisibilityChange)

    return () => {
      window.removeEventListener('sync-status-change', handleStatusChange)
      window.removeEventListener('sync-event', handleSyncProgress)
      document.removeEventListener('mousedown', handleOutsideClick)
      document.removeEventListener('visibilitychange', handleVisibilityChange)
      clearTimeout(syncProgressTimerRef.current)
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

    // Minimum timer: was 1000ms which forced a 1s splash even when local data
    // is already cached (typical refresh). 200ms is enough for a smooth transition
    // without making every refresh feel sluggish.
    const minTimer = setTimeout(() => {
      minElapsed = true
      checkReady()
    }, 200)

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
  // real authority; this just hides off-role destinations from staff).
  // Two staff sectors (owner requirement, 2026-07):
  //   cashier      → the SALES sector: billing counter + what billing needs.
  //   supply adder → the STOCK sector: inventory, labels, purchase bills —
  //                  their whole job lives under Inventory + Purchases.
  const staffRole = (user?.role || '').toLowerCase()
  const isCashier = staffRole === 'cashier'
  const isSupplyAdder = staffRole === 'supply adder'
  const OWNER_ONLY_PATHS = React.useMemo(() => new Set(['/purchases', '/b2b-network', '/b2b-orders', '/reports', '/import', '/staff', '/dashboard', '/pos-live-counter']), [])
  // What each staff sector is allowed to SEE (backend still enforces writes).
  const SUPPLY_ADDER_PATHS = React.useMemo(() => new Set(['/', '/stock', '/purchases', '/profile', '/support', '/settings']), [])

  React.useEffect(() => {
    if (isCashier && OWNER_ONLY_PATHS.has(location.pathname)) {
      navigate('/sales', { replace: true })
    } else if (isSupplyAdder && !SUPPLY_ADDER_PATHS.has(location.pathname)
               && !location.pathname.startsWith('/invoice/')) {
      navigate('/stock', { replace: true })
    }
  }, [isCashier, isSupplyAdder, location.pathname, navigate, OWNER_ONLY_PATHS, SUPPLY_ADDER_PATHS])

  const visibleNav = isCashier
    ? NAV.map(s => ({ ...s, items: s.items.filter(i => !OWNER_ONLY_PATHS.has(i.to) && !i.ownerOnly) })).filter(s => s.items.length > 0)
    : isSupplyAdder
      ? NAV.map(s => ({ ...s, items: s.items.filter(i => SUPPLY_ADDER_PATHS.has(i.to)) })).filter(s => s.items.length > 0)
      : NAV

  const visibleSubnav = isCashier
    ? SUBNAV.filter(item => !OWNER_ONLY_PATHS.has(item.to))
    : isSupplyAdder
      ? SUBNAV.filter(item => SUPPLY_ADDER_PATHS.has(item.to))
      : SUBNAV

  // Track collapsed state per section with localStorage persistence
  const [collapsed, setCollapsed] = React.useState(() => {
    try {
      const saved = localStorage.getItem('sidebar_collapsed_sections')
      if (saved) {
        return JSON.parse(saved)
      }
    } catch (e) {
      logger.error(e)
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
      logger.error(e)
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
    // Default to 'system' so the app follows the OS light/dark setting out of the
    // box (matches the boot script in index.html). Explicit choices still win.
    return localStorage.getItem('billing_theme') || 'system'
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

  // One-time notice the first time the app auto-adopts the OS theme (i.e. the
  // user never picked one). Captured before the theme effect persists 'system'.
  const themeAutoAdopted = React.useRef(
    typeof localStorage !== 'undefined' && !localStorage.getItem('billing_theme')
  )
  React.useEffect(() => {
    if (!themeAutoAdopted.current) return
    try {
      if (localStorage.getItem('billing_theme_toast_shown')) return
      localStorage.setItem('billing_theme_toast_shown', '1')
    } catch { return }
    const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches
    // Small delay so the toast listener is mounted and it isn't jarring on first paint.
    const t = setTimeout(() => {
      window.dispatchEvent(new CustomEvent('show_toast', {
        detail: { type: 'info', msg: `Matching your system theme (${prefersDark ? 'dark' : 'light'}). Change it anytime in Settings.` },
      }))
    }, 900)
    return () => clearTimeout(t)
  }, [])

  // Profile popover menu
  const [showProfileMenu, setShowProfileMenu] = React.useState(false)
  const [mobileMenuOpen, setMobileMenuOpen] = React.useState(false)
  const profileMenuRef = React.useRef(null)
  const userChipRef = React.useRef(null)

  React.useEffect(() => {
    setMobileMenuOpen(false)
  }, [location.pathname])

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
  const [minimizedLive, setMinimizedLive] = React.useState(null)

  const checkMinimized = React.useCallback(() => {
    const uid = user?.user_id || user?.id
    if (!uid) {
      setMinimizedBill(null)
      setMinimizedLive(null)
      return
    }

    // Helper to compute items and totals from a tab
    const getTabStats = (tab) => {
      const lines = tab?.form?.lines || tab?.form?.items || []
      const itemsCount = lines.length
      const totalAmt = lines.reduce((sum, item) => {
        const q = parseFloat(item.quantity) || parseFloat(item.qty) || 0
        const p = parseFloat(item.unit_price) || parseFloat(item.price) || 0
        const d = parseFloat(item.discount) || 0
        const cgst = parseFloat(item.cgst_rate) || 0
        const sgst = parseFloat(item.sgst_rate) || 0
        const base = q * p - d
        const tax = base * ((cgst + sgst) / 100)
        return sum + Math.max(0, base + tax)
      }, 0) || 0
      return { itemsCount, totalAmt }
    };

    // 1. Check standard POS minimized
    const isMinimized = localStorage.getItem(`pos_minimized_${uid}`) === 'true'
    const savedTabsStr = localStorage.getItem(`pos_minimized_tabs_${uid}`)
    if (isMinimized && savedTabsStr) {
      try {
        const savedTabs = JSON.parse(savedTabsStr)
        if (Array.isArray(savedTabs) && savedTabs.length > 0) {
          const activeId = localStorage.getItem(`pos_minimized_active_id_${uid}`)
          const activeTab = savedTabs.find(t => t.id === activeId) || savedTabs[0]
          const { itemsCount, totalAmt } = getTabStats(activeTab)

          setMinimizedBill({
            name: activeTab.name || 'Invoice Draft',
            itemsCount,
            totalAmt,
            tabsCount: savedTabs.length
          })
        } else {
          setMinimizedBill(null)
        }
      } catch (e) {
        setMinimizedBill(null)
      }
    } else {
      setMinimizedBill(null)
    }

    // 2. Check Live View minimized
    const isLiveMinimized = localStorage.getItem(`pos_live_minimized_${uid}`) === 'true'
    const savedLiveTabsStr = localStorage.getItem(`pos_live_minimized_tabs_${uid}`)
    const liveCounter = localStorage.getItem(`pos_live_minimized_counter_${uid}`)
    const liveClientId = localStorage.getItem(`pos_live_minimized_client_id_${uid}`)
    if (isLiveMinimized && savedLiveTabsStr && liveCounter) {
      try {
        const savedLiveTabs = JSON.parse(savedLiveTabsStr)
        if (Array.isArray(savedLiveTabs) && savedLiveTabs.length > 0) {
          const activeId = localStorage.getItem(`pos_live_minimized_active_id_${uid}`)
          const activeTab = savedLiveTabs.find(t => t.id === activeId) || savedLiveTabs[0]
          const { itemsCount, totalAmt } = getTabStats(activeTab)

          setMinimizedLive({
            counter: liveCounter,
            clientId: liveClientId,
            name: activeTab.name || `Counter ${liveCounter}`,
            itemsCount,
            totalAmt,
            tabsCount: savedLiveTabs.length
          })
        } else {
          setMinimizedLive(null)
        }
      } catch (e) {
        setMinimizedLive(null)
      }
    } else {
      setMinimizedLive(null)
    }
  }, [user?.user_id, user?.id])

  React.useEffect(() => {
    checkMinimized()
    window.addEventListener('pos_minimized_changed', checkMinimized)
    return () => window.removeEventListener('pos_minimized_changed', checkMinimized)
  }, [checkMinimized])

  React.useEffect(() => {
    if (location.pathname !== '/sales' && location.pathname !== '/live-view') {
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
    // On mobile devices (width <= 768px), force zoom to 100% to prevent fixed container layout offsets and bottom gaps
    const isMobile = window.innerWidth <= 768
    const finalZoom = isMobile ? 100 : zoom

    document.documentElement.style.zoom = `${finalZoom}%`
    document.documentElement.style.setProperty('--zoom', finalZoom / 100)
    // Remove old minHeight hack — the --zoom formula handles this correctly
    document.documentElement.style.minHeight = ''
    if (!isMobile && stored !== String(zoom)) {
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

  const isSalesPage = location.pathname === '/sales' || location.pathname === '/stock'
  const pageTitle = title || PAGE_TITLES[location.pathname] || 'BizAssist'

  return (
    <div className={`app-shell ${isSalesPage ? 'pos-layout-shell' : ''}`}>
      {!appReady && <PageLoader />}
      {/* Nudge to sync when a device is missing data the other side holds (sensed at login) */}
      <SyncNudgeModal />
      {/* Web-only: a Local-only account has no data on the cloud — explain instead of showing an empty app */}
      <WebLocalOnlyNotice />

      {/* Global Toast Container */}
      {/* Landscape orientation overlay for POS `/sales` page on mobile */}
      {isSalesPage && (
        <div className="pos-portrait-overlay">
          <div className="pos-portrait-content">
            <div className="rotate-icon-wrapper">
              <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="rotate-device-icon">
                <rect x="5" y="2" width="14" height="20" rx="2" ry="2" transform="rotate(90 12 12)" />
                <path d="M12 18h.01" />
              </svg>
            </div>
            <h2>Rotate Your Device</h2>
            <p>Please rotate your phone to landscape mode to use the Billing Counter.</p>
          </div>
        </div>
      )}

      {/* ── Sidebar ── */}
      {!isSalesPage && (
        <aside className={`sidebar ${mobileMenuOpen ? 'open' : ''}`}>
          {/* Brand */}
          <div className="sidebar-brand">
            {profile?.logo ? (
              <img src={profile.logo} alt="Logo" style={{ width: 36, height: 36, objectFit: 'contain', borderRadius: 'var(--radius-sm)' }} />
            ) : (
              <BuildingMark size={30} />
            )}
            <div style={{ flex: 1, minWidth: 0 }}>
              <div className="brand-name">{profile?.business_name || user?.business_name || 'BizAssist'}</div>
              {isSyncOn && (
                <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
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
                      backgroundColor: isSyncPaused
                        ? 'rgba(245, 158, 11, 0.1)'
                        : (effectiveMode === 'hybrid'
                            ? (queueDepth.last_status === 'failed' && queueDepth.pending_count > 0 ? 'rgba(239, 68, 68, 0.1)' :
                               queueDepth.pending_count > 0 ? 'rgba(245, 158, 11, 0.1)' :
                               !syncHealth.isOnline ? 'rgba(255, 255, 255, 0.05)' : 'rgba(34, 197, 94, 0.1)')
                            : (syncHealth.status === 'connected' ? 'rgba(34, 197, 94, 0.1)' :
                               syncHealth.status === 'connecting' ? 'rgba(245, 158, 11, 0.1)' :
                               'rgba(239, 68, 68, 0.1)')),
                      color: isSyncPaused
                        ? 'var(--warning, #f59e0b)'
                        : (effectiveMode === 'hybrid'
                            ? (queueDepth.last_status === 'failed' && queueDepth.pending_count > 0 ? 'var(--danger, #ef4444)' :
                               queueDepth.pending_count > 0 ? 'var(--warning, #f59e0b)' :
                               !syncHealth.isOnline ? 'var(--text-muted)' : 'var(--success, #22c55e)')
                            : (syncHealth.status === 'connected' ? 'var(--success, #22c55e)' :
                               syncHealth.status === 'connecting' ? 'var(--warning, #f59e0b)' :
                               'var(--danger, #ef4444)')),
                      border: '1px solid currentColor',
                      textTransform: 'none',
                      letterSpacing: 'normal'
                    }}
                    title="Click to view sync health check details"
                  >
                    {isSyncPaused ? (
                      <>
                        <AlertIcon size={10} strokeWidth={2.5} />
                        <span>Sync Paused</span>
                      </>
                    ) : effectiveMode === 'hybrid' ? (
                      <>
                        {/* Offline is the highest priority — shown before pending/error */}
                        {!syncHealth.isOnline ? (
                          <>
                            <AlertIcon size={10} strokeWidth={2.5} />
                            <span>Sync Offline</span>
                          </>
                        ) : queueDepth.last_status === 'failed' && queueDepth.pending_count > 0 ? (
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
                            {showRefreshFlash ? (
                              <span className="sync-spinner-small" style={{ borderTopColor: 'var(--success)' }} />
                            ) : (
                              <CheckIcon size={10} strokeWidth={2.5} />
                            )}
                            <span>{showRefreshFlash ? 'Sync Refreshed' : 'Sync Live'}</span>
                          </>
                        )}
                      </>
                    ) : (
                      <>
                        {syncHealth.status === 'connected' && (
                          <>
                            {showRefreshFlash ? (
                              <span className="sync-spinner-small" style={{ borderTopColor: 'var(--success)' }} />
                            ) : (
                              <CheckIcon size={10} strokeWidth={2.5} />
                            )}
                            <span>{showRefreshFlash ? 'Sync Refreshed' : 'Sync Live'}</span>
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
                        {/* 'offline' is a dedicated status emitted by handleOffline */}
                        {syncHealth.status === 'offline' && (
                          <>
                            <AlertIcon size={10} strokeWidth={2.5} />
                            <span>Offline</span>
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

                  {/* Manual Refresh App Content button (especially useful in windows desktop app wrapper) */}
                  <button
                    onClick={(e) => {
                      e.stopPropagation()
                      window.dispatchEvent(new CustomEvent('sync-event', {
                        detail: { type: 'sync.reconnect' }
                      }))
                    }}
                    style={{
                      background: 'rgba(255, 255, 255, 0.05)',
                      border: '1px solid var(--border)',
                      padding: '3px',
                      color: 'var(--text-muted, #718096)',
                      cursor: 'pointer',
                      display: 'inline-flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      borderRadius: '50%',
                      transition: 'all 0.2s',
                      marginTop: '4px'
                    }}
                    onMouseEnter={(e) => {
                      e.currentTarget.style.color = 'var(--text-primary)'
                      e.currentTarget.style.backgroundColor = 'rgba(255, 255, 255, 0.15)'
                    }}
                    onMouseLeave={(e) => {
                      e.currentTarget.style.color = 'var(--text-muted)'
                      e.currentTarget.style.backgroundColor = 'rgba(255, 255, 255, 0.05)'
                    }}
                    title="Refresh Page Content"
                  >
                    <SyncIcon size={11} className={showRefreshFlash ? 'sync-spinner-small' : ''} />
                  </button>
                </div>
              )}
            </div>
            
            {/* Close button for mobile drawer */}
            <button
              className="mobile-drawer-close"
              onClick={() => setMobileMenuOpen(false)}
              aria-label="Close menu"
              style={{
                background: 'none',
                border: 'none',
                color: 'var(--text-muted)',
                cursor: 'pointer',
                padding: '4px',
                display: 'none',
                alignItems: 'center',
                justifyContent: 'center',
                marginLeft: '8px',
                flexShrink: 0
              }}
            >
              <CloseIcon size={18} />
            </button>
            
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
                      {effectiveMode}
                    </span>
                  </div>
                  
                  <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                    <span style={{ color: 'var(--text-secondary)' }}>Status</span>
                    <span style={{
                      fontWeight: '700',
                      color: isSyncPaused
                        ? 'var(--warning, #f59e0b)'
                        : (effectiveMode === 'hybrid'
                            ? (queueDepth.last_status === 'failed' && queueDepth.pending_count > 0 ? 'var(--danger)' :
                               queueDepth.pending_count > 0 ? 'var(--warning)' : 'var(--success)')
                            : (syncHealth.status === 'connected' ? 'var(--success)' :
                               syncHealth.status === 'connecting' ? 'var(--warning)' : 'var(--danger)'))
                    }}>
                      {isSyncPaused
                        ? 'Sync Paused (Pro Required)'
                        : (effectiveMode === 'hybrid'
                            ? (queueDepth.last_status === 'failed' && queueDepth.pending_count > 0 ? 'Sync Error' :
                               queueDepth.pending_count > 0 ? 'Syncing...' : 'Synced')
                            : (syncHealth.status === 'connected' ? 'Connected' :
                               syncHealth.status === 'connecting' ? 'Reconnecting...' : 'Error / Offline'))}
                    </span>
                  </div>

                  <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                    <span style={{ color: 'var(--text-secondary)' }}>Network State</span>
                    <span style={{ fontWeight: '600', color: syncHealth.isOnline ? 'var(--success)' : 'var(--danger)' }}>
                      {syncHealth.isOnline ? 'Online' : 'Offline'}
                    </span>
                  </div>

                  {effectiveMode === 'hybrid' && (() => {
                      // Human-friendly entity label map
                      const ENTITY_LABEL = {
                        invoices:                 'Invoices',
                        invoice_payments:         'Payments',
                        customers:                'Customers',
                        products:                 'Products',
                        inventory:                'Inventory',
                        stock_ledger:             'Stock Ledger',
                        product_barcodes:         'Barcodes',
                        purchase_invoices:        'Purchase Bills',
                        purchase_invoice_items:   'Purchase Items',
                        expenses:                 'Expenses',
                        godowns:                  'Godowns',
                        vendors:                  'Vendors',
                        b2b_ledger:               'B2B Ledger',
                      }
                      const fmtEntity = (e) => ENTITY_LABEL[e] || (e ? e.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase()) : '')

                      const isActivelySyncing = !!(syncProgress && syncProgress.total > 0 && syncProgress.done < syncProgress.total)
                      const pct = syncProgress && syncProgress.total > 0
                        ? Math.round((syncProgress.done / syncProgress.total) * 100)
                        : 0

                      // When not actively syncing but queue is non-empty, show next_entity
                      const nextEntityLabel = !isActivelySyncing && queueDepth.next_entity
                        ? fmtEntity(queueDepth.next_entity)
                        : null

                      // Per-entity pills from entity_counts
                      const entityPills = queueDepth.entity_counts && Object.keys(queueDepth.entity_counts).length > 0
                        ? Object.entries(queueDepth.entity_counts)
                        : null

                      return (
                        <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>

                          {/* Outbox summary row */}
                          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                            <span style={{ color: 'var(--text-secondary)' }}>Sync Outbox</span>
                            <span style={{
                              fontWeight: '600',
                              color: isSyncPaused ? 'var(--warning, #f59e0b)' : (queueDepth.pending_count > 0 ? 'var(--warning)' : 'var(--success)')
                            }}>
                              {isSyncPaused ? 'Paused — Pro Required' : (queueDepth.pending_count > 0 ? `${queueDepth.pending_count} pending` : 'Fully Synced')}
                            </span>
                          </div>

                          {/* Per-entity pills — visible when idle with pending items */}
                          {!isActivelySyncing && entityPills && (
                            <div style={{ display: 'flex', flexWrap: 'wrap', gap: '4px', paddingLeft: 2 }}>
                              {entityPills.map(([ent, cnt]) => (
                                <span key={ent} style={{
                                  fontSize: '0.7rem', fontWeight: 600,
                                  background: 'rgba(245,158,11,0.12)',
                                  border: '1px solid rgba(245,158,11,0.3)',
                                  borderRadius: 10, padding: '2px 7px',
                                  color: 'var(--warning, #f59e0b)',
                                  display: 'inline-flex', alignItems: 'center', gap: 4,
                                }}>
                                  {fmtEntity(ent)} <span style={{ opacity: 0.75 }}>×{cnt}</span>
                                </span>
                              ))}
                            </div>
                          )}

                          {/* LIVE: Syncing Now banner — visible while sync.progress SSE arrives */}
                          {isActivelySyncing && (() => {
                            const isPush  = (syncProgress.phase || 'push') === 'push'
                            const accent  = isPush ? '#68d391' : '#63b3ed'  // green=up, blue=down
                            const accentA = isPush ? 'rgba(104,211,145,' : 'rgba(99,179,237,'
                            const dirLabel = isPush
                              ? '↑ Local → Cloud'
                              : '↓ Cloud → Local'
                            return (
                              <div style={{
                                background: `${accentA}0.07)`,
                                border: `1px solid ${accentA}0.25)`,
                                borderRadius: 8, padding: '8px 10px',
                                display: 'flex', flexDirection: 'column', gap: 6,
                              }}>
                                {/* Header row: spinner + direction + count */}
                                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 6 }}>
                                  <span style={{ display: 'inline-flex', alignItems: 'center', gap: 5, fontSize: '0.73rem', color: accent, fontWeight: 700 }}>
                                    <span className="sync-spinner-small" style={{ borderColor: `${accentA}0.25)`, borderTopColor: accent }} />
                                    Syncing
                                  </span>
                                  {/* Direction badge */}
                                  <span style={{
                                    fontSize: '0.67rem', fontWeight: 700,
                                    background: `${accentA}0.13)`,
                                    border: `1px solid ${accentA}0.3)`,
                                    borderRadius: 10, padding: '2px 8px',
                                    color: accent, letterSpacing: '0.01em',
                                  }}>
                                    {dirLabel}
                                  </span>
                                  <span style={{ fontSize: '0.7rem', color: 'var(--text-muted)', fontWeight: 600 }}>
                                    {syncProgress.done} / {syncProgress.total}
                                  </span>
                                </div>

                                {/* Entity pills for current chunk */}
                                {(syncProgress.entities || []).length > 0 && (
                                  <div style={{ display: 'flex', flexWrap: 'wrap', gap: '4px' }}>
                                    {(syncProgress.entities || []).map(e => (
                                      <span key={e} style={{
                                        fontSize: '0.69rem', fontWeight: 700,
                                        background: `${accentA}0.15)`,
                                        border: `1px solid ${accentA}0.35)`,
                                        borderRadius: 10, padding: '2px 8px',
                                        color: accent,
                                      }}>
                                        {fmtEntity(e)}
                                      </span>
                                    ))}
                                  </div>
                                )}

                                {/* Progress bar */}
                                <div style={{ background: `${accentA}0.12)`, borderRadius: 4, height: 4, overflow: 'hidden' }}>
                                  <div style={{
                                    height: '100%',
                                    width: `${pct}%`,
                                    background: accent,
                                    borderRadius: 4,
                                    transition: 'width 0.4s ease',
                                  }} />
                                </div>
                              </div>
                            )
                          })()}

                          {/* Up next hint when idle but pending */}
                          {nextEntityLabel && !isActivelySyncing && (
                            <div style={{ fontSize: '0.7rem', color: 'var(--text-muted)', paddingLeft: 2 }}>
                              Up next: <strong style={{ color: 'var(--text-secondary)' }}>{nextEntityLabel}</strong>
                            </div>
                          )}
                        </div>
                      )
                    })()
                  }



                  {effectiveMode !== 'hybrid' && (
                    <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                      <span style={{ color: 'var(--text-secondary)' }}>Last Sync Message</span>
                      <span style={{ fontWeight: '600', color: 'var(--text-primary)', textTransform: 'capitalize' }}>
                        {syncHealth.lastEntity ? `${syncHealth.lastEntity} updated` : 'None'}
                      </span>
                    </div>
                  )}

                  {effectiveMode === 'hybrid' && queueDepth.last_sync_time && (
                    <div style={{ display: 'flex', flexDirection: 'column', gap: '2px', borderTop: '1px solid var(--border)', paddingTop: '6px' }}>
                      <span style={{ color: 'var(--text-secondary)' }}>Last Synced At</span>
                      <span style={{ fontWeight: '500', color: 'var(--text-muted)', fontSize: '0.72rem' }}>
                        {formatIST(queueDepth.last_sync_time)}
                      </span>
                    </div>
                  )}

                  {effectiveMode !== 'hybrid' && syncHealth.lastSyncTime && (
                    <div style={{ display: 'flex', flexDirection: 'column', gap: '2px', borderTop: '1px solid var(--border)', paddingTop: '6px' }}>
                      <span style={{ color: 'var(--text-secondary)' }}>Last Synced At</span>
                      <span style={{ fontWeight: '500', color: 'var(--text-muted)', fontSize: '0.72rem' }}>
                        {formatIST(syncHealth.lastSyncTime)}
                      </span>
                    </div>
                  )}

                  {lastAutoRefresh && (
                    <div style={{ display: 'flex', flexDirection: 'column', gap: '2px', borderTop: '1px solid var(--border)', paddingTop: '6px' }}>
                      <span style={{ color: 'var(--text-secondary)' }}>Last Auto-Refreshed At</span>
                      <span style={{ fontWeight: '500', color: 'var(--text-muted)', fontSize: '0.72rem' }}>
                        {formatIST(lastAutoRefresh)}
                      </span>
                    </div>
                  )}
                </div>

                {effectiveMode === 'hybrid' && queueDepth.last_error && (
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

                {effectiveMode !== 'hybrid' && syncHealth.error && (
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

                {effectiveMode === 'hybrid' && (
                  <button
                    onClick={(e) => {
                      e.stopPropagation()
                      if (isSyncPaused) {
                        handleCheckPlan(e)
                      } else {
                        handleSyncFlush()
                      }
                    }}
                    disabled={flushing || checkingPlan}
                    style={{
                      width: '100%',
                      padding: '6px 12px',
                      backgroundColor: (flushing || checkingPlan) ? 'rgba(255,255,255,0.08)' : 'var(--accent, #3b82f6)',
                      color: (flushing || checkingPlan) ? 'var(--text-muted)' : '#fff',
                      border: 'none',
                      borderRadius: 'var(--radius-sm, 4px)',
                      cursor: (flushing || checkingPlan) ? 'not-allowed' : 'pointer',
                      fontWeight: '600',
                      fontSize: '0.75rem',
                      transition: 'background-color 0.2s',
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      gap: '6px'
                    }}
                  >
                    {isSyncPaused ? (
                      <>
                        <span className={checkingPlan ? 'sync-spinner-small' : ''} />
                        {checkingPlan ? 'Checking...' : 'Refresh Plan Status'}
                      </>
                    ) : (
                      <>
                        <SyncIcon size={12} className={flushing ? 'sync-spinner-small' : ''} />
                        {flushing ? 'Syncing Now...' : 'Sync Now'}
                      </>
                    )}
                  </button>
                )}

                {effectiveMode !== 'hybrid' && (syncHealth.status === 'error' || syncHealth.status === 'connecting') && (
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

                {/* Refresh Page Content Button — always visible in the popover */}
                <button
                  onClick={(e) => {
                    e.stopPropagation()
                    window.dispatchEvent(new CustomEvent('sync-event', {
                      detail: { type: 'sync.reconnect' }
                    }))
                  }}
                  style={{
                    width: '100%',
                    padding: '6px 12px',
                    backgroundColor: 'rgba(255, 255, 255, 0.05)',
                    border: '1px solid var(--border)',
                    color: 'var(--text-primary)',
                    borderRadius: 'var(--radius-sm, 4px)',
                    cursor: 'pointer',
                    fontWeight: '600',
                    fontSize: '0.75rem',
                    transition: 'all 0.2s',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    gap: '6px',
                    marginTop: '6px'
                  }}
                  onMouseEnter={(e) => {
                    e.currentTarget.style.backgroundColor = 'rgba(255, 255, 255, 0.1)'
                    e.currentTarget.style.borderColor = 'var(--text-muted)'
                  }}
                  onMouseLeave={(e) => {
                    e.currentTarget.style.backgroundColor = 'rgba(255, 255, 255, 0.05)'
                    e.currentTarget.style.borderColor = 'var(--border)'
                  }}
                  title="Refresh Page Content"
                >
                  <SyncIcon size={12} className={showRefreshFlash ? 'sync-spinner-small' : ''} />
                  Refresh Page Data
                </button>
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

                   {!isCollapsed && items.map(({ to, icon, label, external }) => {
                    if (external) {
                      if (!getAiDashboardUrl()) return null // no dashboard on this platform
                      return (
                        <a
                          key={label}
                          href={getAiDashboardUrl()}
                          className="nav-link"
                          onClick={(e) => {
                            e.preventDefault()
                            setMobileMenuOpen(false)
                            if (aiGated) {
                              window.alert('Dashboard BIZASSIST is part of the Pro plan. Contact your provider to upgrade.')
                              return
                            }
                            openAiDashboard()
                          }}
                        >
                          <span className="nav-icon">{icon}</span>
                          {label}
                          {aiGated && (
                            <span style={{
                              marginLeft: 'auto', fontSize: '0.6rem', fontWeight: 800,
                              letterSpacing: '0.08em', padding: '2px 6px', borderRadius: 6,
                              background: 'var(--accent)', color: '#fff'
                            }}>PRO</span>
                          )}
                        </a>
                      )
                    }
                    return (
                    <NavLink
                      key={to}
                      to={to}
                      end={to === '/'}
                      onClick={() => setMobileMenuOpen(false)}
                      className={({ isActive }) =>
                        'nav-link' + (isActive ? ' active' : '')
                      }
                    >
                      <span className="nav-icon">{icon}</span>
                      {label}
                    </NavLink>
                    )
                  })}
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
                  const targetUid = user?.user_id || user?.id
                  if (targetUid) {
                    localStorage.removeItem(`pos_minimized_${targetUid}`);
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
                        const cleanupUid = user?.user_id || user?.id
                        if (cleanupUid) {
                          localStorage.removeItem(`pos_minimized_${cleanupUid}`);
                          localStorage.removeItem(`pos_minimized_tabs_${cleanupUid}`);
                          localStorage.removeItem(`pos_minimized_active_id_${cleanupUid}`);
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
            
            {minimizedLive && (
              <div
                className="pos-minimized-card"
                style={{ marginTop: minimizedBill ? 10 : 0, borderLeft: '3px solid var(--accent)' }}
                onClick={() => {
                  const targetUid = user?.user_id || user?.id
                  const targetCounter = minimizedLive.counter;
                  const targetClientId = minimizedLive.clientId;
                  if (targetUid) {
                    localStorage.removeItem(`pos_live_minimized_${targetUid}`);
                  }
                  window.dispatchEvent(new Event('pos_minimized_changed'));
                  navigate(`/live-view?live_counter=${encodeURIComponent(targetCounter)}${targetClientId ? `&client_id=${encodeURIComponent(targetClientId)}` : ''}`);
                }}
              >
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <span style={{ fontSize: '0.78rem', fontWeight: 700, color: 'var(--accent)', letterSpacing: '0.02em' }}>
                    <ZapIcon size={14} style={{ color: 'var(--accent)', marginRight: 6, display: 'inline-block', verticalAlign: 'middle' }} /> Live View: {minimizedLive.counter}
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
                      if (window.confirm('Discard active live counter monitoring draft?')) {
                        const cleanupUid = user?.user_id || user?.id
                        if (cleanupUid) {
                          localStorage.removeItem(`pos_live_minimized_${cleanupUid}`);
                          localStorage.removeItem(`pos_live_minimized_counter_${cleanupUid}`);
                          localStorage.removeItem(`pos_live_minimized_client_id_${cleanupUid}`);
                          localStorage.removeItem(`pos_live_minimized_tabs_${cleanupUid}`);
                          localStorage.removeItem(`pos_live_minimized_active_id_${cleanupUid}`);
                        }
                        window.dispatchEvent(new Event('pos_minimized_changed'));
                      }
                    }}
                   aria-label="Close"><CloseIcon size={16} /></button>
                </div>
                <div style={{ fontSize: '0.82rem', fontWeight: 600, color: 'var(--text-primary)' }}>
                  {minimizedLive.name}
                </div>
                <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.72rem', color: 'var(--text-secondary)', marginTop: 2 }}>
                  <span>{minimizedLive.itemsCount} items</span>
                  <span style={{ fontWeight: 700, color: 'var(--success)' }}>
                    ₹{minimizedLive.totalAmt.toLocaleString('en-IN', { maximumFractionDigits: 2 })}
                  </span>
                </div>
              </div>
            )}
            
            {showProfileMenu && (
              <div className="profile-menu" ref={profileMenuRef} onClick={e => e.stopPropagation()} onMouseDown={e => e.stopPropagation()}>
                <div className="profile-menu-header">
                  <div className="profile-menu-biz">{profile?.business_name || user?.username || 'BizAssist User'}</div>
                  <div className="profile-menu-sub">Enterprise Account</div>
                </div>
                <div className="profile-menu-sep" />
                <Link className="profile-menu-item" to="/profile" onClick={() => setShowProfileMenu(false)}>
                  <UserIcon size={14} /> My Profile
                </Link>
                <Link className="profile-menu-item" to="/settings" onClick={() => setShowProfileMenu(false)}>
                  <SettingsIcon size={14} /> App Settings
                </Link>
                <Link className="profile-menu-item" to="/settings?tab=staff" onClick={() => setShowProfileMenu(false)}>
                  <ContactsIcon size={14} /> Staff & Cashiers
                </Link>
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
                <button
                  className="profile-menu-item"
                  onClick={() => { setShowProfileMenu(false); navigate('/support'); }}
                  style={{ display: 'flex', alignItems: 'center', gap: 8 }}
                >
                  <AlertIcon size={14} /> Feedback & Support
                </button>
                {!IS_DESKTOP_APP && (
                  <button
                    className="btn-premium"
                    style={{ width: 'calc(100% - 20px)', margin: '6px 10px', padding: '9px 12px', fontSize: '0.8rem' }}
                    onClick={() => { setShowProfileMenu(false); openDownloadPage(); }}
                  >
                    <DownloadIcon size={14} /> Download Desktop App
                  </button>
                )}
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

      {/* Mobile Top Header Bar */}
      {!isSalesPage && (
        <header className="mobile-header">
          <button
            type="button"
            className="mobile-menu-toggle"
            onClick={() => setMobileMenuOpen(true)}
            aria-label="Open menu"
          >
            <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
              <line x1="3" y1="12" x2="21" y2="12"></line>
              <line x1="3" y1="6" x2="21" y2="6"></line>
              <line x1="3" y1="18" x2="21" y2="18"></line>
            </svg>
          </button>

          <div className="mobile-header-brand" onClick={() => navigate('/')}>
            {profile?.logo ? (
              <img src={profile.logo} alt="Logo" style={{ width: 28, height: 28, objectFit: 'contain', borderRadius: '4px' }} />
            ) : (
              <BuildingMark size={22} />
            )}
            <span className="mobile-brand-name">
              {profile?.business_name || user?.business_name || 'BizAssist'}
            </span>
          </div>

          <div className="mobile-user-avatar-wrapper" ref={userChipRef}>
            <div
              className="mobile-user-avatar"
              onClick={() => setShowProfileMenu(!showProfileMenu)}
            >
              {profile?.logo ? (
                <img src={profile.logo} alt="Logo" />
              ) : (
                initials
              )}
            </div>

            {/* Profile Dropdown positioned below avatar on mobile */}
            {showProfileMenu && (
              <div className="profile-menu mobile-dropdown" ref={profileMenuRef} onClick={e => e.stopPropagation()} onMouseDown={e => e.stopPropagation()}>
                <div className="profile-menu-header">
                  <div className="profile-menu-biz">{profile?.business_name || user?.username || 'BizAssist User'}</div>
                  <div className="profile-menu-sub">Enterprise Account</div>
                </div>
                <div className="profile-menu-sep" />
                <Link className="profile-menu-item" to="/profile" onClick={() => setShowProfileMenu(false)}>
                  <UserIcon size={14} /> My Profile
                </Link>
                <Link className="profile-menu-item" to="/settings" onClick={() => setShowProfileMenu(false)}>
                  <SettingsIcon size={14} /> App Settings
                </Link>
                <Link className="profile-menu-item" to="/settings?tab=staff" onClick={() => setShowProfileMenu(false)}>
                  <ContactsIcon size={14} /> Staff & Cashiers
                </Link>
                <button
                  className="profile-menu-item"
                  onClick={() => {
                    setShowProfileMenu(false)
                    if (hasLock) {
                      lock()
                    } else {
                      navigate('/settings')
                    }
                  }}
                  style={{ color: 'var(--warning, #f59e0b)', display: 'flex', alignItems: 'center', gap: 8 }}
                >
                  <LockIcon size={14} /> {hasLock ? 'Lock Session' : 'Lock App (Set PIN)'}
                </button>
                <button
                  className="profile-menu-item"
                  onClick={() => { setShowProfileMenu(false); navigate('/support'); }}
                  style={{ display: 'flex', alignItems: 'center', gap: 8 }}
                >
                  <AlertIcon size={14} /> Feedback & Support
                </button>
                {!IS_DESKTOP_APP && (
                  <button
                    className="btn-premium"
                    style={{ width: 'calc(100% - 20px)', margin: '6px 10px', padding: '9px 12px', fontSize: '0.8rem' }}
                    onClick={() => { setShowProfileMenu(false); openDownloadPage(); }}
                  >
                    <DownloadIcon size={14} /> Download Desktop App
                  </button>
                )}
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
          </div>
        </header>
      )}

      {/* Backdrop overlay for mobile drawer */}
      {mobileMenuOpen && !isSalesPage && (
        <div
          className="mobile-drawer-backdrop"
          onClick={() => setMobileMenuOpen(false)}
        />
      )}

      {/* ── Main area ── */}
      <div className="main-area">

        {/* ── Page content ── */}
        <main className="page-content" style={{ position: 'relative' }}>
          {/* ⓘ page help — one mount point, per-route content (config/helpContent.js) */}
          <PageHelp />
          {children}
        </main>
      </div>

      {/* Toast portal — rendered at document.body to escape overflow:hidden on .app-shell */}
      {toasts.length > 0 && createPortal(
        <div style={{
          position: 'fixed',
          bottom: 24,
          right: 24,
          zIndex: 99999,
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
              boxShadow: '0 10px 30px -5px rgba(0,0,0,0.25)',
              display: 'flex',
              alignItems: 'center',
              gap: 12,
              animation: 'slideIn 0.2s ease-out',
              minWidth: 240
            }}>
              <span style={{ display: 'inline-flex', alignItems: 'center', flexShrink: 0 }}>
                {toast.type === 'success' ? <CheckIcon size={16} style={{ color: 'var(--success, #22c55e)' }} /> :
                 toast.type === 'error' ? <AlertIcon size={16} style={{ color: 'var(--danger, #ef4444)' }} /> :
                 toast.type === 'warning' ? <AlertIcon size={16} style={{ color: 'var(--warning, #f59e0b)' }} /> :
                 <SummaryIcon size={16} style={{ color: 'var(--accent, #3b82f6)' }} />}
              </span>
              <span style={{ fontSize: '0.82rem', fontWeight: 500, color: 'var(--text, #1e293b)', lineHeight: 1.4, flex: 1 }}>
                {toast.msg}
              </span>
              <button
                onClick={() => setToasts(prev => prev.filter(t => t.id !== toast.id))}
                style={{
                  background: 'none',
                  border: 'none',
                  color: 'var(--text-muted, #64748b)',
                  cursor: 'pointer',
                  marginLeft: 4,
                  display: 'flex',
                  alignItems: 'center',
                  padding: 0,
                  flexShrink: 0
                }}
                aria-label="Close"
              >
                <CloseIcon size={14} />
              </button>
            </div>
          ))}
        </div>,
        document.body
      )}
      {sessionExpired && (
        <div style={{
          position: 'fixed',
          inset: 0,
          zIndex: 99999,
          background: 'rgba(15, 23, 42, 0.95)',
          backdropFilter: 'blur(16px)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          padding: 24,
        }}>
          <div style={{
            background: 'var(--bg-2, #1a1a1a)',
            border: '1px solid var(--border, rgba(255, 255, 255, 0.12))',
            borderRadius: 24,
            padding: '40px 48px',
            width: '100%',
            maxWidth: 500,
            boxShadow: '0 25px 50px -12px rgba(0, 0, 0, 0.5)',
            textAlign: 'center',
          }}>
            <div style={{
              width: 80,
              height: 80,
              borderRadius: '50%',
              background: 'linear-gradient(135deg, #6366f1 0%, #4f46e5 100%)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              margin: '0 auto 24px',
              boxShadow: '0 8px 30px rgba(99, 102, 241, 0.3)'
            }}>
              <LockIcon size={40} style={{ color: '#fff' }} />
            </div>

            <h2 style={{
              fontSize: '1.75rem',
              fontWeight: 800,
              color: 'var(--text-primary, #fff)',
              marginBottom: 16,
              letterSpacing: '-0.02em',
              lineHeight: 1.2
            }}>
              Upgrade to Pro Required
            </h2>

            <p style={{
              fontSize: '0.94rem',
              color: 'var(--text-secondary, #ccc)',
              lineHeight: 1.6,
              marginBottom: 24
            }}>
              Your 5-minute preview of the cloud application has expired. Access to the shared cloud database, multi-device sync, and premium features require a Pro subscription.
            </p>

            <div style={{
              background: 'rgba(99, 102, 241, 0.08)',
              border: '1px solid rgba(99, 102, 241, 0.25)',
              borderRadius: 12,
              padding: '16px',
              fontSize: '0.84rem',
              color: 'var(--text-primary, #fff)',
              lineHeight: 1.5,
              marginBottom: 28,
              textAlign: 'left'
            }}>
              <strong>Want to upgrade?</strong> Contact your provider or system administrator to activate the <strong>Pro Plan</strong> and resume work.
            </div>

            <div style={{
              display: 'flex',
              flexDirection: 'column',
              gap: 12
            }}>
              <button
                onClick={() => {
                  sessionStorage.removeItem('bizassist_session_start_time')
                  logout()
                  navigate('/login')
                }}
                style={{
                  padding: '14px 28px',
                  borderRadius: 12,
                  background: 'linear-gradient(135deg, #6366f1 0%, #4f46e5 100%)',
                  color: '#fff',
                  border: 'none',
                  cursor: 'pointer',
                  fontSize: '0.9rem',
                  fontWeight: 700,
                  boxShadow: '0 4px 14px rgba(99, 102, 241, 0.4)',
                  transition: 'all 0.2s',
                  width: '100%'
                }}
              >
                Sign Out
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
