import React, { useState, useEffect, useRef } from 'react'
import { useAuth, lastBizId } from '../lib/auth'
import { api } from '../lib/api'
import { BuildingMark } from '../components/Logo'
import { cycleTheme, getBillingUrl, getTheme } from '../lib/theme'
import { renderGoogleButton } from '../lib/googleAuth'
import TaskLoginScene from '../components/TaskLoginScene'

export default function Login() {
  const { ownerLogin, staffLogin, googleLogin, notice } = useAuth()
  const [theme, setThemeChoice] = useState(getTheme)
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
  const [verifiedBusiness, setVerifiedBusiness] = useState(null)
  const [staffRoster, setStaffRoster] = useState([])
  const [verifying, setVerifying] = useState(false)
  const [googleUnavailable, setGoogleUnavailable] = useState(false)
  const googleBtnRef = useRef(null)
  const lookupVersion = useRef(0)

  const set = (k) => (e) => setF(prev => ({ ...prev, [k]: e.target.value }))
  const changeBusiness = (e) => {
    lookupVersion.current += 1
    setF(prev => ({ ...prev, business: e.target.value, login_name: '', password: '' }))
    setVerifiedBusiness(null)
    setStaffRoster([])
    setVerifying(false)
    setError(null)
  }

  // Render Google button for Owner login
  useEffect(() => {
    let active = true
    if (mode === 'owner' && googleBtnRef.current) {
      setGoogleUnavailable(false)
      renderGoogleButton(googleBtnRef.current, {
        onCredential: async (credential) => {
          if (!active) return
          setBusy(true)
          setError(null)
          try {
            await googleLogin(credential)
          } catch (err) {
            if (active) setError(err.message || 'Google authentication failed.')
          } finally {
            if (active) setBusy(false)
          }
        },
        text: 'signin_with',
      }).then(rendered => { if (active) setGoogleUnavailable(!rendered) })
    }
    return () => { active = false }
  }, [mode, googleLogin])

  // Look up business details and staff accounts
  const checkBusiness = async (overrideBiz) => {
    const ident = (overrideBiz ?? f.business).trim()
    if (!ident) return
    const version = ++lookupVersion.current
    setVerifying(true)
    setVerifiedBusiness(null)
    setStaffRoster([])
    setF(prev => ({ ...prev, login_name: '', password: '' }))
    setError(null)
    try {
      const data = await api.post('/api/auth/lookup-business', { identifier: ident })
      if (version !== lookupVersion.current) return
      if (data?.found) {
        setVerifiedBusiness(data)
        const staff = data.staff || []
        setStaffRoster(staff)
        setF(prev => ({ ...prev, login_name: staff[0]?.username || '' }))
      } else {
        setError(data?.message || 'No business found. Check your owner’s details and try again.')
      }
    } catch (err) {
      if (version === lookupVersion.current) setError(err.message || 'Could not find this business. Please try again.')
    } finally {
      if (version === lookupVersion.current) setVerifying(false)
    }
  }

  // Pre-check if business is saved
  useEffect(() => {
    if (f.business) checkBusiness(f.business)
    return () => { lookupVersion.current += 1 }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const submit = async (e) => {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      if (mode === 'staff') {
        if (!verifiedBusiness || verifying || !staffRoster.some(s => s.username === f.login_name)) {
          throw new Error('Find your business and select your staff account first.')
        }
        await staffLogin(verifiedBusiness.public_id, f.login_name, f.password)
      } else {
        await ownerLogin(f.username.trim(), f.password)
      }
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <>
      <div className="login-container task-auth" id="login-container">
        <button type="button" className="task-auth-theme" onClick={() => setThemeChoice(cycleTheme())} aria-label={`Appearance: ${theme}. Change appearance`}>
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden="true"><circle cx="12" cy="12" r="4" /><path d="M12 2v3m0 14v3M2 12h3m14 0h3M5 5l2 2m10 10 2 2M5 19l2-2M17 7l2-2" /></svg>
          {theme === 'system' ? 'System' : theme === 'dark' ? 'Dark' : 'Light'}
        </button>
        <div className="login-card">
          <div className="login-glow" />
          <div className="login-symbol"><BuildingMark size={44} /></div>
          <h1 className="login-title">STATER</h1>
          <p className="login-subtitle">FIELD TEAM &amp; LOGISTICS</p>

          {/* Staff vs Owner Tabs matching Billing */}
          <div className="login-tabs" role="tablist">
            <button
              type="button"
              role="tab"
              aria-selected={mode === 'staff'}
              className={`login-tab-btn ${mode === 'staff' ? 'active' : ''}`}
              onClick={() => { setMode('staff'); setError(null) }}
              disabled={busy}
            >
              Staff Login
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={mode === 'owner'}
              className={`login-tab-btn ${mode === 'owner' ? 'active' : ''}`}
              onClick={() => { setMode('owner'); setError(null) }}
              disabled={busy}
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
                  <label htmlFor="staff-bizid" className="form-label">Business Identifier</label>
                  <div style={{ position: 'relative' }}>
                    <input
                      id="staff-bizid"
                      className="form-input"
                      placeholder="Owner's Phone, Username, Email, or BizID"
                      value={f.business}
                      onChange={changeBusiness}
                      onKeyDown={e => {
                        if (e.key === 'Enter') { e.preventDefault(); checkBusiness() }
                      }}
                      autoCapitalize="none"
                      autoComplete="off"
                      disabled={busy}
                      required
                      autoFocus
                    />
                    {verifying && (
                      <span style={{ position: 'absolute', right: 12, top: 10, fontSize: '0.75rem', color: 'var(--text-muted)' }}>
                        Checking…
                      </span>
                    )}
                  </div>
                  <span className="form-hint">Enter your owner’s phone, username, email, or BizID.</span>
                  <button type="button" className="btn btn-secondary" style={{ marginTop: 8, width: '100%' }} disabled={busy || verifying || !f.business.trim()} onClick={() => checkBusiness()}>
                    {verifying ? 'Finding business…' : 'Find business'}
                  </button>
                </div>

                {verifiedBusiness && (
                  <div style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: 8,
                    margin: '6px 0 10px',
                    padding: '8px 12px',
                    borderRadius: 8,
                    background: 'rgba(16, 185, 129, 0.08)',
                    border: '1px solid rgba(16, 185, 129, 0.25)',
                    fontSize: '0.8rem',
                    textAlign: 'left'
                  }}>
                    <span style={{ color: '#10b981', fontWeight: 700 }}>✓</span>
                    <span style={{ fontWeight: 600, color: 'var(--text-primary)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                      {verifiedBusiness.business_name}
                    </span>
                    <span style={{ color: 'var(--text-muted)', fontSize: '0.74rem', marginLeft: 'auto' }}>
                      {verifiedBusiness.public_id}
                    </span>
                  </div>
                )}

                <div className="form-group" style={{ textAlign: 'left', marginTop: 10 }}>
                  <label htmlFor="staff-login-select" className="form-label" style={{ display: 'flex', justifyContent: 'space-between' }}>
                    <span>Your Staff Account</span>
                    {staffRoster.length > 0 && (
                      <span style={{ fontSize: '0.72rem', color: 'var(--accent)', fontWeight: 600 }}>
                        {staffRoster.length} staff found
                      </span>
                    )}
                  </label>
                    <select
                      id="staff-login-select"
                      className="form-input"
                      value={f.login_name}
                      onChange={set('login_name')}
                      disabled={busy || !verifiedBusiness || !staffRoster.length}
                      required
                    >
                      {!staffRoster.length && <option value="">{verifiedBusiness ? 'No active staff accounts' : 'Find your business first'}</option>}
                      {staffRoster.map(s => (
                          <option key={s.id} value={s.username}>
                            {s.name ? `${s.name} (${s.username})` : s.username}
                          </option>
                      ))}
                    </select>
                  {verifiedBusiness && !staffRoster.length && <span className="form-hint">Ask your owner to add or enable your staff account.</span>}
                </div>
              </>
            ) : (
              <>
                {/* Google Sign-in for Owner */}
                <div style={{ marginBottom: 14 }}>
                  <div ref={googleBtnRef} style={{ display: 'flex', justifyContent: 'center', minHeight: 40 }} />
                  {googleUnavailable && <span className="form-hint" role="status">Google sign-in is unavailable. Use your account credentials below.</span>}
                  <div style={{
                    display: 'flex',
                    alignItems: 'center',
                    margin: '12px 0 8px',
                    gap: 12
                  }}>
                    <div style={{ flex: 1, height: 1, background: 'var(--border)' }} />
                    <span style={{ fontSize: '0.72rem', color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
                      or with credentials
                    </span>
                    <div style={{ flex: 1, height: 1, background: 'var(--border)' }} />
                  </div>
                </div>

                <div className="form-group" style={{ textAlign: 'left' }}>
                  <label htmlFor="owner-username" className="form-label">Username, Email, or Phone</label>
                  <input
                    id="owner-username"
                    className="form-input"
                    value={f.username}
                    onChange={set('username')}
                    autoCapitalize="none"
                    autoComplete="username"
                    disabled={busy}
                    required
                    autoFocus
                  />
                  <span className="form-hint">Same account as STATER Bill.</span>
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
                  autoComplete="current-password"
                  disabled={busy || (mode === 'staff' && (!verifiedBusiness || !staffRoster.length))}
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

            <button type="submit" className="login-submit-btn" disabled={busy || (mode === 'staff' && (verifying || !verifiedBusiness || !f.login_name))} style={{ marginTop: 16 }}>
              {busy ? 'Signing in…' : mode === 'staff' ? 'Start Shift' : 'Sign In as Owner'}
            </button>

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
              <div className="form-hint" style={{ marginTop: 6 }}>Start your 14-day Pro trial in Billing. Use the same account here.</div>
            </div>

            <p className="login-reassurance">
              <svg aria-hidden="true" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <rect x="3" y="11" width="18" height="10" rx="2" />
                <path d="M7 11V7a5 5 0 0 1 10 0v4" />
              </svg>
              <span>Your team’s workspace, securely signed in.</span>
            </p>
          </form>
        </div>
        <footer className="task-auth-footer">Need a hand? <a href="mailto:support@staterbill.com">support@staterbill.com</a></footer>
        <TaskLoginScene />
      </div>
    </>
  )
}
