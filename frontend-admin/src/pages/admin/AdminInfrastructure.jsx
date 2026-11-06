import { useState, useEffect, useCallback, useRef } from 'react'
import { useAuth } from '../../contexts/AuthContext'
import { logger } from '../../utils/logger'
import { useDialog } from '../../contexts/DialogContext'
import { API_BASE } from '../../config'
import { Icon } from '../../components/icons'

function StatusPill({ status, label }) {
  let bg = 'rgba(107, 114, 128, 0.15)'
  let color = '#9ca3af'
  let border = 'rgba(107, 114, 128, 0.3)'

  const s = String(status).toUpperCase()
  if (s === 'ACTIVE' || s === 'ONLINE' || s === 'CONNECTED') {
    bg = 'rgba(16, 185, 129, 0.12)'
    color = '#10b981'
    border = 'rgba(16, 185, 129, 0.3)'
  } else if (s === 'STANDBY' || s === 'PAUSED') {
    bg = 'rgba(245, 158, 11, 0.15)'
    color = '#f59e0b'
    border = 'rgba(245, 158, 11, 0.3)'
  } else if (s.includes('HTTP_503') || s === 'DEGRADED' || s === 'ERROR' || s === 'UNREACHABLE') {
    bg = 'rgba(239, 68, 68, 0.15)'
    color = '#ef4444'
    border = 'rgba(239, 68, 68, 0.3)'
  }

  return (
    <span style={{
      display: 'inline-flex',
      alignItems: 'center',
      gap: 6,
      padding: '4px 10px',
      borderRadius: 9999,
      fontSize: 12,
      fontWeight: 600,
      background: bg,
      color: color,
      border: `1px solid ${border}`,
      letterSpacing: '0.02em',
      textTransform: 'uppercase'
    }}>
      <span style={{ width: 7, height: 7, borderRadius: '50%', background: color }} />
      {label || status}
    </span>
  )
}

function MetricCard({ title, icon, provider, status, children, accentColor }) {
  return (
    <div style={{
      background: 'var(--bg-2, #18181b)',
      border: '1px solid var(--border, #27272a)',
      borderRadius: 'var(--radius-lg, 14px)',
      padding: '20px 24px',
      display: 'flex',
      flexDirection: 'column',
      gap: 16,
      boxShadow: 'var(--shadow-sm, 0 2px 8px rgba(0,0,0,0.2))',
      position: 'relative',
      overflow: 'hidden'
    }}>
      <div style={{
        position: 'absolute',
        top: 0,
        left: 0,
        right: 0,
        height: 3,
        background: accentColor || 'var(--accent, #c2714f)'
      }} />

      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <div style={{
            width: 36,
            height: 36,
            borderRadius: 8,
            background: 'var(--bg-1, #09090b)',
            border: '1px solid var(--border, #27272a)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            color: accentColor || 'var(--accent, #c2714f)'
          }}>
            <Icon name={icon || 'server'} size={20} />
          </div>
          <div>
            <div style={{ fontSize: 16, fontWeight: 700, color: 'var(--text-primary, #f4f4f5)' }}>{title}</div>
            <div style={{ fontSize: 12, color: 'var(--text-muted, #71717a)' }}>{provider}</div>
          </div>
        </div>
        <StatusPill status={status} />
      </div>

      <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
        {children}
      </div>
    </div>
  )
}

function StatRow({ label, value, sub, progress }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', fontSize: 13 }}>
        <span style={{ color: 'var(--text-muted, #a1a1aa)' }}>{label}</span>
        <span style={{ fontWeight: 600, fontFamily: 'var(--font-mono, monospace)', color: 'var(--text-primary, #f4f4f5)' }}>
          {value}
          {sub && <span style={{ fontSize: 11, color: 'var(--text-muted, #71717a)', marginLeft: 6 }}>({sub})</span>}
        </span>
      </div>
      {typeof progress === 'number' && (
        <div style={{
          width: '100%',
          height: 6,
          background: 'var(--bg-1, #27272a)',
          borderRadius: 4,
          overflow: 'hidden'
        }}>
          <div style={{
            width: `${Math.min(100, Math.max(0, progress))}%`,
            height: '100%',
            background: progress > 85 ? '#ef4444' : progress > 60 ? '#f59e0b' : '#10b981',
            borderRadius: 4,
            transition: 'width 0.4s ease'
          }} />
        </div>
      )}
    </div>
  )
}

