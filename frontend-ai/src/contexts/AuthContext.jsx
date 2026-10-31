import { Fragment, createContext, useContext, useState, useRef, useEffect, useCallback, useMemo } from 'react'
import { API_BASE } from '../config'
import { logger, setBizId } from '../utils/logger'
import { trustedHandoff } from '../utils/handoff'

const AuthContext = createContext(null)

export function AuthProvider({ children }) {
  const [user,       setUser]       = useState(null)   // enterprise user
  const [adminUser,  setAdminUser]  = useState(null)   // admin user
  const [loading,    setLoading]    = useState(true)
  const generation = useRef(0)
  const clearSession = useCallback(() => {
    generation.current++
    localStorage.removeItem('user')
    localStorage.removeItem('active_session_id')
    localStorage.removeItem('biz_name')
    setUser(null)
  }, [])

  // Keep the [BizId=…] logging context in sync with the signed-in business.
  useEffect(() => { setBizId(user?.public_id || null) }, [user])

  // Restore sessions from localStorage or SSO on mount
  useEffect(() => {
    const initAuth = async () => {
      const requestGeneration = generation.current
      const params = new URLSearchParams(window.location.search)
      const ssoTicket = params.get('sso')
      const isLogout = params.get('logout') === 'true'
      let ssoSuccess = false

      if (isLogout) {
        // Intercept silent logout ping from billing app
        clearSession()

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
            if (requestGeneration !== generation.current) return
            localStorage.setItem('user', JSON.stringify(data))
            if (data.business_name) localStorage.setItem('biz_name', data.business_name)
            setUser(data)
            ssoSuccess = true
          } else {
            logger.warn('[SSO] Ticket redemption rejected by server')
          }
        } catch (err) {
          logger.warn('[SSO] Ticket redemption failed:', err)
        }
      }

      // If no SSO was handled or it failed, fall back to localStorage
      if (!ssoSuccess) {
        if (requestGeneration !== generation.current) return
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
  }, [clearSession])

  // Listen for SSO tickets sent via postMessage from the billing app.
  // WEB-05: Listen for cross-window logout via storage event and BroadcastChannel
  useEffect(() => {
    function handleStorage(e) {
      if (e.key === 'user') {
        generation.current++
        localStorage.removeItem('active_session_id')
        if (!e.newValue) { localStorage.removeItem('biz_name'); setUser(null) }
        else { try { setUser(JSON.parse(e.newValue)) } catch { clearSession() } }
      }
    }
    window.addEventListener('storage', handleStorage)

    let channel = null
    if (typeof BroadcastChannel !== 'undefined') {
      try {
        channel = new BroadcastChannel('bizassist_auth_channel')
        channel.onmessage = (event) => {
          if (event.data?.type === 'LOGOUT') {
            clearSession()
          }
        }
      } catch (err) {
        // ignore
      }
    }

    return () => {
      window.removeEventListener('storage', handleStorage)
      if (channel) channel.close()
    }
  }, [clearSession])

  // This fires when the tab is already open (React is mounted) and the user
  // clicks "Open AI Dashboard" again after having logged out — the mount
  // useEffect won't re-run, so the billing app uses postMessage instead.
  useEffect(() => {
    async function handleMessage(event) {
      if (!trustedHandoff(event, { billingUrl: import.meta.env.VITE_BILLING_URL })) return
      if (event.data?.type === 'AUTH_LOGOUT') { clearSession(); return }
      if (!event.data || event.data.type !== 'SSO_TICKET') return

      const ticket = event.data.ticket
      if (!ticket) return
      const requestGeneration = ++generation.current

      try {
        const res = await fetch(`${API_BASE}/redeem-ticket`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ ticket })
        })
        if (res.ok) {
          const data = await res.json()
          if (generation.current !== requestGeneration) return
          localStorage.removeItem('active_session_id')
          localStorage.setItem('user', JSON.stringify(data))
          if (data.business_name) localStorage.setItem('biz_name', data.business_name)
          setUser(data)
        } else {
          logger.warn('[SSO] postMessage ticket redemption rejected by server')
        }
      } catch (err) {
        logger.warn('[SSO] postMessage ticket redemption failed:', err)
      }
    }

    window.addEventListener('message', handleMessage)
    return () => window.removeEventListener('message', handleMessage)
  }, [clearSession])


  // ── Enterprise login ──────────────────────────────────────────
  const login = useCallback(async (username, password) => {
    const requestGeneration = ++generation.current
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
    if (requestGeneration !== generation.current) throw new Error('Sign-in cancelled')
    localStorage.setItem('user', JSON.stringify(data))
    setUser(data)
    return data
  }, [])

  // ── Enterprise signup ─────────────────────────────────────────
  const signup = useCallback(async (username, password, businessName) => {
    const requestGeneration = ++generation.current
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
    if (requestGeneration !== generation.current) throw new Error('Registration cancelled')
    localStorage.setItem('user', JSON.stringify(data))
    if (data.business_name) localStorage.setItem('biz_name', data.business_name)
    setUser(data)
    return data
  }, [])

  const logout = clearSession

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
    const requestGeneration = generation.current

    const res = await fetch(url, {
      ...options,
      headers: {
        ...(options.headers || {}),
        ...(token ? { Authorization: `Bearer ${token}` } : {})
      }
    })
    if (res.status === 401 && generation.current === requestGeneration) {
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
      <Fragment key={user?.token || adminUser?.token || 'signed-out'}>{children}</Fragment>
    </AuthContext.Provider>
  )
}

export function useAuth() {
  return useContext(AuthContext)
}
