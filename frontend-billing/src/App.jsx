import React from 'react'
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { AuthProvider, useAuth } from './contexts/AuthContext'
import PageLoader from './components/PageLoader'

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
import Staff       from './pages/Staff'

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
      <Route path="/staff"       element={<ProtectedRoute><Staff       /></ProtectedRoute>} />


      {/* Catch-all */}
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}

export default function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <AppRoutes />
      </AuthProvider>
    </BrowserRouter>
  )
}
