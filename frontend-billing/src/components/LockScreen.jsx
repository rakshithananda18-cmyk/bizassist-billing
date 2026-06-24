// src/components/LockScreen.jsx
// ============================================================
// Full-screen lock overlay shown when the session is locked.
// • Non-dismissable: no ESC, no click-outside, no backdrop close.
// • Always offers "Sign Out" as a PIN-reset escape hatch.
// • Animated entry (slide-up + fade).
// ============================================================
import React, { useState, useEffect, useRef } from 'react'
import { createPortal } from 'react-dom'
import { useLock } from '../contexts/LockContext'
import { useAuth } from '../contexts/AuthContext'
import { useNavigate } from 'react-router-dom'
import { BuildingMark } from './Logo'
import { LockIcon } from './Icons'
import { logger } from '../utils/logger'

export default function LockScreen() {
  const { isLocked, hasLock, unlock } = useLock()
  const { user, logout }              = useAuth()
  const navigate = useNavigate()

  const [pin,      setPin]      = useState('')
  const [error,    setError]    = useState('')
  const [shaking,  setShaking]  = useState(false)
  const [checking, setChecking] = useState(false)
  const inputRef = useRef(null)

  // Focus input whenever lock screen appears
  useEffect(() => {
    if (isLocked && hasLock) {
      setTimeout(() => inputRef.current?.focus(), 120)
    }
  }, [isLocked, hasLock])

  // Clear error when user starts typing again
  useEffect(() => { if (pin) setError('') }, [pin])

  // Prevent body scroll while locked
  useEffect(() => {
    if (isLocked && hasLock) {
      const prev = document.body.style.overflow
      document.body.style.overflow = 'hidden'
      return () => { document.body.style.overflow = prev }
    }
  }, [isLocked, hasLock])

  if (!isLocked || !hasLock) return null

  const handleUnlock = async (e) => {
    e?.preventDefault()
    if (!pin.trim() || checking) return
    setChecking(true)
    const ok = await unlock(pin)
    setChecking(false)
    if (ok) {
      setPin('')
      setError('')
    } else {
      setError('Incorrect passcode. Try again.')
      setShaking(true)
      setPin('')
      setTimeout(() => setShaking(false), 500)
      inputRef.current?.focus()
      logger.warn('[LOCK] Incorrect PIN entered')
    }
  }

  const handleSignOut = () => {
    if (window.confirm('Sign out? Your session will end and the passcode will be reset on next login.')) {
      logout()
      navigate('/login')
      logger.info('[LOCK] User signed out from lock screen')
    }
  }

  return createPortal(
    <div
      role="dialog"
      aria-modal="true"
      aria-label="Session locked"
      onMouseDown={(e) => e.stopPropagation()}
      onTouchStart={(e) => e.stopPropagation()}
      onKeyDown={(e) => {
        // Only allow typing in the input — block all nav shortcuts
        if (e.key === 'Escape') e.preventDefault()
      }}
      style={{
        position: 'fixed',
        inset: 0,
        zIndex: 99999,
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        background: 'var(--bg-1, #0f1117)',
        animation: 'fadeIn 200ms ease',
      }}
    >
      {/* Subtle grid pattern */}
      <div style={{
        position: 'absolute', inset: 0, opacity: 0.03,
        backgroundImage: 'linear-gradient(var(--border,#1e2535) 1px,transparent 1px),linear-gradient(90deg,var(--border,#1e2535) 1px,transparent 1px)',
        backgroundSize: '40px 40px',
        pointerEvents: 'none',
      }} />

      <div
        style={{
          position: 'relative',
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          gap: 24,
          padding: '40px 36px',
          width: '100%',
          maxWidth: 380,
          background: 'var(--bg-2, #161b27)',
          border: '1px solid var(--border, #1e2535)',
          borderRadius: 'var(--radius-xl, 20px)',
          boxShadow: '0 32px 80px rgba(0,0,0,0.6)',
          animation: 'slideUp 220ms cubic-bezier(.22,.61,.36,1)',
        }}
      >
        {/* Logo + brand */}
        <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 10 }}>
          <div style={{ color: 'var(--accent, #C2714F)', opacity: 0.9 }}>
            <BuildingMark size={44} />
          </div>
          <div style={{ textAlign: 'center' }}>
            <div style={{ fontSize: '1.1rem', fontWeight: 700, color: 'var(--text-primary, #f1f5f9)', letterSpacing: '-0.01em' }}>
              {user?.business_name || 'BizAssist'}
            </div>
            <div style={{ fontSize: '0.8rem', color: 'var(--text-muted, #64748b)', marginTop: 2 }}>
              Session Locked · {user?.username}
            </div>
          </div>
        </div>

        {/* Lock icon */}
        <div style={{
          width: 56, height: 56, borderRadius: '50%',
          background: 'var(--bg-3, #1a2035)',
          border: '1px solid var(--border, #1e2535)',
          display: 'flex', alignItems: 'center', justifyContent: 'center',
        }}>
          <LockIcon size={24} style={{ color: 'var(--accent, #C2714F)' }} />
        </div>

        {/* PIN input form */}
        <form
          onSubmit={handleUnlock}
          style={{ width: '100%', display: 'flex', flexDirection: 'column', gap: 12 }}
        >
          <label style={{ fontSize: '0.8rem', color: 'var(--text-muted, #64748b)', textAlign: 'center' }}>
            Enter your passcode to continue
          </label>

          <input
            ref={inputRef}
            type="password"
            value={pin}
            onChange={e => setPin(e.target.value)}
            placeholder="Passcode"
            autoComplete="current-password"
            style={{
              width: '100%',
              padding: '12px 16px',
              background: 'var(--bg-3, #1a2035)',
              border: `1px solid ${error ? 'var(--danger, #ef4444)' : 'var(--border, #1e2535)'}`,
              borderRadius: 'var(--radius-md, 10px)',
              color: 'var(--text-primary, #f1f5f9)',
              fontSize: '1rem',
              outline: 'none',
              textAlign: 'center',
              letterSpacing: '0.2em',
              transition: 'border-color 0.2s',
              animation: shaking ? 'lockShake 0.45s ease' : undefined,
              boxSizing: 'border-box',
            }}
            onKeyDown={e => { if (e.key === 'Enter') handleUnlock() }}
          />

          {error && (
            <div style={{
              fontSize: '0.78rem',
              color: 'var(--danger, #ef4444)',
              textAlign: 'center',
              animation: 'fadeIn 150ms ease',
            }}>
              {error}
            </div>
          )}

          <button
            type="submit"
            disabled={!pin.trim() || checking}
            style={{
              padding: '11px 0',
              borderRadius: 'var(--radius-md, 10px)',
              background: 'var(--accent, #C2714F)',
              color: '#fff',
              fontWeight: 700,
              fontSize: '0.9rem',
              border: 'none',
              cursor: !pin.trim() || checking ? 'not-allowed' : 'pointer',
              opacity: !pin.trim() || checking ? 0.55 : 1,
              transition: 'opacity 0.2s',
              width: '100%',
            }}
          >
            {checking ? 'Checking…' : 'Unlock'}
          </button>
        </form>

        {/* Sign out escape hatch */}
        <div style={{ borderTop: '1px solid var(--border, #1e2535)', paddingTop: 16, width: '100%', textAlign: 'center' }}>
          <button
            type="button"
            onClick={handleSignOut}
            style={{
              background: 'none',
              border: 'none',
              color: 'var(--text-muted, #64748b)',
              fontSize: '0.8rem',
              cursor: 'pointer',
              textDecoration: 'underline',
              padding: 0,
            }}
          >
            Forgot passcode? Sign out instead
          </button>
        </div>
      </div>

      {/* Shake keyframe for wrong PIN */}
      <style>{`
        @keyframes lockShake {
          0%,100% { transform: translateX(0); }
          15%      { transform: translateX(-8px); }
          30%      { transform: translateX(8px); }
          45%      { transform: translateX(-6px); }
          60%      { transform: translateX(6px); }
          75%      { transform: translateX(-3px); }
          90%      { transform: translateX(3px); }
        }
      `}</style>
    </div>,
    document.body,
  )
}
