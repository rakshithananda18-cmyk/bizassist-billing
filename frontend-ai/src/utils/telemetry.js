/**
 * telemetry.js — frontend diagnostics capture (Admin Console plan).
 * Same contract as frontend-billing/src/utils/telemetry.js — see that file.
 * Ships unhandled errors + explicit logEvent() calls to the app's backend
 * AND the cloud backend, tagged with the device id and BizID when known.
 */
import { API_BASE } from '../config'

const CLOUD_URL = import.meta.env.VITE_CLOUD_TELEMETRY_URL || 'https://rakshit-dev-bizassist.hf.space'
const SOURCE = 'frontend-ai'
const FLUSH_MS = 20000
const MAX_QUEUE = 40
const MAX_PAYLOAD = 2000

let queue = []
let timer = null
let installed = false

function deviceId() {
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
    const u = JSON.parse(localStorage.getItem('user') || 'null')
    return u?.public_id || null
  } catch {
    return null
  }
}

function truncate(v) {
  const s = typeof v === 'string' ? v : JSON.stringify(v)
  return s && s.length > MAX_PAYLOAD ? s.slice(0, MAX_PAYLOAD) + '…' : s
}

function buildBatch(events) {
  const batch = {
    source: SOURCE,
    device_id: deviceId(),
    app_version: import.meta.env.VITE_APP_VERSION || 'web',
    platform: 'browser',
    events,
  }
  const bizid = currentBizId()
  if (bizid) batch.bizid = bizid
  return batch
}

function post(base, body, useBeacon = false) {
  const url = `${base}/api/telemetry/log`
  try {
    if (useBeacon && navigator.sendBeacon) {
      navigator.sendBeacon(url, new Blob([JSON.stringify(body)], { type: 'application/json' }))
      return
    }
    fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
      keepalive: true,
    }).catch(() => {})
  } catch { /* never break the app over telemetry */ }
}

function flush(useBeacon = false) {
  if (!queue.length) return
  const events = queue.splice(0, MAX_QUEUE)
  const body = buildBatch(events)
  post(API_BASE, body, useBeacon)
  if (!API_BASE.startsWith(CLOUD_URL)) post(CLOUD_URL, body, useBeacon)
}

function enqueue(event, payload, level = 'info') {
  queue.push({ event, level, payload, at: new Date().toISOString() })
  if (queue.length >= MAX_QUEUE) flush()
  else if (!timer) timer = setTimeout(() => { timer = null; flush() }, FLUSH_MS)
}

export function logEvent(event, payload = {}, level = 'info') {
  enqueue(String(event).slice(0, 80), payload, level)
}

export function initTelemetry() {
  if (installed || typeof window === 'undefined') return
  installed = true

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

  window.addEventListener('pagehide', () => flush(true))
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'hidden') flush(true)
  })
}
