import React, { useEffect, useState } from 'react'
import { IS_LOCAL_APP } from '../../config'
import { useAuth } from '../../contexts/AuthContext'
import { CloudIcon, MonitorIcon } from '../Icons'

/**
 * WebLocalOnlyNotice — shown ONLY on the web app (browser URL), and only for a
 * free / Local-only account (profile.is_premium === false).
 *
 * Why: at signup every account is mirrored to the cloud for its BizID, but a
 * Local-only account never pushes its DATA up. So such a user can log in on the
 * web (their identity exists on cloud) and land in an EMPTY app — the classic
 * "where did my data go?!" panic. Instead of a blank dashboard we explain that
 * their data lives on the desktop device they used, and offer the upgrade path.
 *
 * Non-blocking: the user can dismiss it (a genuinely brand-new web signup can
 * carry on). Shown once per browser session so it never nags. The desktop app
 * (IS_LOCAL_APP) never renders this — it has the data locally.
 */
export default function WebLocalOnlyNotice() {
  const { profile, settings } = useAuth()
  const [dismissed, setDismissed] = useState(false)

  useEffect(() => {
    try {
      if (sessionStorage.getItem('bizassist_web_localonly_dismissed') === '1') {
        setDismissed(true)
      }
    } catch { /* sessionStorage may be unavailable — show the notice */ }
  }, [])

  // Only on the web, only once profile is loaded, only for non-premium accounts.
  // (Before the backend exposes is_premium, this is undefined → notice stays
  //  hidden, so it can never false-fire during rollout.)
  if (IS_LOCAL_APP) return null
  if (dismissed) return null
  // A hybrid/cloud account DOES push its data to the cloud, so the web view is
  // NOT empty for them — never show the "your data is on your desktop" notice,
  // regardless of premium. Only a genuinely Local-only account lands here.
  const hostingMode = settings?.general?.hosting_mode
  if (hostingMode === 'hybrid' || hostingMode === 'cloud') return null
  if (!profile || profile.is_premium !== false) return null

  const dismiss = () => {
    try { sessionStorage.setItem('bizassist_web_localonly_dismissed', '1') } catch { /* ignore */ }
    setDismissed(true)
  }

  return (
    <div style={{ position: 'fixed', inset: 0, zIndex: 9997, background: 'rgba(0,0,0,0.6)', backdropFilter: 'blur(8px)', display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 24 }}>
      <div style={{ background: 'var(--bg-2, #1a1a1a)', border: '1px solid var(--border, rgba(255,255,255,0.12))', borderRadius: 16, padding: '28px 32px', width: '100%', maxWidth: 480, boxShadow: '0 24px 80px rgba(0,0,0,0.5)' }}>
        <div style={{ display: 'inline-flex', alignItems: 'center', gap: 10, fontSize: '1.12rem', fontWeight: 800, color: 'var(--text-primary)', marginBottom: 12 }}>
          <MonitorIcon size={20} style={{ color: 'var(--accent)' }} />
          <span>Your data is on your desktop</span>
        </div>

        <p style={{ fontSize: '0.9rem', color: 'var(--text-secondary)', lineHeight: 1.6, margin: '0 0 14px 0' }}>
          This is a <strong>Local-only</strong> account, so your invoices, stock and reports are stored on the device you use — not on the cloud. That's why this web view looks empty.
        </p>

        {/* The requested note — explicit and unmissable. */}
        <div style={{ background: 'rgba(99,102,241,0.08)', border: '1px solid rgba(99,102,241,0.3)', borderRadius: 8, padding: '12px 14px', fontSize: '0.85rem', color: 'var(--text-primary)', lineHeight: 1.55, marginBottom: 18 }}>
          <strong>Note:</strong> Please log in from the local device you used earlier — your data is present only on that local device.
        </div>

        <p style={{ fontSize: '0.82rem', color: 'var(--text-muted)', lineHeight: 1.55, margin: '0 0 20px 0', display: 'flex', alignItems: 'flex-start', gap: 8 }}>
          <CloudIcon size={16} style={{ flexShrink: 0, marginTop: 2, color: 'var(--accent)' }} />
          <span>Want to reach your data from anywhere? Switch that desktop app to <strong>Local + Cloud</strong> (Settings → Hosting &amp; Sync). It keeps billing fast and offline while syncing everything to the cloud so it shows up here too.</span>
        </p>

        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 10 }}>
          <button
            onClick={dismiss}
            style={{ padding: '9px 18px', borderRadius: 8, background: 'transparent', color: 'var(--text-secondary)', border: '1px solid var(--border, rgba(255,255,255,0.15))', cursor: 'pointer', fontSize: '0.85rem', fontWeight: 600 }}
          >
            Continue on web
          </button>
        </div>
      </div>
    </div>
  )
}
