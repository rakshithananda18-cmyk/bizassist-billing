import React, { useEffect, useState, useCallback } from 'react'
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { AuthProvider, useAuth } from './contexts/AuthContext'
import { LockProvider } from './contexts/LockContext'
import LockScreen from './components/LockScreen'
import PageLoader from './components/PageLoader'
import Modal from './components/Modal'
import { syncManager } from './sync/syncManager'
import { API_BASE } from './config'
import { logger } from './utils/logger'
import { useRealtimeLeader } from './hooks/useRealtimeLeader'
import { IS_LOCAL_APP } from './config'

// Pages
import Login     from './pages/Login'
import Register  from './pages/Register'
import Home      from './pages/Home'
import Dashboard from './pages/Dashboard'
import Sales     from './pages/Sales'
import LiveView  from './pages/LiveView'
import Purchases from './pages/Purchases'
import Payments  from './pages/Payments'
import Stock     from './pages/Stock'
import Parties   from './pages/Parties'
import Reports   from './pages/Reports'
import Import    from './pages/Import'
import B2BNetwork from './pages/B2BNetwork'
import B2BOrders      from './pages/B2BOrders'
import Profile     from './pages/Profile'
import Settings    from './pages/Settings'
import POSLiveCounter from './pages/POSLiveCounter'
import InvoiceViewer  from './invoice/InvoiceViewer'
import PublicInvoiceViewer from './pages/PublicInvoiceViewer'
import Support from './pages/Support'


function ProtectedRoute({ children }) {
  const { user, loading } = useAuth()
  if (loading) return <PageLoader />
  return user ? children : <Navigate to="/login" replace />
}

