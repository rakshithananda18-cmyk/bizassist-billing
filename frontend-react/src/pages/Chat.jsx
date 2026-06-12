import { useState, useEffect, useRef, useCallback } from 'react'
import { useAuth } from '../contexts/AuthContext'
import { useDialog } from '../contexts/DialogContext'
import { API_BASE } from '../config'
import ActionConfirm from '../components/ActionConfirm'
import MessageBubble from '../components/chat/MessageBubble'
import TypingIndicator from '../components/chat/TypingIndicator'
import ChatInput from '../components/chat/ChatInput'
import { renderMarkdown } from '../utils/markdown'
import { fetchSessions } from '../utils/sessionsCache'
import { Icon } from '../components/icons'

// ── Inline SVG helper for CHIPS ──────────────────────────────────────────────
const svgIcon = (children) => (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round">{children}</svg>
)

const CHIPS = [
  { icon: svgIcon(<><path d="M12 2a7 7 0 0 0-4 12.7V17h8v-2.3A7 7 0 0 0 12 2Z" /><line x1="9" y1="21" x2="15" y2="21" /></>), label: 'Smart Insights', smartInsights: true },
  { icon: svgIcon(<><path d="M21 12V7H5a2 2 0 0 1 0-4h14v4" /><path d="M3 5v14a2 2 0 0 0 2 2h16v-5" /><path d="M18 12a2 2 0 0 0 0 4h4v-4Z" /></>), label: 'Top debtors', query: 'Show my top debtors by overdue amount', intent: 'top_debtors' },
  { icon: svgIcon(<><circle cx="12" cy="12" r="9" /><polyline points="12 7 12 12 15 14" /></>), label: 'Expiring soon', query: 'What stock is expiring soon?', intent: 'expiring_soon' },
  { icon: svgIcon(<><line x1="6" y1="20" x2="6" y2="14" /><line x1="12" y1="20" x2="12" y2="10" /><line x1="18" y1="20" x2="18" y2="4" /></>), label: 'Revenue summary', query: 'Show me the total revenue and pending payments summary', intent: 'revenue_summary' },
  { icon: svgIcon(<><path d="M21 8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16Z" /><path d="m3.3 7 8.7 5 8.7-5" /><path d="M12 22V12" /></>), label: 'Low stock', query: 'Which products are low on stock?', intent: 'low_stock' },
  { icon: svgIcon(<><circle cx="12" cy="12" r="9" /><line x1="12" y1="8" x2="12" y2="12" /><line x1="12" y1="16" x2="12.01" y2="16" /></>), label: 'Overdue invoices', query: 'List all overdue invoices with amounts', intent: 'overdue_list' },
  { icon: svgIcon(<><path d="M8 21h8" /><path d="M12 17v4" /><path d="M7 4h10v5a5 5 0 0 1-10 0V4Z" /><path d="M17 5h3v2a3 3 0 0 1-3 3" /><path d="M7 5H4v2a3 3 0 0 0 3 3" /></>), label: 'Top customers', query: 'Who are my top 5 customers by revenue?', intent: 'top_customers' },
]

