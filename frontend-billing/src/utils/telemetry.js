/**
 * telemetry.js — frontend diagnostics capture (Admin Console plan).
 *
 * With optional diagnostics accepted, captures unhandled errors, promise rejections, and logEvent()
 * calls, and ships them (batched, fire-and-forget) to the backend telemetry
 * sink — BOTH the app's own backend (local on desktop, cloud on web) and the
 * cloud backend explicitly, so field issues always reach the Admin Console.
 *
 * Every batch carries:
 *   - a stable per-browser device id (localStorage, "web-" prefixed)
 *   - the logged-in business's BizID (public_id) when known
 * No business data — only app diagnostics.
 */
import { API_BASE } from '../config'
import { APP_VERSION } from '../config/appVersion'
import { diagnosticsAllowed, STORAGE_CONSENT_CHANGED, STORAGE_CONSENT_KEY } from './storageConsent'

// Cloud Run Mumbai telemetry endpoint
const CLOUD_URL = import.meta.env.VITE_CLOUD_TELEMETRY_URL || 'https://staterbill-api-1076771386585.asia-south1.run.app'
// Hugging Face fallback (uncomment to re-enable):
// const CLOUD_URL = 'https://rakshit-dev-bizassist.hf.space'
const SOURCE = 'frontend-billing'
const FLUSH_MS = 20000
const MAX_QUEUE = 40
const MAX_PAYLOAD = 2000

let queue = []
let timer = null
let installed = false

function deviceId(persistent = true) {
  if (!persistent) return 'web-oneoff-' + (globalThis.crypto?.randomUUID?.() || Math.random().toString(36).slice(2))
  try {
    let id = localStorage.getItem('web_device_id')
    if (!id) {
      id = 'web-' + (crypto.randomUUID ? crypto.randomUUID() : Math.random().toString(36).slice(2))
      localStorage.setItem('web_device_id', id)
    }
    return id
  } catch {
    return 'web-unknown'
  }
}

function currentBizId() {
  try {
    // The billing app stores the session under 'billing_user' (not 'user') — the
    // old key meant the BizID never attached to telemetry batches.
    const u = JSON.parse(localStorage.getItem('billing_user') || 'null')
    return u?.public_id || null
  } catch {
    return null
  }
}

function truncate(v) {
  const s = typeof v === 'string' ? v : JSON.stringify(v)
  return s && s.length > MAX_PAYLOAD ? s.slice(0, MAX_PAYLOAD) + '…' : s
}

function buildBatch(events, persistentDevice = diagnosticsAllowed()) {
  const batch = {
    source: SOURCE,
    device_id: deviceId(persistentDevice),
    app_version: APP_VERSION,
    platform: 'browser',
    events,
  }
  const bizid = currentBizId()
  if (bizid) batch.bizid = bizid
  return batch
}

function post(base, body, useBeacon = false) {
  const url = `${base}/api/telemetry/log`
  // Cross-origin here means: the dev server (:5174) talking to the local backend
  // (:8001), or any origin talking to the cloud.
  const crossOrigin = typeof window !== 'undefined' &&
    !String(base).startsWith(window.location.origin)

  try {
    // `navigator.sendBeacon` ALWAYS uses credentials mode "include". The API
    // authenticates with Bearer tokens, not cookies, so it correctly sets
    // `allow_credentials=False` — and a credentialed request against that is
    // rejected at preflight with:
    //   "The value of the 'Access-Control-Allow-Credentials' header ... is ''
    //    which must be 'true' when the request's credentials mode is 'include'"
    // Raising allow_credentials to satisfy a telemetry ping would weaken CORS
    // for the whole API (the origin regex matches any localhost/LAN address),
    // so the fix belongs here: beacon only same-origin, and use fetch with
    // `keepalive` — the standard sendBeacon replacement, which survives unload
    // and lets us omit credentials — for everything else.
    if (useBeacon && !crossOrigin && navigator.sendBeacon) {
      navigator.sendBeacon(url, new Blob([JSON.stringify(body)], { type: 'application/json' }))
      return
    }
    fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
      keepalive: true,
      credentials: 'omit',   // never send cookies — the API is token-authenticated
    }).catch(() => {})
  } catch { /* never break the app over telemetry */ }
}

