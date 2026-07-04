import React, { useEffect, useState } from 'react'
import { useAuth } from '../../contexts/AuthContext'
import BackupModal from './BackupModal'
import { SyncIcon, CloudIcon } from '../Icons'

/**
 * SyncNudgeModal — a non-blocking nudge shown (for premium accounts) when the
 * cloud and this device hold different amounts of data, sensed at EVERY login via
 * a read-only count compare (see utils/loginSync.js → 'cloud-data-available').
 *
 * Two directions:
 *   • 'cloud-to-local' — the cloud is ahead; offer to pull it down so this device
 *     doesn't miss data another device created.
 *   • 'local-to-cloud' — this device is ahead; offer to push it up so the cloud
 *     (and other devices) don't miss data created here.
 *
 * It does NOT auto-sync (data movement stays gated behind an explicit click). It
 * just surfaces the divergence and runs the same non-destructive merge as the
 * Settings button. Mount once near the app root.
 */
export default function SyncNudgeModal() {
  const { token } = useAuth()
  const [info, setInfo] = useState(null)     // { direction, cloudTotal, localTotal, delta }
  const [syncing, setSyncing] = useState(false)

  useEffect(() => {
    const onEvt = (e) => setInfo(e?.detail || { delta: 0, direction: 'cloud-to-local' })
    window.addEventListener('cloud-data-available', onEvt)
    return () => window.removeEventListener('cloud-data-available', onEvt)
  }, [])

  const direction = info?.direction || 'cloud-to-local'
  const isPull = direction === 'cloud-to-local'

  // Running the actual sync → reuse the merge modal in the sensed direction.
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
  const n = info.delta || 0

  return (
    <div style={{ position: 'fixed', inset: 0, zIndex: 9998, background: 'rgba(0,0,0,0.6)', backdropFilter: 'blur(8px)', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
      <div style={{ background: 'var(--bg-2, #1a1a1a)', border: '1px solid var(--border, rgba(255,255,255,0.12))', borderRadius: 16, padding: '26px 30px', width: '100%', maxWidth: 440, boxShadow: '0 24px 80px rgba(0,0,0,0.5)' }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8, fontSize: '1.08rem', fontWeight: 700, color: 'var(--text-primary)', marginBottom: 8 }}>
          <span style={{ display: 'inline-flex', alignItems: 'center', gap: 8 }}>
            <CloudIcon size={18} style={{ color: 'var(--accent)' }} />
            <span>{isPull ? 'Cloud data available' : 'This device has unsynced data'}</span>
          </span>
          <button
            type="button"
            aria-label="Close"
            onClick={() => setInfo(null)}
            style={{ background: 'transparent', border: 'none', color: 'var(--text-muted)', cursor: 'pointer', fontSize: '1.4rem', lineHeight: 1, padding: '0 4px', marginLeft: 8 }}
          >
            ×
          </button>
        </div>
        <div style={{ fontSize: '0.84rem', color: 'var(--text-muted)', lineHeight: 1.55, marginBottom: 18 }}>
          {isPull ? (
            <>
              Your cloud account has {n > 0 ? <strong>{n} record{n === 1 ? '' : 's'}</strong> : 'data'} that {n === 1 ? "isn't" : "aren't"} on this device yet. They won’t appear here until you sync.
              <div style={{ marginTop: 8, opacity: 0.85 }}>
                Bring it down now? (This is a safe merge — nothing on this device is overwritten.)
              </div>
            </>
          ) : (
            <>
              This device has {n > 0 ? <strong>{n} record{n === 1 ? '' : 's'}</strong> : 'data'} that {n === 1 ? "isn't" : "aren't"} on the cloud yet. Your other devices won’t see {n === 1 ? 'it' : 'them'} until you sync.
              <div style={{ marginTop: 8, opacity: 0.85 }}>
                Push it up now? (This is a safe merge — nothing on the cloud is overwritten.)
              </div>
            </>
          )}
        </div>
        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 10 }}>
          <button
            onClick={() => setSyncing(true)}
            style={{ padding: '8px 18px', borderRadius: 8, background: 'var(--accent)', color: '#fff', border: 'none', cursor: 'pointer', fontSize: '0.84rem', fontWeight: 700, display: 'inline-flex', alignItems: 'center', gap: 6 }}
          >
            <SyncIcon size={14} /> {isPull ? 'Sync down now' : 'Sync up now'}
          </button>
        </div>
      </div>
    </div>
  )
}
