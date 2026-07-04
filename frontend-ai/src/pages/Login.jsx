import { useState, useEffect } from 'react'
import { useNavigate, Link } from 'react-router-dom'
import { useAuth } from '../contexts/AuthContext'
import { BuildingMark } from '../components/Logo'

export default function Login() {
  const { login, signup } = useAuth()
  const navigate  = useNavigate()

  const [tab,      setTab]      = useState('login')   // 'login' | 'signup'
  const [username, setUsername] = useState('')
  const [bizname,  setBizname]  = useState('')
  const [password, setPassword] = useState('')
  const [showPw,   setShowPw]   = useState(false)
  const [pwFocus,  setPwFocus]  = useState(false)
  const [error,    setError]    = useState('')
  const [loading,  setLoading]  = useState(false)
  const [showConditions, setShowConditions] = useState(false)

  // Password condition checks (for signup tab)
  const condLength    = password.length >= 8
  const condCapital   = /[A-Z]/.test(password)
  const condLower     = /[a-z]/.test(password)
  const condNumber    = /[0-9]/.test(password)
  const condSpecial   = /[^A-Za-z0-9]/.test(password)
  const hasUnmetConditions = !condLength || !condCapital || !condLower || !condNumber || !condSpecial

  useEffect(() => {
    // Make sure theme applies even before logging in
    const stored = localStorage.getItem('theme') || 'system'
    const computed = stored === 'system' ? (window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light') : stored
    document.body.setAttribute('data-theme', computed)
  }, [])

  useEffect(() => {
    // Reset visibility immediately when typing/focus changes
    setShowConditions(false)
    
    // Wait for 1 second of idle typing to show the requirements dropdown
    const timer = setTimeout(() => {
      setShowConditions(true)
    }, 1000)
    
    return () => clearTimeout(timer)
  }, [password, pwFocus, tab])

  async function handleSubmit(e) {
    e.preventDefault()
    setError('')
    setLoading(true)
    try {
      if (tab === 'login') {
        await login(username, password)
        navigate('/chat')
      } else {
        // Signup: validate conditions first
        if (!condLength || !condCapital || !condLower || !condNumber || !condSpecial) {
          setError('Password does not meet all requirements.')
          setLoading(false)
          return
        }
        if (!bizname.trim()) {
          setError('Business name is required.')
          setLoading(false)
          return
        }
        await signup(username, password, bizname.trim())
        navigate('/chat')
      }
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <>
    {/* Decorative blurred app interface behind the login card (legacy look) */}
    <div className="login-backdrop" aria-hidden="true">
      <aside className="lb-sidebar">
        <div className="lb-logo" style={{ display: 'flex', alignItems: 'center', gap: 6 }}><BuildingMark size={18} /> BizAssist</div>
        <div className="lb-navitem active">AI Assistant</div>
        <div className="lb-navitem">Dashboard</div>
        <div className="lb-navitem">Invoices</div>
        <div className="lb-navitem">Payments</div>
        <div className="lb-navitem">Clients</div>
        <div className="lb-navitem">Database Viewer</div>
      </aside>
      <main className="lb-main">
        <div className="lb-h1">Business Database</div>
        <div className="lb-row">
          <div className="lb-card" /><div className="lb-card" /><div className="lb-card" />
        </div>
        <div className="lb-bar" /><div className="lb-bar" />
        <div className="lb-bar" /><div className="lb-bar" />
      </main>
      <aside className="lb-right">
        <div className="lb-h1" style={{ fontSize: 26 }}>Good evening</div>
        <div className="lb-chip" /><div className="lb-chip" />
        <div className="lb-chip" /><div className="lb-chip" />
      </aside>
    </div>

    <div className="login-container" id="login-container">
      <div className="login-card">
        <div className="login-glow"></div>
        <div className="login-symbol"><BuildingMark size={42} /></div>
        <h1 className="login-title">BIZASSIST</h1>
        <p className="login-subtitle">Enterprise Business Intelligence Portal</p>

        <form id="login-form" onSubmit={handleSubmit}>

          {/* Username */}
          <div className="form-group">
            <label htmlFor="username">Username</label>
            <input
              type="text"
              id="username"
              placeholder="e.g. pharmacy"
              value={username}
              onChange={e => setUsername(e.target.value)}
              required
              autoComplete="username"
            />
          </div>

          {/* Password */}
          <div className="form-group">
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

            <div className="forgot-password-tip" style={{ marginTop: 6, fontSize: 11.5, color: 'var(--secondary-text)', textAlign: 'left', lineHeight: '1.4' }}>
              Forgot password? Contact your system administrator to reset it.
            </div>
          </div>

          {/* Error */}
          {error && (
            <div id="login-error" className="login-error" style={{ display: 'block' }}>
              {error}
            </div>
          )}

          <button type="submit" className="login-submit-btn" disabled={loading}>
            {loading
            ? 'Signing in...'
            : 'Sign In to Dashboard'}
          </button>
        </form>

        <div className="login-footer">
          <Link to="/admin/login" className="admin-link">
            Looking for Admin Portal? Go to Admin Portal →
          </Link>
        </div>
      </div>
    </div>
    </>
  )
}
