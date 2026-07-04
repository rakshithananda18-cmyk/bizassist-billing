import { useState, useEffect, useCallback } from 'react'
import { useAuth } from '../../contexts/AuthContext'
import { API_BASE } from '../../config'
import { Section } from '../../components/ui'
import { Icon } from '../../components/icons'

/**
 * AdminTelemetry — Phase B.2 + B.3 of the Admin Console plan.
 * Tabs: Events (filterable telemetry.jsonl viewer) · Devices (latest per
 * install) · Server Log (bizassist.log tail) · Audit (admin_audit.jsonl).
 */

const LEVEL_COLORS = {
  error: { bg: 'rgba(192,57,43,0.12)', fg: '#c0392b' },
  warn:  { bg: 'rgba(201,150,66,0.15)', fg: '#b07d2b' },
  info:  { bg: 'rgba(58,154,92,0.10)',  fg: '#3a9a5c' },
}

function LevelBadge({ level }) {
  const c = LEVEL_COLORS[level] || LEVEL_COLORS.info
  return (
    <span className="tag" style={{ background: c.bg, color: c.fg, fontWeight: 700, textTransform: 'uppercase', fontSize: 10 }}>
      {level || 'info'}
    </span>
  )
}

function fmtTime(iso) {
  if (!iso) return '—'
  try { return new Date(iso).toLocaleString() } catch { return iso }
}

const TABS = [
  { key: 'events',  label: 'Events' },
  { key: 'devices', label: 'Devices' },
  { key: 'server',  label: 'Server Log' },
  { key: 'audit',   label: 'Audit Trail' },
]

