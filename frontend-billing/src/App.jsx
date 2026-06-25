import React, { useEffect, useState } from 'react'
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { AuthProvider, useAuth } from './contexts/AuthContext'
import { LockProvider } from './contexts/LockContext'
import LockScreen from './components/LockScreen'
import PageLoader from './components/PageLoader'
import { syncManager } from './sync/syncManager'
import { API_BASE } from './config'
import { logger } from './utils/logger'

// Pages
import Login     from './pages/Login'
import Register  from './pages/Register'
import Home      from './pages/Home'
import Dashboard from './pages/Dashboard'
import Sales     from './pages/Sales'
import Purchases from './pages/Purchases'
import Payments  from './pages/Payments'
import Stock     from './pages/Stock'
import Parties   from './pages/Parties'
import Reports   from './pages/Reports'
import Import    from './pages/Import'
import Connections from './pages/Connections'
import Orders      from './pages/Orders'
import Profile     from './pages/Profile'
import Settings    from './pages/Settings'


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

      <Route path="/"          element={<ProtectedRoute><Home      /></ProtectedRoute>} />
      <Route path="/dashboard" element={<ProtectedRoute><Dashboard /></ProtectedRoute>} />
      <Route path="/sales"     element={<ProtectedRoute><Sales     /></ProtectedRoute>} />
      <Route path="/purchases" element={<ProtectedRoute><Purchases /></ProtectedRoute>} />
      <Route path="/payments"  element={<ProtectedRoute><Payments  /></ProtectedRoute>} />
      <Route path="/stock"    element={<ProtectedRoute><Stock     /></ProtectedRoute>} />
      <Route path="/parties"  element={<ProtectedRoute><Parties   /></ProtectedRoute>} />
      <Route path="/reports"  element={<ProtectedRoute><Reports   /></ProtectedRoute>} />
      <Route path="/import"   element={<ProtectedRoute><Import    /></ProtectedRoute>} />
      <Route path="/connections" element={<ProtectedRoute><Connections /></ProtectedRoute>} />
      <Route path="/orders"      element={<ProtectedRoute><Orders      /></ProtectedRoute>} />
      <Route path="/profile"     element={<ProtectedRoute><Profile     /></ProtectedRoute>} />
      <Route path="/settings"    element={<ProtectedRoute><Settings    /></ProtectedRoute>} />
      <Route path="/staff"       element={<Navigate to="/settings?tab=lock" replace />} />


      {/* Catch-all */}
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}

