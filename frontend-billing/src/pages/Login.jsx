import React, { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../contexts/AuthContext'
import { logger } from '../utils/logger'

const STAR = 'M50 0 L51.5 4.5 L56 6 L51.5 7.5 L50 12 L48.5 7.5 L44 6 L48.5 4.5 Z'
const WINDOWS = [
  [10.6, 39], [15.1, 39],
  [28.5, 29], [33.2, 29], [28.5, 34], [33.2, 34],
  [46.5, 23], [51.2, 23], [46.5, 28], [51.2, 28], [46.5, 33], [51.2, 33],
]

function BuildingMark({ size = 28, strokeWidth = 1.8 }) {
  return (
    <svg width={size} height={size} viewBox="0 -5 64 64" fill="none" aria-hidden="true"
         shapeRendering="geometricPrecision" style={{ display: 'block', flexShrink: 0 }}>
      <g stroke="currentColor" strokeWidth={strokeWidth} strokeLinejoin="round">
        <rect x="8" y="36" width="12" height="18" rx="1" />
        <rect x="26" y="26" width="12" height="28" rx="1" />
        <rect x="44" y="16" width="12" height="38" rx="1" />
      </g>
      <g fill="currentColor">
        {WINDOWS.map(([x, y], i) => (
          <rect key={i} x={x} y={y} width="2.1" height="2.1" />
        ))}
      </g>
      <g stroke="currentColor" strokeWidth={strokeWidth} fill="none" strokeLinejoin="round">
        <rect x="11.4" y="46" width="5.2" height="8" />
        <rect x="29.4" y="43" width="5.2" height="11" />
        <rect x="47.4" y="40" width="5.2" height="14" />
      </g>
      <path d={STAR} fill="var(--accent)" />
    </svg>
  )
}

export default function Login() {
  const { login } = useAuth()
  const navigate  = useNavigate()

  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [showPw,   setShowPw]   = useState(false)
  const [error,    setError]    = useState('')
  const [loading,  setLoading]  = useState(false)

  async function handleSubmit(e) {
    e.preventDefault()
    setError('')
    setLoading(true)
    logger.debug('Login submit triggered for username:', username)
    try {
      await login(username, password)
      logger.info('Login completed successfully! Navigating to dashboard.')
      navigate('/', { replace: true })
    } catch (err) {
      logger.error('Login request failed:', err.message)
      setError(err.message || 'Invalid username or password. Please try again.')
    } finally {
      setLoading(false)
    }
  }

  return (
    <>
    <div className="login-backdrop" aria-hidden="true">
      <aside className="lb-sidebar">
        <div className="lb-logo" style={{ display: 'flex', alignItems: 'center', gap: 6 }}><BuildingMark size={18} /> BizAssist</div>
        <div className="lb-nav-section">Supply & Inflow</div>
        <div className="lb-navitem">Supplier Orders</div>
        <div className="lb-navitem">Purchase Bills</div>
        <div className="lb-navitem">Store Sync</div>
        <div className="lb-navitem">Data Migration</div>
        <div className="lb-nav-section">Hub</div>
        <div className="lb-navitem active">Home</div>
        <div className="lb-navitem">Dashboard</div>
        <div className="lb-nav-section">Sales & Operations</div>
        <div className="lb-navitem">Billing Counter</div>
        <div className="lb-navitem">Cash Book</div>
        <div className="lb-navitem">Contacts & Dues</div>
        <div className="lb-navitem">GST & Tax Reports</div>
      </aside>
      <main className="lb-main" style={{ flex: 1, padding: '24px 32px', display: 'flex', flexDirection: 'column', gap: '20px' }}>
        <div className="lb-h1" style={{ fontSize: '1.5rem', fontWeight: 700 }}>Home</div>
        
        {/* KPI Grid (4 cards) */}
        <div className="lb-grid-4" style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: '16px' }}>
          <div className="lb-card" style={{ height: '80px', borderRadius: '8px', background: 'var(--bg-2)', border: '1px solid var(--border)' }} />
          <div className="lb-card" style={{ height: '80px', borderRadius: '8px', background: 'var(--bg-2)', border: '1px solid var(--border)' }} />
          <div className="lb-card" style={{ height: '80px', borderRadius: '8px', background: 'var(--bg-2)', border: '1px solid var(--border)' }} />
          <div className="lb-card" style={{ height: '80px', borderRadius: '8px', background: 'var(--bg-2)', border: '1px solid var(--border)' }} />
        </div>

        {/* Second Row Grid (4 cards) */}
        <div className="lb-grid-4" style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: '16px' }}>
          <div className="lb-card" style={{ height: '80px', borderRadius: '8px', background: 'var(--bg-2)', border: '1px solid var(--border)' }} />
          <div className="lb-card" style={{ height: '80px', borderRadius: '8px', background: 'var(--bg-2)', border: '1px solid var(--border)' }} />
          <div className="lb-card" style={{ height: '80px', borderRadius: '8px', background: 'var(--bg-2)', border: '1px solid var(--border)' }} />
          <div className="lb-card" style={{ height: '80px', borderRadius: '8px', background: 'var(--bg-2)', border: '1px solid var(--border)' }} />
        </div>

        {/* Bottom Two Columns Grid */}
        <div className="lb-bottom-split" style={{ display: 'grid', gridTemplateColumns: '1.2fr 0.8fr', gap: '20px', flex: 1 }}>
          {/* Feed */}
          <div className="lb-card" style={{ borderRadius: '8px', background: 'var(--bg-2)', border: '1px solid var(--border)' }} />
          {/* Warnings & Invoices */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
            <div className="lb-card" style={{ flex: 1, borderRadius: '8px', background: 'var(--bg-2)', border: '1px solid var(--border)' }} />
            <div className="lb-card" style={{ flex: 1, borderRadius: '8px', background: 'var(--bg-2)', border: '1px solid var(--border)' }} />
          </div>
        </div>
      </main>
    </div>

    <div className="login-container" id="login-container">
      <div className="login-card">
        <div className="login-glow"></div>
        <div className="login-symbol"><BuildingMark size={42} /></div>
        <h1 className="login-title">BIZASSIST</h1>
        <p className="login-subtitle">ADVANCED BILLING SYSTEM</p>

        <div className="login-tabs">
          <button
            type="button"
            className="login-tab-btn active"
            onClick={() => {}}
          >
            Sign In
          </button>
          <button
            type="button"
            className="login-tab-btn"
            onClick={() => navigate('/register')}
          >
            Register
          </button>
        </div>

        <form id="login-form" onSubmit={handleSubmit}>
          <div className="form-group">
            <label htmlFor="username">Username</label>
            <input
              type="text"
              id="username"
              placeholder="e.g. store"
              value={username}
              onChange={e => setUsername(e.target.value)}
              required
              autoComplete="username"
            />
          </div>

          <div className="form-group" style={{ marginTop: '14px' }}>
            <label htmlFor="password">Password</label>
            <div className="password-wrapper">
              <input
                type={showPw ? 'text' : 'password'}
                id="password"
                placeholder="••••••••"
                value={password}
                onChange={e => setPassword(e.target.value)}
                required
                autoComplete="current-password"
              />
              <button
                type="button"
                className="password-toggle-btn"
                onClick={() => setShowPw(v => !v)}
                aria-label="Toggle password visibility"
              >
                {showPw ? (
                  <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94" />
                    <path d="M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19" />
                    <line x1="1" y1="1" x2="23" y2="23" />
                  </svg>
                ) : (
                  <svg className="eye-icon" xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"></path>
                    <circle cx="12" cy="12" r="3"></circle>
                  </svg>
                )}
              </button>
            </div>

            <div className="forgot-password-tip" style={{ marginTop: 6, fontSize: 11.5, color: 'var(--text-secondary)', textAlign: 'left', lineHeight: '1.4' }}>
              Forgot password? Contact your system administrator to reset it.
            </div>
          </div>

          {error && (
            <div id="login-error" className="login-error" style={{ marginTop: '14px' }}>
              {error}
            </div>
          )}

          <button
            type="submit"
            className="login-submit-btn"
            id="submit-btn"
            disabled={loading}
          >
            {loading ? 'Signing in...' : 'Sign In'}
          </button>
        </form>
      </div>
    </div>
    </>
  )
}
