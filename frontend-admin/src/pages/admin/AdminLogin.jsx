import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../../contexts/AuthContext'
import { BuildingMark } from '../../components/Logo'
import AdminConstellation from '../../components/AdminConstellation'
import { useAdminTheme } from '../../utils/adminPreferences'
import '../../styles/adminLogin.css'

function billingSignInUrl() {
  try {
    const url = new URL('/login', import.meta.env.VITE_BILLING_URL || 'https://app.staterbill.com')
    if (['https:', 'http:'].includes(url.protocol)) return url.href
  } catch { /* Keep the public sign-in destination available with a bad local override. */ }
  return 'https://app.staterbill.com/login'
}

export default function AdminLogin() {
  const { adminLogin } = useAuth()
  const navigate = useNavigate()
  const [isDark, setTheme] = useAdminTheme()

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
      const destination = sessionStorage.getItem('admin_return_path')
      sessionStorage.removeItem('admin_return_path')
      const safe = typeof destination === 'string' && destination.startsWith('/admin/') && !destination.includes('\\') && destination.split(/[?#]/)[0] !== '/admin/login'
      navigate(safe ? destination : '/admin/dashboard')
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
    <main className="admin-entry" id="admin-login-container">
      <div className="admin-entry-appearance" role="group" aria-label="Appearance">
        <button type="button" aria-label="Use light appearance" aria-pressed={!isDark} onClick={() => setTheme(false)}><svg viewBox="0 0 24 24" width="17" height="17" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden="true"><circle cx="12" cy="12" r="4" /><path d="M12 2v2m0 16v2M2 12h2m16 0h2M5 5l1.5 1.5m11 11L19 19M5 19l1.5-1.5m11-11L19 5" /></svg></button>
        <button type="button" aria-label="Use dark appearance" aria-pressed={isDark} onClick={() => setTheme(true)}><svg viewBox="0 0 24 24" width="17" height="17" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden="true"><path d="M20 15A9 9 0 0 1 9 4a9 9 0 1 0 11 11Z" /></svg></button>
      </div>
      <div className="admin-entry-frame">
        <section className="admin-entry-form-panel" aria-labelledby="admin-signin-title">
          <div className="admin-entry-form-card">
            <div className="admin-entry-card-brand"><BuildingMark size={40} accent="#c15f3c" /><strong>Stater <span>Admin</span></strong></div>
            <div className="admin-entry-form-kicker"><span /> ADMINISTRATOR ACCESS</div>
            <h1 id="admin-signin-title">{needsOtp ? 'One more step.' : 'Welcome back.'}</h1>
            <p className="admin-entry-form-intro">{needsOtp ? 'Enter the six-digit code from your authenticator to continue.' : 'Sign in to your operations workspace.'}</p>

            <form id="admin-login-form" onSubmit={handleSubmit} aria-busy={loading} aria-describedby={error ? 'login-error' : undefined}>
              <div className="admin-entry-field">
                <label htmlFor="admin-username">Admin Username</label>
                <input type="text" id="admin-username" value={username} onChange={e => setUsername(e.target.value)} required autoComplete="username" />
              </div>

              <div className="admin-entry-field">
                <label htmlFor="admin-password">Password</label>
                <div className="admin-entry-password">
                  <input type={showPw ? 'text' : 'password'} id="admin-password" value={password} onChange={e => setPassword(e.target.value)} required autoComplete="current-password" />
                  <button type="button" className="admin-entry-password-toggle" onClick={() => setShowPw(v => !v)} aria-label="Toggle password visibility" aria-pressed={showPw}>
                    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                      {showPw ? <><path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19M1 1l22 22" /></> : <><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8Z" /><circle cx="12" cy="12" r="3" /></>}
                    </svg>
                  </button>
                </div>
              </div>

              {needsOtp && <div className="admin-entry-field admin-entry-otp-field">
                <label htmlFor="admin-otp">Authenticator Code</label>
                <input type="text" id="admin-otp" inputMode="numeric" pattern="[0-9]*" maxLength={6} placeholder="6-digit code" value={otp} onChange={e => setOtp(e.target.value.replace(/\D/g, ''))} required autoFocus autoComplete="one-time-code" />
              </div>}

              {error && <div id="login-error" className="admin-entry-error" role="alert">{error}</div>}

              <button type="submit" className="admin-entry-submit" disabled={loading}>
                <span>{loading ? 'Signing in...' : 'Admin Sign In'}</span>
                {loading ? <span className="admin-entry-spinner" aria-hidden="true" /> : <span aria-hidden="true">→</span>}
              </button>
            </form>

            <div className="admin-entry-form-footer"><p>Here to run your store?</p><a href={billingSignInUrl()}>Go to STATER Bill sign in <span aria-hidden="true">↗</span></a></div>
            <p className="admin-entry-access-note">For platform administrators. Use your assigned admin account.</p>
          </div>
        </section>
      </div>
      <AdminConstellation />
    </main>
  )
}
