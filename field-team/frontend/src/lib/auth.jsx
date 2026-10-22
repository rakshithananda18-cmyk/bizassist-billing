// lib/auth.jsx — who is signed in (owner or field staff) and the device id.
import React, { createContext, useCallback, useContext, useEffect, useState } from 'react'
import { api, tokenStore } from './api'

const AuthContext = createContext(null)
const DEVICE_KEY = 'task_device_id'
const LAST_BIZ_KEY = 'task_last_bizid'

// A random id per browser install. The server binds/limits staff sessions to
// it. Clearing site data creates a new "device" — the owner then releases the
// old one from Staff → Release device.
export function deviceId() {
  try {
    let id = localStorage.getItem(DEVICE_KEY)
    if (!id) {
      id = (crypto.randomUUID ? crypto.randomUUID() : `${Date.now()}-${Math.random().toString(36).slice(2)}`)
      localStorage.setItem(DEVICE_KEY, id)
    }
    return id
  } catch {
    return 'no-storage-device'
  }
}

export function deviceLabel() {
  const ua = navigator.userAgent || ''
  const os = /Android [\d.]+/.exec(ua)?.[0] || (/iPhone|iPad/.test(ua) ? 'iOS' : /Windows/.test(ua) ? 'Windows' : /Mac OS X/.test(ua) ? 'macOS' : 'Device')
  const model = /Android [\d.]+; ([^;)]+)/.exec(ua)?.[1]
  const browser = /Edg\//.test(ua) ? 'Edge' : /Chrome\//.test(ua) ? 'Chrome' : /Safari\//.test(ua) ? 'Safari' : /Firefox\//.test(ua) ? 'Firefox' : 'Browser'
  return [model, os, browser].filter(Boolean).join(' · ').slice(0, 150)
}

export function lastBizId() {
  try { return localStorage.getItem(LAST_BIZ_KEY) || '' } catch { return '' }
}

// Single sign-on from BizAssist Billing, the same hand-off as its AI dashboard:
// the Field Team link in billing's sidebar opens …/?sso=<30-second single-use
// ticket>. Taken once per page load and removed from the address bar before
// anything awaits, so StrictMode's second mount, a reload or a bookmark can
// never try to spend it again.
function takeSsoTicket() {
  try {
    const url = new URL(window.location.href)
    const ticket = url.searchParams.get('sso')
    if (!ticket) return null
    url.searchParams.delete('sso')
    window.history.replaceState(window.history.state, '', url)
    return ticket
  } catch {
    return null
  }
}

let ssoTicket = takeSsoTicket()
let ssoExchange = null

export function AuthProvider({ children }) {
  const [me, setMe] = useState(null)
  const [loading, setLoading] = useState(() => !!tokenStore.get() || !!ssoTicket)
  const [notice, setNotice] = useState(null)

  const refresh = useCallback(async () => {
    if (!tokenStore.get()) { setMe(null); setLoading(false); return null }
    try {
      const data = await api.get('/api/auth/me')
      setMe(data)
      return data
    } catch (e) {
      if (e.status === 401) { tokenStore.clear(); setMe(null) }
      return null
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    const onUnauthorized = (ev) => {
      tokenStore.clear()
      setMe(null)
      setNotice(ev.detail || 'Signed out — please sign in again.')
    }
    window.addEventListener('task:unauthorized', onUnauthorized)
    return () => window.removeEventListener('task:unauthorized', onUnauthorized)
  }, [])

  const accept = useCallback(async (data) => {
    tokenStore.set(data.token)
    if (data.public_id) { try { localStorage.setItem(LAST_BIZ_KEY, data.public_id) } catch { /* ignore */ } }
    setNotice(data.signed_out_other_device ? 'You were signed out on your other device.' : null)
    return refresh()
  }, [refresh])

  // On start: a billing hand-off ticket wins over a stored session (the owner
  // just chose to open Field Team from billing); otherwise restore the session.
  useEffect(() => {
    if (ssoTicket) {
      const ticket = ssoTicket
      ssoTicket = null
      ssoExchange = api.post('/api/auth/exchange', { ticket }).then(accept).catch((e) => {
        setNotice(e.message || 'Could not sign you in from BizAssist Billing — sign in below.')
        return refresh()
      })
    }
    if (!ssoExchange) refresh()
  }, [refresh, accept])

  const ownerLogin = (username, password) =>
    api.post('/api/auth/owner/login', { username, password }).then(accept)

  const ownerSignup = (payload) => api.post('/api/auth/owner/signup', payload).then(accept)

  const staffLogin = (business, login_name, password) =>
    api.post('/api/auth/staff/login', {
      business, login_name, password, device_id: deviceId(), device_label: deviceLabel(),
    }).then(accept)

  const logout = async () => {
    try { await api.post('/api/auth/logout') } catch { /* already gone */ }
    tokenStore.clear()
    setMe(null)
  }

  return (
    <AuthContext.Provider value={{ me, loading, notice, setNotice, refresh, ownerLogin, ownerSignup, staffLogin, logout }}>
      {children}
    </AuthContext.Provider>
  )
}

export const useAuth = () => useContext(AuthContext)
