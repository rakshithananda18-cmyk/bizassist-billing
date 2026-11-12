import { IS_LOCAL_APP, CLOUD_URL, LOCAL_URL } from '../config'
import { getHostingPreference } from './deviceMode'
import { logger } from './logger'
import { boundedJsonFetch } from '../api/boundedRequest'

const REQUEST_TIMEOUT_MS = 10000
const headersFor = token => ({ 'Content-Type': 'application/json', Authorization: `Bearer ${token}` })

async function boundedFetch(url, options, timeoutMs = REQUEST_TIMEOUT_MS) {
  return boundedJsonFetch(url, options, timeoutMs)
}

function syncRequestEvent(detail, isCurrent) {
  if (!isCurrent() || typeof window === 'undefined') return
  window.dispatchEvent(new CustomEvent('sync-event', {
    detail: { type: 'sync.trigger', sync_request: true, ...detail },
  }))
}

async function responseBody(response) {
  try { return await response.json() } catch { return {} }
}

async function requireAccepted(response) {
  const body = await responseBody(response)
  if (!response.ok) {
    const detail = typeof body?.detail === 'string' ? body.detail : null
    throw new Error(detail || `Cloud sync could not start (HTTP ${response.status}).`)
  }
  return body
}

/** Queue the durable local worker. Acceptance is not a completed data restore. */
export async function requestBackgroundSync(token, { base = LOCAL_URL, isCurrent = () => true, source = 'manual' } = {}) {
  if (!token || !isCurrent()) return { skipped: true }
  try {
    const response = await boundedFetch(`${base}/api/sync/flush?pull=true`, {
      method: 'POST', headers: headersFor(token),
    })
    if (!isCurrent()) return { skipped: true }
    const body = await requireAccepted(response)
    if (!isCurrent()) return { skipped: true }
    syncRequestEvent({ source, status: 'pending', accepted: true }, isCurrent)
    return { ...body, accepted: true, pending: true }
  } catch (error) {
    if (!isCurrent()) return { skipped: true }
    syncRequestEvent({ source, status: 'failed', accepted: false, error: error.message }, isCurrent)
    error.syncRequestReported = true
    throw error
  }
}

/**
 * Verify the two identities, then enable/schedule the account-scoped local
 * worker for Pro. Credentials stay backend-specific; no bulk export/import or
 * count comparison runs in the browser. An explicit Local-only choice wins.
 */
export async function reconcileBizIdOnLogin(token, cloudToken = null, {
  isCurrent = () => true,
  runModeWrite = operation => operation(),
  source = 'login',
  base = LOCAL_URL,
} = {}) {
  const current = () => {
    try {
      return isCurrent() && getHostingPreference() !== 'local'
        && localStorage.getItem('bizassist_hosting_mode') !== 'cloud'
    } catch { return false }
  }
  try {
    if (!IS_LOCAL_APP || !token || !cloudToken || !current()) return { skipped: true }
    if (typeof navigator !== 'undefined' && navigator.onLine === false) return { skipped: true }

    const readProfile = async (base, bearer) => {
      if (!current()) return null
      const response = await boundedFetch(`${base}/profile`, { headers: headersFor(bearer) })
      if (!current()) return null
      if (!response.ok) throw new Error(`Could not verify the sync account (HTTP ${response.status}).`)
      return responseBody(response)
    }
    const [cloudProfile, localProfile] = await Promise.all([
      readProfile(CLOUD_URL, cloudToken), readProfile(base, token),
    ])
    if (!current()) return { skipped: true }
    const cloudBiz = cloudProfile?.public_id
    const localBiz = localProfile?.public_id
    if (!cloudBiz || !localBiz || cloudBiz !== localBiz) {
      logger.warn('[LOGIN-SYNC] Cloud/local identity is missing or different; background activation was skipped.')
      return { skipped: true, reason: 'identity_mismatch' }
    }
    const premium = cloudProfile?.is_premium === true
      || cloudProfile?.plan === 'pro' || cloudProfile?.subscription?.plan === 'pro'
    if (!premium) return { skipped: true, reason: 'plan_required' }

    // Share AuthContext's hosting-write queue. A later explicit Local save must
    // land AFTER this activation, even if cloud verification is slow.
    const response = await runModeWrite(() => {
      if (!current()) return null
      return boundedFetch(`${base}/api/sync/cloud-token`, {
        method: 'POST', headers: headersFor(token),
        body: JSON.stringify({ token: cloudToken, enable_sync: true }),
      }, 20000)
    })
    if (!response || !current()) return { skipped: true }
    const activation = await requireAccepted(response)
    if (!current()) return { skipped: true }
    if (activation.hosting_mode !== 'hybrid') {
      throw new Error('The local service could not enable background sync. Update the desktop app and try again.')
    }
    if (activation.sync_started === true) {
      syncRequestEvent({ source, status: 'pending', accepted: true, initial_restore_pending: activation.initial_restore_pending === true }, current)
      window.dispatchEvent(new CustomEvent('refresh-settings'))
      return { accepted: true, pending: true }
    }
    return await requestBackgroundSync(token, { base, isCurrent: current, source })
  } catch (error) {
    if (!current()) return { skipped: true }
    logger.warn('[LOGIN-SYNC] Background sync could not start:', error?.message || error)
    if (!error.syncRequestReported) syncRequestEvent({ source, status: 'failed', accepted: false, error: error?.message || 'Cloud sync could not start.' }, current)
    return { accepted: false, error: error?.message }
  }
}