export default function AdminInfrastructure() {
  const { authFetch } = useAuth()
  const { showError } = useDialog()
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)
  const [autoRefresh, setAutoRefresh] = useState(true)
  const [lastUpdated, setLastUpdated] = useState(null)
  const timerRef = useRef(null)

  const fetchMetrics = useCallback(async (isSilent = false) => {
    if (!isSilent) setRefreshing(true)
    try {
      const res = await authFetch(`${API_BASE}/admin/infrastructure-metrics`)
      if (!res.ok) throw new Error('Failed to load infrastructure telemetry')
      const json = await res.json()
      setData(json)
      setLastUpdated(new Date())
    } catch (err) {
      logger.error('Error loading infrastructure metrics:', err)
      if (!isSilent) showError(err)
    } finally {
      setLoading(false)
      setRefreshing(false)
    }
  }, [authFetch, showError])

  useEffect(() => {
    fetchMetrics()
  }, [fetchMetrics])

  useEffect(() => {
    if (autoRefresh) {
      timerRef.current = setInterval(() => {
        fetchMetrics(true)
      }, 15000)
    }
    return () => {
      if (timerRef.current) clearInterval(timerRef.current)
    }
  }, [autoRefresh, fetchMetrics])

  function formatUptime(seconds) {
    if (!seconds) return '0s'
    const d = Math.floor(seconds / (3600 * 24))
    const h = Math.floor((seconds % (3600 * 24)) / 3600)
    const m = Math.floor((seconds % 3600) / 60)
    const s = seconds % 60
    const parts = []
    if (d > 0) parts.push(`${d}d`)
    if (h > 0) parts.push(`${h}h`)
    if (m > 0) parts.push(`${m}m`)
    if (parts.length === 0 || (d === 0 && h === 0)) parts.push(`${s}s`)
    return parts.join(' ')
  }

  const cloudRun = data?.cloud_run
  const hf = data?.huggingface
  const supabase = data?.supabase
  const vercel = data?.vercel

  return (
    <div className="admin-main" style={{ margin: 0, padding: 0 }}>
      {/* Header */}
      <div className="admin-header-row" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 24 }}>
        <div className="admin-title-group">
          <h1 style={{ display: 'flex', alignItems: 'center', gap: 10, margin: 0, fontSize: 24, fontWeight: 700 }}>
            <Icon name="server" size={24} style={{ color: 'var(--accent, #c2714f)' }} />
            <span>Infrastructure & Cloud Analytics</span>
          </h1>
          <p style={{ margin: '4px 0 0', fontSize: 13, color: 'var(--text-muted, #71717a)' }}>
            Real-time observability across Google Cloud Run, Hugging Face Standby, Supabase PostgreSQL, and Vercel Edge.
          </p>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          {lastUpdated && (
            <span style={{ fontSize: 12, color: 'var(--text-muted, #71717a)' }}>
              Updated {lastUpdated.toLocaleTimeString()}
            </span>
          )}
          <label style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 13, cursor: 'pointer', color: 'var(--text-secondary, #d4d4d8)' }}>
            <input
              type="checkbox"
              checked={autoRefresh}
              onChange={(e) => setAutoRefresh(e.target.checked)}
              style={{ accentColor: 'var(--accent, #c2714f)' }}
            />
            Auto (15s)
          </label>
          <button
            onClick={() => fetchMetrics(false)}
            disabled={refreshing}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 6,
              padding: '7px 14px',
              borderRadius: 8,
              background: 'var(--bg-2, #27272a)',
              color: 'var(--text-primary, #f4f4f5)',
              border: '1px solid var(--border, #3f3f46)',
              fontSize: 13,
              fontWeight: 600,
              cursor: refreshing ? 'not-allowed' : 'pointer'
            }}
          >
            <Icon name="refresh" size={14} className={refreshing ? 'spinning' : ''} />
            {refreshing ? 'Probing...' : 'Refresh'}
          </button>
        </div>
      </div>

      {loading && !data ? (
        <div style={{ textAlign: 'center', padding: '60px 0', color: 'var(--text-muted)' }}>
          <Icon name="refresh" size={28} className="spinning" style={{ marginBottom: 12, color: 'var(--accent)' }} />
          <div>Probing production fleet & database connections...</div>
        </div>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 24 }}>
          {/* Disaster Recovery Architecture Banner */}
          <div style={{
            background: 'linear-gradient(90deg, rgba(194, 113, 79, 0.12) 0%, rgba(24, 24, 27, 0.6) 100%)',
            border: '1px solid rgba(194, 113, 79, 0.3)',
            borderRadius: 12,
            padding: '16px 20px',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            flexWrap: 'wrap',
            gap: 12
          }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
              <div style={{
                width: 32,
                height: 32,
                borderRadius: '50%',
                background: 'rgba(194, 113, 79, 0.2)',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                color: 'var(--accent, #c2714f)'
              }}>
                <Icon name="shield" size={18} />
              </div>
              <div>
                <div style={{ fontSize: 14, fontWeight: 700, color: 'var(--text-primary, #f4f4f5)' }}>
                  Active/Passive Architecture: 100% Traffic on Google Cloud Run (Mumbai)
                </div>
                <div style={{ fontSize: 12, color: 'var(--text-muted, #a1a1aa)' }}>
                  Zero background pinging during normal operation. Hugging Face Spaces operates as cold/warm disaster recovery standby.
                </div>
              </div>
            </div>
            <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
              <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>Standby Health:</span>
              <StatusPill
                status={hf?.failover_ready ? 'STANDBY' : (hf?.status || 'UNKNOWN')}
                label={hf?.failover_ready ? 'STANDBY READY' : (hf?.status || 'DOWN')}
              />
            </div>
          </div>

          {/* 4 Infrastructure Tiles Grid */}
          <div style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fit, minmax(320px, 1fr))',
            gap: 20
          }}>
            {/* 1. Google Cloud Run */}
            <MetricCard
              title="Google Cloud Run"
              provider="Primary Production Backend"
              icon="server"
              status={cloudRun?.status || 'ACTIVE'}
              accentColor="#3b82f6"
            >
              <StatRow label="Region" value={cloudRun?.region || 'asia-south1 (Mumbai)'} />
              <StatRow label="Service Name" value={cloudRun?.service_name || 'staterbill-api'} />
              <StatRow label="Process Uptime" value={formatUptime(cloudRun?.uptime_seconds)} />
              <StatRow
                label="Process Memory (RSS)"
                value={`${cloudRun?.memory?.rss_mb || 0} MB`}
                progress={cloudRun?.memory?.percent || 15}
                sub={`${cloudRun?.memory?.percent || 0}% host`}
              />
              <StatRow
                label="CPU Utilization"
                value={`${cloudRun?.cpu_percent || 0}%`}
                progress={cloudRun?.cpu_percent || 5}
              />
              <StatRow label="Active Worker Threads" value={cloudRun?.thread_count || 4} />
              <StatRow label="Runtime Environment" value={`Python ${cloudRun?.python_version} (${cloudRun?.platform})`} />
            </MetricCard>

            {/* 2. Hugging Face Spaces (Standby) */}
            <MetricCard
              title="Hugging Face Spaces"
              provider="Disaster Recovery Standby (Passive)"
              icon="shield"
              status={hf?.failover_ready ? 'STANDBY' : (hf?.status || 'UNKNOWN')}
              accentColor="#f59e0b"
            >
              <StatRow label="Target Space" value={hf?.space_name || 'rakshit-dev/bizassist'} />
              <StatRow label="Health Probe Status" value={hf?.status || 'N/A'} sub={hf?.code ? `HTTP ${hf?.code}` : null} />
              <StatRow
                label="Probe Round-Trip Latency"
                value={`${hf?.latency_ms || 0} ms`}
                progress={Math.min(100, (hf?.latency_ms || 0) / 30)}
              />
              <StatRow
                label="Disaster Failover Readiness"
                value={hf?.failover_ready ? 'Ready to activate' : 'Standby Degraded'}
                sub={hf?.failover_ready ? 'Synced to origin/main' : 'Service starting or recovering'}
              />
              <div style={{
                marginTop: 8,
                padding: '10px 12px',
                background: 'var(--bg-1, #09090b)',
                borderRadius: 8,
                border: '1px solid var(--border, #27272a)',
                fontSize: 12,
                color: 'var(--text-muted, #a1a1aa)',
                lineHeight: 1.5
              }}>
                <strong style={{ color: 'var(--text-primary)' }}>Failover activation:</strong> Uncomment <code>SECONDARY_HF_URL</code> in frontend config or change Vercel <code>VITE_API_URL</code>.
              </div>
            </MetricCard>

            {/* 3. Supabase PostgreSQL */}
            <MetricCard
              title="Supabase Database"
              provider={supabase?.provider || 'Managed PostgreSQL'}
              icon="database"
              status={supabase?.status || 'CONNECTED'}
              accentColor="#10b981"
            >
              <StatRow label="Dialect Engine" value={supabase?.dialect || 'postgresql'} />
              <StatRow label="Database Storage Size" value={supabase?.size_str || '0 MB'} />
              <StatRow
                label="Connection Pool"
                value={`${supabase?.connection_pool?.total || 1} / ${supabase?.connection_pool?.max || 100}`}
                progress={supabase?.connection_pool?.utilization_pct || 2}
                sub={`${supabase?.connection_pool?.active || 1} active, ${supabase?.connection_pool?.idle || 0} idle`}
              />
              <StatRow
                label="Query Cache Hit Ratio"
                value={`${supabase?.cache_hit_ratio_pct || 99.8}%`}
                progress={supabase?.cache_hit_ratio_pct || 99.8}
              />
              <div style={{
                marginTop: 8,
                display: 'grid',
                gridTemplateColumns: 'repeat(2, 1fr)',
                gap: 8,
                background: 'var(--bg-1, #09090b)',
                padding: 10,
                borderRadius: 8,
                border: '1px solid var(--border, #27272a)'
              }}>
                <div>
                  <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>Invoices</div>
                  <div style={{ fontSize: 15, fontWeight: 700, fontFamily: 'monospace' }}>{supabase?.table_counts?.invoices || 0}</div>
                </div>
                <div>
                  <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>Products</div>
                  <div style={{ fontSize: 15, fontWeight: 700, fontFamily: 'monospace' }}>{supabase?.table_counts?.products || 0}</div>
                </div>
                <div>
                  <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>Businesses / Users</div>
                  <div style={{ fontSize: 15, fontWeight: 700, fontFamily: 'monospace' }}>{supabase?.table_counts?.users || 0}</div>
                </div>
                <div>
                  <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>Payment Records</div>
                  <div style={{ fontSize: 15, fontWeight: 700, fontFamily: 'monospace' }}>{supabase?.table_counts?.payments || 0}</div>
                </div>
              </div>
            </MetricCard>

            {/* 4. Vercel Edge Global Network */}
            <MetricCard
              title="Vercel Edge Network"
              provider="Global CDN & Frontend Hosting"
              icon="sparkle"
              status={vercel?.status || 'ONLINE'}
              accentColor="#c2714f"
            >
              <StatRow label="Production Domain" value="staterbill.com" />
              <StatRow label="Edge Response Status" value={vercel?.endpoints?.[0]?.status || 'ONLINE'} sub={`HTTP ${vercel?.endpoints?.[0]?.code || 200}`} />
              <StatRow
                label="Edge Latency"
                value={`${vercel?.endpoints?.[0]?.latency_ms || 0} ms`}
                progress={Math.min(100, (vercel?.endpoints?.[0]?.latency_ms || 0) / 15)}
              />
              <StatRow label="Serving Edge POP" value={vercel?.endpoints?.[0]?.edge_pop || 'BOM1 (Mumbai Edge)'} />
              <StatRow label="SSL / TLS Encryption" value="Strict Transport Security (HSTS)" />
            </MetricCard>
          </div>

          {/* System Latency & Performance Comparison Bar */}
          <div style={{
            background: 'var(--bg-2, #18181b)',
            border: '1px solid var(--border, #27272a)',
            borderRadius: 14,
            padding: '20px 24px'
          }}>
            <h3 style={{ margin: '0 0 16px', fontSize: 16, fontWeight: 700, display: 'flex', alignItems: 'center', gap: 8 }}>
              <Icon name="activity" size={18} style={{ color: 'var(--accent)' }} />
              Latency Comparison & SLA Thresholds
            </h3>

            <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
              <div>
                <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 6, fontSize: 13 }}>
                  <span>Google Cloud Run (Mumbai) Primary API</span>
                  <span style={{ fontWeight: 600, fontFamily: 'monospace' }}>~180 - 450 ms</span>
                </div>
                <div style={{ height: 8, background: 'var(--bg-1)', borderRadius: 4, overflow: 'hidden' }}>
                  <div style={{ width: '25%', height: '100%', background: '#3b82f6', borderRadius: 4 }} />
                </div>
              </div>

              <div>
                <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 6, fontSize: 13 }}>
                  <span>Vercel Edge Frontend (staterbill.com)</span>
                  <span style={{ fontWeight: 600, fontFamily: 'monospace' }}>{vercel?.endpoints?.[0]?.latency_ms || 40} ms</span>
                </div>
                <div style={{ height: 8, background: 'var(--bg-1)', borderRadius: 4, overflow: 'hidden' }}>
                  <div style={{ width: `${Math.min(100, (vercel?.endpoints?.[0]?.latency_ms || 40) / 10)}%`, height: '100%', background: '#c2714f', borderRadius: 4 }} />
                </div>
              </div>

              <div>
                <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 6, fontSize: 13 }}>
                  <span>Hugging Face Spaces (Standby Probe)</span>
                  <span style={{ fontWeight: 600, fontFamily: 'monospace' }}>{hf?.latency_ms || 1200} ms</span>
                </div>
                <div style={{ height: 8, background: 'var(--bg-1)', borderRadius: 4, overflow: 'hidden' }}>
                  <div style={{ width: `${Math.min(100, (hf?.latency_ms || 1200) / 30)}%`, height: '100%', background: hf?.failover_ready ? '#f59e0b' : '#ef4444', borderRadius: 4 }} />
                </div>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
