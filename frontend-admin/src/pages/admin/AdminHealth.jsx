import { useState, useEffect } from 'react'
import { useAuth } from '../../contexts/AuthContext'
import { useDialog } from '../../contexts/DialogContext'
import { API_BASE } from '../../config'
import { Icon } from '../../components/icons'

export default function AdminHealth() {
  const { authFetch } = useAuth()
  const { showError } = useDialog()
  
  const [health, setHealth] = useState(null)
  const [feedbacks, setFeedbacks] = useState([])
  const [alterations, setAlterations] = useState([])
  const [loading, setLoading] = useState(true)
  
  const [expandedAlteration, setExpandedAlteration] = useState(null)
  const [downloadingId, setDownloadingId] = useState(null)

  useEffect(() => {
    loadAllData()
  }, [])

  async function loadAllData() {
    setLoading(true)
    try {
      // 1. Fetch Health check stats
      const healthRes = await authFetch(`${API_BASE}/admin/health-check`)
      if (healthRes.ok) {
        const healthData = await healthRes.json()
        setHealth(healthData)
      }

      // 2. Fetch Merchant Feedbacks
      const feedbackRes = await authFetch(`${API_BASE}/admin/feedbacks`)
      if (feedbackRes.ok) {
        const feedbackData = await feedbackRes.json()
        setFeedbacks(feedbackData)
      }

      // 3. Fetch Table Alterations Audit Logs
      const altRes = await authFetch(`${API_BASE}/admin/table-alterations`)
      if (altRes.ok) {
        const altData = await altRes.json()
        setAlterations(altData)
      }
    } catch (err) {
      console.error('Failed to load system health data', err)
      showError(err)
    } finally {
      setLoading(false)
    }
  }

  async function handleDownloadLogs(feedbackId, originalFilename) {
    if (downloadingId) return
    setDownloadingId(feedbackId)
    try {
      const res = await authFetch(`${API_BASE}/admin/feedback/logs/${feedbackId}`)
      if (!res.ok) throw new Error('Logs archive file not found on cloud server.')
      const blob = await res.blob()
      const url = window.URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = originalFilename || `client_logs_${feedbackId}.tar.gz`
      document.body.appendChild(a)
      a.click()
      a.remove()
      window.URL.revokeObjectURL(url)
    } catch (err) {
      showError(err)
    } finally {
      setDownloadingId(null)
    }
  }

  function formatBytes(bytes) {
    if (!bytes) return '0 Bytes'
    const k = 1024
    const sizes = ['Bytes', 'KB', 'MB', 'GB']
    const i = Math.floor(Math.log(bytes) / Math.log(k))
    return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i]
  }

  function renderStatusDot(status) {
    const color = status === 'connected' || status === 'reachable' ? '#10b981'
                : status === 'error' || status === 'unreachable' ? '#ef4444'
                : '#6b7280';
    return (
      <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
        <span style={{ width: 8, height: 8, borderRadius: '50%', background: color, display: 'inline-block' }} />
        <span style={{ textTransform: 'capitalize', fontSize: 13, fontWeight: 600 }}>{status}</span>
      </span>
    )
  }

  return (
    <div className="admin-main">
      <div className="admin-header-row">
        <div className="admin-title-group">
          <h1 style={{ display: 'flex', alignItems: 'center', gap: 8 }}><Icon name="alert" size={24} /> SYSTEM HEALTH & AUDIT</h1>
          <p>Real-time database connection monitoring, client logs, and change auditing</p>
        </div>
        <div className="admin-header-actions">
          <button className="btn-flush" onClick={loadAllData} disabled={loading} style={{ padding: '10px 16px', fontSize: 13, display: 'inline-flex', alignItems: 'center', gap: 6 }}>
            <Icon name="refresh" size={14} /> Refresh Stats
          </button>
        </div>
      </div>

      {loading && !health ? (
        <div className="vskel" style={{ marginTop: 24 }}></div>
      ) : (
        <>
          {/* HEALTH STATUS CARDS */}
          <div className="vsummary-strip-three" style={{ marginTop: 24, display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: 20 }}>
            {/* Local DB Status */}
            <div className="vsummary-card" style={{ borderLeftColor: health?.sqlite === 'connected' ? '#10b981' : '#6b7280', padding: 18 }}>
              <div className="vsummary-label">SQLite Local DB</div>
              <div className="vsummary-value" style={{ fontSize: '1.4rem', marginTop: 4 }}>
                {renderStatusDot(health?.sqlite)}
              </div>
              <div className="vsummary-sub">desktop instance client</div>
            </div>

            {/* Cloud DB Status */}
            <div className="vsummary-card" style={{ borderLeftColor: health?.postgres === 'connected' || health?.postgres === 'reachable' ? '#10b981' : '#6b7280', padding: 18 }}>
              <div className="vsummary-label">PostgreSQL Cloud DB</div>
              <div className="vsummary-value" style={{ fontSize: '1.4rem', marginTop: 4 }}>
                {renderStatusDot(health?.postgres)}
              </div>
              <div className="vsummary-sub">supabase persistence node</div>
            </div>

            {/* Log files card */}
            <div className="vsummary-card" style={{ borderLeftColor: '#3b82f6', padding: 18 }}>
              <div className="vsummary-label">Server Console Log File</div>
              <div className="vsummary-value" style={{ fontSize: '1.25rem', fontWeight: 700, color: 'var(--text-color, #fff)', marginTop: 4 }}>
                {health?.log_file?.exists ? formatBytes(health?.log_file?.size_bytes) : 'Not found'}
              </div>
              <div className="vsummary-sub">tailing logs/bizassist.log</div>
            </div>

            {/* Telemetry Stats */}
            <div className="vsummary-card" style={{ borderLeftColor: '#8b5cf6', padding: 18 }}>
              <div className="vsummary-label">Persistent Telemetry</div>
              <div className="vsummary-value" style={{ fontSize: '1.25rem', fontWeight: 700, color: 'var(--text-color, #fff)', marginTop: 4 }}>
                {health?.telemetry?.rows?.toLocaleString() || 0} events
              </div>
              <div className="vsummary-sub">DB store row count</div>
            </div>
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: '1fr', gap: 24, marginTop: 24 }}>
            {/* SECTION 1: MERCHANT FEEDBACKS & LOGS */}
            <div className="admin-table-widget">
              <div className="admin-table-title" style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 12 }}>
                <Icon name="chat" size={16} /> Merchant Feedback & Diagnostics
              </div>
              <div style={{ overflowX: 'auto' }}>
                <table className="admin-table">
                  <thead>
                    <tr>
                      <th style={{ width: 120 }}>Date</th>
                      <th style={{ width: 100 }}>Biz ID</th>
                      <th style={{ width: 120 }}>Username</th>
                      <th>Reported Issue</th>
                      <th style={{ width: 160, textAlign: 'center' }}>Diagnostics Logs</th>
                    </tr>
                  </thead>
                  <tbody>
                    {feedbacks.length === 0 ? (
                      <tr>
                        <td colSpan="5" style={{ textAlign: 'center', color: 'var(--secondary-text)', padding: '24px 0' }}>
                          No feedbacks or logs submitted yet.
                        </td>
                      </tr>
                    ) : (
                      feedbacks.map((fb) => (
                        <tr key={fb.id}>
                          <td>{new Date(fb.created_at + 'Z').toLocaleString()}</td>
                          <td>
                            <code style={{ background: 'var(--hover-bg, rgba(255,255,255,0.05))', padding: '2px 6px', borderRadius: 4, fontSize: 11 }}>
                              {fb.business_id}
                            </code>
                          </td>
                          <td style={{ fontWeight: 600 }}>{fb.username || 'System'}</td>
                          <td style={{ whiteSpace: 'pre-wrap', lineHeight: 1.5, fontSize: '0.85rem' }}>{fb.message}</td>
                          <td style={{ textAlign: 'center' }}>
                            {fb.log_file_path ? (
                              <button
                                className="btn-flush"
                                onClick={() => handleDownloadLogs(fb.id, fb.log_file_path.split('/').pop())}
                                disabled={downloadingId === fb.id}
                                style={{
                                  padding: '6px 12px',
                                  fontSize: 11,
                                  background: 'rgba(99,102,241,0.1)',
                                  color: '#818cf8',
                                  border: '1px solid rgba(99,102,241,0.3)',
                                  borderRadius: 6,
                                  cursor: 'pointer',
                                  display: 'inline-flex',
                                  alignItems: 'center',
                                  gap: 4
                                }}
                              >
                                <Icon name="upload" size={11} style={{ transform: 'rotate(180deg)' }} /> 
                                {downloadingId === fb.id ? 'Downloading...' : 'Download Logs'}
                              </button>
                            ) : (
                              <span style={{ color: 'var(--secondary-text)', fontSize: 11 }}>None</span>
                            )}
                          </td>
                        </tr>
                      ))
                    )}
                  </tbody>
                </table>
              </div>
            </div>

            {/* SECTION 2: HIGH-MONITORING DATABASE AUDITING */}
            <div className="admin-table-widget">
              <div className="admin-table-title" style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 12 }}>
                <Icon name="database" size={16} /> Table Alteration Audit Log
              </div>
              <div style={{ color: 'var(--secondary-text)', fontSize: '13px', marginBottom: 16 }}>
                Centralized recording of database inserts, updates, and deletes across client nodes. Click any alteration to view the column payload details.
              </div>
              <div style={{ overflowX: 'auto' }}>
                <table className="admin-table">
                  <thead>
                    <tr>
                      <th style={{ width: 160 }}>Timestamp</th>
                      <th style={{ width: 80 }}>Biz ID</th>
                      <th style={{ width: 120 }}>User</th>
                      <th style={{ width: 140 }}>Table Altered</th>
                      <th style={{ width: 100 }}>Action</th>
                      <th style={{ width: 100 }}>Record ID</th>
                      <th style={{ width: 60 }}>Details</th>
                    </tr>
                  </thead>
                  <tbody>
                    {alterations.length === 0 ? (
                      <tr>
                        <td colSpan="7" style={{ textAlign: 'center', color: 'var(--secondary-text)', padding: '24px 0' }}>
                          No database alterations captured yet.
                        </td>
                      </tr>
                    ) : (
                      alterations.map((alt) => {
                        const isExpanded = expandedAlteration === alt.id
                        return (
                          <>
                            <tr
                              key={alt.id}
                              onClick={() => setExpandedAlteration(isExpanded ? null : alt.id)}
                              style={{ cursor: 'pointer', hover: 'background: rgba(255,255,255,0.02)' }}
                            >
                              <td>{new Date(alt.created_at + 'Z').toLocaleString()}</td>
                              <td>
                                <code style={{ fontSize: 11, background: 'var(--hover-bg, rgba(255,255,255,0.05))', padding: '2px 4px', borderRadius: 4 }}>
                                  {alt.business_id}
                                </code>
                              </td>
                              <td style={{ fontWeight: 600 }}>{alt.username || 'System'}</td>
                              <td style={{ fontStyle: 'italic', color: '#f3f4f6' }}>{alt.table_name}</td>
                              <td>
                                <span style={{
                                  fontSize: 11,
                                  fontWeight: 700,
                                  padding: '2px 6px',
                                  borderRadius: 4,
                                  background: alt.action === 'INSERT' ? 'rgba(16,185,129,0.1)'
                                            : alt.action === 'UPDATE' ? 'rgba(245,158,11,0.1)'
                                            : 'rgba(239,68,68,0.1)',
                                  color: alt.action === 'INSERT' ? '#10b981'
                                       : alt.action === 'UPDATE' ? '#f59e0b'
                                       : '#ef4444'
                                }}>
                                  {alt.action}
                                </span>
                              </td>
                              <td>ID #{alt.record_id || 'N/A'}</td>
                              <td>
                                <Icon name={isExpanded ? 'chevronDown' : 'chevronRight'} size={12} style={{ color: 'var(--secondary-text)' }} />
                              </td>
                            </tr>
                            {isExpanded && (
                              <tr style={{ background: 'rgba(0,0,0,0.15)' }}>
                                <td colSpan="7" style={{ padding: '16px 24px' }}>
                                  <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: 16 }}>
                                    {/* Old values */}
                                    <div>
                                      <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--secondary-text)', marginBottom: 6 }}>
                                        Old Values
                                      </div>
                                      <pre style={{
                                        margin: 0,
                                        padding: 12,
                                        background: 'rgba(0,0,0,0.3)',
                                        border: '1px solid var(--border-color, rgba(255,255,255,0.08))',
                                        borderRadius: 6,
                                        fontSize: 11.5,
                                        fontFamily: 'monospace',
                                        color: '#ef4444',
                                        whiteSpace: 'pre-wrap',
                                        maxHeight: 180,
                                        overflowY: 'auto'
                                      }}>
                                        {alt.old_values ? JSON.stringify(JSON.parse(alt.old_values), null, 2) : 'None (INSERT operation)'}
                                      </pre>
                                    </div>
                                    {/* New values */}
                                    <div>
                                      <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--secondary-text)', marginBottom: 6 }}>
                                        New Values / Payload
                                      </div>
                                      <pre style={{
                                        margin: 0,
                                        padding: 12,
                                        background: 'rgba(0,0,0,0.3)',
                                        border: '1px solid var(--border-color, rgba(255,255,255,0.08))',
                                        borderRadius: 6,
                                        fontSize: 11.5,
                                        fontFamily: 'monospace',
                                        color: '#10b981',
                                        whiteSpace: 'pre-wrap',
                                        maxHeight: 180,
                                        overflowY: 'auto'
                                      }}>
                                        {alt.new_values ? JSON.stringify(JSON.parse(alt.new_values), null, 2) : 'None (DELETE operation)'}
                                      </pre>
                                    </div>
                                  </div>
                                </td>
                              </tr>
                            )}
                          </>
                        )
                      })
                    )}
                  </tbody>
                </table>
              </div>
            </div>
          </div>
        </>
      )}
    </div>
  )
}
