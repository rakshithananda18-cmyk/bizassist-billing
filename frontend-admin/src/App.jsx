import { useEffect } from 'react'
import { BrowserRouter, Routes, Route, Navigate, useLocation } from 'react-router-dom'
import { AuthProvider } from './contexts/AuthContext'
import { AdminProtectedRoute } from './components/ProtectedRoute'

import AdminLayout from './layouts/AdminLayout'

import AdminLogin      from './pages/admin/AdminLogin'
import AdminDashboard  from './pages/admin/AdminDashboard'
import AdminBusinesses from './pages/admin/AdminBusinesses'
import AdminUsage      from './pages/admin/AdminUsage'
import AdminCache      from './pages/admin/AdminCache'
import AdminTelemetry  from './pages/admin/AdminTelemetry'

import { DialogProvider } from './contexts/DialogContext'

function ScrollToTop() {
  const { pathname } = useLocation()
  useEffect(() => {
    window.scrollTo(0, 0)
  }, [pathname])
  return null
}

export default function App() {
  return (
    <AuthProvider>
      <DialogProvider>
        <BrowserRouter>
        <ScrollToTop />
        <Routes>

          {/* Public */}
          <Route path="/admin/login" element={<AdminLogin />} />
          <Route path="/login" element={<Navigate to="/admin/login" replace />} />
          <Route path="/" element={<Navigate to="/admin/dashboard" replace />} />

          {/* Admin portal */}
          <Route element={<AdminProtectedRoute><AdminLayout /></AdminProtectedRoute>}>
            <Route path="/admin"              element={<Navigate to="/admin/dashboard" replace />} />
            <Route path="/admin/dashboard"    element={<AdminDashboard />} />
            <Route path="/admin/businesses"   element={<AdminBusinesses />} />
            <Route path="/admin/usage"        element={<AdminUsage />} />
            <Route path="/admin/cache"        element={<AdminCache />} />
            <Route path="/admin/telemetry"    element={<AdminTelemetry />} />
          </Route>

          <Route path="*" element={<Navigate to="/admin/dashboard" replace />} />

        </Routes>
      </BrowserRouter>
      </DialogProvider>
    </AuthProvider>
  )
}
