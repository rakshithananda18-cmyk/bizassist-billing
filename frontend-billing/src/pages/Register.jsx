// ============================================================================
// Page: Register.jsx
// Description: Merchant sign-up page. Handles creating new business owner accounts
//              and configuring baseline settings.
// ============================================================================
import React, { useState, useEffect, useRef } from 'react'
import { API_BASE, CLOUD_URL, IS_LOCAL_APP } from '../config'
import { useNavigate, useLocation, Link } from 'react-router-dom'
import { useAuth } from '../contexts/AuthContext'
import { logger } from '../utils/logger'
import {
  EyeIcon,
  EyeOffIcon
} from '../components/Icons'
import { BuildingMark } from '../components/Logo'
import CustomSelect from '../components/common/CustomSelect'
import { DESKTOP_DOWNLOAD_URL } from '../config/downloadApp'
import './registration.css'
import { normalizeRegistrationPhone } from '../utils/registrationPhone'
import GoogleOnboardingModal from '../components/auth/GoogleOnboardingModal'
import AuthRoadmap from '../components/auth/AuthRoadmap'
import AuthThemeToggle from '../components/auth/AuthThemeToggle'
import RegistrationStory from '../components/auth/RegistrationStory'
import { renderGoogleButton } from '../utils/googleAuth'

