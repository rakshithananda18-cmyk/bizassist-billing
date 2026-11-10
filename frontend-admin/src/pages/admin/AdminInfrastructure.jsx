import { useState, useEffect, useCallback, useRef } from 'react'
import { useAuth } from '../../contexts/AuthContext'
import { API_BASE } from '../../config'
import { Icon } from '../../components/icons'
import { readableError } from '../../utils/httpErrors'
import '../../styles/infrastructure.css'

function formatBytes(bytes) {
  if (bytes === null || bytes === undefined || !Number.isFinite(Number(bytes))) return 'Unavailable'
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  let idx = 0
  let b = Number(bytes)
  while (b >= 1024 && idx < units.length - 1) {
    b /= 1024
    idx++
  }
  return `${b.toFixed(1)} ${units[idx]}`
}

function uptime(value) {
  if (value === null || value === undefined || !Number.isFinite(Number(value))) return 'Unavailable'
  const seconds = Math.max(0, Math.floor(value))
  return `${Math.floor(seconds / 3600)}h ${Math.floor((seconds % 3600) / 60)}m ${seconds % 60}s`
}

function metric(value, suffix = '') {
  return value === null || value === undefined || value === '' || (typeof value === 'number' && !Number.isFinite(value))
    ? 'Unavailable' : `${value}${suffix}`
}

function MetricRow({ label, value }) {
  return <div className="infra-stat"><span>{label}</span><strong>{value}</strong></div>
}

function StatusBadge({ status }) {
  const s = String(status || '').toUpperCase()
  let bg = 'var(--bg-3)'
  let color = 'var(--text-muted)'
  let border = 'var(--border)'

  if (s === 'ACTIVE' || s === 'HEALTHY' || s === 'ONLINE' || s === 'CONNECTED' || s === 'FREE_TIER') {
    bg = 'var(--success-dim)'
    color = 'var(--success)'
    border = 'color-mix(in srgb, var(--success) 25%, transparent)'
  } else if (s === 'UNAVAILABLE' || s === 'ERROR' || s === 'DOWN') {
    bg = 'var(--danger-dim)'
    color = 'var(--danger)'
    border = 'color-mix(in srgb, var(--danger) 25%, transparent)'
  } else if (s === 'WARNING' || s === 'DEGRADED') {
    bg = 'var(--warning-dim)'
    color = 'var(--warning)'
    border = 'color-mix(in srgb, var(--warning) 25%, transparent)'
  }

  return (
    <span style={{
      display: 'inline-flex',
      alignItems: 'center',
      gap: 5,
      padding: '2px 8px',
      borderRadius: 6,
      fontSize: 11,
      fontWeight: 700,
      letterSpacing: '0.04em',
      background: bg,
      color: color,
      border: `1px solid ${border}`
    }}>
      <span style={{ width: 6, height: 6, borderRadius: '50%', background: color }} />
      {s || 'UNKNOWN'}
    </span>
  )
}

function MethodBadge({ method }) {
  const m = String(method || 'GET').toUpperCase()
  const colors = {
    GET: { bg: 'rgba(49, 130, 206, 0.15)', text: '#63b3ed', border: 'rgba(49, 130, 206, 0.3)' },
    POST: { bg: 'rgba(56, 161, 105, 0.15)', text: '#68d391', border: 'rgba(56, 161, 105, 0.3)' },
    PUT: { bg: 'rgba(221, 107, 32, 0.15)', text: '#f6ad55', border: 'rgba(221, 107, 32, 0.3)' },
    DELETE: { bg: 'rgba(229, 62, 62, 0.15)', text: '#fc8181', border: 'rgba(229, 62, 62, 0.3)' },
    PATCH: { bg: 'rgba(159, 122, 234, 0.15)', text: '#b794f4', border: 'rgba(159, 122, 234, 0.3)' }
  }
  const c = colors[m] || { bg: 'rgba(255,255,255,0.08)', text: '#fff', border: 'rgba(255,255,255,0.15)' }

  return (
    <span style={{
      display: 'inline-block',
      fontFamily: 'monospace',
      fontSize: 11,
      fontWeight: 700,
      padding: '2px 6px',
      borderRadius: 4,
      background: c.bg,
      color: c.text,
      border: `1px solid ${c.border}`
    }}>
      {m}
    </span>
  )
}

function StatusCodeBadge({ code }) {
  const n = Number(code) || 0
  let color = '#48bb78'
  let bg = 'rgba(72, 187, 120, 0.12)'
  if (n >= 500) {
    color = '#f56565'
    bg = 'rgba(245, 101, 101, 0.15)'
  } else if (n >= 400) {
    color = '#ed8936'
    bg = 'rgba(237, 137, 54, 0.15)'
  } else if (n >= 300) {
    color = '#63b3ed'
    bg = 'rgba(99, 179, 237, 0.15)'
  }

  return (
    <span style={{
      fontFamily: 'monospace',
      fontSize: 11,
      fontWeight: 700,
      padding: '2px 6px',
      borderRadius: 4,
      background: bg,
      color: color
    }}>
      {code}
    </span>
  )
}

