/**
 * components/chat/MessageFeedback.jsx
 * ===================================
 * Thumbs up/down on an assistant answer. A thumbs-down asks "what did you want?"
 * and the chosen intent is sent as a correction — so re-running the SAME query
 * returns the right answer next time (server-side QueryOverride).
 */
import { useState, useRef, useEffect } from 'react'
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
  const rootRef = useRef(null)
  const downRef = useRef(null)
  const [pickerPos, setPickerPos] = useState(null)

  // Keep the picker positioned while open; close only on outside-click / Escape.
  useEffect(() => {
    if (!showPicker) return
    const place = () => {
      const r = downRef.current?.getBoundingClientRect()
      if (!r) return
      const PW = 300, PH = 240, GAP = 6, PAD = 10
      const left = Math.min(Math.max(r.left, PAD), window.innerWidth - PW - PAD)
      const spaceBelow = window.innerHeight - r.bottom
      const top = spaceBelow >= PH + GAP ? r.bottom + GAP : Math.max(PAD, r.top - PH - GAP)
      setPickerPos({ top, left })
    }
    place()
    const onDocClick = (e) => { if (rootRef.current && !rootRef.current.contains(e.target)) setShowPicker(false) }
    const onKey = (e) => { if (e.key === 'Escape') setShowPicker(false) }
    document.addEventListener('mousedown', onDocClick)
    document.addEventListener('keydown', onKey)
    window.addEventListener('scroll', place, true)
    window.addEventListener('resize', place)
    return () => {
      document.removeEventListener('mousedown', onDocClick)
      document.removeEventListener('keydown', onKey)
      window.removeEventListener('scroll', place, true)
      window.removeEventListener('resize', place)
    }
  }, [showPicker])

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
    // Clicking the thumb again (while the picker is open) closes it.
    if (showPicker) { setShowPicker(false); return }
    const r = downRef.current?.getBoundingClientRect()
    if (r) {
      const PW = 300, PH = 240, GAP = 6, PAD = 10
      const left = Math.min(Math.max(r.left, PAD), window.innerWidth - PW - PAD)
      const spaceBelow = window.innerHeight - r.bottom
      const top = spaceBelow >= PH + GAP ? r.bottom + GAP : Math.max(PAD, r.top - PH - GAP)
      setPickerPos({ top, left })
    }
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
    opacity: 0.5, padding: '2px 4px', lineHeight: 0,
    color: 'inherit', display: 'inline-flex',
  }
  const btnActive = { ...btn, opacity: 1, color: 'var(--accent-color)' }

  const ThumbUp = () => (
    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor"
         strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M7 10v12" />
      <path d="M15 5.88 14 10h5.83a2 2 0 0 1 1.92 2.56l-2.33 8A2 2 0 0 1 17.5 22H4a2 2 0 0 1-2-2v-8a2 2 0 0 1 2-2h2.76a2 2 0 0 0 1.79-1.11L12 2a3.13 3.13 0 0 1 3 3.88Z" />
    </svg>
  )
  const ThumbDown = () => (
    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor"
         strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M17 14V2" />
      <path d="M9 18.12 10 14H4.17a2 2 0 0 1-1.92-2.56l2.33-8A2 2 0 0 1 6.5 2H20a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2h-2.76a2 2 0 0 0-1.79 1.11L12 22a3.13 3.13 0 0 1-3-3.88Z" />
    </svg>
  )

  return (
    <div style={{ marginTop: 0 }} ref={rootRef}>
      <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
        <button style={verdict === 'up' ? btnActive : btn} onClick={onUp} title="Good answer" aria-label="Good answer"><ThumbUp /></button>
        <button ref={downRef} style={verdict === 'down' ? btnActive : btn} onClick={onDown} title="Wrong answer" aria-label="Wrong answer"><ThumbDown /></button>
      </div>

      {showPicker && pickerPos && (
        <div className="bz-popover" onClick={e => e.stopPropagation()}
          style={{ position: 'fixed', top: pickerPos.top, left: pickerPos.left, width: 300, maxHeight: 240, overflowY: 'auto', zIndex: 1000 }}>
          <div style={{ fontSize: 12, opacity: 0.7, marginBottom: 8 }}>What did you want?</div>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
            {intents.map(it => (
              <button
                key={it.key}
                onClick={() => pick(it.key)}
                style={{
                  fontSize: 12, padding: '4px 10px', borderRadius: 999,
                  border: '1px solid var(--border-color)', background: 'transparent',
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
