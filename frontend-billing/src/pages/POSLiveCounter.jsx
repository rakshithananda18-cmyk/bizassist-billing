// ============================================================================
// Page: POSLiveCounter.jsx
// Description: Owner Live Counters view. Shows active POS cashier sessions,
//              their active cart status, and live connection tracking.
//              Displays network mode (LAN vs cloud) per counter with clear
//              visual badges. Includes Settings shortcut for configuration.
// ============================================================================
import React, { useEffect, useMemo, useState } from 'react'
import { useSearchParams, useNavigate } from 'react-router-dom'
import AppLayout from '../layouts/AppLayout'
import { useAuth } from '../contexts/AuthContext'
import { useReadinessProbe } from '../hooks/useReadinessProbe'
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

// ── Network badge component ───────────────────────────────────────────────────
function NetworkBadge({ networkMode }) {
  if (!networkMode) return null
  const isLocal = networkMode === 'local'
  return (
    <span style={{
      display: 'inline-flex',
      alignItems: 'center',
      gap: 4,
      padding: '2px 8px',
      borderRadius: 20,
      fontSize: '0.65rem',
      fontWeight: 700,
      letterSpacing: '0.03em',
      background: isLocal
        ? 'rgba(34,197,94,0.13)'
        : 'rgba(99,102,241,0.13)',
      color: isLocal
        ? 'var(--success, #22c55e)'
        : '#818cf8',
      border: `1px solid ${isLocal ? 'rgba(34,197,94,0.3)' : 'rgba(99,102,241,0.3)'}`,
    }}>
      <span style={{
        width: 5, height: 5, borderRadius: '50%',
        background: isLocal ? 'var(--success, #22c55e)' : '#818cf8',
        display: 'inline-block',
        flexShrink: 0,
      }} />
      {isLocal ? 'LAN' : 'Cloud'}
    </span>
  )
}

// ── Connection status strip ───────────────────────────────────────────────────
function ConnectionStrip({ sseProbe, networkMode }) {
  const isConnected = sseProbe?.status === 'online'
  const isChecking  = sseProbe?.status === 'checking'
  const isLocal     = IS_LOCAL_APP || networkMode === 'local'

  return (
    <div style={{
      display: 'flex',
      alignItems: 'center',
      gap: 10,
      padding: '8px 16px',
      borderRadius: 10,
      background: isConnected
        ? 'rgba(34,197,94,0.07)'
        : isChecking
          ? 'rgba(234,179,8,0.07)'
          : 'rgba(239,68,68,0.07)',
      border: `1px solid ${isConnected ? 'rgba(34,197,94,0.25)' : isChecking ? 'rgba(234,179,8,0.25)' : 'rgba(239,68,68,0.25)'}`,
      marginBottom: 20,
    }}>
      {/* Animated pulse dot */}
      <span style={{
        position: 'relative',
        width: 10,
        height: 10,
        flexShrink: 0,
      }}>
        <span style={{
          position: 'absolute',
          inset: 0,
          borderRadius: '50%',
          background: isConnected ? 'var(--success, #22c55e)' : isChecking ? '#eab308' : '#ef4444',
          animation: isConnected ? 'pulse-dot 2s infinite' : 'none',
        }} />
      </span>

      <div style={{ flex: 1 }}>
        <span style={{
          fontSize: '0.78rem',
          fontWeight: 600,
          color: isConnected ? 'var(--success, #22c55e)' : isChecking ? '#eab308' : '#ef4444',
        }}>
          {isConnected ? 'Live feed connected' : isChecking ? 'Connecting…' : 'Live feed disconnected'}
        </span>
        <span style={{ fontSize: '0.72rem', color: 'var(--text-muted)', marginLeft: 8 }}>
          {isLocal ? 'Direct LAN connection — ultra-low latency' : 'Relayed via cloud SSE'}
        </span>
      </div>

      {/* Network path indicator */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexShrink: 0 }}>
        <span style={{
          fontSize: '0.65rem',
          fontWeight: 700,
          padding: '2px 8px',
          borderRadius: 20,
          background: isLocal ? 'rgba(34,197,94,0.13)' : 'rgba(99,102,241,0.13)',
          color: isLocal ? 'var(--success, #22c55e)' : '#818cf8',
          border: `1px solid ${isLocal ? 'rgba(34,197,94,0.3)' : 'rgba(99,102,241,0.3)'}`,
          display: 'inline-flex', alignItems: 'center', gap: 4,
        }}>
          {isLocal ? (
            <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
              <path d="M5 12.55a11 11 0 0 1 14.08 0"/><path d="M1.42 9a16 16 0 0 1 21.16 0"/><path d="M8.53 16.11a6 6 0 0 1 6.95 0"/><circle cx="12" cy="20" r="1"/>
            </svg>
          ) : (
            <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
              <path d="M18 10h-1.26A8 8 0 1 0 9 20h9a5 5 0 0 0 0-10z"/>
            </svg>
          )}
          {isLocal ? 'LAN' : 'Cloud'}
        </span>
      </div>
    </div>
  )
}

