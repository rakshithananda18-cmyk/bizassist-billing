import { useEffect } from 'react'
import { Navigate, useLocation, useNavigate } from 'react-router-dom'
import { useAuth } from '../contexts/AuthContext'

// A return from Field Team names a business, never grants access. Do not show
// an already-open Billing account's records when it belongs to somebody else.
export default function BillingWorkspaceGuard({ children }) {
  const { user, loading, logout } = useAuth()
  const location = useLocation()
  const navigate = useNavigate()
  const params = new URLSearchParams(location.search)
  const candidate = params.get('field_business')
  const expected = /^[A-Za-z0-9_-]{1,100}$/.test(candidate || '') ? candidate : null
  const matches = expected && user?.public_id === expected
  useEffect(() => {
    if (!matches) return
    const next = new URLSearchParams(location.search)
    next.delete('field_business')
    navigate({ pathname: location.pathname, search: next.toString(), hash: location.hash }, { replace: true })
  }, [matches, location.pathname, location.search, location.hash, navigate])
  if (!expected || loading || matches) return children
  if (!user) {
    return location.pathname === '/login' ? children : <Navigate to={`/login?${params}`} replace />
  }
  return (
    <main className="login-container">
      <section className="card" style={{ maxWidth: 480, padding: 28 }} role="alert">
        <h1 style={{ fontSize: '1.3rem' }}>Choose the same business</h1>
        <p style={{ marginTop: 12 }}>Field Team is open for <strong>{expected}</strong>. Billing is signed in to <strong>{user.business_name || user.public_id}</strong> ({user.public_id}).</p>
        <p style={{ margin: '12px 0 20px', color: 'var(--text-secondary)' }}>Sign in with the matching Billing account to continue.</p>
        <button type="button" className="btn btn-primary" onClick={() => {
          logout()
          navigate(`/login?field_business=${encodeURIComponent(expected)}`, { replace: true })
        }}>Switch Billing account</button>
      </section>
    </main>
  )
}