function flush(useBeacon = false) {
  if (!diagnosticsAllowed()) { queue = []; return }
  if (!queue.length) return
  const events = queue.splice(0, MAX_QUEUE)
  const body = buildBatch(events)
  post(API_BASE, body, useBeacon)
  // Desktop/local dev: also ship to the cloud so the Admin Console sees it.
  if (!API_BASE.startsWith(CLOUD_URL)) post(CLOUD_URL, body, useBeacon)
}

function enqueue(event, payload, level = 'info') {
  if (!diagnosticsAllowed()) return
  queue.push({ event, level, payload, at: new Date().toISOString() })
  if (queue.length >= MAX_QUEUE) flush()
  else if (!timer) timer = setTimeout(() => { timer = null; flush() }, FLUSH_MS)
}

/** Explicit app-level event, e.g. logEvent('print_failed', { template }, 'warn') */
export function logEvent(event, payload = {}, level = 'info') {
  enqueue(String(event).slice(0, 80), payload, level)
}

/** User-triggered "Send diagnostics": stamp a marker event with environment
 *  context and force an immediate flush to the local AND cloud sinks, so the
 *  last N (bizid-tagged) events reach the Admin Console right away. Returns
 *  true once the flush has been kicked off. */
export function sendDiagnostics(reason = 'manual', extra = {}, { userInitiated = false } = {}) {
  // A deliberate Send diagnostics click authorizes this one report. Automatic
  // startup/error reports require the saved optional-diagnostics preference.
  if (!diagnosticsAllowed() && !userInitiated && reason !== 'manual') return false
  let payload
  try {
    payload = {
      reason,
      mode: (typeof localStorage !== 'undefined' && localStorage.getItem('bizassist_hosting_mode')) || 'local',
      app_version: APP_VERSION,
      platform: (typeof navigator !== 'undefined' && navigator.platform) || undefined,
      user_agent: (typeof navigator !== 'undefined' && navigator.userAgent) || undefined,
      url: (typeof location !== 'undefined' && `${location.origin}${location.pathname}`) || undefined,
      ...extra,
    }
  } catch { /* diagnostics must never throw */ }
  if (diagnosticsAllowed()) {
    enqueue('diagnostics_report', payload, 'info')
    flush()
    return true
  }
  const body = buildBatch([{ event: 'diagnostics_report', payload, level: 'info', at: new Date().toISOString() }])
  post(API_BASE, body)
  if (!API_BASE.startsWith(CLOUD_URL)) post(CLOUD_URL, body)
  return true
}

/** Install global error capture. Call once from main.jsx. */
export function initTelemetry() {
  if (installed || typeof window === 'undefined') return
  installed = true

  const applyConsent = () => {
    if (diagnosticsAllowed()) return
    queue = []
    clearTimeout(timer)
    timer = null
    try { localStorage.removeItem('web_device_id') } catch { /* Storage may be blocked. */ }
  }
  applyConsent()
  window.addEventListener(STORAGE_CONSENT_CHANGED, applyConsent)
  window.addEventListener('storage', event => {
    if (event.key === STORAGE_CONSENT_KEY || event.key === null) applyConsent()
  })

  window.addEventListener('error', (e) => {
    enqueue('window_error', {
      message: truncate(e.message),
      file: e.filename ? e.filename.split('/').pop() : undefined,
      line: e.lineno,
      stack: truncate(e.error?.stack),
    }, 'error')
  })

  window.addEventListener('unhandledrejection', (e) => {
    const r = e.reason
    enqueue('unhandled_rejection', {
      message: truncate(r?.message || String(r)),
      stack: truncate(r?.stack),
    }, 'error')
  })

  // Don't lose the tail of the queue when the tab closes.
  window.addEventListener('pagehide', () => flush(true))
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'hidden') flush(true)
  })
}
