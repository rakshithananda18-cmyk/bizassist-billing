import { useState, useEffect } from 'react'
import { useAuth } from '../../contexts/AuthContext'
import { API_BASE } from '../../config'

export default function AdminDashboard() {
  const { authFetch, adminLogout } = useAuth()
  const [stats, setStats] = useState({ businesses: 0, revenue: 0, files: 0 })
  const [loading, setLoading] = useState(true)
  const [dropdownOpen, setDropdownOpen] = useState(false)

  useEffect(() => {
    loadDashboardStats()
  }, [])

  async function loadDashboardStats() {
    setLoading(true)
    try {
      const res = await authFetch(`${API_BASE}/admin/businesses`)
      if (!res.ok) throw new Error('Failed to load merchant directory')
      const data = await res.json()
      
      const count = data.length
      const combinedRevenue = data.reduce((sum, b) => sum + (b.total_revenue || 0), 0)
      const combinedFiles = data.reduce((sum, b) => sum + (b.upload_count || 0), 0)

      setStats({
        businesses: count,
        revenue: combinedRevenue,
        files: combinedFiles
      })
    } catch (err) {
      console.error(err)
    } finally {
      setLoading(false)
    }
  }

  async function handleFlushAll() {
    if (!window.confirm('Flush context and query response caches for all users?')) return
    try {
      const res = await authFetch(`${API_BASE}/admin/flush-all-cache`, { method: 'POST' })
      const data = await res.json()
      alert(data.message || 'All caches flushed successfully.')
    } catch (err) {
      alert(err.message)
    }
  }

  async function handleResetChroma() {
    if (!window.confirm('Reset Chroma documents collection? This fixes dimensionality mismatch errors.')) return
    try {
      const res = await authFetch(`${API_BASE}/admin/reset-chroma-documents`, { method: 'POST' })
      const data = await res.json()
      alert(data.message || 'Chroma documents reset successfully.')
    } catch (err) {
      alert(err.message)
    }
  }

  async function handleWipeAllData() {
    if (!window.confirm('WARNING: This will permanently delete all dynamic business data (invoices, inventory, payments, uploads, document embeddings, and chat messages) across all user accounts. Proceed?')) return
    try {
      const res = await authFetch(`${API_BASE}/admin/wipe-all-data`, { method: 'DELETE' })
      const data = await res.json()
      alert(data.message || 'All dynamic business data wiped successfully.')
      loadDashboardStats()
    } catch (err) {
      alert(err.message)
    }
  }

  // Handle clicking outside to close dropdown
  useEffect(() => {
    function handleClickOutside() {
      setDropdownOpen(false)
    }
    window.addEventListener('click', handleClickOutside)
    return () => window.removeEventListener('click', handleClickOutside)
  }, [])

  return (
    <div className="admin-main" style={{ margin: 0, padding: 0 }}>
      <div className="admin-header-row">
        <div className="admin-title-group">
          <h1>✦ BIZASSIST ADMIN WORKSPACE</h1>
          <p>Aggregated tracking & telemetry for all enterprise business accounts</p>
        </div>
        <div className="admin-header-actions">
          {/* Flush Cache Dropdown */}
          <div className={`flush-dropdown ${dropdownOpen ? 'open' : ''}`} onClick={e => e.stopPropagation()}>
            <button className="btn-flush" style={{ padding: '10px 16px', fontSize: 13 }} onClick={() => setDropdownOpen(!dropdownOpen)}>
              🗑 System Cache ▾
            </button>
            <div className="flush-dropdown-menu">
              <button className="flush-dropdown-item" onClick={() => { setDropdownOpen(false); handleFlushAll(); }}>
                🔄 Flush All Query Cache
                <span style={{ fontSize: 11, color: 'var(--secondary-text)', marginLeft: 'auto' }}>All users</span>
              </button>
              <button className="flush-dropdown-item" onClick={() => { setDropdownOpen(false); handleResetChroma(); }}>
                🧠 Reset Chroma Documents
                <span style={{ fontSize: 11, color: 'var(--secondary-text)', marginLeft: 'auto' }}>Fix dim errors</span>
              </button>
              <div className="flush-dropdown-divider"></div>
              <button className="flush-dropdown-item danger" onClick={() => { setDropdownOpen(false); handleWipeAllData(); }}>
                ⚠ Wipe All Business Data
              </button>
            </div>
          </div>
        </div>
      </div>

      {loading ? (
        <div className="vskel"></div>
      ) : (
        <>
          {/* STATS STRIP */}
          <div className="vsummary-strip-three" style={{ marginTop: 24 }}>
            <div className="vsummary-card" style={{ borderLeftColor: 'var(--accent-color)', cursor: 'default' }}>
              <div className="vsummary-label">Registered Businesses</div>
              <div className="vsummary-value">{stats.businesses}</div>
              <div className="vsummary-sub">active sandboxes</div>
            </div>
            <div className="vsummary-card" style={{ borderLeftColor: '#3a9a5c', cursor: 'default' }}>
              <div className="vsummary-label">Combined Revenue</div>
              <div className="vsummary-value">₹{stats.revenue.toLocaleString('en-IN')}</div>
              <div className="vsummary-sub">across all accounts</div>
            </div>
            <div className="vsummary-card" style={{ borderLeftColor: '#c97c22', cursor: 'default' }}>
              <div className="vsummary-label">Total Files Logged</div>
              <div className="vsummary-value">{stats.files}</div>
              <div className="vsummary-sub">datasets uploaded</div>
            </div>
          </div>

          {/* Quick guide card */}
          <div className="admin-table-widget" style={{ marginTop: 24 }}>
            <div className="admin-table-title">Admin Quick Operations</div>
            <div style={{ color: 'var(--secondary-text)', fontSize: '13.5px', lineHeight: 1.6, marginTop: 12 }}>
              Welcome to the BizAssist Admin portal. Use the navigation sidebar to:
              <br />• View and manage merchant users, inspect databases, wipe user data, or modify rate limits in **Businesses**.
              <br />• Monitor API requests limits, queries count, token logs, and AI runs in **Usage & Limits**.
              <br />• Inspect active cache memory states and execute database schema resets in **Cache & System**.
            </div>
          </div>
        </>
      )}
    </div>
  )
}
