/**
 * components/chat/MessageFeedback.jsx
 * ===================================
 * Thumbs up/down on an assistant answer. A thumbs-down asks "what did you want?"
 * and the chosen intent is sent as a correction — so re-running the SAME query
 * returns the right answer next time (server-side QueryOverride).
 */
import { useState } from 'react'
import { useAuth } from '../../contexts/AuthContext'
import { API_BASE } from '../../config'

// Cache the intents list across all bubbles (one fetch per session).
let _intentsCache = null

export default function MessageFeedback({ query, source, modelTier, sessionId }) {
  const { authFetch } = useAuth()
  const [verdict, setVerdict]       = useState(null)   // null | 'up' | 'down'
  const [showPicker, setShowPicker] = useState(false)
  const [intents, setIntents]       = useState(_intentsCache || [])
  const [doneMsg, setDoneMsg]       = useState(null)

  if (!query || source === 'error') return null

  async function post(v, correction) {
    try {
      const res = await authFetch(`${API_BASE}/feedback`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          query, verdict: v, correction: correction || null,
          session_id: sessionId, route: modelTier, handler_key: source,
        }),
      })
      if (res.ok) {
        const d = await res.json().catch(() => ({}))
        return d
      }
    } catch {}
    return {}
  }

  async function onUp() {
    setVerdict('up'); setShowPicker(false)
    await post('up')
    setDoneMsg('Thanks!')
  }

  async function onDown() {
    setVerdict('down')
    if (!_intentsCache) {
      try {
        const res = await authFetch(`${API_BASE}/feedback/intents`)
        if (res.ok) { const d = await res.json(); _intentsCache = d.intents || [] }
      } catch {}
    }
    setIntents(_intentsCache || [])
    setShowPicker(true)
  }

  async function pick(key) {
    setShowPicker(false)
    const d = await post('down', key)
    setDoneMsg(d.override ? "Got it — I'll answer that the right way next time." : 'Thanks for the feedback.')
  }

  if (doneMsg) {
    return <div style={{ fontSize: 12, opacity: 0.6, marginTop: 4 }}>{doneMsg}</div>
  }

  const btn = {
    background: 'transparent', border: 'none', cursor: 'pointer',
    fontSize: 14, opacity: 0.55, padding: '2px 4px', lineHeight: 1,
    color: 'inherit',
  }
  const btnActive = { ...btn, opacity: 1 }

  return (
    <div style={{ marginTop: 4 }}>
      <div style={{ display: 'flex', gap: 2, alignItems: 'center' }}>
        <span style={{ fontSize: 11, opacity: 0.4, marginRight: 2 }}>Helpful?</span>
        <button style={verdict === 'up' ? btnActive : btn} onClick={onUp} title="Good answer">👍</button>
        <button style={verdict === 'down' ? btnActive : btn} onClick={onDown} title="Wrong answer">👎</button>
      </div>

      {showPicker && (
        <div style={{
          marginTop: 6, padding: 8, borderRadius: 8,
          border: '1px solid rgba(127,127,127,0.25)', maxWidth: 320,
        }}>
          <div style={{ fontSize: 12, opacity: 0.7, marginBottom: 6 }}>What did you want?</div>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
            {intents.map(it => (
              <button
                key={it.key}
                onClick={() => pick(it.key)}
                style={{
                  fontSize: 12, padding: '4px 10px', borderRadius: 999,
                  border: '1px solid rgba(127,127,127,0.3)', background: 'transparent',
                  cursor: 'pointer', color: 'inherit',
                }}
              >
                {it.label}
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
