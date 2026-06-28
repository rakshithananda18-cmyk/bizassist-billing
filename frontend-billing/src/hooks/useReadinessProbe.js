import { useState, useEffect, useCallback, useRef } from 'react'
import { logger } from '../utils/logger'
import { LOCAL_URL, CLOUD_URL, IS_LOCAL_APP } from '../config'

const INTERVAL_MS = 30_000

// Timeout-aware fetch
function fetchWithTimeout(url, timeout, opts = {}) {
  const ctrl = new AbortController()
  const id = setTimeout(() => ctrl.abort(), timeout)
  return fetch(url, { ...opts, signal: ctrl.signal }).finally(() => clearTimeout(id))
}

// ── Probe runners ─────────────────────────────────────────────────────────────

async function runLocalProbe() {
  const t0 = Date.now()
  try {
    const savedLocalUrl = typeof localStorage !== 'undefined' ? localStorage.getItem('bizassist_local_backend_url') : null
    const targetLocal = savedLocalUrl || LOCAL_URL
    const res = await fetchWithTimeout(`${targetLocal}/health`, 500, { mode: 'cors' })
    const ms = Date.now() - t0
    if (!res.ok) return { status: 'offline', ms: null, error: `HTTP ${res.status}` }
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

async function runCloudProbe() {
  const t0 = Date.now()
  try {
    const res = await fetchWithTimeout(`${CLOUD_URL}/health`, 6000)
    const ms = Date.now() - t0
    if (!res.ok) return { status: 'offline', ms: null, error: `HTTP ${res.status}` }
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
  const [cloudProbe,    setCloudProbe]    = useState(INIT)
  const [internetProbe, setInternetProbe] = useState(INIT)
  const [sseProbe,      setSseProbe]      = useState(INIT)

  const intervalRef = useRef(null)

  const runAll = useCallback(async () => {
    setLocalProbe(INIT)
    setCloudProbe(INIT)
    setInternetProbe(INIT)
    setSseProbe(INIT)

    logger.debug('[PROBE] Initiating readiness probes (local backend, cloud backend, internet connectivity)...')
    
    // Request latest SSE status update
    window.dispatchEvent(new CustomEvent('sync-status-request'))

    const [lResult, cResult, iResult] = await Promise.all([
      runLocalProbe(),
      runCloudProbe(),
      runInternetProbe(),
    ])
    logger.debug('[PROBE] Probe results received:', { local: lResult.status, cloud: cResult.status, internet: iResult.status })
    setLocalProbe(lResult)
    setCloudProbe(cResult)
    setInternetProbe(iResult)
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
      } else if (detail.status === 'error' || detail.status === 'disconnected') {
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

  return { localProbe, cloudProbe, internetProbe, sseProbe, recheck }
}
