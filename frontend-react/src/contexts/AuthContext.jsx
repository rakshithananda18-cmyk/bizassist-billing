import { createContext, useContext, useState, useEffect } from 'react'
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
  async function login(username, password) {
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
  }

  function logout() {
    localStorage.removeItem('user')
    localStorage.removeItem('active_session_id')
    localStorage.removeItem('biz_name')
    setUser(null)
  }

  // ── Admin login ───────────────────────────────────────────────
  async function adminLogin(username, password) {
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
  }

  function adminLogout() {
    localStorage.removeItem('admin_user')
    localStorage.removeItem('biz_name')
    setAdminUser(null)
  }

  // ── Authenticated fetch (auto-attaches Bearer token & intercepts 401s) ─────────
  async function authFetch(url, options = {}) {
    const token = user?.token || adminUser?.token
    const res = await fetch(url, {
      ...options,
      headers: {
        ...(options.headers || {}),
        ...(token ? { Authorization: `Bearer ${token}` } : {})
      }
    })
    if (res.status === 401) {
      if (adminUser) {
        adminLogout()
      } else {
        logout()
      }
    }
    return res
  }

  return (
    <AuthContext.Provider value={{
      user, adminUser, loading,
      login, logout,
      adminLogin, adminLogout,
      authFetch
    }}>
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth() {
  return useContext(AuthContext)
}
