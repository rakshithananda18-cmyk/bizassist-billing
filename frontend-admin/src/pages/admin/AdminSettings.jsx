import { useState, useEffect, useMemo } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { useAuth } from '../../contexts/AuthContext'
import { API_BASE } from '../../config'
import { Icon } from '../../components/icons'
import TwoFactorCard from '../../components/TwoFactorCard'
import { useDialog } from '../../contexts/DialogContext'
import { formatAdminTime, useAdminPreference, useAdminTheme } from '../../utils/adminPreferences'

const ROUTER_MODES = ['legacy', 'shadow', 'new']

const SETTINGS_CATEGORIES = [
  {
    title: 'Platform & Security',
    tabs: [
      { id: 'appearance', label: 'Display & Appearance', icon: 'sun', desc: 'Theme, rail mode & layout' },
      { id: 'security',   label: 'Security & 2FA',       icon: 'shield', desc: 'TOTP, credentials & session' },
    ]
  },
  {
    title: 'AI Model & Router',
    tabs: [
      { id: 'router',     label: 'AI Model Router',      icon: 'sparkle', desc: 'Provider routing & fallback' },
      { id: 'limits',     label: 'Rate Limits & Quotas', icon: 'chart', desc: 'API throttles & daily caps' },
    ]
  },
  {
    title: 'Diagnostics & Operations',
    tabs: [
      { id: 'system',     label: 'System & Doctor',      icon: 'server', desc: 'Chroma, DB ping & cache' },
      { id: 'feedback',   label: 'Merchant Support Logs', icon: 'chat', desc: 'Feedback & issue reports' },
    ]
  }
]