function AppRoutes() {
  const { user } = useAuth()
  return (
    <Routes>
      <Route path="/login"    element={user ? <Navigate to="/" replace /> : <Login />} />
      <Route path="/register" element={user ? <Navigate to="/" replace /> : <Register />} />
      <Route path="/public/invoice/:uid" element={<PublicInvoiceViewer />} />

      <Route path="/"          element={<ProtectedRoute><Home      /></ProtectedRoute>} />
      <Route path="/dashboard" element={<ProtectedRoute><Dashboard /></ProtectedRoute>} />
      <Route path="/sales"     element={<ProtectedRoute><Sales key="sales" /></ProtectedRoute>} />
      <Route path="/live-view" element={<ProtectedRoute><LiveView /></ProtectedRoute>} />
      <Route path="/purchases" element={<ProtectedRoute><Purchases /></ProtectedRoute>} />
      <Route path="/payments"  element={<ProtectedRoute><Payments  /></ProtectedRoute>} />
      <Route path="/stock"    element={<ProtectedRoute><Stock     /></ProtectedRoute>} />
      <Route path="/parties"  element={<ProtectedRoute><Parties   /></ProtectedRoute>} />
      <Route path="/reports"  element={<ProtectedRoute><Reports   /></ProtectedRoute>} />
      <Route path="/import"   element={<ProtectedRoute><Import    /></ProtectedRoute>} />
      <Route path="/b2b-network" element={<ProtectedRoute><B2BNetwork /></ProtectedRoute>} />
      <Route path="/b2b-orders"      element={<ProtectedRoute><B2BOrders      /></ProtectedRoute>} />
      <Route path="/profile"     element={<ProtectedRoute><Profile     /></ProtectedRoute>} />
      <Route path="/settings"    element={<ProtectedRoute><Settings    /></ProtectedRoute>} />
      <Route path="/support"     element={<ProtectedRoute><Support     /></ProtectedRoute>} />
      <Route path="/pos-live-counter"    element={<ProtectedRoute><POSLiveCounter    /></ProtectedRoute>} />
      <Route path="/invoice/:invoiceNo/view" element={<ProtectedRoute><InvoiceViewer /></ProtectedRoute>} />
      <Route path="/staff"       element={<Navigate to="/settings?tab=staff" replace />} />


      {/* Catch-all */}
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}

// ── Sync Prompt Banner ──────────────────────────────────────────────────────
// Non-blocking slide-in banner that surfaces two actionable sync states:
//   OFFLINE_PENDING  — bills saved offline are waiting to push to cloud
//   MULTI_DEVICE     — same user logged in on another device/tab simultaneously
//
// Shown only in hybrid mode. Dismissed by syncing or "Remind Later".

const BANNER_STATES = {
  OFFLINE_PENDING: 'offline_pending',
  MULTI_DEVICE:    'multi_device',
  NONE:            null,
}

function SyncPromptBanner() {
  const { user, authFetch, settings } = useAuth()
  const [bannerState, setBannerState] = useState(BANNER_STATES.NONE)
  const [pendingCount, setPendingCount] = useState(0)
  const [syncing, setSyncing] = useState(false)
  const [dismissed, setDismissed] = useState(false)

  const hostingMode = settings?.general?.hosting_mode || localStorage.getItem('bizassist_hosting_mode') || 'local'
  const isHybrid = IS_LOCAL_APP && hostingMode === 'hybrid'

  // Check outbox on mount and after sync-flushed events
  const checkOutbox = useCallback(async () => {
    if (!user || !isHybrid || dismissed) return
    try {
      const count = await syncManager.pendingCount()
      setPendingCount(count)
      if (count > 0) setBannerState(BANNER_STATES.OFFLINE_PENDING)
      else setBannerState(BANNER_STATES.NONE)
    } catch { /* best-effort */ }
  }, [user, isHybrid, dismissed])

  useEffect(() => {
    if (!isHybrid || !user) return
    // Small delay so app finishes initialising before we check
    const t = setTimeout(checkOutbox, 3000)
    const onFlushed = () => checkOutbox()
    window.addEventListener('sync-flushed', onFlushed)
    return () => { clearTimeout(t); window.removeEventListener('sync-flushed', onFlushed) }
  }, [checkOutbox, isHybrid, user])

  // Detect same-user on another tab via BroadcastChannel
  useEffect(() => {
    if (!isHybrid || !user || typeof BroadcastChannel === 'undefined') return
    const ch = new BroadcastChannel('bizassist_session')
    ch.postMessage({ type: 'session_ping', userId: user.id })
    ch.onmessage = (e) => {
      if (e.data?.type === 'session_ping' && e.data?.userId === user.id) {
        setBannerState(prev => prev === BANNER_STATES.OFFLINE_PENDING ? prev : BANNER_STATES.MULTI_DEVICE)
      }
    }
    return () => ch.close()
  }, [isHybrid, user])

  const handleSyncNow = async () => {
    setSyncing(true)
    try {
      await syncManager.flushOutbox()
      window.dispatchEvent(new CustomEvent('sync-flushed'))
      setBannerState(BANNER_STATES.NONE)
    } catch { /* will retry */ }
    finally { setSyncing(false) }
  }

  const handleRemindLater = () => {
    setDismissed(true)
    setBannerState(BANNER_STATES.NONE)
    // Re-check after 10 minutes
    setTimeout(() => setDismissed(false), 10 * 60 * 1000)
  }

  if (!bannerState || !user) return null

  const isPending = bannerState === BANNER_STATES.OFFLINE_PENDING
  const color     = isPending ? '#f59e0b' : '#3b82f6'
  const bg        = isPending ? 'rgba(245,158,11,0.12)' : 'rgba(59,130,246,0.12)'
  const border    = isPending ? 'rgba(245,158,11,0.35)' : 'rgba(59,130,246,0.35)'

  return (
    <div style={{
      position: 'fixed', bottom: 20, left: '50%', transform: 'translateX(-50%)',
      zIndex: 9999, maxWidth: 480, width: 'calc(100% - 40px)',
      background: 'var(--card-bg, #1a1a2e)',
      border: `1px solid ${border}`,
      borderLeft: `4px solid ${color}`,
      borderRadius: 12, padding: '14px 18px',
      display: 'flex', alignItems: 'flex-start', gap: 14,
      boxShadow: '0 8px 32px rgba(0,0,0,0.4)',
      animation: 'slideUpBanner 0.3s ease',
    }}>
      <span style={{ fontSize: 22, marginTop: 1 }}>
        {isPending ? '⚡' : '📡'}
      </span>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontWeight: 600, fontSize: '0.9rem', color: color, marginBottom: 2 }}>
          {isPending
            ? `${pendingCount} bill${pendingCount !== 1 ? 's' : ''} saved offline — not yet synced`
            : 'Same account open on another device'}
        </div>
        <div style={{ fontSize: '0.8rem', color: 'var(--text-muted, #888)', lineHeight: 1.4 }}>
          {isPending
            ? 'Sync now to prevent data loss and keep cloud up to date.'
            : 'Bills may take longer to sync. Consider closing the other session.'}
        </div>
        <div style={{ display: 'flex', gap: 8, marginTop: 10 }}>
          <button
            onClick={handleSyncNow}
            disabled={syncing}
            style={{
              padding: '6px 16px', borderRadius: 8, border: 'none',
              background: color, color: '#fff', fontWeight: 600,
              fontSize: '0.82rem', cursor: syncing ? 'not-allowed' : 'pointer',
              opacity: syncing ? 0.7 : 1, transition: 'opacity 0.2s',
            }}
          >
            {syncing ? '⏳ Syncing…' : '↑ Sync Now'}
          </button>
          <button
            onClick={handleRemindLater}
            style={{
              padding: '6px 14px', borderRadius: 8,
              border: `1px solid ${border}`, background: 'transparent',
              color: 'var(--text-muted, #888)', fontSize: '0.82rem',
              cursor: 'pointer',
            }}
          >
            Remind Later
          </button>
        </div>
      </div>
      <button
        onClick={handleRemindLater}
        style={{ background: 'none', border: 'none', color: 'var(--text-muted, #888)',
          cursor: 'pointer', fontSize: 18, padding: '0 0 0 4px', lineHeight: 1 }}
        aria-label="Dismiss"
      >×</button>
    </div>
  )
}


