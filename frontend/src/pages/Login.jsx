import React, { useEffect, useState } from 'react'
import { useAuth, lastBizId } from '../lib/auth'
import { Logo } from '../components/Logo'

export default function Login() {
  const { ownerLogin, ownerSignup, staffLogin, exchange, notice } = useAuth()
  // Staff sign in daily on phones; owners rarely. Remember the last tab used.
  const [mode, setModeState] = useState(() => { try { return localStorage.getItem('task_login_mode') || 'staff' } catch { return 'staff' } })
  const setMode = (m) => { setModeState(m); try { localStorage.setItem('task_login_mode', m) } catch { /* ignore */ } }
  const [signup, setSignup] = useState(false)
  const [f, setF] = useState({ username: '', password: '', business_name: '', phone: '', business: lastBizId(), login_name: '' })
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const set = (k) => (e) => setF({ ...f, [k]: e.target.value })

  // Single sign-on from BizAssist Billing: …/#sso=<billing token>
  useEffect(() => {
    const m = /#sso=([^&]+)/.exec(window.location.hash)
    if (!m) return
    history.replaceState(null, '', window.location.pathname)
    setBusy(true)
    exchange(decodeURIComponent(m[1])).catch(e => setError(e.message)).finally(() => setBusy(false))
  }, [exchange])

  const submit = async (e) => {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      if (mode === 'staff') await staffLogin(f.business.trim(), f.login_name.trim(), f.password)
      else if (signup) await ownerSignup({ username: f.username.trim(), password: f.password, business_name: f.business_name.trim(), phone: f.phone.trim() || null })
      else await ownerLogin(f.username.trim(), f.password)
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="login-page">
      <form className="login-card" onSubmit={submit}>
        <div className="stack" style={{ gap: 6 }}>
          <Logo size={30} />
          <div className="product">Field Team · Tasks · Deliveries</div>
        </div>
        <div className="seg" role="tablist">
          <button type="button" className={mode === 'staff' ? 'on' : ''} onClick={() => { setMode('staff'); setSignup(false) }}>Staff</button>
          <button type="button" className={mode === 'owner' ? 'on' : ''} onClick={() => setMode('owner')}>Owner</button>
        </div>
        {notice && <div className="alert alert-warning">{notice}</div>}
        {error && <div className="alert alert-danger">{error}</div>}

        {mode === 'staff' ? (
          <>
            <div className="form-group">
              <label className="form-label">Business ID</label>
              <input className="form-input" value={f.business} onChange={set('business')} placeholder="BA-XXXXXX" autoCapitalize="characters" required />
              <span className="form-hint">Ask your owner for the BizID (shown in their app).</span>
            </div>
            <div className="form-group">
              <label className="form-label">Your login name</label>
              <input className="form-input" value={f.login_name} onChange={set('login_name')} autoCapitalize="none" autoComplete="username" required />
            </div>
          </>
        ) : (
          <>
            <div className="form-group">
              <label className="form-label">Username</label>
              <input className="form-input" value={f.username} onChange={set('username')} autoCapitalize="none" autoComplete="username" required />
              {!signup && <span className="form-hint">Same account as BizAssist Billing.</span>}
            </div>
            {signup && (
              <>
                <div className="form-group">
                  <label className="form-label">Business name</label>
                  <input className="form-input" value={f.business_name} onChange={set('business_name')} required />
                </div>
                <div className="form-group">
                  <label className="form-label">Phone (optional)</label>
                  <input className="form-input" value={f.phone} onChange={set('phone')} inputMode="tel" />
                </div>
              </>
            )}
          </>
        )}
        <div className="form-group">
          <label className="form-label">Password</label>
          <input className="form-input" type="password" value={f.password} onChange={set('password')} autoComplete={signup ? 'new-password' : 'current-password'} required />
          {signup && <span className="form-hint">8+ characters with upper-case, lower-case and a number.</span>}
        </div>
        <button className="btn btn-primary btn-lg btn-block" disabled={busy}>
          {busy ? 'Please wait…' : mode === 'staff' ? 'Sign in' : signup ? 'Create BizAssist account' : 'Sign in as owner'}
        </button>
        {mode === 'owner' && (
          <button type="button" className="btn btn-ghost btn-sm" onClick={() => setSignup(!signup)}>
            {signup ? 'I already have a BizAssist account' : 'New to BizAssist? Create an account'}
          </button>
        )}
        {mode === 'staff' && <div className="form-hint">One phone at a time: signing in here signs your other device out.</div>}
      </form>
    </div>
  )
}
