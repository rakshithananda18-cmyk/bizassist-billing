import { createContext, useContext, useState, useEffect, useCallback, useMemo, useRef } from 'react'
import { API_BASE } from '../config'
import { setBizId } from '../utils/logger'
import { trustedHandoff } from '../utils/handoff'
import { boundedFetch, isSessionRejection, responseError } from '../utils/httpErrors'
import { useSessionRefresh } from '../hooks/useSessionRefresh'
const AuthContext = createContext(null)
const HANDOFF_ERROR = 'Billing could not sign you in. Open Dashboard BIZASSIST from Billing again, or sign in here.'

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null)
  const [adminUser, setAdminUser] = useState(null)
  const [loading, setLoading] = useState(true)
  const [notice, setNotice] = useState(null)
  const generation = useRef(0)
  const sessions = useRef({})
  sessions.current = { user, adminUser }
  const initial = useRef(null)
  if (!initial.current) {
    const params = new URLSearchParams(window.location.search)
    initial.current = { ticket: params.get('sso'), logout: params.get('logout') === 'true', promise: null }
  }
  const rememberPath = useCallback(() => {
    const path = window.location.pathname + window.location.search + window.location.hash
    if (path.startsWith('/admin/') && window.location.pathname !== '/admin/login') {
      try { sessionStorage.setItem('admin_return_path', path) } catch { /* storage unavailable */ }
    }
  }, [])
  const clearSession = useCallback(() => {
    generation.current++
    for (const store of [localStorage, sessionStorage]) {
      for (const key of ['user', 'admin_user', 'active_session_id', 'biz_name', 'token', 'access_token', 'admin_token']) store.removeItem(key)
    }
    setUser(null)
    setAdminUser(null)
  }, [])
  const adminLogout = useCallback(() => {
    rememberPath()
    generation.current++
    localStorage.removeItem('admin_user')
    localStorage.removeItem('biz_name')
    setAdminUser(null)
  }, [rememberPath])
  const acceptUser = useCallback(data => {
    localStorage.setItem('user', JSON.stringify(data))
    if (data.business_name) localStorage.setItem('biz_name', data.business_name)
    setUser(data)
  }, [])
  const acceptAdmin = useCallback(data => {
    localStorage.setItem('admin_user', JSON.stringify(data))
    setAdminUser(data)
  }, [])
  const { warning: userWarning, refreshSession: refreshUser } = useSessionRefresh(user, acceptUser, clearSession)
  const { warning: adminWarning, refreshSession: refreshAdmin } = useSessionRefresh(adminUser, acceptAdmin, adminLogout)
  useEffect(() => { setBizId(user?.public_id || null) }, [user])

  const redeem = useCallback(async ticket => {
    const res = await boundedFetch(`${API_BASE}/redeem-ticket`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ ticket }),
    })
    if (!res.ok) throw await responseError(res)
    const data = await res.json()
    if (!data.token) throw new Error('Missing sign-in session')
    if (data.role === 'admin') {
      const confirmation = await boundedFetch(`${API_BASE}/admin/session`, { headers: { Authorization: `Bearer ${data.token}` } })
      if (!confirmation.ok) throw await responseError(confirmation)
      return { ...data, ...(await confirmation.json()), token: data.token }
    }
    return data
  }, [])
  const acceptHandoff = useCallback(data => {
    if (data.role === 'admin') acceptAdmin(data)
    else acceptUser(data)
    setNotice(null)
  }, [acceptUser, acceptAdmin])
  useEffect(() => {
    let active = true
    const launch = initial.current
    const init = async () => {
      if (launch.logout) {
        clearSession()
        const url = new URL(window.location)
        url.searchParams.delete('logout')
        window.history.replaceState({}, document.title, url)
        setLoading(false)
        return
      }
      if (launch.ticket) {
        clearSession()
        const requestGeneration = generation.current
        const url = new URL(window.location)
        url.searchParams.delete('sso')
        window.history.replaceState({}, document.title, url)
        if (!launch.promise) launch.promise = redeem(launch.ticket)
        try {
          const data = await launch.promise
          if (!active || requestGeneration !== generation.current) return
          acceptHandoff(data)
        } catch {
          if (!active || requestGeneration !== generation.current) return
          clearSession()
          setNotice(HANDOFF_ERROR)
        } finally { if (active) setLoading(false) }
        return
      }
      try {
        const savedUser = localStorage.getItem('user')
        const savedAdmin = localStorage.getItem('admin_user')
        if (savedUser) setUser(JSON.parse(savedUser))
        if (savedAdmin) setAdminUser(JSON.parse(savedAdmin))
      } catch { clearSession() }
      setLoading(false)
    }
    init()
    return () => { active = false }
  }, [clearSession, redeem, acceptHandoff])
  useEffect(() => {
    const onMessage = async event => {
      if (!trustedHandoff(event, { billingUrl: import.meta.env.VITE_BILLING_URL })) return
      if (event.data?.type === 'AUTH_LOGOUT') { clearSession(); setLoading(false); return }
      if (event.data?.type !== 'SSO_TICKET' || !event.data.ticket) return
      clearSession()
      setNotice(null)
      setLoading(true)
      const requestGeneration = generation.current
      try {
        const data = await redeem(event.data.ticket)
        if (requestGeneration === generation.current) { acceptHandoff(data); setLoading(false) }
      } catch {
        if (requestGeneration === generation.current) { clearSession(); setNotice(HANDOFF_ERROR); setLoading(false) }
      }
    }
    const onStorage = event => {
      if (!['user', 'admin_user'].includes(event.key) && event.key !== null) return
      generation.current++
      if (event.key === null || !event.newValue) {
        if (event.key === 'admin_user') setAdminUser(null)
        else { localStorage.removeItem('biz_name'); setUser(null); if (event.key === null) setAdminUser(null) }
      } else {
        try { (event.key === 'admin_user' ? setAdminUser : setUser)(JSON.parse(event.newValue)) }
        catch { clearSession() }
      }
    }
    window.addEventListener('message', onMessage)
    window.addEventListener('storage', onStorage)
    let channel
    try {
      if (typeof BroadcastChannel !== 'undefined') {
        channel = new BroadcastChannel('bizassist_auth_channel')
        channel.onmessage = event => { if (event.data?.type === 'LOGOUT') clearSession() }
      }
    } catch { /* not supported */ }
    return () => { window.removeEventListener('message', onMessage); window.removeEventListener('storage', onStorage); channel?.close() }
  }, [clearSession, redeem, acceptHandoff])
  const credentials = useCallback(async (path, body, admin = false) => {
    const requestGeneration = ++generation.current
    const res = await boundedFetch(`${API_BASE}${path}`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
    if (!res.ok) throw await responseError(res)
    const data = await res.json()
    if (requestGeneration !== generation.current) throw new Error('Sign-in cancelled')
    if (admin && data.role !== 'admin') throw new Error('Access denied. Admin role required.')
    ;(admin ? acceptAdmin : acceptUser)(data)
    setNotice(null)
    return data
  }, [acceptAdmin, acceptUser])
  const login = useCallback((username, password) => credentials('/login', { username, password }), [credentials])
  const signup = useCallback((username, password, businessName) => credentials('/signup', { username, password, business_name: businessName }), [credentials])
  const adminLogin = useCallback((username, password, otp) => credentials('/login', otp ? { username, password, otp } : { username, password }, true), [credentials])
  const logout = clearSession
  const authFetch = useCallback(async (url, options = {}) => {
    const isAdmin = url.includes('/admin/')
    const active = isAdmin ? (adminUser || user) : (user || adminUser)
    const token = active?.token
    const requestGeneration = generation.current
    const res = await boundedFetch(url, {
      ...options, headers: { ...(options.headers || {}), ...(token ? { Authorization: `Bearer ${token}` } : {}) },
    })
    const latest = isAdmin ? (sessions.current.adminUser || sessions.current.user) : (sessions.current.user || sessions.current.adminUser)
    if (requestGeneration === generation.current && token === latest?.token) {
      if (isSessionRejection(res)) { if (isAdmin) adminLogout(); else clearSession() }
      else if (res.status === 401) await (isAdmin ? refreshAdmin : refreshUser)(true)
    }
    return res
  }, [adminUser, user, adminLogout, clearSession, refreshAdmin, refreshUser])
  const value = useMemo(() => ({ user, adminUser, loading, notice, login, signup, logout, adminLogin, adminLogout, authFetch }),
    [user, adminUser, loading, notice, login, signup, logout, adminLogin, adminLogout, authFetch])
  return (
    <AuthContext.Provider value={value}>
      {(notice || adminWarning || userWarning) && <div role="alert" className="auth-session-notice">{notice || adminWarning || userWarning}
        {notice && <button type="button" onClick={() => { setNotice(null); window.location.assign('/admin/login') }}>Sign in</button>}
      </div>}
      {children}
    </AuthContext.Provider>
  )
}
export function useAuth() { return useContext(AuthContext) }
