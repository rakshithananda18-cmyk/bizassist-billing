/**
 * components/chat/ChatHistory.jsx
 * =================================
 * Popup panel showing session list with rename/delete actions.
 * Anchors above the input area.
 */

export default function ChatHistory({
  sessions,
  activeId,
  renamingId,
  renameValue,
  menuOpenId,
  menuPos,
  onSelectSession,
  onStartNewChat,
  onDeleteSession,
  onRenameSession,
  onRenameStart,
  onRenameValueChange,
  onRenameCancel,
  onMenuOpen,
  onMenuClose,
  onClose,
}) {
  return (
    <div id="chat-history-popup" className="chat-history-popup">
      <div className="popup-header">
        <span className="popup-title">Conversations</span>
        <button className="popup-close-btn" onClick={onClose} title="Close">×</button>
      </div>
      <button className="new-chat-btn" onClick={() => { onStartNewChat(); onClose() }}>
        <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
          <line x1="12" y1="5" x2="12" y2="19"></line>
          <line x1="5" y1="12" x2="19" y2="12"></line>
        </svg>
        New Chat
      </button>
      <div className="chat-sessions-list" id="chat-sessions-list">
        {sessions.length === 0 ? (
          <div style={{ padding: 12, textAlign: 'center', fontSize: 12, color: 'var(--secondary-text)' }}>
            No chats yet
          </div>
        ) : (
          sessions.map(s => (
            <div
              key={s.session_id}
              className={`rp-chat-item ${s.session_id === activeId ? 'active' : ''}`}
              onClick={() => {
                if (renamingId === s.session_id) return
                onSelectSession(s.session_id)
                onClose()
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
                    onClick={e => e.stopPropagation()}
                    onChange={e => onRenameValueChange(e.target.value)}
                    onBlur={() => onRenameSession(s.session_id, renameValue)}
                    onKeyDown={e => {
                      if (e.key === 'Enter') onRenameSession(s.session_id, renameValue)
                      if (e.key === 'Escape') onRenameCancel()
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
                  onClick={e => {
                    e.stopPropagation()
                    if (menuOpenId === s.session_id) { onMenuClose(); return }
                    const r = e.currentTarget.getBoundingClientRect()
                    onMenuOpen(s.session_id, { top: r.bottom + 4, left: Math.max(8, r.right - 140) })
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
                    onClick={e => e.stopPropagation()}
                  >
                    <button
                      className="rp-chat-menu-item"
                      onClick={() => {
                        onRenameStart(s.session_id, s.session_title || '')
                        onMenuClose()
                      }}
                    >
                      ✏ Rename
                    </button>
                    <button
                      className="rp-chat-menu-item danger"
                      onClick={e => {
                        onMenuClose()
                        onDeleteSession(e, s.session_id)
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
  )
}
