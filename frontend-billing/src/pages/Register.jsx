import React, { useState, useEffect } from 'react'
import { API_BASE, CLOUD_URL } from '../config'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../contexts/AuthContext'
import { logger } from '../utils/logger'
import {
  SummaryIcon,
  CounterIcon,
  InventoryIcon,
  ReportsIcon
} from '../components/Icons'
import { BuildingMark } from '../components/Logo'

export default function Register() {
  const { signup } = useAuth()
  const navigate  = useNavigate()

  const [form, setForm] = useState({
    businessName: '',
    username: '',
    password: '',
    country: 'India',
    phone: '',
    agreeTerms: false
  })
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const [showPasswordCriteria, setShowPasswordCriteria] = useState(false)
  const [existing, setExisting] = useState(false)   // username already taken on the cloud (the registry)

  // Pre-check a username against the CLOUD (the identity authority) so we can
  // branch to "log in" instead of failing the whole registration on submit.
  const checkUsername = async (u) => {
    u = (u ?? form.username ?? '').trim()
    if (!u) { setExisting(false); return }
    try {
      const r = await fetch(`${CLOUD_URL}/api/identity/check`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username: u }),
      })
      if (r.ok) setExisting((await r.json())?.exists === true)
    } catch { /* offline / cloud unreachable → skip; signup will surface it on submit */ }
  }

  // Live (debounced) check as the user types the username.
  useEffect(() => {
    const u = (form.username || '').trim()
    if (!u) { setExisting(false); return }
    const t = setTimeout(() => checkUsername(u), 450)
    return () => clearTimeout(t)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [form.username])

  const [templates, setTemplates] = useState([])
  const [selectedTemplate, setSelectedTemplate] = useState('general')

  useEffect(() => {
    fetch(`${API_BASE}/business/templates`)
      .then(res => res.ok ? res.json() : {})
      .then(data => {
        if (data && data.templates) {
          setTemplates(data.templates)
        }
      })
      .catch(err => logger.error('Failed to load templates:', err))
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

  const handleSubmit = async e => {
    e.preventDefault()
    setError('')
    logger.debug('Registration submit triggered. Validating inputs...', {
      businessName: form.businessName,
      username: form.username,
      country: form.country,
      phone: form.phone,
      agreeTerms: form.agreeTerms
    })

    if (!isPasswordValid) {
      logger.warn('Registration failed client validation: Password strength criteria not met.')
      setError('Password does not meet all strength requirements.')
      return
    }
    if (!form.agreeTerms) {
      logger.warn('Registration failed client validation: User did not agree to terms.')
      setError('You must agree to the Terms of Service to create an account.')
      return
    }
    if (existing) {
      setError('An account with this username already exists. Please log in instead.')
      return
    }

    logger.info('Client validation passed. Calling signup API for username:', form.username)
    setLoading(true)
    try {
      await signup({
        username: form.username,
        password: form.password,
        business_name: form.businessName,
        template_key: selectedTemplate
      })
      logger.info('Registration completed successfully! Navigating to dashboard.')
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
    <div className="split-page" style={{ position: 'relative', zIndex: 2 }}>
      {/* Left Panel: Registration Card */}
      <div className="split-left" style={{ position: 'relative', background: 'transparent', padding: '16px 20px' }}>
        <div className="login-card" style={{ maxWidth: '440px', width: '100%', margin: '0 auto', padding: '24px 28px' }}>
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
              <select
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
              </select>
            </div>

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
              {existing && (
                <div style={{
                  marginTop: 6, fontSize: '0.78rem', color: 'var(--text-muted)',
                  display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap',
                }}>
                  <span>An account with this username already exists.</span>
                  <button
                    type="button"
                    onClick={() => navigate('/login')}
                    style={{ background: 'none', border: 'none', color: 'var(--accent)', cursor: 'pointer', fontWeight: 700, padding: 0, textDecoration: 'underline' }}
                  >
                    Log in instead
                  </button>
                </div>
              )}
            </div>

            <div className="form-group" style={{ marginTop: '4px' }}>
              <label htmlFor="password">Password</label>
              <input
                id="password"
                type="password"
                placeholder="••••••••"
                value={form.password}
                onFocus={() => setShowPasswordCriteria(true)}
                onChange={e => setForm(f => ({ ...f, password: e.target.value }))}
                required
              />
              {showPasswordCriteria && (
                <div className="password-criteria" style={{ marginTop: 6, padding: '8px 12px' }}>
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

            {/* Row with Country & Phone */}
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12, marginTop: '4px' }}>
              <div className="form-group">
                <label htmlFor="country">Country</label>
                <select
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
                </select>
              </div>

              <div className="form-group">
                <label htmlFor="phone">Phone (Optional)</label>
                <input
                  id="phone"
                  type="text"
                  placeholder="+91 9999999999"
                  value={form.phone}
                  onChange={e => setForm(f => ({ ...f, phone: e.target.value }))}
                />
              </div>
            </div>

            <div style={{ display: 'flex', alignItems: 'flex-start', gap: 8, margin: '8px 0 6px 0' }}>
              <input
                id="agreeTerms"
                type="checkbox"
                checked={form.agreeTerms}
                onChange={e => setForm(f => ({ ...f, agreeTerms: e.target.checked }))}
                style={{ marginTop: 3, cursor: 'pointer' }}
                required
              />
              <label htmlFor="agreeTerms" style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', cursor: 'pointer', lineHeight: 1.35 }}>
                I agree to the local data storage Terms of Service.
              </label>
            </div>

            {error && (
              <div className="login-error" style={{ margin: '4px 0', padding: '8px' }}>
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
        </div>
      </div>

      {/* Right Panel: Value Showcase */}
      <div className="split-right" style={{ background: 'var(--bg-2)', borderLeft: '1px solid var(--border)', display: 'flex', flexDirection: 'column', justifyContent: 'center' }}>
        <div style={{ maxWidth: '480px', margin: '0 auto' }}>
          <h2 style={{ fontSize: '1.75rem', fontWeight: 700, color: 'var(--text-primary)', marginBottom: 16, lineHeight: 1.25 }}>
            Manage all your businesses from one unified platform.
          </h2>
          <p style={{ fontSize: '0.9rem', color: 'var(--text-secondary)', marginBottom: 36, lineHeight: 1.5 }}>
            Supercharge your administration with multi-business GST invoices, automated expense ingestion, and dynamic reporting.
          </p>

          <div style={{ display: 'flex', flexDirection: 'column', gap: 24 }}>
            <div style={{ display: 'flex', gap: 16, alignItems: 'flex-start' }}>
              <div style={{ width: 36, height: 36, borderRadius: '50%', background: 'var(--accent-dim)', color: 'var(--accent)', display: 'flex', alignItems: 'center', justifyCenter: 'center', flexShrink: 0, paddingLeft: 8, paddingTop: 8 }}>
                <SummaryIcon size={18} />
              </div>
              <div>
                <div style={{ fontWeight: 600, fontSize: '0.95rem', color: 'var(--text-primary)' }}>Multi-Business Support</div>
                <div style={{ fontSize: '0.82rem', color: 'var(--text-secondary)', marginTop: 2 }}>Switch organizations seamlessly and keep ledgers entirely separate.</div>
              </div>
            </div>

            <div style={{ display: 'flex', gap: 16, alignItems: 'flex-start' }}>
              <div style={{ width: 36, height: 36, borderRadius: '50%', background: 'var(--accent-dim)', color: 'var(--accent)', display: 'flex', alignItems: 'center', justifyCenter: 'center', flexShrink: 0, paddingLeft: 8, paddingTop: 8 }}>
                <CounterIcon size={18} />
              </div>
              <div>
                <div style={{ fontWeight: 600, fontSize: '0.95rem', color: 'var(--text-primary)' }}>Professional Invoicing</div>
                <div style={{ fontSize: '0.82rem', color: 'var(--text-secondary)', marginTop: 2 }}>Generate premium, GST-compliant invoices and track unpaid accounts.</div>
              </div>
            </div>

            <div style={{ display: 'flex', gap: 16, alignItems: 'flex-start' }}>
              <div style={{ width: 36, height: 36, borderRadius: '50%', background: 'var(--accent-dim)', color: 'var(--accent)', display: 'flex', alignItems: 'center', justifyCenter: 'center', flexShrink: 0, paddingLeft: 8, paddingTop: 8 }}>
                <InventoryIcon size={18} />
              </div>
              <div>
                <div style={{ fontWeight: 600, fontSize: '0.95rem', color: 'var(--text-primary)' }}>Inventory &amp; Stock Ledger</div>
                <div style={{ fontSize: '0.82rem', color: 'var(--text-secondary)', marginTop: 2 }}>Adjust stock quantities, set low-inventory thresholds, and track suppliers.</div>
              </div>
            </div>

            <div style={{ display: 'flex', gap: 16, alignItems: 'flex-start' }}>
              <div style={{ width: 36, height: 36, borderRadius: '50%', background: 'var(--accent-dim)', color: 'var(--accent)', display: 'flex', alignItems: 'center', justifyCenter: 'center', flexShrink: 0, paddingLeft: 8, paddingTop: 8 }}>
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
