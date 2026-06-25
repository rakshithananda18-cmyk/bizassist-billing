import React, { createContext, useContext, useState, useEffect, useCallback } from 'react'
import { API_BASE, updateApiBase } from '../config'
import { logger } from '../utils/logger'

const AuthContext = createContext(null)

export function AuthProvider({ children }) {
  const [user, setUser]   = useState(null)
  const [token, setToken] = useState(() => localStorage.getItem('billing_token') || null)
  const [loading, setLoading] = useState(true)
  const [businessConfig, setBusinessConfig] = useState(null)
  const [attributesSchema, setAttributesSchema] = useState([])
  const [appReady, setAppReady] = useState(false)

  // Restore session from localStorage on mount
  useEffect(() => {
    try {
      const savedUser = localStorage.getItem('billing_user')
      if (savedUser) {
        setUser(JSON.parse(savedUser))
        logger.info('Session restored successfully for user from localStorage')
      } else {
        logger.debug('No saved session user found in localStorage.')
      }
    } catch (err) {
      logger.error('Failed to restore billing session:', err)
    }
    setLoading(false)
  }, [])

  const _saveSession = useCallback((data) => {
    const tok = data.token || data.access_token
    localStorage.setItem('billing_token', tok)
    const userObj = {
      id: data.id,
      username: data.username,
      business_name: data.business_name,
      role: data.role,
    }
    localStorage.setItem('billing_user', JSON.stringify(userObj))
    setToken(tok)
    setUser(userObj)
    // Store which backend this account lives on (db_mode: 'local' | 'cloud').
    // getApiBase() reads this first so requests always go to the right DB.
    if (data.db_mode) {
      localStorage.setItem('bizassist_user_home_mode', data.db_mode)
      updateApiBase(data.db_mode)
      logger.info(`[AUTH] Account home mode set to: ${data.db_mode} (from db_mode)`)
    }
  }, [])

  const login = useCallback(async (username, password) => {
    logger.info('Attempting login for username:', username)
    const res = await fetch(`${API_BASE}/login`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username, password }),
    })
    if (!res.ok) {
      const err = await res.json().catch(() => ({}))
      logger.error('Login request failed with status:', res.status, err.detail)
      throw new Error(err.detail || 'Invalid credentials')
    }
    const data = await res.json()
    logger.info('Login successful for user:', data.username, 'role:', data.role)
    _saveSession(data)
  }, [_saveSession])

  const signup = useCallback(async ({ username, password, business_name, template_key }) => {
    logger.info('Attempting signup for username:', username, 'business:', business_name, 'template:', template_key)
    const res = await fetch(`${API_BASE}/signup`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username, password, business_name }),
    })
    if (!res.ok) {
      const err = await res.json().catch(() => ({}))
      logger.error('Signup request failed with status:', res.status, err.detail)
      throw new Error(err.detail || 'Registration failed')
    }
    const data = await res.json()
    logger.info('Signup and session setup successful for user:', data.username)

    // Setup business template before saving session
    const tok = data.token || data.access_token
    if (tok && template_key) {
      try {
        const setupRes = await fetch(`${API_BASE}/business/setup`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'Authorization': `Bearer ${tok}`
          },
          body: JSON.stringify({ template_key })
        })
        if (!setupRes.ok) {
          logger.error('Failed to setup business template on signup:', setupRes.status)
        } else {
          logger.info('Business template setup succeeded on signup with key:', template_key)
        }
      } catch (err) {
        logger.error('Error during business template setup on signup:', err)
      }
    }

    _saveSession(data)
  }, [_saveSession])

  const logout = useCallback(() => {
    logger.info('Logging out user, clearing local session token.')
    localStorage.removeItem('billing_token')
    localStorage.removeItem('billing_user')
    localStorage.removeItem('bizassist_user_home_mode')  // clear home mode — next user gets their own
    setToken(null)
    setUser(null)
    setAppReady(false)
  }, [])

  /**
   * switchMode — change hosting mode and force re-login.
   *
   * Why logout? Local and cloud databases assign different integer IDs to the
   * same username (e.g. local id=122, cloud id=7 for 'Rakshith'). The JWT
   * embeds that id. After switching backends the old JWT references an id that
   * doesn't exist in the new DB → every request fails with 401.
   * Logging out clears the stale JWT; the user re-authenticates against the
   * new backend and gets a fresh, correct JWT.
   */
  const switchMode = useCallback(async (newMode) => {
    logger.info(`[MODE SWITCH] Switching to "${newMode}" mode — will logout to refresh JWT`)
    // 1. Save the new mode to the CURRENT backend before switching
    try {
      await fetch(`${API_BASE}/settings`, {
        method: 'PATCH',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({ general: { hosting_mode: newMode } }),
      })
    } catch (err) {
      logger.warn('[MODE SWITCH] Could not save mode to backend (continuing anyway):', err)
    }
    // 2. Update localStorage so the new API_BASE is effective immediately
    updateApiBase(newMode)
    // 3. Force logout — clears stale JWT; user will log in against new backend
    localStorage.removeItem('billing_token')
    localStorage.removeItem('billing_user')
    setToken(null)
    setUser(null)
    setAppReady(false)
    window.dispatchEvent(new CustomEvent('show_toast', {
      detail: { type: 'info', msg: `Switched to ${newMode} mode. Please log in again.` }
    }))
    logger.info(`[MODE SWITCH] Done. API_BASE is now: ${API_BASE}`)
  }, [token])

  const [profile, setProfile] = useState(null)

  const fetchProfile = useCallback(async () => {
    if (!token) return
    try {
      const res = await fetch(`${API_BASE}/profile`, {
        headers: {
          Authorization: `Bearer ${token}`
        }
      })
      if (res.ok) {
        const data = await res.json()
        setProfile(data)
      }
    } catch (err) {
      logger.error('Failed to fetch profile:', err)
    }
  }, [token])

  const [settings, setSettings] = useState(null)

  const fetchSettings = useCallback(async () => {
    if (!token) return
    try {
      const res = await fetch(`${API_BASE}/settings`, {
        headers: {
          Authorization: `Bearer ${token}`
        }
      })
      if (res.ok) {
        const data = await res.json()
        setSettings(data)
        logger.info('Loaded app settings successfully in context')
        // NOTE: We do NOT call updateApiBase here.
        // The user's home mode (bizassist_user_home_mode) is the source of truth
        // for which backend to hit. Overriding it from settings would cause
        // wrong-backend routing after a mode switch + re-login.
      }
    } catch (err) {
      logger.error('Failed to fetch settings in context:', err)
    }
  }, [token])

  const fetchBusinessConfig = useCallback(async () => {
    if (!token) return
    try {
      const res = await fetch(`${API_BASE}/business/config`, {
        headers: {
          Authorization: `Bearer ${token}`
        }
      })
      if (res.ok) {
        const data = await res.json()
        setBusinessConfig(data.config)
        setAttributesSchema(data.attributes_schema || [])
        logger.info('Loaded business config successfully')
      }
    } catch (err) {
      logger.error('Failed to fetch business config:', err)
    }
  }, [token])

  useEffect(() => {
    if (token) {
      fetchProfile()
      fetchBusinessConfig()
      fetchSettings()
    } else {
      setProfile(null)
      setBusinessConfig(null)
      setSettings(null)
      setAttributesSchema([])
    }
  }, [token, fetchProfile, fetchBusinessConfig, fetchSettings])

  useEffect(() => {
    const handleRefreshSettings = () => {
      logger.info('[AuthContext] refresh-settings event triggered. Fetching latest settings…')
      fetchSettings()
    }
    window.addEventListener('refresh-settings', handleRefreshSettings)
    return () => {
      window.removeEventListener('refresh-settings', handleRefreshSettings)
    }
  }, [fetchSettings])

  // Authenticated fetch helper
  const authFetch = useCallback(async (path, opts = {}) => {
    let apiPath = path
    if (apiPath.startsWith('/billing/')) {
      apiPath = '/' + apiPath.slice('/billing/'.length)
    } else if (apiPath.startsWith('billing/')) {
      apiPath = '/' + apiPath.slice('billing/'.length)
    }

    logger.debug(`authFetch request started for path: ${path} (mapped to ${apiPath}), method: ${opts.method || 'GET'}`)
    
    const headers = {
      ...(opts.headers || {}),
      Authorization: `Bearer ${token}`
    }
    if (!(opts.body instanceof FormData)) {
      headers['Content-Type'] = 'application/json'
    }

    let res
    try {
      res = await fetch(`${API_BASE}${apiPath}`, {
        ...opts,
        headers
      })
    } catch (err) {
      logger.error(`authFetch network failure for path: ${path}`, err)
      window.dispatchEvent(new CustomEvent('show_toast', {
        detail: { type: 'error', msg: err.message || 'Network connection failed' }
      }))
      throw err
    }

    if (res.status === 401) {
      logger.warn(`authFetch encountered 401 (Unauthorized) for path: ${path}. Auto-logging out.`)
      logout()
      throw new Error('Session expired')
    }

    if (!res.ok) {
      res.clone().json().then(err => {
        const detail = err?.detail || `Error: ${res.statusText || res.status}`
        window.dispatchEvent(new CustomEvent('show_toast', {
          detail: { type: 'error', msg: detail }
        }))
      }).catch(() => {
        window.dispatchEvent(new CustomEvent('show_toast', {
          detail: { type: 'error', msg: `Request failed with status ${res.status}` }
        }))
      })
    }

    logger.debug(`authFetch response status for path ${path}: ${res.status}`)
    return res
  }, [token, logout])

  return (
    <AuthContext.Provider value={{
      user, token, loading, login, logout, signup, switchMode, authFetch, profile, fetchProfile, setProfile,
      businessConfig, attributesSchema, fetchBusinessConfig, appReady, setAppReady,
      settings, fetchSettings
    }}>
      {children}
    </AuthContext.Provider>
  )
}

export const useAuth = () => useContext(AuthContext)

export const useBusinessConfig = () => {
  const { businessConfig, attributesSchema, fetchBusinessConfig } = useAuth()
  
  const t = useCallback((key, fallback) => {
    if (!businessConfig || !businessConfig.terminology) {
      return fallback || key
    }
    const lowerKey = key.toLowerCase()
    const resolved = businessConfig.terminology[lowerKey]
    if (resolved) {
      if (key[0] === key[0].toUpperCase()) {
        return resolved.charAt(0).toUpperCase() + resolved.slice(1)
      }
      return resolved
    }
    return fallback || key
  }, [businessConfig])

  return {
    config: businessConfig,
    attributesSchema,
    refreshConfig: fetchBusinessConfig,
    t
  }
}

