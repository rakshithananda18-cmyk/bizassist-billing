import { Navigate } from 'react-router-dom'
import { useAuth } from '../contexts/AuthContext'

// Protects enterprise user routes
export function ProtectedRoute({ children }) {
  const { user, loading } = useAuth()
  if (loading) return <div className="page-loading">Loading...</div>
  if (!user)   return <Navigate to="/login" replace />
  return children
}

// Protects admin routes
export function AdminProtectedRoute({ children }) {
  const { adminUser, loading } = useAuth()
  if (loading)    return <div className="page-loading">Loading...</div>
  if (!adminUser) return <Navigate to="/admin/login" replace />
  return children
}
