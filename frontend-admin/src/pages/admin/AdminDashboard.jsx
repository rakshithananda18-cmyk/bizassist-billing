import { useState, useEffect, useRef } from 'react'
import { useAuth } from '../../contexts/AuthContext'
import { logger } from '../../utils/logger'
import { useDialog } from '../../contexts/DialogContext'
import { API_BASE } from '../../config'
import { BuildingMark } from '../../components/Logo'
import { Icon } from '../../components/icons'

export default function AdminDashboard() {
  const { authFetch, adminLogout } = useAuth()
  const { showAlert, showConfirm, showError } = useDialog()
  const [stats, setStats] = useState(null)
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState(null)
  const statsRequest = useRef(0)
  const [dropdownOpen, setDropdownOpen] = useState(false)
  const [routerMode, setRouterMode] = useState(null)      // 'legacy' | 'shadow' | 'new'
  const [routerBusy, setRouterBusy] = useState(false)

  useEffect(() => {
    loadDashboardStats()
    loadRouterMode()
    return () => { ++statsRequest.current }
  }, [])

  async function loadRouterMode() {
    try {
      const res = await authFetch(`${API_BASE}/admin/router-mode`)
      if (res.ok) {
        const data = await res.json()
        setRouterMode(data.mode)
      }
    } catch (err) {
      logger.error('router-mode load failed', err)
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
    const requestId = ++statsRequest.current
    setLoading(true)
    setLoadError(null)
    try {
      const res = await authFetch(`${API_BASE}/admin/businesses`)
      if (!res.ok) throw new Error('Failed to load merchant directory')
      const data = await res.json()
      if (!Array.isArray(data) || data.some(b => !b || b.total_revenue == null || b.upload_count == null
        || !Number.isFinite(Number(b.total_revenue)) || !Number.isFinite(Number(b.upload_count)))) {
        throw new Error('Invalid merchant directory response')
      }
      if (requestId !== statsRequest.current) return
      
      const count = data.length
      const combinedRevenue = data.reduce((sum, b) => sum + Number(b.total_revenue), 0)
      const combinedFiles = data.reduce((sum, b) => sum + Number(b.upload_count), 0)

      setStats({
        businesses: count,
        revenue: combinedRevenue,
        files: combinedFiles
      })
    } catch (err) {
      if (requestId !== statsRequest.current) return
      logger.error(err)
      setLoadError('Business overview could not be loaded.')
    } finally {
      if (requestId === statsRequest.current) setLoading(false)
    }
  }

  async function handleFlushAll() {
    if (!(await showConfirm('Flush context and query response caches for all users?'))) return
    try {
      const res = await authFetch(`${API_BASE}/admin/flush-all-cache`, { method: 'POST' })
      const data = await res.json()
      if (!res.ok) throw new Error(data.detail || data.error || 'Cache flush failed')
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
      if (!res.ok) throw new Error(data.detail || data.error || 'Chroma reset failed')
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
      if (!res.ok) throw new Error(data.detail || data.error || 'Data wipe failed')
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
          <h1 style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <BuildingMark size={24} /> BizAssist Admin Workspace
          </h1>
          <p>Aggregated tracking, limits, and telemetry for all enterprise business accounts</p>
        </div>
        <div className="admin-header-actions">
          <button type="button" className="btn-flush" onClick={loadDashboardStats} disabled={loading}>
            <Icon name="refresh" size={14} /> Refresh overview
          </button>
          {/* Flush Cache Dropdown */}
          <div className={`flush-dropdown ${dropdownOpen ? 'open' : ''}`} onClick={e => e.stopPropagation()}>
            <button className="btn-flush" style={{ padding: '8px 14px', fontSize: 13 }} onClick={() => setDropdownOpen(!dropdownOpen)}>
              <Icon name="trash" size={14} />
              <span>System Cache</span>
              <Icon name="chevronDown" size={12} />
            </button>
            <div className="flush-dropdown-menu">
              <button className="flush-dropdown-item" onClick={() => { setDropdownOpen(false); handleFlushAll(); }}>
                <span style={{ display: 'inline-flex', alignItems: 'center', gap: 8 }}><Icon name="refresh" size={14} /> Flush All Query Cache</span>
                <span style={{ fontSize: 11, color: 'var(--text-muted)', marginLeft: 'auto' }}>All users</span>
              </button>
              <button className="flush-dropdown-item" onClick={() => { setDropdownOpen(false); handleResetChroma(); }}>
                <span style={{ display: 'inline-flex', alignItems: 'center', gap: 8 }}><Icon name="brain" size={14} /> Reset Chroma Documents</span>
                <span style={{ fontSize: 11, color: 'var(--text-muted)', marginLeft: 'auto' }}>Fix dim errors</span>
              </button>
              <div className="flush-dropdown-divider" />
              <button className="flush-dropdown-item danger" onClick={() => { setDropdownOpen(false); handleWipeAllData(); }}>
                <span style={{ display: 'inline-flex', alignItems: 'center', gap: 8 }}><Icon name="warn" size={14} /> Wipe All Business Data</span>
                <span style={{ fontSize: 11, color: 'var(--text-muted)', marginLeft: 'auto' }}>Wipe DB</span>
              </button>
            </div>
          </div>
        </div>
      </div>

      {loadError && <div role="alert" style={{ marginTop: 16, color: 'var(--danger)' }}>
        <p>{loadError}{stats ? ' Showing the last loaded overview.' : ''}</p>
        <button type="button" className="btn-flush" onClick={loadDashboardStats} disabled={loading}>Retry overview</button>
      </div>}
      {loading && !stats ? (
        <div className="vskel"></div>
      ) : stats ? (
        <>
          {/* STATS STRIP */}
          <div style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))',
            gap: 16,
            marginTop: 18,
          }}>
            <div style={{
              background: 'var(--bg-2)',
              border: '1px solid var(--border)',
              borderLeft: '4px solid var(--accent)',
              borderRadius: 'var(--radius-lg, 12px)',
              padding: '18px 20px',
              boxShadow: 'var(--shadow-sm)',
            }}>
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 6 }}>
                <span style={{ fontSize: 11, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.06em', color: 'var(--text-muted)' }}>Registered Businesses</span>
                <Icon name="users" size={16} style={{ color: 'var(--accent)' }} />
              </div>
              <div style={{ fontSize: 28, fontWeight: 700, fontFamily: "var(--font-serif)", color: 'var(--text-primary)' }}>{stats.businesses}</div>
              <div style={{ fontSize: 12, color: 'var(--text-muted)', marginTop: 2 }}>active sandboxes</div>
            </div>

            <div style={{
              background: 'var(--bg-2)',
              border: '1px solid var(--border)',
              borderLeft: '4px solid var(--success)',
              borderRadius: 'var(--radius-lg, 12px)',
              padding: '18px 20px',
              boxShadow: 'var(--shadow-sm)',
            }}>
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 6 }}>
                <span style={{ fontSize: 11, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.06em', color: 'var(--text-muted)' }}>Combined Revenue</span>
                <Icon name="wallet" size={16} style={{ color: 'var(--success)' }} />
              </div>
              <div style={{ fontSize: 28, fontWeight: 700, fontFamily: "var(--font-serif)", color: 'var(--text-primary)' }}>₹{stats.revenue.toLocaleString('en-IN')}</div>
              <div style={{ fontSize: 12, color: 'var(--text-muted)', marginTop: 2 }}>across all accounts</div>
            </div>

            <div style={{
              background: 'var(--bg-2)',
              border: '1px solid var(--border)',
              borderLeft: '4px solid var(--warning)',
              borderRadius: 'var(--radius-lg, 12px)',
              padding: '18px 20px',
              boxShadow: 'var(--shadow-sm)',
            }}>
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 6 }}>
                <span style={{ fontSize: 11, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.06em', color: 'var(--text-muted)' }}>Total Files Logged</span>
                <Icon name="file" size={16} style={{ color: 'var(--warning)' }} />
              </div>
              <div style={{ fontSize: 28, fontWeight: 700, fontFamily: "var(--font-serif)", color: 'var(--text-primary)' }}>{stats.files}</div>
              <div style={{ fontSize: 12, color: 'var(--text-muted)', marginTop: 2 }}>datasets uploaded</div>
            </div>
          </div>

          {/* AI Router Mode switch */}
          <div className="admin-table-widget" style={{ marginTop: 20 }}>
            <div className="admin-table-title" style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <span>AI Router Mode</span>
                {routerMode && (
                  <span className="tag" style={{
                    background: routerMode === 'new' ? 'rgba(99,102,241,.12)'
                              : routerMode === 'shadow' ? 'var(--warning-dim)'
                              : 'var(--bg-1)',
                    color: routerMode === 'new' ? '#6366f1'
                         : routerMode === 'shadow' ? 'var(--warning)'
                         : 'var(--text-secondary)',
                    border: '1px solid var(--border)',
                  }}>
                    {routerMode.toUpperCase()}
                  </span>
                )}
              </div>
            </div>
            <div style={{ color: 'var(--text-muted)', fontSize: 13, lineHeight: 1.5, margin: '8px 0 14px' }}>
              Switch how chat questions are routed — takes effect on the next message without restart.
              Resets to the environment default (<code>LLM_ROUTER</code>) on server reboot.
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: 10 }}>
              {[
                { key: 'legacy', icon: 'building', label: 'Legacy Mode',  desc: 'Exact previous deterministic behaviour' },
                { key: 'shadow', icon: 'eye',      label: 'Shadow Mode',  desc: 'Legacy answers + silent comparison logs' },
                { key: 'new',    icon: 'brain',    label: 'New AI Router', desc: 'LLM router steers with automatic fallback' },
              ].map(opt => {
                const isSelected = routerMode === opt.key
                return (
                  <button
                    key={opt.key}
                    type="button"
                    disabled={routerBusy}
                    onClick={() => handleRouterMode(opt.key)}
                    style={{
                      padding: '12px 14px',
                      borderRadius: 'var(--radius-md, 8px)',
                      textAlign: 'left',
                      cursor: routerBusy ? 'wait' : 'pointer',
                      opacity: routerBusy ? 0.6 : 1,
                      border: isSelected ? '1.5px solid var(--accent)' : '1px solid var(--border)',
                      background: isSelected ? 'var(--accent-dim)' : 'var(--bg-2)',
                      transition: 'all 0.15s ease',
                    }}
                  >
                    <div style={{ display: 'flex', alignItems: 'center', gap: 7, fontWeight: isSelected ? 600 : 500, color: isSelected ? 'var(--accent)' : 'var(--text-primary)', fontSize: 13.5 }}>
                      <Icon name={opt.icon} size={15} />
                      <span>{opt.label}</span>
                    </div>
                    <span style={{ display: 'block', fontSize: 11.5, color: 'var(--text-muted)', marginTop: 4 }}>
                      {opt.desc}
                    </span>
                  </button>
                )
              })}
            </div>
          </div>

          {/* Quick operations guide */}
          <div className="admin-table-widget" style={{ marginTop: 20 }}>
            <div className="admin-table-title">Admin Quick Operations</div>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: 14, marginTop: 12 }}>
              <div style={{ padding: '12px 14px', background: 'var(--bg-1)', borderRadius: 'var(--radius-md, 8px)', border: '1px solid var(--border)' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontWeight: 600, fontSize: 13, color: 'var(--text-primary)', marginBottom: 4 }}>
                  <Icon name="users" size={14} style={{ color: 'var(--accent)' }} /> Businesses
                </div>
                <div style={{ fontSize: 12, color: 'var(--text-muted)', lineHeight: 1.5 }}>
                  View registered merchants, audit user limits, inspect database tables, and manage Pro plans.
                </div>
              </div>

              <div style={{ padding: '12px 14px', background: 'var(--bg-1)', borderRadius: 'var(--radius-md, 8px)', border: '1px solid var(--border)' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontWeight: 600, fontSize: 13, color: 'var(--text-primary)', marginBottom: 4 }}>
                  <Icon name="chart" size={14} style={{ color: 'var(--accent)' }} /> Usage & Limits
                </div>
                <div style={{ fontSize: 12, color: 'var(--text-muted)', lineHeight: 1.5 }}>
                  Monitor daily API request allowances, token burn, queries count, and AI execution times.
                </div>
              </div>

              <div style={{ padding: '12px 14px', background: 'var(--bg-1)', borderRadius: 'var(--radius-md, 8px)', border: '1px solid var(--border)' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontWeight: 600, fontSize: 13, color: 'var(--text-primary)', marginBottom: 4 }}>
                  <Icon name="trash" size={14} style={{ color: 'var(--accent)' }} /> Cache & System
                </div>
                <div style={{ fontSize: 12, color: 'var(--text-muted)', lineHeight: 1.5 }}>
                  Inspect active context and query memory caches, flush stale embeddings, and run schema resets.
                </div>
              </div>
            </div>
          </div>
        </>
      ) : null}
    </div>
  )
}
