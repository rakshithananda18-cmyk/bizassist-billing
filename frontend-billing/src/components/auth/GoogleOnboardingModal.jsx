/**
 * components/auth/GoogleOnboardingModal.jsx
 * Step-2 onboarding modal for new Google accounts:
 * Allows user to choose their store username, mandatory phone, category, and business name.
 */
import React, { useState, useEffect } from 'react'
import { API_BASE, CLOUD_URL, IS_LOCAL_APP } from '../../config'
import { useAuth } from '../../contexts/AuthContext'
import { boundedJsonFetch } from '../../api/boundedRequest'
import CustomSelect from '../common/CustomSelect'

const CATEGORIES = [
  { key: 'general', label: 'General Retail / Store' },
  { key: 'supermarket', label: 'Supermarket / Grocery' },
  { key: 'pharmacy', label: 'Pharmacy / Medical Store' },
  { key: 'restaurant', label: 'Restaurant / Café' },
  { key: 'clothing', label: 'Apparel / Garments' },
  { key: 'electronics', label: 'Electronics & Mobile' },
  { key: 'hardware', label: 'Hardware & Electrical' },
  { key: 'services', label: 'Services & Repair' },
]

export default function GoogleOnboardingModal({ isOpen, initialData, credential, onClose, onSuccess }) {
  const { googleAuth } = useAuth()
  const [businessName, setBusinessName] = useState('')
  const [category, setCategory] = useState('general')
  const [username, setUsername] = useState('')
  const [phone, setPhone] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [checkingUname, setCheckingUname] = useState(false)
  const [unameAvailable, setUnameAvailable] = useState(null)

  useEffect(() => {
    if (initialData) {
      setBusinessName(initialData.suggested_business_name || '')
      setUsername(initialData.suggested_username || '')
    }
  }, [initialData])

  // Live username availability check
  useEffect(() => {
    if (!username || username.trim().length < 3) {
      setUnameAvailable(null)
      return
    }
    const clean = username.trim()
    const timer = setTimeout(async () => {
      setCheckingUname(true)
      try {
        const res = await boundedJsonFetch(`${IS_LOCAL_APP ? CLOUD_URL : API_BASE}/api/auth/check-username?username=${encodeURIComponent(clean)}`)
        const data = await res.json()
        setUnameAvailable(data?.available ?? null)
      } catch {
        setUnameAvailable(null)
      } finally {
        setCheckingUname(false)
      }
    }, 350)

    return () => clearTimeout(timer)
  }, [username])

  if (!isOpen) return null

  const handleSubmit = async (e) => {
    e.preventDefault()
    setError('')
    if (!username.trim() || username.trim().length < 3) {
      setError('Please choose a username of at least 3 characters.')
      return
    }
    if (unameAvailable === false) {
      setError('This username is already taken. Please choose another.')
      return
    }
    if (!phone.trim() || phone.replace(/\D/g, '').length < 10) {
      setError('A valid 10-digit mobile phone number is required.')
      return
    }

    setLoading(true)
    try {
      const data = await googleAuth({
          credential,
          username: username.trim(),
          business_name: businessName.trim() || `${username.trim()}'s Store`,
          category,
          phone: phone.trim(),
        }, true)

      if (onSuccess) {
        onSuccess(data)
      }
      onClose()
    } catch (err) {
      setError(err?.message || 'Error creating account.')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div style={{
      position: 'fixed',
      inset: 0,
      backgroundColor: 'rgba(0, 0, 0, 0.8)',
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
        maxWidth: 460,
        width: '100%',
        padding: '26px 30px',
        boxShadow: '0 24px 48px rgba(0,0,0,0.6)',
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

        {/* Header with Google user profile badge */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 14, marginBottom: 18 }}>
          {initialData?.picture ? (
            <img
              src={initialData.picture}
              alt={initialData.name || 'User'}
              style={{ width: 44, height: 44, borderRadius: '50%', border: '2px solid var(--accent, #f59e0b)' }}
            />
          ) : (
            <div style={{
              width: 44, height: 44, borderRadius: '50%',
              background: 'var(--accent, #f59e0b)', color: '#000',
              fontWeight: 800, fontSize: 18, display: 'flex', alignItems: 'center', justifyContent: 'center'
            }}>
              {(initialData?.name || 'G')[0]}
            </div>
          )}
          <div>
            <h2 style={{ fontSize: '1.14rem', fontWeight: 800, margin: 0 }}>
              Welcome, {initialData?.name || 'Merchant'}!
            </h2>
            <div style={{ fontSize: '0.76rem', color: 'var(--text-muted)', marginTop: 2 }}>
              Verified email: <span style={{ color: '#fbbf24' }}>{initialData?.email}</span>
            </div>
          </div>
        </div>

        <p style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', marginBottom: 16, lineHeight: 1.45 }}>
          Set up your store details to start your <strong>14-day free Pro trial</strong>. Cashiers and counters will use this store username to log in.
        </p>

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

        <form onSubmit={handleSubmit}>
          {/* Business Name */}
          <div style={{ marginBottom: 12 }}>
            <label htmlFor="google-bizname" style={{ display: 'block', fontSize: '0.8rem', fontWeight: 600, marginBottom: 5 }}>
              Business / Store Name *
            </label>
            <input
              id="google-bizname"
              type="text"
              placeholder="e.g. Royal Supermarket"
              value={businessName}
              onChange={(e) => setBusinessName(e.target.value)}
              required
              style={{
                width: '100%',
                boxSizing: 'border-box',
                padding: '9px 12px',
                borderRadius: 9,
                border: '1.5px solid var(--border)',
                background: 'var(--bg-2, #111318)',
                color: 'inherit',
                fontSize: '0.88rem',
                outline: 'none',
              }}
            />
          </div>

          {/* Business Category */}
          <div style={{ marginBottom: 12 }}>
            <label htmlFor="google-category" style={{ display: 'block', fontSize: '0.8rem', fontWeight: 600, marginBottom: 5 }}>
              Business Category *
            </label>
            <CustomSelect
              id="google-category"
              value={category}
              onChange={(e) => setCategory(e.target.value)}
              style={{
                width: '100%',
                padding: '9px 12px',
                borderRadius: '9px',
                border: '1.5px solid var(--border)',
                background: 'var(--bg-2, #111318)',
                fontSize: '13px',
                color: 'inherit',
                outline: 'none',
              }}
            >
              {CATEGORIES.map((c) => (
                <option key={c.key} value={c.key}>{c.label}</option>
              ))}
            </CustomSelect>
          </div>

          {/* Choose Store Username */}
          <div style={{ marginBottom: 12 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 5 }}>
              <label htmlFor="google-username" style={{ fontSize: '0.8rem', fontWeight: 600 }}>
                Choose Your Username *
              </label>
              <span style={{ fontSize: '0.72rem' }}>
                {checkingUname && <span style={{ color: 'var(--text-muted)' }}>Checking…</span>}
                {!checkingUname && unameAvailable === true && <span style={{ color: '#10b981', fontWeight: 700 }}>✓ Available</span>}
                {!checkingUname && unameAvailable === false && <span style={{ color: '#ef4444', fontWeight: 700 }}>✗ Already taken</span>}
              </span>
            </div>
            <input
              id="google-username"
              type="text"
              placeholder="e.g. royal_mart"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              required
              style={{
                width: '100%',
                boxSizing: 'border-box',
                padding: '9px 12px',
                borderRadius: 9,
                border: `1.5px solid ${unameAvailable === false ? '#ef4444' : unameAvailable === true ? '#10b981' : 'var(--border)'}`,
                background: 'var(--bg-2, #111318)',
                color: 'inherit',
                fontSize: '0.88rem',
                outline: 'none',
              }}
            />
            <small style={{ color: 'var(--text-muted)', fontSize: '0.7rem' }}>
              Used by you and your cashier staff to log in at the counter.
            </small>
          </div>

          {/* Mandatory Phone */}
          <div style={{ marginBottom: 18 }}>
            <label htmlFor="google-phone" style={{ display: 'block', fontSize: '0.8rem', fontWeight: 600, marginBottom: 5 }}>
              Mobile Phone Number *
            </label>
            <input
              id="google-phone"
              type="tel"
              placeholder="+91 98765 43210"
              value={phone}
              onChange={(e) => setPhone(e.target.value)}
              required
              style={{
                width: '100%',
                boxSizing: 'border-box',
                padding: '9px 12px',
                borderRadius: 9,
                border: '1.5px solid var(--border)',
                background: 'var(--bg-2, #111318)',
                color: 'inherit',
                fontSize: '0.88rem',
                outline: 'none',
              }}
            />
            <small style={{ color: 'var(--text-muted)', fontSize: '0.7rem' }}>
              Mandatory for account recovery and receipt dispatch.
            </small>
          </div>

          <button
            type="submit"
            disabled={loading || unameAvailable === false}
            className="login-submit-btn"
            style={{
              width: '100%',
              padding: '11px',
              borderRadius: 10,
              background: 'var(--accent, #f59e0b)',
              color: '#000',
              fontWeight: 700,
              border: 'none',
              cursor: loading || unameAvailable === false ? 'not-allowed' : 'pointer',
              fontSize: '0.92rem',
            }}
          >
            {loading ? 'Creating Store…' : 'Launch Store (Start 14-Day Free Trial) ➔'}
          </button>
        </form>
      </div>
    </div>
  )
}
