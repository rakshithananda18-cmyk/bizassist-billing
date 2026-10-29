import React, { useState } from 'react'
import { useAuth, lastBizId } from '../lib/auth'
import { BuildingMark } from '../components/Logo'
import { getBillingUrl } from '../lib/theme'

export default function Login() {
  const { ownerLogin, staffLogin, notice } = useAuth()
  const [mode, setModeState] = useState(() => {
    try { return localStorage.getItem('task_login_mode') || 'staff' } catch { return 'staff' }
  })
  const setMode = (m) => {
    setModeState(m)
    try { localStorage.setItem('task_login_mode', m) } catch { /* ignore */ }
  }
  const [f, setF] = useState({ username: '', password: '', business: lastBizId(), login_name: '' })
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const [showPw, setShowPw] = useState(false)
  const set = (k) => (e) => setF({ ...f, [k]: e.target.value })

  const submit = async (e) => {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      if (mode === 'staff') await staffLogin(f.business.trim(), f.login_name.trim(), f.password)
      else await ownerLogin(f.username.trim(), f.password)
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <>
      {/* Signature BizAssist blurred app backdrop behind modal */}
      <div className="login-backdrop" aria-hidden="true">
        <aside className="lb-sidebar">
          <div className="lb-logo" style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
            <BuildingMark size={18} /> BizAssist
          </div>
          <div className="lb-nav-section">Today</div>
          <div className="lb-navitem active">Dashboard</div>
          <div className="lb-navitem">Live Map</div>
          <div className="lb-navitem">Day Plan</div>
          <div className="lb-navitem">Tasks</div>
          <div className="lb-navitem">Shop Requests</div>
          <div className="lb-nav-section">Setup</div>
          <div className="lb-navitem">Shops</div>
          <div className="lb-navitem">Routes</div>
          <div className="lb-navitem">Staff</div>
          <div className="lb-nav-section">Records</div>
          <div className="lb-navitem">Attendance</div>
          <div className="lb-navitem">Scorecard</div>
        </aside>
        <main className="lb-main">
          <div className="lb-h1">Dashboard</div>
          <div className="lb-grid-4">
            <div className="lb-card" />
            <div className="lb-card" />
            <div className="lb-card" />
            <div className="lb-card" />
          </div>
          <div className="lb-bottom-split">
            <div className="lb-card" style={{ height: 260 }} />
            <div className="lb-card" style={{ height: 260 }} />
          </div>
        </main>
      </div>

      {/* Floating Centered Glass Modal */}
      <div className="login-container" id="login-container">
        <div className="login-card">
          <div className="login-glow" />
          <div className="login-symbol"><BuildingMark size={44} /></div>
          <h1 className="login-title">BIZASSIST</h1>
          <p className="login-subtitle">FIELD TEAM &amp; LOGISTICS</p>

          {/* Staff vs Owner Tabs matching Billing */}
          <div className="login-tabs" role="tablist">
            <button
              type="button"
              role="tab"
              aria-selected={mode === 'staff'}
              className={`login-tab-btn ${mode === 'staff' ? 'active' : ''}`}
              onClick={() => { setMode('staff'); setError(null) }}
            >
              Staff Login
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={mode === 'owner'}
              className={`login-tab-btn ${mode === 'owner' ? 'active' : ''}`}
              onClick={() => { setMode('owner'); setError(null) }}
            >
              Owner Login
            </button>
          </div>

          {notice && (
            <div className="alert alert-warning" style={{ width: '100%', marginBottom: 14 }}>
              {notice}
            </div>
          )}
          {error && (
            <div className="login-error" role="alert" style={{ marginBottom: 14 }}>
              {error}
            </div>
          )}

          <form onSubmit={submit} className="login-form">
            {mode === 'staff' ? (
              <>
                <div className="form-group" style={{ textAlign: 'left' }}>
                  <label htmlFor="staff-bizid" className="form-label">Business ID</label>
                  <input
                    id="staff-bizid"
                    className="form-input"
                    value={f.business}
                    onChange={set('business')}
                    placeholder="e.g. BA-XXXXXX"
                    autoCapitalize="characters"
                    required
                    autoFocus
                  />
                  <span className="form-hint">Ask your owner for the BizID (shown in their app).</span>
                </div>
                <div className="form-group" style={{ textAlign: 'left', marginTop: 10 }}>
                  <label htmlFor="staff-login-name" className="form-label">Your login name</label>
                  <input
                    id="staff-login-name"
                    className="form-input"
                    value={f.login_name}
                    onChange={set('login_name')}
                    placeholder="e.g. ravi"
                    autoCapitalize="none"
                    autoComplete="username"
                    required
                  />
                </div>
              </>
            ) : (
              <>
                <div className="form-group" style={{ textAlign: 'left' }}>
                  <label htmlFor="owner-username" className="form-label">Username</label>
                  <input
                    id="owner-username"
                    className="form-input"
                    value={f.username}
                    onChange={set('username')}
                    placeholder="e.g. store_owner"
                    autoCapitalize="none"
                    autoComplete="username"
                    required
                    autoFocus
                  />
                  <span className="form-hint">Same account as BizAssist Billing.</span>
                </div>
              </>
            )}

            <div className="form-group" style={{ textAlign: 'left', marginTop: 10 }}>
              <label htmlFor="login-password" className="form-label">Password</label>
              <div className="password-wrapper">
                <input
                  id="login-password"
                  className="form-input"
                  type={showPw ? 'text' : 'password'}
                  value={f.password}
                  onChange={set('password')}
                  placeholder="••••••••"
                  autoComplete="current-password"
                  required
                />
                <button
                  type="button"
                  className="password-toggle-btn"
                  onClick={() => setShowPw(!showPw)}
                  aria-label="Toggle password visibility"
                >
                  {showPw ? (
                    <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                      <path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94" />
                      <path d="M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19" />
                      <line x1="1" y1="1" x2="23" y2="23" />
                    </svg>
                  ) : (
                    <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                      <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z" />
                      <circle cx="12" cy="12" r="3" />
                    </svg>
                  )}
                </button>
              </div>
            </div>

            <button type="submit" className="login-submit-btn" disabled={busy} style={{ marginTop: 16 }}>
              {busy ? 'Signing in…' : mode === 'staff' ? 'Start Shift' : 'Sign In as Owner'}
            </button>

            {mode === 'owner' && (
              <div style={{ textAlign: 'center', marginTop: 14 }}>
                <span style={{ fontSize: '0.8rem', color: 'var(--text-muted)', marginRight: 6 }}>
                  New business owner?
                </span>
                <a
                  href={getBillingUrl('/register')}
                  style={{ fontSize: '0.8rem', color: 'var(--accent)', fontWeight: 600, padding: 0, border: 'none', background: 'none', cursor: 'pointer' }}
                >
                  Register in Billing
                </a>
                <div className="form-hint" style={{ marginTop: 6 }}>Create your business and activate its 14-day Pro trial in Billing, then return here with the same account.</div>
              </div>
            )}

            <p className="login-reassurance">
              <svg aria-hidden="true" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <rect x="3" y="11" width="18" height="10" rx="2" />
                <path d="M7 11V7a5 5 0 0 1 10 0v4" />
              </svg>
              <span>Your business data stays private and encrypted.</span>
            </p>
          </form>
        </div>
      </div>
    </>
  )
}
