import React from 'react'
import { createPortal } from 'react-dom'
import { NavLink, Link, useNavigate, useLocation } from 'react-router-dom'
import { useAuth } from '../contexts/AuthContext'
import { useConfirm } from '../contexts/ConfirmContext'
import { useLock } from '../contexts/LockContext'
import { API_BASE, IS_LOCAL_APP } from '../config'
import { logger } from '../utils/logger'
import { formatIST } from '../utils/format'
import { resolveHostingMode } from '../utils/resolveHostingMode'
import { getAiDashboardUrl, openAiDashboard } from '../config/aiDashboard'
import { IS_DESKTOP_APP, openDownloadPage } from '../config/downloadApp'
import { BuildingMark } from '../components/Logo'
import PageLoader from '../components/PageLoader'
import PageHelp from '../components/PageHelp'
import SyncNudgeModal from '../components/hosting/SyncNudgeModal'
import WebLocalOnlyNotice from '../components/hosting/WebLocalOnlyNotice'
import SidebarContextMenu from '../components/layout/SidebarContextMenu'
import ToastContainer from '../components/layout/ToastContainer'
import SessionExpiredModal from '../components/layout/SessionExpiredModal'
import { useDocLabels } from '../hooks/useDocLabels'
// HostingOnboardingModal removed: hosting is now chosen once, in Register.
// The post-login onboarding pop-up duplicated that choice and was intrusive.
import { BillsIcon, CashIcon, ChevronDownIcon, CloseIcon, ConnectionIcon, ContactsIcon, CounterIcon, DashboardIcon, HomeIcon, ImportIcon, InventoryIcon, LockIcon, LogoutIcon, OrderIcon, ReportsIcon, SettingsIcon, SummaryIcon, TaxIcon, ZapIcon, SunIcon, MoonIcon, MonitorIcon, UserIcon, CheckIcon, AlertIcon, SyncIcon, DownloadIcon, PlusIcon } from '../components/Icons'


const NAV = [
  {
    section: 'Supply & Inflow',
    items: [
      { to: '/stock',     icon: <InventoryIcon size={16} className="nav-anim-inventory" />, label: 'Stock & Purchases' },
      // TRIAL ENTRY — remove together with StockPurchases.jsx once the revamped
      // workspace is signed off (deletion trigger at the top of
      // StockWorkspace.jsx). Kept visibly labelled so it cannot quietly become
      // a permanent second way to reach the same screen.
      { to: '/stock-workspace', icon: <InventoryIcon size={16} className="nav-anim-inventory" />, label: 'Stock (new)' },
      { to: '/b2b', icon: <OrderIcon size={16} className="nav-anim-b2border" />, label: 'B2B' },
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
      // Contacts & Payments workspace: Contacts · Transactions · Invoices tabs
      { to: '/parties',  icon: <ContactsIcon size={16} className="nav-anim-contact" />,  label: 'Contacts & Payments' },
      // /money routes preserved for backward-compat but removed from nav
      { to: '/reports',  icon: <ReportsIcon size={16} className="nav-anim-report" />,   label: 'GST & Tax Reports' },
    ]
  }
]

// Flat list for sub-navbar (only key pages, grouped)
const SUBNAV = [
  { to: '/',           label: 'Home',                  icon: <HomeIcon size={14} /> },
  { to: '/dashboard',  label: 'Dashboard',             icon: <DashboardIcon size={14} /> },
  { to: '/sales',      label: 'Billing',               icon: <CounterIcon size={14} /> },
  { to: '/parties',    label: 'Contacts & Payments',   icon: <ContactsIcon size={14} /> },
  { to: '/stock',      label: 'Stock & Purchases',     icon: <InventoryIcon size={14} /> },
  { to: '/reports',    label: 'Reports',               icon: <ReportsIcon size={14} /> },
]

// Map route -> page title
const PAGE_TITLES = {
  '/':              'Home',
  '/dashboard':     'Dashboard',
  '/sales':         'Billing Counter',
  '/parties':       'Contacts & Payments',
  '/stock':         'Stock & Purchases',
  '/b2b':           'B2B',
  '/reports':       'GST & Tax Reports',
  '/import':        'Data Migration',
  '/profile':       'My Profile',
  '/staff':         'Staff & Cashiers',
  '/settings':      'App Settings',
}

// The five screens a counter lives in, for the mobile bottom bar. Deliberately
// a list of ROUTES, not of nav objects: the icon and label are looked up from
// the sidebar's own nav list at render time, so this can never drift into
// showing a tab the sidebar has renamed or the plan has hidden.
// Workspaces that open with the sidebar collapsed to its rail. Stock is a wide
// data grid built as a full-bleed POS surface; the nav costs it 240px it has a
// real use for. Prefix match, so /stock/inventory, /stock/purchases and any
// future tab inherit it.
const AUTO_COLLAPSE_ROUTES = ['/stock', '/stock-workspace']

const BOTTOM_BAR_ROUTES = ['/', '/sales', '/stock', '/parties', '/reports']

