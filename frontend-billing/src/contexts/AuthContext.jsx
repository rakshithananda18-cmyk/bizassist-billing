import React, { useContext, useState, useEffect, useCallback, useRef } from 'react'
import { authContext as AuthContext } from './contextIdentity'
import {
  API_BASE,
  updateApiBase,
  IS_LOCAL_APP,
  CLOUD_URL,
  LOCAL_URL,
  FALLBACK_CLOUD_URL,
  getActiveCloudUrl,
  switchActiveCloudUrl,
  getAlternateCloudUrl,
} from '../config'
import { resolveHostingMode, shouldPersistMode } from '../utils/resolveHostingMode'
import { logger, setBizId } from '../utils/logger'
import { reconcileBizIdOnLogin } from '../utils/loginSync'
import { isUpgradeToPro } from '../utils/planTransition'
import { discoverLocalBackend, getNetworkMode, clearDiscoveryCache } from '../utils/networkDiscovery'
import { reconcileDeviceModeOnLogin, getHostingPreference, setHostingPreference } from '../utils/deviceMode'
import { syncManager } from '../sync/syncManager'
import { tokenStorage } from '../utils/tokenStorage'
import { clearBillingProfileCache } from '../hooks/useBillingProfile'
import { notifyAiLogout, getAiDashboardUrl } from '../config/aiDashboard'
import { sessionFetch, resilientSessionFetch, invalidateSessionRefresh } from '../api/session'
import { readableError } from '../api/httpErrors'
import { useSessionRefresh } from '../hooks/useSessionRefresh'
import {
  isAuthEntryPath,
  isDemoRequested,
  activateDemoSession,
  clearDemoSession,
  handleDemoRequest,
  DEMO_USER,
  DEMO_TOKEN,
  DEMO_SETTINGS,
} from '../demo/demoEngine'

const AUTH_REQUEST_TIMEOUT_MS = 8000
export const WEB_AUTH_BUDGET_MS = 65000
function clearPreviewTimers() {
  try {
    for (const key of Object.keys(sessionStorage)) if (key.startsWith('bizassist_preview_start:') || key === 'bizassist_session_start_time') sessionStorage.removeItem(key)
  } catch { /* unavailable storage */ }
}

// Authentication is a security boundary, but it must also have a bounded wait.
// An unavailable local service used to leave the login screen spinning forever.
const authFetchWithTimeout = async (url, options, timeoutMs = AUTH_REQUEST_TIMEOUT_MS) => {
  if (typeof AbortController === 'undefined') return fetch(url, options)

  const controller = new AbortController()
  const timeout = setTimeout(() => controller.abort(), timeoutMs)
  try {
    return await fetch(url, { ...options, signal: controller.signal })
  } catch (err) {
    if (controller.signal.aborted || err?.name === 'AbortError') {
      const timeoutError = new Error(`Request timed out after ${Math.ceil(timeoutMs / 1000)} seconds.`)
      timeoutError.code = 'AUTH_REQUEST_TIMEOUT'
      throw timeoutError
    }
    throw err
  } finally {
    clearTimeout(timeout)
  }
}

/**
 * Dual-Cloud Active Failover:
 * Transparently retries requests against the backup cloud endpoint
 * (Cloud Run Mumbai <-> Hugging Face Spaces) if the current cloud endpoint
 * experiences a timeout, network failure, or HTTP 502/503/504 gateway outage.
 */
const authFetchWithFailover = async (url, options, timeoutMs = IS_LOCAL_APP ? AUTH_REQUEST_TIMEOUT_MS : WEB_AUTH_BUDGET_MS) => {
  const currentCloud = (typeof getActiveCloudUrl === 'function' ? getActiveCloudUrl() : CLOUD_URL) || CLOUD_URL
  const altCloud = (typeof getAlternateCloudUrl === 'function' ? getAlternateCloudUrl() : FALLBACK_CLOUD_URL) || FALLBACK_CLOUD_URL
  const canFailover = !IS_LOCAL_APP || (typeof url === 'string' && (url.includes('run.app') || url.includes('hf.space')))

  try {
    const res = await authFetchWithTimeout(url, options, timeoutMs)
    if (res.status >= 502 && res.status <= 504 && canFailover && altCloud && altCloud !== currentCloud) {
      logger.warn(`[FAILOVER] Primary cloud returned HTTP ${res.status}. Attempting backup backend...`)
      throw new Error(`Server returned HTTP ${res.status}`)
    }
    return res
  } catch (primaryErr) {
    if (!canFailover || !altCloud || altCloud === currentCloud) {
      throw primaryErr
    }

    let fallbackUrl = url
    if (typeof url === 'string' && currentCloud && url.startsWith(currentCloud)) {
      fallbackUrl = url.replace(currentCloud, altCloud)
    } else if (typeof url === 'string' && (url.includes('run.app') || url.includes('hf.space'))) {
      try {
        const parsed = new URL(url)
        fallbackUrl = `${altCloud}${parsed.pathname}${parsed.search}`
      } catch {
        throw primaryErr
      }
    } else {
      throw primaryErr
    }

    logger.warn(`[FAILOVER] Primary endpoint unreachable (${primaryErr.message}). Retrying on fallback: ${fallbackUrl}...`)
    try {
      const fallbackRes = await authFetchWithTimeout(fallbackUrl, options, timeoutMs)
      if (fallbackRes.ok || fallbackRes.status < 500) {
        if (typeof switchActiveCloudUrl === 'function') {
          switchActiveCloudUrl(altCloud)
        }
        logger.info(`[FAILOVER] Active cloud seamlessly switched to: ${altCloud}`)
        return fallbackRes
      }
      return fallbackRes
    } catch (fallbackErr) {
      logger.error(`[FAILOVER] Both primary and fallback backends failed.`, {
        primary: primaryErr.message,
        fallback: fallbackErr.message,
      })
      throw primaryErr
    }
  }
}

// Decode token payload (base64) client-side to read user_id / public_id without network

const isCloudEndpoint = (u) =>
  typeof u === 'string' &&
  (u.includes('run.app') || u.includes('hf.space') || u === CLOUD_URL || u === FALLBACK_CLOUD_URL)

