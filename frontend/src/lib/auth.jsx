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

export function AuthProvider({ children }) {
  const [me, setMe] = useState(null)
  const [loading, setLoading] = useState(!!tokenStore.get())
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

  useEffect(() => { refresh() }, [refresh])

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

  const ownerLogin = (username, password) =>
    api.post('/api/auth/owner/login', { username, password }).then(accept)

  const ownerSignup = (payload) => api.post('/api/auth/owner/signup', payload).then(accept)

  const staffLogin = (business, login_name, password) =>
    api.post('/api/auth/staff/login', {
      business, login_name, password, device_id: deviceId(), device_label: deviceLabel(),
    }).then(accept)

  const exchange = (billing_token) => api.post('/api/auth/exchange', { billing_token }).then(accept)

  const logout = async () => {
    try { await api.post('/api/auth/logout') } catch { /* already gone */ }
    tokenStore.clear()
    setMe(null)
  }

  return (
    <AuthContext.Provider value={{ me, loading, notice, setNotice, refresh, ownerLogin, ownerSignup, staffLogin, exchange, logout }}>
      {children}
    </AuthContext.Provider>
  )
}

export const useAuth = () => useContext(AuthContext)
