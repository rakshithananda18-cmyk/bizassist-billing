import React, { createContext, useContext, useState, useEffect, useCallback } from 'react'
import { API_BASE, updateApiBase, IS_LOCAL_APP, CLOUD_URL, LOCAL_URL } from '../config'
import { logger, setBizId } from '../utils/logger'
import { reconcileBizIdOnLogin } from '../utils/loginSync'

const AuthContext = createContext(null)

const decodeToken = (token) => {
  try {
    const base64Url = (token || '').split('.')[1]
    if (!base64Url) return null
    const base64 = base64Url.replace(/-/g, '+').replace(/_/g, '/')
    const jsonPayload = decodeURIComponent(atob(base64).split('').map(function(c) {
      return '%' + ('00' + c.charCodeAt(0).toString(16)).slice(-2)
    }).join(''))
    return JSON.parse(jsonPayload)
  } catch (e) {
    return null
  }
}

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
      const savedToken = localStorage.getItem('billing_token')
      if (savedUser) {
        let userObj = JSON.parse(savedUser)
        // Ensure user_id / public_id are populated even for old sessions by
        // decoding the token (both are in the JWT payload).
        if (savedToken && (!userObj.user_id || !userObj.public_id)) {
          const decoded = decodeToken(savedToken)
          if (decoded) {
            userObj.user_id = userObj.user_id || decoded.user_id
            userObj.public_id = userObj.public_id || decoded.public_id
            localStorage.setItem('billing_user', JSON.stringify(userObj))
            logger.info('Auto-healed user session from JWT payload (user_id/public_id).')
          }
        }
        setUser(userObj)
        setBizId(userObj.public_id)   // restore [BizId=…] logging context
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
    
    // Auto-resolve user_id / public_id from token payload if not sent in the
    // data response (the JWT carries both).
    let resolvedUserId = data.user_id
    let resolvedBizId = data.public_id
    if ((!resolvedUserId || !resolvedBizId) && tok) {
      const decoded = decodeToken(tok)
      resolvedUserId = resolvedUserId || decoded?.user_id
      resolvedBizId = resolvedBizId || decoded?.public_id
    }

    const userObj = {
      id: data.id,
      user_id: resolvedUserId || data.id,
      public_id: resolvedBizId || null,               // BizID — used for [BizId=…] logging + telemetry
      username: data.username,
      business_name: data.business_name,
      role: data.role,
      counter_prefix: data.counter_prefix || null,   // POS counter series for this login (§9.3a)
    }
    localStorage.setItem('billing_user', JSON.stringify(userObj))
    setToken(tok)
    setUser(userObj)
    setBizId(userObj.public_id)   // stamp every subsequent log line with [BizId=…]
    // Store which backend this account lives on (db_mode: 'local' | 'cloud').
    // We log a warning if the account's home backend doesn't match the current
    // platform (e.g. local account opened on web URL) but do NOT redirect —
    // the URL-based detection in config.js is the authoritative routing rule.
    if (data.db_mode) {
      localStorage.setItem('bizassist_user_home_mode', data.db_mode)
      const currentPlatform = IS_LOCAL_APP ? 'local' : 'cloud'
      if (data.db_mode !== currentPlatform) {
        logger.warn(
          `[AUTH] Account home is "${data.db_mode}" but running on "${currentPlatform}" platform. ` +
          `Data may be on a different backend. Consider switching platforms.`
        )
      } else {
        logger.info(`[AUTH] Account home mode confirmed: ${data.db_mode}`)
      }
    }
  }, [])

  /**
   * Standard device provisioning (no shared secrets): with the credentials the
   * user just typed, obtain a CLOUD-issued 24 h token scoped to this business
   * and hand it to the local backend for the hybrid sync worker
   * (POST /api/sync/cloud-token). Best-effort — never blocks or fails login.
   */
  const _provisionCloudSyncToken = useCallback(async (username, password, localToken, cloudToken = null) => {
    if (!IS_LOCAL_APP || !localToken) return null
    if (typeof navigator !== 'undefined' && navigator.onLine === false) return null
    try {
      let token = cloudToken
      if (!token) {
        const res = await fetch(`${CLOUD_URL}/login`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ username, password }),
        })
        if (!res.ok) return null
        token = (await res.json())?.token
      }
      if (!token) return null
      localStorage.setItem('bizassist_cloud_token', token)
      await fetch(`${LOCAL_URL}/api/sync/cloud-token`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${localToken}` },
        body: JSON.stringify({ token }),
      })
      logger.info('[SYNC] Cloud sync token provisioned (24h, business-scoped)')
      // Keep the CLOUD record's hosting_mode in step with this device when it's
      // on Local + Cloud, so the Admin Console shows "Local + Cloud" (the sync
      // worker moves business data, not the settings JSON). Runs for BOTH paths
      // that mint a cloud token — signup and the Settings switch → re-login.
      // Best-effort and informational; never affects the token result.
      try {
        const mode = (typeof localStorage !== 'undefined' && localStorage.getItem('bizassist_hosting_mode')) || 'local'
        if (mode === 'hybrid') {
          await fetch(`${CLOUD_URL}/settings`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
            body: JSON.stringify({ general: { hosting_mode: 'hybrid' } }),
          }).catch(() => {})
        }
      } catch { /* informational only */ }
      return token
    } catch (err) {
      logger.debug('[SYNC] Cloud sync token provisioning skipped:', err?.message)
      return null
    }
  }, [])

  const login = useCallback(async (username, password) => {
    logger.info('Attempting login for username:', username)

    // 1. Try the platform's primary backend (local on the downloaded app).
    const res = await fetch(`${API_BASE}/login`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username, password }),
    })
    if (res.ok) {
      const data = await res.json()
      logger.info('Login successful for user:', data.username, 'role:', data.role)
      _saveSession(data)
      // Fire-and-forget: provision the cloud sync token first, then run the
      // BizID identity check WITH that cloud token. Never send a locally
      // signed JWT to the cloud — its JWT_SECRET differs on packaged installs,
      // so the cloud would (correctly) reject it with 401 "Invalid token".
      _provisionCloudSyncToken(username, password, data.token || data.access_token)
        .then(cloudTok => reconcileBizIdOnLogin(data.token || data.access_token, cloudTok))
      return
    }

    // 2. FRESH-DEVICE fallback (downloaded app, online): if there's simply no
    //    local user yet, authenticate against the CLOUD and create the local
    //    mirror (identity only — data stays gated, pulled later via "Back up
    //    now"). We first confirm the local account truly doesn't exist, so a
    //    wrong password on an existing local account is NEVER masked.
    if (IS_LOCAL_APP) {
      // The local identity check works offline (it's localhost).
      let localExists = true
      try {
        const c = await fetch(`${LOCAL_URL}/api/biz_id/check`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ username }),
        })
        if (c.ok) localExists = (await c.json())?.exists === true
      } catch { /* treat as exists → no fallback */ }

      if (!localExists) {
        // Fresh device. We need the cloud to set it up — block clearly if offline.
        if (typeof navigator !== 'undefined' && navigator.onLine === false) {
          throw new Error('This account isn’t set up on this device yet. Connect to the internet once to set it up, then it works offline.')
        }
        const cloudRes = await fetch(`${CLOUD_URL}/login`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ username, password }),
        })
        if (cloudRes.ok) {
          const cloudData = await cloudRes.json()
          // Create the local mirror with the SAME (cloud) BizID — identity only.
          const mirror = await fetch(`${LOCAL_URL}/signup`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              username, password,
              business_name: cloudData.business_name || username,
              public_id: cloudData.public_id,
            }),
          })
          if (mirror.ok) {
            const localData = await mirror.json()
            logger.info(`[LOGIN] Fresh device — local mirror created (BizID ${cloudData.public_id}). Data is gated; use "Cloud → Local Sync" to pull it.`)
            _saveSession(localData)
            // Sense divergence and pop the "Cloud → Local Sync" nudge — on a fresh
            // device the cloud always has more, so this surfaces the data popup.
            reconcileBizIdOnLogin(localData.token || localData.access_token, cloudData.token)
            // We already hold a fresh cloud token from the fresh-device login — store it.
            _provisionCloudSyncToken(username, password, localData.token || localData.access_token, cloudData.token)
            return
          }
          logger.error(`[LOGIN] Cloud login ok but local mirror failed: HTTP ${mirror.status}`)
          throw new Error('Signed in, but could not set up this device. Please try again.')
        }
        // Cloud login also failed → fall through to surface the credential error.
      } else if (res.status === 401) {
        // Local account exists but credentials failed locally. Check if cloud has updated credentials.
        try {
          if (typeof navigator === 'undefined' || navigator.onLine !== false) {
            const cloudRes = await fetch(`${CLOUD_URL}/login`, {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ username, password }),
            })
            if (cloudRes.ok) {
              const cloudData = await cloudRes.json()
              // Credentials verified on Cloud. Request local backend to reconcile/sync the password.
              const reconcileRes = await fetch(`${LOCAL_URL}/api/auth/reconcile_password`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                  username,
                  password,
                  public_id: cloudData.public_id
                })
              })
              if (reconcileRes.ok) {
                // Retry local login now that local password hash is updated.
                const retryRes = await fetch(`${API_BASE}/login`, {
                  method: 'POST',
                  headers: { 'Content-Type': 'application/json' },
                  body: JSON.stringify({ username, password }),
                })
                if (retryRes.ok) {
                  const retryData = await retryRes.json()
                  logger.info('[LOGIN] Local password reconciled with cloud and login successful.')
                  _saveSession(retryData)
                  _provisionCloudSyncToken(username, password, retryData.token || retryData.access_token, cloudData.token)
                    .then(cloudTok => reconcileBizIdOnLogin(retryData.token || retryData.access_token, cloudTok))
                  return
                }
              } else {
                const recErr = await reconcileRes.json().catch(() => ({}))
                if (recErr.detail) {
                  throw new Error(recErr.detail)
                }
              }
            }
          }
        } catch (err) {
          if (err.message && err.message.includes('Identity mismatch')) {
            logger.error('[LOGIN-RECONCILE] Reconcile mismatch:', err.message)
            throw err
          }
          logger.warn('[LOGIN-RECONCILE] Swallowing non-mismatch reconcile error:', err.message)
        }
      }
    }

    // 3. No fallback applied → surface the original error.
    const err = await res.json().catch(() => ({}))
    logger.error('Login request failed with status:', res.status, err.detail)
    throw new Error(err.detail || 'Invalid credentials')
  }, [_saveSession, _provisionCloudSyncToken])

  // Staff login (§9.5): staff never use a global username — authenticate scoped to
  // the business owner (owner username + per-business counter/staff name + password).
  const staffLogin = useCallback(async (ownerUsername, staffLoginName, password) => {
    logger.info('Attempting staff login under owner:', ownerUsername, 'as', staffLoginName)
    const body = JSON.stringify({ owner_username: ownerUsername, staff_login_name: staffLoginName, password })

    // 1. Try the platform's primary backend (local on the desktop app).
    const res = await fetch(`${API_BASE}/login/staff`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body,
    })
    if (res.ok) {
      const data = await res.json()
      logger.info('Staff login successful:', data.username, 'role:', data.role)
      _saveSession(data)
      reconcileBizIdOnLogin(data.token || data.access_token)
      return
    }

    // 2. FRESH-DEVICE fallback (desktop, online): on a brand-new device the local
    //    backend is only an identity mirror — the owner's staff rows aren't there
    //    yet (they arrive when the business data syncs down). So a staff on a new
    //    terminal fails locally even with the correct password. Authenticate
    //    against the CLOUD instead and run THIS terminal as a cloud client — it
    //    has no local copy of the business to serve anyway (same as the web).
    //    This never masks a wrong password: the cloud is tried only AFTER the
    //    local attempt has already failed. Reversible from Settings → Hosting.
    if (IS_LOCAL_APP && CLOUD_URL !== API_BASE &&
        (typeof navigator === 'undefined' || navigator.onLine !== false)) {
      try {
        const cloudRes = await fetch(`${CLOUD_URL}/login/staff`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body,
        })
        if (cloudRes.ok) {
          const cloudData = await cloudRes.json()
          logger.info('[STAFF] Fresh device — authenticated on cloud; running this terminal as a cloud client.')
          // Point this device at the cloud where the staff's data lives. (Hybrid
          // routes to the LOCAL backend, which lacks the data, so it must be cloud.)
          updateApiBase('cloud')
          _saveSession(cloudData)
          window.dispatchEvent(new CustomEvent('show_toast', {
            detail: { type: 'info', msg: 'Signed in via cloud — this device has no local copy of the business yet.' },
          }))
          return
        }
      } catch (e) {
        logger.warn('[STAFF] Cloud fallback failed:', e?.message)
      }
    }

    // 3. No fallback applied → surface the original error.
    const err = await res.json().catch(() => ({}))
    logger.error('Staff login failed:', res.status, err.detail)
    throw new Error(err.detail || 'Invalid credentials')
  }, [_saveSession])

  // Apply the chosen business template on a backend (best-effort).
  const _applyTemplate = useCallback(async (base, tok, template_key) => {
    if (!tok || !template_key) return
    try {
      const r = await fetch(`${base}/business/setup`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${tok}` },
        body: JSON.stringify({ template_key }),
      })
      if (!r.ok) logger.error(`[SIGNUP] template setup on ${base} failed: HTTP ${r.status}`)
      else logger.info(`[SIGNUP] template setup ok on ${base} (${template_key})`)
    } catch (err) {
      logger.error(`[SIGNUP] template setup error on ${base}:`, err)
    }
  }, [])

  const _doSignup = useCallback(async (base, body) => {
    const res = await fetch(`${base}/signup`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
    if (!res.ok) {
      const err = await res.json().catch(() => ({}))
      const e = new Error(err.detail || 'Registration failed')
      e.status = res.status
      throw e
    }
    return res.json()
  }, [])

  const signup = useCallback(async ({ username, password, business_name, template_key, hosting = 'local', phone = null }) => {
    logger.info('Attempting signup for username:', username, 'business:', business_name, 'template:', template_key, 'hosting:', hosting)

    // Cloud-authoritative identity (D9): on the downloaded app we register on the
    // CLOUD first (the single BizID authority), then mirror the account locally
    // with that BizID so both sides share one identity. Registration therefore
    // needs a one-time network connection. On the web there is no local backend,
    // so we just register on the cloud (current behaviour).
    if (IS_LOCAL_APP) {
      if (typeof navigator !== 'undefined' && navigator.onLine === false) {
        throw new Error('Registration needs an internet connection (your account is created on the cloud once, then works offline).')
      }
      // 1. Create the cloud account → mints the BizID.
      let cloudData
      try {
        cloudData = await _doSignup(CLOUD_URL, { username, password, business_name, phone })
      } catch (err) {
        if (err.status === 400) {
          // Username already taken on the cloud — most likely the same person.
          throw new Error('An account with this username already exists. Please log in instead.')
        }
        throw err
      }
      const bizId = cloudData.public_id

      // 2. Mirror locally with the SAME BizID, then log in locally (local-first).
      //    Seed the template ONLY on local (the working copy); the cloud receives
      //    this data later via backup/push, so seeding it on cloud too would
      //    create duplicate starter data.
      let localData
      let didReclaim = false
      try {
        localData = await _doSignup(LOCAL_URL, { username, password, business_name, public_id: bizId, phone })
      } catch (err) {
        // Local orphan: the cloud accepted this username (so its old cloud account
        // was deleted → username free on the cloud), but a stale LOCAL mirror still
        // holds it → the local /signup 400s. Re-key that orphan to the new BizID
        // instead of failing — same person, same device. (Non-destructive: any
        // existing local data on the row is kept.)
        if (err.status === 400) {
          logger.warn('[SIGNUP] Local username is orphaned — reclaiming it onto the new cloud BizID.')
          const res = await fetch(`${LOCAL_URL}/api/auth/reclaim_local`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ username, password, public_id: bizId, business_name }),
          })
          if (!res.ok) {
            const e = await res.json().catch(() => ({}))
            throw new Error(e.detail || 'An account with this username already exists on this device and could not be reset.')
          }
          localData = await res.json()
          didReclaim = true
        } else {
          throw err
        }
      }
      // Only seed the template on a FRESH local account — a reclaimed orphan may
      // already have its starter data, and re-seeding would duplicate it.
      if (!didReclaim) {
        await _applyTemplate(LOCAL_URL, localData.token || localData.access_token, template_key)
      }
      logger.info(`[SIGNUP] Cloud-issued BizID ${bizId} ${didReclaim ? 'reclaimed onto' : 'mirrored to'} local. Logged in locally.`)
      _saveSession(localData)

      // ── Automate the hosting choice made at signup — NO separate onboarding
      //    and NO migration. A brand-new account has no data to move, so:
      //      • 'local'          → stay offline-only on the local backend.
      //      • 'hybrid' (Local + Cloud) → keep the fast local backend AND turn on
      //        background cloud sync: persist the mode on the local DB (so the
      //        sync worker engages) and provision the cloud sync token from the
      //        credentials we already have. The local JWT stays valid (hybrid
      //        still talks to the local backend), so there's nothing to re-login.
      try {
        const localTok = localData.token || localData.access_token
        if (hosting === 'hybrid') {
          updateApiBase('hybrid')
          await fetch(`${LOCAL_URL}/settings`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${localTok}` },
            body: JSON.stringify({ general: { hosting_mode: 'hybrid' } }),
          }).catch(() => { /* self-heals on next settings fetch */ })
          // Mint the cloud sync token (best-effort). _provisionCloudSyncToken also
          // stamps hosting_mode=hybrid on the cloud record when the device is on
          // Local + Cloud, so the Admin Console reflects it. Never blocks signup.
          _provisionCloudSyncToken(username, password, localTok)
        } else {
          updateApiBase('local')
        }
      } catch (e) {
        logger.warn('[SIGNUP] Hosting auto-setup skipped (works, sync self-heals on next login):', e?.message)
      }
      return
    }

    // Web: register on the cloud backend (API_BASE = cloud here).
    const data = await _doSignup(API_BASE, { username, password, business_name, phone })
    await _applyTemplate(API_BASE, data.token || data.access_token, template_key)
    logger.info('Signup successful (web/cloud) for user:', data.username)
    _saveSession(data)
  }, [_saveSession, _applyTemplate, _doSignup, _provisionCloudSyncToken])

  const logout = useCallback(() => {
    logger.info('Logging out user, clearing local session token.')
    
    // Hidden cross-origin iframe to trigger AI dashboard logout synchronously
    try {
      const { hostname, port } = window.location
      const aiUrl = import.meta.env.VITE_AI_DASHBOARD_URL || 
        (port === '8450' ? `http://${hostname}:8451` : `http://${hostname}:5173`)
        
      const iframe = document.createElement('iframe')
      iframe.style.display = 'none'
      iframe.src = `${aiUrl}/?logout=true`
      document.body.appendChild(iframe)
      setTimeout(() => iframe.remove(), 2000)
    } catch (e) {
      // Ignore if iframe fails
    }

    localStorage.removeItem('billing_token')
    localStorage.removeItem('billing_user')
    localStorage.removeItem('bizassist_cloud_token')
    localStorage.removeItem('bizassist_user_home_mode')  // clear home mode — next user gets their own
    setToken(null)
    setUser(null)
    setAppReady(false)
    setBizId(null)   // stop tagging logs with the signed-out business
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
    // 1. Save the new mode to the CURRENT backend before switching.
    //    Backend exposes PUT /settings (a merge-patch); there is no PATCH route,
    //    so PATCH returned 405 and the mode was never persisted to the DB —
    //    which meant the sync worker (reads general.hosting_mode from the DB)
    //    never engaged hybrid. Use PUT to match the rest of the app.
    try {
      const res = await fetch(`${API_BASE}/settings`, {
        method: 'PUT',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({ general: { hosting_mode: newMode } }),
      })
      // Pro-gate: the backend refuses to enable hybrid/cloud on a free plan (402).
      // Abort the switch and tell the user — do NOT flip mode, log out, or migrate.
      if (res.status === 402) {
        let detail = 'Local + Cloud requires the Pro plan. Contact your provider to upgrade.'
        try { detail = (await res.json()).detail || detail } catch { /* keep default */ }
        window.dispatchEvent(new CustomEvent('show_toast', { detail: { type: 'error', msg: detail } }))
        logger.info('[MODE SWITCH] Blocked — Pro plan required')
        return false
      }
      if (!res.ok) logger.warn(`[MODE SWITCH] Save mode returned HTTP ${res.status}`)
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
    const modeLabel = { local: 'Local', hybrid: 'Local + Cloud', cloud: 'Cloud' }[newMode] || newMode
    window.dispatchEvent(new CustomEvent('show_toast', {
      detail: { type: 'info', msg: `Switched to ${modeLabel}. Please log in again.` }
    }))
    logger.info(`[MODE SWITCH] Done. API_BASE is now: ${API_BASE}`)
  }, [token])

  /**
   * setHostingMode — flip between Local and Local+Cloud (hybrid) WITHOUT a logout.
   *
   * Both modes talk to the SAME local backend (hybrid just adds a background
   * push to the cloud), so the local-signed JWT stays valid and there is no id
   * mismatch — unlike the old pure-cloud switch, nothing here requires a
   * re-login or a data migration. Turning Local+Cloud ON still needs a cloud
   * token (minted from the password at login); enabling it for an already
   * signed-in user is therefore driven through the guarded re-login path
   * (switchMode) so the sync worker gets its token. Turning it OFF (→ local) or
   * confirming a mode is a pure, instant, non-destructive preference change.
   */
  const setHostingMode = useCallback(async (newMode) => {
    logger.info(`[MODE] Setting hosting mode to "${newMode}" (no logout — same local backend)`)
    try {
      const res = await fetch(`${API_BASE}/settings`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
        body: JSON.stringify({ general: { hosting_mode: newMode } }),
      })
      // Pro-gate: enabling hybrid on a free plan is refused (402). Abort and tell
      // the user instead of falsely toasting "Local + Cloud enabled". Switching
      // back to 'local' is never gated, so this only trips when turning cloud ON.
      if (res.status === 402) {
        let detail = 'Local + Cloud requires the Pro plan. Contact your provider to upgrade.'
        try { detail = (await res.json()).detail || detail } catch { /* keep default */ }
        window.dispatchEvent(new CustomEvent('show_toast', { detail: { type: 'error', msg: detail } }))
        logger.info('[MODE] Hybrid blocked — Pro plan required')
        return false
      }
      if (!res.ok) logger.warn(`[MODE] Save mode returned HTTP ${res.status}`)
    } catch (err) {
      logger.warn('[MODE] Could not save mode to backend (continuing anyway):', err)
    }
    updateApiBase(newMode)
    window.dispatchEvent(new CustomEvent('refresh-settings'))
    window.dispatchEvent(new CustomEvent('show_toast', {
      detail: {
        type: 'success',
        msg: newMode === 'local'
          ? 'Switched to Local. Cloud sync is paused — billing stays fast and offline.'
          : 'Local + Cloud enabled. Your data now syncs to the cloud in the background.',
      },
    }))
    logger.info(`[MODE] Done. API_BASE is now: ${API_BASE}`)
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
      if (res.status === 404) {
        logger.warn('[AUTH] Restored session user not found on active backend. Auto-logging out.')
        logout()
        return
      }
      if (res.ok) {
        const data = await res.json()
        setProfile(data)
      }
    } catch (err) {
      logger.error('Failed to fetch profile:', err)
    }
  }, [token, logout])

  const [settings, setSettings] = useState(null)

  const fetchSettings = useCallback(async () => {
    if (!token) return
    try {
      const res = await fetch(`${API_BASE}/settings`, {
        headers: {
          Authorization: `Bearer ${token}`
        }
      })
      if (res.status === 404) {
        logger.warn('[AUTH] Restored session settings user not found on active backend. Auto-logging out.')
        logout()
        return
      }
      if (res.ok) {
        const data = await res.json()
        // (§9.3a/b) Reconcile the account's saved `general.hosting_mode` to the
        // REAL mode so it can't drift. A stale value (e.g. 'local' persisted on
        // the account from an earlier desktop switch) otherwise mis-tags cloud
        // invoices with `LCL-` (getCounterPrefix reads this) and previously also
        // disabled realtime. The real mode: web is ALWAYS cloud; a desktop app
        // uses its own per-device choice (`bizassist_hosting_mode`).
        const realMode = !IS_LOCAL_APP
          ? 'cloud'
          : ((typeof localStorage !== 'undefined' && localStorage.getItem('bizassist_hosting_mode'))
              || data?.general?.hosting_mode || 'local')
        if (data?.general && data.general.hosting_mode !== realMode) {
          logger.info(`[AUTH] Reconciling saved hosting_mode '${data.general.hosting_mode}' → real '${realMode}'`)
          data.general.hosting_mode = realMode
          setSettings(data)
          // Persist the correction (best-effort; general is owner+cashier-writable).
          fetch(`${API_BASE}/settings`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
            body: JSON.stringify({ general: { hosting_mode: realMode } }),
          }).catch(err => logger.warn('[AUTH] hosting_mode reconcile PUT failed (non-blocking):', err))
        } else {
          setSettings(data)
        }
        logger.info('Loaded app settings successfully in context')
        // NOTE: We do NOT call updateApiBase here.
        // The user's home mode (bizassist_user_home_mode) is the source of truth
        // for which backend to hit. Overriding it from settings would cause
        // wrong-backend routing after a mode switch + re-login.
      }
    } catch (err) {
      logger.error('Failed to fetch settings in context:', err)
    }
  }, [token, logout])

  const fetchBusinessConfig = useCallback(async () => {
    if (!token) return
    try {
      const res = await fetch(`${API_BASE}/business/config`, {
        headers: {
          Authorization: `Bearer ${token}`
        }
      })
      if (res.status === 404) {
        logger.warn('[AUTH] Restored session business config user not found on active backend. Auto-logging out.')
        logout()
        return
      }
      if (res.ok) {
        const data = await res.json()
        setBusinessConfig(data.config)
        setAttributesSchema(data.attributes_schema || [])
        logger.info('Loaded business config successfully')
      }
    } catch (err) {
      logger.error('Failed to fetch business config:', err)
    }
  }, [token, logout])

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

  useEffect(() => {
    const handleUnauthorized = () => {
      logger.warn('[AuthContext] auth_unauthorized event triggered. Auto-logging out.')
      logout()
      window.dispatchEvent(new CustomEvent('show_toast', {
        detail: { type: 'error', msg: 'Session expired. Please log in again.' }
      }))
    }
    window.addEventListener('auth_unauthorized', handleUnauthorized)
    return () => {
      window.removeEventListener('auth_unauthorized', handleUnauthorized)
    }
  }, [logout])

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
      user, token, loading, login, staffLogin, logout, signup, switchMode, setHostingMode, authFetch, profile, fetchProfile, setProfile,
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
