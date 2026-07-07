import React, { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../../contexts/AuthContext'
import {
  CloudIcon, DevicesIcon, SyncIcon, SparkleIcon, CheckIcon, ZapIcon,
  ShieldIcon, CloseIcon, PremiumGradientDefs, MonitorIcon
} from '../Icons'

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

  const handleUpgrade = (mode) => {
    dismiss()
    const target = mode === 'cloud' || mode === 'hybrid' ? mode : 'hybrid'
    navigate(`/settings?tab=advanced&switch=${target}`)
  }

  if (!show) return null

  const name = user?.business_name || user?.username || 'there'

  const features = [
    {
      name: "Checkout Performance",
      local: "⚡ Sub-second (Local)",
      hybrid: "⚡ Sub-second (Local)",
      cloud: "🌐 Network Dependent",
      localOk: true,
      hybridOk: true,
      cloudOk: false,
    },
    {
      name: "100% Offline Billing",
      local: "✅ Yes (Free Uptime)",
      hybrid: "✅ Yes (Free Uptime)",
      cloud: "❌ No (Requires Internet)",
      localOk: true,
      hybridOk: true,
      cloudOk: false,
    },
    {
      name: "Automatic Cloud Backup",
      local: "❌ None",
      hybrid: "✅ Yes (Real-time)",
      cloud: "✅ Yes (Direct)",
      localOk: false,
      hybridOk: true,
      cloudOk: true,
    },
    {
      name: "Multi-Device Sync",
      local: "❌ None",
      hybrid: "✅ Yes (Real-time)",
      cloud: "✅ Yes (Instant)",
      localOk: false,
      hybridOk: true,
      cloudOk: true,
    },
    {
      name: "Access from Anywhere",
      local: "❌ Local PC Only",
      hybrid: "✅ Yes (Web + Mobile)",
      cloud: "✅ Yes (Web + Mobile)",
      localOk: false,
      hybridOk: true,
      cloudOk: true,
    },
    {
      name: "AI Advisor & Insights",
      local: "❌ Disabled",
      hybrid: "✅ Full Access",
      cloud: "✅ Full Access",
      localOk: false,
      hybridOk: true,
      cloudOk: true,
    }
  ]

  return (
    <div className="hosting-ob-backdrop" style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', position: 'fixed', inset: 0, zIndex: 9999, background: 'rgba(0,0,0,0.7)', backdropFilter: 'blur(10px)' }}>
      <PremiumGradientDefs />
      <div className="hosting-ob-card" style={{ background: 'var(--bg-2, #181818)', border: '1px solid var(--border, rgba(255,255,255,0.12))', borderRadius: 24, width: '90%', maxWidth: 780, overflow: 'hidden', boxShadow: '0 32px 100px rgba(0,0,0,0.65)', display: 'flex', flexDirection: 'column' }}>

        {/* Header Section */}
        <div style={{ position: 'relative', padding: '32px 40px 24px', textAlign: 'center', borderBottom: '1px solid var(--border, rgba(255,255,255,0.08))' }}>
          <div style={{ position: 'absolute', inset: 0, background: 'var(--grad-premium-soft, rgba(79, 70, 229, 0.05))', pointerEvents: 'none' }} />
          <button
            onClick={dismiss}
            aria-label="Close"
            style={{
              position: 'absolute', top: 18, right: 18, background: 'transparent', border: 'none',
              color: 'var(--text-muted, #888)', cursor: 'pointer', padding: 6, borderRadius: 8, transition: 'all 0.2s'
            }}
            onMouseOver={e => e.currentTarget.style.color = 'var(--text-primary)'}
            onMouseOut={e => e.currentTarget.style.color = 'var(--text-muted)'}
          >
            <CloseIcon size={20} />
          </button>

          <div className="icon-premium-tile" style={{ width: 52, height: 52, marginBottom: 12, marginInline: 'auto' }}>
            <SparkleIcon size={26} strokeWidth={1.8} />
          </div>
          <h2 style={{ fontSize: '1.6rem', fontWeight: 800, color: 'var(--text-primary, #fff)', margin: '0 0 8px', letterSpacing: '-0.01em' }}>
            Welcome to BizAssist, <span className="text-premium">{name}</span>
          </h2>
          <p style={{ color: 'var(--text-muted, #999)', fontSize: '0.92rem', maxWidth: 620, margin: '0 auto', lineHeight: 1.5 }}>
            Choose the perfect hosting mode for your database. You are currently in <strong>Local Mode</strong>. You can upgrade to sync with the cloud or access your data anywhere.
          </p>
        </div>

        {/* Feature Comparison Table */}
        <div style={{ padding: '24px 32px', overflowX: 'auto' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', textAlign: 'left', minWidth: 600 }}>
            <thead>
              <tr style={{ borderBottom: '2px solid var(--border, rgba(255,255,255,0.12))' }}>
                <th style={{ padding: '12px 16px', fontSize: '0.84rem', fontWeight: 700, color: 'var(--text-muted, #888)', width: '30%' }}>DATABASE FEATURE</th>
                <th style={{ padding: '12px 16px', fontSize: '0.84rem', fontWeight: 700, color: 'var(--text-muted, #888)', textAlign: 'center', width: '23%' }}>
                  <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 6 }}>
                    <MonitorIcon size={14} /> Local Mode
                  </div>
                </th>
                <th style={{ padding: '12px 16px', fontSize: '0.84rem', fontWeight: 700, textAlign: 'center', width: '24%', position: 'relative', background: 'rgba(79, 70, 229, 0.08)', borderRadius: '12px 12px 0 0' }}>
                  <div style={{ position: 'absolute', top: -14, left: '50%', transform: 'translateX(-50%)', background: 'var(--accent, #4f46e5)', color: '#fff', fontSize: '0.58rem', fontWeight: 900, padding: '2px 8px', borderRadius: 99, letterSpacing: '0.05em' }}>
                    RECOMMENDED
                  </div>
                  <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 6, color: 'var(--accent, #4f46e5)' }} className="text-premium">
                    <SyncIcon size={14} /> Local + Cloud
                  </div>
                </th>
                <th style={{ padding: '12px 16px', fontSize: '0.84rem', fontWeight: 700, color: 'var(--text-muted, #888)', textAlign: 'center', width: '23%' }}>
                  <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 6 }}>
                    <CloudIcon size={14} /> Cloud Mode
                  </div>
                </th>
              </tr>
            </thead>
            <tbody>
              {features.map((f, i) => (
                <tr key={i} style={{ borderBottom: '1px solid var(--border, rgba(255,255,255,0.06))', background: i % 2 === 1 ? 'rgba(255,255,255,0.01)' : 'transparent' }}>
                  <td style={{ padding: '14px 16px', fontSize: '0.85rem', fontWeight: 600, color: 'var(--text-primary, #fff)' }}>{f.name}</td>
                  
                  {/* Local Cell */}
                  <td style={{ padding: '14px 16px', fontSize: '0.8rem', textAlign: 'center', color: f.localOk ? 'var(--text-secondary, #ccc)' : 'var(--text-muted, #666)' }}>
                    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 6 }}>
                      {f.localOk ? (
                        <CheckIcon size={14} style={{ color: '#22c55e' }} strokeWidth={3} />
                      ) : (
                        <CloseIcon size={14} style={{ color: 'var(--text-muted, #666)' }} strokeWidth={2.5} />
                      )}
                      <span>{f.local}</span>
                    </div>
                  </td>
                  
                  {/* Hybrid Cell (Highlighted Column) */}
                  <td style={{ padding: '14px 16px', fontSize: '0.8rem', textAlign: 'center', background: 'rgba(79, 70, 229, 0.04)', fontWeight: 600, color: 'var(--text-primary, #fff)' }}>
                    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 6 }}>
                      {f.hybridOk ? (
                        <CheckIcon size={14} style={{ color: '#22c55e' }} strokeWidth={3} />
                      ) : (
                        <CloseIcon size={14} style={{ color: 'var(--text-muted, #666)' }} strokeWidth={2.5} />
                      )}
                      <span>{f.hybrid}</span>
                    </div>
                  </td>
                  
                  {/* Cloud Cell */}
                  <td style={{ padding: '14px 16px', fontSize: '0.8rem', textAlign: 'center', color: f.cloudOk ? 'var(--text-secondary, #ccc)' : 'var(--text-muted, #666)' }}>
                    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 6 }}>
                      {f.cloudOk ? (
                        <CheckIcon size={14} style={{ color: '#22c55e' }} strokeWidth={3} />
                      ) : (
                        <CloseIcon size={14} style={{ color: 'var(--text-muted, #666)' }} strokeWidth={2.5} />
                      )}
                      <span>{f.cloud}</span>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {/* Buttons / Actions */}
        <div style={{ padding: '24px 32px', background: 'var(--bg-3, rgba(255,255,255,0.02))', borderTop: '1px solid var(--border, rgba(255,255,255,0.08))', display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 16, flexWrap: 'wrap' }}>
          <button
            onClick={dismiss}
            style={{
              padding: '11px 20px', background: 'transparent',
              border: '1px solid var(--border, rgba(255,255,255,0.15))', color: 'var(--text-secondary, #ccc)',
              borderRadius: 10, cursor: 'pointer', fontWeight: 600, fontSize: '0.86rem', transition: 'all 0.2s'
            }}
            onMouseOver={e => e.currentTarget.style.background = 'rgba(255,255,255,0.05)'}
            onMouseOut={e => e.currentTarget.style.background = 'transparent'}
          >
            Keep Local Only (Free)
          </button>
          
          <div style={{ display: 'flex', gap: 12 }}>
            <button
              onClick={() => handleUpgrade('cloud')}
              style={{
                padding: '11px 20px', background: 'var(--bg-2, #181818)', border: '1px solid var(--border, rgba(255,255,255,0.15))',
                color: 'var(--text-primary, #fff)', borderRadius: 10, cursor: 'pointer', fontWeight: 600, fontSize: '0.86rem',
                display: 'inline-flex', alignItems: 'center', gap: 8, transition: 'all 0.2s'
              }}
              onMouseOver={e => e.currentTarget.style.background = 'rgba(255,255,255,0.05)'}
              onMouseOut={e => e.currentTarget.style.background = 'var(--bg-2)'}
            >
              <CloudIcon size={15} /> Switch to Cloud
            </button>
            <button
              className="btn-premium"
              onClick={() => handleUpgrade('hybrid')}
              style={{
                padding: '11px 26px', borderRadius: 10, cursor: 'pointer', fontWeight: 700, fontSize: '0.86rem',
                display: 'inline-flex', alignItems: 'center', gap: 8, border: 'none'
              }}
            >
              <ZapIcon size={15} /> Try Local + Cloud
            </button>
          </div>
        </div>

        {/* Footer */}
        <div style={{
          display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 8,
          padding: '14px 24px 18px', borderTop: '1px solid var(--border, rgba(255,255,255,0.06))',
          color: 'var(--text-muted, #777)', fontSize: '0.78rem',
        }}>
          <ShieldIcon size={14} />
          <span>Switch hosting mode anytime in Settings → Manage Hosting & Backups. Your data always stays protected.</span>
        </div>

      </div>
    </div>
  )
}
