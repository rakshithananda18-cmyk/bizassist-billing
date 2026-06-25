import React, { useEffect } from 'react'
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

  useEffect(() => {
    if (!token || !user) return

    const hostingMode = settings?.general?.hosting_mode || 'local'
    if (hostingMode === 'local') {
      logger.info('[REALTIME] Hosting mode is Local. Real-time stream disabled.')
      return
    }

    logger.info('[REALTIME] Connecting to SSE stream in mode:', hostingMode)
    const url = `${API_BASE}/realtime/events?token=${encodeURIComponent(token)}`
    const es = new EventSource(url)

    es.onopen = () => {
      logger.info('[REALTIME] SSE connection established.')
    }

    es.onmessage = async (e) => {
      try {
        const data = JSON.parse(e.data)
        logger.debug('[REALTIME] Received SSE event:', data)
        
        // Dispatch window level event
        window.dispatchEvent(new CustomEvent('sync-event', { detail: data }))

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
    }

    return () => {
      logger.info('[REALTIME] Disconnecting SSE stream.')
      es.close()
    }
  }, [user, token, settings])

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

