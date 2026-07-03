import React, { useEffect, useState } from 'react'
import { useAuth } from '../../contexts/AuthContext'
import { CloudIcon, DevicesIcon, LockIcon, SyncIcon, SparkleIcon } from '../Icons'

export default function HostingOnboardingModal() {
  const { user, settings, switchMode } = useAuth()
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
    // Dismiss and trigger the actual mode switch for testing
    dismiss()
    switchMode(mode)
  }

  if (!show) return null

  return (
    <div style={{ position: 'fixed', inset: 0, zIndex: 9999, background: 'rgba(0,0,0,0.5)', backdropFilter: 'blur(4px)', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
      <div className="slide-up" style={{ background: 'var(--bg, #ffffff)', border: '1px solid var(--border)', borderRadius: 16, padding: '32px', width: '100%', maxWidth: 700, boxShadow: '0 24px 80px rgba(0,0,0,0.2)' }}>
        <div style={{ textAlign: 'center', marginBottom: 24 }}>
          <h2 style={{ fontSize: '1.5rem', fontWeight: 800, color: 'var(--text-primary)', marginBottom: 8 }}>Choose Your Workspace Setup</h2>
          <p style={{ color: 'var(--text-muted)', fontSize: '0.95rem' }}>Select how you want BizAssist to manage your data across devices.</p>
        </div>

        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: '16px', marginBottom: '24px' }}>
          
          {/* LOCAL (Current) */}
          <div style={{ border: '2px solid var(--accent)', borderRadius: 12, padding: '20px', display: 'flex', flexDirection: 'column', position: 'relative', background: 'var(--accent-dim, rgba(193, 95, 60, 0.05))' }}>
            <div style={{ position: 'absolute', top: -12, left: '50%', transform: 'translateX(-50%)', background: 'var(--accent)', color: '#fff', fontSize: '0.7rem', fontWeight: 700, padding: '2px 10px', borderRadius: 12 }}>
              CURRENT
            </div>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', marginBottom: 12, color: 'var(--accent)' }}>
              <DevicesIcon size={32} />
            </div>
            <h3 style={{ textAlign: 'center', fontSize: '1.1rem', marginBottom: 8, color: 'var(--text-primary)' }}>Local Mode</h3>
            <p style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', textAlign: 'center', flex: 1 }}>Free forever. Fast offline billing. Data is stored only on this device.</p>
            <button onClick={dismiss} style={{ marginTop: 16, padding: '8px', background: 'transparent', border: '1px solid var(--accent)', color: 'var(--accent)', borderRadius: 8, cursor: 'pointer', fontWeight: 600 }}>
              Keep Local
            </button>
          </div>

          {/* CLOUD (Premium) */}
          <div style={{ border: '1px solid var(--border)', borderRadius: 12, padding: '20px', display: 'flex', flexDirection: 'column', position: 'relative' }}>
            <div style={{ position: 'absolute', top: -12, left: '50%', transform: 'translateX(-50%)', background: 'rgba(224, 242, 254, 0.9)', backdropFilter: 'blur(4px)', color: '#0369a1', fontSize: '0.7rem', fontWeight: 700, padding: '2px 10px', borderRadius: 12, display: 'flex', alignItems: 'center', gap: 4, border: '1px solid #bae6fd' }}>
              <LockIcon size={12} /> PREMIUM
            </div>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', marginBottom: 12, color: '#0ea5e9' }}>
              <CloudIcon size={32} />
            </div>
            <h3 style={{ textAlign: 'center', fontSize: '1.1rem', marginBottom: 8, color: 'var(--text-primary)' }}>Cloud Mode</h3>
            <p style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', textAlign: 'center', flex: 1 }}>Sync across multiple devices in real-time. Secure cloud backups.</p>
            <button onClick={() => handleUpgrade('cloud')} style={{ marginTop: 16, padding: '8px', background: '#0ea5e9', border: 'none', color: '#fff', borderRadius: 8, cursor: 'pointer', fontWeight: 600 }}>
              Try Cloud
            </button>
          </div>

          {/* HYBRID (Premium) */}
          <div style={{ border: '1px solid var(--border)', borderRadius: 12, padding: '20px', display: 'flex', flexDirection: 'column', position: 'relative' }}>
            <div style={{ position: 'absolute', top: -12, left: '50%', transform: 'translateX(-50%)', background: 'rgba(224, 242, 254, 0.9)', backdropFilter: 'blur(4px)', color: '#0369a1', fontSize: '0.7rem', fontWeight: 700, padding: '2px 10px', borderRadius: 12, display: 'flex', alignItems: 'center', gap: 4, border: '1px solid #bae6fd' }}>
              <SparkleIcon size={12} /> BEST VALUE
            </div>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', marginBottom: 12, color: '#0ea5e9' }}>
              <SyncIcon size={32} />
            </div>
            <h3 style={{ textAlign: 'center', fontSize: '1.1rem', marginBottom: 8, color: 'var(--text-primary)' }}>Hybrid Mode</h3>
            <p style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', textAlign: 'center', flex: 1 }}>Ultra-fast offline billing + seamless background cloud sync.</p>
            <button onClick={() => handleUpgrade('hybrid')} style={{ marginTop: 16, padding: '8px', background: '#0ea5e9', border: 'none', color: '#fff', borderRadius: 8, cursor: 'pointer', fontWeight: 600 }}>
              Try Hybrid
            </button>
          </div>
          
        </div>

      </div>
    </div>
  )
}
