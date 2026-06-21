import { useState, useEffect } from 'react'
import { useAuth } from '../../contexts/AuthContext'
import { useDialog } from '../../contexts/DialogContext'
import { API_BASE } from '../../config'
import { BuildingMark } from '../../components/Logo'
import { Icon } from '../../components/icons'

export default function AdminDashboard() {
  const { authFetch, adminLogout } = useAuth()
  const { showAlert, showConfirm, showError } = useDialog()
  const [stats, setStats] = useState({ businesses: 0, revenue: 0, files: 0 })
  const [loading, setLoading] = useState(true)
  const [dropdownOpen, setDropdownOpen] = useState(false)
  const [routerMode, setRouterMode] = useState(null)      // 'legacy' | 'shadow' | 'new'
  const [routerBusy, setRouterBusy] = useState(false)

  useEffect(() => {
    loadDashboardStats()
    loadRouterMode()
  }, [])

  async function loadRouterMode() {
    try {
      const res = await authFetch(`${API_BASE}/admin/router-mode`)
      if (res.ok) {
        const data = await res.json()
        setRouterMode(data.mode)
      }
    } catch (err) {
      console.error('router-mode load failed', err)
    }
  }

  async function handleRouterMode(mode) {
    if (mode === routerMode || routerBusy) return
    const blurb = {
      legacy: 'Switch to LEGACY routing? The app behaves exactly like the previous version (LLM router never called).',
      shadow: 'Switch to SHADOW mode? Legacy keeps answering; the new LLM router silently logs comparisons for the report.',
      new:    'Switch to NEW routing? The LLM router steers (advice, gated actions, analysis). Legacy stays as automatic fallback.',
    }[mode]
    if (!(await showConfirm(blurb))) return
    setRouterBusy(true)
    try {
      const res = await authFetch(`${API_BASE}/admin/router-mode`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ mode }),
      })
      const data = await res.json()
      if (!res.ok) throw new Error(data.detail || data.error || 'Switch failed')
      setRouterMode(data.mode)
      await showAlert(data.message || `Routing switched to ${data.mode}.`)
    } catch (err) {
      await showError(err)
    } finally {
      setRouterBusy(false)
    }
  }

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
    if (!(await showConfirm('Flush context and query response caches for all users?'))) return
    try {
      const res = await authFetch(`${API_BASE}/admin/flush-all-cache`, { method: 'POST' })
      const data = await res.json()
      await showAlert(data.message || 'All caches flushed successfully.')
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
    } catch (err) {
      await showError(err)
    }
  }

  async function handleWipeAllData() {
    if (!(await showConfirm('WARNING: This will permanently delete all dynamic business data (invoices, inventory, payments, uploads, document embeddings, and chat messages) across all user accounts. Proceed?'))) return
    try {
      const res = await authFetch(`${API_BASE}/admin/wipe-all-data`, { method: 'DELETE' })
      const data = await res.json()
      await showAlert(data.message || 'All dynamic business data wiped successfully.')
      loadDashboardStats()
    } catch (err) {
      await showError(err)
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
          <h1 style={{ display: 'flex', alignItems: 'center', gap: 8 }}><BuildingMark size={24} /> BIZASSIST ADMIN WORKSPACE</h1>
          <p>Aggregated tracking & telemetry for all enterprise business accounts</p>
        </div>
        <div className="admin-header-actions">
          {/* Flush Cache Dropdown */}
          <div className={`flush-dropdown ${dropdownOpen ? 'open' : ''}`} onClick={e => e.stopPropagation()}>
            <button className="btn-flush" style={{ padding: '10px 16px', fontSize: 13, display: 'inline-flex', alignItems: 'center', gap: 6 }} onClick={() => setDropdownOpen(!dropdownOpen)}>
              <Icon name="trash" size={14} /> System Cache <Icon name="chevronDown" size={12} />
            </button>
            <div className="flush-dropdown-menu">
              <button className="flush-dropdown-item" onClick={() => { setDropdownOpen(false); handleFlushAll(); }}>
                <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}><Icon name="refresh" size={14} /> Flush All Query Cache</span>
                <span style={{ fontSize: 11, color: 'var(--secondary-text)', marginLeft: 'auto' }}>All users</span>
              </button>
              <button className="flush-dropdown-item" onClick={() => { setDropdownOpen(false); handleResetChroma(); }}>
                <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}><Icon name="brain" size={14} /> Reset Chroma Documents</span>
                <span style={{ fontSize: 11, color: 'var(--secondary-text)', marginLeft: 'auto' }}>Fix dim errors</span>
              </button>
              <button className="flush-dropdown-item" onClick={() => { setDropdownOpen(false); handleWipeAllData(); }} style={{ borderTop: '1px solid var(--border-color)' }}>
                <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6, color: 'var(--danger-color)' }}><Icon name="warn" size={14} /> Wipe All Business Data</span>
                <span style={{ fontSize: 11, color: 'var(--secondary-text)', marginLeft: 'auto' }}>Wipe DB</span>
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

          {/* AI Router Mode switch */}
          <div className="admin-table-widget" style={{ marginTop: 24 }}>
            <div className="admin-table-title">
              AI Router Mode
              {routerMode && (
                <span style={{
                  marginLeft: 10, fontSize: 12, padding: '3px 10px', borderRadius: 12,
                  background: routerMode === 'new' ? 'rgba(99,102,241,.15)'
                            : routerMode === 'shadow' ? 'rgba(201,124,34,.15)'
                            : 'rgba(100,116,139,.15)',
                  color: routerMode === 'new' ? '#6366f1'
                       : routerMode === 'shadow' ? '#c97c22'
                       : 'var(--secondary-text)',
                }}>
                  ● {routerMode.toUpperCase()}
                </span>
              )}
            </div>
            <div style={{ color: 'var(--secondary-text)', fontSize: '13.5px', lineHeight: 1.6, margin: '10px 0 14px' }}>
              Switch how chat questions are routed — takes effect on the next message, no restart.
              Resets to the .env default (<code>LLM_ROUTER</code>) on server restart.
            </div>
            <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
              {[
                { key: 'legacy', icon: <Icon name="building" size={16} />, label: 'Legacy',  desc: 'exact previous behaviour' },
                { key: 'shadow', icon: <Icon name="eye" size={16} />, label: 'Shadow',  desc: 'legacy answers + comparison logs' },
                { key: 'new',    icon: <Icon name="brain" size={16} />, label: 'New',     desc: 'LLM router steers, legacy fallback' },
              ].map(opt => (
                <button
                  key={opt.key}
                  className="btn-flush"
                  disabled={routerBusy}
                  onClick={() => handleRouterMode(opt.key)}
                  style={{
                    padding: '10px 16px', fontSize: 13, textAlign: 'left',
                    opacity: routerBusy ? 0.6 : 1,
                    border: routerMode === opt.key
                      ? '2px solid var(--accent-color)' : '1px solid var(--border-color)',
                    fontWeight: routerMode === opt.key ? 700 : 500,
                  }}
                >
                  {opt.icon} {opt.label}
                  <span style={{ display: 'block', fontSize: 11, color: 'var(--secondary-text)', fontWeight: 400 }}>
                    {opt.desc}
                  </span>
                </button>
              ))}
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