export default function AppLayout({ children, title }) {
  const { user, logout, profile, token, businessConfig, appReady, setAppReady, settings, fetchSettings } = useAuth()
  const { hasLock, lock, resetInactivityTimer } = useLock()
  const confirm = useConfirm()
  const navigate = useNavigate()
  const location = useLocation()
  const label = useDocLabels()

  // Quick actions surfaced in the sidebar right-click menu.
  // Each entry: { label, icon: <SvgComponent />, action(navigate) }
  const QUICK_ACTIONS = {
    '/':            (nav) => [
      { label: 'Go to Home',           icon: <HomeIcon size={14} />,      action: () => nav('/') },
      { label: 'Open Billing Counter', icon: <CounterIcon size={14} />,   action: () => nav('/sales') },
    ],
    '/dashboard':   (nav) => [
      { label: 'Open Dashboard',       icon: <DashboardIcon size={14} />, action: () => nav('/dashboard') },
      { label: 'Refresh Data',         icon: <SyncIcon size={14} />,      action: () => window.dispatchEvent(new CustomEvent('sync-event', { detail: { type: 'sync.reconnect' } })) },
    ],
    '/sales':       (nav) => [
      { label: 'New Invoice',          icon: <PlusIcon size={14} />,      action: () => nav('/sales') },
      { label: "Today's Bills",        icon: <BillsIcon size={14} />,     action: () => nav('/sales?view=today') },
    ],
    '/stock':       (nav) => [
      { label: 'Stock & Items',        icon: <InventoryIcon size={14} />, action: () => nav('/stock/inventory') },
      { label: label('purchase') + 's',       icon: <BillsIcon size={14} />,     action: () => nav('/stock/purchase') },
      { label: 'Adjust Stock',         icon: <ZapIcon size={14} />,       action: () => { nav('/stock/inventory'); setTimeout(() => window.dispatchEvent(new CustomEvent('open_adjust_stock')), 200) } },
    ],
    '/parties':     (nav) => [
      { label: 'Contacts',             icon: <ContactsIcon size={14} />,  action: () => nav('/parties/contacts') },
      { label: 'Transactions',         icon: <CashIcon size={14} />,      action: () => nav('/parties/payments') },
      { label: 'Add Contact',          icon: <PlusIcon size={14} />,      action: () => { nav('/parties/contacts'); setTimeout(() => window.dispatchEvent(new CustomEvent('open_add_contact')), 200) } },
    ],
    '/reports':     (nav) => [
      { label: 'Open Reports',         icon: <ReportsIcon size={14} />,   action: () => nav('/reports') },
      { label: 'GST Summary',          icon: <TaxIcon size={14} />,       action: () => nav('/reports?tab=gst') },
    ],
    '/b2b':         (nav) => [
      { label: 'Place an order',       icon: <OrderIcon size={14} />,      action: () => nav('/b2b?tab=order') },
      { label: 'Outgoing orders',      icon: <OrderIcon size={14} />,      action: () => nav('/b2b?tab=outgoing') },
      { label: 'Incoming orders',      icon: <OrderIcon size={14} />,      action: () => nav('/b2b?tab=incoming') },
      { label: 'Connections',          icon: <ConnectionIcon size={14} />, action: () => nav('/b2b?tab=connections') },
    ],
    '/import':      (nav) => [
      { label: 'Data Migration',       icon: <ImportIcon size={14} />,    action: () => nav('/import') },
    ],
    '/pos-live-counter': (nav) => [
      { label: 'Open Live Counter',    icon: <MonitorIcon size={14} />,   action: () => nav('/pos-live-counter') },
    ],
  }

  const hostingMode = settings?.general?.hosting_mode || null
  const deviceMode = (typeof localStorage !== 'undefined' && localStorage.getItem('bizassist_hosting_mode')) || null
  // Derived from URL + plan + device routing — never from a remembered value
  // that can go stale. See utils/resolveHostingMode.js for why.
  const effectiveMode = resolveHostingMode({
    isLocalApp: IS_LOCAL_APP,
    plan: settings?.subscription?.plan,
    savedMode: hostingMode,
    deviceMode,
  })
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

  // ── Cloud Pull Countdown (hybrid mode only) ───────────────────────────────
  const pullIntervalSec = Math.max(
    parseInt(settings?.general?.cloud_pull_interval ?? 120, 10) || 120,
    30
  )
  const [nextPullIn, setNextPullIn] = React.useState(null)   // seconds until next auto-pull
  const [pulling, setPulling] = React.useState(false)        // "Pull Now" in-flight

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

  // "Pull from Cloud Now" — triggers the backend flush (which also pulls),
  // then resets the countdown to full interval.
  const handlePullNow = React.useCallback(async () => {
    if (!token || pulling) return
    setPulling(true)
    try {
      // ?pull=true is REQUIRED — without it the backend only flushes the outbox
      // (push) and never fetches cloud-authored rows, so this button silently
      // did nothing for cloud → local convergence.
      await fetch(`${API_BASE}/api/sync/flush?pull=true`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}` }
      })
      // Give the server ~2s to complete the pull cycle, then refresh depth
      setTimeout(async () => {
        try {
          const r = await fetch(`${API_BASE}/api/sync/queue-depth`, {
            headers: { Authorization: `Bearer ${token}` }
          })
          if (r.ok) setQueueDepth(await r.json())
        } catch (e) {}
        setPulling(false)
        setNextPullIn(pullIntervalSec)
        window.dispatchEvent(new CustomEvent('sync-flushed'))
      }, 2000)
    } catch (err) {
      logger.error('Pull from cloud failed:', err)
      setPulling(false)
    }
  }, [token, pulling, pullIntervalSec])

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

    // A sale (or any local write) queues outbox rows immediately, but the panel
    // only re-read the depth on its 30s tick — so right after completing a sale
    // the status still showed the PREVIOUS state: stale "0 pending" and a stale
    // last-sync time, exactly when the owner looks at it to confirm the sale is
    // safe. Refresh on the same SSE events that signal local data changed.
    //
    // Debounced: a single sale emits several triggers (invoice, payment, stock)
    // and sync.progress fires per chunk; without this the panel would issue a
    // burst of queue-depth requests per sale.
    let debounce = null
    const handleDataChanged = (e) => {
      const t = e?.detail?.type
      if (t !== 'sync.trigger' && t !== 'sync.progress' && t !== 'sync.pull_ping') return
      if (debounce) clearTimeout(debounce)
      debounce = setTimeout(fetchQueueDepth, 600)
    }
    window.addEventListener('sync-event', handleDataChanged)

    return () => {
      clearInterval(interval)
      if (debounce) clearTimeout(debounce)
      window.removeEventListener('sync-flushed', handleSyncFlushed)
      window.removeEventListener('sync-event', handleDataChanged)
    }
  }, [effectiveMode, token])

  // ── Pull countdown tick ───────────────────────────────────────────────────
  // Counts down to the next periodic pull cycle based on pullIntervalSec (default 120s).
  // Resets cleanly when manual pull/flush is triggered.
  React.useEffect(() => {
    if (effectiveMode !== 'hybrid') return
    const tick = () => {
      if (pulling) {
        setNextPullIn(0)
        return
      }
      const lastStr = queueDepth.last_sync_time
      const baseMs = lastStr ? new Date(lastStr).getTime() : Date.now()
      const elapsed = Math.max(0, Math.floor((Date.now() - baseMs) / 1000))
      // Cyclic remaining seconds in current interval (e.g. 120s cycle)
      const cyclePos = elapsed % pullIntervalSec
      const rem = cyclePos === 0 ? 0 : (pullIntervalSec - cyclePos)
      setNextPullIn(rem)
    }
    tick()
    const t = setInterval(tick, 1000)
    return () => clearInterval(t)
  }, [effectiveMode, queueDepth.last_sync_time, pullIntervalSec, pulling])

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
  // { entities: ['invoices','customers'], done: 3, total: 7,
  //   failed: 0, rejected: 0 } | null
  const [syncProgress, setSyncProgress] = React.useState(null)
  // Rows the sync could not apply, kept after the progress banner clears.
  // Findings M-12 / M-13: the backend used to drop such rows silently and still
  // report a clean sync, so there was nothing here to show. Now that it reports
  // them, "sync finished" must not be allowed to mean "everything arrived".
  const [syncRowProblems, setSyncRowProblems] = React.useState(0)
  // M-20: rows the cloud is holding until a parent arrives. Deliberately NOT
  // folded into syncRowProblems — they are waiting, not failing, and the owner
  // should not be told a sale "could not be synced" when it is queued and safe.
  const [syncDeferred, setSyncDeferred] = React.useState(0)
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
        // THREE outcomes, and they are NOT interchangeable:
        //   `failed`   — rows the PULL apply path rejected (M-12)
        //   `rejected` — rows the cloud REFUSED to store on PUSH (M-13).
        //                Acked, so they will not be re-sent. Genuinely lost
        //                unless someone acts.
        //   `deferred` — rows the cloud is HOLDING because a parent has not
        //                arrived yet (M-20). NOT acked, still in the outbox,
        //                re-sent every cycle. Nothing is lost and nobody needs
        //                to do anything unless it persists.
        //
        // Counting deferrals as failures would put "could not be synced" over
        // rows that are simply queued — alarming the owner about the mechanism
        // that is protecting their data. Counting them as success would be the
        // M-20 defect again, one layer up. So they get their own, calmer line.
        const problems = (d.failed || 0) + (d.rejected || 0)
        const deferred = d.deferred || 0
        setSyncProgress({
          entities: d.entities || [], done: d.done || 0, total: d.total || 0,
          phase: d.phase || 'push', problems, deferred,
        })
        if (problems > 0) setSyncRowProblems(problems)
        setSyncDeferred(deferred)
        // Auto-clear the progress banner 2.5s after the batch completes — but
        // ONLY when every row landed. Clearing it on a partial batch is exactly
        // the "green banner over missing data" this pair of findings was about.
        if (d.done >= d.total && d.total > 0 && problems === 0) {
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
  // '/purchases' stays listed so the legacy redirect can't be ridden into the
  // purchases tab by a cashier; Godown.jsx additionally hides that tab by role.
  const OWNER_ONLY_PATHS = React.useMemo(() => new Set(['/stock/purchase', '/b2b', '/b2b-network', '/b2b-orders', '/reports', '/import', '/staff', '/dashboard', '/pos-live-counter']), [])
  // What each staff sector is allowed to SEE (backend still enforces writes).
  // '/stock' is the supply adder's whole sector (stock/inventory + purchase bills).
  const SUPPLY_ADDER_PATHS = React.useMemo(() => new Set(['/', '/stock', '/profile', '/support', '/settings']), [])

  React.useEffect(() => {
    if (isCashier && OWNER_ONLY_PATHS.has(location.pathname)) {
      navigate('/sales', { replace: true })
    } else if (isSupplyAdder && !SUPPLY_ADDER_PATHS.has(location.pathname)
               && !location.pathname.startsWith('/stock')
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

  // ── Sidebar right-click context menu ─────────────────────────────────────
  // { x, y, item: { to, label }, flatIndex: number } | null
  const [sidebarCtxMenu, setSidebarCtxMenu] = React.useState(null)

  // Flat ordered list of nav item `to` keys — user can reorder via ctx menu.
  // Derived from visibleNav on first load; persisted to localStorage.
  const [navOrder, setNavOrder] = React.useState(() => {
    try {
      const saved = localStorage.getItem('sidebar_nav_order')
      if (saved) return JSON.parse(saved)
    } catch { /* ignore */ }
    return null // null = use default order from NAV
  })

  // Build the ordered nav: apply custom order if set, else fall back to visibleNav.
  const orderedVisibleNav = React.useMemo(() => {
    // Collect all items from visibleNav into a flat list
    const flat = visibleNav.flatMap(s => s.items.map(item => ({ ...item, section: s.section })))
    if (!navOrder) return flat
    // Sort by the saved order; items not in the saved list go at the end
    const orderMap = Object.fromEntries(navOrder.map((key, i) => [key, i]))
    return [...flat].sort((a, b) => {
      const ai = orderMap[a.to] ?? 9999
      const bi = orderMap[b.to] ?? 9999
      return ai - bi
    })
  }, [visibleNav, navOrder])

  const saveNavOrder = (flat) => {
    const keys = flat.map(i => i.to).filter(Boolean)
    setNavOrder(keys)
    try { localStorage.setItem('sidebar_nav_order', JSON.stringify(keys)) } catch { /* ignore */ }
  }

  const moveNavItem = (flatIndex, direction) => {
    const next = [...orderedVisibleNav]
    const targetIndex = flatIndex + direction
    if (targetIndex < 0 || targetIndex >= next.length) return
    ;[next[flatIndex], next[targetIndex]] = [next[targetIndex], next[flatIndex]]
    saveNavOrder(next)
  }

  // Close ctx menu on outside click or Escape
  React.useEffect(() => {
    if (!sidebarCtxMenu) return
    const close = () => setSidebarCtxMenu(null)
    const onKey = (e) => { if (e.key === 'Escape') close() }
    document.addEventListener('mousedown', close, true)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', close, true)
      document.removeEventListener('keydown', onKey)
    }
  }, [sidebarCtxMenu])

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

  // Whole-sidebar collapse (icon rail) — see BOTTOM_BAR_ROUTES near the bottom
  // bar for the mobile half of the same navigation problem. Distinct from `collapsed` above, which
  // collapses individual nav SECTIONS — different key, different concept, and
  // conflating them would make one setting silently undo the other.
  // Read from localStorage in the initialiser so the rail is already narrow on
  // first paint; setting it in an effect makes the sidebar visibly snap.
  const [sidebarCollapsed, setSidebarCollapsed] = React.useState(() => {
    try { return localStorage.getItem('billing_sidebar_collapsed') === 'true' }
    catch { return false }
  })

  // Routes that want the width more than they want the nav. Entering one
  // collapses the rail; LEAVING restores whatever the owner's saved preference
  // was, so this never silently becomes their global setting.
  //
  // Keyed on pathname only, which is what makes manual override work: the
  // effect fires when you ARRIVE, so expanding the rail while you are on the
  // page sticks until you navigate away and come back.
  React.useEffect(() => {
    const wantsRail = AUTO_COLLAPSE_ROUTES.some(p => location.pathname.startsWith(p))
    if (wantsRail) {
      setSidebarCollapsed(true)
      return
    }
    try {
      setSidebarCollapsed(localStorage.getItem('billing_sidebar_collapsed') === 'true')
    } catch { /* private mode — leave whatever is on screen */ }
  }, [location.pathname])

  const toggleSidebarCollapsed = React.useCallback(() => {
    setSidebarCollapsed(prev => {
      const next = !prev
      try { localStorage.setItem('billing_sidebar_collapsed', String(next)) }
      catch { /* private mode — the toggle still works for this session */ }
      return next
    })
  }, [])
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

  // Full-bleed POS layout: Billing and the LEGACY Stock & Purchases page only.
  // Contacts & Payments (/parties) stays in the normal app layout with the
  // sidebar, and so does the revamped /stock-workspace.
  //
  // `/stock-workspace` is excluded explicitly because `startsWith('/stock')`
  // matches it too — which is why the new page rendered with no sidebar at all
  // and looked "full screen" no matter what its own shell did. The whole point
  // of the revamp is to be a normal page, so it must not inherit this.
  // When the trial ends and /stock points at StockWorkspace, drop the
  // `/stock` clause entirely rather than adding another exception.
  const isSalesPage = location.pathname === '/sales'
    || (location.pathname.startsWith('/stock')
        && !location.pathname.startsWith('/stock-workspace'))
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
        <aside className={`sidebar ${mobileMenuOpen ? 'open' : ''} ${sidebarCollapsed ? 'collapsed' : ''}`}>
          {/* Collapse to an icon rail — same affordance as frontend-ai's
              AppLayout. Hidden on mobile, where the drawer and the bottom bar
              already handle navigation and a rail would just be a third way to
              do the same thing. */}
          <button
            type="button"
            className="sidebar-collapse-btn hide-on-mobile"
            onClick={toggleSidebarCollapsed}
            aria-label={sidebarCollapsed ? 'Expand sidebar' : 'Collapse sidebar'}
            aria-expanded={!sidebarCollapsed}
            title={sidebarCollapsed ? 'Expand sidebar' : 'Collapse sidebar'}
          >
            {sidebarCollapsed ? '›' : '‹'}
          </button>
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
                        purchase_invoices:        label('purchase') + 's',
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

                          {/* ROWS WAITING ON A PARENT (finding M-20).
                              Amber, not red, and worded as a delay rather than a
                              failure — because that is what it is. These rows are
                              still in the outbox and are re-sent every cycle; the
                              cloud is holding them only until a related record
                              arrives. Before M-20 they were acked and deleted, so
                              this state had nothing to show and a real Rs641 sale
                              disappeared with a success message over it. */}
                          {syncDeferred > 0 && (
                            <div style={{
                              background: 'rgba(237,137,54,0.09)',
                              border: '1px solid rgba(237,137,54,0.32)',
                              borderRadius: 8, padding: '8px 10px',
                              display: 'flex', flexDirection: 'column', gap: 4,
                            }}>
                              <span style={{ fontSize: '0.73rem', fontWeight: 700, color: '#ed8936' }}>
                                {syncDeferred} record{syncDeferred === 1 ? '' : 's'} waiting on a related record
                              </span>
                              <span style={{ fontSize: '0.67rem', color: 'var(--text-muted, #a0aec0)', lineHeight: 1.45 }}>
                                Nothing is lost. They are still in the outbox and
                                will send automatically once the record they depend
                                on arrives. If this does not clear on its own, ask
                                support to check which record they are waiting for.
                              </span>
                            </div>
                          )}

                          {/* ROWS THAT DID NOT ARRIVE (findings M-12 / M-13).
                              Sits ABOVE the progress banner and does NOT
                              auto-dismiss. A sync that finishes having dropped
                              rows used to report a clean success — the backend
                              now reports the count, and this is the only place an
                              owner can see it without reading a log file.

                              DEFERRED rows are deliberately NOT counted here: they
                              are queued and safe, and telling an owner a sale
                              "could not be synced" when it is simply waiting would
                              make them distrust the one mechanism protecting it. */}
                          {syncRowProblems > 0 && (
                            <div style={{
                              background: 'rgba(245,101,101,0.09)',
                              border: '1px solid rgba(245,101,101,0.32)',
                              borderRadius: 8, padding: '8px 10px',
                              display: 'flex', flexDirection: 'column', gap: 4,
                            }}>
                              <span style={{ fontSize: '0.73rem', fontWeight: 700, color: '#fc8181' }}>
                                {syncRowProblems} record{syncRowProblems === 1 ? '' : 's'} could not be synced
                              </span>
                              <span style={{ fontSize: '0.67rem', color: 'var(--text-muted, #a0aec0)', lineHeight: 1.45 }}>
                                They are saved for review, not lost. Everything else
                                synced normally. Ask support to check the sync review
                                list if this keeps happening.
                              </span>
                              <button
                                type="button"
                                onClick={() => setSyncRowProblems(0)}
                                style={{
                                  alignSelf: 'flex-start', marginTop: 2,
                                  background: 'transparent', border: 'none', padding: 0,
                                  color: '#fc8181', fontSize: '0.67rem', fontWeight: 700,
                                  cursor: 'pointer', textDecoration: 'underline',
                                }}
                              >
                                Dismiss
                              </button>
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

                  {/* ── Cloud pull row (hybrid only, Pro only) ───────────────── */}
                  {effectiveMode === 'hybrid' && (() => {
                    const isPro = subscription?.plan === 'pro'
                    if (!isPro) return null   // Free: this row is not relevant

                    const hasSyncError = syncHealth.status === 'error' || !!syncHealth.last_error
                    // "Active" means the backend's cloud event stream is really
                    // attached — reported by services/cloud_listener via
                    // queue-depth — NOT merely that the user ticked the setting.
                    // The old test was `cloud_push_ping_enabled !== false`, which
                    // read an unset flag as TRUE and so showed a green "active"
                    // badge (and hid the countdown) for a mechanism that did not
                    // exist. Whenever the stream is down we fall through to the
                    // timer, because the periodic pull is what is converging the
                    // device at that moment.
                    const instantPullOn = queueDepth?.instant_pull?.connected === true

                    // Helper: format seconds as "1m 30s" or "45s"
                    const fmt = sec => {
                      const m = Math.floor(sec / 60), s = sec % 60
                      return m > 0 ? `${m}m ${String(s).padStart(2,'0')}s` : `${s}s`
                    }

                    // Pro + Instant Pull ON + no error → green badge
                    if (instantPullOn && !hasSyncError) {
                      return (
                        <div style={{
                          display: 'flex', justifyContent: 'space-between', alignItems: 'center',
                          borderTop: '1px solid var(--border)', paddingTop: '6px'
                        }}>
                          <span style={{ color: 'var(--text-secondary)' }}>Cloud pull</span>
                          <span style={{
                            fontWeight: '700', fontSize: '0.72rem',
                            color: 'var(--success, #22c55e)',
                            display: 'flex', alignItems: 'center', gap: 4
                          }}>
                            <span>⚡</span> Instant Pull active
                          </span>
                        </div>
                      )
                    }

                    // Not connected → the timer is what is actually converging
                    // this device, so show it and say why it is in charge.
                    const ip = queueDepth?.instant_pull || {}
                    const timerColor = nextPullIn === 0 ? 'var(--success, #22c55e)'
                      : nextPullIn !== null && nextPullIn <= 15 ? 'var(--warning, #f59e0b)'
                      : 'var(--text-muted)'
                    const timerLabel = nextPullIn === null ? '—'
                      : nextPullIn === 0 ? 'pulling…'
                      : fmt(nextPullIn)
                    const fallbackReason = hasSyncError ? '⚠ Fallback pull'
                      : ip.running ? 'Instant Pull connecting…'
                      : 'Next cloud pull'

                    return (
                      <div style={{
                        display: 'flex', justifyContent: 'space-between', alignItems: 'center',
                        borderTop: '1px solid var(--border)', paddingTop: '6px'
                      }}>
                        <span
                          style={{ color: hasSyncError ? 'var(--warning, #f59e0b)' : 'var(--text-secondary)' }}
                          title={ip.last_error ? `Instant Pull: ${ip.last_error}` : undefined}
                        >
                          {fallbackReason}
                        </span>
                        <span style={{
                          fontWeight: '600', fontSize: '0.72rem',
                          color: timerColor,
                          fontVariantNumeric: 'tabular-nums', letterSpacing: '0.01em'
                        }}>
                          {timerLabel}
                        </span>
                      </div>
                    )
                  })()}

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
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                    {/* ── Live activity strip ──────────────────────────────
                        One place that answers "is something happening right
                        now, and which way is it going". Push already emitted
                        sync.progress; pull had no feedback at all, so the
                        button just sat there for the ~2s round trip. */}
                    {(flushing || pulling || syncProgress) && (
                      <div style={{
                        padding: '6px 9px',
                        borderRadius: 'var(--radius-sm, 4px)',
                        background: pulling ? 'rgba(99,179,237,0.10)' : 'rgba(34,197,94,0.10)',
                        border: `1px solid ${pulling ? 'rgba(99,179,237,0.30)' : 'rgba(34,197,94,0.30)'}`,
                        fontSize: '0.72rem',
                        color: 'var(--text-secondary)'
                      }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                          <span className="sync-spinner-small" />
                          <strong style={{ color: pulling ? 'var(--info, #63b3ed)' : 'var(--success, #22c55e)' }}>
                            {pulling ? 'Pulling from cloud…' : 'Pushing to cloud…'}
                          </strong>
                          {syncProgress?.total > 0 && (
                            <span style={{ marginLeft: 'auto', fontVariantNumeric: 'tabular-nums' }}>
                              {syncProgress.done}/{syncProgress.total}
                            </span>
                          )}
                        </div>
                        {syncProgress?.total > 0 && (
                          <div style={{
                            marginTop: 5, height: 3, borderRadius: 2,
                            background: 'var(--bg-3)', overflow: 'hidden'
                          }}>
                            <div style={{
                              width: `${Math.min(100, Math.round((syncProgress.done / syncProgress.total) * 100))}%`,
                              height: '100%',
                              background: pulling ? 'var(--info, #63b3ed)' : 'var(--success, #22c55e)',
                              transition: 'width 0.3s ease'
                            }} />
                          </div>
                        )}
                        {syncProgress?.entities?.length > 0 && (
                          <div style={{ marginTop: 3, color: 'var(--text-muted)' }}>
                            {syncProgress.entities.slice(0, 3).join(', ')}
                          </div>
                        )}
                      </div>
                    )}

                    {/* ── Pending outbox summary ── */}
                    <div style={{
                      display: 'flex', justifyContent: 'space-between', alignItems: 'center',
                      padding: '5px 9px', borderRadius: 'var(--radius-sm, 4px)',
                      background: 'var(--bg-2)', border: '1px solid var(--border)',
                      fontSize: '0.72rem'
                    }}>
                      <span style={{ color: 'var(--text-secondary)' }}>Waiting in outbox</span>
                      <span style={{
                        fontWeight: 700,
                        fontVariantNumeric: 'tabular-nums',
                        color: (queueDepth.pending_count || 0) > 0
                          ? 'var(--warning, #f59e0b)'
                          : 'var(--success, #22c55e)'
                      }}>
                        {queueDepth.pending_count || 0}
                        {(queueDepth.pending_count || 0) === 0 && ' — all synced'}
                      </span>
                    </div>

                    {/* ── Push outbox now ── */}
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
                        // Push = GREEN (outgoing, matches the healthy sync-outbox
                        // colour), Pull = BLUE (incoming). Both used to be blue,
                        // which made the two actions visually indistinguishable.
                        backgroundColor: (flushing || checkingPlan) ? 'rgba(255,255,255,0.08)' : 'var(--success, #22c55e)',
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
                          {flushing ? 'Syncing Now...' : '↑ Push to Cloud'}
                        </>
                      )}
                    </button>

                    {/* ── Pull from cloud now ── */}
                    {!isSyncPaused && (
                      <button
                        id="sync-pull-now-btn"
                        onClick={(e) => { e.stopPropagation(); handlePullNow() }}
                        disabled={pulling || flushing}
                        style={{
                          width: '100%',
                          padding: '6px 12px',
                          backgroundColor: 'rgba(99, 179, 237, 0.1)',
                          color: pulling ? 'var(--text-muted)' : 'var(--info, #63b3ed)',
                          border: '1px solid rgba(99, 179, 237, 0.3)',
                          borderRadius: 'var(--radius-sm, 4px)',
                          cursor: (pulling || flushing) ? 'not-allowed' : 'pointer',
                          fontWeight: '600',
                          fontSize: '0.75rem',
                          transition: 'all 0.2s',
                          display: 'flex',
                          alignItems: 'center',
                          justifyContent: 'center',
                          gap: '6px',
                          opacity: (pulling || flushing) ? 0.6 : 1
                        }}
                        onMouseEnter={(e) => {
                          if (!pulling && !flushing) {
                            e.currentTarget.style.backgroundColor = 'rgba(99,179,237,0.18)'
                            e.currentTarget.style.borderColor = 'rgba(99,179,237,0.55)'
                          }
                        }}
                        onMouseLeave={(e) => {
                          e.currentTarget.style.backgroundColor = 'rgba(99,179,237,0.1)'
                          e.currentTarget.style.borderColor = 'rgba(99,179,237,0.3)'
                        }}
                        title={`Auto-pull runs every ${pullIntervalSec}s. Click to pull from cloud immediately.`}
                      >
                        <SyncIcon size={12} className={pulling ? 'sync-spinner-small' : ''} />
                        {pulling ? 'Pulling from Cloud…' : '↓ Pull from Cloud Now'}
                      </button>
                    )}
                  </div>
                )}

                {/* Why are the Push/Pull buttons missing? Explain it, don't just
                    render nothing. Both controls are gated on hybrid mode, so in
                    Local or Cloud-only mode the popover silently lost them and
                    looked like the buttons had been deleted. */}
                {effectiveMode !== 'hybrid' && (
                  <div style={{
                    padding: '8px 10px',
                    borderRadius: 'var(--radius-sm, 4px)',
                    background: 'var(--bg-2)',
                    border: '1px solid var(--border)',
                    fontSize: '0.72rem',
                    lineHeight: 1.45,
                    color: 'var(--text-muted)'
                  }}>
                    <strong style={{ color: 'var(--text-secondary)' }}>
                      Mode: {effectiveMode === 'cloud' ? 'Cloud only' : 'Local only'}
                    </strong>
                    <br />
                    Push / Pull controls and the outbox queue exist only in{' '}
                    <strong>Local + Cloud (Hybrid)</strong> mode. In{' '}
                    {effectiveMode === 'cloud' ? 'Cloud-only' : 'Local-only'} mode there is no
                    local outbox, so nothing is queued for sync. Switch modes in
                    Settings → Hosting to enable them.

                    {/* Device override vs account setting. `effectiveMode` follows
                        the device key because getApiBase() routes on it — so when
                        the account says hybrid but this browser is pinned to
                        'cloud', the honest fix is to drop the override, not to
                        pretend the mode is something the routing disagrees with. */}
                    {IS_LOCAL_APP
                      && hostingMode === 'hybrid'
                      && effectiveMode !== 'hybrid'
                      && (
                      <div style={{ marginTop: 8, paddingTop: 8, borderTop: '1px solid var(--border)' }}>
                        <div style={{ color: 'var(--warning, #f59e0b)', marginBottom: 6 }}>
                          This account is set to <strong>Local + Cloud</strong>, but this
                          device is pinned to <strong>{effectiveMode}</strong>.
                        </div>
                        <button
                          className="btn btn-secondary"
                          style={{ fontSize: '0.72rem', padding: '3px 9px' }}
                          onClick={(e) => {
                            e.stopPropagation()
                            try { localStorage.removeItem('bizassist_hosting_mode') } catch { /* storage unavailable */ }
                            window.location.reload()
                          }}
                        >
                          Use Local + Cloud on this device
                        </button>
                      </div>
                    )}
                  </div>
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

          {/* Nav — flat ordered list, regrouped by section label */}
          <nav className="sidebar-nav">
            {(() => {
              // Group back into sections while preserving custom order
              const groups = []
              orderedVisibleNav.forEach((item, flatIndex) => {
                const last = groups[groups.length - 1]
                if (last && last.section === item.section) {
                  last.items.push({ item, flatIndex })
                } else {
                  groups.push({ section: item.section, items: [{ item, flatIndex }] })
                }
              })
              return groups.map(({ section, items }) => {
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

                    {!isCollapsed && items.map(({ item: { to, icon, label, external }, flatIndex }) => {
                      const handleCtxMenu = (e) => {
                        e.preventDefault()
                        setSidebarCtxMenu({ x: e.clientX, y: e.clientY, to, label, flatIndex })
                      }
                      if (external) {
                        if (!getAiDashboardUrl()) return null
                        return (
                          <a
                            key={label}
                            href={getAiDashboardUrl()}
                            className="nav-link"
                            data-label={label}
                            onContextMenu={handleCtxMenu}
                            onClick={(e) => {
                              e.preventDefault()
                              setMobileMenuOpen(false)
                              if (aiGated) {
                                confirm({
                                  mode: 'alert',
                                  title: 'Pro plan feature',
                                  message: 'Dashboard BIZASSIST is part of the Pro plan. Contact your provider to upgrade.',
                                })
                                return
                              }
                              openAiDashboard()
                            }}
                          >
                            <span className="nav-icon">{icon}</span>
                            {/* Wrapped like the NavLink below. As a bare text
                                node this was the one label the collapsed rail
                                could not hide, so "Dashboard BIZASSIST" spilled
                                out of the 56px rail. */}
                            <span className="nav-label">{label}</span>
                            {aiGated && !sidebarCollapsed && (
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
                          onContextMenu={handleCtxMenu}
                          className={({ isActive }) =>
                            'nav-link' + (isActive ? ' active' : '')
                          }
                          // Read by the collapsed rail's hover tooltip. The
                          // label text itself is hidden when collapsed, so
                          // without this the rail is a row of unnamed icons.
                          data-label={label}
                        >
                          <span className="nav-icon">{icon}</span>
                          {/* Wrapped so the rail can hide the text without
                              hiding the icon. It was a bare text node. */}
                          <span className="nav-label">{label}</span>
                        </NavLink>
                      )
                    })}
                  </React.Fragment>
                )
              })
            })()}
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
                    onClick={async (e) => {
                      e.stopPropagation();
                      const ok = await confirm({
                        mode: 'discard',
                        title: 'Discard draft bill?',
                        message: 'Discard active draft billing session?',
                        confirmText: 'Discard',
                      })
                      if (ok) {
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
                    onClick={async (e) => {
                      e.stopPropagation();
                      const ok = await confirm({
                        mode: 'discard',
                        title: 'Discard live draft?',
                        message: 'Discard active live counter monitoring draft?',
                        confirmText: 'Discard',
                      })
                      if (ok) {
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

      {/* ── Sidebar right-click context menu — extracted to components/layout/SidebarContextMenu ── */}
      {sidebarCtxMenu && (
        <SidebarContextMenu
          menu={sidebarCtxMenu}
          quickActions={QUICK_ACTIONS[sidebarCtxMenu.to]?.(navigate) || []}
          flatCount={orderedVisibleNav.length}
          onMove={(dir) => {
            moveNavItem(sidebarCtxMenu.flatIndex, dir)
            setSidebarCtxMenu(prev => prev && ({ ...prev, flatIndex: prev.flatIndex + dir }))
          }}
          hasCustomOrder={!!navOrder}
          onResetOrder={() => {
            setNavOrder(null)
            try { localStorage.removeItem('sidebar_nav_order') } catch { /* ignore */ }
            setSidebarCtxMenu(null)
          }}
          onClose={() => setSidebarCtxMenu(null)}
        />
      )}

      {/* ── Mobile bottom bar (iOS-style tab bar) ──────────────────────────
          On a phone the drawer costs two taps to reach anything: open it, then
          pick. These are the five screens a counter actually lives in, one tap
          away, in the thumb zone. The drawer stays for everything else.

          Routes are taken from the SAME nav list the sidebar renders, so a
          renamed or removed route cannot leave a dead tab here — the "two
          copies of one thing" trap CLEANUP §6.1 records. */}
      {!isSalesPage && (
        <nav className="mobile-bottombar" aria-label="Primary">
          {BOTTOM_BAR_ROUTES.map(to => {
            const item = orderedVisibleNav.find(n => n.to === to)
            if (!item) return null          // hidden by plan/role — no dead tab
            const active = location.pathname === to ||
              (to !== '/' && location.pathname.startsWith(to))
            return (
              <NavLink
                key={to}
                to={to}
                className={'bb-item' + (active ? ' active' : '')}
                onClick={() => setMobileMenuOpen(false)}
              >
                <span className="bb-icon">{item.icon}</span>
                <span className="bb-label">{item.label}</span>
              </NavLink>
            )
          })}
        </nav>
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

      {/* Toast portal — extracted to components/layout/ToastContainer */}
      <ToastContainer
        toasts={toasts}
        onDismiss={(id) => setToasts(prev => prev.filter(t => t.id !== id))}
      />
      {sessionExpired && (
        <SessionExpiredModal
          onSignOut={() => {
            sessionStorage.removeItem('bizassist_session_start_time')
            logout()
            navigate('/login')
          }}
        />
      )}
    </div>
  )
}
