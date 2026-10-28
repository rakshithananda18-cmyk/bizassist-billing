// lib/auth.jsx — who is signed in (owner or field staff) and the device id.
import React, { createContext, useCallback, useContext, useEffect, useRef, useState } from 'react'
import { api, tokenStore } from './api'
import { setThemeBusiness } from './theme'
import { startBillingBridge, takeBillingLaunch } from './billingBridge'

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

// A handoff takes precedence over every stored session. Only the exchange is
// shared across StrictMode effects; a later provider mount restores the current
// token instead of replaying an already consumed handoff.
const billingLaunch = takeBillingLaunch()
let ssoExchange = null
let launchHandled = false

export function AuthProvider({ children }) {
  const [me, setMe] = useState(null)
  const [loading, setLoading] = useState(() => !!tokenStore.get() || billingLaunch.requested)
  const [notice, setNotice] = useState(null)
  const lastRefresh = useRef(0)

  const clearSession = useCallback(() => {
    tokenStore.clear()
    setMe(null)
    setThemeBusiness(null)
  }, [])

  const refresh = useCallback(async () => {
    const token = tokenStore.get()
    if (!token) { setMe(null); setThemeBusiness(null); setLoading(false); return null }
    try {
      const data = await api.get('/api/auth/me')
      if (tokenStore.get() !== token) return null
      if (billingLaunch.expectedBusiness && data.public_id !== billingLaunch.expectedBusiness) {
        clearSession()
        setNotice('This is a different business from Billing. Open Field Team from the correct Billing account, or sign in with that account.')
        return null
      }
      setThemeBusiness(data.public_id)
      setMe(data)
      lastRefresh.current = Date.now()
      return data
    } catch (e) {
      if (tokenStore.get() !== token) return null
      if (e.status === 401 || e.status === 402) clearSession()
      setNotice(e.message || 'Could not verify your business. Please retry.')
      return null
    } finally {
      if (!tokenStore.get() || tokenStore.get() === token) setLoading(false)
    }
  }, [clearSession])

  useEffect(() => {
    const onUnauthorized = (ev) => {
      clearSession()
      setNotice(ev.detail || 'Signed out — please sign in again.')
    }
    window.addEventListener('task:unauthorized', onUnauthorized)
    return () => window.removeEventListener('task:unauthorized', onUnauthorized)
  }, [clearSession])

  const accept = useCallback(async (data) => {
    tokenStore.set(data.token)
    if (data.public_id) { try { localStorage.setItem(LAST_BIZ_KEY, data.public_id) } catch { /* ignore */ } }
    setNotice(data.signed_out_other_device ? 'You were signed out on your other device.' : null)
    const verified = await refresh()
    if (!verified) throw new Error('Could not confirm this business. Please check the connection and sign in again.')
    return verified
  }, [refresh])

  useEffect(() => {
    let active = true
    if (billingLaunch.requested && !launchHandled) {
      if (!ssoExchange) {
        clearSession()
        ssoExchange = billingLaunch.ticket
          ? api.post('/api/auth/exchange', { ticket: billingLaunch.ticket })
          : Promise.resolve(null)
      }
      ssoExchange.then(async data => {
        if (!active) return
        launchHandled = true
        if (data) await accept(data)
        else setNotice('Billing could not hand over this session. Sign in with the same Billing account to continue.')
      }).catch(e => {
        if (!active) return
        launchHandled = true
        clearSession()
        setNotice(e.message || 'Could not sign you in from Billing. Sign in with the same account below.')
      }).finally(() => { if (active) setLoading(false) })
    } else refresh()
    return () => { active = false }
  }, [refresh, accept, clearSession])

  const kind = me?.kind
  const businessId = me?.public_id
  useEffect(() => startBillingBridge({ kind, public_id: businessId }, billingLaunch), [kind, businessId])

  useEffect(() => {
    let pending = false
    const onFocus = () => {
      if (pending || document.visibilityState === 'hidden' || !tokenStore.get()
        || Date.now() - lastRefresh.current < 15000) return
      pending = true
      refresh().finally(() => { pending = false })
    }
    window.addEventListener('focus', onFocus)
    window.addEventListener('online', onFocus)
    document.addEventListener('visibilitychange', onFocus)
    return () => {
      window.removeEventListener('focus', onFocus)
      window.removeEventListener('online', onFocus)
      document.removeEventListener('visibilitychange', onFocus)
    }
  }, [refresh])

  const signIn = async (path, body) => {
    clearSession()
    setNotice(null)
    return accept(await api.post(path, body))
  }

  const ownerLogin = (username, password) =>
    signIn('/api/auth/owner/login', { username, password })

  const ownerSignup = (payload) => signIn('/api/auth/owner/signup', payload)

  const staffLogin = (business, login_name, password) =>
    signIn('/api/auth/staff/login', {
      business, login_name, password, device_id: deviceId(), device_label: deviceLabel(),
    })

  const logout = async () => {
    try { await api.post('/api/auth/logout') } catch { /* already gone */ }
    clearSession()
    billingLaunch.expectedBusiness = null
    billingLaunch.origin = null
  }

  return (
    <AuthContext.Provider value={{ me, loading, notice, setNotice, refresh, ownerLogin, ownerSignup, staffLogin, logout }}>
      {children}
    </AuthContext.Provider>
  )
}

export const useAuth = () => useContext(AuthContext)
