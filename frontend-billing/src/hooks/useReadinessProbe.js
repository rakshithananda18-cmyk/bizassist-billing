import { useState, useEffect, useCallback, useRef } from 'react'
import { logger } from '../utils/logger'

const CLOUD_URL =
  import.meta.env.VITE_API_URL || 'https://rakshit-dev-bizassist.hf.space'

const LOCAL_URL = 'http://localhost:8001'

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
    const res = await fetchWithTimeout(`${LOCAL_URL}/health`, 500, { mode: 'cors' })
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
      const onLocalhost =
        window.location.hostname === 'localhost' ||
        window.location.hostname === '127.0.0.1'
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

  const intervalRef = useRef(null)

  const runAll = useCallback(async () => {
    setLocalProbe(INIT)
    setCloudProbe(INIT)
    setInternetProbe(INIT)

    logger.debug('[PROBE] Initiating readiness probes (local backend, cloud backend, internet connectivity)...')
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

  return { localProbe, cloudProbe, internetProbe, recheck }
}
