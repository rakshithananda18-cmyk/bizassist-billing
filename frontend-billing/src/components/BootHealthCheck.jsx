import { useEffect, useState, useCallback } from 'react'
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

const CHECK = async (base) => {
  const t0 = Date.now()
  try {
    const ctrl = new AbortController()
    const id = setTimeout(() => ctrl.abort(), 6000)
    const res = await fetch(`${base}/health`, { signal: ctrl.signal, mode: 'cors' })
    clearTimeout(id)
    const ms = Date.now() - t0
    if (!res.ok) return { ok: false, ms, detail: `HTTP ${res.status}` }
    const body = await res.json().catch(() => ({}))
    // Clock skew: compare server time (if present) to ours.
    let skewMs = null
    const serverTime = body.time || body.now || res.headers.get('date')
    if (serverTime) {
      const st = new Date(serverTime).getTime()
      if (!Number.isNaN(st)) skewMs = Math.abs(Date.now() - st)
    }
    return {
      ok: body.status ? body.status === 'ok' : true,
      ms,
      db: body.db || null,
      skewMs,
      detail: body.db && body.db !== 'connected' ? `DB ${body.db}` : null,
    }
  } catch (err) {
    return { ok: false, ms: Date.now() - t0, detail: err?.name === 'AbortError' ? 'Timeout' : (err?.message || 'Network error') }
  }
}

function Row({ label, state }) {
  const color = state == null ? 'var(--text-muted)' : state.ok ? 'var(--success)' : 'var(--danger)'
  const icon = state == null ? '…' : state.ok ? '✓' : '✕'
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '7px 0', fontSize: '0.86rem' }}>
      <span style={{ width: 18, textAlign: 'center', color, fontWeight: 700 }}>{icon}</span>
      <span style={{ flex: 1, color: 'var(--text-primary)' }}>{label}</span>
      <span style={{ color, fontSize: '0.78rem' }}>
        {state == null ? 'checking…' : state.ok ? `${state.ms}ms` : (state.detail || 'failed')}
      </span>
    </div>
  )
}

export default function BootHealthCheck({ auto = true, onClose = null }) {
  const [active, setActive] = useState(null)
  const [cloud, setCloud] = useState(null)
  const [running, setRunning] = useState(false)
  const [sent, setSent] = useState(false)

  const run = useCallback(async () => {
    setRunning(true); setSent(false)
    setActive(null); setCloud(null)
    const [a, c] = await Promise.all([
      CHECK(API_BASE),
      // Only probe cloud separately when it differs from the active backend.
      CLOUD_URL && CLOUD_URL !== API_BASE ? CHECK(CLOUD_URL) : Promise.resolve(null),
    ])
    setActive(a)
    setCloud(c)
    setRunning(false)
    logger?.info?.('[HEALTH] self-test', { active: a?.ok, cloud: c?.ok })
  }, [])

  useEffect(() => { if (auto) run() }, [auto, run])

  const skew = active?.skewMs
  const skewBad = skew != null && skew > 120000  // >2 min → JWT trouble

  const report = () => {
    sendDiagnostics('boot_health_check', {
      active_ok: !!active?.ok, active_ms: active?.ms, active_detail: active?.detail,
      cloud_ok: cloud ? !!cloud.ok : null, cloud_detail: cloud?.detail,
      db: active?.db, skew_ms: skew,
    })
    setSent(true)
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

      <Row label="This device's backend" state={active} />
      {CLOUD_URL && CLOUD_URL !== API_BASE && (
        <Row label={IS_LOCAL_APP ? 'Cloud server (for sync / cloud mode)' : 'Cloud server'} state={cloud} />
      )}
      <Row label="Database connection" state={active == null ? null : { ok: !active.db || active.db === 'connected', ms: active.ms, detail: active.db && active.db !== 'connected' ? `DB ${active.db}` : null }} />
      {skew != null && (
        <Row label="Clock in sync with server" state={{ ok: !skewBad, ms: Math.round(skew / 1000) + 's off', detail: skewBad ? 'Clock skew — fix device time' : null }} />
      )}

      <div style={{ display: 'flex', gap: 8, marginTop: 12 }}>
        <button className="btn btn-ghost" onClick={run} disabled={running} style={{ flex: 1 }}>
          {running ? 'Checking…' : 'Re-check'}
        </button>
        <button className="btn" onClick={report} disabled={running || sent} style={{ flex: 1 }}>
          {sent ? 'Diagnostics sent ✓' : 'Send diagnostics'}
        </button>
      </div>
      <div style={{ fontSize: '0.72rem', color: 'var(--text-muted)', marginTop: 8, lineHeight: 1.4 }}>
        "Send diagnostics" uploads this device's recent app events (tagged with your business id) so support can debug remotely. No business data is included.
      </div>
    </div>
  )
}
