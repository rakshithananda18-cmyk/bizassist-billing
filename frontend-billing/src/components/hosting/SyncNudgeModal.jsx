import React, { useEffect, useState } from 'react'
import { useAuth } from '../../contexts/AuthContext'
import BackupModal from './BackupModal'
import { SyncIcon } from '../Icons'

// Snooze key stored in sessionStorage — resets on every new browser session/tab.
const SNOOZE_KEY = 'bizassist_sync_nudge_snoozed_until'
const SNOOZE_MS  = 4 * 60 * 60 * 1000  // 4 hours

/**
 * SyncNudgeModal — a non-blocking nudge shown (for premium accounts) when the
 * cloud and this device hold different amounts of data, sensed at login via
 * a read-only count compare (see utils/loginSync.js → 'cloud-data-available').
 *
 * Two directions:
 *   • 'cloud-to-local' — cloud has data not yet on this device (e.g. another
 *     device billed while this desktop app was closed). Offer to pull it down.
 *   • 'local-to-cloud' — this device has data not yet on the cloud (e.g. billed
 *     offline, or cloud was unreachable). Offer to push it up.
 *
 * Buttons:
 *   • "Sync Now"      — opens BackupModal in the correct direction.
 *   • "Remind Later"  — snoozes the nudge for 4 hours (sessionStorage).
 *
 * Data movement stays gated behind an explicit click — nothing syncs automatically.
 * Mount once near the app root.
 */
export default function SyncNudgeModal() {
  const { token } = useAuth()
  const [info, setInfo]     = useState(null)   // { direction, cloudTotal, localTotal, delta }
  const [syncing, setSyncing] = useState(false)

  useEffect(() => {
    const onEvt = (e) => {
      // Honour snooze: don't show again until the snooze window expires.
      try {
        const snoozedUntil = sessionStorage.getItem(SNOOZE_KEY)
        if (snoozedUntil && Date.now() < Number(snoozedUntil)) return
      } catch (_) {}
      setInfo(e?.detail || { delta: 0, direction: 'cloud-to-local' })
    }
    window.addEventListener('cloud-data-available', onEvt)
    return () => window.removeEventListener('cloud-data-available', onEvt)
  }, [])

  const handleRemindLater = () => {
    try { sessionStorage.setItem(SNOOZE_KEY, String(Date.now() + SNOOZE_MS)) } catch (_) {}
    setInfo(null)
  }

  const direction = info?.direction || 'cloud-to-local'
  const isPull    = direction === 'cloud-to-local'
  const n         = info?.delta || 0

  // Show the actual sync modal if the user clicked Sync Now.
  if (syncing) {
    return (
      <BackupModal
        token={token}
        direction={direction}
        onComplete={() => { setSyncing(false); setInfo(null) }}
        onError={() => { /* BackupModal shows its own error UI; keep it open */ }}
      />
    )
  }

  if (!info) return null

  // ── Title + description vary by direction ────────────────────────────────
  const title = isPull
    ? '☁️  Cloud data not on this device'
    : '📤  Local data not on cloud'

  const body = isPull ? (
    <>
      Your <strong>cloud account</strong> has{' '}
      {n > 0 ? <strong>{n} record{n === 1 ? '' : 's'}</strong> : 'data'}{' '}
      that {n === 1 ? "isn't" : "aren't"} on this desktop yet —
      probably billed from another device or the web app.
      <div style={{ marginTop: 8, color: 'var(--text-primary)', opacity: 0.7, fontSize: '0.8rem' }}>
        Sync down = safe merge. Nothing on this device gets deleted.
      </div>
    </>
  ) : (
    <>
      This <strong>desktop app</strong> has{' '}
      {n > 0 ? <strong>{n} record{n === 1 ? '' : 's'}</strong> : 'data'}{' '}
      that {n === 1 ? "isn't" : "aren't"} on the cloud yet —
      your other devices won't see {n === 1 ? 'it' : 'them'} until you sync.
      <div style={{ marginTop: 8, color: 'var(--text-primary)', opacity: 0.7, fontSize: '0.8rem' }}>
        Sync up = safe merge. Nothing on the cloud gets deleted.
      </div>
    </>
  )

  return (
    <div style={{
      position: 'fixed', inset: 0, zIndex: 9998,
      background: 'rgba(0,0,0,0.55)', backdropFilter: 'blur(6px)',
      display: 'flex', alignItems: 'center', justifyContent: 'center',
      padding: '0 16px',
    }}>
      <div style={{
        background: 'var(--bg-2, #1c1c1e)',
        border: '1px solid var(--border, rgba(255,255,255,0.12))',
        borderRadius: 18,
        padding: '28px 30px 22px',
        width: '100%', maxWidth: 460,
        boxShadow: '0 32px 96px rgba(0,0,0,0.55)',
      }}>

        {/* Header */}
        <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 8, marginBottom: 12 }}>
          <span style={{ fontSize: '1.05rem', fontWeight: 700, color: 'var(--text-primary)', lineHeight: 1.3 }}>
            {title}
          </span>
          <button
            type="button" aria-label="Dismiss"
            onClick={() => setInfo(null)}
            style={{ background: 'transparent', border: 'none', color: 'var(--text-muted)', cursor: 'pointer', fontSize: '1.3rem', lineHeight: 1, padding: '2px 4px', flexShrink: 0 }}
          >×</button>
        </div>

        {/* Body */}
        <div style={{ fontSize: '0.855rem', color: 'var(--text-muted)', lineHeight: 1.6, marginBottom: 22 }}>
          {body}
        </div>

        {/* Direction badge */}
        <div style={{
          display: 'inline-flex', alignItems: 'center', gap: 6,
          background: isPull ? 'rgba(99,179,237,0.12)' : 'rgba(154,230,180,0.12)',
          border: `1px solid ${isPull ? 'rgba(99,179,237,0.3)' : 'rgba(154,230,180,0.3)'}`,
          borderRadius: 20, padding: '4px 12px', fontSize: '0.77rem',
          color: isPull ? 'var(--info, #63b3ed)' : 'var(--success, #68d391)',
          marginBottom: 22, fontWeight: 600,
        }}>
          {isPull ? '☁️ Cloud → 🖥 Desktop' : '🖥 Desktop → ☁️ Cloud'}
        </div>

        {/* Action buttons */}
        <div style={{ display: 'flex', gap: 10, justifyContent: 'flex-end' }}>
          <button
            type="button"
            onClick={handleRemindLater}
            style={{
              padding: '8px 16px', borderRadius: 8, fontSize: '0.84rem', fontWeight: 600,
              background: 'transparent',
              border: '1px solid var(--border, rgba(255,255,255,0.15))',
              color: 'var(--text-muted)', cursor: 'pointer',
            }}
          >
            Remind Later
          </button>
          <button
            type="button"
            onClick={() => setSyncing(true)}
            style={{
              padding: '8px 20px', borderRadius: 8, fontSize: '0.84rem', fontWeight: 700,
              background: 'var(--accent)', color: '#fff', border: 'none', cursor: 'pointer',
              display: 'inline-flex', alignItems: 'center', gap: 7,
            }}
          >
            <SyncIcon size={14} />
            {isPull ? 'Sync Now' : 'Sync Now'}
          </button>
        </div>
      </div>
    </div>
  )
}
