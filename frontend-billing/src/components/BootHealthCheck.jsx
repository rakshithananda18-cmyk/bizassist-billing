import { runAsync } from '../utils/asyncAction'
import { useEffect, useState, useCallback, useRef } from 'react'
import { API_BASE, CLOUD_URL, IS_LOCAL_APP } from '../config'
import { sendDiagnostics } from '../utils/telemetry'
import { logger } from '../utils/logger'

/**
 * BootHealthCheck — a first-run / on-demand self-test so field installs can
 * diagnose themselves instead of failing silently. Checks the things that
 * actually block the app: is the active backend reachable, is the cloud
 * reachable (needed for cloud/hybrid), is the DB connected, and is the client
 * clock roughly in sync with the server (JWTs fail on large skew).
 *
 * Self-contained: pulls only from config + telemetry, so it can be dropped in
 * at boot (e.g. from AppLayout) without new wiring. Set `auto` to run on mount;
 * `onClose` renders a dismiss button.
 */

const CHECK = async (base, controller) => {
  const t0 = Date.now()
  const id = setTimeout(() => controller.abort(), 6000)
  try {
    const res = await fetch(`${base.replace(/\/$/, '')}/health`, { signal: controller.signal, mode: 'cors' })
    const ms = Date.now() - t0
    if (!res.ok) return { ok: false, ms, detail: `HTTP ${res.status}` }
    const body = await res.json().catch(() => null)
    if (!body || !['ok', 'error'].includes(body.status)) {
      return { ok: false, ms, detail: 'Server returned an invalid health response.' }
    }
    // Clock skew: compare server time (if present) to ours.
    let skewMs = null
    const serverTime = body.time || body.now || res.headers?.get?.('date')
    if (serverTime) {
      const st = new Date(serverTime).getTime()
      if (!Number.isNaN(st)) skewMs = Math.abs(Date.now() - st)
    }
    return {
      ok: body.status === 'ok' && body.db === 'connected',
      ms,
      db: body.db || null,
      dbType: body.db_type || null,
      version: body.version || null,
      skewMs,
      detail: body.db && body.db !== 'connected' ? `DB ${body.db}`
        : body.db !== 'connected' ? 'Database connection not verified.'
        : body.status !== 'ok' ? 'Server reported an unhealthy state.' : null,
    }
  } catch (err) {
    return { ok: false, ms: Date.now() - t0, detail: err?.name === 'AbortError' ? 'Timeout' : (err?.message || 'Network error') }
  } finally {
    clearTimeout(id)
  }
}

function Row({ label, state, running }) {
  const color = state == null ? 'var(--text-muted)' : state.ok ? 'var(--success)' : 'var(--danger)'
  const icon = state == null ? '…' : state.ok ? '✓' : '✕'
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '7px 0', fontSize: '0.86rem' }}>
      <span style={{ width: 18, textAlign: 'center', color, fontWeight: 700 }}>{icon}</span>
      <span style={{ flex: 1, color: 'var(--text-primary)' }}>{label}</span>
      <span style={{ color, fontSize: '0.78rem' }} role="status">
        {state == null ? (running ? 'checking…' : 'Not checked') : state.ok ? (state.value || `${state.ms}ms`) : (state.detail || 'failed')}
      </span>
    </div>
  )
}

export default function BootHealthCheck({ auto = true, onClose = null }) {
  const [active, setActive] = useState(null)
  const [cloud, setCloud] = useState(null)
  const [running, setRunning] = useState(false)
  const [sent, setSent] = useState(false)
  const requestRef = useRef(0)
  const controllersRef = useRef([])

  const run = useCallback(async () => {
    const request = ++requestRef.current
    controllersRef.current.forEach(controller => controller.abort())
    const controllers = [new AbortController(), new AbortController()]
    controllersRef.current = controllers
    setRunning(true); setSent(false)
    setActive(null); setCloud(null)
    const [a, c] = await Promise.all([
      CHECK(API_BASE, controllers[0]).then(result => {
        if (request === requestRef.current) setActive(result)
        return result
      }),
      // Only probe cloud separately when it differs from the active backend.
      CLOUD_URL && CLOUD_URL !== API_BASE ? CHECK(CLOUD_URL, controllers[1]).then(result => {
        if (request === requestRef.current) setCloud(result)
        return result
      }) : Promise.resolve(null),
    ])
    if (request !== requestRef.current) return
    setRunning(false)
    logger?.info?.('[HEALTH] self-test', { active: a?.ok, cloud: c?.ok })
  }, [])

  useEffect(() => {
    if (auto) runAsync(() => run())
    return () => {
      requestRef.current += 1
      controllersRef.current.forEach(controller => controller.abort())
    }
  }, [auto, run])

  const skew = active?.skewMs
  const skewBad = skew != null && skew > 120000  // >2 min → JWT trouble

  const report = () => {
    const queued = sendDiagnostics('boot_health_check', {
      active_ok: !!active?.ok, active_ms: active?.ms, active_detail: active?.detail,
      cloud_ok: cloud ? !!cloud.ok : null, cloud_detail: cloud?.detail,
      db: active?.db, skew_ms: skew,
    }, { userInitiated: true })
    setSent(queued === true)
  }

  return (
    <div style={{
      border: '1px solid var(--border)', borderRadius: 12, padding: '16px 18px',
      background: 'var(--bg-2)', maxWidth: 460,
    }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 6 }}>
        <div style={{ fontWeight: 700, fontSize: '0.95rem', color: 'var(--text-primary)' }}>System check</div>
        {onClose && (
          <button onClick={onClose} style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'var(--text-muted)', fontSize: 16 }}>✕</button>
        )}
      </div>

      <div style={{ fontSize: '0.72rem', color: 'var(--text-muted)', overflowWrap: 'anywhere', marginBottom: 6 }}>Active server: {API_BASE}</div>
      <Row label="This device's backend" state={active} running={running} />
      {CLOUD_URL && CLOUD_URL !== API_BASE && (
        <Row label={IS_LOCAL_APP ? 'Cloud server (for sync)' : 'Cloud server'} state={cloud} running={running} />
      )}
      <Row label="Database connection" running={running} state={active == null ? null : { ok: active.db === 'connected', ms: active.ms, detail: active.db ? `DB ${active.db}` : 'Not verified' }} />
      {(active?.dbType || active?.version) && (
        <div style={{ fontSize: '0.72rem', color: 'var(--text-muted)', marginTop: 4 }}>
          {[active.dbType, active.version && `Version ${active.version}`].filter(Boolean).join(' · ')}
        </div>
      )}
      {skew != null && (
        <Row label="Clock in sync with server" state={{ ok: !skewBad, value: `${Math.round(skew / 1000)}s difference`, detail: skewBad ? 'Clock skew — fix device time' : null }} />
      )}

      <div style={{ display: 'flex', gap: 8, marginTop: 12 }}>
        <button className="btn btn-ghost" onClick={run} disabled={running} style={{ flex: 1 }}>
          {running ? 'Checking…' : 'Re-check'}
        </button>
        <button className="btn" onClick={report} disabled={running || sent} style={{ flex: 1 }}>
          {sent ? 'Diagnostics queued ✓' : 'Send diagnostics'}
        </button>
      </div>
      <div style={{ fontSize: '0.72rem', color: 'var(--text-muted)', marginTop: 8, lineHeight: 1.4 }}>
        "Send diagnostics" sends this system check and, if you allow optional diagnostics, recent app errors to support. It includes your business id when signed in, but no invoice or customer records.
      </div>
    </div>
  )
}
