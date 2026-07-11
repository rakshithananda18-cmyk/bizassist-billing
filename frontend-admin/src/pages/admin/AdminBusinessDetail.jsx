// AdminBusinessDetail — one screen per merchant for remote debugging.
// ===================================================================
// REVIEW_1 §4.2: everything support needs on a single page — fleet stats,
// sync health (sync doctor verdict + reasons), latest telemetry scoped by
// BizID, server-log tail filtered to this business, plan & limits at a
// glance, and the session kill-switch (force logout).
import { useState, useEffect, useCallback } from 'react'
import { useParams, Link } from 'react-router-dom'
import { useAuth } from '../../contexts/AuthContext'
import { useDialog } from '../../contexts/DialogContext'
import { logger } from '../../utils/logger'
import { API_BASE } from '../../config'
import { Section } from '../../components/ui'
import { Icon } from '../../components/icons'

const HEALTH_COLORS = { green: '#3a9a5c', amber: '#b7791f', red: '#c53030' }

function Stat({ label, value, mono }) {
  return (
    <div style={{ minWidth: 120 }}>
      <div style={{ fontSize: 11, textTransform: 'uppercase', letterSpacing: '0.06em', color: 'var(--secondary-text)', marginBottom: 4 }}>{label}</div>
      <div style={{ fontSize: 18, fontWeight: 600, fontFamily: mono ? "'Geist Mono',monospace" : "'Crimson Pro',serif" }}>{value}</div>
    </div>
  )
}

