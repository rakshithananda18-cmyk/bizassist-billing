import { useState } from 'react'
import { useNavigate, Link } from 'react-router-dom'
import { useAuth } from '../../contexts/AuthContext'

export default function AdminLogin() {
  const { adminLogin } = useAuth()
  const navigate = useNavigate()

  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [showPw,   setShowPw]   = useState(false)
  const [error,    setError]    = useState('')
  const [loading,  setLoading]  = useState(false)
  const [needsOtp, setNeedsOtp] = useState(false)   // server asked for a 2FA code
  const [otp,      setOtp]      = useState('')

  async function handleSubmit(e) {
    e.preventDefault()
    setError('')
    setLoading(true)
    try {
      await adminLogin(username, password, needsOtp ? otp : undefined)
      navigate('/admin/dashboard')
    } catch (err) {
      // Backend signals "2FA code required" after a correct password —
      // reveal the OTP field instead of treating it as a failure.
      if (/2FA code required/i.test(err.message)) {
        setNeedsOtp(true)
        setError('')
      } else {
        setError(err.message)
        if (/2FA/i.test(err.message)) setOtp('')
      }
    } finally {
      setLoading(false)
    }
  }

  return (
    <>
    {/* Decorative blurred admin interface behind the login card */}
    <div className="login-backdrop lb-admin" aria-hidden="true">
      <div className="lb-topbar">
        <div className="lb-logo" style={{ margin: 0, fontSize: 18 }}>✦ BIZASSIST</div>
        <div className="lb-pill" /><div className="lb-pill" />
        <div className="lb-pill wide" /><div className="lb-pill" />
      </div>
      <main className="lb-main">
        <div className="lb-h1">✦ BizAssist Admin Workspace</div>
        <div className="lb-row">
          <div className="lb-card" /><div className="lb-card" /><div className="lb-card" />
        </div>
        <div className="lb-bar" /><div className="lb-bar" /><div className="lb-bar" />
      </main>
    </div>

    <div className="login-container" id="admin-login-container">
      <div className="login-card">
        <div className="login-glow"></div>
        <div className="login-symbol">✦</div>
        <h1 className="login-title">BIZASSIST</h1>
        <p className="login-subtitle">Admin Monitoring Workspace</p>

        <form id="admin-login-form" onSubmit={handleSubmit}>

          {/* Admin Username */}
          <div className="form-group">
            <label htmlFor="admin-username">Admin Username</label>
            <input
              type="text"
              id="admin-username"
              placeholder="e.g. admin"
              value={username}
              onChange={e => setUsername(e.target.value)}
              required
              autoComplete="username"
            />
          </div>

          {/* Password with eye toggle */}
          <div className="form-group">
            <label htmlFor="admin-password">Password</label>
            <div className="password-wrapper">
              <input
                type={showPw ? 'text' : 'password'}
                id="admin-password"
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
          </div>

          {/* 2FA code — appears only after the server asks for it */}
          {needsOtp && (
            <div className="form-group">
              <label htmlFor="admin-otp">Authenticator Code</label>
              <input
                type="text"
                id="admin-otp"
                inputMode="numeric"
                pattern="[0-9]*"
                maxLength={6}
                placeholder="6-digit code"
                value={otp}
                onChange={e => setOtp(e.target.value.replace(/\D/g, ''))}
                required
                autoFocus
                autoComplete="one-time-code"
                style={{ letterSpacing: '0.35em', fontFamily: "'Geist Mono', monospace", textAlign: 'center' }}
              />
            </div>
          )}

          {/* Error */}
          {error && (
            <div id="login-error" className="login-error" style={{ display: 'block' }}>
              {error}
            </div>
          )}

          <button
            type="submit"
            className="login-submit-btn"
            disabled={loading}
          >
            {loading ? 'Signing in...' : 'Admin Sign In'}
          </button>
        </form>

        <div className="login-footer">
          <Link to="/login" className="admin-link">
            Looking for Enterprise App? Go to Sign In →
          </Link>
        </div>
      </div>
    </div>
    </>
  )
}