function RealtimeSyncListener() {
  const { user, token, settings, fetchSettings } = useAuth()
  const [modalOpen, setModalOpen] = useState(false)
  const [modalReason, setModalReason] = useState('')

  useRealtimeLeader(token, settings, user)

  useEffect(() => {
    const handleAutoDisabled = (e) => {
      setModalReason(e.detail?.reason || 'Unknown connection error')
      setModalOpen(true)
      fetchSettings()
    }

    window.addEventListener('realtime-sync-auto-disabled', handleAutoDisabled)

    return () => {
      window.removeEventListener('realtime-sync-auto-disabled', handleAutoDisabled)
    }
  }, [fetchSettings])

  return (
    <Modal
      open={modalOpen}
      title="⚠️ Real-Time Sync Paused"
      onClose={() => setModalOpen(false)}
      footer={
        <button 
          className="btn btn-primary" 
          onClick={() => setModalOpen(false)}
          style={{ width: '100%' }}
        >
          Acknowledge
        </button>
      }
    >
      <div style={{ display: 'flex', flexDirection: 'column', gap: 12, padding: '4px 0' }}>
        <p style={{ margin: 0, fontSize: '0.9rem', lineHeight: '1.4', color: 'var(--text-primary)' }}>
          Real-time sync was <strong>automatically paused</strong> after repeated connection failures.
        </p>
        
        <div style={{ 
          background: 'rgba(239, 68, 68, 0.1)', 
          border: '1px solid rgba(239, 68, 68, 0.2)', 
          borderRadius: 8, 
          padding: 12,
          fontSize: '0.82rem',
          color: 'var(--danger, #ef4444)',
          fontFamily: 'monospace',
          whiteSpace: 'pre-wrap',
          wordBreak: 'break-word'
        }}>
          Reason: {modalReason}
        </div>

        <p style={{ margin: 0, fontSize: '0.8rem', lineHeight: '1.4', color: 'var(--text-muted)' }}>
          This is a temporary, session-only pause to avoid hammering the server — your setting was <strong>not</strong> changed. It resumes automatically when you refresh the page or your connection stabilises, or use <strong>Reconnect</strong> in the sync status menu.
        </p>
      </div>
    </Modal>
  )
}

export default function App() {
  useEffect(() => {
    const unsubscribe = syncManager.start()
    return unsubscribe
  }, [])

  return (
    <BrowserRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
      <AuthProvider>
        <LockProvider>
          {/* Lock screen intercepts entire UI when session is locked */}
          <LockScreen />
          <RealtimeSyncListener />
          {/* Slide-in banner: offline bills pending sync + same-user multi-device warning */}
          <SyncPromptBanner />
          <AppRoutes />
        </LockProvider>
      </AuthProvider>
    </BrowserRouter>
  )
}

