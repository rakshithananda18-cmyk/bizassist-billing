// ============================================================================
// Page: Login.jsx
// Description: User session authentication page. Supports merchant owner credentials
//              as well as cashier staff login credentials, storing tokens in localStorage.
// ============================================================================
import React, { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../contexts/AuthContext'
import { logger } from '../utils/logger'
import { BuildingMark } from '../components/Logo'
import { API_BASE } from '../config'
import CustomSelect from '../components/common/CustomSelect'

export default function Login() {
  const { login, staffLogin } = useAuth()
  const navigate  = useNavigate()

  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [showPw,   setShowPw]   = useState(false)
  const [error,    setError]    = useState('')
  const [loading,  setLoading]  = useState(false)
  const [rememberMe, setRememberMe] = useState(true)

  // Reset root document zoom to prevent browser positioning alignment bugs on logout
  useEffect(() => {
    const originalZoom = document.documentElement.style.zoom
    const originalZoomVar = document.documentElement.style.getPropertyValue('--zoom')
    
    document.documentElement.style.zoom = ''
    document.documentElement.style.removeProperty('--zoom')
    
    return () => {
      if (originalZoom) document.documentElement.style.zoom = originalZoom
      if (originalZoomVar) document.documentElement.style.setProperty('--zoom', originalZoomVar)
    }
  }, [])

  // Recent logins state
  const [recentLogins, setRecentLogins] = useState(() => {
    try {
      return JSON.parse(localStorage.getItem('bizassist_recent_logins') || '[]')
    } catch {
      return []
    }
  })
  
  // View states: 'recent' | 'password' | 'staff' | 'standard'
  const [view, setView] = useState(() => {
    try {
      const list = JSON.parse(localStorage.getItem('bizassist_recent_logins') || '[]')
      return list.length > 0 ? 'recent' : 'standard'
    } catch {
      return 'standard'
    }
  })

  // Selected owner/business for quick login
  const [selectedOwner, setSelectedOwner] = useState(null)
  const [selectedStaffUser, setSelectedStaffUser] = useState('')

  // Other-Business (standard) flow is OWNER-GATED (§9.5): type the business owner
  // username → choose Owner Login (password) or Staff Login (counter dropdown +
  // password). Staff are never logged in by a global username directly.
  const [standardStep, setStandardStep] = useState('username')  // username | choose | owner | staff
  const [bizLookup, setBizLookup] = useState(null)              // { business_name, staff:[{login_name, counter_prefix, role}] }

  // Handle standard submit (when logging in first-time or other account)
  async function handleSubmitStandard(e) {
    e.preventDefault()
    setError('')
    setLoading(true)
    logger.debug('Login submit triggered for username:', username)
    try {
      await login(username, password)
      
      // Save recent login info if successful
      const savedUserStr = localStorage.getItem('billing_user')
      const token = localStorage.getItem('billing_token')
      if (savedUserStr && token) {
        const loggedUser = JSON.parse(savedUserStr)
        if (rememberMe) {
          // If the logged in user is an owner, we should save/update their entry in recent logins
          if (loggedUser.role !== 'cashier' && loggedUser.role !== 'supply adder') {
            let staffList = []
            try {
              const res = await fetch(`${API_BASE}/staff`, {
                headers: { 'Authorization': `Bearer ${token}` }
              })
              if (res.ok) {
                staffList = await res.json()
              }
            } catch (err) {
              logger.error('Failed to fetch staff list during login memory:', err)
            }
            
            const recent = JSON.parse(localStorage.getItem('bizassist_recent_logins') || '[]')
            const updatedRecent = recent.filter(item => item.username !== loggedUser.username)
            updatedRecent.unshift({
              username: loggedUser.username,
              businessName: loggedUser.business_name || 'My Business',
              staffAccounts: staffList.map(s => ({ username: s.username, role: s.role }))
            })
            localStorage.setItem('bizassist_recent_logins', JSON.stringify(updatedRecent))
          } else {
            // If staff member logged in directly from the standard form, find/add them to parent business if recent list has it
            const recent = JSON.parse(localStorage.getItem('bizassist_recent_logins') || '[]')
            const ownerIndex = recent.findIndex(item => item.businessName === loggedUser.business_name)
            if (ownerIndex !== -1) {
              const ownerEntry = recent[ownerIndex]
              const exists = ownerEntry.staffAccounts.some(s => s.username === loggedUser.username)
              if (!exists) {
                ownerEntry.staffAccounts.push({
                  username: loggedUser.username,
                  role: loggedUser.role || 'cashier'
                })
                recent[ownerIndex] = ownerEntry
                localStorage.setItem('bizassist_recent_logins', JSON.stringify(recent))
              }
            }
          }
        } else {
          // Remove from recent logins if not checked
          const recent = JSON.parse(localStorage.getItem('bizassist_recent_logins') || '[]')
          const updatedRecent = recent.filter(item => item.username !== username)
          localStorage.setItem('bizassist_recent_logins', JSON.stringify(updatedRecent))
        }
      }

      logger.info('Login completed successfully! Navigating to dashboard.')
      navigate('/', { replace: true })
    } catch (err) {
      logger.error('Login request failed:', err.message)
      setError(err.message || 'Invalid username or password. Please try again.')
    } finally {
      setLoading(false)
    }
  }

  // Handle owner quick login (with password)
  async function handleSubmitOwnerQuick(e) {
    e.preventDefault()
    if (!selectedOwner) return
    setError('')
    setLoading(true)
    try {
      await login(selectedOwner.username, password)

      // Optionally refresh/update their staff accounts list
      const savedUserStr = localStorage.getItem('billing_user')
      const token = localStorage.getItem('billing_token')
      if (savedUserStr && token) {
        const loggedUser = JSON.parse(savedUserStr)
        let staffList = []
        try {
          const res = await fetch(`${API_BASE}/staff`, {
            headers: { 'Authorization': `Bearer ${token}` }
          })
          if (res.ok) {
            staffList = await res.json()
          }
        } catch (err) {
          logger.error('Failed to fetch staff list during quick login memory:', err)
        }
        
        const recent = JSON.parse(localStorage.getItem('bizassist_recent_logins') || '[]')
        const updatedRecent = recent.filter(item => item.username !== loggedUser.username)
        updatedRecent.unshift({
          username: loggedUser.username,
          businessName: loggedUser.business_name || 'My Business',
          staffAccounts: staffList.map(s => ({ username: s.username, role: s.role }))
        })
        localStorage.setItem('bizassist_recent_logins', JSON.stringify(updatedRecent))
      }

      logger.info('Quick owner login completed successfully!')
      navigate('/', { replace: true })
    } catch (err) {
      setError(err.message || 'Invalid password. Please try again.')
    } finally {
      setLoading(false)
    }
  }

  // Other-Business: resolve the typed owner username → business + counters.
  async function handleOwnerContinue(e) {
    e.preventDefault()
    setError('')
    const owner = username.trim()
    if (!owner) { setError('Enter the business owner username.'); return }
    setLoading(true)
    try {
      const res = await fetch(`${API_BASE}/staff-counters?owner=${encodeURIComponent(owner)}`)
      if (res.ok) {
        const data = await res.json()
        setBizLookup(data)
        // If the business has staff, offer the choice; else go straight to owner password.
        setStandardStep((data.staff && data.staff.length > 0) ? 'choose' : 'owner')
      } else {
        // Owner not found via lookup (typo / fresh account) — still allow an owner
        // password attempt (login() will validate); no staff option.
        setBizLookup(null)
        setStandardStep('owner')
      }
    } catch {
      setBizLookup(null)
      setStandardStep('owner')
    } finally {
      setLoading(false)
    }
  }

  // Other-Business: staff sign-in (owner username + selected counter + password).
  async function handleStandardStaffLogin(e) {
    e.preventDefault()
    if (!selectedStaffUser) { setError('Select a counter.'); return }
    setError('')
    setLoading(true)
    try {
      await staffLogin(username.trim(), selectedStaffUser, password)
      navigate('/', { replace: true })
    } catch (err) {
      setError(err.message || 'Invalid password. Please try again.')
    } finally {
      setLoading(false)
    }
  }

  // Handle staff quick login
  async function handleSubmitStaffQuick(e) {
    e.preventDefault()
    if (!selectedStaffUser) {
      setError('Please select a staff username.')
      return
    }
    setError('')
    setLoading(true)
    try {
      await staffLogin(selectedOwner.username, selectedStaffUser, password)
      
      // Self-register/persist this staff user in the owner's list in localStorage
      const savedUserStr = localStorage.getItem('billing_user')
      if (savedUserStr && selectedOwner) {
        const loggedUser = JSON.parse(savedUserStr)
        const recent = JSON.parse(localStorage.getItem('bizassist_recent_logins') || '[]')
        const ownerIndex = recent.findIndex(item => item.username === selectedOwner.username)
        if (ownerIndex !== -1) {
          const ownerEntry = recent[ownerIndex]
          const exists = ownerEntry.staffAccounts.some(s => s.username === loggedUser.username)
          if (!exists) {
            ownerEntry.staffAccounts.push({
              username: loggedUser.username,
              role: loggedUser.role || 'cashier'
            })
            recent[ownerIndex] = ownerEntry
            localStorage.setItem('bizassist_recent_logins', JSON.stringify(recent))
          }
        }
      }

      logger.info('Quick staff login completed successfully!')
      navigate('/', { replace: true })
    } catch (err) {
      setError(err.message || 'Invalid password. Please try again.')
    } finally {
      setLoading(false)
    }
  }

  // Reusable show/hide password toggle (same SVGs as the other login views).
  const pwToggleBtn = (
    <button type="button" className="password-toggle-btn" onClick={() => setShowPw(v => !v)} aria-label="Toggle password visibility">
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
  )

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
      <div className="login-card" style={{ boxSizing: 'border-box' }}>
        <div className="login-glow"></div>
        <div className="login-symbol"><BuildingMark size={42} /></div>
        <h1 className="login-title">BIZASSIST</h1>
        <p className="login-subtitle">ADVANCED BILLING SYSTEM</p>

        {/* Show tabs ONLY inside recent logins view to keep screens extremely compact */}
        {view === 'recent' && (
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
        )}

        {/* ── View 1: Recent Logins List ── */}
        {view === 'recent' && (
          <div style={{ width: '100%', boxSizing: 'border-box' }}>
            <p style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', marginBottom: 16, textAlign: 'center', fontWeight: 500 }}>
              Select a recent business to log in
            </p>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 12, margin: '12px 0 20px', width: '100%', boxSizing: 'border-box' }}>
              {recentLogins.map((item, idx) => (
                <button
                  key={idx}
                  type="button"
                  onClick={async () => {
                    setSelectedOwner(item)
                    setPassword('')
                    setError('')
                    const hasCachedStaff = item.staffAccounts && item.staffAccounts.length > 0
                    setView(hasCachedStaff ? 'recent-choose' : 'password')
                    try {
                      const res = await fetch(`${API_BASE}/staff-counters?owner=${encodeURIComponent(item.username)}`)
                      if (res.ok) {
                        const data = await res.json()
                        const liveStaff = (data.staff || []).map(s => ({
                          username: s.login_name,
                          role: s.role
                        }))
                        setSelectedOwner(prev => {
                          if (prev && prev.username === item.username) {
                            return { ...prev, staffAccounts: liveStaff }
                          }
                          return prev
                        })
                        const recent = JSON.parse(localStorage.getItem('bizassist_recent_logins') || '[]')
                        const idx = recent.findIndex(r => r.username === item.username)
                        if (idx !== -1) {
                          recent[idx].staffAccounts = liveStaff
                          localStorage.setItem('bizassist_recent_logins', JSON.stringify(recent))
                        }
                        setView(prev => {
                          if (prev === 'recent' || prev === 'recent-choose') {
                            return liveStaff.length > 0 ? 'recent-choose' : 'password'
                          }
                          return prev
                        })
                      }
                    } catch (err) {
                      logger.error('Failed to fetch live staff list for quick login:', err)
                    }
                  }}
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    padding: '14px 16px',
                    borderRadius: 14,
                    background: 'var(--bg-2)',
                    border: '1.5px solid var(--border)',
                    width: '100%',
                    boxSizing: 'border-box',
                    textAlign: 'left',
                    cursor: 'pointer',
                    transition: 'all 0.22s cubic-bezier(0.4, 0, 0.2, 1)',
                    boxShadow: 'var(--shadow-sm)',
                    position: 'relative',
                    overflow: 'hidden'
                  }}
                  onMouseEnter={e => {
                    e.currentTarget.style.borderColor = 'var(--accent)'
                    e.currentTarget.style.transform = 'translateY(-2px)'
                    e.currentTarget.style.boxShadow = '0 6px 16px var(--accent-dim)'
                    e.currentTarget.style.background = 'var(--bg-3)'
                  }}
                  onMouseLeave={e => {
                    e.currentTarget.style.borderColor = 'var(--border)'
                    e.currentTarget.style.transform = 'translateY(0)'
                    e.currentTarget.style.boxShadow = 'var(--shadow-sm)'
                    e.currentTarget.style.background = 'var(--bg-2)'
                  }}
                >
                  {/* Left avatar badge */}
                  <div style={{
                    width: 38,
                    height: 38,
                    borderRadius: 10,
                    background: 'var(--bg-3)',
                    border: '1px solid var(--border)',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    marginRight: 14,
                    flexShrink: 0,
                    color: 'var(--accent)'
                  }}>
                    <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                      <path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"></path>
                      <polyline points="9 22 9 12 15 12 15 22"></polyline>
                    </svg>
                  </div>

                  {/* Main text metadata */}
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ fontSize: '0.92rem', fontWeight: 700, color: 'var(--text-primary)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                      {item.businessName}
                    </div>
                    <div style={{ fontSize: '0.78rem', color: 'var(--text-secondary)', marginTop: 2, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                      Owner: {item.username}
                    </div>
                  </div>

                  {/* Right chevron indicator */}
                  <div style={{ marginLeft: 8, color: 'var(--text-muted)' }}>
                    <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                      <polyline points="9 18 15 12 9 6"></polyline>
                    </svg>
                  </div>
                </button>
              ))}
            </div>
            
            <button
              type="button"
              className="btn btn-ghost"
              onClick={() => {
                setUsername('')
                setPassword('')
                setError('')
                setView('standard')
              }}
              style={{
                width: '100%',
                fontSize: '0.82rem',
                fontWeight: 600,
                color: 'var(--accent)',
                marginTop: 8,
                textAlign: 'center',
                cursor: 'pointer',
                border: 'none',
                background: 'none'
              }}
            >
              Use another account
            </button>
          </div>
        )}

        {/* ── View 1.5: Choose Owner vs Staff for Recent Owner ── */}
        {view === 'recent-choose' && (
          <div style={{ width: '100%', boxSizing: 'border-box' }}>
            <div style={{
              display: 'flex',
              alignItems: 'center',
              padding: '10px 12px',
              borderRadius: 12,
              background: 'var(--bg-3)',
              border: '1px solid var(--border)',
              marginBottom: 16,
              gap: 12,
              width: '100%',
              boxSizing: 'border-box'
            }}>
              <div style={{
                width: 34,
                height: 34,
                borderRadius: 8,
                background: 'var(--bg-2)',
                border: '1px solid var(--border)',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                color: 'var(--accent)',
                flexShrink: 0
              }}>
                <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"></path>
                  <polyline points="9 22 9 12 15 12 15 22"></polyline>
                </svg>
              </div>
              <div style={{ textAlign: 'left', minWidth: 0 }}>
                <div style={{ fontSize: '0.88rem', fontWeight: 700, color: 'var(--text-primary)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                  {selectedOwner?.businessName}
                </div>
                <div style={{ fontSize: '0.78rem', color: 'var(--text-secondary)', marginTop: 1 }}>
                  Choose how to sign in
                </div>
              </div>
            </div>

            <button
              type="button"
              className="login-submit-btn"
              onClick={() => {
                setError('')
                setPassword('')
                setView('password')
              }}
              style={{ width: '100%' }}
            >
              Owner Login
            </button>
            <button
              type="button"
              className="login-submit-btn"
              onClick={() => {
                setError('')
                setPassword('')
                setSelectedStaffUser(selectedOwner?.staffAccounts?.[0]?.username || '')
                setView('staff')
              }}
              style={{
                width: '100%',
                marginTop: 10,
                background: 'var(--bg-2)',
                color: 'var(--text-primary)',
                border: '1px solid var(--border)'
              }}
            >
              Staff Login
            </button>

            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginTop: 16 }}>
              <button
                type="button"
                className="btn btn-ghost"
                onClick={() => {
                  setError('')
                  setView('recent')
                }}
                style={{ fontSize: '0.8rem', color: 'var(--text-muted)', cursor: 'pointer', border: 'none', background: 'none', padding: 0 }}
              >
                ← Back
              </button>
              <button
                type="button"
                className="btn btn-ghost"
                onClick={() => {
                  setUsername('')
                  setPassword('')
                  setError('')
                  setView('standard')
                }}
                style={{ fontSize: '0.8rem', color: 'var(--accent)', fontWeight: 600, cursor: 'pointer', border: 'none', background: 'none', padding: 0 }}
              >
                Other Business Login
              </button>
            </div>
          </div>
        )}

        {/* ── View 2: Password Input for Recent Owner ── */}
        {view === 'password' && (
          <form onSubmit={handleSubmitOwnerQuick} className="login-form" style={{ width: '100%', boxSizing: 'border-box' }}>
            <div style={{
              display: 'flex',
              alignItems: 'center',
              padding: '10px 12px',
              borderRadius: 12,
              background: 'var(--bg-3)',
              border: '1px solid var(--border)',
              marginBottom: 16,
              gap: 12,
              width: '100%',
              boxSizing: 'border-box'
            }}>
              <div style={{
                width: 34,
                height: 34,
                borderRadius: 8,
                background: 'var(--bg-2)',
                border: '1px solid var(--border)',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                color: 'var(--accent)',
                flexShrink: 0
              }}>
                <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"></path>
                  <polyline points="9 22 9 12 15 12 15 22"></polyline>
                </svg>
              </div>
              <div style={{ textAlign: 'left', minWidth: 0 }}>
                <div style={{ fontSize: '0.88rem', fontWeight: 700, color: 'var(--text-primary)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                  {selectedOwner?.businessName}
                </div>
                <div style={{ fontSize: '0.78rem', color: 'var(--text-secondary)', marginTop: 1 }}>
                  Owner: {selectedOwner?.username}
                </div>
              </div>
            </div>

            <div className="form-group" style={{ width: '100%', boxSizing: 'border-box' }}>
              <label htmlFor="quick-password">Password</label>
              <div className="password-wrapper">
                <input
                  type={showPw ? 'text' : 'password'}
                  id="quick-password"
                  placeholder="••••••••"
                  value={password}
                  onChange={e => setPassword(e.target.value)}
                  required
                  autoFocus
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

            {error && <div className="login-error" style={{ marginTop: '10px' }}>{error}</div>}

            <button type="submit" className="login-submit-btn" disabled={loading} style={{ marginTop: 10 }}>
              {loading ? 'Signing in...' : 'Sign In'}
            </button>

            {/* Inline Staff Login Mention */}
            {selectedOwner?.staffAccounts && selectedOwner.staffAccounts.length > 0 && (
              <div style={{ textAlign: 'center', marginTop: 8 }}>
                <span style={{ fontSize: '0.8rem', color: 'var(--text-muted)', marginRight: 6 }}>
                  Are you a staff member?
                </span>
                <button
                  type="button"
                  className="btn btn-ghost"
                  onClick={() => {
                    setSelectedStaffUser(selectedOwner.staffAccounts[0]?.username || '')
                    setPassword('')
                    setError('')
                    setView('staff')
                  }}
                  style={{ fontSize: '0.8rem', color: 'var(--accent)', fontWeight: 600, padding: 0, border: 'none', background: 'none', cursor: 'pointer' }}
                >
                  Staff Login
                </button>
              </div>
            )}

            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginTop: 12 }}>
              <button
                type="button"
                className="btn btn-ghost"
                onClick={() => {
                  setError('')
                  if (selectedOwner?.staffAccounts && selectedOwner.staffAccounts.length > 0) {
                    setView('recent-choose')
                  } else {
                    setView('recent')
                  }
                }}
                style={{ fontSize: '0.8rem', color: 'var(--text-muted)', cursor: 'pointer', border: 'none', background: 'none', padding: 0 }}
              >
                {selectedOwner?.staffAccounts && selectedOwner.staffAccounts.length > 0 ? '← Back' : '← Back to recent logins'}
              </button>
              <button
                type="button"
                className="btn btn-ghost"
                onClick={() => {
                  setUsername('')
                  setPassword('')
                  setError('')
                  setView('standard')
                }}
                style={{ fontSize: '0.8rem', color: 'var(--accent)', fontWeight: 600, cursor: 'pointer', border: 'none', background: 'none', padding: 0 }}
              >
                Other Business Login
              </button>
            </div>
          </form>
        )}

        {/* ── View 3: Dropdown Staff Login for Recent Owner ── */}
        {view === 'staff' && (
          <form onSubmit={handleSubmitStaffQuick} className="login-form" style={{ width: '100%', boxSizing: 'border-box' }}>
            <div style={{
              display: 'flex',
              alignItems: 'center',
              padding: '10px 12px',
              borderRadius: 12,
              background: 'var(--bg-3)',
              border: '1px solid var(--border)',
              marginBottom: 16,
              gap: 12,
              width: '100%',
              boxSizing: 'border-box'
            }}>
              <div style={{
                width: 34,
                height: 34,
                borderRadius: 8,
                background: 'var(--bg-2)',
                border: '1px solid var(--border)',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                color: 'var(--accent)',
                flexShrink: 0
              }}>
                <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"></path>
                  <polyline points="9 22 9 12 15 12 15 22"></polyline>
                </svg>
              </div>
              <div style={{ textAlign: 'left', minWidth: 0 }}>
                <div style={{ fontSize: '0.88rem', fontWeight: 700, color: 'var(--text-primary)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                  {selectedOwner?.businessName}
                </div>
                <div style={{ fontSize: '0.78rem', color: 'var(--text-secondary)', marginTop: 1 }}>
                  Staff Login
                </div>
              </div>
            </div>

            <div className="form-group" style={{ width: '100%', boxSizing: 'border-box' }}>
              <label htmlFor="staff-user-select" style={{ fontSize: '10.5px' }}>Select Staff User</label>
              <CustomSelect
                id="staff-user-select"
                value={selectedStaffUser}
                onChange={e => setSelectedStaffUser(e.target.value)}
              >
                {selectedOwner?.staffAccounts?.map((s, idx) => (
                  <option key={idx} value={s.username}>
                    {s.username} ({s.role || 'cashier'})
                  </option>
                ))}
              </CustomSelect>
            </div>

            <div className="form-group" style={{ marginTop: '10px', width: '100%', boxSizing: 'border-box' }}>
              <label htmlFor="staff-password" style={{ fontSize: '10.5px' }}>Password</label>
              <div className="password-wrapper">
                <input
                  type={showPw ? 'text' : 'password'}
                  id="staff-password"
                  placeholder="••••••••"
                  value={password}
                  onChange={e => setPassword(e.target.value)}
                  required
                  autoFocus
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

            {error && <div className="login-error" style={{ marginTop: '10px' }}>{error}</div>}

            <button type="submit" className="login-submit-btn" disabled={loading} style={{ marginTop: 10 }}>
              {loading ? 'Signing in...' : 'Sign In'}
            </button>

            <div style={{ textAlign: 'center', marginTop: 8 }}>
              <button
                type="button"
                className="btn btn-ghost"
                onClick={() => {
                  setPassword('')
                  setError('')
                  setView('password')
                }}
                style={{ fontSize: '0.8rem', color: 'var(--accent)', fontWeight: 600, padding: 0, border: 'none', background: 'none', cursor: 'pointer' }}
              >
                Owner Login
              </button>
            </div>

            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginTop: 12 }}>
              <button
                type="button"
                className="btn btn-ghost"
                onClick={() => {
                  setError('')
                  setView('recent-choose')
                }}
                style={{ fontSize: '0.8rem', color: 'var(--text-muted)', cursor: 'pointer', border: 'none', background: 'none', padding: 0 }}
              >
                ← Back
              </button>
              <button
                type="button"
                className="btn btn-ghost"
                onClick={() => {
                  setUsername('')
                  setPassword('')
                  setError('')
                  setView('standard')
                }}
                style={{ fontSize: '0.8rem', color: 'var(--accent)', fontWeight: 600, cursor: 'pointer', border: 'none', background: 'none', padding: 0 }}
              >
                Other Business Login
              </button>
            </div>
          </form>
        )}

        {/* ── View 4: Standard Form (First-time / Other Login) ── */}
        {view === 'standard' && (
          <div style={{ width: '100%', boxSizing: 'border-box' }}>
            {/* Business header */}
            <div style={{ display: 'flex', alignItems: 'center', padding: '12px 14px', borderRadius: 12, background: 'var(--bg-3)', border: '1px solid var(--border)', marginBottom: 20, gap: 12, width: '100%', boxSizing: 'border-box' }}>
              <div style={{ width: 34, height: 34, borderRadius: 8, background: 'var(--bg-2)', border: '1px solid var(--border)', display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--accent)', flexShrink: 0 }}>
                <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"></path>
                  <polyline points="9 22 9 12 15 12 15 22"></polyline>
                </svg>
              </div>
              <div style={{ textAlign: 'left', minWidth: 0 }}>
                <div style={{ fontSize: '0.88rem', fontWeight: 700, color: 'var(--text-primary)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                  {standardStep === 'username' ? 'Other Business Login' : (bizLookup?.business_name || 'Business Login')}
                </div>
                <div style={{ fontSize: '0.78rem', color: 'var(--text-secondary)', marginTop: 1 }}>
                  {standardStep === 'username' && 'Enter the business owner username'}
                  {standardStep === 'choose' && 'Choose how to sign in'}
                  {standardStep === 'owner' && 'Owner Login'}
                  {standardStep === 'staff' && 'Staff Login'}
                </div>
              </div>
            </div>

            {/* STEP 1 — owner username */}
            {standardStep === 'username' && (
              <form onSubmit={handleOwnerContinue} style={{ width: '100%' }}>
                <div className="form-group" style={{ width: '100%', boxSizing: 'border-box' }}>
                  <label htmlFor="owner-username">Business Owner Username</label>
                  <input type="text" id="owner-username" placeholder="e.g. store_owner" value={username} onChange={e => setUsername(e.target.value)} required autoFocus autoComplete="username" />
                </div>
                {error && <div className="login-error" style={{ marginTop: 14 }}>{error}</div>}
                <button type="submit" className="login-submit-btn" disabled={loading} style={{ marginTop: 14 }}>
                  {loading ? 'Checking…' : 'Continue'}
                </button>
                <div style={{ textAlign: 'center', marginTop: 10 }}>
                  <span style={{ fontSize: '0.8rem', color: 'var(--text-muted)', marginRight: 6 }}>Don't have an account?</span>
                  <button type="button" onClick={() => navigate('/register')} style={{ fontSize: '0.8rem', color: 'var(--accent)', fontWeight: 600, padding: 0, border: 'none', background: 'none', cursor: 'pointer' }}>Register</button>
                </div>
              </form>
            )}

            {/* STEP 2 — choose owner vs staff */}
            {standardStep === 'choose' && (
              <div style={{ width: '100%' }}>
                <button type="button" className="login-submit-btn" onClick={() => { setError(''); setPassword(''); setStandardStep('owner') }} style={{ width: '100%' }}>Owner Login</button>
                <button type="button" className="login-submit-btn" disabled={!(bizLookup?.staff?.length)} onClick={() => { setError(''); setPassword(''); setSelectedStaffUser(bizLookup?.staff?.[0]?.login_name || ''); setStandardStep('staff') }} style={{ width: '100%', marginTop: 10, background: 'var(--bg-2)', color: 'var(--text-primary)', border: '1px solid var(--border)' }}>Staff Login</button>
                <button type="button" onClick={() => { setError(''); setStandardStep('username') }} style={{ width: '100%', marginTop: 14, fontSize: '0.82rem', fontWeight: 600, color: 'var(--accent)', border: 'none', background: 'none', cursor: 'pointer' }}>← Back</button>
              </div>
            )}

            {/* STEP 3 — owner password */}
            {standardStep === 'owner' && (
              <form onSubmit={handleSubmitStandard} style={{ width: '100%' }}>
                <div className="form-group" style={{ width: '100%', boxSizing: 'border-box' }}>
                  <label htmlFor="owner-password">Owner Password</label>
                  <div className="password-wrapper">
                    <input type={showPw ? 'text' : 'password'} id="owner-password" placeholder="••••••••" value={password} onChange={e => setPassword(e.target.value)} required autoFocus autoComplete="current-password" />
                    {pwToggleBtn}
                  </div>
                </div>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 12, userSelect: 'none' }}>
                  <input type="checkbox" id="remember-me" checked={rememberMe} onChange={e => setRememberMe(e.target.checked)} style={{ width: 'auto', margin: 0, cursor: 'pointer' }} />
                  <label htmlFor="remember-me" style={{ fontSize: '0.82rem', color: 'var(--text-secondary)', cursor: 'pointer', margin: 0, textTransform: 'none', fontWeight: 500, letterSpacing: 'normal' }}>Remember me</label>
                </div>
                {error && <div className="login-error" style={{ marginTop: 14 }}>{error}</div>}
                <button type="submit" className="login-submit-btn" disabled={loading} style={{ marginTop: 14 }}>{loading ? 'Signing in…' : 'Sign In as Owner'}</button>
                <button type="button" onClick={() => { setError(''); setStandardStep(bizLookup?.staff?.length ? 'choose' : 'username') }} style={{ width: '100%', marginTop: 12, fontSize: '0.82rem', fontWeight: 600, color: 'var(--accent)', border: 'none', background: 'none', cursor: 'pointer' }}>← Back</button>
              </form>
            )}

            {/* STEP 4 — staff (counter dropdown) */}
            {standardStep === 'staff' && (
              <form onSubmit={handleStandardStaffLogin} style={{ width: '100%' }}>
                <div className="form-group" style={{ width: '100%', boxSizing: 'border-box' }}>
                  <label htmlFor="std-staff-select">Select Counter</label>
                  <CustomSelect id="std-staff-select" value={selectedStaffUser} onChange={e => setSelectedStaffUser(e.target.value)}>
                    {(bizLookup?.staff || []).map((s, idx) => (
                      <option key={idx} value={s.login_name}>
                        {s.login_name}{s.counter_prefix ? ` · ${s.counter_prefix}` : ''} ({s.role || 'cashier'})
                      </option>
                    ))}
                  </CustomSelect>
                </div>
                <div className="form-group" style={{ marginTop: 14, width: '100%', boxSizing: 'border-box' }}>
                  <label htmlFor="std-staff-password">Password</label>
                  <div className="password-wrapper">
                    <input type={showPw ? 'text' : 'password'} id="std-staff-password" placeholder="••••••••" value={password} onChange={e => setPassword(e.target.value)} required autoFocus autoComplete="current-password" />
                    {pwToggleBtn}
                  </div>
                </div>
                {error && <div className="login-error" style={{ marginTop: 14 }}>{error}</div>}
                <button type="submit" className="login-submit-btn" disabled={loading} style={{ marginTop: 14 }}>{loading ? 'Signing in…' : 'Sign In'}</button>
                <button type="button" onClick={() => { setError(''); setStandardStep('choose') }} style={{ width: '100%', marginTop: 12, fontSize: '0.82rem', fontWeight: 600, color: 'var(--accent)', border: 'none', background: 'none', cursor: 'pointer' }}>← Back</button>
              </form>
            )}

            {recentLogins.length > 0 && (
              <button type="button" className="btn btn-ghost" onClick={() => { setError(''); setStandardStep('username'); setView('recent') }} style={{ width: '100%', fontSize: '0.82rem', fontWeight: 600, color: 'var(--accent)', marginTop: 16, textAlign: 'center', cursor: 'pointer', border: 'none', background: 'none' }}>
                ← Show Recent Logins
              </button>
            )}
          </div>
        )}
      </div>
    </div>
    </>
  )
}