export default function Register() {
  const { signup, setSession } = useAuth()
  const navigate  = useNavigate()
  const location  = useLocation()

  const [form, setForm] = useState({
    businessName: '',
    username: '',
    email: '',
    password: '',
    confirmPassword: '',
    country: 'India',
    phone: '',
    agreeTerms: false
  })
  const [error, setError] = useState('')
  const errorRef = useRef(null)
  const [loading, setLoading] = useState(false)
  const [waking, setWaking] = useState(false)

  // Real-time username availability
  const [checkingUname, setCheckingUname] = useState(false)
  const [unameAvailable, setUnameAvailable] = useState(null)

  // Google Sign-In / OAuth state
  const [showGoogleModal, setShowGoogleModal] = useState(false)
  const [googleCredential, setGoogleCredential] = useState('')
  const [googleOnboardingData, setGoogleOnboardingData] = useState(null)
  const googleBtnRef = useRef(null)

  const handleGoogleCredential = async (credential) => {
    setError('')
    setLoading(true)
    try {
      const res = await fetch(`${API_BASE}/api/auth/google/verify`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ credential }),
      })
      const data = await res.json()
      if (!res.ok) throw new Error(data?.detail || 'Google sign-in failed.')

      if (data.action === 'login' && data.token) {
        setSession(data)
        navigate('/', { replace: true })
      } else if (data.status === 'needs_onboarding') {
        setGoogleCredential(credential)
        setGoogleOnboardingData(data)
        setShowGoogleModal(true)
      }
    } catch (err) {
      setError(err?.message || 'Google authentication error')
    } finally {
      setLoading(false)
    }
  }

  const handleGoogleRegisterSuccess = (data) => {
    if (data?.token) {
      setSession(data)
      navigate('/', { replace: true })
    }
  }

  useEffect(() => {
    if (googleBtnRef.current) {
      renderGoogleButton(googleBtnRef.current, {
        onCredential: handleGoogleCredential,
        text: 'signup_with',
      })
    }
  }, [])

  // Live username availability check
  useEffect(() => {
    if (!form.username || form.username.trim().length < 3) {
      setUnameAvailable(null)
      return
    }
    const clean = form.username.trim()
    const timer = setTimeout(async () => {
      setCheckingUname(true)
      try {
        const res = await fetch(`${API_BASE}/api/auth/check-username?username=${encodeURIComponent(clean)}`)
        const data = await res.json()
        setUnameAvailable(data?.available ?? null)
      } catch {
        setUnameAvailable(null)
      } finally {
        setCheckingUname(false)
      }
    }, 350)
    return () => clearTimeout(timer)
  }, [form.username])
  useEffect(() => {
    setWaking(false)
    if (!loading || IS_LOCAL_APP) return
    const timer = setTimeout(() => setWaking(true), 4000)
    return () => clearTimeout(timer)
  }, [loading])
  const [showPasswordCriteria, setShowPasswordCriteria] = useState(false)
  const [showPassword, setShowPassword] = useState(false)
  const [showConfirmPassword, setShowConfirmPassword] = useState(false)
  const [templates, setTemplates] = useState([])
  const [selectedTemplate, setSelectedTemplate] = useState('general')
  // Where should this business's data live? Chosen at signup in the desktop
  // app (web always runs on cloud). 'local' just proceeds; 'cloud'/'hybrid'
  // route into the guarded switch flow after signup (never a silent switch).
  const [hostingChoice, setHostingChoice] = useState('hybrid')
  // First-time phone registrations receive the mandatory 14-day cloud trial.
  // Local + Cloud is preselected; choosing Local still keeps sync off by choice.
  const trialDays = 14
  // Set when Local + Cloud fell back to Local (no trial for this business):
  // say so before going in, instead of letting the sync quietly not happen.
  const [fallbackNote, setFallbackNote] = useState(null)

  useEffect(() => {
    if (location.state?.prefillUsername) {
      setForm(f => ({ ...f, username: location.state.prefillUsername }))
    }
  }, [location.state])

  useEffect(() => {
    // Templates come from the active backend; if the local (desktop) backend
    // can't serve them (older packaged build without the config JSONs), fall
    // back to the cloud, and finally to a built-in list — the Business
    // Category dropdown must never be empty. The built-in list mirrors
    // backend/core/templates/configs/*.json so an un-rebuilt desktop app still
    // shows every category (rebuild with the updated .spec restores the live list).
    const FALLBACK_TEMPLATES = [
      { key: 'general',      label: 'General Business' },
      { key: 'supermarket',  label: 'Supermarket / Retail' },
      { key: 'pharmacy',     label: 'Pharmacy / Medical' },
      { key: 'restaurant',   label: 'Restaurant / Café' },
      { key: 'electronics',  label: 'Electronics / Appliances' },
      { key: 'mobile',       label: 'Mobile / Accessories Shop' },
      { key: 'hardware',     label: 'Hardware / Electricals' },
      { key: 'repair',       label: 'Repair / Service Center' },
      { key: 'services',     label: 'Services / Professional' },
      { key: 'b2b_supplier', label: 'B2B Supplier' },
    ]
    const fetchTemplates = async (base) => {
      const res = await fetch(`${base}/business/templates`)
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const data = await res.json()
      return Array.isArray(data?.templates) && data.templates.length ? data.templates : null
    }
    ;(async () => {
      try {
        const t = await fetchTemplates(API_BASE)
        if (t) { setTemplates(t); return }
        throw new Error('empty template list')
      } catch (err) {
        logger.warn('Templates unavailable on active backend, trying cloud:', err?.message)
        try {
          if (CLOUD_URL !== API_BASE) {
            const t = await fetchTemplates(CLOUD_URL)
            if (t) { setTemplates(t); return }
          }
          throw new Error('empty cloud template list')
        } catch (err2) {
          logger.error('Failed to load templates from all sources — using built-in fallback:', err2?.message)
          setTemplates(FALLBACK_TEMPLATES)
        }
      }
    })()
  }, [])

  // Live password validation checks
  const pass = form.password
  const checks = {
    length: pass.length >= 8,
    upper: /[A-Z]/.test(pass),
    lower: /[a-z]/.test(pass),
    digit: /[0-9]/.test(pass)
  }
  const isPasswordValid = checks.length && checks.upper && checks.lower && checks.digit

  useEffect(() => {
    if (error) errorRef.current?.focus()
  }, [error])

  const handleSubmit = async e => {
    e.preventDefault()
    setError('')
    logger.debug('Registration submit triggered. Validating inputs...', {
      businessName: form.businessName,
      username: form.username,
      country: form.country,
      agreeTerms: form.agreeTerms
    })

    if (unameAvailable === false) {
      setError('This username is already taken. Please choose another username.')
      return
    }
    if (!isPasswordValid) {
      logger.warn('Registration failed client validation: Password strength criteria not met.')
      setError('Password does not meet all strength requirements.')
      return
    }
    if (!form.agreeTerms) {
      logger.warn('Registration failed client validation: User did not agree to terms.')
      setError('You must agree to the Terms of Service.')
      return
    }
    if (form.password !== form.confirmPassword) {
      setError('Passwords do not match.')
      return
    }
    let phone
    try {
      phone = normalizeRegistrationPhone(form.phone, form.country)
    } catch (err) {
      setError(err.message)
      return
    }
    logger.info('Client validation passed. Calling signup API for username:', form.username)
    setLoading(true)
    try {
      const result = await signup({
        username: form.username,
        password: form.password,
        business_name: form.businessName,
        template_key: selectedTemplate,
        hosting: IS_LOCAL_APP ? hostingChoice : 'cloud',
        phone,
        email: form.email?.trim() || null,
      })
      logger.info('Registration completed successfully!')
      if (result?.fellBackToLocal) {
        setFallbackNote('This business did not get a Pro trial (for example, the phone number already had one), '
          + 'so your data stays on this computer (Local). You can turn on Local + Cloud in Settings once you have Pro.')
        return
      }
      if (result?.trialUnavailable) {
        setFallbackNote('This phone number has already used its first-time trial. Your account is ready on the cloud. Upgrade to Pro for Local + Cloud sync, or download the desktop app for Local billing.')
        return
      }
      // Hosting is auto-configured inside signup() from the choice above (Local, or
      // Local + Cloud which turns on background sync). There is no separate
      // onboarding, migration, or re-login — a brand-new account has no data to
      // move — so we go straight to the app.
      navigate('/', { replace: true })
    } catch (err) {
      logger.error('Registration signup API call failed:', err.message)
      setError(err.message || 'Registration failed. Please check details and try again.')
    } finally {
      setLoading(false)
    }
  }

  return (
    <>
    <div className="split-page registration-page roadmap-auth">
      <AuthRoadmap interactive={false} />
      <AuthThemeToggle />
      {/* Left Panel: Registration Card */}
      <div className="split-left">
        <div className="login-card login-card--wide">
          {waking && <p role="status">Waking up the server… this can take up to a minute.</p>}
          <div className="login-glow"></div>
          <div className="login-symbol" style={{ marginBottom: 4 }}><BuildingMark size={32} /></div>
          <h1 className="login-title" style={{ fontSize: 24 }}>Create your account</h1>
          <p className="registration-form-intro">A few details. A fresh start for your business.</p>

          <p className="registration-signin">Already have an account? <Link to="/login">Sign in</Link></p>

          {fallbackNote ? (
            <div className="login-form" style={{ gap: 12 }} data-testid="hosting-fallback">
              <div style={{ fontSize: '0.84rem', color: 'var(--text-secondary)', lineHeight: 1.5, padding: '10px 12px', borderRadius: 10, border: '1px solid var(--border)', background: 'var(--bg-2)' }}>
                <strong style={{ color: 'var(--text-primary)' }}>Your account is ready.</strong> {fallbackNote}
              </div>
              <button className="login-submit-btn" type="button" style={{ padding: '10px' }} onClick={() => navigate('/', { replace: true })}>
                Continue to STATER Bill
              </button>
            </div>
          ) : (
          <form className="login-form" id="register-form" onSubmit={handleSubmit} style={{ gap: 10 }}>
            {/* Google Quick Sign-Up */}
            <div style={{ marginBottom: 12 }}>
              <div className="registration-google" ref={googleBtnRef} style={{ display: 'flex', justifyContent: 'center', minHeight: 44 }} />
              <div style={{
                display: 'flex',
                alignItems: 'center',
                margin: '14px 0 10px',
                gap: 12
              }}>
                <div style={{ flex: 1, height: 1, background: 'var(--border)' }} />
                <span style={{ fontSize: '0.74rem', color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
                  or register manually
                </span>
                <div style={{ flex: 1, height: 1, background: 'var(--border)' }} />
              </div>
            </div>

            <div className="form-group">
              <label htmlFor="businessName">Business name</label>
              <input
                id="businessName"
                type="text"
                value={form.businessName}
                onChange={e => setForm(f => ({ ...f, businessName: e.target.value }))}
                required
              />
            </div>

            <div className="form-group" style={{ marginTop: '4px' }}>
              <label htmlFor="businessTemplate">Business Category</label>
              <CustomSelect
                id="businessTemplate"
                value={selectedTemplate}
                onChange={e => setSelectedTemplate(e.target.value)}
                style={{
                  width: '100%',
                  padding: '9px 12px',
                  borderRadius: '10px',
                  border: '1.5px solid var(--border)',
                  background: 'var(--bg-2)',
                  fontSize: '13px',
                  color: 'var(--text-primary)',
                  outline: 'none'
                }}
              >
                {templates.map(t => (
                  <option key={t.key} value={t.key}>
                    {t.label}
                  </option>
                ))}
              </CustomSelect>
            </div>

            <div className="form-group" style={{ marginTop: '4px' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <label htmlFor="username">Store username</label>
                {checkingUname && <span style={{ fontSize: '0.72rem', color: 'var(--text-muted)' }}>Checking…</span>}
                {!checkingUname && unameAvailable === true && (
                  <span style={{ fontSize: '0.72rem', color: 'var(--success, #10b981)', fontWeight: 600 }}>✓ Available</span>
                )}
                {!checkingUname && unameAvailable === false && (
                  <span style={{ fontSize: '0.72rem', color: 'var(--error, #ef4444)', fontWeight: 600 }}>✕ Already taken</span>
                )}
              </div>
              <input
                id="username"
                aria-label="Store Username"
                type="text"
                value={form.username}
                onChange={e => setForm(f => ({ ...f, username: e.target.value.toLowerCase().replace(/\s+/g, '_') }))}
                required
                autoComplete="username"
              />
            </div>

            {/* Row with Country & Mandatory Phone */}
            <div className="registration-extra-grid">
              <div className="form-group">
                <label htmlFor="country">Country</label>
                <CustomSelect
                  id="country"
                  value={form.country}
                  onChange={e => setForm(f => ({ ...f, country: e.target.value }))}
                  style={{
                    width: '100%',
                    padding: '9px 12px',
                    borderRadius: '10px',
                    border: '1.5px solid var(--border)',
                    background: 'var(--bg-2)',
                    fontSize: '13px',
                    color: 'var(--text-primary)',
                    outline: 'none'
                  }}
                >
                  <option value="India">India</option>
                  <option value="United States">United States</option>
                  <option value="United Kingdom">United Kingdom</option>
                  <option value="Singapore">Singapore</option>
                  <option value="UAE">UAE</option>
                </CustomSelect>
              </div>

              <div className="form-group">
                <label htmlFor="phone">Phone</label>
                <input
                  id="phone"
                  aria-label="Phone"
                  type="tel"
                  required
                  autoComplete="tel"
                  maxLength={30}
                  aria-describedby="registration-account-help"
                    value={form.phone}
                  onChange={e => setForm(f => ({ ...f, phone: e.target.value }))}
                />
              </div>
            </div>

            {/* Email Address */}
            <div className="form-group" style={{ marginTop: '4px' }}>
              <label htmlFor="email">Email (optional)</label>
              <input
                id="email"
                type="email"
                value={form.email}
                onChange={e => setForm(f => ({ ...f, email: e.target.value }))}
                autoComplete="email"
              />
            </div>

              <fieldset className="registration-storage">
                <legend>Billing setup</legend>
                <div data-testid="hosting-choice" className="registration-storage-grid">
                  {[
                    { key: 'local',  title: 'Local only',     desc: 'Offline on this computer.' },
                    { key: 'hybrid', title: 'Local + Cloud',  desc: 'Desktop + browser, connected.' },
                  ].map(opt => (
                    <div key={opt.key} className="registration-storage-choice">
                    <button
                      type="button"
                      disabled={!IS_LOCAL_APP && opt.key === 'local'}
                      className={`registration-storage-option ${hostingChoice === opt.key ? 'is-selected' : ''}`}
                      aria-pressed={hostingChoice === opt.key}
                      onClick={() => setHostingChoice(opt.key)}
                    >
                      <div style={{ fontWeight: 700, fontSize: '0.86rem' }}>
                        {opt.title}
                        {opt.key === 'hybrid' && trialDays > 0 && (
                          <span style={{ marginLeft: 6, fontSize: '0.62rem', fontWeight: 800, letterSpacing: '0.04em', padding: '1px 6px', borderRadius: 6, background: 'var(--accent-solid, var(--accent))', color: 'var(--accent-foreground, #fff)', verticalAlign: 'middle' }}>
                            14 DAYS FREE
                          </span>
                        )}
                      </div>
                      <div style={{ fontSize: '0.72rem', color: 'var(--text-muted)', marginTop: 3, lineHeight: 1.3 }}>{opt.desc}</div>
                    </button>
                    {!IS_LOCAL_APP && opt.key === 'local' && (
                      <a className="registration-local-download" href={DESKTOP_DOWNLOAD_URL} target="_blank" rel="noopener noreferrer">Download app for Local</a>
                    )}
                    </div>
                  ))}
                </div>
                {IS_LOCAL_APP && hostingChoice === 'hybrid' && (
                  <div style={{ fontSize: '0.72rem', color: 'var(--text-muted)', marginTop: 6 }}>
                    Sync is included during your eligible {trialDays}-day Pro trial. Upgrade to Pro to keep syncing afterward.
                  </div>
                )}
              </fieldset>

            <div className="form-group" style={{ marginTop: '4px' }}>
              <label htmlFor="password">Password</label>
              <div style={{ position: 'relative' }}>
                <input
                  id="password"
                  type={showPassword ? "text" : "password"}
                  placeholder="••••••••"
                  value={form.password}
                  onFocus={() => setShowPasswordCriteria(true)}
                  onChange={e => setForm(f => ({ ...f, password: e.target.value }))}
                  aria-describedby="password-requirements"
                  aria-invalid={form.password.length > 0 && !isPasswordValid}
                  required
                  style={{ width: '100%', paddingRight: '40px' }}
                />
                <button
                  type="button"
                  onClick={() => setShowPassword(!showPassword)}
                  aria-label={showPassword ? 'Hide password' : 'Show password'}
                  aria-pressed={showPassword}
                  style={{ position: 'absolute', right: '10px', top: '50%', transform: 'translateY(-50%)', color: 'var(--text-muted)' }}
                >
                  {showPassword ? <EyeOffIcon size={16} /> : <EyeIcon size={16} />}
                </button>
              </div>
              {showPasswordCriteria && (
                <div id="password-requirements" className="password-criteria" aria-live="polite" style={{ marginTop: 6, padding: '8px 12px' }}>
                  <div className={`criteria-item ${checks.length ? 'met' : ''}`} style={{ display: 'flex', gap: 6, fontSize: '0.75rem', color: checks.length ? 'var(--success)' : 'var(--text-muted)' }}>
                    <span>{checks.length ? '✓' : '○'}</span> At least 8 characters
                  </div>
                  <div className={`criteria-item ${checks.upper ? 'met' : ''}`} style={{ display: 'flex', gap: 6, fontSize: '0.75rem', color: checks.upper ? 'var(--success)' : 'var(--text-muted)' }}>
                    <span>{checks.upper ? '✓' : '○'}</span> One uppercase letter (A-Z)
                  </div>
                  <div className={`criteria-item ${checks.lower ? 'met' : ''}`} style={{ display: 'flex', gap: 6, fontSize: '0.75rem', color: checks.lower ? 'var(--success)' : 'var(--text-muted)' }}>
                    <span>{checks.lower ? '✓' : '○'}</span> One lowercase letter (a-z)
                  </div>
                  <div className={`criteria-item ${checks.digit ? 'met' : ''}`} style={{ display: 'flex', gap: 6, fontSize: '0.75rem', color: checks.digit ? 'var(--success)' : 'var(--text-muted)' }}>
                    <span>{checks.digit ? '✓' : '○'}</span> One number (0-9)
                  </div>
                </div>
              )}
            </div>

            {form.password.length > 0 && (
              <div className="form-group" style={{ marginTop: '4px' }}>
                <label htmlFor="confirmPassword">Confirm Password</label>
                <div style={{ position: 'relative' }}>
                  <input
                    id="confirmPassword"
                    type={showConfirmPassword ? "text" : "password"}
                    placeholder="••••••••"
                    value={form.confirmPassword}
                    onChange={e => setForm(f => ({ ...f, confirmPassword: e.target.value }))}
                    aria-describedby={form.confirmPassword && form.password !== form.confirmPassword ? 'confirm-password-error' : undefined}
                    aria-invalid={form.confirmPassword.length > 0 && form.password !== form.confirmPassword}
                    required
                    style={{ 
                      width: '100%', 
                      paddingRight: '40px',
                      borderColor: form.confirmPassword ? (form.password === form.confirmPassword ? 'var(--success)' : 'var(--error)') : 'var(--border)'
                    }}
                  />
                  <button
                    type="button"
                    onClick={() => setShowConfirmPassword(!showConfirmPassword)}
                  aria-label={showConfirmPassword ? 'Hide confirm password' : 'Show confirm password'}
                  aria-pressed={showConfirmPassword}
                    style={{ position: 'absolute', right: '10px', top: '50%', transform: 'translateY(-50%)', color: 'var(--text-muted)' }}
                  >
                    {showConfirmPassword ? <EyeOffIcon size={16} /> : <EyeIcon size={16} />}
                  </button>
                </div>
                {form.confirmPassword && form.password !== form.confirmPassword && (
                  <div id="confirm-password-error" role="alert" style={{ fontSize: '0.75rem', color: 'var(--error)', marginTop: 4 }}>Passwords do not match</div>
                )}
              </div>
            )}

            <fieldset style={{ border: 0, padding: 0, margin: '8px 0 6px 0', minWidth: 0 }}>
              <legend style={{ position: 'absolute', width: 1, height: 1, padding: 0, margin: -1, overflow: 'hidden', clip: 'rect(0, 0, 0, 0)', whiteSpace: 'nowrap', border: 0 }}>Terms agreement</legend>
              <div style={{ display: 'flex', alignItems: 'flex-start', gap: 8 }}>
                <input
                  id="agreeTerms"
                  type="checkbox"
                  checked={form.agreeTerms}
                  onChange={e => setForm(f => ({ ...f, agreeTerms: e.target.checked }))}
                  aria-describedby="terms-help"
                  style={{ cursor: 'pointer', accentColor: 'var(--accent)', marginTop: 2, flexShrink: 0 }}
                  required
                />
                <label htmlFor="agreeTerms" style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', cursor: 'pointer', lineHeight: 1.35 }}>
                  I agree to the <a href="/terms" target="_blank" rel="noopener noreferrer" style={{ color: 'var(--accent, #c15f3c)', textDecoration: 'underline' }}>Terms of Service</a> and acknowledge the <a href="/privacy" target="_blank" rel="noopener noreferrer" style={{ color: 'var(--accent, #c15f3c)', textDecoration: 'underline' }}>Privacy Policy</a>.
                </label>
              </div>
              <div id="terms-help" style={{ fontSize: '0.7rem', color: 'var(--text-muted)', marginLeft: 24, marginTop: 3 }}>
                We use these details to create and secure your business account.
              </div>
            </fieldset>

            {error && (
              <div ref={errorRef} className="login-error" role="alert" aria-live="assertive" tabIndex="-1" style={{ margin: '4px 0', padding: '8px' }}>
                {error}
              </div>
            )}

            <button
              className="login-submit-btn"
              type="submit"
              disabled={loading}
              style={{ marginTop: '4px', padding: '10px' }}
            >
              {loading ? 'Creating Account…' : 'Create account'}
            </button>
          </form>
          )}
        </div>
      </div>

      <aside className="split-right" aria-label="What you can do with STATER Bill">
        <RegistrationStory />
      </aside>
    </div>

    {/* Google Onboarding Modal (for first-time Google sign-ups) */}
    <GoogleOnboardingModal
      isOpen={showGoogleModal}
      credential={googleCredential}
      initialData={googleOnboardingData}
      onClose={() => setShowGoogleModal(false)}
      onSuccess={handleGoogleRegisterSuccess}
    />
    </>
  )
}
