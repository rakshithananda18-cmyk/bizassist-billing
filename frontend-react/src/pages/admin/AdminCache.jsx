import { useState, useEffect } from 'react'
import { useAuth } from '../../contexts/AuthContext'
import { useDialog } from '../../contexts/DialogContext'
import { API_BASE } from '../../config'

export default function AdminCache() {
  const { authFetch } = useAuth()
  const { showAlert, showConfirm, showError } = useDialog()
  const [cacheStats, setCacheStats] = useState({ context_cache: [], query_cache: [] })
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    loadCache()
  }, [])

  async function loadCache() {
    setLoading(true)
    try {
      const res = await authFetch(`${API_BASE}/admin/cache-stats`)
      if (!res.ok) throw new Error('Failed to load cache stats')
      const data = await res.json()
      setCacheStats(data)
    } catch (err) {
      console.error(err)
    } finally {
      setLoading(false)
    }
  }

  async function handleFlushAll() {
    if (!(await showConfirm('Flush context and query response caches for all users?'))) return
    try {
      const res = await authFetch(`${API_BASE}/admin/flush-all-cache`, { method: 'POST' })
      const data = await res.json()
      await showAlert(data.message || 'All caches flushed successfully.')
      loadCache()
    } catch (err) {
      await showError(err)
    }
  }

  async function handleResetChroma() {
    if (!(await showConfirm('Reset Chroma documents collection? This fixes dimensionality mismatch errors.'))) return
    try {
      const res = await authFetch(`${API_BASE}/admin/reset-chroma-documents`, { method: 'POST' })
      const data = await res.json()
      await showAlert(data.message || 'Chroma documents reset successfully.')
      loadCache()
    } catch (err) {
      await showError(err)
    }
  }

  return (
    <div className="admin-main" style={{ margin: 0, padding: 0 }}>
      {/* Header */}
      <div className="admin-header-row" style={{ borderBottom: '1.5px solid var(--border-color)', paddingBottom: 20 }}>
        <div className="admin-title-group">
          <h1>✦ CACHE & TELEMETRY MONITOR</h1>
          <p>Inspect in-memory context caches and saved model prompt answer collections</p>
        </div>
        <div className="admin-header-actions">
          <button className="btn-flush" onClick={handleFlushAll}>
            🔄 Flush All Caches
          </button>
          <button className="btn-flush" onClick={handleResetChroma}>
            🧠 Reset Chroma
          </button>
          <button className="btn-flush" onClick={loadCache}>
            Refresh Stats ⟳
          </button>
        </div>
      </div>

      {/* Monitor Widget */}
      <div className="admin-table-widget" style={{ marginTop: 24 }}>
        <div className="admin-table-title" style={{ marginBottom: 16 }}>System Cache Telemetry</div>
        
        {loading ? (
          <div className="vskel"></div>
        ) : (
          <div className="admin-cache-grid">
            {/* Context Caches */}
            <div>
              <h3 style={{ fontSize: 13, color: 'var(--secondary-text)', marginBottom: 12, fontWeight: 600 }}>
                ACTIVE CONTEXT CACHES
              </h3>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
                {cacheStats.context_cache.length === 0 ? (
                  <div style={{ color: 'var(--secondary-text)', fontSize: 13, padding: 10 }}>
                    No active context caches.
                  </div>
                ) : (
                  cacheStats.context_cache.map((item, idx) => {
                    const builtAtStr = item.built_at ? new Date(item.built_at * 1000).toLocaleTimeString() : 'N/A'
                    const estTokens = Math.round(item.size_chars / 4)
                    const pct = Math.min((estTokens / 4000) * 100, 100)

                    return (
                      <div key={idx} className="cache-entry-card">
                        <div className="cache-meta-row">
                          <span style={{ fontWeight: 600, color: 'var(--accent-color)' }}>User ID: {item.user_id}</span>
                          <span style={{ color: 'var(--secondary-text)' }}>Built: {builtAtStr}</span>
                        </div>
                        <div className="cache-meta-row" style={{ marginTop: 2 }}>
                          <span>Size: {item.size_chars.toLocaleString()} chars (~{estTokens.toLocaleString()} tokens)</span>
                        </div>
                        <div className="cache-bar-bg" style={{ marginTop: 6 }}>
                          <div className="cache-bar-fill" style={{ width: `${pct}%` }}></div>
                        </div>
                      </div>
                    )
                  })
                )}
              </div>
            </div>

            {/* Query Caches */}
            <div>
              <h3 style={{ fontSize: 13, color: 'var(--secondary-text)', marginBottom: 12, fontWeight: 600 }}>
                ACTIVE QUERY RESPONSE CACHES
              </h3>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
                {cacheStats.query_cache.length === 0 ? (
                  <div style={{ color: 'var(--secondary-text)', fontSize: 13, padding: 10 }}>
                    No cached query responses.
                  </div>
                ) : (
                  cacheStats.query_cache.map((item, idx) => (
                    <div key={idx} className="cache-entry-card">
                      <div className="cache-meta-row">
                        <span style={{ fontWeight: 600, color: 'var(--accent-color)' }}>User ID: {item.user_id}</span>
                        <span style={{ fontWeight: 500 }}>{item.query_count} cached queries</span>
                      </div>
                      <div className="cache-meta-row" style={{ marginTop: 2, fontSize: 11, color: 'var(--secondary-text)' }}>
                        <span>Answers stored to prevent Rate Limits</span>
                      </div>
                    </div>
                  ))
                )}
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