function RealtimeSyncListener() {
  const { user, token, settings } = useAuth()
  const [reconnectTrigger, setReconnectTrigger] = useState(0)

  useEffect(() => {
    if (!token || !user) {
      const detail = { status: 'disconnected', error: null, lastSyncTime: null, lastEntity: null, isOnline: navigator.onLine }
      window.__syncStatus = detail
      window.dispatchEvent(new CustomEvent('sync-status-change', { detail }))
      return
    }

    const hostingMode = settings?.general?.hosting_mode || 'local'
    if (hostingMode === 'local') {
      logger.info('[REALTIME] Hosting mode is Local. Real-time stream disabled.')
      const detail = { status: 'disconnected', error: null, lastSyncTime: null, lastEntity: null, isOnline: navigator.onLine }
      window.__syncStatus = detail
      window.dispatchEvent(new CustomEvent('sync-status-change', { detail }))
      return
    }

    let lastSyncTime = localStorage.getItem(`sync_last_time_${user.id}`) || null
    let lastEntity = localStorage.getItem(`sync_last_entity_${user.id}`) || null
    let connectionError = null

    const emitStatus = (status, errOverride = null) => {
      const detail = {
        status,
        error: errOverride || connectionError,
        lastSyncTime,
        lastEntity,
        isOnline: navigator.onLine
      }
      window.__syncStatus = detail
      window.dispatchEvent(new CustomEvent('sync-status-change', { detail }))
    }

    // Initial status check
    const initialStatus = navigator.onLine ? 'connecting' : 'error'
    const initialError = navigator.onLine ? null : 'No internet connection. Client is offline.'
    emitStatus(initialStatus, initialError)

    if (!navigator.onLine) {
      logger.warn('[REALTIME] Offline on mount, deferring EventSource connection.')
      return
    }

    logger.info('[REALTIME] Connecting to SSE stream in mode:', hostingMode, 'trigger:', reconnectTrigger)
    window.dispatchEvent(new CustomEvent('show_toast', {
      detail: { type: 'info', msg: `Connecting to cloud sync stream (${hostingMode} mode)…` }
    }))
    const url = `${API_BASE}/realtime/events?token=${encodeURIComponent(token)}`
    
    let es = null
    try {
      es = new EventSource(url)

      es.onopen = () => {
        logger.info('[REALTIME] SSE connection established.')
        connectionError = null
        emitStatus('connected')
        window.dispatchEvent(new CustomEvent('show_toast', {
          detail: { type: 'success', msg: 'Cloud real-time sync connected.' }
        }))
      }

      es.onmessage = async (e) => {
        try {
          const data = JSON.parse(e.data)
          logger.debug('[REALTIME] Received SSE event:', data)
          
          lastSyncTime = new Date().toISOString()
          lastEntity = data.entity
          localStorage.setItem(`sync_last_time_${user.id}`, lastSyncTime)
          localStorage.setItem(`sync_last_entity_${user.id}`, lastEntity)
          connectionError = null
          emitStatus('connected')

          // Dispatch window level event
          window.dispatchEvent(new CustomEvent('sync-event', { detail: data }))
          window.dispatchEvent(new CustomEvent('show_toast', {
            detail: { type: 'info', msg: `Syncing remote ${data.entity} updates…` }
          }))

          // Trigger background outbox cursor pull to keep cache fresh
          if (['invoice', 'payment', 'purchase', 'product', 'party', 'order', 'godown'].includes(data.entity)) {
            logger.info('[REALTIME] Auto pulling deltas for entity:', data.entity)
            try {
              await syncManager.pull()
            } catch (err) {
              logger.error('[REALTIME] Auto pull failed:', err)
            }
          }
        } catch (err) {
          logger.error('[REALTIME] SSE parse error:', err)
        }
      }

      es.onerror = (err) => {
        logger.error('[REALTIME] SSE error:', err)
        connectionError = 'Sync stream interrupted. Reconnecting…'
        emitStatus('error')
      }
    } catch (err) {
      logger.error('[REALTIME] EventSource instantiation failed:', err)
      connectionError = err.message || 'Failed to initialize sync client.'
      emitStatus('error')
    }

    const handleOnline = () => {
      logger.info('[REALTIME] Network online detected.')
      connectionError = null
      emitStatus('connecting')
      setReconnectTrigger(prev => prev + 1)
    }

    const handleOffline = () => {
      logger.warn('[REALTIME] Network offline detected.')
      connectionError = 'No internet connection. Client is offline.'
      emitStatus('error')
      window.dispatchEvent(new CustomEvent('show_toast', {
        detail: { type: 'warning', msg: 'Network connection lost. Sync suspended.' }
      }))
    }

    const handleReconnectRequest = () => {
      logger.info('[REALTIME] Manual reconnect requested.')
      setReconnectTrigger(prev => prev + 1)
    }

    const handleStatusRequest = () => {
      logger.info('[REALTIME] Status request received, re-emitting.')
      const currentStatus = es && es.readyState === EventSource.OPEN ? 'connected' : (navigator.onLine ? 'connecting' : 'error')
      emitStatus(currentStatus)
    }

    window.addEventListener('online', handleOnline)
    window.addEventListener('offline', handleOffline)
    window.addEventListener('sync-reconnect-request', handleReconnectRequest)
    window.addEventListener('sync-status-request', handleStatusRequest)

    return () => {
      logger.info('[REALTIME] Cleaning up SSE connection.')
      if (es) {
        es.close()
      }
      window.removeEventListener('online', handleOnline)
      window.removeEventListener('offline', handleOffline)
      window.removeEventListener('sync-reconnect-request', handleReconnectRequest)
      window.removeEventListener('sync-status-request', handleStatusRequest)
    }
  }, [user, token, settings, reconnectTrigger])

  return null
}

export default function App() {
  useEffect(() => {
    const unsubscribe = syncManager.start()
    return unsubscribe
  }, [])

  return (
    <BrowserRouter>
      <AuthProvider>
        <LockProvider>
          {/* Lock screen intercepts entire UI when session is locked */}
          <LockScreen />
          <RealtimeSyncListener />
          <AppRoutes />
        </LockProvider>
      </AuthProvider>
    </BrowserRouter>
  )
}

