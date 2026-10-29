import { useState, useEffect, useRef } from 'react'
import { useAuth } from '../../contexts/AuthContext'
import { logger } from '../../utils/logger'
import { API_BASE } from '../../config'
import { Icon } from '../../components/icons'

export default function AdminUsage() {
  const { authFetch } = useAuth()
  const [stats, setStats] = useState(null)
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState(null)
  const usageRequest = useRef(0)

  useEffect(() => {
    loadUsage()
    return () => { ++usageRequest.current }
  }, [])

  async function loadUsage() {
    const requestId = ++usageRequest.current
    setLoading(true)
    setLoadError(null)
    try {
      const res = await authFetch(`${API_BASE}/admin/usage-stats`)
      if (!res.ok) throw new Error('Failed to load usage statistics')
      const data = await res.json()
      const fields = ['queries_today', 'queries_limit', 'tokens_today', 'tokens_limit', 'complex_today', 'complex_limit', 'requests_per_minute']
      if (!Array.isArray(data) || data.some(s => !s || fields.some(field =>
        s[field] == null || typeof s[field] !== 'number' || !Number.isFinite(s[field]) || s[field] < 0))) {
        throw new Error('Invalid usage statistics response')
      }
      if (requestId !== usageRequest.current) return
      setStats(data)
    } catch (err) {
      if (requestId !== usageRequest.current) return
      logger.error(err)
      setLoadError('Usage statistics could not be loaded.')
    } finally {
      if (requestId === usageRequest.current) setLoading(false)
    }
  }

  function getBarColor(pct) {
    if (pct >= 90) return 'red'
    if (pct >= 70) return 'yellow'
    return 'green'
  }

  // The admin API accepts zero quotas. They have no percentage denominator;
  // avoid 0/0 while still showing any usage recorded against that quota.
  const quotaPercent = (used, limit) => limit > 0 ? Math.max(0, Math.min((used / limit) * 100, 100)) : (used > 0 ? 100 : 0)

  return (
    <div className="admin-main" style={{ margin: 0, padding: 0 }}>
      {/* Header */}
      <div className="admin-header-row">
        <div className="admin-title-group">
          <h1 style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <Icon name="chart" size={22} style={{ color: 'var(--accent)' }} />
            <span>Today's Usage & Rate Limits</span>
          </h1>
          <p>Real-time tracking of API queries, tokens consumed, and complex reasoning runs per merchant</p>
        </div>
        <button className="btn-flush" onClick={loadUsage} disabled={loading} style={{ padding: '8px 14px', fontSize: 13 }}>
          <Icon name="refresh" size={13} />
          <span>Refresh Stats</span>
        </button>
      </div>

      {loadError && <div role="alert" style={{ marginTop: 16, color: 'var(--danger)' }}>
        <p>{loadError}{stats ? ' Showing the last loaded usage data.' : ''}</p>
        <button type="button" className="btn-flush" onClick={loadUsage} disabled={loading}>Retry usage</button>
      </div>}

      {/* Usage Cards Grid */}
      <div className="admin-table-widget" style={{ marginTop: 20 }}>
        <div className="admin-table-title" style={{ marginBottom: 16 }}>Live Merchant Usage Statistics</div>
        
        {loading && !stats ? (
          <div className="vskel"></div>
        ) : stats?.length === 0 ? (
          <div style={{ color: 'var(--text-muted)', fontSize: 13, padding: 20, textAlign: 'center' }}>
            No usage data logged yet today.
          </div>
        ) : stats ? (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
            {stats.map(s => {
              const qPct = quotaPercent(s.queries_today, s.queries_limit)
              const tPct = quotaPercent(s.tokens_today, s.tokens_limit)
              const cPct = quotaPercent(s.complex_today, s.complex_limit)

              return (
                <div key={s.username} style={{ border: '1px solid var(--border-color)', borderRadius: 10, padding: 16 }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
                    <span style={{ fontWeight: 700, color: 'var(--accent-color)' }}>{s.business_name}</span>
                    <span style={{ fontSize: 11, color: 'var(--secondary-text)' }}>
                      @{s.username} · {s.requests_per_minute}/min max
                    </span>
                  </div>
                  <div className="usage-stat-grid">
                    {/* Queries */}
                    <div className="usage-stat-card">
                      <div className="usage-stat-label">Queries Today</div>
                      <div className="usage-stat-value">
                        {s.queries_today}{' '}
                        <span style={{ fontSize: 12, fontWeight: 400, color: 'var(--secondary-text)' }}>
                          / {s.queries_limit}
                        </span>
                      </div>
                      <div className="usage-bar-wrap">
                        <div className="usage-bar-row">
                          <span>{qPct.toFixed(0)}% used</span>
                        </div>
                        <div className="usage-bar-bg">
                          <div className={`usage-bar-fill ${getBarColor(qPct)}`} style={{ width: `${qPct}%` }}></div>
                        </div>
                      </div>
                    </div>

                    {/* Tokens */}
                    <div className="usage-stat-card">
                      <div className="usage-stat-label">Tokens Today</div>
                      <div className="usage-stat-value">
                        {s.tokens_today.toLocaleString()}{' '}
                        <span style={{ fontSize: 12, fontWeight: 400, color: 'var(--secondary-text)' }}>
                          / {s.tokens_limit.toLocaleString()}
                        </span>
                      </div>
                      <div className="usage-bar-wrap">
                        <div className="usage-bar-row">
                          <span>{tPct.toFixed(0)}% used</span>
                        </div>
                        <div className="usage-bar-bg">
                          <div className={`usage-bar-fill ${getBarColor(tPct)}`} style={{ width: `${tPct}%` }}></div>
                        </div>
                      </div>
                    </div>

                    {/* Complex runs */}
                    <div className="usage-stat-card">
                      <div className="usage-stat-label">AI_COMPLEX Runs Today</div>
                      <div className="usage-stat-value">
                        {s.complex_today}{' '}
                        <span style={{ fontSize: 12, fontWeight: 400, color: 'var(--secondary-text)' }}>
                          / {s.complex_limit}
                        </span>
                      </div>
                      <div className="usage-bar-wrap">
                        <div className="usage-bar-row">
                          <span>{cPct.toFixed(0)}% used</span>
                        </div>
                        <div className="usage-bar-bg">
                          <div className={`usage-bar-fill ${getBarColor(cPct)}`} style={{ width: `${cPct}%` }}></div>
                        </div>
                      </div>
                    </div>

                    {/* Rate Limit Info */}
                    <div className="usage-stat-card">
                      <div className="usage-stat-label">Rate Limit</div>
                      <div className="usage-stat-value">
                        {s.requests_per_minute}
                        <span style={{ fontSize: 12, fontWeight: 400, color: 'var(--secondary-text)' }}> req/min</span>
                      </div>
                      <div className="usage-stat-sub" style={{ marginTop: 8 }}>Burst protection active</div>
                    </div>
                  </div>
                </div>
              )
            })}
          </div>
        ) : null}
      </div>
    </div>
  )
}
