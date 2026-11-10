import { useCallback, useState, useEffect, useRef } from 'react'
import { useAuth } from '../../contexts/AuthContext'
import { logger } from '../../utils/logger'
import { useDialog } from '../../contexts/DialogContext'
import { API_BASE } from '../../config'
import { Link } from 'react-router-dom'
import { formatAdminTime } from '../../utils/adminPreferences'
import '../../styles/overview.css'
import { Icon } from '../../components/icons'

export default function AdminDashboard() {
  const { authFetch, adminUser } = useAuth()
  const { showAlert, showConfirm, showError } = useDialog()
  const [stats, setStats] = useState(null)
  const [loading, setLoading] = useState(true)
  const [loadedAt, setLoadedAt] = useState(null)
  const [loadError, setLoadError] = useState(null)
  const statsRequest = useRef(0)
  const [dropdownOpen, setDropdownOpen] = useState(false)
  const [routerMode, setRouterMode] = useState(null)      // 'legacy' | 'shadow' | 'new'
  const [routerBusy, setRouterBusy] = useState(false)



  const loadRouterMode = useCallback(async () => {
    try {
      const res = await authFetch(`${API_BASE}/admin/router-mode`)
      if (res.ok) {
        const data = await res.json()
        setRouterMode(data.mode)
      }
    } catch (err) {
      logger.error('router-mode load failed', err)
    }
  }, [authFetch])

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

  const loadDashboardStats = useCallback(async () => {
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
        files: combinedFiles,
        records: [...data].sort((a, b) => (a.business_name || a.username || '').localeCompare(b.business_name || b.username || '')).slice(0, 5),
      })
      setLoadedAt(new Date().toISOString())
    } catch (err) {
      if (requestId !== statsRequest.current) return
      logger.error(err)
      setLoadError('Business overview could not be loaded.')
    } finally {
      if (requestId === statsRequest.current) setLoading(false)
    }
  }, [authFetch])

  useEffect(() => {
    const requestCounter = statsRequest
    loadDashboardStats()
    loadRouterMode()
    return () => { ++requestCounter.current }
  }, [loadDashboardStats, loadRouterMode])

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
    const onKey = event => { if (event.key === 'Escape') setDropdownOpen(false) }
    window.addEventListener('click', handleClickOutside)
    window.addEventListener('keydown', onKey)
    return () => { window.removeEventListener('click', handleClickOutside); window.removeEventListener('keydown', onKey) }
  }, [])

  const workspaces = [
    { to: '/admin/businesses', icon: 'users', title: 'Support a business', copy: 'Accounts, plans, access and business records.' },
    { to: '/admin/metrics', icon: 'chart', title: 'Follow adoption', copy: 'Activation, plan mix and businesses to follow up.' },
    { to: '/admin/health', icon: 'shield', title: 'Check diagnostics', copy: 'Review service health and audit results.' },
    { to: '/admin/telemetry', icon: 'activity', title: 'Trace an issue', copy: 'Find events and logs for a closer look.' },
  ]
  const displayCount = value => value != null && Number.isFinite(Number(value)) ? Number(value).toLocaleString('en-IN') : '—'

  return (
    <div className="admin-main admin-overview">
      <header className="overview-heading">
        <div>
          <p className="overview-eyebrow">The operations desk</p>
          <h1>Your platform.<br /><span>A clearer perspective.</span></h1>
          <p className="overview-intro">Welcome back{adminUser?.username ? `, ${adminUser.username}` : ''}. Keep an eye on the businesses you support, then get straight to the work that matters.</p>
        </div>
        <div className="overview-heading-actions">
          <Link className="overview-primary-link" to="/admin/businesses">Open business directory <Icon name="chevronRight" size={15} /></Link>
          <button type="button" className="btn-flush overview-refresh" onClick={loadDashboardStats} disabled={loading}>
            <Icon name="refresh" size={14} /> Refresh overview
          </button>
        </div>
      </header>

      {loadError && <div className="overview-load-notice" role="alert">
        <Icon name="alert" size={17} />
        <p>{loadError}{stats ? ' Showing the last loaded overview.' : ''}</p>
        <button type="button" className="btn-flush" onClick={loadDashboardStats} disabled={loading}>Retry overview</button>
      </div>}
      {loading && !stats ? (
        <div className="overview-skeleton" role="status" aria-label="Loading business overview"><div /><div /><div /></div>
      ) : stats ? (
        <>
          <section className="overview-stat-section" aria-label="Business overview totals">
            <div className="overview-section-meta"><span>Business snapshot</span><span><Icon name="clock" size={12} /> Updated {formatAdminTime(loadedAt)}</span></div>
            <div className="overview-stats">
              <div className="overview-stat overview-stat-featured">
                <div className="overview-stat-top"><span>Registered Businesses</span><Icon name="users" size={19} /></div>
                <strong>{stats.businesses.toLocaleString('en-IN')}</strong>
                <p>Accounts in the business directory</p>
                <Link to="/admin/businesses">View directory <Icon name="chevronRight" size={13} /></Link>
              </div>
              <div className="overview-stat">
                <div className="overview-stat-top"><span>Business revenue</span><Icon name="wallet" size={19} /></div>
                <strong>₹{stats.revenue.toLocaleString('en-IN')}</strong>
                <p>Recorded across these business accounts</p>
                <span className="overview-stat-note">Merchant sales, across all recorded periods</span>
              </div>
              <div className="overview-stat">
                <div className="overview-stat-top"><span>Files uploaded</span><Icon name="file" size={19} /></div>
                <strong>{stats.files.toLocaleString('en-IN')}</strong>
                <p>Documents and datasets in these accounts</p>
                <Link to="/admin/usage">Review usage &amp; limits <Icon name="chevronRight" size={13} /></Link>
              </div>
            </div>
          </section>

          <div className="overview-work-grid">
            <section className="overview-business-panel" aria-labelledby="overview-business-title">
              <div className="overview-panel-heading"><div><span className="overview-eyebrow">The businesses behind the numbers</span><h2 id="overview-business-title">Business directory</h2></div><Link to="/admin/businesses">View all <Icon name="chevronRight" size={13} /></Link></div>
              {stats.records.length ? <div className="overview-business-table-wrap"><table className="overview-business-table">
                <thead><tr><th>Business</th><th>Inventory</th><th>Invoices</th><th><span className="overview-sr-only">Open account</span></th></tr></thead>
                <tbody>{stats.records.map((business, index) => <tr key={business.id ?? `${business.username}-${index}`}>
                  <td><div className="overview-business-identity"><span className="overview-business-initial" aria-hidden="true">{(business.business_name || business.username || 'B').trim().charAt(0).toUpperCase()}</span><div>{business.id != null ? <Link to={`/admin/businesses/${business.id}`}>{business.business_name || business.username || 'Unnamed business'}</Link> : <strong>{business.business_name || business.username || 'Unnamed business'}</strong>}<span>{business.bizid || business.public_id || 'BizID unavailable'}</span></div></div></td>
                  <td>{displayCount(business.inventory_count)}</td><td>{displayCount(business.invoice_count)}</td>
                  <td>{business.id != null && <Link className="overview-business-open" to={`/admin/businesses/${business.id}`} aria-label={`Open ${business.business_name || business.username || 'business'} account`}><Icon name="chevronRight" size={16} /></Link>}</td>
                </tr>)}</tbody>
              </table></div> : <div className="overview-empty"><Icon name="building" size={30} /><h3>Your directory starts here.</h3><p>Registered businesses will appear here with their inventory and invoice counts.</p><Link to="/admin/businesses">Open the business directory <Icon name="chevronRight" size={13} /></Link></div>}
              {stats.records.length > 0 && <p className="overview-table-note">Showing up to five businesses, sorted by name. Open the directory to search and manage every account.</p>}
            </section>

            <section className="overview-workspaces" aria-labelledby="overview-workspaces-title">
              <div className="overview-panel-heading"><div><span className="overview-eyebrow">Pick up the next task</span><h2 id="overview-workspaces-title">A place for every operation.</h2></div></div>
              <div className="overview-workspace-list">{workspaces.map(workspace => <Link key={workspace.to} className="overview-workspace-link" to={workspace.to}><span className="overview-workspace-icon"><Icon name={workspace.icon} size={17} /></span><span><strong>{workspace.title}</strong><small>{workspace.copy}</small></span><Icon name="chevronRight" size={14} /></Link>)}</div>
            </section>
          </div>

          <section className="overview-runtime" aria-labelledby="overview-runtime-title">
            <div className="overview-panel-heading"><div><span className="overview-eyebrow">Platform controls</span><h2 id="overview-runtime-title">Runtime &amp; maintenance</h2></div>
              <div className={`flush-dropdown ${dropdownOpen ? 'open' : ''}`} onClick={e => e.stopPropagation()}>
                <button type="button" className="btn-flush" aria-expanded={dropdownOpen} aria-controls="overview-cache-menu" onClick={() => setDropdownOpen(!dropdownOpen)}><Icon name="settings" size={14} /> System Cache <Icon name="chevronDown" size={12} /></button>
                {dropdownOpen && <div className="flush-dropdown-menu" id="overview-cache-menu">
                  <button className="flush-dropdown-item" onClick={() => { setDropdownOpen(false); handleFlushAll(); }}><Icon name="refresh" size={14} /><span>Flush All Query Cache</span></button>
                  <button className="flush-dropdown-item" onClick={() => { setDropdownOpen(false); handleResetChroma(); }}><Icon name="brain" size={14} /><span>Reset Chroma Documents</span></button>
                  <div className="flush-dropdown-divider" />
                  <button className="flush-dropdown-item danger" onClick={() => { setDropdownOpen(false); handleWipeAllData(); }}><Icon name="warn" size={14} /><span>Wipe All Business Data</span></button>
                </div>}
              </div>
            </div>
            <div className="overview-router-heading"><div><h3>AI Router Mode <span className="overview-router-state">{routerMode ? routerMode.toUpperCase() : 'UNAVAILABLE'}</span></h3><p>Choose how chat requests are handled. Changes take effect on the next message; a server restart restores the environment default.</p></div><Icon name="sliders" size={21} /></div>
            <div className="overview-router-options">
              {[
                { key: 'legacy', icon: 'building', label: 'Legacy Mode', desc: 'Use the established deterministic routing.' },
                { key: 'shadow', icon: 'eye', label: 'Shadow Mode', desc: 'Keep legacy answers and log new-router comparisons.' },
                { key: 'new', icon: 'brain', label: 'New AI Router', desc: 'Let the LLM router steer, with automatic legacy fallback.' },
              ].map(option => <button key={option.key} type="button" className={`overview-router-option ${routerMode === option.key ? 'is-selected' : ''}`} aria-pressed={routerMode === option.key} disabled={routerBusy} onClick={() => handleRouterMode(option.key)}><span><Icon name={option.icon} size={17} /><strong>{option.label}</strong>{routerMode === option.key && <Icon name="check" size={14} />}</span><small>{option.desc}</small></button>)}
            </div>
          </section>
        </>
      ) : null}
    </div>
  )
}
