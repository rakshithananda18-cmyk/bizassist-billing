import { createContext, useContext, useState, useEffect, useCallback, useMemo } from 'react'
import { API_BASE } from '../config'

const AuthContext = createContext(null)

export function AuthProvider({ children }) {
  const [user,       setUser]       = useState(null)   // enterprise user
  const [adminUser,  setAdminUser]  = useState(null)   // admin user
  const [loading,    setLoading]    = useState(true)

  // Restore sessions from localStorage or SSO on mount
  useEffect(() => {
    const initAuth = async () => {
      const params = new URLSearchParams(window.location.search)
      const ssoTicket = params.get('sso')
      const isLogout = params.get('logout') === 'true'
      let ssoSuccess = false
      
      if (isLogout) {
        // Intercept silent logout ping from billing app
        localStorage.removeItem('user')
        localStorage.removeItem('active_session_id')
        localStorage.removeItem('biz_name')
        setUser(null)
        
        const url = new URL(window.location)
        url.searchParams.delete('logout')
        window.history.replaceState({}, document.title, url)
        setLoading(false)
        return
      }
      
      if (ssoTicket) {
        // Clean up the URL immediately (synchronously) so React StrictMode's 
        // second mount doesn't try to double-redeem the single-use ticket.
        const url = new URL(window.location)
        url.searchParams.delete('sso')
        window.history.replaceState({}, document.title, url)

        try {
          const res = await fetch(`${API_BASE}/redeem-ticket`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ ticket: ssoTicket })
          })
          if (res.ok) {
            const data = await res.json()
            localStorage.setItem('user', JSON.stringify(data))
            if (data.business_name) localStorage.setItem('biz_name', data.business_name)
            setUser(data)
            ssoSuccess = true
          } else {
            console.warn('[SSO] Ticket redemption rejected by server')
          }
        } catch (err) {
          console.warn('[SSO] Ticket redemption failed:', err)
        }
      }
      
      // If no SSO was handled or it failed, fall back to localStorage
      if (!ssoSuccess) {
        try {
          const u = localStorage.getItem('user')
          const a = localStorage.getItem('admin_user')
          if (u) setUser(JSON.parse(u))
          if (a) setAdminUser(JSON.parse(a))
        } catch {}
      }
      setLoading(false)
    }
    
    initAuth()
  }, [])

  // Listen for SSO tickets sent via postMessage from the billing app.
  // This fires when the tab is already open (React is mounted) and the user
  // clicks "Open AI Dashboard" again after having logged out — the mount
  // useEffect won't re-run, so the billing app uses postMessage instead.
  useEffect(() => {
    async function handleMessage(event) {
      // Only accept messages from our known AI dashboard origins
      const knownOrigins = [
        window.location.origin,
        // Allow the billing app's origin dynamically — we trust same-host ports
        `http://${window.location.hostname}:5174`,
        `http://${window.location.hostname}:8450`,
      ]
      if (!knownOrigins.includes(event.origin) && !event.origin.startsWith('http://localhost')) {
        return
      }
      if (!event.data || event.data.type !== 'SSO_TICKET') return

      const ticket = event.data.ticket
      if (!ticket) return

      try {
        const res = await fetch(`${API_BASE}/redeem-ticket`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ ticket })
        })
        if (res.ok) {
          const data = await res.json()
          localStorage.setItem('user', JSON.stringify(data))
          if (data.business_name) localStorage.setItem('biz_name', data.business_name)
          setUser(data)
        } else {
          console.warn('[SSO] postMessage ticket redemption rejected by server')
        }
      } catch (err) {
        console.warn('[SSO] postMessage ticket redemption failed:', err)
      }
    }

    window.addEventListener('message', handleMessage)
    return () => window.removeEventListener('message', handleMessage)
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
