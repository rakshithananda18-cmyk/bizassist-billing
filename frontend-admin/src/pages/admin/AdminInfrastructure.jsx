import { useState, useEffect, useCallback, useRef } from 'react'
import { useAuth } from '../../contexts/AuthContext'
import { API_BASE } from '../../config'
import { Icon } from '../../components/icons'
import { readableError } from '../../utils/httpErrors'
import '../../styles/infrastructure.css'

const display = (value, suffix = '') => value === null || value === undefined || value === '' ? 'unavailable' : `${value}${suffix}`
function StatRow({ label, value, suffix = '' }) {
  return <div className="infra-stat"><span>{label}</span><strong>{display(value, suffix)}</strong></div>
}
function Card({ title, icon, status, children }) {
  return <section className="admin-table-widget infra-card">
    <div className="infra-card-header"><h2><Icon name={icon} size={20} />{title}</h2><span className="infra-status">{display(status)}</span></div>
    {children}
  </section>
}
function uptime(value) {
  if (value === null || value === undefined) return null
  const seconds = Math.max(0, Math.floor(value))
  return `${Math.floor(seconds / 3600)}h ${Math.floor(seconds % 3600 / 60)}m ${seconds % 60}s`
}
export default function AdminInfrastructure() {
  const { authFetch } = useAuth()
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)
  const [loading, setLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)
  const [autoRefresh, setAutoRefresh] = useState(false)
  const [lastUpdated, setLastUpdated] = useState(null)
  const pending = useRef(false)
  const mounted = useRef(true)
  const fetchMetrics = useCallback(async () => {
    if (pending.current) return
    pending.current = true
    setRefreshing(true)
    try {
      const response = await authFetch(`${API_BASE}/admin/infrastructure-metrics`)
      const json = await response.json().catch(() => ({}))
      if (!response.ok) throw new Error(`HTTP ${response.status}: ${readableError(response.status, json)}`)
      if (!mounted.current) return
      setData(json)
      setError(null)
      setLastUpdated(new Date())
    } catch (failure) {
      if (mounted.current) setError(failure.message || 'Infrastructure metrics could not be loaded.')
    } finally {
      pending.current = false
      if (mounted.current) { setLoading(false); setRefreshing(false) }
    }
  }, [authFetch])
  useEffect(() => {
    mounted.current = true
    fetchMetrics()
    return () => { mounted.current = false }
  }, [fetchMetrics])
  useEffect(() => {
    if (!autoRefresh) return
    const timer = setInterval(() => { if (!document.hidden && !pending.current) fetchMetrics() }, 60000)
    return () => clearInterval(timer)
  }, [autoRefresh, fetchMetrics])
  const cloud = data?.cloud_run
  const hf = data?.huggingface
  const db = data?.supabase
  const edge = data?.vercel?.endpoints?.[0]
  return <div className="admin-main">
    <div className="admin-header-row infra-header">
      <div className="admin-title-group"><h1>Infrastructure & Cloud Analytics</h1><p>Current service, database and frontend availability.</p></div>
      <div className="infra-controls">
        {lastUpdated && <span>Updated {lastUpdated.toLocaleTimeString()}</span>}
        <label><input type="checkbox" checked={autoRefresh} onChange={event => setAutoRefresh(event.target.checked)} /> Auto (60s)</label>
        <button type="button" onClick={fetchMetrics} disabled={refreshing}><Icon name="refresh" size={14} className={refreshing ? 'spinning' : ''} />{refreshing ? 'Refreshing…' : 'Refresh'}</button>
      </div>
    </div>
    {error && <div role="alert" className="infra-error"><div><strong>Infrastructure metrics unavailable</strong><p>{error}</p>{data && <p>The values below are from the previous successful check.</p>}</div><button type="button" onClick={fetchMetrics} disabled={refreshing}>Retry</button></div>}
    {loading && !data ? <p role="status"><Icon name="refresh" className="spinning" size={20} /> Checking services…</p> :
      <div className="infra-grid">
        <Card title="Google Cloud Run" icon="server" status={cloud?.status}>
          <StatRow label="Region" value={cloud?.region} />
          <StatRow label="Service Name" value={cloud?.service_name} />
          <StatRow label="Revision" value={cloud?.revision} />
          <StatRow label="Instance" value={cloud?.instance || cloud?.instance_id} />
          <StatRow label="Process Uptime" value={uptime(cloud?.uptime_seconds)} />
          <StatRow label="Process Memory (RSS)" value={cloud?.memory?.rss_mb} suffix=" MB" />
          <StatRow label="CPU Utilization" value={cloud?.cpu_percent} suffix="%" />
          <StatRow label="Active Worker Threads" value={cloud?.thread_count} />
          <StatRow label="Python" value={cloud?.python_version} />
          <p className="infra-note">Process metrics describe the responding instance.</p>
        </Card>
        <Card title="Legacy Hugging Face endpoint" icon="shield" status={hf?.status}>
          <StatRow label="Target Space" value={hf?.space_name} />
          <StatRow label="Health Probe Status" value={hf?.status} />
          <StatRow label="Probe Round-Trip Latency" value={hf?.latency_ms} suffix=" ms" />
          <p className="infra-note">The legacy endpoint forwards installed desktop clients to Cloud Run. A probe is shown only when configured.</p>
        </Card>
        <Card title="Supabase Database" icon="database" status={db?.status}>
          <StatRow label="Dialect Engine" value={db?.dialect} />
          <StatRow label="Database Storage Size" value={db?.size_str} />
          <StatRow label="Active Connections" value={db?.connection_pool?.active} />
          <StatRow label="Idle Connections" value={db?.connection_pool?.idle} />
          <StatRow label="Query Cache Hit Ratio" value={db?.cache_hit_ratio_pct} suffix="%" />
          <StatRow label="Invoices" value={db?.table_counts?.invoices} />
          <StatRow label="Products" value={db?.table_counts?.products} />
          <StatRow label="Businesses / Users" value={db?.table_counts?.users} />
          <StatRow label="Payment Records" value={db?.table_counts?.payments} />
        </Card>
        <Card title="Vercel Frontend" icon="sparkle" status={data?.vercel?.status}>
          <StatRow label="Production Domain" value={edge?.domain} />
          <StatRow label="Edge Response Status" value={edge?.status} />
          <StatRow label="HTTP Status" value={edge?.code} />
          <StatRow label="Edge Latency" value={edge?.latency_ms} suffix=" ms" />
          <StatRow label="Serving Edge POP" value={edge?.edge_pop} />
        </Card>
      </div>}
  </div>
}
