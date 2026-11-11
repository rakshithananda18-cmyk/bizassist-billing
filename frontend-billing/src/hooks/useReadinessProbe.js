import { useState, useEffect, useCallback, useRef } from 'react'
import { logger } from '../utils/logger'
import { LOCAL_URL, PRIMARY_CLOUD_RUN_URL, IS_LOCAL_APP } from '../config'

const INTERVAL_MS = 30_000

// Timeout-aware fetch
function fetchWithTimeout(url, timeout, opts = {}, consume = response => response) {
  const ctrl = new AbortController()
  const id = setTimeout(() => ctrl.abort(), timeout)
  return fetch(url, { ...opts, signal: ctrl.signal }).then(consume).finally(() => clearTimeout(id))
}

async function assertHealthyBackend(res) {
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  const body = await res.json()
  if (body?.status !== 'ok' || body?.db !== 'connected') {
    throw new Error('Server database is not ready. Restart the backend and try again.')
  }
}

// ── Probe runners ─────────────────────────────────────────────────────────────

async function runLocalProbe() {
  const t0 = Date.now()
  try {
    const savedLocalUrl = typeof localStorage !== 'undefined' ? localStorage.getItem('bizassist_local_backend_url') : null
    const targetLocal = savedLocalUrl || LOCAL_URL
    // 3s, not 500ms: /health does real DB work (users.settings scan) and can
    // exceed 500ms on first hit / dev --reload. A dead server still fails
    // instantly (connection refused) — the timeout only guards a hung one.
    await fetchWithTimeout(`${targetLocal}/health`, 3000, { mode: 'cors' }, assertHealthyBackend)
    const ms = Date.now() - t0
    return { status: ms > 1000 ? 'slow' : 'online', ms, error: null }
  } catch (err) {
    const ms = Date.now() - t0
    const msg = err?.message || ''
    if (err?.name === 'AbortError') return { status: 'offline', ms: null, error: 'Timeout (no local server)' }
    if (
      err instanceof TypeError &&
      (msg.includes('fetch') || msg.includes('network') || msg.includes('CORS') ||
        msg.includes('Failed to fetch') || msg.includes('NetworkError'))
    ) {
      const onLocalhost = IS_LOCAL_APP
      if (!onLocalhost) return { status: 'cors', ms: null, error: 'Mixed-content / CORS blocked' }
    }
    return { status: 'offline', ms: null, error: msg || 'Network error' }
  }
}

async function runNamedCloudProbe(url) {
  const t0 = Date.now()
  try {
    await fetchWithTimeout(`${url}/health`, 6000, {}, assertHealthyBackend)
    const ms = Date.now() - t0
    return { status: ms > 1000 ? 'slow' : 'online', ms, error: null }
  } catch (err) {
    if (err?.name === 'AbortError') return { status: 'offline', ms: null, error: 'Timeout' }
    return { status: 'offline', ms: null, error: err?.message || 'Network error' }
  }
}

async function runInternetProbe() {
  if (!navigator.onLine) return { status: 'offline', ms: null, error: 'navigator.onLine = false' }
  const t0 = Date.now()
  try {
    await fetchWithTimeout('https://dns.google', 1000, { method: 'HEAD', mode: 'no-cors' })
    const ms = Date.now() - t0
    return { status: ms > 1000 ? 'slow' : 'online', ms, error: null }
  } catch (err) {
    if (err?.name === 'AbortError') return { status: 'offline', ms: null, error: 'Timeout' }
    return { status: 'offline', ms: null, error: err?.message || 'No internet' }
  }
}

// ─────────────────────────────────────────────────────────────────────────────

const INIT = { status: 'checking', ms: null, error: null }

export function useReadinessProbe() {
  const [localProbe,    setLocalProbe]    = useState(INIT)
  const [googleProbe,   setGoogleProbe]   = useState(INIT)
  // The standby probe is disabled; it must not keep the preflight pending.
  const [hfProbe]                       = useState(null)
  const [cloudProbe,    setCloudProbe]    = useState(INIT)
  const [internetProbe, setInternetProbe] = useState(INIT)
  const [sseProbe,      setSseProbe]      = useState(INIT)

  const intervalRef = useRef(null)
  const runRef = useRef(0)

  const runAll = useCallback(async () => {
    const run = ++runRef.current
    const publish = (setter) => (result) => {
      if (run === runRef.current) setter(result)
      return result
    }
    setLocalProbe(INIT)
    setGoogleProbe(INIT)
    setCloudProbe(INIT)
    setInternetProbe(INIT)
    setSseProbe(INIT)

    logger.debug('[PROBE] Initiating readiness probes (local, Google Cloud Run, internet)...')
    
    // Request latest SSE status update
    window.dispatchEvent(new CustomEvent('sync-status-request'))

    // Publish each result independently: Local mode must not wait for cloud.
    const [lResult, gResult, iResult] = await Promise.all([
      runLocalProbe().then(publish(setLocalProbe)),
      runNamedCloudProbe(PRIMARY_CLOUD_RUN_URL).then(publish((result) => {
        setGoogleProbe(result)
        setCloudProbe(result)
      })),
      runInternetProbe().then(publish(setInternetProbe)),
    ])
    logger.debug('[PROBE] Probe results received:', { local: lResult.status, google: gResult.status, internet: iResult.status })
  }, [])

  const recheck = useCallback(() => {
    logger.info('[PROBE] Manual probe recheck requested')
    if (intervalRef.current) clearInterval(intervalRef.current)
    runAll()
    intervalRef.current = setInterval(runAll, INTERVAL_MS)
  }, [runAll])

  useEffect(() => {
    runAll()
    intervalRef.current = setInterval(runAll, INTERVAL_MS)
    return () => {
      runRef.current += 1
      if (intervalRef.current) clearInterval(intervalRef.current)
    }
  }, [runAll])

  useEffect(() => {
    const handleStatusChange = (e) => {
      const detail = e.detail || {}
      logger.debug('[PROBE] SSE sync status changed:', detail)
      let status = 'checking'
      if (detail.status === 'connected') {
        status = 'online'
      } else if (detail.status === 'error' || detail.status === 'offline' || detail.status === 'disconnected') {
        status = 'offline'
      }
      setSseProbe({
        status,
        ms: null,
        error: detail.error || (detail.status === 'disconnected' ? 'Disconnected' : null)
      })
    }

    window.addEventListener('sync-status-change', handleStatusChange)
    
    // Initial status request
    window.dispatchEvent(new CustomEvent('sync-status-request'))

    if (window.__syncStatus) {
      handleStatusChange({ detail: window.__syncStatus })
    }

    return () => {
      window.removeEventListener('sync-status-change', handleStatusChange)
    }
  }, [])

  return { localProbe, googleProbe, hfProbe, cloudProbe, internetProbe, sseProbe, recheck }
}