export default function AdminTelemetry() {
  const { authFetch } = useAuth()
  const [tab, setTab] = useState('events')
  const [loading, setLoading] = useState(false)

  // Events
  const [events, setEvents] = useState([])
  const [filters, setFilters] = useState({ device: '', event: '', level: '', limit: 200 })
  const [expanded, setExpanded] = useState(null)

  // Devices / server log / audit
  const [devices, setDevices] = useState([])
  const [serverLog, setServerLog] = useState({ path: null, lines: [] })
  const [audit, setAudit] = useState([])

  const loadEvents = useCallback(async () => {
    setLoading(true)
    try {
      const params = new URLSearchParams()
      if (filters.device) params.set('device', filters.device)
      if (filters.event) params.set('event', filters.event)
      if (filters.level) params.set('level', filters.level)
      params.set('limit', filters.limit || 200)
      const res = await authFetch(`${API_BASE}/admin/telemetry?${params}`)
      if (res.ok) setEvents((await res.json()).events || [])
    } catch (err) { console.error(err) } finally { setLoading(false) }
  }, [authFetch, filters])

  const loadTab = useCallback(async (t) => {
    setLoading(true)
    try {
      if (t === 'devices') {
        const res = await authFetch(`${API_BASE}/admin/telemetry/devices`)
        if (res.ok) setDevices(await res.json())
      } else if (t === 'server') {
        const res = await authFetch(`${API_BASE}/admin/server-log?lines=300`)
        if (res.ok) setServerLog(await res.json())
      } else if (t === 'audit') {
        const res = await authFetch(`${API_BASE}/admin/audit-log?limit=200`)
        if (res.ok) setAudit(await res.json())
      }
    } catch (err) { console.error(err) } finally { setLoading(false) }
  }, [authFetch])

  useEffect(() => {
    if (tab === 'events') loadEvents()
    else loadTab(tab)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tab])

  return (
    <div className="admin-main" style={{ margin: 0, padding: 0 }}>
      <div className="admin-header-row" style={{ borderBottom: '1.5px solid var(--border-color)', paddingBottom: 20 }}>
        <div className="admin-title-group">
          <h1>✦ TELEMETRY & LOGS</h1>
          <p>Field-install diagnostics, server log tail, and the admin audit trail</p>
        </div>
        <button className="btn-flush" onClick={() => (tab === 'events' ? loadEvents() : loadTab(tab))} style={{ padding: '10px 16px', fontSize: 13 }}>
          ↻ Refresh
        </button>
      </div>

      {/* Sub-tabs */}
      <div style={{ display: 'flex', gap: 6, marginTop: 20 }}>
        {TABS.map(t => (
          <button
            key={t.key}
            className="btn-flush"
            onClick={() => setTab(t.key)}
            style={{
              padding: '8px 16px', fontSize: 13,
              background: tab === t.key ? 'var(--accent-soft)' : 'transparent',
              color: tab === t.key ? 'var(--accent-color)' : 'var(--secondary-text)',
              fontWeight: tab === t.key ? 600 : 500,
            }}
          >
            {t.label}
          </button>
        ))}
      </div>

      {/* ── EVENTS ── */}
      {tab === 'events' && (
        <Section title="Telemetry Events (newest first)" icon={<Icon name="chart" size={16} />} noPad style={{ marginTop: 16 }}>
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', padding: '12px 16px 0' }}>
            <input placeholder="Device id contains…" value={filters.device}
                   onChange={e => setFilters(f => ({ ...f, device: e.target.value }))}
                   style={{ fontSize: 12, padding: '6px 10px' }} />
            <input placeholder="Event name (exact)" value={filters.event}
                   onChange={e => setFilters(f => ({ ...f, event: e.target.value }))}
                   style={{ fontSize: 12, padding: '6px 10px' }} />
            <select value={filters.level} onChange={e => setFilters(f => ({ ...f, level: e.target.value }))}
                    style={{ fontSize: 12, padding: '6px 10px' }}>
              <option value="">All levels</option>
              <option value="info">info</option>
              <option value="warn">warn</option>
              <option value="error">error</option>
            </select>
            <button className="btn-flush" onClick={loadEvents} style={{ fontSize: 12 }}>Apply</button>
          </div>

          {loading ? <div className="vskel" style={{ margin: 16 }}></div> : (
            <div className="admin-table-wrap" style={{ overflowX: 'auto', width: '100%' }}>
              <table className="admin-table" style={{ width: '100%', marginTop: 12 }}>
                <thead>
                  <tr>
                    <th>Received</th>
                    <th>Level</th>
                    <th>Event</th>
                    <th>Source</th>
                    <th>Device</th>
                    <th>Version</th>
                    <th>Payload</th>
                  </tr>
                </thead>
                <tbody>
                  {events.length === 0 ? (
                    <tr><td colSpan="7" style={{ textAlign: 'center', color: 'var(--secondary-text)', padding: 30 }}>
                      No telemetry events match. Installs report here automatically.
                    </td></tr>
                  ) : events.map((ev, i) => (
                    <tr key={i} style={{ verticalAlign: 'top' }}>
                      <td style={{ whiteSpace: 'nowrap', fontSize: 12 }}>{fmtTime(ev.received_at)}</td>
                      <td><LevelBadge level={ev.level} /></td>
                      <td style={{ fontWeight: 600, color: ev.level === 'error' ? '#c0392b' : 'var(--text-color)' }}>{ev.event}</td>
                      <td style={{ fontSize: 12 }}>{ev.source}</td>
                      <td style={{ fontFamily: "'Geist Mono',monospace", fontSize: 11, opacity: 0.8 }}>{(ev.device_id || '').slice(0, 12)}</td>
                      <td style={{ fontSize: 12 }}>{ev.app_version || '—'}<span style={{ opacity: 0.6 }}> {ev.platform || ''}</span></td>
                      <td>
                        {ev.payload ? (
                          <button className="btn-flush" style={{ fontSize: 11 }} onClick={() => setExpanded(expanded === i ? null : i)}>
                            {expanded === i ? 'Hide' : 'View'}
                          </button>
                        ) : '—'}
                        {expanded === i && ev.payload && (
                          <pre style={{
                            marginTop: 8, padding: 10, borderRadius: 8, maxWidth: 480, maxHeight: 260,
                            overflow: 'auto', fontSize: 11, background: 'var(--hover-bg)',
                            border: '1px solid var(--border-color)', whiteSpace: 'pre-wrap', wordBreak: 'break-word',
                          }}>{JSON.stringify(ev.payload, null, 2)}</pre>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Section>
      )}

      {/* ── DEVICES ── */}
      {tab === 'devices' && (
        <Section title="Devices (latest report per install)" icon={<Icon name="users" size={16} />} noPad style={{ marginTop: 16 }}>
          {loading ? <div className="vskel" style={{ margin: 16 }}></div> : (
            <div className="admin-table-wrap" style={{ overflowX: 'auto', width: '100%' }}>
              <table className="admin-table" style={{ width: '100%', marginTop: 12 }}>
                <thead>
                  <tr><th>Device</th><th>App Version</th><th>Platform</th><th>Source</th><th>Last Seen</th><th>Last Event</th></tr>
                </thead>
                <tbody>
                  {devices.length === 0 ? (
                    <tr><td colSpan="6" style={{ textAlign: 'center', color: 'var(--secondary-text)', padding: 30 }}>No devices have reported telemetry yet.</td></tr>
                  ) : devices.map((d, i) => (
                    <tr key={i}>
                      <td style={{ fontFamily: "'Geist Mono',monospace", fontSize: 11 }}>{d.device_id}</td>
                      <td style={{ fontWeight: 600 }}>{d.app_version || '—'}</td>
                      <td>{d.platform || '—'}</td>
                      <td style={{ fontSize: 12 }}>{d.source}</td>
                      <td style={{ fontSize: 12, whiteSpace: 'nowrap' }}>{fmtTime(d.last_seen)}</td>
                      <td><span style={{ display: 'inline-flex', gap: 6, alignItems: 'center' }}><LevelBadge level={d.last_level} /> {d.last_event}</span></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Section>
      )}

      {/* ── SERVER LOG ── */}
      {tab === 'server' && (
        <Section title={`Server Log Tail ${serverLog.path ? `(${serverLog.path})` : ''}`} icon={<Icon name="file" size={16} />} style={{ marginTop: 16 }}>
          {loading ? <div className="vskel"></div> : serverLog.lines.length === 0 ? (
            <div style={{ color: 'var(--secondary-text)', padding: 12 }}>
              No server log file found on this backend (HF Spaces logs to console — check the Space logs panel).
            </div>
          ) : (
            <pre style={{
              padding: 14, borderRadius: 10, maxHeight: 520, overflow: 'auto', fontSize: 11.5,
              background: 'var(--hover-bg)', border: '1px solid var(--border-color)',
              whiteSpace: 'pre-wrap', wordBreak: 'break-word', lineHeight: 1.5,
            }}>{serverLog.lines.join('\n')}</pre>
          )}
        </Section>
      )}

      {/* ── AUDIT TRAIL ── */}
      {tab === 'audit' && (
        <Section title="Admin Audit Trail (who did what, when)" icon={<Icon name="settings" size={16} />} noPad style={{ marginTop: 16 }}>
          {loading ? <div className="vskel" style={{ margin: 16 }}></div> : (
            <div className="admin-table-wrap" style={{ overflowX: 'auto', width: '100%' }}>
              <table className="admin-table" style={{ width: '100%', marginTop: 12 }}>
                <thead>
                  <tr><th>Time (UTC)</th><th>Admin</th><th>Action</th><th>Target</th><th>Details</th></tr>
                </thead>
                <tbody>
                  {audit.length === 0 ? (
                    <tr><td colSpan="5" style={{ textAlign: 'center', color: 'var(--secondary-text)', padding: 30 }}>No admin mutations recorded yet.</td></tr>
                  ) : audit.map((a, i) => {
                    const { target, target_bizid, target_username, ...rest } = a.details || {}
                    return (
                      <tr key={i}>
                        <td style={{ whiteSpace: 'nowrap', fontSize: 12 }}>{fmtTime(a.timestamp)}</td>
                        <td>
                          <span style={{ fontWeight: 600, fontSize: 12 }}>{a.admin_username || `#${a.admin_id}`}</span>
                          {a.admin_bizid && (
                            <span style={{ display: 'block', fontFamily: "'Geist Mono',monospace", fontSize: 10, opacity: 0.7 }}>{a.admin_bizid}</span>
                          )}
                        </td>
                        <td style={{ fontWeight: 600, color: 'var(--accent-color)' }}>{a.action}</td>
                        <td>
                          {target_username || target_bizid ? (
                            <>
                              <span style={{ fontWeight: 500, fontSize: 12 }}>{target_username || `#${target}`}</span>
                              {target_bizid && (
                                <span style={{ display: 'block', fontFamily: "'Geist Mono',monospace", fontSize: 10, opacity: 0.7 }}>{target_bizid}</span>
                              )}
                            </>
                          ) : (target != null ? `#${target}` : '—')}
                        </td>
                        <td style={{ fontSize: 12, fontFamily: "'Geist Mono',monospace", opacity: 0.85 }}>
                          {Object.keys(rest).length ? JSON.stringify(rest) : '—'}
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          )}
        </Section>
      )}
    </div>
  )
}