const isSameBackendOrCloudFailover = (a, b) =>
  a === b || (isCloudEndpoint(a) && isCloudEndpoint(b))

function decodeToken(tok) {
  if (!tok) return null
  try {
    const parts = tok.split('.')
    if (parts.length < 2) return null
    const payload = JSON.parse(atob(parts[1]))
    return payload
  } catch {
    return null
  }
}

function syncScopeFor(user) {
  const bizId = user?.public_id
  const userId = user?.user_id
  return bizId && userId ? `biz:${bizId}|user:${userId}` : null
}

export function AuthProvider({ children }) {
  const authGeneration = useRef(0)
  const modeGeneration = useRef(0)
  const modeChangePending = useRef(false)
  const modeWrites = useRef(Promise.resolve())
  // An explicit Local save must land after any automatic Pro-mode save that
  // was already in flight. Otherwise a late login request can turn sync back on.
  const saveHostingMode = useCallback((backend, sessionToken, mode) => {
    const generation = authGeneration.current
    const save = modeWrites.current.catch(() => {}).then(() => {
      if (generation !== authGeneration.current || tokenStorage.getItem('billing_token') !== sessionToken) return null
      return authFetchWithTimeout(`${backend}/settings`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${sessionToken}` },
        body: JSON.stringify({ general: { hosting_mode: mode } }),
      })
    })
    modeWrites.current = save.catch(() => {})
    return save
  }, [])
  const reportedLoadErrors = useRef(new Set())
  const reportLoadError = async (response, path) => {
    if (response.ok) { reportedLoadErrors.current.delete(path); return }
    if (reportedLoadErrors.current.has(path) || [401, 403].includes(response.status)) return
    reportedLoadErrors.current.add(path)
    const message = readableError(response.status, response.headers?.get?.('content-type'), await response.clone().text())
    window.dispatchEvent(new CustomEvent('show_toast', { detail: { type: 'warning', msg: message } }))
  }
  const demoReq = isDemoRequested()
  const [user, setUser]   = useState(() => demoReq ? DEMO_USER : null)
  const [token, setToken] = useState(() => demoReq ? DEMO_TOKEN : (tokenStorage.getItem('billing_token') || null))
  const [loading, setLoading] = useState(() => !demoReq)
  const [isDemoMode, setIsDemoMode] = useState(() => demoReq)
  const demoSessionRef = useRef(demoReq)
  demoSessionRef.current = Boolean(isDemoMode || user?.is_demo || token === DEMO_TOKEN)
  const [businessConfig, setBusinessConfig] = useState(() => demoReq ? { demo: true } : null)
  const [attributesSchema, setAttributesSchema] = useState([])
  const [appReady, setAppReady] = useState(() => isDemoRequested())
  // 'local' — connected to owner's backend on same LAN (fast, offline capable)
  // 'cloud' — connected via cloud (different network or cloud-only mode)
  const [networkMode, setNetworkMode] = useState(() => getNetworkMode())


  // Restore session from localStorage/tokenStorage on mount
  useEffect(() => {
    try {
      // A visitor who follows the marketing tour's sign-in/trial links must
      // enter real authentication, even when this tab previously ran a demo.
      if (isAuthEntryPath(window.location.pathname)) clearDemoSession()
      if (isDemoRequested()) {
        activateDemoSession()
        setUser(DEMO_USER)
        setToken(DEMO_TOKEN)
        setIsDemoMode(true)
        setBizId(DEMO_USER.public_id)
        setSettings(DEMO_SETTINGS)
        setAppReady(true)
        setLoading(false)
        logger.info('[DEMO] Activated instant real app demo unit session.')
        return
      }

      const savedUser = localStorage.getItem('billing_user')
      const savedToken = tokenStorage.getItem('billing_token')
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
        const restoredScope = syncScopeFor(userObj)
        if (restoredScope) syncManager.setScope(restoredScope)
        else syncManager.clearScope()
        setBizId(userObj.public_id)   // restore [BizId=…] logging context
        logger.info('Session restored successfully for user from tokenStorage')
      } else {
        logger.debug('No saved session user found.')
      }
    } catch (err) {
      logger.error('Failed to restore billing session:', err)
    }
    setLoading(false)
  }, [])

  const _saveSession = useCallback((data) => {
    authGeneration.current++
    invalidateSessionRefresh()
    reportedLoadErrors.current.clear()
    clearPreviewTimers()
    setSettings(null)
    const savedGeneration = authGeneration.current
    setProfile(null)
    syncManager.clearScope()
    clearBillingProfileCache()
    const tok = data.token || data.access_token
    tokenStorage.setItem('billing_token', tok)

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

    // ── Per-account device-mode guard ────────────────────────────────────────
    // `bizassist_hosting_mode` is device-global. If a DIFFERENT account logs in
    // (e.g. free user first, then the Pro owner), the previous account's stale
    // mode (usually 'local') must not override the incoming account's saved
    // hosting_mode — it hid the sidebar sync/refresh panel for Pro users and
    // the fetchSettings reconcile then PUT the stale mode onto their account.
    // 'cloud' is preserved (device routing; see utils/deviceMode.js).
    const clearedMode = reconcileDeviceModeOnLogin(userObj.public_id || userObj.username || userObj.id)
    if (clearedMode) {
      logger.info(`[AUTH] Account switch — dropped previous account's device hosting mode '${clearedMode}'; this account's saved hosting_mode now applies.`)
    }

    setToken(tok)
    setUser(userObj)
    const sessionScope = syncScopeFor(userObj)
    if (sessionScope) {
      syncManager.setScope(sessionScope)
    } else {
      syncManager.clearScope()
      logger.warn('[SYNC] Offline queue disabled until a stable BizID and user ID are available.')
    }
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

    // LAN discovery (non-blocking, cloud URL only): check if the owner's local
    // backend is reachable on the same WiFi/LAN. If so, switch API_BASE to the
    // local URL for lower latency and offline capability.
    // This doesn't block login — it runs in the background after session is saved.
    const bizId = userObj.public_id || String(userObj.id)
    discoverLocalBackend(bizId).then(localUrl => {
      if (savedGeneration !== authGeneration.current) return
      if (localUrl) {
        // Same LAN — switch to local backend for all subsequent requests
        try {
          localStorage.setItem('bizassist_use_lan_db', 'true')
          localStorage.setItem('bizassist_local_backend_url', localUrl)
          updateApiBase(getNetworkMode())
        } catch { /* ignore */ }
        setNetworkMode('local')
        logger.info(`[AUTH] Same-network local backend detected: ${localUrl} — switching API_BASE`)
      } else {
        setNetworkMode('cloud')
      }
    }).catch(err => {
      logger.debug('[AUTH] LAN discovery failed:', err?.message)
      setNetworkMode('cloud')
    })
  }, [setNetworkMode])



  /**
   * Standard device provisioning (no shared secrets): with the credentials the
   * user just typed, obtain a CLOUD-issued 24 h token scoped to this business
   * and hand it to the local backend for the hybrid sync worker
   * (POST /api/sync/cloud-token). Best-effort — never blocks or fails login.
   */
  const _provisionCloudSyncToken = useCallback(async (username, password, localToken, cloudToken = null) => {
    if (!IS_LOCAL_APP || !localToken) return null
    if (getHostingPreference() === 'local') return null
    if (typeof navigator !== 'undefined' && navigator.onLine === false) return null
    const generation = authGeneration.current
    const current = () => generation === authGeneration.current && tokenStorage.getItem('billing_token') === localToken && getHostingPreference() !== 'local'
    try {
      if (!current()) return null
      let token = cloudToken
      if (!token) {
        const res = await authFetchWithTimeout(`${CLOUD_URL}/login`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ username, password }),
        })
        if (!res.ok) return null
        token = (await res.json())?.token
      }
      if (!token) return null
      if (!current()) return null
      const provisioned = await authFetchWithTimeout(`${LOCAL_URL}/api/sync/cloud-token`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${localToken}` },
        body: JSON.stringify({ token }),
      })
      if (!provisioned.ok || !current()) return null
      localStorage.setItem('bizassist_cloud_token', token)
      logger.info('[SYNC] Cloud sync token provisioned (24h, business-scoped)')
      window.dispatchEvent(new CustomEvent('refresh-settings'))
      // Keep the CLOUD record's hosting_mode in step with this device when it's
      // on Local + Cloud, so the Admin Console shows "Local + Cloud" (the sync
      // worker moves business data, not the settings JSON). Runs for BOTH paths
      // that mint a cloud token — signup and the Settings switch → re-login.
      // Best-effort and informational; never affects the token result.
      try {
        const mode = (typeof localStorage !== 'undefined' && localStorage.getItem('bizassist_hosting_mode')) || 'local'
        if (mode === 'hybrid') {
          void authFetchWithTimeout(`${CLOUD_URL}/settings`, {
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

  const _startVerifiedSync = useCallback((localToken, cloudToken, {
    generation = authGeneration.current,
    modeEpoch = modeGeneration.current,
    source = 'login',
  } = {}) => {
    const backend = API_BASE
    const current = () => generation === authGeneration.current
      && modeEpoch === modeGeneration.current && !modeChangePending.current
      && tokenStorage.getItem('billing_token') === localToken && API_BASE === backend
    return reconcileBizIdOnLogin(localToken, cloudToken, {
      source, isCurrent: current,
      runModeWrite: operation => {
        const write = modeWrites.current.catch(() => {}).then(() => current() ? operation() : null)
        modeWrites.current = write.catch(() => {})
        return write
      },
    })
  }, [])

  const _prepareLoginSync = useCallback((username, password, localToken, cloudToken = null, source = 'login') => {
    // Capture before provisioning: a delayed cloud reply from an earlier login
    // must not activate sync for a later account or override Local-only.
    const fence = { generation: authGeneration.current, modeEpoch: modeGeneration.current, source }
    return _provisionCloudSyncToken(username, password, localToken, cloudToken)
      .then(provisioned => _startVerifiedSync(localToken, provisioned, fence))
  }, [_provisionCloudSyncToken, _startVerifiedSync])

  const login = useCallback(async (username, password) => {
    logger.info('Attempting login for username:', username)

    // 1. Try the platform's primary backend (local on the downloaded app).
    let res
    try {
      res = await authFetchWithFailover(`${API_BASE}/login`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username, password }),
      })
    } catch (err) {
      if (err?.code === 'AUTH_REQUEST_TIMEOUT') {
        if (!IS_LOCAL_APP) throw new Error('The server did not respond. Check your connection and try again.')
        throw new Error('The local billing service is not responding. Wait a moment, then restart Stater if it persists.')
      }
      throw err
    }
    if (res.ok) {
      const data = await res.json()
      logger.info('Login successful for user:', data.username, 'role:', data.role)
      _saveSession(data)
      // Fire-and-forget: provision the cloud sync token first, then run the
      // BizID identity check WITH that cloud token. Never send a locally
      // signed JWT to the cloud — its JWT_SECRET differs on packaged installs,
      // so the cloud would (correctly) reject it with 401 "Invalid token".
      _prepareLoginSync(username, password, data.token || data.access_token)
      return
    }

    // 2. FRESH-DEVICE recovery (downloaded app, online).  Do not preflight a
    // username: a public existence endpoint is an account-enumeration oracle.
    // Instead, prove the password with Cloud first, then ask the local service
    // to reconcile or create the mirror. Those mutations require the verified
    // credentials and matching BizID, so they do not disclose local accounts.
    if (IS_LOCAL_APP) {
      if (typeof navigator !== 'undefined' && navigator.onLine === false) {
        throw new Error('This account isn’t set up on this device yet. Connect to the internet once to set it up, then it works offline.')
      }
      try {
        const cloudRes = await fetch(`${CLOUD_URL}/login`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ username, password }),
        })
        if (cloudRes.ok) {
          const cloudData = await cloudRes.json()
          // If this device already holds the same business, update its local
          // password and retry. A 404 merely means this is a fresh device.
          const reconcileRes = await fetch(`${LOCAL_URL}/api/auth/reconcile_password`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ username, password, public_id: cloudData.public_id }),
          })
          if (reconcileRes.ok) {
            const retryRes = await fetch(`${API_BASE}/login`, {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ username, password }),
            })
            if (retryRes.ok) {
              const retryData = await retryRes.json()
              logger.info('[LOGIN] Local password reconciled with cloud and login successful.')
              _saveSession(retryData)
              _prepareLoginSync(username, password, retryData.token || retryData.access_token, cloudData.token)
              return
            }
          } else {
            const recErr = await reconcileRes.json().catch(() => ({}))
            if (recErr.detail && recErr.detail.includes('Identity mismatch')) {
              const reclaimRes = await fetch(`${LOCAL_URL}/api/auth/reclaim_local`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                  username,
                  password,
                  public_id: cloudData.public_id,
                  business_name: cloudData.business_name,
                }),
              })
              if (reclaimRes.ok) {
                const reclaimData = await reclaimRes.json()
                logger.info('[LOGIN] Orphan reclaimed onto new cloud BizID — logged in locally.')
                _saveSession(reclaimData)
                _prepareLoginSync(username, password, reclaimData.token || reclaimData.access_token, cloudData.token)
                return
              }
              const reclaimErr = await reclaimRes.json().catch(() => ({}))
              throw new Error(reclaimErr.detail || recErr.detail)
            }
          }

          // No verified local owner exists, so create an identity-only mirror.
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
            logger.info(`[LOGIN] Fresh device — local mirror created (BizID ${cloudData.public_id}); preparing background cloud restore.`)
            _saveSession(localData)
            // Provision first, then verify and schedule the durable worker. No
            // popup races a missing cloud token on a fresh installation.
            _prepareLoginSync(username, password, localData.token || localData.access_token, cloudData.token, 'device-restore')
            return
          }
          logger.error(`[LOGIN] Cloud login ok but local mirror failed: HTTP ${mirror.status}`)
          throw new Error('Signed in, but could not set up this device. Please try again.')
        }
        // Cloud login also failed → fall through to surface the local error.
      } catch (err) {
        logger.warn('[LOGIN-RECOVERY] Cloud-verified device recovery failed:', err?.message)
      }
    }

    // 3. No fallback applied → surface the original error.
    const err = await res.json().catch(() => ({}))
    logger.error('Login request failed with status:', res.status, err.detail)
    throw new Error([400, 401, 403].includes(res.status) ? 'Wrong username or password.' : readableError(res.status, res.headers?.get?.('content-type'), err))
  }, [_saveSession, _prepareLoginSync])

  // Staff login (§9.5): staff never use a global username — authenticate scoped to
  // the business owner (owner username + per-business counter/staff name + password).
  const staffLogin = useCallback(async (ownerUsername, staffLoginName, password) => {
    logger.info('Attempting staff login under owner:', ownerUsername, 'as', staffLoginName)
    const body = JSON.stringify({ owner_username: ownerUsername, staff_login_name: staffLoginName, password })

    // 1. Try the platform's primary backend (local on the desktop app).
    let res
    try {
      res = await authFetchWithFailover(`${API_BASE}/login/staff`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body,
      })
    } catch (err) {
      if (err?.code === 'AUTH_REQUEST_TIMEOUT') {
        if (!IS_LOCAL_APP) throw new Error('The server did not respond. Check your connection and try again.')
        throw new Error('The local billing service is not responding. Wait a moment, then restart Stater if it persists.')
      }
      throw err
    }
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
    throw new Error([400, 401, 403].includes(res.status) ? 'Wrong username or password.' : readableError(res.status, res.headers?.get?.('content-type'), err))
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
    const requestId = globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random()}`
    const send = () => authFetchWithFailover(`${base}/signup`, {
      method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Client-Request-Id': requestId }, body: JSON.stringify(body),
    })
    let res
    try { res = await send() }
    catch (error) {
      // A timeout can occur after the account committed. Recover it with proof
      // of the same credentials before making another signup attempt.
      const recovered = await authFetchWithFailover(`${base}/login`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ username: body.username, password: body.password }),
      })
      if (recovered.ok) return recovered.json()
      if (recovered.status === 401) res = await send()
      else throw new Error(readableError(recovered.status, recovered.headers?.get?.('content-type'), await recovered.text()))
    }
    if (!res.ok) {
      const e = new Error(readableError(res.status, res.headers?.get?.('content-type'), await res.text()))
      e.status = res.status
      throw e
    }
    return res.json()
  }, [])

  const signup = useCallback(async ({ username, password, business_name, template_key, hosting = 'local', phone = null, email = null }) => {
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
        cloudData = await _doSignup(CLOUD_URL, { username, password, business_name, phone, email })
      } catch (err) {
        if (err.status === 400 && /username|already (?:exists|registered|taken)/i.test(err.message)) {
          // Username already taken on the cloud — most likely the same person.
          throw new Error('An account with this username already exists. Please log in instead.')
        }
        throw err
      }
      const bizId = cloudData.public_id
      // Local + Cloud is a Pro feature, so it needs the Pro trial the cloud just
      // granted (or not: one trial per phone, or trials switched off). A cloud
      // that reports `trial` decides; an older one sends nothing and the choice
      // stands. Without the trial the business is set up Local instead, and the
      // caller says so (Register.jsx).
      const trialKnown = !!cloudData && Object.prototype.hasOwnProperty.call(cloudData, 'trial')
      const fellBackToLocal = hosting === 'hybrid' && trialKnown && !cloudData.trial
      const effectiveHosting = fellBackToLocal ? 'local' : hosting

      // 2. Mirror locally with the SAME BizID, then log in locally (local-first).
      //    Seed the template ONLY on local (the working copy); the cloud receives
      //    this data later via backup/push, so seeding it on cloud too would
      //    create duplicate starter data.
      let localData
      let didReclaim = false
      try {
        localData = await _doSignup(LOCAL_URL, { username, password, business_name, public_id: bizId, phone, email })
      } catch (err) {
        // Local orphan: the cloud accepted this username (so its old cloud account
        // was deleted → username free on the cloud), but a stale LOCAL mirror still
        // holds it → the local /signup 400s. Re-key that orphan to the new BizID
        // instead of failing — the backend verifies the new cloud identity and
        // purges stale data before rekeying this retired local business.
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

      // Only a choice the owner actually made is an opt-out. A fallback caused
      // by missing trial eligibility must auto-enable sync on a later upgrade.
      if (!fellBackToLocal) setHostingPreference(bizId, effectiveHosting)

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
        if (effectiveHosting === 'hybrid') {
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
      if (fellBackToLocal) logger.info('[SIGNUP] No Pro trial for this business - set up Local instead of Local + Cloud.')
      return { hosting: effectiveHosting, fellBackToLocal, trial: cloudData.trial || null }
    }

    // Web: register on the cloud backend (API_BASE = cloud here).
    const data = await _doSignup(API_BASE, { username, password, business_name, phone, email })
    await _applyTemplate(API_BASE, data.token || data.access_token, template_key)
    logger.info('Signup successful (web/cloud) for user:', data.username)
    _saveSession(data)
    return { hosting: 'cloud', trial: data.trial || null,
      trialUnavailable: Object.prototype.hasOwnProperty.call(data, 'trial') && !data.trial }
  }, [_saveSession, _applyTemplate, _doSignup, _provisionCloudSyncToken])

  const logout = useCallback(async (announce = true) => {
    // A demo can run beside an owner's saved session. Leaving the sample store
    // must never revoke that token, erase its credentials, or sign out its tabs.
    if (demoSessionRef.current || isDemoRequested()) {
      authGeneration.current++
      reportedLoadErrors.current.clear()
      clearDemoSession()
      demoSessionRef.current = false
      try {
        const url = new URL(window.location.href)
        url.searchParams.delete('demo')
        url.searchParams.delete('embed')
        url.searchParams.delete('tour')
        if (url.pathname.startsWith('/demo')) url.pathname = '/login'
        window.history.replaceState(window.history.state, '', url.pathname + url.search + url.hash)
      } catch { /* session state still exits when browser history is unavailable */ }
      clearBillingProfileCache()
      setIsDemoMode(false)
      setToken(null)
      setUser(null)
      setSettings(null)
      setProfile(null)
      setBusinessConfig(null)
      setAttributesSchema([])
      setAppReady(false)
      setBizId(null)
      return
    }
    authGeneration.current++
    invalidateSessionRefresh()
    reportedLoadErrors.current.clear()
    clearPreviewTimers()
    notifyAiLogout()
    const outgoingToken = tokenStorage.getItem('billing_token')
    if (announce === true && outgoingToken) {
      const controller = new AbortController()
      const timeout = setTimeout(() => controller.abort(), 3000)
      try {
        await Promise.race([
          fetch(`${API_BASE}/auth/logout`, { method: 'POST', headers: { Authorization: `Bearer ${outgoingToken}` }, keepalive: true, signal: controller.signal }),
          new Promise(resolve => setTimeout(resolve, 3000)),
        ])
      } catch { /* local logout remains available offline */ }
      finally { clearTimeout(timeout) }
      // A new login while the old logout was pending owns the session now.
      if (tokenStorage.getItem('billing_token') !== outgoingToken) return
    }
    logger.info('Logging out user, clearing local session token.')

    // Clear billing profile cache so next user does not inherit prior business profile (WEB-07)
    try {
      clearBillingProfileCache()
    } catch (e) {
      // Ignore
    }

    // Broadcast logout to all tabs/windows (e.g. open AI tab, WEB-05)
    if (announce === true && typeof BroadcastChannel !== 'undefined') {
      try {
        const bc = new BroadcastChannel('bizassist_auth_channel')
        bc.postMessage({ type: 'LOGOUT' })
        bc.close()
      } catch (e) {
        // Ignore
      }
    }

    // Hidden cross-origin iframe to trigger AI dashboard logout synchronously
    try {
      const aiUrl = getAiDashboardUrl()

      const iframe = document.createElement('iframe')
      iframe.style.display = 'none'
      iframe.src = `${aiUrl}/?logout=true`
      document.body.appendChild(iframe)
      setTimeout(() => iframe.remove(), 2000)
    } catch (e) {
      // Ignore if iframe fails
    }

    tokenStorage.removeItem('billing_token')
    localStorage.removeItem('billing_user')
    tokenStorage.removeItem('bizassist_cloud_token')
    clearDemoSession()
    setIsDemoMode(false)
    syncManager.clearScope()
    localStorage.removeItem('bizassist_user_home_mode')  // clear home mode — next user gets their own
    localStorage.removeItem('pos_upi_vpa')  // clear device payment handle so next business doesn't inherit it
    setToken(null)
    setUser(null)
    setSettings(null)
    setProfile(null)
    setAppReady(false)
    setBizId(null)   // stop tagging logs with the signed-out business
  }, [])

  useEffect(() => {
    if (isDemoMode || user?.is_demo || token === DEMO_TOKEN) return
    const changed = event => {
      if (token && (event.key === 'billing_token' || event.key === 'billing_user') && !event.newValue) logout(false)
      else if (event.key === 'billing_token' && event.newValue) {
        try {
          const saved = JSON.parse(localStorage.getItem('billing_user') || 'null')
          if (saved?.public_id && saved.public_id !== user?.public_id) { window.location.reload(); return }
        } catch { /* same-session refresh still works */ }
        setToken(event.newValue)
      }
    }
    window.addEventListener('storage', changed)
    let channel
    try {
      if (typeof BroadcastChannel !== 'undefined') {
        channel = new BroadcastChannel('bizassist_auth_channel')
        channel.onmessage = event => { if (event.data?.type === 'LOGOUT') logout(false) }
      }
    } catch { /* storage events remain available */ }
    return () => { window.removeEventListener('storage', changed); channel?.close() }
  }, [isDemoMode, token, user?.is_demo, user?.public_id, logout])

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
    if (modeChangePending.current) return false
    modeGeneration.current++
    modeChangePending.current = true
    logger.info(`[MODE SWITCH] Switching to "${newMode}" mode — will logout to refresh JWT`)
    // 1. Save the new mode to the CURRENT backend before switching.
    //    Backend exposes PUT /settings (a merge-patch); there is no PATCH route,
    //    so PATCH returned 405 and the mode was never persisted to the DB —
    //    which meant the sync worker (reads general.hosting_mode from the DB)
    //    never engaged hybrid. Use PUT to match the rest of the app.
    try {
      const res = await saveHostingMode(API_BASE, token, newMode)
      if (!res) return false
      // Pro-gate: the backend refuses to enable hybrid/cloud on a free plan (402).
      // Abort the switch and tell the user — do NOT flip mode, log out, or migrate.
      if (res.status === 402) {
        let detail = 'Local + Cloud requires the Pro plan. Contact your provider to upgrade.'
        try { detail = (await res.json()).detail || detail } catch { /* keep default */ }
        window.dispatchEvent(new CustomEvent('show_toast', { detail: { type: 'error', msg: detail } }))
        logger.info('[MODE SWITCH] Blocked — Pro plan required')
        return false
      }
      if (!res.ok) throw new Error(`Could not save storage mode (HTTP ${res.status}). Please try again.`)
    } catch (err) {
      window.dispatchEvent(new CustomEvent('show_toast', { detail: { type: 'error', msg: err.message || 'Could not save storage mode. Please try again.' } }))
      return false
    } finally {
      modeChangePending.current = false
    }
    setHostingPreference(user?.public_id || user?.username || user?.id, newMode)
    // 2. Update localStorage so the new API_BASE is effective immediately
    await logout()
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
    return true
  }, [token, logout, saveHostingMode, user?.public_id, user?.username, user?.id])

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
    if (modeChangePending.current) return false
    // A legacy cloud-routed desktop holds a cloud JWT. It needs a local login
    // before it can use the on-device database; never reuse that JWT locally.
    if (IS_LOCAL_APP && isCloudEndpoint(API_BASE) && newMode === 'local') return switchMode(newMode)
    modeGeneration.current++
    modeChangePending.current = true
    const generation = authGeneration.current
    const backend = API_BASE
    const current = () => generation === authGeneration.current && tokenStorage.getItem('billing_token') === token && API_BASE === backend
    logger.info(`[MODE] Setting hosting mode to "${newMode}" (no logout — same local backend)`)
    try {
      const res = await saveHostingMode(backend, token, newMode)
      if (!res) return false
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
      if (!res.ok) throw new Error(`Could not save storage mode (HTTP ${res.status}). Your current mode is unchanged.`)
    } catch (err) {
      if (current()) window.dispatchEvent(new CustomEvent('show_toast', { detail: { type: 'error', msg: err.message || 'Could not save storage mode. Your current mode is unchanged.' } }))
      return false
    } finally {
      modeChangePending.current = false
    }
    if (!current()) return false
    setHostingPreference(user?.public_id || user?.username || user?.id, newMode)
    updateApiBase(newMode)
    setSettings(previous => previous ? { ...previous, general: { ...previous.general, hosting_mode: newMode } } : previous)
    window.dispatchEvent(new CustomEvent('refresh-settings'))
    window.dispatchEvent(new CustomEvent('show_toast', {
      detail: {
        type: 'success',
        msg: newMode === 'local'
          ? 'Local only selected for this business on this device. Cloud sync is paused in both directions; web and other-device changes will not appear here until you enable Local + Cloud.'
          : 'Local + Cloud enabled. Your data now syncs to the cloud in the background.',
      },
    }))
    logger.info(`[MODE] Done. API_BASE is now: ${API_BASE}`)
    return true
  }, [token, switchMode, saveHostingMode, user?.public_id, user?.username, user?.id])

  useSessionRefresh(isDemoMode || user?.is_demo || token === DEMO_TOKEN ? null : token)
  useEffect(() => {
    if (isDemoMode || user?.is_demo || token === DEMO_TOKEN) return
    const changed = event => { if (event.detail?.token) setToken(event.detail.token) }
    window.addEventListener('auth_token_refreshed', changed)
    return () => window.removeEventListener('auth_token_refreshed', changed)
  }, [isDemoMode, token, user?.is_demo])

  const [profile, setProfile] = useState(null)

  const fetchProfile = useCallback(async () => {
    if (!token || isDemoMode || isDemoRequested() || token === DEMO_TOKEN || user?.is_demo) return
    const backend = API_BASE, generation = authGeneration.current
    const current = () => generation === authGeneration.current && tokenStorage.getItem('billing_token') === token && isSameBackendOrCloudFailover(API_BASE, backend)
    try {
      if (!current()) return
      const res = await sessionFetch(`${backend}/profile`, {
        headers: {
          Authorization: `Bearer ${token}`
        }
      })
      if (!current()) return
      await reportLoadError(res, '/profile')
      if (res.ok) {
        const data = await res.json()
        if (!current()) return
        setProfile(data)
      }
    } catch (err) {
      logger.error('Failed to fetch profile:', err)
    }
  }, [token, logout])

  const [settings, setSettings] = useState(() => isDemoRequested() ? DEMO_SETTINGS : null)

  const fetchSettings = useCallback(async (force = false) => {
    if (!token || isDemoMode || isDemoRequested() || token === DEMO_TOKEN || user?.is_demo) return
    if (modeChangePending.current) return
    const backend = API_BASE, generation = authGeneration.current
    const modeEpoch = modeGeneration.current
    const current = () => !modeChangePending.current && modeEpoch === modeGeneration.current && generation === authGeneration.current && tokenStorage.getItem('billing_token') === token && isSameBackendOrCloudFailover(API_BASE, backend)
    try {
      if (!current()) return
      const url = force ? `${backend}/settings?force=true` : `${backend}/settings`
      const res = await sessionFetch(url, {
        headers: {
          Authorization: `Bearer ${token}`
        }
      })
      if (!current()) return
      await reportLoadError(res, '/settings')
      if (res.ok) {
        const data = await res.json()
        if (!current()) return
        // (§9.3a/b) Reconcile the account's saved `general.hosting_mode` to the
        // REAL mode so it can't drift. A stale value (e.g. 'local' persisted on
        // the account from an earlier desktop switch) otherwise mis-tags cloud
        // invoices with `LCL-` (getCounterPrefix reads this) and previously also
        // disabled realtime. The real mode: web is ALWAYS cloud; a desktop app
        // uses its own per-device choice (`bizassist_hosting_mode`).
        const savedMode = data?.general?.hosting_mode
        const deviceMode = (typeof localStorage !== 'undefined' && localStorage.getItem('bizassist_hosting_mode')) || null

        // The mode is DERIVED from URL + plan + device routing (see
        // utils/resolveHostingMode.js), not read back from whatever was stored
        // last. The previous reconcile did the opposite: it let a stale device
        // key outrank the account and then PUT that stale value over the user's
        // actual choice, so a Pro owner's "Local + Cloud" was silently rewritten
        // to 'cloud' on every settings load. The backend's sync-queue gate reads
        // this stored field directly, so that one wrong value stopped every row
        // from being queued and emptied the outbox.
        // The plan must be READ, not assumed. The old expression ended in
        // `: 'pro'`, so a settings response that carried no `subscription` block
        // silently promoted the session to Pro; the mirror-image guess ('free')
        // is worse still, because it resolves a hybrid account down to 'local'
        // and that is the value that switches the sync worker off. So: track
        // whether we actually know, and let shouldPersistMode refuse to write on
        // a guess. `userPlan` may stay undefined — resolveHostingMode treats
        // anything that is not 'pro' as not-Pro, which is the safe read for
        // display; it is only PERSISTING an unknown that is forbidden.
        const readPlan = data?.subscription?.plan || profile?.plan ||
          (typeof profile?.is_premium === 'boolean' ? (profile.is_premium ? 'pro' : 'free') : undefined)
        const planKnown = typeof readPlan === 'string'
        const userPlan = readPlan
        const explicitChoice = getHostingPreference(user?.public_id || user?.username || user?.id)
        const realMode = resolveHostingMode({
          isLocalApp: IS_LOCAL_APP,
          plan: userPlan,
          savedMode,
          deviceMode,
          explicitChoice,
          planKnown,
        })

        // Two DIFFERENT questions, and conflating them is what caused the outage
        // described in resolveHostingMode.js:
        //
        //   (a) How does THIS SESSION behave?  — always `realMode`. A web tab has
        //       no local backend, so it must prefix invoices `CLD-`, not `LCL-`
        //       (getCounterPrefix reads this field), and must not offer
        //       hybrid-only controls. This is in-memory and costs nothing.
        //
        //   (b) What does the ACCOUNT record?  — only written when this session is
        //       entitled to author it. `users` is a synced table, so whatever is
        //       written here lands on every other device, including the desktop
        //       whose sync worker is gated on this exact value.
        //
        // (a) applies unconditionally; (b) is gated.
        if (data?.general) data.general.hosting_mode = realMode
        setSettings(data)

        if (data?.general && shouldPersistMode(realMode, savedMode, { isLocalApp: IS_LOCAL_APP, planKnown, explicitChoice })) {
          logger.info(
            `[AUTH] hosting_mode resolves to '${realMode}' ` +
            `(stored '${savedMode || 'unset'}', plan '${readPlan || 'unknown'}', ` +
            `${IS_LOCAL_APP ? 'local app' : 'web'}) — persisting so the sync gate agrees.`
          )
          // Persisting is what makes it stick server-side; the derivation is
          // deterministic from session facts, so this settles on the first load
          // rather than oscillating the way the old reconcile did.
          if (!current()) return
          saveHostingMode(backend, token, realMode).then(res => {
            if (!res) return
            if (res.ok && current() && deviceMode !== 'cloud') {
              // Both local modes retain the same API and JWT. Keep routing/UI
              // defaults aligned without recording an explicit owner choice.
              updateApiBase(realMode)
            }
            if (res.status === 402) {
              // Plan lapsed between resolve and write — resolveHostingMode will
              // degrade to 'local' on the next pass once the plan is refreshed.
              logger.warn('[AUTH] hosting_mode PUT refused (plan required); will re-resolve on next load.')
            }
          }).catch(err => logger.warn('[AUTH] hosting_mode PUT failed (non-blocking):', err))
        } else if (realMode !== savedMode) {
          logger.info(
            `[AUTH] hosting_mode is '${realMode}' for this session but the account ` +
            `stores '${savedMode || 'unset'}' — NOT persisting ` +
            `(${!IS_LOCAL_APP ? 'web session may not author the account field' : 'plan unknown'}). ` +
            `The account value is authored by the local install only.`
          )
        }
        logger.info('Loaded app settings successfully in context')
        // Reconciliation never moves a cloud-routed session onto a local JWT.
        // Only successful same-backend local/hybrid saves update the device key.
      }
    } catch (err) {
      logger.error('Failed to fetch settings in context:', err)
    }
  }, [token, logout, saveHostingMode, profile?.plan, profile?.is_premium, user?.public_id, user?.username, user?.id])

  useEffect(() => {
    if (!token || settings) return
    let stopped = false, attempt = 0, timer
    const schedule = () => {
      timer = setTimeout(async () => {
        if (stopped) return
        await fetchSettings()
        if (!stopped) schedule()
      }, [2000, 4000, 8000, 16000][attempt++] || 30000)
    }
    schedule()
    const retry = () => { if (!stopped) void fetchSettings() }
    window.addEventListener('focus', retry)
    window.addEventListener('online', retry)
    return () => { stopped = true; clearTimeout(timer); window.removeEventListener('focus', retry); window.removeEventListener('online', retry) }
  }, [token, settings, fetchSettings])

  const fetchBusinessConfig = useCallback(async () => {
    if (!token || isDemoMode || isDemoRequested() || token === DEMO_TOKEN || user?.is_demo) return
    const backend = API_BASE, generation = authGeneration.current
    const current = () => generation === authGeneration.current && tokenStorage.getItem('billing_token') === token && isSameBackendOrCloudFailover(API_BASE, backend)
    try {
      if (!current()) return
      const res = await sessionFetch(`${backend}/business/config`, {
        headers: {
          Authorization: `Bearer ${token}`
        }
      })
      if (!current()) return
      await reportLoadError(res, '/business/config')
      if (res.ok) {
        const data = await res.json()
        if (!current()) return
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
      if (isDemoMode || isDemoRequested() || token === DEMO_TOKEN || user?.is_demo) {
        return
      }
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

  // ── Ask again, occasionally ───────────────────────────────────────────────
  // `settings` was fetched on login and then never again unless something
  // dispatched `refresh-settings`. The backend was willing to answer the whole
  // time — GET /settings re-checks the plan against the cloud — but nothing
  // asked, so an admin granting Pro was invisible until the next sign-in.
  //
  // A poll, not a push: the device that needs to hear "you're Pro now" is a
  // FREE device, which runs no sync worker and holds no cloud listener. There
  // is no open channel to push over, and opening one for every non-paying
  // install to carry a message that may never come is the wrong trade.
  //
  // Cheap on purpose: the server owns the real rate limit (a per-business
  // cooldown, short while free and 30 min once Pro), so most of these ticks
  // cost one local read and no network at all.
  useEffect(() => {
    if (!token) return
    const t = setInterval(() => {
      window.dispatchEvent(new CustomEvent('refresh-settings'))
    }, 5 * 60 * 1000)
    return () => clearInterval(t)
  }, [token])

  // ── Free → Pro, without a re-login ────────────────────────────────────────
  // The plan arriving is not the same as the app reacting to it. Cloud sync
  // becomes available at this moment; activate the verified background worker
  // so an owner who has just paid does not need to sign in again.
  //
  // Only the free → pro EDGE — see utils/planTransition for the three ways
  // "no" is the right answer here.
  const prevPlanRef = React.useRef(undefined)
  useEffect(() => {
    const plan = settings?.subscription?.plan
    const prev = prevPlanRef.current
    prevPlanRef.current = plan
    if (!token || !isUpgradeToPro(prev, plan)) return

    logger.info('[AuthContext] plan upgraded to Pro — preparing background cloud sync')
    // Other plan-aware surfaces can refresh without interrupting this session.
    window.dispatchEvent(new CustomEvent('plan-upgraded'))

    let cloudTok = null
    try { cloudTok = localStorage.getItem('bizassist_cloud_token') } catch { /* ignore */ }
    _startVerifiedSync(token, cloudTok)
  }, [settings?.subscription?.plan, token, _startVerifiedSync])

  useEffect(() => {
    const handleUnauthorized = () => {
      if (isDemoMode || isDemoRequested() || token === DEMO_TOKEN || user?.is_demo) {
        logger.info('[DEMO] Suppressed unauthorized signal in demo sandbox.')
        return
      }
      logger.warn('[AuthContext] auth_unauthorized event triggered. Auto-logging out.')
      logout(false)
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
    const backend = API_BASE, generation = authGeneration.current
    const current = () => generation === authGeneration.current && isSameBackendOrCloudFailover(API_BASE, backend)
    if (!current()) throw new Error('Session changed')
    // DELIBERATELY NO ABSOLUTE-URL PASSTHROUGH.
    // A revision that allowed callers to pass a fully-qualified URL here caused
    // a cross-tenant bug: the session token is issued by, and only valid on, the
    // backend the user logged into. Sending a LOCAL token to the cloud made the
    // cloud resolve the user id against its own users table, where the same
    // integer is a DIFFERENT business — one tenant saw another's BizID.
    // authFetch attaches THIS session's token, so it must only ever target THIS
    // session's backend. Anything that needs the cloud goes through the local
    // backend, which holds a cloud-issued token of its own.
    let apiPath = path
    if (apiPath.startsWith('/billing/')) {
      apiPath = '/' + apiPath.slice('/billing/'.length)
    } else if (apiPath.startsWith('billing/')) {
      apiPath = '/' + apiPath.slice('billing/'.length)
    }

    if (user?.is_demo || isDemoMode || isDemoRequested()) {
      const mockRes = handleDemoRequest(apiPath, opts)
      if (mockRes) return mockRes
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
      res = await resilientSessionFetch(`${backend}${apiPath}`, {
        ...opts,
        headers
      }, { budgetMs: opts.timeoutMs || (apiPath.startsWith('/connections/') && !['GET', 'HEAD'].includes((opts.method || 'GET').toUpperCase()) ? 75000 : 65000) })
    } catch (err) {
      logger.error(`authFetch network failure for path: ${path}`, err)
      window.dispatchEvent(new CustomEvent('show_toast', {
        detail: { type: 'error', msg: err.message || 'Network connection failed' }
      }))
      throw err
    }

    if (!current()) throw new Error('Session changed')


    if (!res.ok) {
      const message = readableError(res.status, res.headers?.get?.('content-type'), await res.clone().text())
      window.dispatchEvent(new CustomEvent('show_toast', { detail: { type: 'error', msg: message } }))
    }

    logger.debug(`authFetch response status for path ${path}: ${res.status}`)
    return res
  }, [token, logout])

  const enterDemoMode = useCallback(() => {
    activateDemoSession()
    setUser(DEMO_USER)
    setToken(DEMO_TOKEN)
    setIsDemoMode(true)
    setBizId(DEMO_USER.public_id)
    setSettings(DEMO_SETTINGS)
    setLoading(false)
  }, [])

  return (
    <AuthContext.Provider value={{
      user, token, loading, login, staffLogin, logout, signup, switchMode, setHostingMode, authFetch, profile, fetchProfile, setProfile,
      businessConfig, attributesSchema, fetchBusinessConfig, appReady, setAppReady,
      settings, fetchSettings,
      networkMode,   // 'local' | 'cloud' — whether this device is on the same LAN as the owner's backend
      setSession: _saveSession,
      isDemoMode,
      enterDemoMode,
    }}>
      {children}
    </AuthContext.Provider>
  )
}

export const useAuth = () => {
  const value = useContext(AuthContext)
  if (value === null) throw new Error('useAuth must be rendered inside AuthProvider')
  return value
}

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
