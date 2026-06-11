import { createContext, useContext, useState, useEffect, useCallback, useMemo } from 'react'
import { API_BASE } from '../config'

const AuthContext = createContext(null)

export function AuthProvider({ children }) {
  const [user,       setUser]       = useState(null)   // enterprise user
  const [adminUser,  setAdminUser]  = useState(null)   // admin user
  const [loading,    setLoading]    = useState(true)

  // Restore sessions from localStorage on mount
  useEffect(() => {
    try {
      const u = localStorage.getItem('user')
      const a = localStorage.getItem('admin_user')
      if (u) setUser(JSON.parse(u))
      if (a) setAdminUser(JSON.parse(a))
    } catch {}
    setLoading(false)
  }, [])

  // ── Enterprise login ──────────────────────────────────────────
  const login = useCallback(async (username, password) => {
    const res = await fetch(`${API_BASE}/login`, {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify({ username, password })
    })
    if (!res.ok) {
      const data = await res.json()
      throw new Error(data.detail || 'Login failed')
    }
    const data = await res.json()
    localStorage.setItem('user', JSON.stringify(data))
    setUser(data)
    return data
  }, [])

  // ── Enterprise signup ─────────────────────────────────────────
  const signup = useCallback(async (username, password, businessName) => {
    const res = await fetch(`${API_BASE}/signup`, {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify({ username, password, business_name: businessName })
    })
    if (!res.ok) {
      const data = await res.json().catch(() => ({}))
      throw new Error(data.detail || 'Registration failed')
    }
    const data = await res.json()
    localStorage.setItem('user', JSON.stringify(data))
    if (data.business_name) localStorage.setItem('biz_name', data.business_name)
    setUser(data)
    return data
  }, [])

  const logout = useCallback(() => {
    localStorage.removeItem('user')
    localStorage.removeItem('active_session_id')
    localStorage.removeItem('biz_name')
    setUser(null)
  }, [])

  // ── Admin login ───────────────────────────────────────────────
  const adminLogin = useCallback(async (username, password) => {
    const res = await fetch(`${API_BASE}/login`, {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify({ username, password })
    })
    if (!res.ok) {
      const data = await res.json()
      throw new Error(data.detail || 'Login failed')
    }
    const data = await res.json()
    if (data.role !== 'admin') throw new Error('Access denied. Admin role required.')
    localStorage.setItem('admin_user', JSON.stringify(data))
    setAdminUser(data)
    return data
  }, [])

  const adminLogout = useCallback(() => {
    localStorage.removeItem('admin_user')
    localStorage.removeItem('biz_name')
    setAdminUser(null)
  }, [])

  // ── Authenticated fetch (auto-attaches Bearer token & intercepts 401s) ─────────
  // Memoized so it's stable across renders — otherwise every consumer's
  // useCallbacks (loadSessions, selectSession, …) change identity each render,
  // re-firing effects that re-fetch chat history and clobber the live messages.
  const authFetch = useCallback(async (url, options = {}) => {
    // If fetching an admin endpoint (contains /admin/), prioritize the adminUser token.
    // Otherwise, prioritize the enterprise user token.
    const isAdminRequest = url.includes('/admin/')
    const token = isAdminRequest
      ? (adminUser?.token || user?.token)
      : (user?.token || adminUser?.token)

    const res = await fetch(url, {
      ...options,
      headers: {
        ...(options.headers || {}),
        ...(token ? { Authorization: `Bearer ${token}` } : {})
      }
    })
    if (res.status === 401) {
      if (isAdminRequest) {
        adminLogout()
      } else {
        logout()
      }
    }
    return res
  }, [user, adminUser, logout, adminLogout])

  const value = useMemo(() => ({
    user, adminUser, loading,
    login, signup, logout,
    adminLogin, adminLogout,
    authFetch
  }), [user, adminUser, loading, login, signup, logout, adminLogin, adminLogout, authFetch])

  return (
    <AuthContext.Provider value={value}>
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth() {
  return useContext(AuthContext)
}