export default function AdminInfrastructure() {
  const { authFetch } = useAuth()
  const [activeTab, setActiveTab] = useState('topology') // 'topology' | 'apm' | 'traces' | 'cost'
  const [infraData, setInfraData] = useState(null)
  const [consoleData, setConsoleData] = useState(null)
  const [traces, setTraces] = useState([])
  const [tracesLoaded, setTracesLoaded] = useState(false)
  const [selectedTrace, setSelectedTrace] = useState(null)
  const [loading, setLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)
  const [error, setError] = useState(null)
  const [autoRefresh, setAutoRefresh] = useState(false)
  const [traceSearch, setTraceSearch] = useState('')
  const [traceStatusFilter, setTraceStatusFilter] = useState('all')
  const [traceMethodFilter, setTraceMethodFilter] = useState('all')

  const mounted = useRef(true)
  const pending = useRef(false)
  const hasData = useRef(false)

  const fetchAllData = useCallback(async () => {
    if (pending.current) return
    pending.current = true
    setRefreshing(true)

    try {
      const read = async (path, label, validate) => {
        try {
          const response = await authFetch(`${API_BASE}${path}`)
          if (!response.ok) {
            const body = await response.json().catch(() => ({}))
            throw new Error(`${label} (HTTP ${response.status || 'error'}): ${readableError(response.status, body)}`)
          }
          const data = await response.json()
          if (!validate(data)) throw new Error(`${label}: the server returned an unavailable or invalid response.`)
          return { data }
        } catch (requestError) {
          return { error: requestError.message || `${label}: could not reach the server.` }
        }
      }
      const [resInfra, resConsole, resTraces] = await Promise.all([
        read('/admin/infrastructure-metrics', 'Infrastructure', data => data && typeof data === 'object' && !Array.isArray(data) && data.cloud_run),
        read('/admin/console-metrics', 'Performance metrics', data => data && typeof data.traffic === 'object' && data.traffic !== null),
        read('/admin/api-traces?limit=60', 'API traces', Array.isArray),
      ])
      if (!mounted.current) return
      const previouslyLoaded = hasData.current
      if (resInfra.data) setInfraData(resInfra.data)
      if (resConsole.data) setConsoleData(resConsole.data)
      if (resTraces.data) { setTraces(resTraces.data); setTracesLoaded(true) }
      const errors = [resInfra, resConsole, resTraces].map(result => result.error).filter(Boolean)
      setError(errors.length ? `${previouslyLoaded ? 'Showing the last loaded data where a refresh failed. ' : ''}${errors.join(' · ')}` : null)
      if (resInfra.data || resConsole.data || resTraces.data) hasData.current = true
    } catch (err) {
      if (mounted.current) setError(err.message || 'Failed to fetch cloud infrastructure data.')
    } finally {
      pending.current = false
      if (mounted.current) {
        setLoading(false)
        setRefreshing(false)
      }
    }
  }, [authFetch])

  useEffect(() => {
    mounted.current = true
    fetchAllData()
    return () => { mounted.current = false }
  }, [fetchAllData])

  useEffect(() => {
    if (!autoRefresh) return
    const interval = setInterval(() => {
      if (!document.hidden && !pending.current) {
        fetchAllData()
      }
    }, 15000)
    return () => clearInterval(interval)
  }, [autoRefresh, fetchAllData])

  // Traces filtering
  const filteredTraces = (Array.isArray(traces) ? traces : []).filter(t => {
    if (traceStatusFilter !== 'all') {
      if (traceStatusFilter === '2xx' && (t.status < 200 || t.status >= 300)) return false
      if (traceStatusFilter === '4xx' && (t.status < 400 || t.status >= 500)) return false
      if (traceStatusFilter === '5xx' && t.status < 500) return false
    }
    if (traceMethodFilter !== 'all' && t.method !== traceMethodFilter) {
      return false
    }
    if (traceSearch.trim()) {
      const q = traceSearch.toLowerCase()
      const matchPath = (t.path || '').toLowerCase().includes(q)
      const matchBiz = String(t.biz_id || '').toLowerCase().includes(q)
      const matchStatus = String(t.status || '').includes(q)
      if (!matchPath && !matchBiz && !matchStatus) return false
    }
    return true
  })

  const cloud = infraData?.cloud_run
  const db = infraData?.supabase
  const edge = infraData?.vercel?.endpoints?.[0]
  const traffic = consoleData?.traffic || {}
  const latency = consoleData?.latency || {}
  const cost = consoleData?.cost || {}

  return (
    <div className="admin-main" style={{ padding: '24px 32px', maxWidth: 1400, margin: '0 auto' }}>
      {/* Mini Google Console Top Banner */}
      <div style={{
        background: 'var(--bg-2)',
        border: '1px solid var(--border)',
        borderRadius: 14,
        padding: '16px 20px',
        marginBottom: 24,
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'center',
        flexWrap: 'wrap',
        gap: 16,
        boxShadow: 'var(--shadow-sm)'
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 14 }}>
          <div style={{
            width: 42,
            height: 42,
            borderRadius: 10,
            background: 'var(--accent-dim)',
            border: '1px solid var(--border)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            color: 'var(--accent)'
          }}>
            <Icon name="server" size={22} />
          </div>
          <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <span style={{ fontSize: 16, fontWeight: 700, color: 'var(--text-primary)', letterSpacing: '-0.01em' }}>
                Infrastructure &amp; observability
              </span>
              <span style={{
                fontSize: 11,
                padding: '2px 7px',
                borderRadius: 5,
                background: 'rgba(194, 113, 79, 0.15)',
                color: 'var(--accent, #c2714f)',
                border: '1px solid rgba(194, 113, 79, 0.3)',
                fontWeight: 600
              }}>
                Platform diagnostics
              </span>
              {cloud?.status && <StatusBadge status={cloud.status} />}
            </div>
            <div style={{ fontSize: 12, color: '#8e8e93', marginTop: 3, display: 'flex', gap: 12 }}>
              <span>Runtime: <strong style={{ color: 'var(--text-primary)' }}>{cloud?.provider || 'Awaiting diagnostics'}</strong></span>
              <span>•</span>
              <span>Snapshot: <strong style={{ color: 'var(--text-primary)' }}>{infraData?.timestamp ? new Date(infraData.timestamp).toLocaleString() : 'Not yet loaded'}</strong></span>
            </div>
          </div>
        </div>

        {/* Global Controls */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <label style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 12, color: '#8e8e93', cursor: 'pointer' }}>
            <input
              type="checkbox"
              checked={autoRefresh}
              onChange={e => setAutoRefresh(e.target.checked)}
              style={{ accentColor: 'var(--accent, #c2714f)' }}
            />
            Auto-refresh (15s)
          </label>
          <button
            type="button"
            onClick={fetchAllData}
            disabled={refreshing}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 6,
              padding: '8px 14px',
              borderRadius: 8,
              background: 'rgba(255,255,255,0.06)',
              border: '1px solid var(--border)',
              color: 'var(--text-primary)',
              fontSize: 12,
              fontWeight: 600,
              cursor: 'pointer'
            }}
          >
            <Icon name="refresh" size={14} className={refreshing ? 'spinning' : ''} />
            {refreshing ? 'Polling…' : 'Refresh'}
          </button>
        </div>
      </div>

      {error && (
        <div role="alert" style={{
          padding: '12px 18px',
          borderRadius: 10,
          background: 'rgba(229, 62, 62, 0.12)',
          border: '1px solid rgba(229, 62, 62, 0.3)',
          color: 'var(--danger)',
          marginBottom: 20,
          fontSize: 13
        }}>
          <div><strong>Diagnostics could not be loaded.</strong><p>{error}</p></div>
          <button type="button" className="btn btn-secondary" disabled={refreshing} onClick={fetchAllData}>Retry diagnostics</button>
        </div>
      )}

      {/* Navigation Tabs */}
      <div style={{
        display: 'flex',
        gap: 8,
        borderBottom: '1px solid rgba(255,255,255,0.08)',
        marginBottom: 24
      }}>
        {[
          { id: 'topology', label: 'Cloud Topology & Services', icon: 'server' },
          { id: 'apm', label: 'APM & Performance Metrics', icon: 'sparkle' },
          { id: 'traces', label: `Call Hits & Tracing (${tracesLoaded ? traces.length : '—'})`, icon: 'activity' },
          { id: 'cost', label: 'Cloud Billing & Cost breakdown', icon: 'wallet' },
        ].map(tab => (
          <button
            key={tab.id}
            type="button"
            onClick={() => setActiveTab(tab.id)}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 8,
              padding: '10px 18px',
              border: 'none',
              borderBottom: activeTab === tab.id ? '2px solid var(--accent, #c2714f)' : '2px solid transparent',
              background: 'transparent',
              color: activeTab === tab.id ? '#fff' : '#8e8e93',
              fontSize: 13,
              fontWeight: 600,
              cursor: 'pointer',
              transition: 'all 0.15s ease'
            }}
          >
            <Icon name={tab.icon} size={15} />
            {tab.label}
          </button>
        ))}
      </div>

      {loading && <div className="card" role="status" style={{ padding: 24 }}>Loading infrastructure diagnostics…</div>}
      {!loading && ((activeTab === 'topology' && !infraData) || (['apm', 'cost'].includes(activeTab) && !consoleData) || (activeTab === 'traces' && !tracesLoaded)) && <div className="card" role="status" style={{ padding: 24 }}>Diagnostics unavailable. Retry to request a current snapshot.</div>}

      {/* TAB 1: TOPOLOGY — values come only from the diagnostics response. */}
      {activeTab === 'topology' && infraData && (
        <div className="infra-grid">
          <article className="card infra-card" style={{ padding: 20 }}>
            <div className="infra-card-header"><h2><Icon name="server" size={18} />{cloud?.service_name || cloud?.provider || 'Backend runtime'}</h2><StatusBadge status={cloud?.status || 'UNAVAILABLE'} /></div>
            <MetricRow label="Region" value={metric(cloud?.region)} />
            <MetricRow label="Revision" value={metric(cloud?.revision)} />
            <MetricRow label="Process Uptime" value={uptime(cloud?.uptime_seconds)} />
            <MetricRow label="Process Memory (RSS)" value={metric(cloud?.memory?.rss_mb, ' MB')} />
            <MetricRow label="CPU Utilization" value={metric(cloud?.cpu_percent, '%')} />
            <MetricRow label="Worker Threads" value={metric(cloud?.thread_count)} />
            <MetricRow label="Runtime" value={cloud?.python_version ? `Python ${cloud.python_version}` : 'Unavailable'} />
            <p className="infra-note">Process measurements describe the responding instance, not the entire deployment.</p>
          </article>

          <article className="card infra-card" style={{ padding: 20 }}>
            <div className="infra-card-header"><h2><Icon name="users" size={18} />Field Team API</h2><StatusBadge status={infraData.field_team?.status || 'UNAVAILABLE'} /></div>
            <MetricRow label="Health Endpoint" value={metric(infraData.field_team?.url)} />
            <MetricRow label="Probe HTTP Status" value={metric(infraData.field_team?.code)} />
            <MetricRow label="Probe Roundtrip" value={metric(infraData.field_team?.latency_ms, ' ms')} />
            {infraData.field_team?.error && <p className="infra-note">{infraData.field_team.error}</p>}
          </article>

          <article className="card infra-card" style={{ padding: 20 }}>
            <div className="infra-card-header"><h2><Icon name="database" size={18} />{db?.provider || 'Database'}</h2><StatusBadge status={db?.status || 'UNAVAILABLE'} /></div>
            <MetricRow label="Database Engine" value={metric(db?.dialect)} />
            <MetricRow label="Storage Footprint" value={db?.size_str ?? formatBytes(db?.size_bytes)} />
            <MetricRow label="Cache Hit Ratio" value={metric(db?.cache_hit_ratio_pct, '%')} />
            <MetricRow label="Pool Connections" value={`${metric(db?.connection_pool?.active)} active · ${metric(db?.connection_pool?.idle)} idle`} />
            <MetricRow label="Connection Capacity" value={metric(db?.connection_pool?.max)} />
            <MetricRow label="Invoices (estimate)" value={metric(db?.table_counts?.invoices)} />
            <MetricRow label="Products (estimate)" value={metric(db?.table_counts?.products)} />
            <p className="infra-note">Table counts are catalog estimates. Unavailable measurements are not reported as zero.</p>
          </article>

          <article className="card infra-card" style={{ padding: 20 }}>
            <div className="infra-card-header"><h2><Icon name="sparkle" size={18} />{infraData.vercel?.provider || 'Web endpoint'}</h2><StatusBadge status={edge?.status || 'UNAVAILABLE'} /></div>
            <MetricRow label="Primary Domain" value={metric(edge?.domain)} />
            <MetricRow label="Endpoint" value={metric(edge?.url)} />
            <MetricRow label="HTTP Status" value={metric(edge?.code)} />
            <MetricRow label="Edge Roundtrip" value={metric(edge?.latency_ms, ' ms')} />
            <MetricRow label="Edge POP Location" value={metric(edge?.edge_pop)} />
            {edge?.error && <p className="infra-note">{edge.error}</p>}
          </article>
        </div>
      )}

      {/* TAB 2: APM & PERFORMANCE */}
      {activeTab === 'apm' && consoleData && (
        <div>
          {/* APM Stats Row */}
          <div style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))',
            gap: 16,
            marginBottom: 24
          }}>
            <div style={{
              background: 'var(--bg-2, #18191c)',
              border: '1px solid var(--border)',
              borderRadius: 12,
              padding: 18
            }}>
              <div style={{ fontSize: 11, fontWeight: 700, color: '#8e8e93', textTransform: 'uppercase' }}>Current Throughput</div>
              <div style={{ fontSize: 26, fontWeight: 700, color: 'var(--text-primary)', marginTop: 6, fontFamily: 'monospace' }}>
                {metric(traffic.rpm_1m)} <span style={{ fontSize: 13, color: '#8e8e93', fontWeight: 500 }}>RPM</span>
              </div>
              <div style={{ fontSize: 12, color: '#8e8e93', marginTop: 4 }}>
                5m avg: {metric(traffic.rpm_5m)} req/min
              </div>
            </div>

            <div style={{
              background: 'var(--bg-2, #18191c)',
              border: '1px solid var(--border)',
              borderRadius: 12,
              padding: 18
            }}>
              <div style={{ fontSize: 11, fontWeight: 700, color: '#8e8e93', textTransform: 'uppercase' }}>P50 Latency (Median)</div>
              <div style={{ fontSize: 26, fontWeight: 700, color: '#48bb78', marginTop: 6, fontFamily: 'monospace' }}>
                {metric(latency.p50_ms)} <span style={{ fontSize: 13, color: '#8e8e93', fontWeight: 500 }}>ms</span>
              </div>
              <div style={{ fontSize: 12, color: '#8e8e93', marginTop: 4 }}>
                Avg: {metric(latency.avg_ms)} ms
              </div>
            </div>

            <div style={{
              background: 'var(--bg-2, #18191c)',
              border: '1px solid var(--border)',
              borderRadius: 12,
              padding: 18
            }}>
              <div style={{ fontSize: 11, fontWeight: 700, color: '#8e8e93', textTransform: 'uppercase' }}>P95 / P99 Tail Latency</div>
              <div style={{ fontSize: 26, fontWeight: 700, color: '#ed8936', marginTop: 6, fontFamily: 'monospace' }}>
                {metric(latency.p95_ms)} <span style={{ fontSize: 13, color: '#8e8e93', fontWeight: 500 }}>/ {metric(latency.p99_ms)} ms</span>
              </div>
              <div style={{ fontSize: 12, color: '#8e8e93', marginTop: 4 }}>
                95% of calls complete under {metric(latency.p95_ms)} ms
              </div>
            </div>

            <div style={{
              background: 'var(--bg-2, #18191c)',
              border: '1px solid var(--border)',
              borderRadius: 12,
              padding: 18
            }}>
              <div style={{ fontSize: 11, fontWeight: 700, color: '#8e8e93', textTransform: 'uppercase' }}>Error Rate</div>
              <div style={{
                fontSize: 26,
                fontWeight: 700,
                color: (traffic.error_rate_pct || 0) > 5 ? '#f56565' : '#48bb78',
                marginTop: 6,
                fontFamily: 'monospace'
              }}>
                {metric(traffic.error_rate_pct)}%
              </div>
              <div style={{ fontSize: 12, color: '#8e8e93', marginTop: 4 }}>
                Total calls logged: {traffic.total_requests == null ? 'Unavailable' : Number(traffic.total_requests).toLocaleString()}
              </div>
            </div>
          </div>

          {/* Status Distribution Bar */}
          <div style={{
            background: 'var(--bg-2, #18191c)',
            border: '1px solid var(--border)',
            borderRadius: 14,
            padding: 20,
            marginBottom: 24
          }}>
            <h3 style={{ margin: '0 0 14px 0', fontSize: 15, fontWeight: 700, color: 'var(--text-primary)' }}>
              HTTP Status Code Distribution (Active Instance)
            </h3>
            <div style={{ display: 'flex', height: 24, borderRadius: 6, overflow: 'hidden', background: 'rgba(255,255,255,0.05)', marginBottom: 12 }}>
              {(() => {
                const dist = traffic.status_distribution || { '2xx': 0, '3xx': 0, '4xx': 0, '5xx': 0 }
                const tot = Math.max(1, (dist['2xx'] || 0) + (dist['3xx'] || 0) + (dist['4xx'] || 0) + (dist['5xx'] || 0))
                const p2 = ((dist['2xx'] || 0) / tot) * 100
                const p3 = ((dist['3xx'] || 0) / tot) * 100
                const p4 = ((dist['4xx'] || 0) / tot) * 100
                const p5 = ((dist['5xx'] || 0) / tot) * 100
                return (
                  <>
                    <div style={{ width: `${p2}%`, background: '#48bb78' }} title={`2xx Success: ${dist['2xx']} (${p2.toFixed(1)}%)`} />
                    <div style={{ width: `${p3}%`, background: '#63b3ed' }} title={`3xx Redirect: ${dist['3xx']} (${p3.toFixed(1)}%)`} />
                    <div style={{ width: `${p4}%`, background: '#ed8936' }} title={`4xx Client Error: ${dist['4xx']} (${p4.toFixed(1)}%)`} />
                    <div style={{ width: `${p5}%`, background: '#f56565' }} title={`5xx Server Error: ${dist['5xx']} (${p5.toFixed(1)}%)`} />
                  </>
                )
              })()}
            </div>
            <div style={{ display: 'flex', gap: 20, fontSize: 12, color: '#8e8e93', flexWrap: 'wrap' }}>
              <span style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                <span style={{ width: 8, height: 8, borderRadius: '50%', background: '#48bb78' }} />
                2xx Success: <strong>{metric(traffic.status_distribution?.['2xx'])}</strong>
              </span>
              <span style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                <span style={{ width: 8, height: 8, borderRadius: '50%', background: '#63b3ed' }} />
                3xx Redirect: <strong>{metric(traffic.status_distribution?.['3xx'])}</strong>
              </span>
              <span style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                <span style={{ width: 8, height: 8, borderRadius: '50%', background: '#ed8936' }} />
                4xx Client Error: <strong>{metric(traffic.status_distribution?.['4xx'])}</strong>
              </span>
              <span style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                <span style={{ width: 8, height: 8, borderRadius: '50%', background: '#f56565' }} />
                5xx Server Error: <strong>{metric(traffic.status_distribution?.['5xx'])}</strong>
              </span>
            </div>
          </div>
        </div>
      )}

      {/* TAB 3: CALL HITS & TRACES */}
      {activeTab === 'traces' && tracesLoaded && (
        <div>
          {/* Filter Bar */}
          <div style={{
            display: 'flex',
            gap: 12,
            marginBottom: 16,
            flexWrap: 'wrap',
            alignItems: 'center',
            justifyContent: 'space-between'
          }}>
            <div style={{ display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap' }}>
              <input
                type="text"
                placeholder="Search path or Biz ID…"
                value={traceSearch}
                onChange={e => setTraceSearch(e.target.value)}
                style={{
                  padding: '8px 14px',
                  borderRadius: 8,
                  background: 'var(--bg-2, #18191c)',
                  border: '1px solid var(--border)',
                  color: 'var(--text-primary)',
                  fontSize: 13,
                  width: 240
                }}
              />

              <select
                value={traceMethodFilter}
                onChange={e => setTraceMethodFilter(e.target.value)}
                style={{
                  padding: '8px 12px',
                  borderRadius: 8,
                  background: 'var(--bg-2, #18191c)',
                  border: '1px solid var(--border)',
                  color: 'var(--text-primary)',
                  fontSize: 13
                }}
              >
                <option value="all">All Methods</option>
                <option value="GET">GET</option>
                <option value="POST">POST</option>
                <option value="PUT">PUT</option>
                <option value="DELETE">DELETE</option>
              </select>

              <select
                value={traceStatusFilter}
                onChange={e => setTraceStatusFilter(e.target.value)}
                style={{
                  padding: '8px 12px',
                  borderRadius: 8,
                  background: 'var(--bg-2, #18191c)',
                  border: '1px solid var(--border)',
                  color: 'var(--text-primary)',
                  fontSize: 13
                }}
              >
                <option value="all">All Statuses</option>
                <option value="2xx">2xx OK</option>
                <option value="4xx">4xx Errors</option>
                <option value="5xx">5xx Server Errors</option>
              </select>
            </div>

            <span style={{ fontSize: 12, color: '#8e8e93' }}>
              Showing {filteredTraces.length} of {traces.length} captured traces
            </span>
          </div>

          {/* Traces Table */}
          <div style={{
            background: 'var(--bg-2, #18191c)',
            border: '1px solid var(--border)',
            borderRadius: 14,
            overflow: 'hidden'
          }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', textAlign: 'left', fontSize: 13 }}>
              <thead>
                <tr style={{ background: 'rgba(255,255,255,0.03)', borderBottom: '1px solid rgba(255,255,255,0.08)', color: '#8e8e93' }}>
                  <th style={{ padding: '12px 16px' }}>Status</th>
                  <th style={{ padding: '12px 16px' }}>Method</th>
                  <th style={{ padding: '12px 16px' }}>Endpoint Path</th>
                  <th style={{ padding: '12px 16px' }}>Duration</th>
                  <th style={{ padding: '12px 16px' }}>Caller IP</th>
                  <th style={{ padding: '12px 16px' }}>Biz ID</th>
                  <th style={{ padding: '12px 16px' }}>Timestamp</th>
                  <th style={{ padding: '12px 16px', textAlign: 'right' }}>Action</th>
                </tr>
              </thead>
              <tbody>
                {filteredTraces.length === 0 ? (
                  <tr>
                    <td colSpan={8} style={{ padding: 32, textAlign: 'center', color: '#8e8e93' }}>
                      No API call traces matched your filters. Calls will appear in real time as requests are handled.
                    </td>
                  </tr>
                ) : (
                  filteredTraces.map((t, idx) => (
                    <tr
                      key={t.id || idx}
                      onClick={() => setSelectedTrace(t)}
                      style={{
                        borderBottom: '1px solid rgba(255,255,255,0.04)',
                        cursor: 'pointer',
                        background: selectedTrace?.id === t.id ? 'rgba(194, 113, 79, 0.08)' : 'transparent',
                        transition: 'background 0.15s ease'
                      }}
                    >
                      <td style={{ padding: '12px 16px' }}>
                        <StatusCodeBadge code={t.status} />
                      </td>
                      <td style={{ padding: '12px 16px' }}>
                        <MethodBadge method={t.method} />
                      </td>
                      <td style={{ padding: '12px 16px', fontFamily: 'monospace', color: 'var(--text-primary)', fontWeight: 600 }}>
                        {t.path}
                      </td>
                      <td style={{ padding: '12px 16px', fontFamily: 'monospace', color: t.duration_ms > 500 ? '#ed8936' : '#48bb78' }}>
                        {t.duration_ms} ms
                      </td>
                      <td style={{ padding: '12px 16px', color: '#8e8e93', fontSize: 12 }}>
                        {t.ip}
                      </td>
                      <td style={{ padding: '12px 16px', color: '#8e8e93', fontSize: 12 }}>
                        {t.biz_id}
                      </td>
                      <td style={{ padding: '12px 16px', color: '#8e8e93', fontSize: 12 }}>
                        {new Date(t.timestamp).toLocaleTimeString()}
                      </td>
                      <td style={{ padding: '12px 16px', textAlign: 'right' }}>
                        <button
                          type="button"
                          onClick={(e) => { e.stopPropagation(); setSelectedTrace(t) }}
                          style={{
                            padding: '4px 10px',
                            borderRadius: 6,
                            background: 'rgba(255,255,255,0.06)',
                            border: '1px solid var(--border)',
                            color: 'var(--text-primary)',
                            fontSize: 11,
                            cursor: 'pointer'
                          }}
                        >
                          Inspect
                        </button>
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>

          {/* Slide-out Trace Drawer */}
          {selectedTrace && (
            <div style={{
              position: 'fixed',
              top: 0,
              right: 0,
              bottom: 0,
              width: 500,
              maxWidth: '90vw',
              background: 'var(--bg-2)',
              borderLeft: '1px solid rgba(255,255,255,0.12)',
              boxShadow: '-10px 0 30px rgba(0,0,0,0.5)',
              zIndex: 9999,
              display: 'flex',
              flexDirection: 'column',
              padding: 24,
              overflowY: 'auto'
            }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 20 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <Icon name="activity" size={18} />
                  <h3 style={{ margin: 0, fontSize: 16, fontWeight: 700, color: 'var(--text-primary)' }}>API Trace Detail</h3>
                </div>
                <button
                  type="button"
                  onClick={() => setSelectedTrace(null)}
                  style={{
                    background: 'transparent',
                    border: 'none',
                    color: '#8e8e93',
                    fontSize: 20,
                    cursor: 'pointer'
                  }}
                >
                  ✕
                </button>
              </div>

              <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <span style={{ color: '#8e8e93', fontSize: 12 }}>Trace ID</span>
                  <strong style={{ color: 'var(--accent, #c2714f)', fontFamily: 'monospace', fontSize: 12 }}>
                    {selectedTrace.id}
                  </strong>
                </div>

                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <span style={{ color: '#8e8e93', fontSize: 12 }}>HTTP Status</span>
                  <StatusCodeBadge code={selectedTrace.status} />
                </div>

                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <span style={{ color: '#8e8e93', fontSize: 12 }}>Method</span>
                  <MethodBadge method={selectedTrace.method} />
                </div>

                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <span style={{ color: '#8e8e93', fontSize: 12 }}>Execution Duration</span>
                  <strong style={{ color: 'var(--text-primary)', fontFamily: 'monospace' }}>{selectedTrace.duration_ms} ms</strong>
                </div>

                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <span style={{ color: '#8e8e93', fontSize: 12 }}>Caller IP Address</span>
                  <strong style={{ color: 'var(--text-primary)', fontFamily: 'monospace' }}>{selectedTrace.ip}</strong>
                </div>

                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <span style={{ color: '#8e8e93', fontSize: 12 }}>Tenant / Biz ID</span>
                  <strong style={{ color: 'var(--text-primary)' }}>{selectedTrace.biz_id}</strong>
                </div>

                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <span style={{ color: '#8e8e93', fontSize: 12 }}>User-Agent</span>
                  <span style={{ color: '#8e8e93', fontSize: 11, maxWidth: 260, textAlign: 'right' }}>
                    {selectedTrace.user_agent}
                  </span>
                </div>

                <div style={{ marginTop: 10 }}>
                  <span style={{ color: '#8e8e93', fontSize: 12, display: 'block', marginBottom: 6 }}>Full Path</span>
                  <div style={{
                    padding: 10,
                    borderRadius: 8,
                    background: 'var(--bg-3)',
                    border: '1px solid var(--border)',
                    fontFamily: 'monospace',
                    fontSize: 12,
                    color: 'var(--text-primary)',
                    wordBreak: 'break-all'
                  }}>
                    {selectedTrace.full_path}
                  </div>
                </div>

                {selectedTrace.error && (
                  <div style={{ marginTop: 10 }}>
                    <span style={{ color: '#f56565', fontSize: 12, display: 'block', marginBottom: 6 }}>Error Details</span>
                    <div style={{
                      padding: 12,
                      borderRadius: 8,
                      background: 'rgba(229, 62, 62, 0.1)',
                      border: '1px solid rgba(229, 62, 62, 0.3)',
                      color: 'var(--danger)',
                      fontSize: 12,
                      fontFamily: 'monospace'
                    }}>
                      {selectedTrace.error}
                    </div>
                  </div>
                )}

                <div style={{ marginTop: 16 }}>
                  <span style={{ color: '#8e8e93', fontSize: 12, display: 'block', marginBottom: 6 }}>Trace JSON Payload</span>
                  <pre style={{
                    padding: 12,
                    borderRadius: 8,
                    background: 'var(--bg-3)',
                    border: '1px solid var(--border)',
                    fontSize: 11,
                    color: 'var(--text-secondary)',
                    overflowX: 'auto'
                  }}>
                    {JSON.stringify(selectedTrace, null, 2)}
                  </pre>
                </div>
              </div>
            </div>
          )}
        </div>
      )}

      {/* TAB 4: CLOUD BILLING & COST */}
      {activeTab === 'cost' && consoleData && (
        <div>
          {/* Cost Headline Cards */}
          <div style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))',
            gap: 16,
            marginBottom: 24
          }}>
            <div style={{
              background: 'var(--bg-2, #18191c)',
              border: '1px solid var(--border)',
              borderRadius: 14,
              padding: 20
            }}>
              <div style={{ fontSize: 11, fontWeight: 700, color: '#8e8e93', textTransform: 'uppercase' }}>
                Estimated Monthly Cloud Cost
              </div>
              <div style={{ fontSize: 32, fontWeight: 700, color: '#48bb78', marginTop: 8, fontFamily: 'monospace' }}>
                {cost.current_monthly_usd == null ? 'Unavailable' : `$${Number(cost.current_monthly_usd).toFixed(2)}`} <span style={{ fontSize: 14, color: '#8e8e93' }}>{cost.current_monthly_inr == null ? '' : `(₹${Number(cost.current_monthly_inr).toFixed(2)})`}</span>
              </div>
              <div style={{ fontSize: 12, color: '#48bb78', marginTop: 6, display: 'flex', alignItems: 'center', gap: 6 }}>
                <span style={{ width: 8, height: 8, borderRadius: '50%', background: '#48bb78' }} />
                Planning estimate · not an invoice
              </div>
            </div>

            <div style={{
              background: 'var(--bg-2, #18191c)',
              border: '1px solid var(--border)',
              borderRadius: 14,
              padding: 20
            }}>
              <div style={{ fontSize: 11, fontWeight: 700, color: '#8e8e93', textTransform: 'uppercase' }}>
                Projected at 10x Scale
              </div>
              <div style={{ fontSize: 32, fontWeight: 700, color: 'var(--text-primary)', marginTop: 8, fontFamily: 'monospace' }}>
                {cost.projected_scale?.at_10x_traffic_usd == null ? 'Unavailable' : `$${Number(cost.projected_scale.at_10x_traffic_usd).toFixed(2)}`}
              </div>
              <div style={{ fontSize: 12, color: '#8e8e93', marginTop: 6 }}>
                Based on the server's recorded request volume
              </div>
            </div>

            <div style={{
              background: 'var(--bg-2, #18191c)',
              border: '1px solid var(--border)',
              borderRadius: 14,
              padding: 20
            }}>
              <div style={{ fontSize: 11, fontWeight: 700, color: '#8e8e93', textTransform: 'uppercase' }}>
                Projected at 100x Scale
              </div>
              <div style={{ fontSize: 32, fontWeight: 700, color: '#ed8936', marginTop: 8, fontFamily: 'monospace' }}>
                {cost.projected_scale?.at_100x_traffic_usd == null ? 'Unavailable' : `$${Number(cost.projected_scale.at_100x_traffic_usd).toFixed(2)}`} <span style={{ fontSize: 14, color: '#8e8e93' }}>/mo</span>
              </div>
              <div style={{ fontSize: 12, color: '#8e8e93', marginTop: 6 }}>
                Model assumptions may differ from provider billing
              </div>
            </div>
          </div>

          {/* Services Breakdown Table */}
          <div style={{
            background: 'var(--bg-2, #18191c)',
            border: '1px solid var(--border)',
            borderRadius: 14,
            padding: 20
          }}>
            <h3 style={{ margin: '0 0 16px 0', fontSize: 15, fontWeight: 700, color: 'var(--text-primary)' }}>
              Service Cost Model & Assumptions
            </h3>

            <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
              {(cost.services || []).map((svc, idx) => (
                <div
                  key={idx}
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'space-between',
                    padding: '14px 18px',
                    borderRadius: 10,
                    background: 'rgba(255,255,255,0.02)',
                    border: '1px solid var(--border)',
                    flexWrap: 'wrap',
                    gap: 12
                  }}
                >
                  <div>
                    <div style={{ fontSize: 14, fontWeight: 700, color: 'var(--text-primary)' }}>{svc.name}</div>
                    <div style={{ fontSize: 12, color: '#8e8e93' }}>{svc.role} • {svc.unit}</div>
                  </div>

                  <div style={{ textAlign: 'center' }}>
                    <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--text-primary)' }}>{svc.consumed}</div>
                    <div style={{ fontSize: 11, color: '#8e8e93' }}>Quota: {svc.quota}</div>
                  </div>

                  <div style={{ display: 'flex', alignItems: 'center', gap: 16 }}>
                    <div style={{ textAlign: 'right' }}>
                      <div style={{ fontSize: 14, fontWeight: 700, color: '#48bb78', fontFamily: 'monospace' }}>
                        {svc.cost_usd == null ? 'Unavailable' : `$${Number(svc.cost_usd).toFixed(2)}`}
                      </div>
                      <div style={{ fontSize: 10, color: '#8e8e93' }}>Model estimate</div>
                    </div>
                    <StatusBadge status={svc.status} />
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