// ── Counter tile ──────────────────────────────────────────────────────────────
function CounterTile({ s, highlight, onClick }) {
  const isOffline = s.offline || s.idle

  return (
    <div
      onClick={() => !isOffline && onClick(s)}
      style={{
        padding: '16px',
        borderRadius: 12,
        border: highlight
          ? '2px solid var(--primary, #c0612a)'
          : `1px solid var(--border)`,
        opacity: isOffline ? 0.55 : 1,
        cursor: isOffline ? 'default' : 'pointer',
        background: isOffline ? 'rgba(255,255,255,0.015)' : 'var(--card-bg, inherit)',
        borderStyle: isOffline ? 'dashed' : 'solid',
        transition: 'transform 0.18s, border-color 0.18s, box-shadow 0.18s',
        position: 'relative',
        overflow: 'hidden',
      }}
      onMouseEnter={(e) => {
        if (isOffline) return
        e.currentTarget.style.transform = 'translateY(-2px) scale(1.015)'
        e.currentTarget.style.borderColor = 'var(--accent)'
        e.currentTarget.style.boxShadow = '0 6px 24px rgba(0,0,0,0.12)'
      }}
      onMouseLeave={(e) => {
        if (isOffline) return
        e.currentTarget.style.transform = ''
        e.currentTarget.style.borderColor = highlight ? 'var(--primary, #c0612a)' : 'var(--border)'
        e.currentTarget.style.boxShadow = ''
      }}
    >
      {/* Top row: counter label + status */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 10 }}>
        <span style={{
          fontSize: '0.75rem',
          fontWeight: 800,
          letterSpacing: '0.05em',
          padding: '2px 10px',
          borderRadius: 20,
          background: 'var(--accent-muted, rgba(192,97,42,0.12))',
          color: 'var(--accent, #c0612a)',
        }}>
          {s.counter || '—'}
        </span>

        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          {/* Network mode badge */}
          {!isOffline && s.network_mode && <NetworkBadge networkMode={s.network_mode} />}

          {/* Online/offline pill */}
          <span style={{
            fontSize: '0.68rem',
            fontWeight: 700,
            display: 'inline-flex',
            alignItems: 'center',
            gap: 4,
            color: isOffline ? 'var(--text-muted)' : 'var(--success, #22c55e)',
          }}>
            <span style={{
              width: 7, height: 7, borderRadius: '50%',
              background: isOffline ? 'var(--text-muted)' : 'var(--success, #22c55e)',
              display: 'inline-block',
              animation: isOffline ? 'none' : 'pulse-dot 2s infinite',
            }} />
            {isOffline ? 'Offline' : 'Live'}
          </span>
        </div>
      </div>

      {/* Cashier name + role */}
      <div style={{ fontSize: '0.95rem', fontWeight: 700, color: 'var(--text-primary)', marginBottom: 10 }}>
        {s.username || 'Unknown'}
        {s.role && (
          <span style={{ fontSize: '0.68rem', fontWeight: 500, color: 'var(--text-muted)', marginLeft: 6 }}>
            ({s.role})
          </span>
        )}
      </div>

      {/* Cart stats */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 10 }}>
        <span style={{ fontSize: '0.73rem', color: 'var(--text-muted)' }}>
          {s.item_count || 0} item{(s.item_count || 0) === 1 ? '' : 's'}
        </span>
        <span style={{
          fontSize: '1.2rem',
          fontWeight: 800,
          color: isOffline ? 'var(--text-muted)' : 'var(--text-primary)',
        }}>
          {isOffline ? '—' : money(s.cart_total)}
        </span>
      </div>

      {/* Footer: bill no + last seen */}
      <div style={{
        paddingTop: 10,
        borderTop: '1px solid var(--border)',
        display: 'flex',
        justifyContent: 'space-between',
        fontSize: '0.68rem',
        color: 'var(--text-muted)',
      }}>
        <span>Bill: {s.active_bill || '—'}</span>
        <span>{isOffline ? '—' : relTime(s._recv)}</span>
      </div>

      {/* Click hint for online counters */}
      {!isOffline && (
        <div style={{
          position: 'absolute',
          bottom: 0, left: 0, right: 0,
          padding: '6px',
          textAlign: 'center',
          fontSize: '0.63rem',
          fontWeight: 600,
          color: 'var(--accent)',
          opacity: 0,
          transition: 'opacity 0.18s',
          background: 'var(--card-bg, inherit)',
          borderTop: '1px solid var(--border)',
        }}
          className="tile-hint"
        >
          Click to view live cart →
        </div>
      )}
    </div>
  )
}

