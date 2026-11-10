import { useEffect } from 'react'
import { Navigate, useLocation } from 'react-router-dom'
import { useAuth } from '../contexts/AuthContext'
import PageLoader from './PageLoader'

// Protects enterprise user routes
export function ProtectedRoute({ children }) {
  const { user, loading } = useAuth()
  if (loading) return <PageLoader />
  if (!user)   return <Navigate to="/login" replace />
  return children
}

// Protects admin routes
export function AdminProtectedRoute({ children }) {
  const { adminUser, loading } = useAuth()
  const location = useLocation()
  useEffect(() => {
    if (!loading && !adminUser && location.pathname.startsWith('/admin/') && location.pathname !== '/admin/login') {
      sessionStorage.setItem('admin_return_path', location.pathname + location.search + location.hash)
    }
  }, [adminUser, loading, location])
  if (loading)    return <PageLoader />
  if (!adminUser) return <Navigate to="/admin/login" replace />
  return children
}
