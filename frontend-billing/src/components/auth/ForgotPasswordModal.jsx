/**
 * components/auth/ForgotPasswordModal.jsx
 * Multi-step account recovery modal via 6-digit OTP (Brevo email / SMS).
 */
import React, { useState } from 'react'
import { API_BASE } from '../../config'
import { EyeIcon, EyeOffIcon } from '../Icons'

export default function ForgotPasswordModal({ isOpen, onClose, onSuccess }) {
  const [step, setStep] = useState(1) // 1: request, 2: verify
  const [identifier, setIdentifier] = useState('')
  const [otp, setOtp] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [showPassword, setShowPassword] = useState(false)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [info, setInfo] = useState('')
  const [destHint, setDestHint] = useState('')
  const [unameHint, setUnameHint] = useState('')

  if (!isOpen) return null

  const handleRequestOtp = async (e) => {
    e.preventDefault()
    setError('')
    setInfo('')
    if (!identifier.trim()) {
      setError('Please enter your phone number, username, or email.')
      return
    }

    setLoading(true)
    try {
      const res = await fetch(`${API_BASE}/api/auth/forgot-password/request-otp`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ identifier: identifier.trim() }),
      })
      const data = await res.json()
      if (!res.ok) {
        throw new Error(data?.detail || 'Failed to send verification code.')
      }

      setDestHint(data.destination || 'your registered contact')
      setUnameHint(data.username_hint || '')
      setInfo(data.message || 'Verification code sent.')
      setStep(2)
    } catch (err) {
      setError(err?.message || 'Error communicating with server.')
    } finally {
      setLoading(false)
    }
  }

  const handleVerifyAndReset = async (e) => {
    e.preventDefault()
    setError('')
    if (!otp.trim() || otp.trim().length !== 6) {
      setError('Please enter the 6-digit verification code.')
      return
    }
    if (!newPassword || newPassword.length < 8) {
      setError('New password must be at least 8 characters long.')
      return
    }

    setLoading(true)
    try {
      const res = await fetch(`${API_BASE}/api/auth/forgot-password/verify-and-reset`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          identifier: identifier.trim(),
          otp: otp.trim(),
          new_password: newPassword,
        }),
      })
      const data = await res.json()
      if (!res.ok) {
        throw new Error(data?.detail || 'Failed to verify code and reset password.')
      }

      if (onSuccess) {
        onSuccess(data)
      }
      onClose()
    } catch (err) {
      setError(err?.message || 'Failed to reset password.')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div style={{
      position: 'fixed',
      inset: 0,
      backgroundColor: 'rgba(0, 0, 0, 0.75)',
      backdropFilter: 'blur(6px)',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      zIndex: 9999,
      padding: 16,
    }}>
      <div style={{
        backgroundColor: 'var(--bg-card, #181b22)',
        border: '1.5px solid var(--border, #2d3343)',
        borderRadius: 16,
        maxWidth: 440,
        width: '100%',
        padding: '24px 28px',
        boxShadow: '0 20px 40px rgba(0,0,0,0.6)',
        position: 'relative',
        color: 'var(--text-primary, #e5e7eb)',
      }}>
        {/* Close Button */}
        <button
          type="button"
          onClick={onClose}
          style={{
            position: 'absolute',
            top: 16,
            right: 16,
            background: 'none',
            border: 'none',
            color: 'var(--text-muted, #9ca3af)',
            fontSize: 20,
            cursor: 'pointer',
            lineHeight: 1,
          }}
        >
          ✕
        </button>

        <div style={{ marginBottom: 18 }}>
          <h2 style={{ fontSize: '1.18rem', fontWeight: 800, margin: 0, color: 'var(--text-primary)' }}>
            {step === 1 ? 'Find Store / Reset Password' : 'Enter Verification Code'}
          </h2>
          <p style={{ fontSize: '0.82rem', color: 'var(--text-secondary, #9ca3af)', marginTop: 6, lineHeight: 1.45 }}>
            {step === 1
              ? 'Enter your registered mobile number, username, or email to receive a 6-digit recovery code.'
              : `Code sent to ${destHint}. Enter it below along with your new password.`}
          </p>
        </div>

        {error && (
          <div style={{
            background: 'rgba(239, 68, 68, 0.15)',
            border: '1px solid #ef4444',
            borderRadius: 8,
            color: '#f87171',
            padding: '8px 12px',
            fontSize: '0.78rem',
            marginBottom: 14,
          }}>
            {error}
          </div>
        )}

        {info && step === 2 && (
          <div style={{
            background: 'rgba(245, 158, 11, 0.12)',
            border: '1px solid rgba(245, 158, 11, 0.4)',
            borderRadius: 8,
            color: '#fbbf24',
            padding: '8px 12px',
            fontSize: '0.78rem',
            marginBottom: 14,
          }}>
            {info}
            {unameHint && <div><strong>Store Username:</strong> {unameHint}</div>}
          </div>
        )}

        {step === 1 && (
          <form onSubmit={handleRequestOtp}>
            <div style={{ marginBottom: 16 }}>
              <label htmlFor="recovery-identifier" style={{ display: 'block', fontSize: '0.8rem', fontWeight: 600, marginBottom: 6 }}>
                Phone Number, Username, or Email
              </label>
              <input
                id="recovery-identifier"
                type="text"
                placeholder="e.g. 9876543210 or ramesh_mart"
                value={identifier}
                onChange={(e) => setIdentifier(e.target.value)}
                required
                autoFocus
                style={{
                  width: '100%',
                  boxSizing: 'border-box',
                  padding: '10px 14px',
                  borderRadius: 10,
                  border: '1.5px solid var(--border)',
                  background: 'var(--bg-2, #111318)',
                  color: 'inherit',
                  fontSize: '0.88rem',
                  outline: 'none',
                }}
              />
            </div>
            <button
              type="submit"
              disabled={loading}
              className="login-submit-btn"
              style={{
                width: '100%',
                padding: '10px',
                borderRadius: 10,
                background: 'var(--accent, #f59e0b)',
                color: '#000',
                fontWeight: 700,
                border: 'none',
                cursor: loading ? 'not-allowed' : 'pointer',
              }}
            >
              {loading ? 'Sending Code…' : 'Send 6-Digit Code ➔'}
            </button>
          </form>
        )}

        {step === 2 && (
          <form onSubmit={handleVerifyAndReset}>
            <div style={{ marginBottom: 14 }}>
              <label htmlFor="recovery-otp" style={{ display: 'block', fontSize: '0.8rem', fontWeight: 600, marginBottom: 6 }}>
                6-Digit Verification Code
              </label>
              <input
                id="recovery-otp"
                type="text"
                inputMode="numeric"
                maxLength={6}
                placeholder="123456"
                value={otp}
                onChange={(e) => setOtp(e.target.value.replace(/\D/g, ''))}
                required
                autoFocus
                style={{
                  width: '100%',
                  boxSizing: 'border-box',
                  padding: '10px 14px',
                  borderRadius: 10,
                  border: '1.5px solid var(--border)',
                  background: 'var(--bg-2, #111318)',
                  color: '#fbbf24',
                  fontSize: '1.2rem',
                  letterSpacing: '4px',
                  textAlign: 'center',
                  fontWeight: 800,
                  outline: 'none',
                }}
              />
            </div>

            <div style={{ marginBottom: 16 }}>
              <label htmlFor="recovery-new-password" style={{ display: 'block', fontSize: '0.8rem', fontWeight: 600, marginBottom: 6 }}>
                Set New Password (min. 8 chars, 1 uppercase, 1 lowercase, 1 number)
              </label>
              <div style={{ position: 'relative' }}>
                <input
                  id="recovery-new-password"
                  type={showPassword ? 'text' : 'password'}
                  placeholder="••••••••"
                  value={newPassword}
                  onChange={(e) => setNewPassword(e.target.value)}
                  required
                  style={{
                    width: '100%',
                    boxSizing: 'border-box',
                    padding: '10px 38px 10px 14px',
                    borderRadius: 10,
                    border: '1.5px solid var(--border)',
                    background: 'var(--bg-2, #111318)',
                    color: 'inherit',
                    fontSize: '0.88rem',
                    outline: 'none',
                  }}
                />
                <button
                  type="button"
                  onClick={() => setShowPassword(!showPassword)}
                  style={{
                    position: 'absolute',
                    right: 10,
                    top: '50%',
                    transform: 'translateY(-50%)',
                    background: 'none',
                    border: 'none',
                    color: 'var(--text-muted)',
                    cursor: 'pointer',
                    display: 'flex',
                    alignItems: 'center',
                  }}
                >
                  {showPassword ? <EyeOffIcon size={16} /> : <EyeIcon size={16} />}
                </button>
              </div>
            </div>

            <button
              type="submit"
              disabled={loading}
              className="login-submit-btn"
              style={{
                width: '100%',
                padding: '10px',
                borderRadius: 10,
                background: 'var(--accent, #f59e0b)',
                color: '#000',
                fontWeight: 700,
                border: 'none',
                cursor: loading ? 'not-allowed' : 'pointer',
                marginBottom: 10,
              }}
            >
              {loading ? 'Verifying & Updating…' : 'Reset Password & Sign In ➔'}
            </button>

            <button
              type="button"
              onClick={() => { setStep(1); setError(''); }}
              style={{
                width: '100%',
                background: 'none',
                border: 'none',
                color: 'var(--text-secondary)',
                fontSize: '0.78rem',
                cursor: 'pointer',
                textAlign: 'center',
              }}
            >
              ← Re-send code or change number
            </button>
          </form>
        )}
      </div>
    </div>
  )
}
