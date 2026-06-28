// pages/Counters.jsx — Owner Live Counters (plan §9.2 Stage 1).
// =============================================================
// Read-only view: each active POS session publishes a presence snapshot
// (`POST /realtime/presence` → SSE `pos.presence`), and the owner watches each
// till live here — who's on it, their counter, current cart total, last bill.
// Nothing here writes back to a cashier's cart; it's pure observation. The
// edit-a-counter flow (request → approve → soft-lock) is the future Phase 4 step.
import React, { useEffect, useMemo, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import AppLayout from '../layouts/AppLayout'
import { useAuth } from '../contexts/AuthContext'

const STALE_MS = 45000   // no heartbeat for this long → mark the counter idle

const money = (n) => `₹${Number(n || 0).toLocaleString('en-IN', { maximumFractionDigits: 2 })}`

function relTime(ts) {
  if (!ts) return '—'
  const s = Math.max(0, Math.round((Date.now() - ts) / 1000))
  if (s < 5) return 'just now'
  if (s < 60) return `${s}s ago`
  const m = Math.round(s / 60)
  return m < 60 ? `${m}m ago` : `${Math.round(m / 60)}h ago`
}

export default function Counters() {
  const { user } = useAuth()
  const isOwner = (user?.role || '').toLowerCase() !== 'cashier'
  const [params] = useSearchParams()
  const focusCounter = params.get('counter')
  const [sessions, setSessions] = useState({})   // client_id -> latest snapshot
  const [, tick] = useState(0)

  useEffect(() => {
    const onSync = (e) => {
      const d = e.detail
      if (!d || d.type !== 'pos.presence' || !d.client_id) return
      setSessions(prev => ({ ...prev, [d.client_id]: { ...d, _recv: Date.now() } }))
    }
    window.addEventListener('sync-event', onSync)
    const iv = setInterval(() => tick(t => t + 1), 5000)   // refresh "last seen" / idle
    return () => { window.removeEventListener('sync-event', onSync); clearInterval(iv) }
  }, [])

  const tiles = useMemo(() => {
    const now = Date.now()
    return Object.values(sessions)
      .map(s => ({ ...s, idle: now - (s._recv || 0) > STALE_MS }))
      .sort((a, b) => String(a.counter || '').localeCompare(String(b.counter || '')))
  }, [sessions, focusCounter])

  return (
    <AppLayout title="Live Counters">
      <div className="slide-up">
        <div className="page-header">
          <div className="page-header-left">
            <h1 className="page-title">Live Counters</h1>
            <p className="page-subtitle">
              Watch each till in real time — current cart, totals, and who's billing. View-only.
            </p>
          </div>
        </div>

        <div style={{ maxWidth: 1080, margin: '0 auto', padding: '0 4px 24px' }}>
          {!isOwner && (
            <div className="alert alert-warning">Only the business owner can view live counters.</div>
          )}

          {isOwner && tiles.length === 0 && (
            <div className="card" style={{ padding: 24, textAlign: 'center', color: 'var(--text-muted)' }}>
              No active counters yet. A till appears here when a cashier opens the POS in <strong>cloud</strong> mode.
            </div>
          )}

          {isOwner && tiles.length > 0 && (
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(260px, 1fr))', gap: 16 }}>
              {tiles.map(s => {
                const highlight = focusCounter && String(s.counter) === String(focusCounter)
                return (
                  <div key={s.client_id} className="card" style={{
                    padding: 16, borderRadius: 10,
                    border: highlight ? '2px solid var(--primary, #c0612a)' : '1px solid var(--border)',
                    opacity: s.idle ? 0.6 : 1,
                  }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 10 }}>
                      <span className="badge badge-muted" style={{ fontSize: '0.8rem', fontWeight: 700 }}>
                        {s.counter || '—'}
                      </span>
                      <span style={{
                        fontSize: '0.7rem', fontWeight: 600,
                        color: s.idle ? 'var(--text-muted)' : 'var(--success, #2e7d32)',
                        display: 'inline-flex', alignItems: 'center', gap: 5,
                      }}>
                        <span style={{
                          width: 8, height: 8, borderRadius: '50%',
                          background: s.idle ? 'var(--text-muted)' : 'var(--success, #2e7d32)',
                          display: 'inline-block',
                        }} />
                        {s.idle ? 'Idle' : 'Active'}
                      </span>
                    </div>

                    <div style={{ fontSize: '0.95rem', fontWeight: 700, color: 'var(--text-primary)' }}>
                      {s.username || 'Unknown'}
                      {s.role && <span style={{ fontSize: '0.7rem', fontWeight: 500, color: 'var(--text-muted)', marginLeft: 6 }}>({s.role})</span>}
                    </div>

                    <div style={{ marginTop: 12, display: 'flex', justifyContent: 'space-between', alignItems: 'baseline' }}>
                      <span style={{ fontSize: '0.72rem', color: 'var(--text-muted)' }}>
                        {s.item_count || 0} item{(s.item_count || 0) === 1 ? '' : 's'}
                      </span>
                      <span style={{ fontSize: '1.15rem', fontWeight: 800, color: 'var(--text-primary)' }}>
                        {money(s.cart_total)}
                      </span>
                    </div>

                    <div style={{ marginTop: 10, paddingTop: 10, borderTop: '1px solid var(--border)', display: 'flex', justifyContent: 'space-between', fontSize: '0.7rem', color: 'var(--text-muted)' }}>
                      <span>Bill: {s.active_bill || '—'}</span>
                      <span>{relTime(s._recv)}</span>
                    </div>
                  </div>
                )
              })}
            </div>
          )}
        </div>
      </div>
    </AppLayout>
  )
}
