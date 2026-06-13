import { useState, useEffect } from 'react'
import { useAuth } from '../contexts/AuthContext'
import { API_BASE } from '../config'
import { fetchSessions } from '../utils/sessionsCache'
import { Icon } from './icons'
import { useDialog } from '../contexts/DialogContext'

// Donut Arc Helper
function DonutChart({ paid, pending, overdue, healthPct }) {
  const total = paid + pending + overdue || 1
  const r = 36, cx = 44, cy = 44, stroke = 10
  const circ = 2 * Math.PI * r

  const paidPct = paid / total
  const pendPct = pending / total

  const paidDash = paidPct * circ
  const pendDash = pendPct * circ
  const overDash = Math.max(0, 1 - paidPct - pendPct) * circ
  const pendOffset = -(paidPct * circ)
  const overOffset = -((paidPct + pendPct) * circ)

  return (
    <svg width="68" height="68" viewBox="0 0 88 88" style={{ transform: 'rotate(-90deg)', flexShrink: 0 }}>
      <circle cx="44" cy="44" r={r} fill="none" stroke="var(--border-color)" strokeWidth="10" />
      <circle cx="44" cy="44" r={r} fill="none" stroke="#3a9a5c" strokeWidth="10"
        strokeDasharray={`${paidDash} ${circ}`} strokeDashoffset="0" />
      <circle cx="44" cy="44" r={r} fill="none" stroke="#c97c22" strokeWidth="10"
        strokeDasharray={`${pendDash} ${circ}`} strokeDashoffset={pendOffset} />
      <circle cx="44" cy="44" r={r} fill="none" stroke="#c94242" strokeWidth="10"
        strokeDasharray={`${overDash} ${circ}`} strokeDashoffset={overOffset} />
    </svg>
  )
}

