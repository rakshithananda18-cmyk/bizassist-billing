// TODO: Port chat from frontend/js/chat.js
// Features to build:
//   - Session list sidebar (load/switch/delete sessions)
//   - Message bubbles (user + bot)
//   - Typing indicator
//   - Markdown renderer
//   - Prompt chips (quick-start queries)
//   - Model tier badge on responses (DIRECT / AI_SIMPLE / AI_COMPLEX)
//   - Rate limit error handling (429)

export default function Chat() {
  return (
    <div className="page">
      <div className="page-header">
        <h1>AI Assistant</h1>
        <p>Chat interface — coming soon</p>
      </div>
      <div className="placeholder-card" style={{ height: 400, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
        💬 Chat UI
      </div>
    </div>
  )
}
