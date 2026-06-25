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
    setToken(null)
    setUser(null)
    setAppReady(false)
  }, [])

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
        if (data?.general?.hosting_mode) {
          updateApiBase(data.general.hosting_mode)
        }
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
      user, token, loading, login, logout, signup, authFetch, profile, fetchProfile, setProfile,
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

