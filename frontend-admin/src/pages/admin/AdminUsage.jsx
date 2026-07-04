import { useState, useEffect } from 'react'
import { useAuth } from '../../contexts/AuthContext'
import { API_BASE } from '../../config'

export default function AdminUsage() {
  const { authFetch } = useAuth()
  const [stats, setStats] = useState([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    loadUsage()
  }, [])

  async function loadUsage() {
    setLoading(true)
    try {
      const res = await authFetch(`${API_BASE}/admin/usage-stats`)
      if (!res.ok) throw new Error('Failed to load usage statistics')
      const data = await res.json()
      setStats(data)
    } catch (err) {
      console.error(err)
    } finally {
      setLoading(false)
    }
  }

  function getBarColor(pct) {
    if (pct >= 90) return 'red'
    if (pct >= 70) return 'yellow'
    return 'green'
  }

  return (
    <div className="admin-main" style={{ margin: 0, padding: 0 }}>
      {/* Header */}
      <div className="admin-header-row" style={{ borderBottom: '1.5px solid var(--border-color)', paddingBottom: 20 }}>
        <div className="admin-title-group">
          <h1>✦ TODAY'S USAGE DASHBOARD</h1>
          <p>Real-time tracking of API queries, tokens used, and complex reasoning runs per merchant</p>
        </div>
        <button className="btn-flush" onClick={loadUsage} style={{ padding: '10px 16px', fontSize: 13 }}>
          Refresh Stats ⟳
        </button>
      </div>

      {/* Usage Cards Grid */}
      <div className="admin-table-widget" style={{ marginTop: 24 }}>
        <div className="admin-table-title" style={{ marginBottom: 16 }}>Live Merchant Usage Stats</div>
        
        {loading ? (
          <div className="vskel"></div>
        ) : stats.length === 0 ? (
          <div style={{ color: 'var(--secondary-text)', fontSize: 13, padding: 10 }}>
            No usage data logged yet today.
          </div>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
            {stats.map(s => {
              const qPct = Math.min((s.queries_today / s.queries_limit) * 100, 100)
              const tPct = Math.min((s.tokens_today / s.tokens_limit) * 100, 100)
              const cPct = Math.min((s.complex_today / s.complex_limit) * 100, 100)

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
        )}
      </div>
    </div>
  )
}