export default function AdminBusinessDetail() {
  const { id } = useParams()
  const { authFetch } = useAuth()
  const { showAlert, showConfirm, showError } = useDialog()

  const [business, setBusiness] = useState(null)     // row from /admin/businesses
  const [syncHealth, setSyncHealth] = useState(null) // row from /admin/sync-doctor
  const [telemetry, setTelemetry] = useState([])
  const [serverLog, setServerLog] = useState('')
  const [limits, setLimits] = useState(null)
  const [loading, setLoading] = useState(true)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const [bizRes, doctorRes, limitsRes] = await Promise.all([
        authFetch(`${API_BASE}/admin/businesses`),
        authFetch(`${API_BASE}/admin/sync-doctor`),
        authFetch(`${API_BASE}/admin/rate-limits/${id}`),
      ])
      let biz = null
      if (bizRes.ok) {
        const all = await bizRes.json()
        biz = all.find(b => String(b.id) === String(id)) || null
        setBusiness(biz)
      }
      if (doctorRes.ok) {
        const rows = await doctorRes.json()
        setSyncHealth(rows.find(r => String(r.business_id) === String(id)) || null)
      }
      if (limitsRes.ok) setLimits(await limitsRes.json())

      // Telemetry + logs are scoped by BizID / username, which we only know
      // after the fleet fetch resolves.
      if (biz) {
        const [telRes, logRes] = await Promise.all([
          biz.bizid
            ? authFetch(`${API_BASE}/admin/telemetry?bizid=${encodeURIComponent(biz.bizid)}&limit=50`)
            : Promise.resolve(null),
          authFetch(`${API_BASE}/admin/server-log?lines=300&q=${encodeURIComponent(biz.bizid || biz.username)}`),
        ])
        if (telRes && telRes.ok) {
          const t = await telRes.json()
          setTelemetry(Array.isArray(t) ? t : (t.events || []))
        }
        if (logRes.ok) {
          const l = await logRes.json()
          setServerLog(typeof l === 'string' ? l : (l.lines || []).join('\n') || l.log || '')
        }
      }
    } catch (err) {
      logger.error(err)
    } finally {
      setLoading(false)
    }
  }, [id])

  useEffect(() => { load() }, [load])

  async function handleForceLogout() {
    if (!(await showConfirm(
      `Revoke ALL active sessions for "${business?.business_name}"? Every logged-in device (owner + staff) will need to sign in again within ~30 seconds.`
    ))) return
    try {
      const res = await authFetch(`${API_BASE}/admin/force-logout/${id}`, { method: 'POST' })
      const data = await res.json()
      if (!res.ok) throw new Error(data.detail || 'Force logout failed')
      await showAlert(data.message)
    } catch (err) {
      await showError(err)
    }
  }

  async function handleFlushCache() {
    try {
      const res = await authFetch(`${API_BASE}/admin/flush-cache/${id}`, { method: 'POST' })
      const data = await res.json()
      await showAlert(data.message || 'Cache flushed.')
    } catch (err) {
      await showError(err)
    }
  }

  async function handleDownloadLogs() {
    try {
      const res = await authFetch(`${API_BASE}/admin/business-logs/${id}`)
      if (res.status === 404) { await showAlert('No uploaded logs from this business yet.'); return }
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const blob = await res.blob()
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `business-${id}-logs.tar.gz`
      document.body.appendChild(a); a.click(); a.remove()
      setTimeout(() => URL.revokeObjectURL(url), 5000)
    } catch (err) {
      await showError(err)
    }
  }

  const health = syncHealth?.status || 'green'

  return (
    <div className="admin-main" style={{ margin: 0, padding: 0 }}>
      {/* Header */}
      <div className="admin-header-row" style={{ borderBottom: '1.5px solid var(--border-color)', paddingBottom: 20 }}>
        <div className="admin-title-group">
          <div style={{ fontSize: 12, marginBottom: 6 }}>
            <Link to="/admin/businesses" style={{ color: 'var(--secondary-text)', textDecoration: 'none' }}>← Businesses</Link>
          </div>
          <h1 style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            {business?.business_name || `Business #${id}`}
            {business?.plan && (
              <span className="tag" style={{
                background: business.plan === 'pro' ? 'rgba(58,154,92,0.12)' : 'var(--accent-soft)',
                color: business.plan === 'pro' ? '#3a9a5c' : 'var(--secondary-text)',
                fontWeight: 700, textTransform: 'uppercase', fontSize: 10,
              }}>{business.plan}</span>
            )}
            {syncHealth && (
              <span className="tag" title={(syncHealth.reasons || []).join('; ') || 'Sync healthy'} style={{
                background: `${HEALTH_COLORS[health]}22`, color: HEALTH_COLORS[health],
                fontWeight: 700, textTransform: 'uppercase', fontSize: 10,
              }}>SYNC {health}</span>
            )}
          </h1>
          <p style={{ fontFamily: "'Geist Mono',monospace", fontSize: 12 }}>
            {business?.bizid || '—'} · {business?.username || ''} · mode: {business?.hosting_mode || 'local'}
          </p>
        </div>
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
          <button className="btn-flush" onClick={load}><Icon name="refresh" size={12} /> Refresh</button>
          <button className="btn-flush" onClick={handleDownloadLogs}>Download logs</button>
          <button className="btn-flush" onClick={handleFlushCache}>Flush cache</button>
          <button className="btn-wipe-row" onClick={handleForceLogout} title="Revoke every active session for this business">
            Force logout
          </button>
        </div>
      </div>

      {loading && <div className="vskel" style={{ padding: 20, marginTop: 24 }}></div>}

      {!loading && !business && (
        <div style={{ padding: 40, textAlign: 'center', color: 'var(--secondary-text)' }}>
          Business #{id} not found.
        </div>
      )}

      {!loading && business && (
        <>
          {/* Overview strip */}
          <div className="widget" style={{ marginTop: 24, display: 'flex', gap: 32, flexWrap: 'wrap' }}>
            <Stat label="Invoices" value={business.invoice_count} />
            <Stat label="Revenue" value={`₹${(business.total_revenue || 0).toLocaleString('en-IN')}`} />
            <Stat label="Inventory items" value={business.inventory_count} />
            <Stat label="Uploads" value={business.upload_count} />
            <Stat label="Last sync" value={business.last_sync_at ? business.last_sync_at.slice(0, 16).replace('T', ' ') : 'never'} mono />
            <Stat label="Queue depth" value={business.sync_queue_depth ?? 0} mono />
            {limits && (
              <Stat label="Rate limit"
                value={limits.configured
                  ? `${limits.requests_per_minute}/min · ${limits.requests_per_day}/day`
                  : 'defaults'} mono />
            )}
          </div>

          {/* Sync health */}
          <Section title="Sync health" icon={<Icon name="refresh" size={16} />} collapsible style={{ marginTop: 24 }}>
            {syncHealth ? (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                <div style={{ display: 'flex', gap: 24, flexWrap: 'wrap' }}>
                  <Stat label="Verdict" value={health.toUpperCase()} />
                  <Stat label="Pending ops" value={syncHealth.pending_ops} mono />
                  <Stat label="Oldest pending" value={syncHealth.oldest_pending_minutes != null ? `${syncHealth.oldest_pending_minutes} min` : '—'} mono />
                  <Stat label="Recent failures" value={`${syncHealth.recent_failures}/20`} mono />
                </div>
                {(syncHealth.reasons || []).length > 0 && (
                  <ul style={{ margin: '4px 0 0 18px', color: HEALTH_COLORS[health], fontSize: 13 }}>
                    {syncHealth.reasons.map((r, i) => <li key={i}>{r}</li>)}
                  </ul>
                )}
              </div>
            ) : (
              <div style={{ color: 'var(--secondary-text)', fontSize: 13 }}>No sync data for this business.</div>
            )}
          </Section>

          {/* Telemetry */}
          <Section title="Recent telemetry" icon={<Icon name="file" size={16} />} count={telemetry.length} collapsible noPad style={{ marginTop: 24 }}>
            <div className="admin-table-wrap" style={{ overflowX: 'auto', width: '100%' }}>
              <table className="admin-table" style={{ width: '100%', marginTop: 12 }}>
                <thead>
                  <tr><th>Time</th><th>Level</th><th>Event</th><th>Device</th><th>Payload</th></tr>
                </thead>
                <tbody>
                  {telemetry.length === 0 ? (
                    <tr><td colSpan="5" style={{ textAlign: 'center', color: 'var(--secondary-text)', padding: 24 }}>
                      No telemetry from this business yet.
                    </td></tr>
                  ) : telemetry.map((t, i) => (
                    <tr key={i}>
                      <td style={{ fontFamily: "'Geist Mono',monospace", fontSize: 11, whiteSpace: 'nowrap' }}>
                        {(t.timestamp || t.ts || '').slice(0, 19).replace('T', ' ')}
                      </td>
                      <td>
                        <span className="tag" style={{
                          fontSize: 10, fontWeight: 700, textTransform: 'uppercase',
                          background: (t.level === 'error' || t.level === 'warn') ? 'rgba(197,48,48,0.12)' : 'var(--hover-bg)',
                          color: (t.level === 'error' || t.level === 'warn') ? '#c53030' : 'var(--secondary-text)',
                        }}>{t.level || 'info'}</span>
                      </td>
                      <td style={{ fontWeight: 600 }}>{t.event}</td>
                      <td style={{ fontFamily: "'Geist Mono',monospace", fontSize: 11 }}>{t.device || t.device_id || '—'}</td>
                      <td style={{ fontSize: 11, color: 'var(--secondary-text)', maxWidth: 380, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}
                        title={JSON.stringify(t.payload || t.data || {})}>
                        {JSON.stringify(t.payload || t.data || {})}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Section>

          {/* Server log tail */}
          <Section title="Server log (this business)" icon={<Icon name="monitor" size={16} />} collapsible defaultOpen={false} style={{ marginTop: 24 }}>
            {serverLog ? (
              <pre style={{
                margin: 0, padding: 14, borderRadius: 8, background: 'var(--hover-bg)',
                fontSize: 11, fontFamily: "'Geist Mono',monospace", lineHeight: 1.6,
                maxHeight: 420, overflow: 'auto', whiteSpace: 'pre-wrap', wordBreak: 'break-word',
              }}>{serverLog}</pre>
            ) : (
              <div style={{ color: 'var(--secondary-text)', fontSize: 13 }}>No matching server-log lines.</div>
            )}
          </Section>
        </>
      )}
    </div>
  )
}