// InsightsPanel — renders its own header (with collapse/close from props) + content
export default function InsightsPanel({ onCollapse, onCloseMobile }) {
  const { authFetch } = useAuth()
  const { showConfirm } = useDialog()
  const [sessions, setSessions] = useState([])
  const [summary, setSummary] = useState(null)
  const [customers, setCustomers] = useState([])
  const [panelInsights, setPanelInsights] = useState(null)
  const [collapsedSections, setCollapsedSections] = useState(() => ({
    progress: localStorage.getItem('rp_section_progress') === 'collapsed',
    alerts: localStorage.getItem('rp_section_alerts') === 'collapsed',
    context: localStorage.getItem('rp_section_context') === 'collapsed'
  }))
  const [activeSessionId, setActiveSessionId] = useState(() => localStorage.getItem('active_session_id') || null)
  const [menuOpenId, setMenuOpenId] = useState(null)   // session id whose kebab menu is open
  const [menuPos, setMenuPos] = useState({ top: 0, left: 0 })  // fixed-position coords for the menu
  const [renamingId, setRenamingId] = useState(null)   // session id being renamed inline
  const [renameValue, setRenameValue] = useState('')

  useEffect(() => {
    loadInsightsData()

    function handleActiveSync() {
      setActiveSessionId(localStorage.getItem('active_session_id') || null)
    }
    // Highlight follows the active session chosen from the chat popup
    function handleActiveChanged(e) {
      setActiveSessionId(e?.detail?.session_id ?? null)
    }
    window.addEventListener('ai-select-session', handleActiveSync)
    window.addEventListener('ai-new-chat', handleActiveSync)
    window.addEventListener('ai-active-changed', handleActiveChanged)
    // Refresh the chat history list when a session is added/renamed/deleted elsewhere
    window.addEventListener('ai-sessions-updated', loadInsightsData)
    return () => {
      window.removeEventListener('ai-select-session', handleActiveSync)
      window.removeEventListener('ai-new-chat', handleActiveSync)
      window.removeEventListener('ai-active-changed', handleActiveChanged)
      window.removeEventListener('ai-sessions-updated', loadInsightsData)
    }
  }, [])

  // Close the kebab menu when clicking outside
  useEffect(() => {
    function handleClickOutside(e) {
      if (menuOpenId && !e.target.closest('.rp-chat-kebab-wrap')) {
        setMenuOpenId(null)
      }
    }
    document.addEventListener('mousedown', handleClickOutside)
    return () => {
      document.removeEventListener('mousedown', handleClickOutside)
    }
  }, [menuOpenId])

  async function loadInsightsData() {
    try {
      const [sessionsData, summaryRes, customersRes, insightsRes] = await Promise.all([
        fetchSessions(authFetch),   // shared/de-duped request
        authFetch(`${API_BASE}/dashboard-summary`),
        authFetch(`${API_BASE}/top-customers`),
        authFetch(`${API_BASE}/smart-insights/summary`),   // free, deterministic
      ])
      if (sessionsData) setSessions(sessionsData)
      if (summaryRes.ok) setSummary(await summaryRes.json())
      if (customersRes.ok) setCustomers(await customersRes.json())
      if (insightsRes.ok) setPanelInsights(await insightsRes.json())
    } catch (err) {
      console.error('Failed to load insights data:', err)
    }
  }

  function toggleSection(name) {
    setCollapsedSections(prev => {
      const nextVal = !prev[name]
      try {
        localStorage.setItem(`rp_section_${name}`, nextVal ? 'collapsed' : 'open')
      } catch (e) {
        console.error(e)
      }
      return { ...prev, [name]: nextVal }
    })
  }

  async function handleDeleteSession(e, id) {
    if (e) e.stopPropagation()
    const confirmed = await showConfirm('Delete this conversation?')
    if (!confirmed) return
    try {
      const res = await authFetch(`${API_BASE}/chat/history?session_id=${id}`, {
        method: 'DELETE'
      })
      if (res.ok) {
        if (activeSessionId === id) {
          localStorage.removeItem('active_session_id')
          window.dispatchEvent(new CustomEvent('ai-new-chat'))
          setActiveSessionId(null)
        }
        loadInsightsData()
        window.dispatchEvent(new CustomEvent('ai-sessions-updated'))
      }
    } catch (err) {
      console.error('Failed to delete chat session:', err)
    }
  }

  async function renameSession(id, title) {
    const newTitle = (title || '').trim()
    setRenamingId(null)
    if (!newTitle) return
    try {
      const res = await authFetch(`${API_BASE}/chat/session/title`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ session_id: id, title: newTitle }),
      })
      if (res.ok) {
        loadInsightsData()
        window.dispatchEvent(new CustomEvent('ai-sessions-updated'))
      }
    } catch (err) {
      console.error('Failed to rename chat session:', err)
    }
  }

  function handleSessionSelect(id) {
    localStorage.setItem('active_session_id', id || '')
    window.dispatchEvent(new CustomEvent('ai-select-session', { detail: { session_id: id } }))
    setActiveSessionId(id)
  }

  function handleNewChat() {
    window.dispatchEvent(new CustomEvent('ai-new-chat'))
    setActiveSessionId(null)
  }

  // intent set -> deterministic /intent (0 AI tokens); else natural-language AI query
  function sendChip(query, intent, smartInsights = false) {
    if (smartInsights) {
      window.dispatchEvent(new CustomEvent('ai-shortcut', { detail: { smartInsights: true } }))
      return
    }
    sessionStorage.setItem('prefill_query', query)
    window.dispatchEvent(new CustomEvent('ai-shortcut', { detail: { query, intent, label: query } }))
  }

  const total = summary?.invoice_count || 0
  const pending = summary?.pending_invoices || 0
  const revenue = summary?.total_revenue || 0
  const overdueAmt = summary?.overdue_amount || 0

  const overdueCount = overdueAmt > 0 && revenue > 0 ? Math.round((overdueAmt / revenue) * total) : 0
  const paidCount = Math.max(0, total - pending - overdueCount)

  const collectedAmt = revenue - overdueAmt
  const healthPct = revenue > 0 ? Math.round((collectedAmt / revenue) * 100) : 0
  const overPctBar = Math.min(100, (overdueAmt / Math.max(revenue, 1)) * 100)
  const maxCust = customers[0]?.total || 1

  return (
    <>
      {/* Single shared header — collapse/close buttons passed from AppLayout */}
      <div className="sidebar-header rp-header">
        <span className="sidebar-brand-text rp-brand-text">Progress</span>
        <div className="rp-topbar-right">
          <span className="rp-nav-label" id="rp-nav-label">
            {sessions.length} chat{sessions.length !== 1 ? 's' : ''}
          </span>
          {onCollapse && (
            <button
              className="sidebar-toggle-btn rp-collapse-btn matte-glass"
              onClick={() => {
                if (window.matchMedia('(max-width: 1024px)').matches) {
                  onCloseMobile?.();
                } else {
                  onCollapse();
                }
              }}
              title="Toggle Insights"
            >
              <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <rect x="3" y="3" width="18" height="18" rx="2" ry="2"></rect>
                <line x1="15" y1="3" x2="15" y2="21"></line>
              </svg>
            </button>
          )}
        </div>
      </div>

      <div className="sidebar-sep rp-sep"></div>

      <div className="rp-content" id="insights-content" style={{ flex: 1, overflowY: 'auto' }}>

        {/* Section 1: Chat History */}
        <div className={`rp-section ${collapsedSections.progress ? 'collapsed' : ''}`} id="rp-section-progress">
          <div className="rp-section-header" onClick={() => toggleSection('progress')}>
            <svg className="rp-folder-icon" xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"></path>
            </svg>
            <span className="rp-section-title">Chat History</span>
            <svg className="rp-section-arrow" xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
              <polyline points="6 9 12 15 18 9"></polyline>
            </svg>
          </div>
          <div className="rp-section-body" id="rp-progress-body">
            <button className="rp-new-chat-btn" onClick={handleNewChat}>
              + New Chat
            </button>
            <div id="rp-chat-sessions-list">
              {sessions.length === 0 ? (
                <div className="rp-empty">No conversations yet</div>
              ) : (
                sessions.map(s => (
                  <div
                    key={s.session_id}
                    className={`rp-chat-item ${s.session_id === activeSessionId ? 'active' : ''}`}
                    onClick={() => {
                      if (renamingId === s.session_id) return
                      handleSessionSelect(s.session_id)
                    }}
                  >
                    <div className="rp-chat-title-wrapper">
                      <svg className="rp-chat-icon" xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                        <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"></path>
                      </svg>
                      {renamingId === s.session_id ? (
                        <input
                          className="rp-chat-rename-input"
                          value={renameValue}
                          autoFocus
                          onClick={(e) => e.stopPropagation()}
                          onChange={(e) => setRenameValue(e.target.value)}
                          onBlur={() => renameSession(s.session_id, renameValue)}
                          onKeyDown={(e) => {
                            if (e.key === 'Enter') renameSession(s.session_id, renameValue)
                            if (e.key === 'Escape') setRenamingId(null)
                          }}
                        />
                      ) : (
                        <span className="rp-chat-title" title={s.session_title || 'Untitled'}>
                          {s.session_title || 'Untitled'}
                        </span>
                      )}
                    </div>
                    <div className="rp-chat-kebab-wrap">
                      <button
                        className="rp-chat-kebab"
                        title="Options"
                        onClick={(e) => {
                          e.stopPropagation()
                          if (menuOpenId === s.session_id) { setMenuOpenId(null); return }
                          const r = e.currentTarget.getBoundingClientRect()
                          setMenuPos({ top: r.bottom + 4, left: Math.max(8, r.right - 140) })
                          setMenuOpenId(s.session_id)
                        }}
                      >
                        <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="currentColor">
                          <circle cx="12" cy="5" r="1.6"></circle>
                          <circle cx="12" cy="12" r="1.6"></circle>
                          <circle cx="12" cy="19" r="1.6"></circle>
                        </svg>
                      </button>
                      {menuOpenId === s.session_id && (
                        <div
                          className="rp-chat-menu"
                          style={{ position: 'fixed', top: menuPos.top, left: menuPos.left, right: 'auto', width: 160 }}
                          onClick={(e) => e.stopPropagation()}
                        >
                          <button
                            className="rp-chat-menu-item"
                            onClick={() => {
                              setRenameValue(s.session_title || '')
                              setRenamingId(s.session_id)
                              setMenuOpenId(null)
                            }}
                          >
                            <Icon name="edit" size={14} /> Rename
                          </button>
                          <button
                            className="rp-chat-menu-item danger"
                            onClick={(e) => {
                              setMenuOpenId(null)
                              handleDeleteSession(e, s.session_id)
                            }}
                          >
                            <Icon name="trash" size={14} /> Delete
                          </button>
                        </div>
                      )}
                    </div>
                  </div>
                ))
              )}
            </div>
          </div>
        </div>

        {/* Section 1.5: Alerts Section (Collapsible container) */}
        <div className={`rp-section ${collapsedSections.alerts ? 'collapsed' : ''}`} id="rp-section-alerts">
          <div className="rp-section-header" onClick={() => toggleSection('alerts')}>
            <svg className="rp-folder-icon" xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"></path>
            </svg>
            <span className="rp-section-title">Alerts</span>
            <svg className="rp-section-arrow" xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
              <polyline points="6 9 12 15 18 9"></polyline>
            </svg>
          </div>
          <div className="rp-section-body" id="rp-alerts-body">
            <div className="ip-alert-row ip-alert-warn" onClick={() => sendChip('Which medicines and products are expiring in the next 30 days?', 'expiring_soon')}>
              <div className="ip-alert-icon"><Icon name="clock" /></div>
              <div className="ip-alert-text"><strong>Expiry check</strong><span>See items expiring soon</span></div>
              <div className="ip-alert-arrow">›</div>
            </div>
            <div className="ip-alert-row ip-alert-info" onClick={() => sendChip('Which products have low stock and need reordering?', 'low_stock')}>
              <div className="ip-alert-icon"><Icon name="package" /></div>
              <div className="ip-alert-text"><strong>Low stock</strong><span>Items needing reorder</span></div>
              <div className="ip-alert-arrow">›</div>
            </div>
            <div className="ip-alert-row ip-alert-red" onClick={() => sendChip('List all overdue invoices with amounts and due dates', 'overdue_list')}>
              <div className="ip-alert-icon"><Icon name="alert" /></div>
              <div className="ip-alert-text"><strong>Overdue invoices</strong><span>₹{Number(overdueAmt).toLocaleString('en-IN')} pending</span></div>
              <div className="ip-alert-arrow">›</div>
            </div>
            <div className="ip-alert-row ip-alert-green" onClick={() => sendChip('Who are my top 5 customers by revenue this period?', 'top_customers')}>
              <div className="ip-alert-icon"><Icon name="trophy" /></div>
              <div className="ip-alert-text">
                <strong>Top customers</strong>
                <span>{customers[0] ? `${customers[0].customer} leads` : 'See rankings'}</span>
              </div>
              <div className="ip-alert-arrow">›</div>
            </div>
          </div>
        </div>

        {/* Section 2: Business Insights */}
        <div className={`rp-section ${collapsedSections.context ? 'collapsed' : ''}`} id="rp-section-context">
          <div className="rp-section-header" onClick={() => toggleSection('context')}>
            <svg className="rp-folder-icon" xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"></path>
            </svg>
            <span className="rp-section-title">Business Insights</span>
            <svg className="rp-section-arrow" xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
              <polyline points="6 9 12 15 18 9"></polyline>
            </svg>
          </div>
          <div className="rp-section-body" id="rp-context-body">
            {!panelInsights && (
              <div style={{ fontSize: 12, opacity: 0.6, padding: '8px 2px' }}>Reading your business…</div>
            )}
            {panelInsights && !panelInsights.has_data && (
              <div style={{ fontSize: 12, opacity: 0.7, padding: '8px 2px' }}>
                Upload invoices and inventory to see what's working and what to fix.
              </div>
            )}
            {panelInsights && panelInsights.has_data && (
              <>
                {/* What's working */}
                <div className="ip-insight-group">
                  <div className="ip-insight-head" style={{ color: '#3a9a5c', display: 'flex', alignItems: 'center', gap: 6 }}>
                    <Icon name="check" size={14} /> What's working
                  </div>
                  {(panelInsights.positives || []).length === 0 && (
                    <div style={{ fontSize: 12, opacity: 0.55, padding: '2px 0 8px' }}>—</div>
                  )}
                  {(panelInsights.positives || []).map((it, i) => (
                    <div key={i} className="ip-card" style={{ borderLeft: '3px solid #3a9a5c', marginBottom: 8 }}>
                      <div style={{ fontWeight: 600, fontSize: 13 }}>{it.title}</div>
                      <div style={{ fontSize: 12, opacity: 0.85, marginTop: 2 }}>{it.detail}</div>
                    </div>
                  ))}
                </div>

                {/* Could be better */}
                <div className="ip-insight-group" style={{ marginTop: 10 }}>
                  <div className="ip-insight-head" style={{ color: '#c97c22', display: 'flex', alignItems: 'center', gap: 6 }}>
                    <Icon name="warn" size={14} /> Could be better
                  </div>
                  {(panelInsights.improvements || []).length === 0 && (
                    <div style={{ fontSize: 12, opacity: 0.55, padding: '2px 0 8px' }}>Nothing urgent — nicely done.</div>
                  )}
                  {(panelInsights.improvements || []).map((it, i) => (
                    <div key={i} className="ip-card" style={{ borderLeft: '3px solid #c97c22', marginBottom: 8 }}>
                      <div style={{ fontWeight: 600, fontSize: 13 }}>{it.title}</div>
                      <div style={{ fontSize: 12, opacity: 0.85, marginTop: 2 }}>{it.detail}</div>
                      {it.action && (
                        <div style={{ fontSize: 12, marginTop: 4, opacity: 0.95 }}>→ {it.action}</div>
                      )}
                    </div>
                  ))}
                </div>

                <button
                  className="ip-card"
                  onClick={() => sendChip('Smart Insights — grow my business', null, true)}
                  style={{ width: '100%', textAlign: 'center', marginTop: 10, cursor: 'pointer',
                           border: '1px dashed var(--accent-color)', background: 'transparent',
                           color: 'var(--accent-color)', fontSize: 12, fontWeight: 600 }}
                >
                  <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6, justifyContent: 'center' }}><Icon name="rocket" size={14} /> Get full AI growth plan</span>
                </button>
              </>
            )}
          </div>
        </div>

      </div>
    </>
  )
}
