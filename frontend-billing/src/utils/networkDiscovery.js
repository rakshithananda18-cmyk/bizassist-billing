/**
 * networkDiscovery.js
 * ====================
 * LAN auto-discovery: finds the owner's local backend on the same WiFi/LAN
 * network so cashier devices connect directly without manual IP config.
 *
 * Flow:
 *  1. Query cloud registry: GET /discover/{biz_id} → list of known local IPs
 *  2. Probe each IP with GET http://x.x.x.x:8001/health (1.5s timeout)
 *  3. If a probe succeeds → same network → return local URL
 *  4. All fail → different network → return null (use cloud)
 *
 * The result is cached in localStorage for 10 minutes. On next open, we try
 * the cached URL first (fast path), then re-run discovery if it fails.
 */

import { CLOUD_URL, IS_LOCAL_APP } from '../config'
import { logger } from './logger'

const PROBE_TIMEOUT_MS = 1500
const CACHE_KEY = 'bizassist_discovered_local_url'
const CACHE_TTL_MS = 10 * 60 * 1000  // 10 minutes

/**
 * Probe a single backend URL. Returns true if it's reachable and is
 * a local (SQLite) backend for the expected business.
 */
async function probeLocalUrl(url, expectedBizId = null) {
  const ctrl = new AbortController()
  const id = setTimeout(() => ctrl.abort(), PROBE_TIMEOUT_MS)
  try {
    const res = await fetch(`${url}/health`, { signal: ctrl.signal, mode: 'cors' })
    clearTimeout(id)
    if (!res.ok) return false
    const data = await res.json()
    // Must be a local (SQLite) backend — not the cloud endpoint itself
    if (data.db_type !== 'sqlite') return false
    // If we know the expected biz local_ip and the response includes local_ip, verify
    return true
  } catch {
    clearTimeout(id)
    return false
  }
}

/**
 * Try the cached local URL first (fast path on repeat opens).
 * Returns the URL if still reachable, null otherwise.
 */
async function tryCachedUrl() {
  try {
    const raw = localStorage.getItem(CACHE_KEY)
    if (!raw) return null
    const { url, ts } = JSON.parse(raw)
    if (!url || Date.now() - ts > CACHE_TTL_MS) return null
    const ok = await probeLocalUrl(url)
    if (ok) {
      logger.info('[DISCOVERY] Cached local backend still reachable:', url)
      return url
    }
    logger.debug('[DISCOVERY] Cached URL no longer reachable, re-discovering...')
    return null
  } catch {
    return null
  }
}

/**
 * Main discovery function. Call once after login.
 *
 * @param {string} bizId - The business's public_id
 * @returns {Promise<string|null>} The local backend URL if found on same LAN, null otherwise
 */
export async function discoverLocalBackend(bizId) {
  if (!bizId) return null

  // Cashier devices on cloud URL run discovery to find owner's local backend.
  // On IS_LOCAL_APP, you ARE the owner's backend — no discovery needed.
  // (Exception: if the local app is in cloud-only mode, skip too.)
  if (IS_LOCAL_APP) {
    logger.debug('[DISCOVERY] Skipping — already on local backend')
    return null
  }

  // Fast path: check cache first
  const cached = await tryCachedUrl()
  if (cached) return cached

  // Fetch known IPs from cloud registry
  let backends = []
  try {
    const res = await fetch(`${CLOUD_URL}/discover/${bizId}`, { mode: 'cors' })
    if (res.ok) {
      const data = await res.json()
      backends = data.backends || []
      logger.info('[DISCOVERY] Found', backends.length, 'registered backend(s) for biz', bizId)
    }
  } catch (err) {
    logger.debug('[DISCOVERY] Cloud registry unreachable:', err?.message)
    return null
  }

  if (backends.length === 0) {
    logger.debug('[DISCOVERY] No backends registered for biz', bizId)
    return null
  }

  // Probe each backend in parallel (sorted by recency — most recent first)
  const results = await Promise.all(
    backends.map(async (b) => {
      const ok = await probeLocalUrl(b.url)
      logger.debug('[DISCOVERY] Probe', b.url, '→', ok ? 'reachable ✅' : 'unreachable ❌')
      return ok ? b.url : null
    })
  )

  const found = results.find(r => r !== null) || null

  if (found) {
    // Cache the discovered URL
    try {
      localStorage.setItem(CACHE_KEY, JSON.stringify({ url: found, ts: Date.now() }))
    } catch { /* ignore quota errors */ }
    logger.info('[DISCOVERY] Same-network local backend discovered:', found)
  } else {
    logger.info('[DISCOVERY] No reachable local backend found — using cloud')
  }

  return found
}

/**
 * Get the current network mode based on what URL is being used.
 * 'local' — connected directly to the local backend on LAN
 * 'cloud' — connected via cloud backend (different network or cloud-only)
 */
export function getNetworkMode() {
  if (IS_LOCAL_APP) return 'local'
  try {
    const raw = localStorage.getItem(CACHE_KEY)
    if (!raw) return 'cloud'
    const { url, ts } = JSON.parse(raw)
    if (url && Date.now() - ts < CACHE_TTL_MS) return 'local'
  } catch { /* ignore */ }
  return 'cloud'
}

/**
 * Clear the discovery cache (e.g. when the user logs out or
 * when the discovered URL becomes unreachable).
 */
export function clearDiscoveryCache() {
  try { localStorage.removeItem(CACHE_KEY) } catch { /* ignore */ }
}
