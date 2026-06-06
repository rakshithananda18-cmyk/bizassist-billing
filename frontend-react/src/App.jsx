import { useEffect } from 'react'
import { BrowserRouter, Routes, Route, Navigate, useLocation } from 'react-router-dom'
import { AuthProvider } from './contexts/AuthContext'
import { ProtectedRoute, AdminProtectedRoute } from './components/ProtectedRoute'

import AppLayout   from './layouts/AppLayout'
import AdminLayout from './layouts/AdminLayout'

import Login          from './pages/Login'
import Dashboard      from './pages/Dashboard'
import Invoices       from './pages/Invoices'
import Payments       from './pages/Payments'
import Clients        from './pages/Clients'
import Database       from './pages/Database'
import Upload         from './pages/Upload'
import Alerts         from './pages/Alerts'

import NotFound       from './pages/NotFound'

import AdminLogin      from './pages/admin/AdminLogin'
import AdminDashboard  from './pages/admin/AdminDashboard'
import AdminBusinesses from './pages/admin/AdminBusinesses'
import AdminUsage      from './pages/admin/AdminUsage'
import AdminCache      from './pages/admin/AdminCache'

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
          <Route path="/login"       element={<Login />} />
          <Route path="/admin/login" element={<AdminLogin />} />

          {/* Enterprise app */}
          <Route element={<ProtectedRoute><AppLayout /></ProtectedRoute>}>
            <Route index                element={<Navigate to="/chat" replace />} />
            <Route path="/dashboard"    element={<Dashboard />} />
            <Route path="/invoices"     element={<Invoices />} />
            <Route path="/payments"     element={<Payments />} />
            <Route path="/clients"      element={<Clients />} />
            <Route path="/chat"         element={<div />} /> {/* Rendered inside AppLayout */}
            <Route path="/upload"       element={<Upload />} />
            <Route path="/database"     element={<Database />} />
            <Route path="/alerts"       element={<Alerts />} />
          </Route>

          {/* Admin portal */}
          <Route element={<AdminProtectedRoute><AdminLayout /></AdminProtectedRoute>}>
            <Route path="/admin"              element={<Navigate to="/admin/dashboard" replace />} />
            <Route path="/admin/dashboard"    element={<AdminDashboard />} />
            <Route path="/admin/businesses"   element={<AdminBusinesses />} />
            <Route path="/admin/usage"        element={<AdminUsage />} />
            <Route path="/admin/cache"        element={<AdminCache />} />
          </Route>

          <Route path="*" element={<NotFound />} />

        </Routes>
      </BrowserRouter>
      </DialogProvider>
    </AuthProvider>
  )
}