// ── Main page ─────────────────────────────────────────────────────────────────
export default function POSLiveCounter() {
  const { user, authFetch, settings, networkMode } = useAuth()
  const { sseProbe } = useReadinessProbe()
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
    if (isOwner && (hostingMode === 'cloud' || hostingMode === 'hybrid')) {
      authFetch('/staff')
        .then(r => r.ok ? r.json() : [])
        .then(data => setStaffList(data || []))
        .catch(err => logger.error('[COUNTERS] failed to fetch staff list', err))
    }
  }, [isOwner, hostingMode, authFetch])

  // Listen to SSE presence updates (cloud and hybrid both have SSE)
  useEffect(() => {
    if (hostingMode === 'local') return

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
          network_mode: null,
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
          configuredCounters.set(prefix, { ...s, offline: false, idle: false })
        } else {
          configuredCounters.set(prefix, {
            ...configuredCounters.get(prefix),
            ...s,
            offline: true,
            idle: true,
          })
        }
      } else {
        configuredCounters.set(prefix, {
          ...s,
          offline: isStale,
          idle: isStale,
        })
      }
    })

    return Array.from(configuredCounters.values())
      .sort((a, b) => String(a.counter || '').localeCompare(String(b.counter || '')))
  }, [sessions, staffList])

  const onlineCount = tiles.filter(t => !t.offline && !t.idle).length
  const totalCount  = tiles.length

  const handleTileClick = (s) => {
    logger.info(`[COUNTERS] Owner clicking tile to view Counter ${s.counter} (client: ${s.client_id})`)
    navigate(`/live-view?live_counter=${encodeURIComponent(s.counter)}&client_id=${encodeURIComponent(s.client_id)}`)
  }

  return (
    <AppLayout title="POS Counters">
      <style>{`
        @keyframes pulse-dot {
          0%, 100% { opacity: 1; transform: scale(1); }
          50%       { opacity: 0.6; transform: scale(1.4); }
        }
        .counter-tile:hover .tile-hint { opacity: 1 !important; }
      `}</style>

      <div className="slide-up">
        <div className="page-header">
          <div className="page-header-left">
            <h1 className="page-title">POS Counters</h1>
            <p className="page-subtitle">
              Watch each till in real time — click any counter to view its live cart.
            </p>
          </div>

          {/* Summary chips */}
          {isOwner && tiles.length > 0 && (
            <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexShrink: 0 }}>
              <span style={{
                padding: '4px 14px', borderRadius: 20, fontSize: '0.78rem', fontWeight: 700,
                background: 'rgba(34,197,94,0.12)', color: 'var(--success, #22c55e)',
                border: '1px solid rgba(34,197,94,0.25)',
              }}>
                {onlineCount} Live
              </span>
              <span style={{
                padding: '4px 14px', borderRadius: 20, fontSize: '0.78rem', fontWeight: 600,
                background: 'var(--bg-muted, rgba(255,255,255,0.05))', color: 'var(--text-muted)',
                border: '1px solid var(--border)',
              }}>
                {totalCount} Total
              </span>
            </div>
          )}
        </div>

        <div style={{ maxWidth: 1080, margin: '0 auto', padding: '0 4px 40px' }}>
          {/* Non-owner warning */}
          {!isOwner && (
            <div className="alert alert-warning">Only the business owner can view live counters.</div>
          )}

          {/* Local-only mode: cloud upgrade needed */}
          {isOwner && hostingMode === 'local' && (
            <div className="card" style={{
              padding: '48px 32px', textAlign: 'center',
              maxWidth: 560, margin: '48px auto',
              borderRadius: 18,
              border: '1px solid var(--border)',
            }}>
              <div style={{ fontSize: '3rem', marginBottom: 16 }}>☁️</div>
              <h2 style={{ fontSize: '1.25rem', fontWeight: 700, color: 'var(--text-primary)', marginBottom: 10 }}>
                Live Counters needs cloud sync
              </h2>
              <p style={{ fontSize: '0.88rem', color: 'var(--text-secondary)', marginBottom: 28, lineHeight: 1.6 }}>
                Real-time counter monitoring uses cloud SSE. Switch to <strong>Local + Cloud</strong> mode
                in Settings to enable it — billing stays fast and local, only the live view connects to the cloud.
              </p>
              <button
                onClick={() => navigate('/settings?tab=hosting')}
                style={{
                  background: 'var(--accent)', color: '#fff', border: 'none',
                  padding: '10px 24px', borderRadius: 8, fontWeight: 700,
                  cursor: 'pointer', fontSize: '0.88rem', transition: 'opacity 0.2s',
                }}
                onMouseEnter={e => e.currentTarget.style.opacity = '0.85'}
                onMouseLeave={e => e.currentTarget.style.opacity = '1'}
              >
                Go to Settings
              </button>
            </div>
          )}

          {/* Active counter view */}
          {isOwner && (hostingMode === 'cloud' || hostingMode === 'hybrid') && (
            <>
              {/* Connection status strip */}
              <ConnectionStrip sseProbe={sseProbe} networkMode={networkMode} />

              {/* Network legend */}
              <div style={{
                display: 'flex', gap: 14, alignItems: 'center',
                marginBottom: 20, flexWrap: 'wrap',
              }}>
                <span style={{ fontSize: '0.72rem', color: 'var(--text-muted)', fontWeight: 600 }}>
                  Connection mode:
                </span>
                <span style={{ display: 'inline-flex', alignItems: 'center', gap: 5,
                  fontSize: '0.7rem', fontWeight: 700, color: 'var(--success, #22c55e)' }}>
                  <svg width="9" height="9" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                    <path d="M5 12.55a11 11 0 0 1 14.08 0"/><path d="M1.42 9a16 16 0 0 1 21.16 0"/><path d="M8.53 16.11a6 6 0 0 1 6.95 0"/><circle cx="12" cy="20" r="1"/>
                  </svg>
                  LAN — same WiFi/network, ultra-low latency
                </span>
                <span style={{ display: 'inline-flex', alignItems: 'center', gap: 5,
                  fontSize: '0.7rem', fontWeight: 700, color: '#818cf8' }}>
                  <svg width="9" height="9" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                    <path d="M18 10h-1.26A8 8 0 1 0 9 20h9a5 5 0 0 0 0-10z"/>
                  </svg>
                  Cloud — different network, relayed via internet
                </span>
              </div>

              {tiles.length === 0 ? (
                <div className="card" style={{ padding: 32, textAlign: 'center', color: 'var(--text-muted)', borderRadius: 12 }}>
                  <div style={{ fontSize: '2rem', marginBottom: 12 }}>🏪</div>
                  <div style={{ fontWeight: 600, marginBottom: 6 }}>No cashier counters configured</div>
                  <div style={{ fontSize: '0.83rem' }}>
                    A till appears here when you add cashiers with counter prefixes under{' '}
                    <span
                      onClick={() => navigate('/settings')}
                      style={{ color: 'var(--accent)', cursor: 'pointer', textDecoration: 'underline' }}
                    >
                      Staff settings
                    </span>.
                  </div>
                </div>
              ) : (
                <div style={{
                  display: 'grid',
                  gridTemplateColumns: 'repeat(auto-fill, minmax(270px, 1fr))',
                  gap: 16,
                }}>
                  {tiles.map(s => (
                    <div key={s.client_id || s.counter} className="counter-tile">
                      <CounterTile
                        s={s}
                        highlight={focusCounter && String(s.counter) === String(focusCounter)}
                        onClick={handleTileClick}
                      />
                    </div>
                  ))}
                </div>
              )}

              {/* Settings shortcut */}
              <div style={{
                marginTop: 32,
                padding: '14px 20px',
                borderRadius: 10,
                background: 'var(--bg-muted, rgba(255,255,255,0.03))',
                border: '1px solid var(--border)',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                gap: 12,
              }}>
                <div>
                  <div style={{ fontSize: '0.82rem', fontWeight: 700, color: 'var(--text-primary)' }}>
                    Configure counters &amp; discovery
                  </div>
                  <div style={{ fontSize: '0.72rem', color: 'var(--text-muted)', marginTop: 2 }}>
                    Add cashier staff with counter prefixes, or change network / hosting settings.
                  </div>
                </div>
                <button
                  onClick={() => navigate('/settings?tab=hosting')}
                  style={{
                    background: 'transparent', border: '1px solid var(--border)',
                    color: 'var(--text-secondary)', padding: '6px 16px',
                    borderRadius: 6, cursor: 'pointer', fontSize: '0.78rem',
                    fontWeight: 600, flexShrink: 0,
                    transition: 'border-color 0.2s, color 0.2s',
                  }}
                  onMouseEnter={e => {
                    e.currentTarget.style.borderColor = 'var(--accent)'
                    e.currentTarget.style.color = 'var(--accent)'
                  }}
                  onMouseLeave={e => {
                    e.currentTarget.style.borderColor = 'var(--border)'
                    e.currentTarget.style.color = 'var(--text-secondary)'
                  }}
                >
                  Settings →
                </button>
              </div>
            </>
          )}
        </div>
      </div>
    </AppLayout>
  )
}
