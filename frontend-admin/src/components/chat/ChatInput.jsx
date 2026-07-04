/**
 * components/chat/ChatInput.jsx
 * ===============================
 * Input area: textarea, chips bar, file upload, send/mic buttons,
 * and the history popup trigger.
 */
import { Spinner } from '../ui'
import { Icon } from '../icons'
import SelectChip from './SelectChip'
import ChatHistory from './ChatHistory'

export default function ChatInput({
  // input state
  input,
  loading,
  rateLimited,
  rlTimer,
  uploading,
  uploadedQuery,
  chipsExpanded,
  suggestions,
  // history popup state
  showHistoryPopup,
  sessions,
  activeId,
  renamingId,
  renameValue,
  menuOpenId,
  menuPos,
  // refs
  inputRef,
  // static data
  CHIPS,
  // callbacks — input
  onInput,
  onKeyDown,
  onSendMessage,
  onFileUpload,
  onToggleChips,
  // callbacks — chip actions
  onRunIntent,
  onHandleSuggestion,
  onRunAction,
  onSendUploadedQuery,
  // callbacks — history popup
  onToggleHistory,
  onSelectSession,
  onStartNewChat,
  onDeleteSession,
  onRenameSession,
  onRenameStart,
  onRenameValueChange,
  onRenameCancel,
  onMenuOpen,
  onMenuClose,
  onShowAlert,
}) {
  const hasConversation = loading || (suggestions && suggestions.length > 0) || uploadedQuery

  return (
    <div className="input-area-wrapper">
      {/* Quick-action chips bar */}
      <div className={`chat-chips-bar ${chipsExpanded && !showHistoryPopup ? 'show' : ''}`}>
        {uploadedQuery ? (
          <div style={{ display: 'flex', width: '100%', justifyContent: 'center', padding: '6px 0' }}>
            <button
              className="chip chip-sm"
              onClick={onSendUploadedQuery}
              style={{
                color: 'var(--accent-color)',
                fontWeight: 600,
                border: '1.5px solid var(--accent-color)',
                background: 'var(--accent-soft)',
                borderRadius: '999px',
                padding: '6px 14px',
                cursor: 'pointer',
                display: 'inline-flex',
                alignItems: 'center',
                justifyContent: 'center',
                boxShadow: 'var(--shadow-sm)',
              }}
            >
              <span className="chip-icon" style={{ lineHeight: 0, display: 'inline-flex' }}><Icon name="sparkle" size={13} /></span>
              <span className="chip-label" style={{ opacity: 1, maxWidth: 'none', marginLeft: '6px', display: 'inline-block', fontWeight: 600 }}>
                {uploadedQuery}
              </span>
            </button>
          </div>
        ) : (
          (suggestions && suggestions.length > 0 ? suggestions : CHIPS).map(item => (
            item.type === 'select' ? (
              <SelectChip
                key={item.id || item.label}
                chip={item}
                onConfirm={(actionKey, label, params) => {
                  onToggleChips(false)
                  onRunAction(actionKey, label, params)
                }}
              />
            ) : (
              <button
                key={item.id || item.label}
                className="chip chip-sm"
                title={item.label}
                onClick={() => {
                  item.type ? onHandleSuggestion(item) : onRunIntent(item)
                  onToggleChips(false)
                }}
              >
                <span className="chip-icon">
                  {typeof item.icon === 'string' ? <Icon name={item.icon} /> : item.icon}
                </span>
                <span className="chip-label">{item.label}</span>
              </button>
            )
          ))
        )}
      </div>

      <div className={`input-area ${input.trim() ? 'has-content' : ''}`}>
        {/* Chevron toggle for chips bar */}
        {(hasConversation || uploadedQuery) && (
          <button
            type="button"
            className={`chips-toggle-btn ${chipsExpanded ? 'open' : ''}`}
            title={chipsExpanded ? 'Hide quick actions' : 'Show quick actions'}
            onClick={() => onToggleChips(!chipsExpanded)}
          >
            <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round">
              <polyline points="18 15 12 9 6 15"></polyline>
            </svg>
          </button>
        )}

        {/* History popup */}
        {showHistoryPopup && (
          <ChatHistory
            sessions={sessions}
            activeId={activeId}
            renamingId={renamingId}
            renameValue={renameValue}
            menuOpenId={menuOpenId}
            menuPos={menuPos}
            onSelectSession={onSelectSession}
            onStartNewChat={onStartNewChat}
            onDeleteSession={onDeleteSession}
            onRenameSession={onRenameSession}
            onRenameStart={onRenameStart}
            onRenameValueChange={onRenameValueChange}
            onRenameCancel={onRenameCancel}
            onMenuOpen={onMenuOpen}
            onMenuClose={onMenuClose}
            onClose={() => onToggleHistory(false)}
          />
        )}

        <div className="input-text-row">
          <textarea
            ref={inputRef}
            id="user-input"
            rows={1}
            value={input}
            onChange={onInput}
            onKeyDown={onKeyDown}
            placeholder={rateLimited ? `⏳ Rate limited — retry in ${rlTimer}s` : 'Write a message . . . '}
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
              {uploading ? (
                <Spinner />
              ) : (
                <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path>
                  <polyline points="17 8 12 3 7 8"></polyline>
                  <line x1="12" y1="3" x2="12" y2="15"></line>
                </svg>
              )}
            </button>
            <button
              className="control-btn history-btn"
              onClick={() => onToggleHistory(!showHistoryPopup)}
              title="View Chat History"
            >
              <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8"></path>
                <polyline points="3 3 3 8 8 8"></polyline>
                <line x1="12" y1="7" x2="12" y2="12"></line>
                <line x1="12" y1="12" x2="16" y2="14"></line>
              </svg>
            </button>
            <input type="file" id="file-upload-chat" accept=".csv,.xlsx,.pdf" onChange={onFileUpload} hidden />
          </div>
          <div className="controls-right">
            <button
              className="control-btn mic-btn"
              title="Voice Input (Future feature)"
              onClick={() => onShowAlert?.('Voice input feature coming soon!')}
            >
              <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M12 2a3 3 0 0 0-3 3v7a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3Z"></path>
                <path d="M19 10v2a7 7 0 0 1-14 0v-2"></path>
                <line x1="12" y1="19" x2="12" y2="22"></line>
              </svg>
            </button>
            <button
              className="control-btn send-btn"
              onClick={() => onSendMessage()}
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
  )
}
