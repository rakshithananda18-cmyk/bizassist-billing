/** LAN discovery supplies a connection hint, never a local authentication session. */
import { CLOUD_URL, IS_LOCAL_APP } from '../config'
import { boundedJsonFetch } from '../api/boundedRequest'
import { logger } from './logger'

const PROBE_TIMEOUT_MS = 1500
const REGISTRY_TIMEOUT_MS = 4000
const CACHE_KEY = 'bizassist_discovered_local_url'
const CACHE_TTL_MS = 10 * 60 * 1000
let discoveryGeneration = 0

function currentBusinessId() {
  try { return JSON.parse(localStorage.getItem('billing_user') || '{}')?.public_id || null }
  catch { return null }
}

function removeCache() {
  try { localStorage.removeItem(CACHE_KEY) } catch { /* storage unavailable */ }
}

function probeUrl(value) {
  try {
    const url = new URL(value)
    if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password || url.search || url.hash) return null
    const loopback = url.hostname === 'localhost' || url.hostname.endsWith('.localhost')
      || /^127\.\d+\.\d+\.\d+$/.test(url.hostname) || url.hostname === '[::1]'
    // Secure pages must not attempt blockable HTTP LAN fetches. Loopback is a
    // potentially trustworthy origin; browser local-network permissions still apply.
    if (globalThis.location?.protocol === 'https:' && url.protocol === 'http:' && !loopback) return null
    return url.href.replace(/\/$/, '')
  } catch { return null }
}

/** Only return a fresh, transport-compatible hint for this signed-in business. */
export function getDiscoveredLocalBackend(bizId = currentBusinessId()) {
  try {
    const raw = localStorage.getItem(CACHE_KEY)
    if (!raw) return null
    const entry = JSON.parse(raw)
    const url = probeUrl(entry?.url)
    if (!bizId || entry?.bizId !== bizId || !url || !Number.isFinite(entry.ts)
        || entry.ts > Date.now() || Date.now() - entry.ts >= CACHE_TTL_MS) {
      removeCache()
      return null
    }
    return url
  } catch { removeCache(); return null }
}

/** Shared by discovery and the explicit Settings connection check. No credentials are sent. */
export async function probeLocalBackend(value, { timeoutMs = PROBE_TIMEOUT_MS, signal, expectedBizId = null } = {}) {
  const url = probeUrl(value)
  if (!url) return { ok: false, error: 'This connection requires a valid HTTPS local-server address from the web app.' }
  const started = Date.now()
  try {
    const res = await boundedJsonFetch(`${url}/health`, {
      signal, mode: 'cors', redirect: 'error', credentials: 'omit', cache: 'no-store',
    }, timeoutMs)
    if (!res.ok) return { ok: false, error: `HTTP ${res.status}` }
    const data = await res.json()
    if (data?.status !== 'ok' || data?.db !== 'connected' || data?.db_type !== 'sqlite') {
      return { ok: false, error: 'A healthy local database was not verified.' }
    }
    const advertisedBizId = data.public_id || data.biz_id
    if (expectedBizId && advertisedBizId && advertisedBizId !== expectedBizId) {
      return { ok: false, error: 'The server belongs to a different business.' }
    }
    return { ok: true, ms: Date.now() - started, mode: data.mode || 'local', version: data.version || null }
  } catch (err) {
    return { ok: false, error: err?.code === 'AUTH_REQUEST_TIMEOUT' ? 'Connection check timed out.' : 'Local server is unreachable.' }
  }
}

/** Discover only compatible endpoints; finding one does not change API routing. */
export async function discoverLocalBackend(bizId) {
  if (!bizId || IS_LOCAL_APP) return null
  const generation = ++discoveryGeneration
  const ownerAtStart = currentBusinessId()
  if (ownerAtStart && ownerAtStart !== bizId) return null
  const current = () => generation === discoveryGeneration && currentBusinessId() === ownerAtStart

  const cached = getDiscoveredLocalBackend(bizId)
  if (cached) {
    const result = await probeLocalBackend(cached, { expectedBizId: bizId })
    if (!current()) return null
    if (result.ok) return cached
    removeCache()
  }

  let backends
  try {
    const res = await boundedJsonFetch(`${CLOUD_URL}/discover/${encodeURIComponent(bizId)}`, {
      mode: 'cors', redirect: 'error', credentials: 'omit', cache: 'no-store',
    }, REGISTRY_TIMEOUT_MS)
    if (!current() || !res.ok) return null
    const data = await res.json()
    if (!Array.isArray(data?.backends) || (data.biz_id && data.biz_id !== bizId)) return null
    backends = [...new Set(data.backends.map(backend => probeUrl(backend?.url)).filter(Boolean))].slice(0, 16)
  } catch (err) {
    logger.debug('[DISCOVERY] Cloud registry unavailable:', err?.message)
    return null
  }
  if (!current()) return null
  const results = await Promise.all(backends.map(async url => {
    const result = await probeLocalBackend(url, { expectedBizId: bizId })
    return result.ok ? url : null
  }))
  if (!current()) return null
  const found = results.find(Boolean) || null
  if (found) {
    try { localStorage.setItem(CACHE_KEY, JSON.stringify({ bizId, url: found, ts: Date.now() })) } catch { /* storage unavailable */ }
    logger.debug('[DISCOVERY] Local server connection hint verified:', found)
  }
  return found
}

/** The web workspace stays cloud-routed; a discovery hint cannot authenticate it locally. */
export function getNetworkMode() {
  if (!IS_LOCAL_APP) return 'cloud'
  try { return localStorage.getItem('bizassist_hosting_mode') === 'cloud' ? 'cloud' : 'local' }
  catch { return 'local' }
}

export function clearDiscoveryCache() {
  discoveryGeneration++
  removeCache()
}
