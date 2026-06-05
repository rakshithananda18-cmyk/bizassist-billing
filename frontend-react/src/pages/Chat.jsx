import { useState, useEffect, useRef, useCallback } from 'react'
import { useAuth } from '../contexts/AuthContext'
import { API_BASE } from '../config'

// Markdown renderer helper
function renderMarkdown(text) {
  const escape = s => s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')

  function inlineFmt(t) {
    return escape(t)
      .replace(/\*\*\*(.+?)\*\*\*/g, '<strong><em>$1</em></strong>')
      .replace(/\*\*(.+?)\*\*/g,     '<strong>$1</strong>')
      .replace(/__(.+?)__/g,         '<strong>$1</strong>')
      .replace(/\*(.+?)\*/g,         '<em>$1</em>')
      .replace(/_(.+?)_/g,           '<em>$1</em>')
      .replace(/`(.+?)`/g,           '<code class="md-inline-code">$1</code>')
      .replace(/(₹[\d,]+)/g,         '<span class="md-rupee">$1</span>')
  }

  const lines = text.split('\n')
  const output = []
  let inCode = false, inList = false, inOList = false

  const closeList = () => {
    if (inList)  { output.push('</ul>'); inList  = false }
    if (inOList) { output.push('</ol>'); inOList = false }
  }

  for (const line of lines) {
    if (line.trimStart().startsWith('```')) {
      closeList()
      if (!inCode) { output.push('<pre class="md-code-block"><code>'); inCode = true }
      else         { output.push('</code></pre>');              inCode = false }
      continue
    }
    if (inCode) { output.push(escape(line) + '\n'); continue }
    if (!line.trim()) { closeList(); output.push('<br>'); continue }

    const h3 = line.match(/^### (.+)/)
    const h2 = line.match(/^## (.+)/)
    const h1 = line.match(/^# (.+)/)
    if (h3) { closeList(); output.push(`<h3 class="md-h3">${inlineFmt(h3[1])}</h3>`); continue }
    if (h2) { closeList(); output.push(`<h2 class="md-h2">${inlineFmt(h2[1])}</h2>`); continue }
    if (h1) { closeList(); output.push(`<h1 class="md-h1">${inlineFmt(h1[1])}</h1>`); continue }

    if (/^[-*_]{3,}$/.test(line.trim())) { closeList(); output.push('<hr class="md-hr">'); continue }

    const bullet   = line.match(/^[\s]*[-*•]\s+(.+)/)
    const numbered = line.match(/^[\s]*(\d+)[.)]\s+(.+)/)

    if (bullet) {
      if (inOList) { output.push('</ol>'); inOList = false }
      if (!inList) { output.push("<ul class='md-ul'>"); inList = true }
      output.push(`<li>${inlineFmt(bullet[1])}</li>`)
      continue
    }
    if (numbered) {
      if (inList) { output.push('</ul>'); inList = false }
      if (!inOList) { output.push("<ol class='md-ol'>"); inOList = true }
      output.push(`<li>${inlineFmt(numbered[2])}</li>`)
      continue
    }

    closeList()
    output.push(`<p class="md-p">${inlineFmt(line)}</p>`)
  }
  closeList()
  if (inCode) output.push('</code></pre>')
  return output.join('')
}

function TierBadge({ source, modelTier, cached }) {
  if (source === 'db')   return <span className="tier-badge tier-direct">⚡ DIRECT</span>
  if (cached)            return <span className="tier-badge tier-cache">🔁 CACHED</span>
  if (modelTier === 'AI_COMPLEX') return <span className="tier-badge tier-complex">🧠 AI_COMPLEX</span>
  return <span className="tier-badge tier-simple">🤖 AI_SIMPLE</span>
}

function TypingIndicator() {
  return (
    <div className="message-row bot-row">
      <div className="loading-dots">
        <div className="typing">
          <span></span><span></span><span></span>
        </div>
      </div>
    </div>
  )
}

function MessageBubble({ msg }) {
  if (msg.role === 'user') {
    return (
      <div className="message-row user-row">
        <div className="message user">{msg.content}</div>
      </div>
    )
  }
  return (
    <div className="message-row bot-row">
      <div className="bot-message-wrap">
        <div className="bot-name-label">BizAssist</div>
        <div
          className="message bot"
          dangerouslySetInnerHTML={{ __html: renderMarkdown(msg.content) }}
        />
        {msg.source && (
          <TierBadge source={msg.source} modelTier={msg.model_tier} cached={msg.cached} />
        )}
      </div>
    </div>
  )
}

const CHIPS = [
  { icon: '💰', label: 'Who owes most?',      query: 'Who owes me the most?' },
  { icon: '⏰', label: 'Expiring soon',        query: 'Which medicines are expiring soon?' },
  { icon: '📊', label: 'Revenue summary',      query: 'Show me the total revenue and pending payments summary' },
  { icon: '📦', label: 'Low stock',            query: 'Which products are low on stock?' },
  { icon: '🔴', label: 'Overdue invoices',     query: 'List all overdue invoices with amounts' },
  { icon: '🏆', label: 'Top customers',        query: 'Who are my top 5 customers by revenue?' },
]

export default function Chat({ isFullWidth = true, mobileOpen = false, onCloseMobile = () => {} }) {
  const { user, authFetch } = useAuth()
  const [sessions, setSessions] = useState([])
  const [activeId, setActiveId] = useState(() => localStorage.getItem('active_session_id') || null)
  const [messages, setMessages] = useState([])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const [rateLimited, setRateLimited] = useState(false)
  const [rlTimer, setRlTimer] = useState(0)
  const [showHistoryPopup, setShowHistoryPopup] = useState(false)
  const [uploading, setUploading] = useState(false)
  const [menuOpenId, setMenuOpenId] = useState(null)   // session id whose kebab menu is open
  const [menuPos, setMenuPos] = useState({ top: 0, left: 0 })  // fixed-position coords for the menu
  const [renamingId, setRenamingId] = useState(null)   // session id being renamed inline
  const [renameValue, setRenameValue] = useState('')

  // Business renaming & banner config
  const [bizName, setBizName] = useState(() => localStorage.getItem('biz_name') || user?.business_name || 'My Business')
  const [isRenamingBanner, setIsRenamingBanner] = useState(false)
  const [tempBannerBiz, setTempBannerBiz] = useState(bizName)

  // Sync with user business name if loaded/updated
  useEffect(() => {
    if (user?.business_name && !localStorage.getItem('biz_name')) {
      setBizName(user.business_name)
      setTempBannerBiz(user.business_name)
    }
  }, [user])
  const [bizDate] = useState(() => {
    const options = { weekday: 'long', year: 'numeric', month: 'long', day: 'numeric' }
    return new Date().toLocaleDateString('en-US', options)
  })

  const chatRef = useRef(null)
  const inputRef = useRef(null)
  const rlInterval = useRef(null)

  // Sync biz_name dynamically when updated elsewhere
  useEffect(() => {
    const handleBizNameChange = (e) => {
      if (e.detail) {
        setBizName(e.detail)
        setTempBannerBiz(e.detail)
      }
    }
    window.addEventListener('biz-name-updated', handleBizNameChange)
    return () => window.removeEventListener('biz-name-updated', handleBizNameChange)
  }, [])

  function commitBannerRename() {
    const val = tempBannerBiz.trim() || 'My Business'
    setBizName(val)
    localStorage.setItem('biz_name', val)
    setIsRenamingBanner(false)
    window.dispatchEvent(new CustomEvent('biz-name-updated', { detail: val }))
  }

  // Load session list
  const loadSessions = useCallback(async () => {
    try {
      const res = await authFetch(`${API_BASE}/chat/sessions`)
      if (res.ok) {
        const data = await res.json()
        setSessions(data)
      }
    } catch {}
  }, [authFetch])

  // Select session
  const selectSession = useCallback(async (id) => {
    setActiveId(id)
    localStorage.setItem('active_session_id', id || '')
    // Notify the right-panel history so its highlight follows the popup selection
    window.dispatchEvent(new CustomEvent('ai-active-changed', { detail: { session_id: id } }))
    if (!id) {
      setMessages([])
      return
    }
    try {
      const res = await authFetch(`${API_BASE}/chat/history?session_id=${id}`)
      if (res.ok) {
        const data = await res.json()
        setMessages(data.map(m => ({ role: m.role, content: m.content, source: m.source, model_tier: m.model_tier, cached: m.cached })))
      }
    } catch {}
  }, [authFetch])

  // Start new chat
  const startNewChat = useCallback(() => {
    setActiveId(null)
    setMessages([])
    localStorage.removeItem('active_session_id')
    window.dispatchEvent(new CustomEvent('ai-active-changed', { detail: { session_id: null } }))
    loadSessions()
  }, [loadSessions])

  // Delete session
  const deleteSession = useCallback(async (e, id) => {
    if (e) e.stopPropagation()
    if (!window.confirm('Delete this conversation?')) return
    try {
      const res = await authFetch(`${API_BASE}/chat/history?session_id=${id}`, { method: 'DELETE' })
      if (res.ok) {
        if (activeId === id) {
          startNewChat()
        } else {
          loadSessions()
        }
        // Notify the right-panel history list to refresh too
        window.dispatchEvent(new CustomEvent('ai-sessions-updated'))
      }
    } catch {}
  }, [authFetch, activeId, startNewChat, loadSessions])

  // Rename session (persists via backend, then syncs both lists)
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

  // Trigger rate limit
  function triggerRateLimit(seconds = 60) {
    setRateLimited(true)
    setRlTimer(seconds)
    if (rlInterval.current) clearInterval(rlInterval.current)
    rlInterval.current = setInterval(() => {
      setRlTimer(t => {
        if (t <= 1) {
          clearInterval(rlInterval.current)
          setRateLimited(false)
          return 0
        }
        return t - 1
      })
    }, 1000)
  }

  // Send message
  const sendMessage = useCallback(async (text) => {
    const msg = (text || input).trim()
    if (!msg || loading || rateLimited) return

    setInput('')
    if (inputRef.current) inputRef.current.style.height = 'auto'

    setMessages(prev => [...prev, { role: 'user', content: msg }])
    setLoading(true)

    try {
      const res = await authFetch(`${API_BASE}/ask`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: msg, session_id: activeId }),
      })
      const data = await res.json()

      if (data.status_code === 429) {
        setLoading(false)
        setMessages(prev => [...prev, {
          role: 'assistant',
          content: `⚠️ **Rate limit hit.** ${data.error}\n\nRetry after: ${data.retry_after || '60 seconds'}`,
          source: 'error'
        }])
        triggerRateLimit(data.retry_after || 60)
        return
      }

      if (data.session_id && data.session_id !== activeId) {
        setActiveId(data.session_id)
        localStorage.setItem('active_session_id', data.session_id)
        loadSessions()
        window.dispatchEvent(new CustomEvent('ai-sessions-updated'))
        window.dispatchEvent(new CustomEvent('ai-active-changed', { detail: { session_id: data.session_id } }))
      }

      const fullText = data.response || ''
      const botMsg = {
        role: 'assistant',
        content: '',
        source: data.source,
        model_tier: data.model_tier,
        cached: !!data.cached
      }

      setMessages(prev => [...prev, botMsg])
      setLoading(false)

      let i = 0
      const delay = fullText.length > 500 ? 3 : 6
      function typeNext() {
        if (i < fullText.length) {
          i++
          setMessages(prev => {
            const updated = [...prev]
            if (updated.length > 0) {
              updated[updated.length - 1] = { ...botMsg, content: fullText.slice(0, i) }
            }
            return updated
          })
          setTimeout(typeNext, delay)
        }
      }
      typeNext()

    } catch (err) {
      setLoading(false)
      setMessages(prev => [...prev, {
        role: 'assistant',
        content: `❌ Failed to connect to AI. Is the backend running?\n\n${err.message}`,
        source: 'error'
      }])
    }
  }, [input, activeId, loading, rateLimited, authFetch, loadSessions])

  // Listen to session select/update events globally
  useEffect(() => {
    function handleSelectSession(e) {
      if (e.detail && e.detail.session_id !== undefined) {
        selectSession(e.detail.session_id)
      }
    }
    function handleStartNewChat() {
      startNewChat()
    }
    window.addEventListener('ai-select-session', handleSelectSession)
    window.addEventListener('ai-new-chat', handleStartNewChat)
    return () => {
      window.removeEventListener('ai-select-session', handleSelectSession)
      window.removeEventListener('ai-new-chat', handleStartNewChat)
    }
  }, [selectSession, startNewChat])

  // Listen to shortcuts globally
  useEffect(() => {
    function handleShortcut(e) {
      if (e.detail && e.detail.query) {
        sendMessage(e.detail.query)
      }
    }
    window.addEventListener('ai-shortcut', handleShortcut)
    return () => window.removeEventListener('ai-shortcut', handleShortcut)
  }, [sendMessage])

  // Keep this list in sync when sessions change elsewhere (right-panel history)
  useEffect(() => {
    window.addEventListener('ai-sessions-updated', loadSessions)
    return () => window.removeEventListener('ai-sessions-updated', loadSessions)
  }, [loadSessions])

  // Close the history popup / kebab menu when clicking outside
  useEffect(() => {
    function handleClickOutside(e) {
      if (
        showHistoryPopup &&
        !e.target.closest('.chat-history-popup') &&
        !e.target.closest('.history-btn')
      ) {
        setShowHistoryPopup(false)
      }
      if (menuOpenId && !e.target.closest('.rp-chat-kebab-wrap')) {
        setMenuOpenId(null)
      }
    }
    document.addEventListener('mousedown', handleClickOutside)
    return () => {
      document.removeEventListener('mousedown', handleClickOutside)
    }
  }, [showHistoryPopup, menuOpenId])

  // Load chat session on activeId change
  useEffect(() => {
    if (activeId) {
      selectSession(activeId)
    } else {
      setMessages([])
    }
    loadSessions()
  }, [activeId, loadSessions, selectSession])

  // Scroll messages
  useEffect(() => {
    chatRef.current?.scrollTo({ top: chatRef.current.scrollHeight, behavior: 'smooth' })
  }, [messages, loading])

  // Chat-active state effect
  useEffect(() => {
    const active = messages.length > 0 || input.trim().length > 0
    if (active) {
      document.documentElement.classList.add("chat-active")
    } else {
      document.documentElement.classList.remove("chat-active")
    }
    return () => {
      document.documentElement.classList.remove("chat-active")
    }
  }, [messages.length, input])

  // Auto resize textarea
  function handleInput(e) {
    setInput(e.target.value)
    e.target.style.height = 'auto'
    e.target.style.height = e.target.scrollHeight + 'px'
  }

  function handleKeyDown(e) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      sendMessage()
    }
  }

  // File upload in chat
  async function handleFileUpload(e) {
    const file = e.target.files[0]
    if (!file) return

    setUploading(true)
    const formData = new FormData()
    formData.append('file', file)

    try {
      const res = await authFetch(`${API_BASE}/upload`, {
        method: 'POST',
        body: formData,
      })
      const resp = await res.json()
      if (!res.ok || resp.error) {
        throw new Error(resp.error || 'Upload failed')
      }
      alert(`File type: ${resp.file_type}\nRows processed: ${resp.rows}`)
      // Dispatch refresh events
      window.dispatchEvent(new CustomEvent('data-updated'))
      sendMessage(`Analyze the uploaded invoice data and give me a summary`)
    } catch (err) {
      alert('Upload failed: ' + err.message)
    } finally {
      setUploading(false)
      e.target.value = ''
    }
  }

  const hour = new Date().getHours()
  const greeting = hour < 12 ? 'Good morning' : hour < 17 ? 'Good afternoon' : 'Good evening'

  return (
    <div id="assistant-panel" className={`assistant-panel ${mobileOpen ? 'mobile-open' : ''}`}>
      {/* Mobile-only header when opened as drawer/modal */}
      <div className="assistant-mobile-header">
        <span className="amh-title">AI Assistant</span>
        <button className="amh-close-btn" onClick={onCloseMobile} title="Close Assistant">×</button>
      </div>

      <div className="assistant-header" id="assistant-header">
        {/* Always show business name + date (banner style, as before) */}
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
                  padding: 0, maxWidth: '600px'
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

      {/* MAIN CHAT AREA */}
      <div className="chat-main-area">
        <div className="chat-box" id="chat-box" ref={chatRef}>
          {/* EMPTY STATE — replaced by messages on first send */}
          {messages.length === 0 && !loading && (
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
                  <button key={c.label} className="chip" onClick={() => sendMessage(c.query)}>
                    {c.icon} {c.label}
                  </button>
                ))}
              </div>
            </div>
          )}

          {/* MESSAGE BUBBLES */}
          {messages.map((msg, i) => (
            <MessageBubble key={i} msg={msg} />
          ))}

          {/* TYPING INDICATOR */}
          {loading && <TypingIndicator />}
        </div>

        {/* SCROLL FADE — messages dissolve into input */}
        <div className="chat-scroll-fade"></div>

        {/* INPUT */}
        <div className="input-area-wrapper">
          <div className={`input-area ${input.trim() ? 'has-content' : ''}`}>
            {/* CHAT HISTORY POPUP — anchored above input */}
            {showHistoryPopup && (
              <div id="chat-history-popup" className="chat-history-popup">
                <div className="popup-header">
                  <span className="popup-title">Conversations</span>
                  <button className="popup-close-btn" onClick={() => setShowHistoryPopup(false)} title="Close">×</button>
                </div>
                <button className="new-chat-btn" onClick={() => { startNewChat(); setShowHistoryPopup(false) }}>
                  <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                    <line x1="12" y1="5" x2="12" y2="19"></line>
                    <line x1="5" y1="12" x2="19" y2="12"></line>
                  </svg>
                  New Chat
                </button>
                <div className="chat-sessions-list" id="chat-sessions-list">
                  {sessions.length === 0 ? (
                    <div style={{ padding: 12, textAlign: 'center', fontSize: 12, color: 'var(--secondary-text)' }}>No chats yet</div>
                  ) : (
                    sessions.map(s => (
                      <div
                        key={s.session_id}
                        className={`rp-chat-item ${s.session_id === activeId ? 'active' : ''}`}
                        onClick={() => {
                          if (renamingId === s.session_id) return
                          selectSession(s.session_id)
                          setShowHistoryPopup(false)
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
                              style={{ position: 'fixed', top: menuPos.top, left: menuPos.left }}
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
                                ✏ Rename
                              </button>
                              <button
                                className="rp-chat-menu-item danger"
                                onClick={(e) => {
                                  setMenuOpenId(null)
                                  deleteSession(e, s.session_id)
                                }}
                              >
                                🗑 Delete
                              </button>
                            </div>
                          )}
                        </div>
                      </div>
                    ))
                  )}
                </div>
              </div>
            )}
            
            <div className="input-text-row">
              <textarea
                ref={inputRef}
                id="user-input"
                rows={1}
                value={input}
                onChange={handleInput}
                onKeyDown={handleKeyDown}
                placeholder={rateLimited ? `⏳ Rate limited — retry in ${rlTimer}s` : "Message BizAssist..."}
                disabled={rateLimited}
                style={{ resize: 'none' }}
              />
            </div>
            
            <div className="input-controls-row">
              <div className="controls-left">
                <button
                  className="control-btn upload-btn"
                  onClick={() => document.getElementById('file-upload-chat').click()}
                  title="Upload Invoice (PDF/CSV/XLSX)"
                  disabled={uploading}
                >
                  {uploading ? '...' : (
                    <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                      <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path>
                      <polyline points="17 8 12 3 7 8"></polyline>
                      <line x1="12" y1="3" x2="12" y2="15"></line>
                    </svg>
                  )}
                </button>
                <button
                  className="control-btn history-btn"
                  onClick={() => setShowHistoryPopup(!showHistoryPopup)}
                  title="View Chat History"
                >
                  <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8"></path>
                    <polyline points="3 3 3 8 8 8"></polyline>
                    <line x1="12" y1="7" x2="12" y2="12"></line>
                    <line x1="12" y1="12" x2="16" y2="14"></line>
                  </svg>
                </button>
                <input type="file" id="file-upload-chat" accept=".csv,.xlsx,.pdf" onChange={handleFileUpload} hidden />
              </div>
              <div className="controls-right">
                <button
                  className="control-btn mic-btn"
                  title="Voice Input (Future feature)"
                  onClick={() => alert("Voice input feature coming soon!")}
                >
                  <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <path d="M12 2a3 3 0 0 0-3 3v7a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3Z"></path>
                    <path d="M19 10v2a7 7 0 0 1-14 0v-2"></path>
                    <line x1="12" y1="19" x2="12" y2="22"></line>
                  </svg>
                </button>
                <button
                  className="control-btn send-btn"
                  onClick={() => sendMessage()}
                  disabled={!input.trim() || loading || rateLimited}
                  title="Send message"
                >
                  <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                    <line x1="12" y1="19" x2="12" y2="5"></line>
                    <polyline points="5 12 12 5 19 12"></polyline>
                  </svg>
                </button>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
