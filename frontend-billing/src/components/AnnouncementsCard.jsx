// ============================================================================
// AnnouncementsCard — in-app announcements + offer redemption (REVIEW_1 §4.3).
//
// Renders the live campaigns the backend says this business qualifies for
// (GET /announcements) as dismissible cards, plus a quiet "Have an offer
// code?" affordance. Owner-only by design: the backend already gates the
// endpoints with require_owner, and we don't even fetch for cashier logins.
//
// Fail-quiet philosophy: a promo must NEVER break or slow the app shell —
// every network error collapses to rendering nothing.
// ============================================================================
import React, { useState, useEffect, useCallback } from 'react'
import { api } from '../api/client'
import { useAuth } from '../contexts/AuthContext'
import { logger } from '../utils/logger'

// Minimal markdown: **bold**, *italic*, `code`, newlines. No HTML injection —
// everything is escaped first, then a few safe tags are substituted in.
function renderMiniMarkdown(md) {
  const escaped = String(md || '')
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
  const html = escaped
    .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
    .replace(/\*([^*]+)\*/g, '<em>$1</em>')
    .replace(/`([^`]+)`/g, '<code>$1</code>')
    .replace(/\n/g, '<br/>')
  return { __html: html }
}

export default function AnnouncementsCard() {
  const { user, token } = useAuth()
  const [items, setItems] = useState([])
  const [redeeming, setRedeeming] = useState(null)      // campaign id being redeemed
  const [redeemResult, setRedeemResult] = useState({})  // campaign id -> message
  const [showCodeEntry, setShowCodeEntry] = useState(false)
  const [manualCode, setManualCode] = useState('')
  const [manualMsg, setManualMsg] = useState(null)      // { ok, text }

  const isOwner = (user?.role || '').toLowerCase() !== 'cashier'

  const load = useCallback(async () => {
    if (!token || !isOwner) return
    try {
      const data = await api.get('/announcements')
      const list = data?.announcements || []
      setItems(list)
      // Fire-and-forget "seen" acks — the funnel's second stage.
      list.forEach(a => {
        api.post(`/announcements/${a.id}/ack`, { event: 'seen' }).catch(() => {})
      })
    } catch (err) {
      logger.debug('[ANNOUNCE] fetch skipped:', err?.message)
      setItems([])
    }
  }, [token, isOwner])

  useEffect(() => { load() }, [load])

  async function dismiss(a) {
    setItems(prev => prev.filter(x => x.id !== a.id))
    try { await api.post(`/announcements/${a.id}/ack`, { event: 'dismissed' }) } catch { /* quiet */ }
  }

  async function redeemFromCampaign(a) {
    if (!a.offer_code || redeeming) return
    setRedeeming(a.id)
    try {
      await api.post(`/announcements/${a.id}/ack`, { event: 'clicked' }).catch(() => {})
      const res = await api.post('/offers/redeem', { code: a.offer_code })
      setRedeemResult(prev => ({ ...prev, [a.id]: { ok: true, text: res.message || 'Offer applied!' } }))
    } catch (err) {
      setRedeemResult(prev => ({ ...prev, [a.id]: { ok: false, text: err?.detail || err?.message || 'Could not redeem this offer.' } }))
    } finally {
      setRedeeming(null)
    }
  }

  async function redeemManual(e) {
    e.preventDefault()
    if (!manualCode.trim()) return
    setManualMsg(null)
    try {
      const res = await api.post('/offers/redeem', { code: manualCode.trim() })
      setManualMsg({ ok: true, text: res.message || 'Offer applied!' })
      setManualCode('')
    } catch (err) {
      setManualMsg({ ok: false, text: err?.detail || err?.message || 'Invalid code.' })
    }
  }

  if (!isOwner) return null
  if (items.length === 0 && !showCodeEntry) {
    // Nothing to show — just the quiet affordance so codes are always redeemable.
    return (
      <div style={{ textAlign: 'center', marginTop: 4 }}>
        <button
          onClick={() => setShowCodeEntry(true)}
          style={{
            background: 'transparent', border: 'none', cursor: 'pointer',
            color: 'var(--text-secondary)', fontSize: '0.72rem',
            textDecoration: 'underline', textUnderlineOffset: 3, opacity: 0.8,
          }}
        >
          Have an offer code?
        </button>
      </div>
    )
  }

  return (
    <div style={{ width: '100%', maxWidth: 480, display: 'flex', flexDirection: 'column', gap: 10, margin: '0 auto 24px' }}>
      {items.map(a => {
        const result = redeemResult[a.id]
        return (
          <div key={a.id} className="slide-up" style={{
            position: 'relative',
            border: '1px solid var(--border, var(--border-color, #e2e2e2))',
            borderLeft: '3px solid var(--accent)',
            borderRadius: 10,
            padding: '14px 38px 14px 16px',
            background: 'var(--card, var(--card-color, transparent))',
            textAlign: 'left',
          }}>
            {/* Dismiss */}
            <button onClick={() => dismiss(a)} title="Dismiss" aria-label="Dismiss announcement" style={{
              position: 'absolute', top: 8, right: 8,
              background: 'transparent', border: 'none', cursor: 'pointer',
              color: 'var(--text-secondary)', fontSize: 16, lineHeight: 1, padding: 4,
            }}>×</button>

            <div style={{
              fontSize: 13, fontWeight: 700, letterSpacing: '0.02em',
              color: 'var(--accent)', marginBottom: 6, paddingRight: 8,
            }}>
              {a.title}
            </div>
            <div style={{ fontSize: 13, lineHeight: 1.55, color: 'var(--text, inherit)' }}
              dangerouslySetInnerHTML={renderMiniMarkdown(a.body_md)} />

            {a.offer_code && !result?.ok && (
              <div style={{ marginTop: 10, display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
                <button
                  className="chip"
                  disabled={redeeming === a.id}
                  onClick={() => redeemFromCampaign(a)}
                  style={{ fontWeight: 700 }}
                >
                  {redeeming === a.id ? 'Applying…' : `Redeem ${a.offer_code}`}
                </button>
                {result && !result.ok && (
                  <span style={{ fontSize: 12, color: '#c53030' }}>{result.text}</span>
                )}
              </div>
            )}
            {result?.ok && (
              <div style={{ marginTop: 10, fontSize: 12.5, fontWeight: 600, color: '#3a9a5c' }}>
                ✓ {result.text}
              </div>
            )}
          </div>
        )
      })}

      {/* Manual code entry */}
      {showCodeEntry ? (
        <form onSubmit={redeemManual} style={{ display: 'flex', gap: 8, alignItems: 'center', justifyContent: 'center', flexWrap: 'wrap' }}>
          <input
            type="text"
            value={manualCode}
            placeholder="Enter offer code"
            onChange={e => { setManualCode(e.target.value.toUpperCase()); setManualMsg(null) }}
            style={{
              padding: '8px 12px', borderRadius: 8, fontSize: 13, width: 180,
              border: '1px solid var(--border, var(--border-color, #ccc))',
              background: 'transparent', color: 'inherit',
              fontFamily: "'Geist Mono', monospace", letterSpacing: '0.06em',
            }}
          />
          <button type="submit" className="chip" style={{ fontWeight: 700 }}>Apply</button>
          <button type="button" onClick={() => { setShowCodeEntry(false); setManualMsg(null) }} style={{
            background: 'transparent', border: 'none', cursor: 'pointer',
            color: 'var(--text-secondary)', fontSize: 12, textDecoration: 'underline',
          }}>Close</button>
          {manualMsg && (
            <div style={{ width: '100%', textAlign: 'center', fontSize: 12.5, fontWeight: 600, color: manualMsg.ok ? '#3a9a5c' : '#c53030' }}>
              {manualMsg.ok ? '✓ ' : ''}{manualMsg.text}
            </div>
          )}
        </form>
      ) : (
        <div style={{ textAlign: 'center' }}>
          <button onClick={() => setShowCodeEntry(true)} style={{
            background: 'transparent', border: 'none', cursor: 'pointer',
            color: 'var(--text-secondary)', fontSize: '0.72rem',
            textDecoration: 'underline', textUnderlineOffset: 3, opacity: 0.8,
          }}>
            Have an offer code?
          </button>
        </div>
      )}
    </div>
  )
}
