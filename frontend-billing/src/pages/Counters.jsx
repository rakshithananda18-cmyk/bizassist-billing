// ============================================================================
// Page: Counters.jsx
// Description: Owner Live Counters view. Shows active POS cashier sessions,
//              their active cart status, and live connection tracking.
//              Enables counter control and monitoring for store owners.
// ============================================================================
import React, { useEffect, useMemo, useState } from 'react'
import { useSearchParams, useNavigate } from 'react-router-dom'
import AppLayout from '../layouts/AppLayout'
import { useAuth } from '../contexts/AuthContext'
import { logger } from '../utils/logger'
import { IS_LOCAL_APP } from '../config'

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
  const { user, authFetch, settings } = useAuth()
  const isOwner = (user?.role || '').toLowerCase() !== 'cashier'
  const [params] = useSearchParams()
  const focusCounter = params.get('counter')
  const [sessions, setSessions] = useState({})   // client_id -> latest snapshot
  const [, tick] = useState(0)
  const navigate = useNavigate()

  // Resolve hosting mode preference
  const clientMode = (typeof localStorage !== 'undefined' && localStorage.getItem('bizassist_hosting_mode')) || null
  const hostingMode = !IS_LOCAL_APP
    ? 'cloud'
    : (clientMode || settings?.general?.hosting_mode || 'local')

  const [staffList, setStaffList] = useState([])

  // Fetch staff list to get all configured counters
  useEffect(() => {
    if (isOwner && hostingMode === 'cloud') {
      authFetch('/staff')
        .then(r => r.ok ? r.json() : [])
        .then(data => setStaffList(data || []))
        .catch(err => logger.error('[COUNTERS] failed to fetch staff list', err))
    }
  }, [isOwner, hostingMode, authFetch])

  // Listen to SSE presence updates
  useEffect(() => {
    if (hostingMode !== 'cloud') return

    const onSync = (e) => {
      const d = e.detail
      if (!d || d.type !== 'pos.presence' || !d.client_id) return
      setSessions(prev => ({ ...prev, [d.client_id]: { ...d, _recv: Date.now() } }))
    }
    window.addEventListener('sync-event', onSync)
    const iv = setInterval(() => tick(t => t + 1), 5000)   // refresh "last seen" / idle
    return () => { window.removeEventListener('sync-event', onSync); clearInterval(iv) }
  }, [hostingMode])

  // Merge configured staff counter prefixes with active presence snapshots
  const tiles = useMemo(() => {
    const now = Date.now()
    const configuredCounters = new Map()

    // 1. Add all counter prefixes configured in the staff list (starting as offline)
    staffList.forEach(s => {
      const prefix = (s.counter_prefix || '').trim()
      if (prefix && prefix.toUpperCase() !== 'OW') {
        configuredCounters.set(prefix, {
          counter: prefix,
          username: s.name || s.username || 'Cashier',
          role: s.role || 'Cashier',
          item_count: 0,
          cart_total: 0,
          active_bill: '—',
          offline: true,
          client_id: null,
          _recv: null
        })
      }
    })

    // 2. Overlay any active presence messages received over SSE
    Object.values(sessions).forEach(s => {
      const prefix = (s.counter || '').trim()
      if (!prefix || prefix.toUpperCase() === 'OW') return

      const isStale = now - (s._recv || 0) > STALE_MS

      if (configuredCounters.has(prefix)) {
        if (!isStale) {
          configuredCounters.set(prefix, {
            ...s,
            offline: false,
            idle: false
          })
        } else {
          // Keep metadata but mark as offline
          configuredCounters.set(prefix, {
            ...configuredCounters.get(prefix),
            ...s,
            offline: true,
            idle: true
          })
        }
      } else {
        // If not in staff list but active, add it dynamically
        configuredCounters.set(prefix, {
          ...s,
          offline: isStale,
          idle: isStale
        })
      }
    })

    return Array.from(configuredCounters.values())
      .sort((a, b) => String(a.counter || '').localeCompare(String(b.counter || '')))
  }, [sessions, staffList])

  return (
    <AppLayout title="Live Counters">
      <div className="slide-up">
        <div className="page-header">
          <div className="page-header-left">
            <h1 className="page-title">Live Counters</h1>
            <p className="page-subtitle">
              Watch each till in real time — click any counter to view its live cart or edit items.
            </p>
          </div>
        </div>

        <div style={{ maxWidth: 1080, margin: '0 auto', padding: '0 4px 24px' }}>
          {!isOwner && (
            <div className="alert alert-warning">Only the business owner can view live counters.</div>
          )}

          {isOwner && hostingMode !== 'cloud' && (
            <div className="card" style={{ padding: '40px 24px', textAlign: 'center', maxWidth: 600, margin: '40px auto', borderRadius: 16, border: '1px solid var(--border)' }}>
              <div style={{ fontSize: '3rem', marginBottom: 16 }}>☁️</div>
              <h2 style={{ fontSize: '1.25rem', fontWeight: 700, color: 'var(--text-primary)', marginBottom: 8 }}>Live Counters requires Cloud Mode</h2>
              <p style={{ fontSize: '0.9rem', color: 'var(--text-secondary)', marginBottom: 24, lineHeight: 1.5 }}>
                Real-time counter monitoring, remote screen viewing, and cashier-consented bill editing are cloud-only features. Switch your terminal to Cloud Mode to enable these collaborative tools.
              </p>
              <button
                onClick={() => navigate('/settings')}
                style={{
                  background: 'var(--accent)',
                  color: '#fff',
                  border: 'none',
                  padding: '10px 20px',
                  borderRadius: 6,
                  fontWeight: 600,
                  cursor: 'pointer',
                  fontSize: '0.88rem',
                  transition: 'background 0.2s'
                }}
                onMouseEnter={(e) => e.currentTarget.style.background = 'var(--accent-hover, var(--accent))'}
                onMouseLeave={(e) => e.currentTarget.style.background = 'var(--accent)'}
              >
                Go to Settings
              </button>
            </div>
          )}

          {isOwner && hostingMode === 'cloud' && tiles.length === 0 && (
            <div className="card" style={{ padding: 24, textAlign: 'center', color: 'var(--text-muted)' }}>
              No cashier counters configured. A till appears here when you add cashiers with counter prefixes under Staff settings.
            </div>
          )}

          {isOwner && hostingMode === 'cloud' && tiles.length > 0 && (
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(260px, 1fr))', gap: 16 }}>
              {tiles.map(s => {
                const highlight = focusCounter && String(s.counter) === String(focusCounter)
                const isOffline = s.offline || s.idle

                return (
                  <div
                    key={s.client_id || s.counter}
                    className="card"
                    onClick={() => {
                      if (isOffline) {
                        logger.info(`[COUNTERS] Clicked offline counter ${s.counter} — no action`)
                        return
                      }
                      logger.info(`[COUNTERS] Owner clicking tile to view Counter ${s.counter} (client: ${s.client_id})`)
                      navigate(`/live-view?live_counter=${encodeURIComponent(s.counter)}&client_id=${encodeURIComponent(s.client_id)}`)
                    }}
                    style={{
                      padding: 16, borderRadius: 10,
                      border: highlight ? '2px solid var(--primary, #c0612a)' : '1px solid var(--border)',
                      opacity: isOffline ? 0.55 : 1,
                      cursor: isOffline ? 'default' : 'pointer',
                      background: isOffline ? 'rgba(255,255,255,0.015)' : 'var(--card-bg, inherit)',
                      borderStyle: isOffline ? 'dashed' : 'solid',
                      transition: 'transform 0.2s, border-color 0.2s',
                    }}
                    onMouseEnter={(e) => {
                      if (isOffline) return
                      e.currentTarget.style.transform = 'scale(1.02)'
                      e.currentTarget.style.borderColor = 'var(--accent)'
                    }}
                    onMouseLeave={(e) => {
                      if (isOffline) return
                      e.currentTarget.style.transform = 'scale(1)'
                      e.currentTarget.style.borderColor = highlight ? 'var(--primary, #c0612a)' : 'var(--border)'
                    }}
                  >
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 10 }}>
                      <span className="badge badge-muted" style={{ fontSize: '0.8rem', fontWeight: 700 }}>
                        {s.counter || '—'}
                      </span>
                      <span style={{
                        fontSize: '0.7rem', fontWeight: 600,
                        color: isOffline ? 'var(--text-muted)' : 'var(--success, #22c55e)',
                        display: 'inline-flex', alignItems: 'center', gap: 5,
                      }}>
                        <span style={{
                          width: 8, height: 8, borderRadius: '50%',
                          background: isOffline ? 'var(--text-muted)' : 'var(--success, #22c55e)',
                          display: 'inline-block',
                        }} />
                        {isOffline ? 'Offline' : 'Connected'}
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
                      <span style={{ fontSize: '1.15rem', fontWeight: 800, color: isOffline ? 'var(--text-muted)' : 'var(--text-primary)' }}>
                        {isOffline ? '—' : money(s.cart_total)}
                      </span>
                    </div>

                    <div style={{ marginTop: 10, paddingTop: 10, borderTop: '1px solid var(--border)', display: 'flex', justifyContent: 'space-between', fontSize: '0.7rem', color: 'var(--text-muted)' }}>
                      <span>Bill: {s.active_bill || '—'}</span>
                      <span>{isOffline ? '—' : relTime(s._recv)}</span>
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
