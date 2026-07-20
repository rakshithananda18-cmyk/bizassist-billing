// ============================================================================
// SessionExpiredModal — the "Upgrade to Pro Required" full-screen overlay,
// extracted verbatim from layouts/AppLayout.jsx (repo restructure).
// Presentational: the sign-out side effects stay at the call site.
// ============================================================================
import React from 'react'
import { LockIcon } from '../Icons'

export default function SessionExpiredModal({ onSignOut }) {
  return (
    <div style={{
      position: 'fixed',
      inset: 0,
      zIndex: 99999,
      background: 'rgba(15, 23, 42, 0.95)',
      backdropFilter: 'blur(16px)',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      padding: 24,
    }}>
      <div style={{
        background: 'var(--bg-2, #1a1a1a)',
        border: '1px solid var(--border, rgba(255, 255, 255, 0.12))',
        borderRadius: 24,
        padding: '40px 48px',
        width: '100%',
        maxWidth: 500,
        boxShadow: '0 25px 50px -12px rgba(0, 0, 0, 0.5)',
        textAlign: 'center',
      }}>
        <div style={{
          width: 80,
          height: 80,
          borderRadius: '50%',
          background: 'linear-gradient(135deg, #6366f1 0%, #4f46e5 100%)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          margin: '0 auto 24px',
          boxShadow: '0 8px 30px rgba(99, 102, 241, 0.3)'
        }}>
          <LockIcon size={40} style={{ color: '#fff' }} />
        </div>

        <h2 style={{
          fontSize: '1.75rem',
          fontWeight: 800,
          color: 'var(--text-primary, #fff)',
          marginBottom: 16,
          letterSpacing: '-0.02em',
          lineHeight: 1.2
        }}>
          Upgrade to Pro Required
        </h2>

        <p style={{
          fontSize: '0.94rem',
          color: 'var(--text-secondary, #ccc)',
          lineHeight: 1.6,
          marginBottom: 24
        }}>
          Your 5-minute preview of the cloud application has expired. Access to the shared cloud database, multi-device sync, and premium features require a Pro subscription.
        </p>

        <div style={{
          background: 'rgba(99, 102, 241, 0.08)',
          border: '1px solid rgba(99, 102, 241, 0.25)',
          borderRadius: 12,
          padding: '16px',
          fontSize: '0.84rem',
          color: 'var(--text-primary, #fff)',
          lineHeight: 1.5,
          marginBottom: 28,
          textAlign: 'left'
        }}>
          <strong>Want to upgrade?</strong> Contact your provider or system administrator to activate the <strong>Pro Plan</strong> and resume work.
        </div>

        <div style={{
          display: 'flex',
          flexDirection: 'column',
          gap: 12
        }}>
          <button
            onClick={onSignOut}
            style={{
              padding: '14px 28px',
              borderRadius: 12,
              background: 'linear-gradient(135deg, #6366f1 0%, #4f46e5 100%)',
              color: '#fff',
              border: 'none',
              cursor: 'pointer',
              fontSize: '0.9rem',
              fontWeight: 700,
              boxShadow: '0 4px 14px rgba(99, 102, 241, 0.4)',
              transition: 'all 0.2s',
              width: '100%'
            }}
          >
            Sign Out
          </button>
        </div>
      </div>
    </div>
  )
}
