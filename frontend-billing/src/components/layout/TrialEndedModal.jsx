// ============================================================================
// TrialEndedModal — the web app's screen for a business whose signup Pro trial
// has lapsed. Replaces the generic "Upgrade to Pro Required" lock for them.
//
// Why a screen of its own: a trial owner who never installed the desktop app
// has ALL their data in the cloud. "Upgrade or sign out" would leave them no way
// to it. So this offers the free way first — take a backup file (the export is
// never plan-gated), install the desktop app, restore it there — and upgrading
// second. Presentational: the sign-out and plan re-check live at the call site.
// ============================================================================
import React, { useState } from 'react'
import { DESKTOP_DOWNLOAD_URL } from '../../config/downloadApp'
import { downloadBackupFile } from '../../utils/backupFile'
import { logger } from '../../utils/logger'
import { CloudIcon, DownloadIcon, MonitorIcon } from '../Icons'

const btn = (primary) => ({
  padding: '11px 18px', borderRadius: 10, width: '100%',
  background: primary ? 'linear-gradient(135deg, #6366f1 0%, #4f46e5 100%)' : 'transparent',
  color: primary ? '#fff' : 'var(--text-primary, #fff)',
  border: primary ? 'none' : '1px solid var(--border, rgba(255,255,255,0.15))',
  cursor: 'pointer', fontSize: '0.86rem', fontWeight: 700,
  display: 'inline-flex', alignItems: 'center', justifyContent: 'center', gap: 8,
})

const step = { display: 'flex', gap: 10, alignItems: 'flex-start', fontSize: '0.84rem', lineHeight: 1.5 }
const num = {
  flexShrink: 0, width: 22, height: 22, borderRadius: 999, background: 'rgba(99,102,241,0.18)',
  color: 'var(--text-primary, #fff)', fontSize: '0.74rem', fontWeight: 800,
  display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
}

export default function TrialEndedModal({
  isOwner, token, bizId, onSignOut, onDismiss = null, onCheckPlan, checkingPlan = false,
}) {
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState(null)   // { ok, text }

  const takeBackup = async () => {
    setBusy(true); setMsg(null)
    try {
      const name = await downloadBackupFile({ token, bizId })
      setMsg({ ok: true, text: `Saved as ${name}. Keep it until it is restored in the desktop app.` })
    } catch (err) {
      logger.error('[TRIAL] backup download failed:', err)
      setMsg({ ok: false, text: err.message || 'Backup failed — please try again.' })
    } finally {
      setBusy(false)
    }
  }

  return (
    <div role="dialog" aria-modal="true" aria-labelledby="trial-ended-title" style={{
      position: 'fixed', inset: 0, zIndex: 99999,
      background: 'rgba(15, 23, 42, 0.95)', backdropFilter: 'blur(16px)',
      display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 16,
    }}>
      <div style={{
        background: 'var(--bg-2, #1a1a1a)', border: '1px solid var(--border, rgba(255, 255, 255, 0.12))',
        maxHeight: '92vh', overflowY: 'auto', borderRadius: 20, padding: '32px 32px 28px',
        width: '100%', maxWidth: 520, boxShadow: '0 25px 50px -12px rgba(0, 0, 0, 0.5)',
      }}>
        <h2 id="trial-ended-title" style={{
          fontSize: '1.5rem', fontWeight: 800, color: 'var(--text-primary, #fff)',
          margin: '0 0 10px', letterSpacing: '-0.02em', lineHeight: 1.2,
        }}>
          Your Pro trial has ended
        </h2>
        <p style={{ fontSize: '0.9rem', color: 'var(--text-secondary, #ccc)', lineHeight: 1.6, margin: '0 0 20px' }}>
          Your data is safe. Using BizAssist on the web needs Pro, but billing in the
          desktop app stays free — it works offline and keeps your data on your computer.
        </p>

        {isOwner ? (
          <div style={{
            background: 'rgba(99, 102, 241, 0.08)', border: '1px solid rgba(99, 102, 241, 0.25)',
            borderRadius: 12, padding: 16, marginBottom: 16, color: 'var(--text-primary, #fff)',
            display: 'flex', flexDirection: 'column', gap: 12,
          }}>
            <strong style={{ fontSize: '0.88rem', display: 'inline-flex', alignItems: 'center', gap: 8 }}>
              <MonitorIcon size={16} /> Keep billing for free
            </strong>
            <div style={step}>
              <span style={num}>1</span>
              <div style={{ flex: 1 }}>
                <div style={{ marginBottom: 8 }}>Download a backup file of all your data.</div>
                <button type="button" style={btn(true)} onClick={takeBackup} disabled={busy}>
                  <DownloadIcon size={15} /> {busy ? 'Preparing…' : 'Download backup file'}
                </button>
                {msg && (
                  <div role="status" style={{
                    marginTop: 8, fontSize: '0.78rem',
                    color: msg.ok ? 'var(--success, #22c55e)' : 'var(--danger, #ef4444)',
                  }}>{msg.text}</div>
                )}
              </div>
            </div>
            <div style={step}>
              <span style={num}>2</span>
              <div style={{ flex: 1 }}>
                <div style={{ marginBottom: 8 }}>Install the desktop app on your computer.</div>
                <a href={DESKTOP_DOWNLOAD_URL} target="_blank" rel="noopener noreferrer"
                  style={{ ...btn(false), textDecoration: 'none', boxSizing: 'border-box' }}>
                  Download the desktop app
                </a>
              </div>
            </div>
            <div style={step}>
              <span style={num}>3</span>
              <div>
                In the app, sign in with this account, then open
                {' '}<strong>Settings → Advanced → Restore from file</strong> and pick the backup.
              </div>
            </div>
          </div>
        ) : (
          <div style={{
            background: 'rgba(99, 102, 241, 0.08)', border: '1px solid rgba(99, 102, 241, 0.25)',
            borderRadius: 12, padding: 16, marginBottom: 16, fontSize: '0.84rem',
            color: 'var(--text-primary, #fff)', lineHeight: 1.55,
          }}>
            Ask the business owner to move the books to the desktop app, or to activate Pro.
          </div>
        )}

        <div style={{
          border: '1px solid var(--border, rgba(255,255,255,0.12))', borderRadius: 12,
          padding: 16, marginBottom: 20, fontSize: '0.84rem', color: 'var(--text-secondary, #ccc)', lineHeight: 1.55,
        }}>
          <strong style={{ color: 'var(--text-primary, #fff)', display: 'inline-flex', alignItems: 'center', gap: 8, marginBottom: 6 }}>
            <CloudIcon size={16} /> Keep Pro
          </strong>
          <div style={{ marginBottom: 10 }}>
            Web access, cloud sync, AI and Field Team come back as soon as your provider
            activates Pro. Already done? Check again.
          </div>
          <button type="button" style={btn(false)} onClick={onCheckPlan} disabled={checkingPlan}>
            {checkingPlan ? 'Checking…' : 'Check my plan again'}
          </button>
        </div>

        <div style={{ display: 'flex', gap: 10 }}>
          {onDismiss && (
            <button type="button" style={btn(false)} onClick={onDismiss}>
              Look around first
            </button>
          )}
          <button type="button" style={btn(false)} onClick={onSignOut}>
            Sign out
          </button>
        </div>
      </div>
    </div>
  )
}
