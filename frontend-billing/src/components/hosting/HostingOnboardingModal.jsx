import React, { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../../contexts/AuthContext'
import {
  CloudIcon, DevicesIcon, SyncIcon, SparkleIcon, CheckIcon, ZapIcon,
  ShieldIcon, CloseIcon, PremiumGradientDefs,
} from '../Icons'

/**
 * HostingOnboardingModal — first-run welcome for LOCAL users.
 * Left: where they are (Local). Divider. Right: what switching unlocks
 * (Hybrid / Cloud) dressed in the global premium gradient
 * (--grad-premium / .btn-premium / .icon-premium — see index.css).
 */

function Check({ children, premium = false }) {
  return (
    <li className="hosting-ob-check" style={{ listStyle: 'none' }}>
      <span style={{ flexShrink: 0, marginTop: 1, color: premium ? 'inherit' : 'var(--success)' }}>
        <CheckIcon size={15} strokeWidth={2.5} className={premium ? 'icon-premium' : ''} />
      </span>
      <span>{children}</span>
    </li>
  )
}

export default function HostingOnboardingModal() {
  const { user, settings } = useAuth()
  const navigate = useNavigate()
  const [show, setShow] = useState(false)

  useEffect(() => {
    if (!user || !settings) return

    // Only show if the current mode is local and hasn't been seen
    const currentMode = settings?.general?.hosting_mode || 'local'
    if (currentMode !== 'local') return

    const seenKey = `bizassist_hosting_onboarding_seen_${user.id}`
    if (!localStorage.getItem(seenKey)) {
      setShow(true)
    }
  }, [user, settings])

  const dismiss = () => {
    const seenKey = `bizassist_hosting_onboarding_seen_${user.id}`
    localStorage.setItem(seenKey, '1')
    setShow(false)
  }

  /**
   * Don't hard-switch from here — switching backends requires the guarded
   * flow in Settings → Advanced (connection checks, preflight checklist,
   * consequence warning, migration) and forces a re-login by design.
   * Send the user there instead.
   */
  const handleUpgrade = () => {
    dismiss()
    navigate('/settings?tab=advanced')
  }

  if (!show) return null

  const name = user?.business_name || user?.username || 'there'

  return (
    <div className="hosting-ob-backdrop">
      <PremiumGradientDefs />
      <div className="hosting-ob-card">

        {/* ── Hero greeting ─────────────────────────────────────────────── */}
        <div style={{ position: 'relative', padding: '36px 40px 28px', textAlign: 'center', overflow: 'hidden' }}>
          {/* soft gradient wash behind the greeting */}
          <div style={{ position: 'absolute', inset: 0, background: 'var(--grad-premium-soft)', pointerEvents: 'none' }} />
          <button
            onClick={dismiss}
            aria-label="Close"
            style={{
              position: 'absolute', top: 14, right: 14, background: 'transparent', border: 'none',
              color: 'var(--text-muted)', cursor: 'pointer', padding: 6, borderRadius: 8,
            }}
          >
            <CloseIcon size={18} />
          </button>

          <div className="icon-premium-tile" style={{ width: 56, height: 56, marginBottom: 14 }}>
            <SparkleIcon size={28} strokeWidth={1.8} />
          </div>
          <h2 style={{ fontSize: '1.75rem', fontWeight: 800, color: 'var(--text-primary)', margin: '0 0 8px', letterSpacing: '-0.01em' }}>
            Welcome to BizAssist, <span className="text-premium">{name}</span>
          </h2>
          <p style={{ color: 'var(--text-muted)', fontSize: '0.98rem', maxWidth: 560, margin: '0 auto', lineHeight: 1.5 }}>
            You're all set for sub-second offline billing, GST-ready invoices, live inventory
            and shift-wise cash tallies. One choice left — where should your data live?
          </p>
        </div>

        {/* ── Split: LOCAL │ PREMIUM ────────────────────────────────────── */}
        <div className="hosting-ob-grid">

          {/* LEFT — Local (current) */}
          <div style={{ padding: '28px 32px 32px', display: 'flex', flexDirection: 'column' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 6 }}>
              <span style={{
                display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
                width: 44, height: 44, borderRadius: 12,
                background: 'var(--accent-dim)', color: 'var(--accent)',
              }}>
                <DevicesIcon size={24} />
              </span>
              <div>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <h3 style={{ fontSize: '1.15rem', fontWeight: 800, color: 'var(--text-primary)', margin: 0 }}>Local Mode</h3>
                  <span style={{
                    background: 'var(--accent)', color: '#fff', fontSize: '0.62rem', fontWeight: 800,
                    letterSpacing: '0.06em', padding: '3px 9px', borderRadius: 999,
                  }}>
                    YOU'RE HERE
                  </span>
                </div>
                <span style={{ fontSize: '0.78rem', color: 'var(--text-muted)' }}>Free forever</span>
              </div>
            </div>

            <ul style={{ display: 'flex', flexDirection: 'column', gap: 11, padding: 0, margin: '18px 0 0' }}>
              <Check><strong>Sub-second billing</strong> — the engine runs on this machine</Check>
              <Check><strong>100% offline</strong> — no internet needed, ever</Check>
              <Check><strong>Total privacy</strong> — data never leaves this device</Check>
              <Check><strong>Every core feature</strong> — invoices, inventory, dues, GST reports</Check>
            </ul>

            <div style={{ flex: 1 }} />
            <button
              onClick={dismiss}
              style={{
                marginTop: 24, padding: '11px 18px', background: 'transparent',
                border: '1.5px solid var(--accent)', color: 'var(--accent)',
                borderRadius: 8, cursor: 'pointer', fontWeight: 700, fontSize: '0.9rem',
              }}
            >
              Keep Local — I'm good
            </button>
          </div>

          {/* divider line */}
          <div className="hosting-ob-divider" />

          {/* RIGHT — Hybrid / Cloud (premium gradient) */}
          <div style={{
            padding: '28px 32px 32px', display: 'flex', flexDirection: 'column',
            background: 'var(--grad-premium-soft)', borderRadius: '0 0 20px 0',
          }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 6 }}>
              <span className="icon-premium-tile" style={{ width: 44, height: 44 }}>
                <SyncIcon size={24} />
              </span>
              <div>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <h3 style={{ fontSize: '1.15rem', fontWeight: 800, margin: 0 }} className="text-premium">Hybrid & Cloud</h3>
                  <span className="badge-premium"><SparkleIcon size={11} /> BEST VALUE</span>
                </div>
                <span style={{ fontSize: '0.78rem', color: 'var(--text-muted)' }}>Everything in Local, plus superpowers</span>
              </div>
            </div>

            <ul style={{ display: 'flex', flexDirection: 'column', gap: 11, padding: 0, margin: '18px 0 0' }}>
              <Check premium><strong>Automatic cloud backup</strong> — every invoice, safe the moment it's made</Check>
              <Check premium><strong>Multi-device sync</strong> — counters, phone and office always agree</Check>
              <Check premium><strong>Access anywhere</strong> — check today's sales from home</Check>
              <Check premium><strong>Disaster-proof</strong> — new machine? Restore in minutes</Check>
            </ul>

            <div style={{ flex: 1 }} />
            <div style={{ display: 'flex', gap: 10, marginTop: 24 }}>
              <button className="btn-premium" style={{ flex: 1, fontSize: '0.9rem' }} onClick={() => handleUpgrade('hybrid')}>
                <ZapIcon size={15} /> Try Hybrid
              </button>
              <button
                onClick={() => handleUpgrade('cloud')}
                style={{
                  flex: 1, display: 'inline-flex', alignItems: 'center', justifyContent: 'center', gap: 8,
                  padding: '10px 18px', background: 'var(--bg-2, #fff)', border: '1.5px solid #4f46e5',
                  color: '#4f46e5', borderRadius: 8, cursor: 'pointer', fontWeight: 700, fontSize: '0.9rem',
                }}
              >
                <CloudIcon size={15} /> Try Cloud
              </button>
            </div>
          </div>
        </div>

        {/* ── Footer note ───────────────────────────────────────────────── */}
        <div style={{
          display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 8,
          padding: '14px 24px 18px', borderTop: '1px solid var(--border)',
          color: 'var(--text-muted)', fontSize: '0.78rem',
        }}>
          <ShieldIcon size={14} />
          Switch anytime — Settings → Manage Hosting & Backups. Your data moves with you, never without you.
        </div>

      </div>
    </div>
  )
}
