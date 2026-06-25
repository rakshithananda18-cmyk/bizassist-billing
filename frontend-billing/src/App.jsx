import React, { useEffect, useState } from 'react'
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
      title="⚠️ Real-Time Sync Suspended"
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
          Real-time sync has been <strong>automatically disabled</strong> due to repeated connection failures.
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
          To prevent excessive server load, sync has been turned off. You can re-enable it under <strong>Settings &gt; General</strong> once your connection is stable.
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

