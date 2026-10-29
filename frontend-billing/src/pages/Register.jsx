// ============================================================================
// Page: Register.jsx
// Description: Merchant sign-up page. Handles creating new business owner accounts
//              and configuring baseline settings.
// ============================================================================
import React, { useState, useEffect, useRef } from 'react'
import { API_BASE, CLOUD_URL, IS_LOCAL_APP } from '../config'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../contexts/AuthContext'
import { logger } from '../utils/logger'
import {
  SummaryIcon,
  CounterIcon,
  InventoryIcon,
  ReportsIcon,
  EyeIcon,
  EyeOffIcon
} from '../components/Icons'
import { BuildingMark } from '../components/Logo'
import CustomSelect from '../components/common/CustomSelect'
import { DESKTOP_DOWNLOAD_URL } from '../config/downloadApp'
import './registration.css'
import { normalizeRegistrationPhone } from '../utils/registrationPhone'

export default function Register() {
  const { signup } = useAuth()
  const navigate  = useNavigate()

  const [form, setForm] = useState({
    businessName: '',
    username: '',
    password: '',
    confirmPassword: '',
    country: 'India',
    phone: '',
    agreeTerms: false
  })
  const [error, setError] = useState('')
  const errorRef = useRef(null)
  const [loading, setLoading] = useState(false)
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
    {/* Blurred Backdrop */}
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

    {/* Split Page Container (placed on top of backdrop) */}
    <div className="split-page registration-page" style={{ position: 'relative', zIndex: 2 }}>
      {/* Left Panel: Registration Card */}
      <div className="split-left" style={{ position: 'relative', background: 'transparent', padding: '16px 20px' }}>
        <div className="login-card" style={{ maxWidth: '440px', width: '100%', margin: 'auto', padding: '24px 28px' }}>
          <div className="login-glow"></div>
          <div className="login-symbol" style={{ marginBottom: 4 }}><BuildingMark size={32} /></div>
          <h1 className="login-title" style={{ fontSize: 24 }}>Create your account</h1>
          <p className="login-subtitle" style={{ marginBottom: 12 }}>ADVANCED BILLING SYSTEM</p>

          <div className="login-tabs" style={{ marginBottom: 16 }}>
            <button
              type="button"
              className="login-tab-btn"
              onClick={() => navigate('/login')}
            >
              Sign In
            </button>
            <button
              type="button"
              className="login-tab-btn active"
              onClick={() => {}}
            >
              Register
            </button>
          </div>

          {fallbackNote ? (
            <div className="login-form" style={{ gap: 12 }} data-testid="hosting-fallback">
              <div style={{ fontSize: '0.84rem', color: 'var(--text-secondary)', lineHeight: 1.5, padding: '10px 12px', borderRadius: 10, border: '1px solid var(--border)', background: 'var(--bg-2)' }}>
                <strong style={{ color: 'var(--text-primary)' }}>Your account is ready.</strong> {fallbackNote}
              </div>
              <button className="login-submit-btn" type="button" style={{ padding: '10px' }} onClick={() => navigate('/', { replace: true })}>
                Continue to BizAssist
              </button>
            </div>
          ) : (
          <form className="login-form" id="register-form" onSubmit={handleSubmit} style={{ gap: 10 }}>
            <div className="form-group">
              <label htmlFor="businessName">Business / Organization Name</label>
              <input
                id="businessName"
                type="text"
                placeholder="e.g. Acme Corporation"
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

            <fieldset className="registration-storage">
              <legend>Where should your data live?</legend>
              <div data-testid="hosting-choice" className="registration-storage-grid">
                {[
                  { key: 'local',  title: 'Local only',     desc: 'Fast & offline on this PC.' },
                  { key: 'hybrid', title: 'Local + Cloud',  desc: IS_LOCAL_APP
                    ? 'Local speed + automatic cloud sync, backup & multi-device.'
                    : 'Use cloud in browser + desktop app sync.' },
                ].map(opt => (
                  <div key={opt.key} className="registration-storage-choice">
                  <button
                    type="button"
                    className={`registration-storage-option ${hostingChoice === opt.key ? 'is-selected' : ''}`}
                    aria-pressed={hostingChoice === opt.key}
                    disabled={!IS_LOCAL_APP && opt.key === 'local'}
                    aria-describedby={!IS_LOCAL_APP ? 'cloud-storage-help' : undefined}
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
                  {trialDays > 0
                    ? `Included in your ${trialDays}-day Pro trial and set up automatically: billing stays fast and offline while your data syncs to the cloud. When the trial ends, cloud sync stops unless you upgrade to Pro. Everything stays on this computer and keeps working offline.`
                    : 'Set up automatically — no extra steps. Billing stays fast and offline while your data syncs to the cloud in the background.'}
                </div>
              )}
            </fieldset>

            <div className="form-group" style={{ marginTop: '4px' }}>
              <label htmlFor="username">Username or Email</label>
              <input
                id="username"
                type="text"
                placeholder="e.g. store"
                value={form.username}
                onChange={e => setForm(f => ({ ...f, username: e.target.value }))}
                required
              />
            </div>

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

            {/* Row with Country & Phone */}
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12, marginTop: '4px' }}>
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
                  type="tel"
                  required
                  autoComplete="tel"
                  maxLength={30}
                  aria-describedby="registration-phone-help"
                  placeholder="+91 9999999999"
                  value={form.phone}
                  onChange={e => setForm(f => ({ ...f, phone: e.target.value }))}
                />
                <small id="registration-phone-help" style={{ color: 'var(--text-muted)', fontSize: '0.7rem' }}>Required. One first-time trial per phone number.</small>
              </div>
            </div>

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
                  I agree to the Terms of Service and acknowledge the Privacy Notice.
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
              {loading ? 'Registering…' : 'Get Started'}
            </button>
          </form>
          )}
        </div>
      </div>

      {/* Right Panel: Value Showcase & Storage Guide */}
      <div className="split-right" style={{ background: 'var(--bg-2)', borderLeft: '1px solid var(--border)' }}>
        <div style={{ maxWidth: '480px', margin: '0 auto', width: '100%' }}>

          {/* In Cloud URL: Highlight Desktop App Download */}
          {!IS_LOCAL_APP && (
            <div style={{
              background: 'linear-gradient(135deg, var(--bg-1, #f4f4f1) 0%, var(--accent-dim) 100%)',
              border: '1.5px solid var(--accent)',
              borderRadius: 14,
              padding: '16px 18px',
              marginBottom: 24,
              boxShadow: 'var(--shadow-sm)'
            }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 6 }}>
                <span style={{
                  fontSize: '0.65rem',
                  fontWeight: 800,
                  textTransform: 'uppercase',
                  letterSpacing: '0.05em',
                  background: 'var(--accent)',
                  color: '#ffffff',
                  padding: '2px 8px',
                  borderRadius: 5
                }}>
                  Recommended for POS &amp; Counters
                </span>
              </div>
              <h3 style={{ fontSize: '1rem', fontWeight: 700, color: 'var(--text-primary)', margin: '0 0 6px' }}>
                Want 100% Offline Billing? Download the Desktop App
              </h3>
              <p style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', margin: '0 0 12px', lineHeight: 1.45 }}>
                Create your account here in the browser, then install the desktop app to get zero-latency local billing that syncs automatically with your cloud store.
              </p>
              <a
                href={DESKTOP_DOWNLOAD_URL}
                target="_blank"
                rel="noopener noreferrer"
                className="btn btn-primary"
                style={{
                  display: 'inline-flex',
                  alignItems: 'center',
                  gap: 8,
                  padding: '7px 14px',
                  fontSize: '0.8rem',
                  fontWeight: 600,
                  textDecoration: 'none'
                }}
              >
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path>
                  <polyline points="7 10 12 15 17 10"></polyline>
                  <line x1="12" y1="15" x2="12" y2="3"></line>
                </svg>
                Download Desktop App
              </a>
            </div>
          )}

          {/* Storage & Hosting Explanation in Right Panel */}
          <div className="registration-storage-help" id="cloud-storage-help" style={{
            background: 'var(--bg-3)',
            border: '1px solid var(--border)',
            borderRadius: 12,
            padding: '14px 16px',
            marginBottom: 24,
            marginTop: 0
          }}>
            <div style={{ fontSize: '0.75rem', fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.05em', color: 'var(--text-muted)', marginBottom: 8 }}>
              Where should your data live?
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8, fontSize: '0.8rem', lineHeight: 1.45, color: 'var(--text-secondary)' }}>
              <p style={{ margin: 0 }}>
                <strong style={{ color: 'var(--text-primary)' }}>• Local only:</strong> Billing records stay on this computer. Works offline without internet. Ideal for isolated single-counter setups.
              </p>
              <p style={{ margin: 0 }}>
                <strong style={{ color: 'var(--text-primary)' }}>• Local + Cloud:</strong> This browser uses the cloud database; offline Local billing runs in the downloaded app. Sign in with the same account in the desktop app to add Local billing.
              </p>
              <p style={{ margin: 0, fontSize: '0.75rem', color: 'var(--text-muted)', borderTop: '1px solid var(--border)', paddingTop: 6 }}>
                Your first registration with a phone number includes 14 days of Pro access, including Local + Cloud and Field Team.
              </p>
            </div>
          </div>

          <h2 style={{ fontSize: '1.45rem', fontWeight: 700, color: 'var(--text-primary)', marginBottom: 12, lineHeight: 1.25 }}>
            Manage all your businesses from one unified platform.
          </h2>
          <p style={{ fontSize: '0.85rem', color: 'var(--text-secondary)', marginBottom: 24, lineHeight: 1.5 }}>
            Supercharge your administration with multi-business GST invoices, automated expense ingestion, and dynamic reporting.
          </p>

          <div style={{ display: 'flex', flexDirection: 'column', gap: 24 }}>
            <div style={{ display: 'flex', gap: 16, alignItems: 'flex-start' }}>
              <div style={{ width: 36, height: 36, borderRadius: '50%', background: 'var(--accent-dim)', color: 'var(--accent)', display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0, paddingLeft: 8, paddingTop: 8 }}>
                <SummaryIcon size={18} />
              </div>
              <div>
                <div style={{ fontWeight: 600, fontSize: '0.95rem', color: 'var(--text-primary)' }}>Multi-Business Support</div>
                <div style={{ fontSize: '0.82rem', color: 'var(--text-secondary)', marginTop: 2 }}>Switch organizations seamlessly and keep ledgers entirely separate.</div>
              </div>
            </div>

            <div style={{ display: 'flex', gap: 16, alignItems: 'flex-start' }}>
              <div style={{ width: 36, height: 36, borderRadius: '50%', background: 'var(--accent-dim)', color: 'var(--accent)', display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0, paddingLeft: 8, paddingTop: 8 }}>
                <CounterIcon size={18} />
              </div>
              <div>
                <div style={{ fontWeight: 600, fontSize: '0.95rem', color: 'var(--text-primary)' }}>Professional Invoicing</div>
                <div style={{ fontSize: '0.82rem', color: 'var(--text-secondary)', marginTop: 2 }}>Generate premium, GST-compliant invoices and track unpaid accounts.</div>
              </div>
            </div>

            <div style={{ display: 'flex', gap: 16, alignItems: 'flex-start' }}>
              <div style={{ width: 36, height: 36, borderRadius: '50%', background: 'var(--accent-dim)', color: 'var(--accent)', display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0, paddingLeft: 8, paddingTop: 8 }}>
                <InventoryIcon size={18} />
              </div>
              <div>
                <div style={{ fontWeight: 600, fontSize: '0.95rem', color: 'var(--text-primary)' }}>Inventory &amp; Stock Ledger</div>
                <div style={{ fontSize: '0.82rem', color: 'var(--text-secondary)', marginTop: 2 }}>Adjust stock quantities, set low-inventory thresholds, and track suppliers.</div>
              </div>
            </div>

            <div style={{ display: 'flex', gap: 16, alignItems: 'flex-start' }}>
              <div style={{ width: 36, height: 36, borderRadius: '50%', background: 'var(--accent-dim)', color: 'var(--accent)', display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0, paddingLeft: 8, paddingTop: 8 }}>
                <ReportsIcon size={18} />
              </div>
              <div>
                <div style={{ fontWeight: 600, fontSize: '0.95rem', color: 'var(--text-primary)' }}>Real-time Accounting Reports</div>
                <div style={{ fontSize: '0.82rem', color: 'var(--text-secondary)', marginTop: 2 }}>Instantly download P&amp;L reports, tax summaries, and customer statements.</div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
    </>
  )
}