export default function AdminSettings() {
  const { authFetch, adminUser } = useAuth()
  const { showAlert, showConfirm } = useDialog()
  const [searchParams, setSearchParams] = useSearchParams()
  const requestedTab = searchParams.get('tab')
  const activeTab = SETTINGS_CATEGORIES.some(category => category.tabs.some(tab => tab.id === requestedTab)) ? requestedTab : 'appearance'
  const [searchQuery, setSearchQuery] = useState('')

  // Appearance state
  const [isDark, handleThemeChange] = useAdminTheme()
  const [timeFormat, handleTimeFormatChange] = useAdminPreference('admin_time_format')
  const [pollInterval, handlePollIntervalChange] = useAdminPreference('admin_poll_interval')

  // AI Router state
  const [routerMode, setRouterMode] = useState('')
  const [routerLoaded, setRouterLoaded] = useState(false)
  const [routerBusy, setRouterBusy] = useState(false)
  const [routerMsg, setRouterMsg] = useState(null)

  // System cache & diagnostics
  const [cacheStats, setCacheStats] = useState(null)
  const [systemBusy, setSystemBusy] = useState(false)
  const [dbHealth, setDbHealth] = useState(null)
  const [dbError, setDbError] = useState(null)

  // Merchant Feedback logs
  const [feedbackLogs, setFeedbackLogs] = useState([])
  const [feedbackLoading, setFeedbackLoading] = useState(false)
  const [feedbackError, setFeedbackError] = useState(null)

  // Copied BizID toast indicator
  const [copiedBizId, setCopiedBizId] = useState(false)
  const adminBizId = adminUser?.public_id || adminUser?.bizid || null

  function setActiveTab(id) {
    setSearchParams({ tab: id })
  }

  // Load router mode & cache stats on mount
  useEffect(() => {
    async function loadConfig() {
      try {
        const res = await authFetch(`${API_BASE}/admin/router-mode`)
        if (res.ok) {
          const data = await res.json()
          if (!ROUTER_MODES.includes(data.mode)) throw new Error('Unknown router mode returned by server')
          setRouterMode(data.mode)
          setRouterLoaded(true)
        } else throw new Error('Router configuration is unavailable')
      } catch (err) {
        console.error('Failed to load router config:', err)
        setRouterMsg({ ok: false, text: err.message })
      }

      try {
        const res = await authFetch(`${API_BASE}/admin/cache-stats`)
        if (res.ok) {
          const stats = await res.json()
          setCacheStats(stats)
        }
      } catch (err) {
        console.error('Failed to load cache stats:', err)
      }
    }
    loadConfig()
  }, [authFetch])

  // Load feedback logs when feedback tab active
  useEffect(() => {
    let cancelled = false
    if (activeTab === 'feedback') {
      setFeedbackLoading(true)
      setFeedbackError(null)
      authFetch(`${API_BASE}/admin/feedbacks`)
        .then(res => { if (!res.ok) throw new Error('Support tickets could not be loaded.'); return res.json() })
        .then(data => { if (!cancelled) setFeedbackLogs(Array.isArray(data) ? data : []) })
        .catch(error => { if (!cancelled) setFeedbackError(error.message) })
        .finally(() => { if (!cancelled) setFeedbackLoading(false) })
    }
    return () => { cancelled = true }
  }, [activeTab, authFetch])

  useEffect(() => {
    if (activeTab !== 'system') return undefined
    let cancelled = false
    setDbError(null)
    authFetch(`${API_BASE}/admin/health-check`)
      .then(res => { if (!res.ok) throw new Error('Database status is unavailable.'); return res.json() })
      .then(data => { if (!cancelled) setDbHealth(data) })
      .catch(error => { if (!cancelled) setDbError(error.message) })
    return () => { cancelled = true }
  }, [activeTab, authFetch])

  async function handleSaveRouter(e) {
    e.preventDefault()
    if (!routerLoaded || !ROUTER_MODES.includes(routerMode) || routerBusy) return
    if (!(await showConfirm(`Switch platform routing to ${routerMode.toUpperCase()}? This affects live merchant queries and resets to the configured default after a server restart.`))) return
    setRouterBusy(true)
    setRouterMsg(null)
    try {
      const res = await authFetch(`${API_BASE}/admin/router-mode`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ mode: routerMode })
      })
      const data = await res.json().catch(() => ({}))
      if (!res.ok) throw new Error(data.detail || 'Failed to update router configuration')
      setRouterMode(data.mode)
      setRouterMsg({ ok: true, text: data.message || 'AI Router configuration saved successfully' })
    } catch (err) {
      setRouterMsg({ ok: false, text: err.message })
    } finally {
      setRouterBusy(false)
    }
  }

  async function handleFlushAllCache() {
    const ok = await showConfirm('Flush system cache? This clears query response caches across all tenants. Active sessions remain logged in.')
    if (!ok) return

    setSystemBusy(true)
    try {
      const res = await authFetch(`${API_BASE}/admin/flush-all-cache`, { method: 'POST' })
      if (!res.ok) throw new Error('Failed to flush system cache')
      const statsRes = await authFetch(`${API_BASE}/admin/cache-stats`)
      if (statsRes.ok) setCacheStats(await statsRes.json())
      await showAlert('System query response caches have been cleared.')
    } catch (err) {
      await showAlert(`Flush failed: ${err.message}`)
    } finally {
      setSystemBusy(false)
    }
  }

  async function handleResetChroma() {
    const ok = await showConfirm('Reset ChromaDB documents? This clears the vector collection used by semantic business search. Documents will need to be indexed again.')
    if (!ok) return

    setSystemBusy(true)
    try {
      const res = await authFetch(`${API_BASE}/admin/reset-chroma-documents`, { method: 'POST' })
      if (!res.ok) throw new Error('Failed to reset ChromaDB documents')
      await showAlert('ChromaDB documents and vector embeddings have been reset.')
    } catch (err) {
      await showAlert(`Reset failed: ${err.message}`)
    } finally {
      setSystemBusy(false)
    }
  }

  async function copyAdminBizId() {
    if (!adminBizId) return
    try {
      if (!navigator.clipboard?.writeText) throw new Error('Clipboard is unavailable in this browser.')
      await navigator.clipboard.writeText(adminBizId)
      setCopiedBizId(true)
      setTimeout(() => setCopiedBizId(false), 2000)
    } catch { await showAlert('BizID could not be copied. Select and copy the displayed ID manually.') }
  }

  // Filter categories and tabs based on search
  const filteredCategories = useMemo(() => {
    if (!searchQuery.trim()) return SETTINGS_CATEGORIES
    const q = searchQuery.toLowerCase()
    return SETTINGS_CATEGORIES.map(cat => ({
      ...cat,
      tabs: cat.tabs.filter(t => t.label.toLowerCase().includes(q) || t.desc.toLowerCase().includes(q) || t.id.includes(q))
    })).filter(cat => cat.tabs.length > 0)
  }, [searchQuery])

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', minHeight: 0, gap: 14 }}>
      {/* Header Breadcrumb & Title */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: 12 }}>
        <div>
          <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.06em' }}>
            BizAssist Admin / Preferences
          </div>
          <h1 style={{ fontFamily: "var(--font-serif, 'Crimson Pro', Georgia, serif)", fontSize: 24, fontWeight: 700, margin: '2px 0 0', color: 'var(--text-primary)' }}>
            System & Admin Settings
          </h1>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <div style={{
            fontSize: 12,
            fontFamily: "var(--font-mono, monospace)",
            background: 'var(--bg-3)',
            padding: '5px 10px',
            borderRadius: 'var(--radius-md, 8px)',
            border: '1px solid var(--border)',
            display: 'flex',
            alignItems: 'center',
            gap: 6
          }}>
            <span style={{ color: 'var(--text-muted)' }}>Admin BizID:</span>
            <span style={{ fontWeight: 700, color: 'var(--accent)' }}>{adminBizId || 'Unavailable'}</span>
            <button
              type="button"
              disabled={!adminBizId}
              onClick={copyAdminBizId}
              style={{ background: 'none', border: 'none', cursor: 'pointer', padding: 2, color: 'var(--text-muted)', display: 'flex' }}
              title="Copy BizID"
            >
              <Icon name={copiedBizId ? "check" : "copy"} size={13} style={{ color: copiedBizId ? 'var(--success)' : 'inherit' }} />
            </button>
          </div>
        </div>
      </div>

      {/* Split-Pane Settings Container */}
      <div className="settings-split-layout">
        <div className="settings-mobile-nav">
          <label htmlFor="admin-settings-section">Settings section</label>
          <select id="admin-settings-section" value={activeTab} onChange={event => setActiveTab(event.target.value)}>
            {SETTINGS_CATEGORIES.map(category => <optgroup key={category.title} label={category.title}>
              {category.tabs.map(tab => <option key={tab.id} value={tab.id}>{tab.label}</option>)}
            </optgroup>)}
          </select>
        </div>
        {/* Left Categories Sidebar */}
        <div className="settings-sub-sidebar">
          {/* Search Input */}
          <div style={{ position: 'relative', marginBottom: 6 }}>
            <span style={{ position: 'absolute', left: 9, top: '50%', transform: 'translateY(-50%)', color: 'var(--text-muted)', display: 'flex' }}>
              <Icon name="search" size={14} />
            </span>
            <input
              type="text"
              placeholder="Filter settings..."
              value={searchQuery}
              onChange={e => setSearchQuery(e.target.value)}
              style={{
                width: '100%',
                padding: '6px 10px 6px 30px',
                fontSize: 12.5,
                borderRadius: 'var(--radius-md, 8px)',
                border: '1px solid var(--border)',
                background: 'var(--bg-2)',
                color: 'var(--text-primary)',
                outline: 'none',
                boxSizing: 'border-box'
              }}
            />
          </div>

          <div className="settings-sub-sidebar-header">
            <span className="settings-sub-sidebar-title">Categories</span>
            <span style={{ fontSize: 10.5, color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>6 TABS</span>
          </div>

          {/* Grouped Nav Items */}
          <div className="settings-nav-groups">
            {filteredCategories.map(cat => (
              <div key={cat.title} className="settings-nav-group">
                <div className="settings-nav-group-label">{cat.title}</div>
                <div className="settings-nav-items">
                  {cat.tabs.map(tab => (
                    <button
                      key={tab.id}
                      type="button"
                      onClick={() => setActiveTab(tab.id)}
                      aria-current={activeTab === tab.id ? 'page' : undefined}
                      className={`settings-nav-item ${activeTab === tab.id ? 'active' : ''}`}
                    >
                      <div className="settings-nav-icon">
                        <Icon name={tab.icon} size={15} />
                      </div>
                      <div className="settings-nav-text">
                        <div className="settings-nav-label">{tab.label}</div>
                        <div className="settings-nav-desc">{tab.desc}</div>
                      </div>
                    </button>
                  ))}
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* Right Content Panel */}
        <div className="settings-panel-body">
          {/* TAB 1: APPEARANCE & DISPLAY */}
          {activeTab === 'appearance' && (
            <div>
              <div className="settings-card">
                <div className="settings-card-header">
                  <div>
                    <div className="settings-card-title">
                      <Icon name="sun" size={18} />
                      <span>Interface Theme & Surface</span>
                    </div>
                    <div className="settings-card-desc">
                      Select your preferred appearance for the administrative workspace.
                    </div>
                  </div>
                </div>

                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: 14, marginTop: 8 }}>
                  <button
                    type="button"
                    onClick={() => handleThemeChange(false)}
                    style={{
                      padding: 16,
                      borderRadius: 'var(--radius-md, 8px)',
                      border: !isDark ? '2px solid var(--accent)' : '1px solid var(--border)',
                      background: '#ffffff',
                      color: '#000000',
                      textAlign: 'left',
                      cursor: 'pointer',
                      boxShadow: 'var(--shadow-sm)',
                      display: 'flex',
                      flexDirection: 'column',
                      gap: 8,
                      position: 'relative'
                    }}
                  >
                    {!isDark && (
                      <span style={{ position: 'absolute', top: 12, right: 12, color: 'var(--accent)' }}>
                        <Icon name="check" size={16} />
                      </span>
                    )}
                    <div style={{ display: 'flex', alignItems: 'center', gap: 8, fontWeight: 700, fontSize: 14 }}>
                      <Icon name="sun" size={16} />
                      <span>Claude Warm Light</span>
                    </div>
                    <div style={{ fontSize: 12, color: '#555555' }}>
                      Pampas cream canvas, pure white card surfaces, crail terracotta accents.
                    </div>
                  </button>

                  <button
                    type="button"
                    onClick={() => handleThemeChange(true)}
                    style={{
                      padding: 16,
                      borderRadius: 'var(--radius-md, 8px)',
                      border: isDark ? '2px solid var(--accent)' : '1px solid var(--border)',
                      background: '#1e1e1e',
                      color: '#f5f5f4',
                      textAlign: 'left',
                      cursor: 'pointer',
                      boxShadow: 'var(--shadow-sm)',
                      display: 'flex',
                      flexDirection: 'column',
                      gap: 8,
                      position: 'relative'
                    }}
                  >
                    {isDark && (
                      <span style={{ position: 'absolute', top: 12, right: 12, color: 'var(--accent)' }}>
                        <Icon name="check" size={16} />
                      </span>
                    )}
                    <div style={{ display: 'flex', alignItems: 'center', gap: 8, fontWeight: 700, fontSize: 14 }}>
                      <Icon name="moon" size={16} />
                      <span>Deep Charcoal Dark</span>
                    </div>
                    <div style={{ fontSize: 12, color: '#a09f9a' }}>
                      Low glare deep surface, high contrast typography, warm amber accents.
                    </div>
                  </button>
                </div>
              </div>

              <div className="settings-card">
                <div className="settings-card-header">
                  <div>
                    <div className="settings-card-title">
                      <Icon name="clock" size={18} />
                      <span>Regional Time & Telemetry Refresh</span>
                    </div>
                    <div className="settings-card-desc">
                      Configure live dashboard update intervals and timestamps.
                    </div>
                  </div>
                </div>

                <div className="setting-row">
                  <div>
                    <div className="setting-row-label">Timestamp Display Standard</div>
                    <div className="setting-row-desc">Show dates in Indian Standard Time (IST) or UTC.</div>
                  </div>
                  <select
                    aria-label="Timestamp display standard"
                    value={timeFormat}
                    onChange={e => handleTimeFormatChange(e.target.value)}
                    style={{
                      padding: '6px 12px',
                      borderRadius: 'var(--radius-md, 8px)',
                      border: '1px solid var(--border)',
                      background: 'var(--bg-2)',
                      color: 'var(--text-primary)',
                      fontSize: 13
                    }}
                  >
                    <option value="IST">IST (Indian Standard Time, GMT+5:30)</option>
                    <option value="UTC">UTC (Universal Coordinated Time)</option>
                  </select>
                </div>

                <div className="setting-row">
                  <div>
                    <div className="setting-row-label">Telemetry Live Stream Poll Rate</div>
                    <div className="setting-row-desc">How frequently background audit logs fetch new field events.</div>
                  </div>
                  <select
                    aria-label="Telemetry refresh interval"
                    value={pollInterval}
                    onChange={e => handlePollIntervalChange(e.target.value)}
                    style={{
                      padding: '6px 12px',
                      borderRadius: 'var(--radius-md, 8px)',
                      border: '1px solid var(--border)',
                      background: 'var(--bg-2)',
                      color: 'var(--text-primary)',
                      fontSize: 13
                    }}
                  >
                    <option value="5">Every 5 Seconds (High Frequency)</option>
                    <option value="10">Every 10 Seconds (Recommended)</option>
                    <option value="30">Every 30 Seconds (Bandwidth Saver)</option>
                  </select>
                </div>
              </div>
            </div>
          )}

          {/* TAB 2: SECURITY & 2FA */}
          {activeTab === 'security' && (
            <div>
              <div className="settings-card">
                <div className="settings-card-header">
                  <div>
                    <div className="settings-card-title">
                      <Icon name="shield" size={18} />
                      <span>Administrative Two-Factor Authentication</span>
                    </div>
                    <div className="settings-card-desc">
                      Enforce TOTP authenticator app verification (Google Authenticator, Authy, 1Password) on admin login.
                    </div>
                  </div>
                </div>

                <TwoFactorCard />
              </div>

              <div className="settings-card">
                <div className="settings-card-header">
                  <div>
                    <div className="settings-card-title">
                      <Icon name="key" size={18} />
                      <span>Active Session & Access Verification</span>
                    </div>
                    <div className="settings-card-desc">
                      Details regarding current JWT security context and privileges.
                    </div>
                  </div>
                </div>

                <div className="setting-row">
                  <div>
                    <div className="setting-row-label">Authenticated Role</div>
                    <div className="setting-row-desc">Super Administrator · Full fleet access</div>
                  </div>
                  <span className="tag" style={{ background: 'var(--success-dim)', color: 'var(--success)', border: '1px solid rgba(31,107,58,0.2)' }}>
                    ACTIVE SESSION
                  </span>
                </div>

                <div className="setting-row">
                  <div>
                    <div className="setting-row-label">Admin BizID Identifier</div>
                    <div className="setting-row-desc">Database tenant partition key for platform administration.</div>
                  </div>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                    <code style={{ fontFamily: 'var(--font-mono)', fontWeight: 700 }}>{adminBizId || 'Unavailable'}</code>
                    <button
                      type="button"
                      disabled={!adminBizId}
                      onClick={copyAdminBizId}
                      className="btn-flush"
                      style={{ padding: '4px 8px', fontSize: 12, borderRadius: 6 }}
                    >
                      <Icon name={copiedBizId ? "check" : "copy"} size={13} />
                      <span>{copiedBizId ? 'Copied' : 'Copy'}</span>
                    </button>
                  </div>
                </div>
              </div>
            </div>
          )}

          {/* TAB 3: AI MODEL ROUTER */}
          {activeTab === 'router' && (
            <div>
              <div className="settings-card">
                <div className="settings-card-header">
                  <div>
                    <div className="settings-card-title">
                      <Icon name="sparkle" size={18} />
                      <span>Intelligent AI Model Router</span>
                    </div>
                    <div className="settings-card-desc">
                      Choose the live routing stack for merchant queries. Model providers are configured on the server.
                    </div>
                  </div>
                </div>

                <form onSubmit={handleSaveRouter} style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
                  <div className="setting-row">
                    <div>
                      <div className="setting-row-label">Router Orchestration Policy</div>
                      <div className="setting-row-desc">Legacy answers directly, Shadow compares both stacks, and New enables the AI router with legacy fallback.</div>
                    </div>
                    <select
                      aria-label="Router orchestration policy"
                      value={routerMode}
                      disabled={!routerLoaded || routerBusy}
                      onChange={e => setRouterMode(e.target.value)}
                      style={{
                        padding: '6px 12px',
                        borderRadius: 'var(--radius-md, 8px)',
                        border: '1px solid var(--border)',
                        background: 'var(--bg-2)',
                        color: 'var(--text-primary)',
                        fontSize: 13
                      }}
                    >
                      {!routerLoaded && <option value="">Router configuration unavailable</option>}
                      <option value="legacy">Legacy routing</option>
                      <option value="shadow">Shadow comparison</option>
                      <option value="new">New AI router</option>
                    </select>
                  </div>

                  {routerMsg && (
                    <div style={{
                      padding: '8px 12px',
                      borderRadius: 'var(--radius-md, 8px)',
                      fontSize: 13,
                      background: routerMsg.ok ? 'var(--success-dim)' : 'var(--danger-dim)',
                      color: routerMsg.ok ? 'var(--success)' : 'var(--danger)',
                      border: `1px solid ${routerMsg.ok ? 'rgba(31,107,58,0.2)' : 'rgba(155,28,28,0.2)'}`
                    }}>
                      {routerMsg.text}
                    </div>
                  )}

                  <div style={{ display: 'flex', justifyContent: 'flex-end', paddingTop: 8 }}>
                    <button
                      type="submit"
                      disabled={routerBusy || !routerLoaded}
                      className="btn-primary"
                      style={{ padding: '8px 18px', fontSize: 13, display: 'inline-flex', alignItems: 'center', gap: 6 }}
                    >
                      <Icon name="check" size={14} />
                      <span>{routerBusy ? 'Saving...' : 'Save Router Configuration'}</span>
                    </button>
                  </div>
                </form>
              </div>
            </div>
          )}

          {/* TAB 4: RATE LIMITS & QUOTAS */}
          {activeTab === 'limits' && (
            <div className="settings-card">
              <div className="settings-card-header">
                <div>
                  <div className="settings-card-title"><Icon name="chart" size={18} /> API Throttle & Token Budgets</div>
                  <div className="settings-card-desc">Limits are configured per business so each tenant has its own query and token budget.</div>
                </div>
              </div>
              <p style={{ color: 'var(--text-secondary)', fontSize: 13, lineHeight: 1.6 }}>Open a business and choose Limits to edit its requests per minute, daily requests, token budget and complex-query allowance.</p>
              <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', marginTop: 16 }}>
                <Link className="btn-primary" to="/admin/businesses">Manage business limits</Link>
                <Link className="btn-flush" to="/admin/usage">View current usage</Link>
              </div>
            </div>
          )}
          {/* TAB 5: SYSTEM & DOCTOR */}
          {activeTab === 'system' && (
            <div>
              <div className="settings-card">
                <div className="settings-card-header">
                  <div>
                    <div className="settings-card-title">
                      <Icon name="server" size={18} />
                      <span>Database & Cache Diagnostic Doctor</span>
                    </div>
                    <div className="settings-card-desc">
                      Perform maintenance, flush volatile in-memory responses, and inspect vector store.
                    </div>
                  </div>
                </div>

                <div className="setting-row">
                  <div>
                    <div className="setting-row-label">Active Database Connection</div>
                    <div className="setting-row-desc">{dbHealth ? `Server database: ${dbHealth.db_type || 'unknown'}. This connectivity check does not verify schema integrity.` : 'Checking the active server database connection.'}</div>
                  </div>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                    <span style={{
                      display: 'inline-flex',
                      alignItems: 'center',
                      gap: 6,
                      fontSize: 12,
                      fontWeight: 600,
                      color: dbHealth && !dbError && (dbHealth.db_type === 'sqlite' ? dbHealth.sqlite : dbHealth.postgres) === 'connected' ? 'var(--success)' : 'var(--text-muted)'
                    }}>
                      <span style={{ width: 8, height: 8, borderRadius: '50%', background: 'currentColor' }} />
                      {dbError || (dbHealth ? (dbHealth.db_type === 'sqlite' ? dbHealth.sqlite : dbHealth.postgres) || 'Unknown' : 'Checking…')}
                    </span>
                  </div>
                </div>

                <div className="setting-row">
                  <div>
                    <div className="setting-row-label">In-Memory Cache & Prompt Contexts</div>
                    <div className="setting-row-desc">
                      {cacheStats ? `${cacheStats.context_cache?.length || 0} merchant contexts · ${(cacheStats.query_cache || []).reduce((sum, item) => sum + (item.query_count || 0), 0)} cached query responses` : 'Cache statistics are unavailable.'}
                    </div>
                  </div>
                  <button
                    type="button"
                    onClick={handleFlushAllCache}
                    disabled={systemBusy}
                    className="btn-flush"
                    style={{ padding: '6px 14px', fontSize: 12.5, borderRadius: 'var(--radius-md, 8px)', gap: 6 }}
                  >
                    <Icon name="trash" size={14} />
                    <span>Flush All Cache</span>
                  </button>
                </div>

                <div className="setting-row">
                  <div>
                    <div className="setting-row-label">ChromaDB Vector Embeddings Store</div>
                    <div className="setting-row-desc">Semantic vector database index for AI merchant queries.</div>
                  </div>
                  <button
                    type="button"
                    onClick={handleResetChroma}
                    disabled={systemBusy}
                    className="btn-flush"
                    style={{ padding: '6px 14px', fontSize: 12.5, borderRadius: 'var(--radius-md, 8px)', gap: 6 }}
                  >
                    <Icon name="refresh" size={14} />
                    <span>Reset Vectors</span>
                  </button>
                </div>
              </div>

              <div className="settings-card">
                <div className="settings-card-header">
                  <div>
                    <div className="settings-card-title">
                      <Icon name="sliders" size={18} />
                      <span>API Gateway Endpoints</span>
                    </div>
                    <div className="settings-card-desc">
                      Active backend services routing topology.
                    </div>
                  </div>
                </div>

                <div style={{ display: 'flex', flexDirection: 'column', gap: 8, fontSize: 13, fontFamily: 'var(--font-mono)' }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', padding: '6px 0', borderBottom: '1px solid var(--border)' }}>
                    <span style={{ color: 'var(--text-muted)' }}>API_BASE:</span>
                    <span style={{ fontWeight: 600 }}>{API_BASE}</span>
                  </div>
                  <div style={{ display: 'flex', justifyContent: 'space-between', padding: '6px 0', borderBottom: '1px solid var(--border)' }}>
                    <span style={{ color: 'var(--text-muted)' }}>Admin Prefix:</span>
                    <span style={{ fontWeight: 600 }}>{API_BASE}/admin</span>
                  </div>
                  <div style={{ display: 'flex', justifyContent: 'space-between', padding: '6px 0' }}>
                    <span style={{ color: 'var(--text-muted)' }}>Telemetry API:</span>
                    <span style={{ fontWeight: 600 }}>{API_BASE}/admin/telemetry</span>
                  </div>
                </div>
              </div>
            </div>
          )}

          {/* TAB 6: MERCHANT SUPPORT LOGS */}
          {activeTab === 'feedback' && (
            <div>
              <div className="settings-card">
                <div className="settings-card-header">
                  <div>
                    <div className="settings-card-title">
                      <Icon name="chat" size={18} />
                      <span>Merchant Feedback & Support Tickets</span>
                    </div>
                    <div className="settings-card-desc">
                      Issues and diagnostic reports submitted directly by store owners from the billing interface.
                    </div>
                  </div>
                </div>

                {feedbackError && <p role="alert" style={{ color: 'var(--danger)' }}>{feedbackError}</p>}
                {feedbackLoading ? (
                  <div style={{ padding: 24, textAlign: 'center', color: 'var(--text-muted)', fontSize: 13 }}>
                    Loading support tickets...
                  </div>
                ) : !feedbackError && feedbackLogs.length === 0 ? (
                  <div style={{
                    padding: '32px 16px',
                    textAlign: 'center',
                    background: 'var(--bg-3)',
                    borderRadius: 'var(--radius-md, 8px)',
                    color: 'var(--text-muted)',
                    fontSize: 13
                  }}>
                    No merchant support tickets currently on file.
                  </div>
                ) : (
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
                    {feedbackLogs.map((log, idx) => (
                      <div
                        key={log.id || idx}
                        style={{
                          padding: 14,
                          borderRadius: 'var(--radius-md, 8px)',
                          border: '1px solid var(--border)',
                          background: 'var(--bg-1)',
                          display: 'flex',
                          flexDirection: 'column',
                          gap: 6
                        }}
                      >
                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                          <span style={{ fontWeight: 700, fontSize: 13, color: 'var(--text-primary)' }}>
                            {log.business_name || log.username || (log.business_id ? `Business #${log.business_id}` : 'Store Merchant')}
                          </span>
                          <span style={{ fontSize: 11, color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>
                            {formatAdminTime(log.created_at, timeFormat)}
                          </span>
                        </div>
                        <div style={{ fontSize: 13, color: 'var(--text-secondary)', lineHeight: 1.5 }}>
                          {log.message || log.comment || 'Diagnostics log submitted.'}
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