export default function Chat({ isFullWidth = true, mobileOpen = false, onCloseMobile = () => {} }) {
  const { user, authFetch } = useAuth()
  const { showAlert, showConfirm, showError } = useDialog()

  // ── State ─────────────────────────────────────────────────────────────────
  const [sessions, setSessions]           = useState([])
  const [activeId, setActiveId]           = useState(() => localStorage.getItem('active_session_id') || null)
  const [messages, setMessages]           = useState([])
  const [input, setInput]                 = useState('')
  const [loading, setLoading]             = useState(false)
  const [rateLimited, setRateLimited]     = useState(false)
  const [rlTimer, setRlTimer]             = useState(0)
  const [showHistoryPopup, setShowHistoryPopup] = useState(false)
  const [uploading, setUploading]         = useState(false)
  const [uploadedQuery, setUploadedQuery] = useState(null)
  const [chipsExpanded, setChipsExpanded] = useState(false)
  const [menuOpenId, setMenuOpenId]       = useState(null)
  const [menuPos, setMenuPos]             = useState({ top: 0, left: 0 })
  const [renamingId, setRenamingId]       = useState(null)
  const [renameValue, setRenameValue]     = useState('')
  const [suggestions, setSuggestions]     = useState([])
  const [actionPreview, setActionPreview] = useState(null)
  const [actionBusy, setActionBusy]       = useState(false)

  const [bizName, setBizName]             = useState(() => localStorage.getItem('biz_name') || user?.business_name || 'My Business')
  const [isRenamingBanner, setIsRenamingBanner] = useState(false)
  const [tempBannerBiz, setTempBannerBiz] = useState(bizName)
  const [bizDate] = useState(() =>
    new Date().toLocaleDateString('en-US', { weekday: 'long', year: 'numeric', month: 'long', day: 'numeric' })
  )

  // ── Refs ──────────────────────────────────────────────────────────────────
  const chatRef            = useRef(null)
  const inputRef           = useRef(null)
  const rlInterval         = useRef(null)
  const activeBotMessageRef = useRef(null)
  const typingTimeoutRef   = useRef(null)
  const justCreatedRef     = useRef(null)   // session_id we created locally; skip its history re-fetch

  // ── Helpers ───────────────────────────────────────────────────────────────
  const scrollToBottom = useCallback((behavior = 'smooth') => {
    chatRef.current?.scrollTo({ top: chatRef.current.scrollHeight, behavior })
  }, [])

  function triggerRateLimit(seconds = 60) {
    setRateLimited(true)
    setRlTimer(seconds)
    if (rlInterval.current) clearInterval(rlInterval.current)
    rlInterval.current = setInterval(() => {
      setRlTimer(t => {
        if (t <= 1) { clearInterval(rlInterval.current); setRateLimited(false); return 0 }
        return t - 1
      })
    }, 1000)
  }

  // ── Session management ────────────────────────────────────────────────────
  const loadSessions = useCallback(async () => {
    try {
      // force=true: Chat owns session mutations, so it must never be handed a
      // stale pre-mutation list (the New Chat / delete sidebar bug).
      const data = await fetchSessions(authFetch, true)
      if (data) setSessions(data)
    } catch {}
  }, [authFetch])

  const selectSession = useCallback(async (id) => {
    if (typingTimeoutRef.current) clearTimeout(typingTimeoutRef.current)
    setActiveId(id)
    localStorage.setItem('active_session_id', id || '')
    window.dispatchEvent(new CustomEvent('ai-active-changed', { detail: { session_id: id } }))
    if (!id) { setMessages([]); return }
    try {
      const res = await authFetch(`${API_BASE}/chat/history?session_id=${id}`)
      if (res.ok) {
        const data = await res.json()
        setMessages(data.map(m => ({ role: m.role, content: m.content, source: m.source, model_tier: m.model_tier, cached: m.cached })))
      }
    } catch {}
  }, [authFetch])

  const startNewChat = useCallback(() => {
    if (typingTimeoutRef.current) clearTimeout(typingTimeoutRef.current)
    setActiveId(null)
    setMessages([])
    localStorage.removeItem('active_session_id')
    window.dispatchEvent(new CustomEvent('ai-active-changed', { detail: { session_id: null } }))
    loadSessions()
  }, [loadSessions])

  const deleteSession = useCallback(async (e, id) => {
    if (e) e.stopPropagation()
    if (!(await showConfirm('Delete this conversation?'))) return
    try {
      const res = await authFetch(`${API_BASE}/chat/history?session_id=${id}`, { method: 'DELETE' })
      if (res.ok) {
        activeId === id ? startNewChat() : loadSessions()
        window.dispatchEvent(new CustomEvent('ai-sessions-updated'))
      }
    } catch {}
  }, [authFetch, activeId, startNewChat, loadSessions, showConfirm])

  const renameSession = useCallback(async (id, title) => {
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
        loadSessions()
        window.dispatchEvent(new CustomEvent('ai-sessions-updated'))
      }
    } catch {}
  }, [authFetch, loadSessions])

  // ── Banner rename ─────────────────────────────────────────────────────────
  function commitBannerRename() {
    const val = tempBannerBiz.trim() || 'My Business'
    setBizName(val)
    localStorage.setItem('biz_name', val)
    setIsRenamingBanner(false)
    window.dispatchEvent(new CustomEvent('biz-name-updated', { detail: val }))
  }

  // ── Send message ──────────────────────────────────────────────────────────
  const sendMessage = useCallback(async (text) => {
    const msg = (text || input).trim()
    if (!msg || loading || rateLimited) return
    if (typingTimeoutRef.current) clearTimeout(typingTimeoutRef.current)
    setInput('')
    if (inputRef.current) inputRef.current.style.height = 'auto'
    setUploadedQuery(null)
    setMessages(prev => [...prev, { role: 'user', content: msg }])
    setLoading(true)

    // ── SSE streaming via /ask/stream ────────────────────────────
    try {
      const res = await authFetch(`${API_BASE}/ask/stream`, {
        method:  'POST',
        headers: { 'Content-Type': 'application/json' },
        body:    JSON.stringify({ message: msg, session_id: activeId }),
      })

      if (!res.ok || !res.body) {
        // Fallback: server returned an error before streaming started
        const err = await res.json().catch(() => ({ error: `HTTP ${res.status}` }))
        setLoading(false)
        setMessages(prev => [...prev, {
          role: 'assistant',
          content: `❌ ${err.error || 'Request failed'}`,
          source: 'error',
        }])
        return
      }

      // Add a placeholder message that will be filled as tokens arrive
      setMessages(prev => [...prev, {
        role: 'assistant', content: '', source: null,
        model_tier: null, cached: false, chart: null, alerts: [],
        _streamStatus: null,
      }])
      setLoading(false)

      const reader  = res.body.getReader()
      const decoder = new TextDecoder()
      let buffer    = ''

      const updateLast = (updater) =>
        setMessages(prev => {
          const msgs = [...prev]
          const i    = msgs.length - 1
          if (i >= 0 && msgs[i].role === 'assistant') msgs[i] = updater(msgs[i])
          return msgs
        })

      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })

        // Process complete SSE events (separated by \n\n)
        const parts = buffer.split('\n\n')
        buffer = parts.pop()

        for (const part of parts) {
          const trimmed = part.trim()
          if (!trimmed || !trimmed.startsWith('data: ')) continue
          let evt
          try { evt = JSON.parse(trimmed.slice(6)) } catch { continue }

          switch (evt.type) {
            case 'status':
              updateLast(m => ({ ...m, _streamStatus: evt.content }))
              break

            case 'token':
              updateLast(m => ({ ...m, content: m.content + evt.content, _streamStatus: null }))
              chatRef.current?.scrollTo({ top: chatRef.current.scrollHeight, behavior: 'auto' })
              break

            case 'replace':
              updateLast(m => ({ ...m, content: evt.content, _streamStatus: null }))
              setTimeout(() => scrollToBottom('smooth'), 50)
              break

            case 'done': {
              if (evt.session_id && evt.session_id !== activeId) {
                // We already hold this turn's messages locally (just streamed) —
                // mark the session so the activeId effect doesn't re-fetch history
                // and overwrite them (which would drop chart/alerts and flicker).
                justCreatedRef.current = evt.session_id
                setActiveId(evt.session_id)
                localStorage.setItem('active_session_id', evt.session_id)
                loadSessions()
                window.dispatchEvent(new CustomEvent('ai-sessions-updated'))
                window.dispatchEvent(new CustomEvent('ai-active-changed', { detail: { session_id: evt.session_id } }))
              }
              const sugg = Array.isArray(evt.suggestions) ? evt.suggestions : []
              setSuggestions(sugg)
              if (sugg.length > 0) setChipsExpanded(true)
              updateLast(m => ({
                ...m,
                source:     evt.source,
                model_tier: evt.meta?.model_tier,
                cached:     !!(evt.meta?.cached),
                chart:      evt.chart || null,
                alerts:     Array.isArray(evt.alerts) ? evt.alerts : [],
                insight:    evt.insight || null,
                _streamStatus: null,
              }))
              setTimeout(() => scrollToBottom('smooth'), 50)
              break
            }

            case 'error':
              if (evt.status_code === 429) triggerRateLimit(60)
              updateLast(m => ({ ...m, content: `❌ ${evt.message}`, source: 'error', _streamStatus: null }))
              break
          }
        }
      }
    } catch (err) {
      setLoading(false)
      setMessages(prev => [...prev, {
        role: 'assistant',
        content: `❌ Failed to connect. Is the backend running?\n\n${err.message}`,
        source: 'error',
      }])
    }
  }, [input, activeId, loading, rateLimited, authFetch, loadSessions])

  // ── Smart Insights advisor (on-demand) ────────────────────────────────────
  const runSmartInsights = useCallback(async () => {
    if (loading) return
    setChipsExpanded(false)
    setMessages(prev => [...prev, { role: 'user', content: 'Smart Insights — grow my business' }])
    setLoading(true)
    try {
      const res = await authFetch(`${API_BASE}/smart-insights`)
      const data = res.ok ? await res.json() : {}
      const ins = data.insights || []
      let md
      if (data.source === 'empty' || ins.length === 0) {
        md = data.message || 'Not enough data yet for tailored insights — upload invoices and inventory first.'
      } else {
        const icon = { collections: '💰', customers: '🤝', products: '📦', profit: '📈', risk: '⚠️' }
        md = '**🚀 Smart Insights — your top moves**\n\n' + ins.map((it, i) =>
          `**${i + 1}. ${it.title}** ${icon[it.dimension] || ''}\n\n` +
          `${it.insight}\n\n` +
          `➡️ **Do this:** ${it.action}\n\n` +
          `📊 **Impact:** ${it.impact}`
        ).join('\n\n---\n\n')
        if (data.source === 'deterministic') md += '\n\n_(Showing key figures; full AI analysis was unavailable.)_'
      }
      setMessages(prev => [...prev, {
        role: 'assistant', content: md, source: 'advisor',
        model_tier: 'ADVISOR', cached: false, chart: null, alerts: [],
      }])
    } catch (err) {
      setMessages(prev => [...prev, {
        role: 'assistant', content: '❌ Could not generate insights right now.', source: 'error',
      }])
    } finally {
      setLoading(false)
    }
  }, [authFetch, loading])

  // ── Intent / action handlers ──────────────────────────────────────────────
  const runIntent = useCallback(async (chip) => {
    if (chip?.smartInsights) { runSmartInsights(); return }
    if (!chip || !chip.intent) { sendMessage(chip?.query || chip?.label || ''); return }
    setLoading(true)
    setChipsExpanded(false)
    try {
      const res = await authFetch(`${API_BASE}/intent`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ intent: chip.intent, session_id: activeId, question: chip.label, params: chip.params }),
      })
      if (!res.ok) throw new Error('intent unavailable')
      const data = await res.json()
      if (data.session_id && data.session_id !== activeId) {
        setActiveId(data.session_id)
        localStorage.setItem('active_session_id', data.session_id)
        loadSessions()
        window.dispatchEvent(new CustomEvent('ai-sessions-updated'))
        window.dispatchEvent(new CustomEvent('ai-active-changed', { detail: { session_id: data.session_id } }))
      }
      setMessages(prev => [
        ...prev,
        { role: 'user',      content: chip.label },
        { role: 'assistant', content: data.answer?.markdown || '', source: data.source || 'db', alerts: Array.isArray(data.alerts) ? data.alerts : [] },
      ])
      const sugg = Array.isArray(data.suggestions) ? data.suggestions : []
      setSuggestions(sugg)
      setChipsExpanded(sugg.length > 0)
    } catch {
      sendMessage(chip.query || chip.label)
    } finally {
      setLoading(false)
    }
  }, [authFetch, sendMessage, activeId, loadSessions, runSmartInsights])

  const runAction = useCallback(async (actionKey, label, params) => {
    if (!actionKey) return
    setActionBusy(true)
    try {
      const res = await authFetch(`${API_BASE}/action/preview`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action: actionKey, params }),
      })
      if (!res.ok) throw new Error('preview unavailable')
      const preview = await res.json()
      setActionPreview({ ...preview, _action: actionKey, _label: label, _params: params })
    } catch {
      showAlert('Could not prepare that action. Please try again.')
    } finally {
      setActionBusy(false)
    }
  }, [authFetch, showAlert])

  const confirmAction = useCallback(async () => {
    const p = actionPreview
    if (!p) return
    setActionBusy(true)
    try {
      const res = await authFetch(`${API_BASE}/action/execute`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action: p._action, params: p._params, session_id: activeId, question: p._label || p.title }),
      })
      if (!res.ok) throw new Error('execute failed')
      const data = await res.json()
      if (data.session_id && data.session_id !== activeId) {
        setActiveId(data.session_id)
        localStorage.setItem('active_session_id', data.session_id)
        loadSessions()
        window.dispatchEvent(new CustomEvent('ai-sessions-updated'))
        window.dispatchEvent(new CustomEvent('ai-active-changed', { detail: { session_id: data.session_id } }))
      }
      setMessages(prev => [
        ...prev,
        { role: 'user',      content: p._label || p.title },
        { role: 'assistant', content: data.markdown || 'Done.', source: 'action' },
      ])
      setActionPreview(null)
    } catch {
      showAlert('The action could not be completed. Please try again.')
    } finally {
      setActionBusy(false)
    }
  }, [actionPreview, authFetch, activeId, loadSessions, showAlert])

  const handleSuggestion = useCallback((s) => {
    if (!s) return
    if (s.type === 'deterministic' && s.intent) runIntent({ label: s.label, intent: s.intent })
    else if (s.type === 'action' && s.action) runAction(s.action, s.label, s.params)
    else if (s.type === 'select') return
    else sendMessage(s.prompt || s.query || s.label)
  }, [runIntent, runAction, sendMessage])

  // ── File upload ───────────────────────────────────────────────────────────
  async function handleFileUpload(e) {
    const file = e.target.files[0]
    if (!file) return
    setUploading(true)
    const formData = new FormData()
    formData.append('file', file)
    try {
      const res  = await authFetch(`${API_BASE}/upload`, { method: 'POST', body: formData })
      const resp = await res.json()
      if (!res.ok || resp.error) {
        throw new Error(resp.error || resp.detail || resp.message || res.statusText || `Upload failed (${res.status})`)
      }
      await showAlert(`File type: ${resp.file_type}\nRows processed: ${resp.rows}`)
      window.dispatchEvent(new CustomEvent('data-updated'))
      const fileType  = (resp.file_type || '').toUpperCase()
      const queryType = fileType === 'PDF' ? 'document' : (fileType === 'CSV' || fileType === 'XLSX') ? 'dataset' : 'file'
      setUploadedQuery(`Analyze the uploaded ${queryType}?`)
      setChipsExpanded(true)
    } catch (err) {
      await showError(err, 'Upload failed')
    } finally {
      setUploading(false)
      e.target.value = ''
    }
  }

  // ── Input handlers ────────────────────────────────────────────────────────
  function handleInput(e) {
    setInput(e.target.value)
    e.target.style.height = 'auto'
    e.target.style.height = e.target.scrollHeight + 'px'
  }
  function handleKeyDown(e) {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage() }
  }

  // ── Effects ───────────────────────────────────────────────────────────────
  useEffect(() => {
    if (user?.business_name && !localStorage.getItem('biz_name')) {
      setBizName(user.business_name); setTempBannerBiz(user.business_name)
    }
  }, [user])

  useEffect(() => {
    const handler = (e) => { if (e.detail) { setBizName(e.detail); setTempBannerBiz(e.detail) } }
    window.addEventListener('biz-name-updated', handler)
    return () => window.removeEventListener('biz-name-updated', handler)
  }, [])

  useEffect(() => {
    function onSelect(e) { if (e.detail?.session_id !== undefined) selectSession(e.detail.session_id) }
    function onNew() { startNewChat() }
    window.addEventListener('ai-select-session', onSelect)
    window.addEventListener('ai-new-chat', onNew)
    return () => { window.removeEventListener('ai-select-session', onSelect); window.removeEventListener('ai-new-chat', onNew) }
  }, [selectSession, startNewChat])

  useEffect(() => () => { if (typingTimeoutRef.current) clearTimeout(typingTimeoutRef.current) }, [])

  useEffect(() => {
    function handleShortcut(e) {
      const d = e.detail || {}
      if (d.smartInsights) runSmartInsights()
      else if (d.action) runAction(d.action, d.label || d.query, d.params)
      else if (d.intent) runIntent({ intent: d.intent, label: d.label || d.query, query: d.query, params: d.params })
      else if (d.query) sendMessage(d.query)
    }
    window.addEventListener('ai-shortcut', handleShortcut)
    return () => window.removeEventListener('ai-shortcut', handleShortcut)
  }, [sendMessage, runIntent, runAction, runSmartInsights])

  useEffect(() => {
    if (messages.length > 0) return
    const t = setTimeout(() => {
      setSuggestions(prev => (prev?.length) ? prev : [
        { id: 'biz_summary', label: 'Business summary', type: 'ai', icon: 'chart',
          prompt: 'Give me a concise business summary: revenue, what is paid vs pending vs overdue, and anything that needs my attention today.' },
        { id: 'priorities', label: "Today's priorities", type: 'ai', icon: 'clock',
          prompt: 'What are the top 3 things I should act on today, with reasons?' },
      ])
      setChipsExpanded(true)
    }, 10000)
    return () => clearTimeout(t)
  }, [messages.length])

  useEffect(() => {
    window.addEventListener('ai-sessions-updated', loadSessions)
    return () => window.removeEventListener('ai-sessions-updated', loadSessions)
  }, [loadSessions])

  useEffect(() => {
    function handleClickOutside(e) {
      if (showHistoryPopup && !e.target.closest('.chat-history-popup') && !e.target.closest('.history-btn')) {
        setShowHistoryPopup(false)
      }
      if (menuOpenId && !e.target.closest('.rp-chat-kebab-wrap')) setMenuOpenId(null)
      if (!e.target.closest('.chat-chips-bar') && !e.target.closest('.chips-toggle-btn')) setChipsExpanded(false)
    }
    document.addEventListener('mousedown', handleClickOutside)
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [showHistoryPopup, menuOpenId])

  useEffect(() => {
    if (activeId) {
      if (justCreatedRef.current === activeId) {
        // Session we just created via send — messages are already in state.
        justCreatedRef.current = null
      } else {
        selectSession(activeId)
      }
    } else {
      setMessages([])
    }
    loadSessions()
  }, [activeId, loadSessions, selectSession])

  useEffect(() => {
    scrollToBottom('smooth')
    const timers = [50, 100, 150, 200, 250, 300].map(d => setTimeout(() => scrollToBottom('smooth'), d))
    return () => timers.forEach(clearTimeout)
  }, [messages, loading, chipsExpanded, suggestions, scrollToBottom])

  useEffect(() => {
    const active = messages.length > 0 || input.trim().length > 0
    document.documentElement.classList.toggle('chat-active', active)
    return () => document.documentElement.classList.remove('chat-active')
  }, [messages.length, input])

  // ── Derived ───────────────────────────────────────────────────────────────
  const hour     = new Date().getHours()
  const greeting = hour < 12 ? 'Good morning' : hour < 17 ? 'Good afternoon' : 'Good evening'

  // ── Render ────────────────────────────────────────────────────────────────
  return (
    <div id="assistant-panel" className={`assistant-panel ${mobileOpen ? 'mobile-open' : ''}`}>
      {actionPreview && (
        <ActionConfirm
          preview={actionPreview}
          busy={actionBusy}
          onConfirm={confirmAction}
          onClose={() => setActionPreview(null)}
        />
      )}

      <div className="assistant-mobile-header">
        <span className="amh-title">AI Assistant</span>
        <button className="amh-close-btn" onClick={onCloseMobile} title="Close Assistant">×</button>
      </div>

      <div className="assistant-header" id="assistant-header">
        <div className="ah-biz-info" id="ah-biz-info">
          {isRenamingBanner ? (
            <input
              value={tempBannerBiz}
              onChange={e => setTempBannerBiz(e.target.value)}
              onBlur={commitBannerRename}
              onKeyDown={e => {
                if (e.key === 'Enter') commitBannerRename()
                if (e.key === 'Escape') { setTempBannerBiz(bizName); setIsRenamingBanner(false) }
              }}
              autoFocus
              onClick={e => e.stopPropagation()}
              style={{
                fontFamily: 'inherit', fontSize: 'inherit', fontWeight: 'inherit',
                letterSpacing: 'inherit', color: 'var(--accent-color)', background: 'transparent',
                border: 'none', borderBottom: '2.5px solid var(--accent-color)',
                outline: 'none', textAlign: 'center', width: `${Math.max(tempBannerBiz.length * 16, 150)}px`,
                padding: 0, maxWidth: '600px',
              }}
            />
          ) : (
            <div className="ah-biz-name" id="ai-biz-banner-name" onClick={() => setIsRenamingBanner(true)} title="Click to rename">
              {bizName}
            </div>
          )}
          <div className="ah-biz-date" id="ai-biz-banner-date">{bizDate}</div>
        </div>
      </div>

      <div className="chat-main-area">
        <div className="chat-box" id="chat-box" ref={chatRef}>
          {messages.length === 0 && !loading && !activeId && (
            <div className="chat-empty-state" id="chat-empty-state">
              <div className="ces-glow"></div>
              <div className="ces-symbol">✦</div>
              <div className="ces-greeting">{greeting}</div>
              <div className="ces-sub">
                Ask anything about your business —<br />
                revenue, stock, payments, customers.
              </div>
              <div className="ces-chips" id="prompt-chips">
                {CHIPS.map(c => (
                  <button key={c.label} className="chip" onClick={() => runIntent(c)}>
                    {c.icon} {c.label}
                  </button>
                ))}
              </div>
            </div>
          )}

          {messages.map((msg, i) => {
            // The query that produced an assistant answer = the nearest preceding
            // user message (needed so feedback can report what was wrong).
            let priorQuery = null
            if (msg.role === 'assistant') {
              for (let j = i - 1; j >= 0; j--) {
                if (messages[j].role === 'user') { priorQuery = messages[j].content; break }
              }
            }
            return (
              <MessageBubble
                key={i}
                msg={msg}
                query={priorQuery}
                sessionId={activeId}
                innerRef={i === messages.length - 1 && msg.role === 'assistant' ? activeBotMessageRef : null}
              />
            )
          })}

          {loading && <TypingIndicator />}
        </div>

        <div className="chat-scroll-fade"></div>

        <ChatInput
          input={input}
          loading={loading}
          rateLimited={rateLimited}
          rlTimer={rlTimer}
          uploading={uploading}
          uploadedQuery={uploadedQuery}
          chipsExpanded={chipsExpanded}
          suggestions={suggestions}
          showHistoryPopup={showHistoryPopup}
          sessions={sessions}
          activeId={activeId}
          renamingId={renamingId}
          renameValue={renameValue}
          menuOpenId={menuOpenId}
          menuPos={menuPos}
          inputRef={inputRef}
          CHIPS={CHIPS}
          onInput={handleInput}
          onKeyDown={handleKeyDown}
          onSendMessage={sendMessage}
          onFileUpload={handleFileUpload}
          onToggleChips={setChipsExpanded}
          onRunIntent={runIntent}
          onHandleSuggestion={handleSuggestion}
          onRunAction={runAction}
          onSendUploadedQuery={() => { sendMessage(uploadedQuery.replace(/\?$/, '')); setUploadedQuery(null); setChipsExpanded(false) }}
          onToggleHistory={setShowHistoryPopup}
          onSelectSession={selectSession}
          onStartNewChat={startNewChat}
          onDeleteSession={deleteSession}
          onRenameSession={renameSession}
          onRenameStart={(id, title) => { setRenameValue(title); setRenamingId(id) }}
          onRenameValueChange={setRenameValue}
          onRenameCancel={() => setRenamingId(null)}
          onMenuOpen={(id, pos) => { setMenuOpenId(id); setMenuPos(pos) }}
          onMenuClose={() => setMenuOpenId(null)}
          onShowAlert={showAlert}
        />
      </div>
    </div>
  )
}
