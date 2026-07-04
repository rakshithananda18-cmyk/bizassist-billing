// ============================================================================
// Page: Settings.jsx
// Description: Application Settings Orchestrator. Manages store configurations,
//              tax settings, print headers, cashier PIN permissions, and triggers
//              hosting mode transitions (Local/Cloud/Hybrid data migrations).
// ============================================================================
import React, { useState, useEffect, useCallback, useRef } from 'react'
import { useSearchParams } from 'react-router-dom'
import AppLayout from '../layouts/AppLayout'
import { useAuth, useBusinessConfig } from '../contexts/AuthContext'
import { useLock } from '../contexts/LockContext'
import { API_BASE, IS_LOCAL_APP, updateApiBase } from '../config'
import { BillsIcon, CheckIcon, CloseIcon, ContactsIcon, InventoryIcon, LockIcon, PrinterIcon, SettingsIcon, ShieldIcon, TagIcon, WarehouseIcon, MonitorIcon, SyncIcon, CloudIcon, ZapIcon, WifiOffIcon, RobotIcon, DevicesIcon } from '../components/Icons'
import { logger } from '../utils/logger'
import { SkylineLoader } from '../components/Logo'
import { getHeaderLayout, isHeaderLineEnabled, moveItem } from '../utils/printLayout'
import { useReadinessProbe } from '../hooks/useReadinessProbe'
import ReadinessPanel from '../components/hosting/ReadinessPanel'
import PreflightModal from '../components/hosting/PreflightModal'
import ConsequenceModal from '../components/hosting/ConsequenceModal'
import MigrationModal from '../components/hosting/MigrationModal'
import BackupModal from '../components/hosting/BackupModal'
import CustomSelect from '../components/common/CustomSelect'
import { clearBillingProfileCache } from '../hooks/useBillingProfile'

// Sample content shown for each draggable header line in the live preview.
const PREVIEW_HEADER_CONTENT = {
  logo:            { node: <WarehouseIcon size={24} style={{ color: 'var(--text-muted)' }} />, style: { fontSize: '1rem', lineHeight: 1 } },
  company_name:    { node: 'MY RETAIL STORE', style: { fontWeight: 'bold', fontSize: '0.88rem' } },
  company_address: { node: '123 Market Road, Bengaluru', style: { fontSize: '0.62rem', color: '#64748b' } },
  company_contact: { node: 'Ph: +91 98765 43210 · store@gmail.com', style: { fontSize: '0.62rem', color: '#64748b' } },
  gstin:           { node: 'GSTIN: 29AAAAA1111A1Z1', style: { fontSize: '0.62rem', color: '#64748b', fontWeight: 'bold' } },
}

// ============================================================================
// ── 2. LAYOUT SUBCOMPONENTS & MODALS ──
// ============================================================================
// ─── Brand Loading Animation (matches PageLoader / frontend-ai style) ─────────
function BrandLoader({ message = 'Loading settings…' }) {
  return (
    <div style={{
      display: 'flex',
      flexDirection: 'column',
      alignItems: 'center',
      justifyContent: 'center',
      gap: 20,
      padding: '80px 0',
    }}>
      <div style={{ color: 'var(--accent)' }}>
        <SkylineLoader size={72} />
      </div>
      <div style={{ fontSize: '0.85rem', color: 'var(--text-muted)', letterSpacing: '0.01em' }}>{message}</div>
    </div>
  )
}

// ─── Toggle Switch ────────────────────────────────────────────────────────────
function Toggle({ checked, onChange, id, disabled = false }) {
  return (
    <label
      htmlFor={id}
      style={{
        position: 'relative',
        display: 'inline-block',
        width: 42,
        height: 24,
        cursor: disabled ? 'not-allowed' : 'pointer',
        flexShrink: 0,
      }}
    >
      <input
        id={id}
        type="checkbox"
        checked={checked}
        onChange={e => !disabled && onChange(e.target.checked)}
        style={{ opacity: 0, width: 0, height: 0, position: 'absolute' }}
        disabled={disabled}
      />
      <span style={{
        position: 'absolute',
        inset: 0,
        borderRadius: 24,
        background: checked ? 'var(--accent)' : 'var(--border)',
        transition: 'background 0.2s',
        opacity: disabled ? 0.5 : 1,
      }} />
      <span style={{
        position: 'absolute',
        top: 3,
        left: checked ? 21 : 3,
        width: 18,
        height: 18,
        borderRadius: '50%',
        background: '#fff',
        transition: 'left 0.2s',
        boxShadow: '0 1px 3px rgba(0,0,0,0.25)',
      }} />
    </label>
  )
}

// ─── Setting Row ──────────────────────────────────────────────────────────────
function SettingRow({ label, description, children, id }) {
  return (
    <div id={id} className="setting-row" style={{
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'space-between',
      gap: 16,
      padding: '14px 0',
      borderBottom: '1px solid var(--border)',
      borderRadius: 'var(--radius-sm)',
    }}>
      <div style={{ flex: 1 }}>
        <div style={{ fontWeight: 600, fontSize: '0.88rem', color: 'var(--text)' }}>{label}</div>
        {description && (
          <div style={{ fontSize: '0.77rem', color: 'var(--text-muted)', marginTop: 2 }}>{description}</div>
        )}
      </div>
      <div style={{ flexShrink: 0 }}>{children}</div>
    </div>
  )
}

// ─── Section Header ───────────────────────────────────────────────────────────
function SectionHeader({ title }) {
  return (
    <div style={{
      fontSize: '0.72rem',
      fontWeight: 700,
      color: 'var(--accent)',
      letterSpacing: '0.1em',
      textTransform: 'uppercase',
      marginTop: 24,
      marginBottom: 4,
    }}>
      {title}
    </div>
  )
}

// ─── Tabs ─────────────────────────────────────────────────────────────────────
const TABS = [
  { id: 'general',      label: 'General',       icon: <SettingsIcon size={16} /> },
  { id: 'transactions', label: 'Transactions',  icon: <BillsIcon size={16} /> },
  { id: 'inventory',    label: 'Items & Stock', icon: <InventoryIcon size={16} /> },
  { id: 'print',        label: 'Print & PDF',   icon: <PrinterIcon size={16} /> },
  { id: 'labels',       label: 'Custom Labels', icon: <TagIcon size={16} /> },
  { id: 'staff',        label: 'Staff Management',  icon: <ShieldIcon size={16} /> },
  { id: 'advanced',     label: 'Advanced',      icon: <ZapIcon size={16} /> },
]

// ── Global Modal Style Constants ───────────────────────────────────────────
const overlayStyle = {
  position: 'fixed', inset: 0, zIndex: 9000,
  background: 'rgba(0,0,0,0.4)', backdropFilter: 'blur(8px)',
  display: 'flex', alignItems: 'center', justifyContent: 'center',
  padding: 20, pointerEvents: 'all', touchAction: 'none',
}
const boxStyle = {
  background: 'var(--bg-2)', border: '1px solid var(--border)',
  borderRadius: 'var(--radius-xl)', padding: '28px 28px 24px',
  width: '100%', maxWidth: 360, boxShadow: 'var(--shadow-lg)',
  display: 'flex', flexDirection: 'column', gap: 16,
}
const inputStyle = {
  padding: '10px 14px', background: 'var(--bg-3)',
  border: '1px solid var(--border)', borderRadius: 'var(--radius-md)',
  color: 'var(--text-primary)', fontSize: '1rem',
  outline: 'none', width: '100%', boxSizing: 'border-box',
  textAlign: 'center', letterSpacing: '0.15em',
}

// ── Passcode Setup Modal ──────────────────────────────────────────────────
function PasscodeModal({ open, hasLock, onClose, setupPasscode, clearPasscode }) {
  const [step,      setStep]      = useState('menu')  // 'menu' | 'set' | 'confirm' | 'clear'
  const [newPin,    setNewPin]    = useState('')
  const [confirm,  setConfirm]   = useState('')
  const [error,    setError]      = useState('')
  const inputRef = useRef(null)

  useEffect(() => {
    if (open) { setStep(hasLock ? 'menu' : 'set'); setNewPin(''); setConfirm(''); setError('') }
  }, [open, hasLock])

  useEffect(() => { if (open) setTimeout(() => inputRef.current?.focus(), 100) }, [step, open])

  if (!open) return null

  const handleSet = async () => {
    if (newPin.length < 4) { setError('Passcode must be at least 4 characters.'); return }
    if (step === 'set') { setStep('confirm'); setConfirm(''); setError(''); return }
    if (newPin !== confirm) { setError('Passcodes do not match. Try again.'); setConfirm(''); return }
    await setupPasscode(newPin)
    setError('')
    onClose()
  }

  const handleClear = () => { clearPasscode(); onClose() }

  return (
    <div style={overlayStyle} onMouseDown={(e) => e.stopPropagation()}>
      <div style={boxStyle}>
        <div style={{ fontWeight: 700, fontSize: '1rem', color: 'var(--text-primary)', display: 'flex', alignItems: 'center', gap: 6 }}>
          {(step === 'menu' || step === 'clear') && <LockIcon size={18} />}
          {step === 'menu'    && 'Passcode Lock'}
          {step === 'set'     && 'Set New Passcode'}
          {step === 'confirm' && 'Confirm Passcode'}
          {step === 'clear'   && 'Remove Passcode'}
        </div>

        {step === 'menu' && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
            <button className="btn btn-secondary" onClick={() => { setStep('set'); setNewPin(''); setError('') }}
              style={{ justifyContent: 'flex-start' }}>✏️ Change Passcode</button>
            <button className="btn" onClick={() => setStep('clear')}
              style={{ background: 'var(--danger-muted,rgba(239,68,68,.12))', color: 'var(--danger,#ef4444)', border: '1px solid var(--danger,#ef4444)', justifyContent: 'flex-start' }}
            >🗑️ Remove Passcode</button>
            <button className="btn btn-ghost" onClick={onClose}>Cancel</button>
          </div>
        )}

        {(step === 'set' || step === 'confirm') && (
          <>
            <div style={{ fontSize: '0.82rem', color: 'var(--text-muted)' }}>
              {step === 'set' ? 'Enter a passcode (min 4 characters)' : 'Re-enter to confirm'}
            </div>
            <input
              ref={inputRef}
              type="password"
              placeholder={step === 'set' ? 'New passcode' : 'Confirm passcode'}
              value={step === 'set' ? newPin : confirm}
              onChange={e => step === 'set' ? setNewPin(e.target.value) : setConfirm(e.target.value)}
              onKeyDown={e => e.key === 'Enter' && handleSet()}
              style={inputStyle}
              autoComplete="new-password"
            />
            {error && <div style={{ fontSize: '0.78rem', color: 'var(--danger,#ef4444)', textAlign: 'center' }}>{error}</div>}
            <div style={{ display: 'flex', gap: 8 }}>
              <button className="btn btn-ghost" onClick={() => step === 'confirm' ? (setStep('set'), setConfirm(''), setError('')) : onClose()} style={{ flex: 1 }}>Back</button>
              <button className="btn btn-primary" onClick={handleSet} style={{ flex: 2 }}>
                {step === 'set' ? 'Continue' : 'Save Passcode'}
              </button>
            </div>
          </>
        )}

        {step === 'clear' && (
          <>
            <div style={{ fontSize: '0.84rem', color: 'var(--text-muted)' }}>Remove the session lock? The app will no longer require a passcode.</div>
            <div style={{ display: 'flex', gap: 8 }}>
              <button className="btn btn-ghost" onClick={() => setStep('menu')} style={{ flex: 1 }}>Cancel</button>
              <button className="btn" onClick={handleClear}
                style={{ flex: 2, background: 'var(--danger,#ef4444)', color: '#fff', border: 'none' }}>Remove</button>
            </div>
          </>
        )}
      </div>
    </div>
  )
}

// ─── Hosting Mode Section (card-based mode switcher with modal chain) ─────────
function HostingModeSection({ currentMode, onModeChange, token, autoSwitchTarget = null, onAutoSwitchConsumed = null }) {
  const { localProbe, cloudProbe, internetProbe, sseProbe, recheck } = useReadinessProbe()
  const [preflightTarget,  setPreflightTarget]  = useState(null)  // 'local'|'cloud'|'hybrid'
  const [consequenceTarget, setConsequenceTarget] = useState(null)
  const [migrationState,   setMigrationState]   = useState(null)  // { from, to }
  const [backupDir,        setBackupDir]        = useState(null)  // null | 'cloud-to-local' | 'local-to-cloud' (data sync, no mode switch)

  const [useLanDb, setUseLanDb] = useState(() => {
    return typeof localStorage !== 'undefined' && localStorage.getItem('bizassist_use_lan_db') === 'true'
  })
  const [lanServerUrl, setLanServerUrl] = useState(() => {
    return (typeof localStorage !== 'undefined' && localStorage.getItem('bizassist_local_backend_url')) || 'http://localhost:8001'
  })
  const [testStatus, setTestStatus] = useState('idle')
  const [testError, setTestError] = useState('')
  const [verifiedUrl, setVerifiedUrl] = useState('')
  const [isSaved, setIsSaved] = useState(() => {
    return typeof localStorage !== 'undefined' && localStorage.getItem('bizassist_use_lan_db') === 'true'
  })

  const handleTestConnection = async () => {
    logger.info('[SETTINGS] Initiating LAN server connection test for:', lanServerUrl)
    setTestStatus('testing')
    setTestError('')
    setVerifiedUrl('')
    setIsSaved(false)
    let targetUrl = lanServerUrl.trim()
    if (!targetUrl) {
      logger.warn('[SETTINGS] Connection test aborted: Server URL is empty.')
      setTestStatus('error')
      setTestError('Server URL/IP cannot be empty.')
      return
    }
    if (!targetUrl.startsWith('http://') && !targetUrl.startsWith('https://')) {
      targetUrl = `http://${targetUrl}`
    }
    try {
      const urlObj = new URL(targetUrl)
      if (!urlObj.port) {
        targetUrl = `${targetUrl.replace(/\/$/, '')}:8001`
      }
    } catch {
      targetUrl = `${targetUrl.replace(/\/$/, '')}:8001`
    }

    try {
      const controller = new AbortController()
      const timeoutId = setTimeout(() => controller.abort(), 4000) // /health does DB work; 2s flaked on slow disks/LAN
      const res = await fetch(`${targetUrl.replace(/\/$/, '')}/health`, {
        signal: controller.signal,
        mode: 'cors'
      })
      clearTimeout(timeoutId)
      if (!res.ok) {
        throw new Error(`HTTP ${res.status}: ${res.statusText}`)
      }
      const body = await res.json()
      if (body.status === 'ok' && body.db === 'connected') {
        logger.info('[SETTINGS] LAN connection test successful! URL verified:', targetUrl)
        setTestStatus('success')
        setVerifiedUrl(targetUrl)
      } else {
        throw new Error('Server returned unhealthy state or database disconnected.')
      }
    } catch (err) {
      logger.error('[SETTINGS] LAN connection test failed:', err)
      setTestStatus('error')
      setTestError(err.message || 'Network unreachable or server timeout.')
    }
  }

  const handleSaveConnection = () => {
    if (!verifiedUrl) return
    logger.info('[SETTINGS] Saving verified LAN connection configuration. URL:', verifiedUrl)
    localStorage.setItem('bizassist_use_lan_db', 'true')
    localStorage.setItem('bizassist_local_backend_url', verifiedUrl)
    updateApiBase('local')
    window.dispatchEvent(new CustomEvent('lan_status_changed'))
    recheck()
    setIsSaved(true)
    window.dispatchEvent(new CustomEvent('show_toast', {
      detail: { type: 'success', msg: 'Successfully connected and saved LAN database configuration!' }
    }))
  }

  const handleToggleLan = (checked) => {
    setUseLanDb(checked)
    if (!checked) {
      localStorage.setItem('bizassist_use_lan_db', 'false')
      localStorage.removeItem('bizassist_local_backend_url')
      updateApiBase('local')
      window.dispatchEvent(new CustomEvent('lan_status_changed'))
      recheck()
      setTestStatus('idle')
      setVerifiedUrl('')
      setIsSaved(false)
    }
  }

  // Compute card state for each mode
  function cardState(mode) {
    if (mode === currentMode) return 'active'
    const needs = {
      local:  { p1: localProbe },
      cloud:  { p2: cloudProbe, p3: internetProbe },
      hybrid: { p1: localProbe, p2: cloudProbe, p3: internetProbe },
    }[mode] || {}
    const probes = Object.values(needs)
    if (probes.some(p => p.status === 'cors'))    return 'locked'
    if (probes.some(p => p.status === 'offline'))  return 'unavailable'
    return 'ready'
  }

  const CARDS = [
    {
      mode: 'local',
      icon: <MonitorIcon size={18} />,
      title: 'Local Only',
      desc: 'Sub-second execution. 100% offline uptime. Data stays on your device. AI & cloud backups disabled.',
      badges: [
        { icon: <ZapIcon size={12} />, text: 'Fast' },
        { icon: <WifiOffIcon size={12} />, text: 'No internet needed' },
      ],
    },
    {
      mode: 'hybrid',
      icon: <SyncIcon size={18} />,
      title: 'Hybrid',
      desc: 'Fast local POS checkouts. Background sync to cloud. Unlocks cloud backups and AI Advisor.',
      badges: [
        { icon: <SyncIcon size={12} />, text: 'Sync' },
        { icon: <RobotIcon size={12} />, text: 'AI enabled' },
      ],
    },
    {
      mode: 'cloud',
      icon: <CloudIcon size={18} />,
      title: 'Cloud Only',
      desc: 'Cloud is the single source of record. Real-time sync across all devices. Requires internet.',
      badges: [
        { icon: <DevicesIcon size={12} />, text: 'Multi-device' },
        { icon: <CloudIcon size={12} />, text: 'Always synced' },
      ],
    },
  ]

  // Explain WHY a target mode can't be entered, instead of failing silently.
  // (Root cause of the "select Cloud → nothing happens" report: the cloud
  // probe was CORS-blocked/offline, so the card was locked/unavailable and the
  // click was swallowed with no feedback.)
  const explainBlocked = (mode, state) => {
    if (state === 'active') return `You're already in ${mode} mode.`
    if (state === 'locked')
      return `${mode[0].toUpperCase() + mode.slice(1)} mode is blocked: the cloud server rejected this app's request (CORS). Check that the app is on the latest build and that the cloud URL is reachable.`
    if (state === 'unavailable')
      return `${mode[0].toUpperCase() + mode.slice(1)} mode needs the cloud, which is currently offline/unreachable. Connect to the internet and press Re-check, then try again.`
    return null
  }

  const handleCardClick = (mode) => {
    const state = cardState(mode)
    if (state === 'active' || state === 'locked' || state === 'unavailable') {
      const msg = explainBlocked(mode, state)
      if (msg) {
        logger.warn(`[SETTINGS] Mode switch to "${mode}" blocked (${state}): ${msg}`)
        window.dispatchEvent(new CustomEvent('show_toast', {
          detail: { type: state === 'active' ? 'info' : 'error', msg },
        }))
      }
      return
    }
    setPreflightTarget(mode)
  }

  // Deep-link entry (e.g. the first-run HostingOnboardingModal navigates to
  // /settings?tab=advanced&switch=cloud): auto-open the guarded preflight for
  // the requested target instead of silently dropping the user on the tab.
  // If the target isn't reachable yet, tell the user why rather than opening a
  // dead preflight (this is what made the onboarding "Cloud" choice look like a
  // silent failure).
  useEffect(() => {
    if (!autoSwitchTarget) return
    if (['local', 'cloud', 'hybrid'].includes(autoSwitchTarget) && autoSwitchTarget !== currentMode) {
      const state = cardState(autoSwitchTarget)
      if (state === 'ready') {
        setPreflightTarget(autoSwitchTarget)
      } else {
        const msg = explainBlocked(autoSwitchTarget, state)
        if (msg) {
          window.dispatchEvent(new CustomEvent('show_toast', {
            detail: { type: 'error', msg },
          }))
        }
      }
    }
    onAutoSwitchConsumed?.()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [autoSwitchTarget])

  return (
    <div style={{ marginBottom: 24 }}>
      {/* Readiness panel */}
      <ReadinessPanel
        localProbe={localProbe}
        cloudProbe={cloudProbe}
        internetProbe={internetProbe}
        sseProbe={sseProbe}
        onRecheck={recheck}
      />

      {/* Mode cards */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(190px, 1fr))', gap: 12 }}>
        {CARDS.map(({ mode, icon, title, desc, badges }) => {
          const state = cardState(mode)
          return (
            <div
              key={mode}
              className={`hm-card${state === 'active' ? ' hm-card--active' : ''}${state === 'locked' ? ' hm-card--locked' : ''}${state === 'unavailable' ? ' hm-card--unavailable' : ''}`}
              onClick={() => handleCardClick(mode)}
            >
              {/* Active badge */}
              {state === 'active' && (
                <div style={{
                  position: 'absolute', top: 10, right: 10,
                  fontSize: 10, background: 'var(--accent)', color: '#fff',
                  padding: '2px 7px', borderRadius: 4, fontWeight: 700,
                }}>
                  Active
                </div>
              )}
              {state === 'locked' && (
                <div style={{
                  position: 'absolute', top: 10, right: 10,
                  fontSize: 10, background: 'rgba(255,255,255,0.12)', color: 'var(--text-muted)',
                  padding: '2px 7px', borderRadius: 4,
                  display: 'flex', alignItems: 'center', gap: 3,
                }}>
                  <LockIcon size={10} /> Locked
                </div>
              )}
              {state === 'unavailable' && (
                <div style={{
                  position: 'absolute', top: 10, right: 10,
                  fontSize: 10, background: 'rgba(239,68,68,0.15)', color: '#ef4444',
                  padding: '2px 7px', borderRadius: 4,
                }}>
                  Offline
                </div>
              )}

              <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 10, color: 'var(--accent)' }}>
                {icon}
                <span style={{ fontWeight: 700, fontSize: '0.9rem', color: 'var(--text-primary)' }}>{title}</span>
              </div>
              <p style={{ fontSize: '0.78rem', margin: '0 0 10px 0', color: 'var(--text-muted)', lineHeight: 1.5 }}>
                {desc}
              </p>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 5 }}>
                {badges.map((b, idx) => (
                  <span key={idx} style={{
                    display: 'inline-flex',
                    alignItems: 'center',
                    gap: 4,
                    fontSize: '0.7rem', padding: '2px 8px',
                    borderRadius: 12, background: 'rgba(255,255,255,0.06)',
                    border: '1px solid rgba(255,255,255,0.1)',
                    color: 'var(--text-muted)',
                  }}>{b.icon}<span>{b.text}</span></span>
                ))}
              </div>
            </div>
          )
        })}
      </div>

      {/* Local LAN Database Settings (only shown if local/hybrid is active and platform is local/LAN-connected) */}
      {IS_LOCAL_APP && (currentMode === 'local' || currentMode === 'hybrid') && (
        <div style={{
          marginTop: 14, padding: '12px 14px', borderRadius: 10,
          background: 'rgba(255,255,255,0.03)', border: '1px solid rgba(255,255,255,0.08)',
        }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 6 }}>
            <div style={{ fontSize: '0.85rem', fontWeight: 700, color: 'var(--text-primary)' }}>
              Local LAN Master/Client Connection
            </div>
            <label style={{ display: 'inline-flex', alignItems: 'center', gap: 6, cursor: 'pointer', fontSize: '0.78rem', color: 'var(--text-muted)' }}>
              <input
                type="checkbox"
                checked={useLanDb}
                onChange={e => handleToggleLan(e.target.checked)}
                style={{ width: 14, height: 14, accentColor: 'var(--accent)' }}
              />
              Connect to a remote LAN Master PC
            </label>
          </div>
          
          <div style={{ fontSize: '0.74rem', color: 'var(--text-muted)', lineHeight: 1.5, marginBottom: useLanDb ? 12 : 0 }}>
            {useLanDb 
              ? 'Enter the IP address or host URL of the master PC. Both devices will share the same database.' 
              : 'Running in Standalone mode. The database is stored locally on this machine only.'}
          </div>

          {useLanDb && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 10, marginTop: 10 }}>
              <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                <input
                  type="text"
                  placeholder="e.g. 192.168.1.100 or localhost"
                  value={lanServerUrl}
                  onChange={e => {
                    setLanServerUrl(e.target.value)
                    setTestStatus('idle')
                    setVerifiedUrl('')
                    setIsSaved(false)
                  }}
                  className="form-input"
                  style={{
                    flex: 1,
                    fontSize: '0.8rem',
                    padding: '6px 10px',
                    borderRadius: 6,
                    background: 'rgba(0,0,0,0.15)',
                    border: '1px solid rgba(255,255,255,0.12)',
                    color: 'var(--text-primary)',
                  }}
                />
                <button
                  onClick={handleTestConnection}
                  disabled={testStatus === 'testing'}
                  style={{
                    padding: '6px 14px', borderRadius: 6,
                    background: 'var(--accent)',
                    color: '#fff', border: 'none',
                    cursor: testStatus === 'testing' ? 'wait' : 'pointer',
                    fontSize: '0.8rem', fontWeight: 700,
                  }}
                >
                  {testStatus === 'testing' ? 'Testing...' : 'Test Connection'}
                </button>
                {testStatus === 'success' && (
                  <button
                    onClick={handleSaveConnection}
                    disabled={isSaved}
                    style={{
                      padding: '6px 14px', borderRadius: 6,
                      background: isSaved ? '#22c55e' : '#f97316',
                      color: '#fff', border: 'none',
                      cursor: isSaved ? 'default' : 'pointer',
                      fontSize: '0.8rem', fontWeight: 700,
                    }}
                  >
                    {isSaved ? 'Saved ✓' : 'Save & Connect'}
                  </button>
                )}
              </div>

              {testStatus === 'success' && !isSaved && (
                <div style={{ fontSize: '0.72rem', color: '#f97316', display: 'flex', alignItems: 'center', gap: 4 }}>
                  <span style={{ display: 'inline-block', width: 6, height: 6, borderRadius: '50%', background: '#f97316' }} />
                  Connection verified! Click "Save & Connect" to save settings and route traffic to {verifiedUrl}.
                </div>
              )}

              {testStatus === 'success' && isSaved && (
                <div style={{ fontSize: '0.72rem', color: '#22c55e', display: 'flex', alignItems: 'center', gap: 4 }}>
                  <span style={{ display: 'inline-block', width: 6, height: 6, borderRadius: '50%', background: '#22c55e' }} />
                  Connected successfully and saved LAN database configuration! Current server: {lanServerUrl}.
                </div>
              )}

              {testStatus === 'error' && (
                <div style={{ fontSize: '0.72rem', color: '#ef4444', display: 'flex', alignItems: 'center', gap: 4 }}>
                  <span style={{ display: 'inline-block', width: 6, height: 6, borderRadius: '50%', background: '#ef4444' }} />
                  {testError || 'Connection failed: Server is unreachable.'}
                </div>
              )}
            </div>
          )}
        </div>
      )}

      {/* Manual data sync (downloaded app only — needs localhost + network).
          Non-destructive Last-Write-Wins merge; does NOT switch hosting mode. */}
      {IS_LOCAL_APP && (() => {
        const offline = typeof navigator !== 'undefined' && navigator.onLine === false
        const lastSyncText = (dir) => {
          try {
            const iso = localStorage.getItem(`bizassist_last_sync_${dir}`)
            if (!iso) return 'Never synced'
            const d = new Date(iso)
            return `Last synced: ${d.toLocaleString([], { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' })}`
          } catch { return '' }
        }
        const btn = (dir, label) => (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
            <button
              onClick={() => !offline && setBackupDir(dir)}
              disabled={offline}
              title={offline ? 'Connect to the internet to sync' : ''}
              style={{
                flexShrink: 0, padding: '8px 14px', borderRadius: 8,
                background: offline ? 'rgba(255,255,255,0.08)' : 'var(--accent)',
                color: offline ? 'var(--text-muted)' : '#fff', border: 'none',
                cursor: offline ? 'not-allowed' : 'pointer',
                fontSize: '0.8rem', fontWeight: 700, display: 'inline-flex', alignItems: 'center', gap: 6,
              }}
            >
              <SyncIcon size={14} /> {label}
            </button>
            <span style={{ fontSize: '0.68rem', color: 'var(--text-muted)', paddingLeft: 2 }}>{lastSyncText(dir)}</span>
          </div>
        )
        return (
          <div style={{
            marginTop: 14, padding: '12px 14px', borderRadius: 10,
            background: 'rgba(255,255,255,0.03)', border: '1px solid rgba(255,255,255,0.08)',
          }}>
            <div style={{ fontSize: '0.85rem', fontWeight: 700, color: 'var(--text-primary)' }}>
              Sync data with cloud
            </div>
            <div style={{ fontSize: '0.74rem', color: 'var(--text-muted)', lineHeight: 1.5, marginBottom: 10 }}>
              Merge data between this device and the cloud (newer wins — nothing is overwritten). Does not change your hosting mode.
              {offline && <span style={{ color: '#ef4444' }}> You’re offline — connect to sync.</span>}
            </div>
            <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap' }}>
              {btn('cloud-to-local', 'Cloud → Local Sync')}
              {btn('local-to-cloud', 'Local → Cloud Sync')}
            </div>
          </div>
        )
      })()}

      {/* Sync modal */}
      {backupDir && (
        <BackupModal
          token={token}
          direction={backupDir}
          onComplete={() => setBackupDir(null)}
          onError={() => { /* keep modal open so user can read the error / retry */ }}
        />
      )}

      {/* Preflight modal */}
      {preflightTarget && (
        <PreflightModal
          targetMode={preflightTarget}
          localProbe={localProbe}
          cloudProbe={cloudProbe}
          internetProbe={internetProbe}
          onClose={() => setPreflightTarget(null)}
          onProceed={() => {
            setConsequenceTarget(preflightTarget)
            setPreflightTarget(null)
          }}
        />
      )}

      {/* Consequence modal */}
      {consequenceTarget && (
        <ConsequenceModal
          fromMode={currentMode}
          toMode={consequenceTarget}
          onCancel={() => setConsequenceTarget(null)}
          onConfirm={() => {
            setMigrationState({ from: currentMode, to: consequenceTarget })
            setConsequenceTarget(null)
          }}
        />
      )}

      {/* Migration modal */}
      {migrationState && (
        <MigrationModal
          fromMode={migrationState.from}
          toMode={migrationState.to}
          token={token}
          onComplete={() => {
            onModeChange(migrationState.to)
            setMigrationState(null)
          }}
          onError={() => {
            setMigrationState(null)
          }}
        />
      )}
    </div>
  )
}

// ─── Main Component ───────────────────────────────────────────────────────────
// ============================================================================
// ── 3. MAIN SETTINGS STATE INITIALIZATION ──
// ============================================================================
export default function Settings() {
  const { authFetch, user, token, fetchSettings, switchMode } = useAuth()
  const { config, refreshConfig } = useBusinessConfig()
  const { hasLock, setupPasscode, clearPasscode } = useLock()
  const isCashier = (user?.role || '').toLowerCase() === 'cashier'
  const visibleTabs = isCashier ? TABS.filter(t => t.id === 'general') : TABS
  const [showPasscodeModal, setShowPasscodeModal] = useState(false)
  const [searchParams, setSearchParams] = useSearchParams()
  const [activeTab, setActiveTab] = useState(() => {
    const tabParam = new URLSearchParams(window.location.search).get('tab')
    return (tabParam && TABS.some(t => t.id === tabParam)) ? tabParam : 'general'
  })

  useEffect(() => {
    const tabParam = searchParams.get('tab')
    if (tabParam && TABS.some(t => t.id === tabParam) && tabParam !== activeTab) {
      setActiveTab(tabParam)
    }
  }, [searchParams])
  // Which format the print preview shows (independent of the saved thermal_printer_mode).
  const [previewMode, setPreviewMode] = useState('thermal')
  const [dragKey, setDragKey] = useState(null)   // header line being dragged in the preview

  // ── Staff state (used in Lock & Staff tab) ──────────────────────────────────
  const [staffList,      setStaffList]      = useState([])
  const [staffLoading,   setStaffLoading]   = useState(false)
  const [staffForm,      setStaffForm]      = useState({ username: '', password: '', role: 'cashier', counter_prefix: '' })
  const [staffSubmit,    setStaffSubmit]    = useState(false)
  const [staffError,     setStaffError]     = useState('')
  const [staffSuccess,   setStaffSuccess]   = useState('')
  // Reset-password inline modal
  const [resetTarget,    setResetTarget]    = useState(null)  // { id, username }
  const [resetPw,        setResetPw]        = useState('')
  const [resetError,     setResetError]     = useState('')
  // Remove confirmation inline
  const [removeTarget,   setRemoveTarget]   = useState(null)  // { id, username }
  const [editingPrefixes, setEditingPrefixes] = useState({})

  const getAvailableCounterOptions = useCallback((list) => {
    const base = ['C1', 'C2', 'C3', 'C4', 'C5']
    let maxN = 5
    list.forEach(s => {
      const p = s.counter_prefix || ''
      const match = p.match(/^C(\d+)$/i)
      if (match) {
        const num = parseInt(match[1], 10)
        if (num > maxN) {
          maxN = num
        }
      }
    })
    const options = []
    for (let i = 1; i <= maxN + 1; i++) {
      options.push(`C${i}`)
    }
    return options
  }, [])

  const getFirstUnassignedCounter = useCallback((list, options) => {
    const assigned = new Set(list.map(s => s.counter_prefix).filter(Boolean))
    for (const opt of options) {
      if (!assigned.has(opt)) {
        return opt
      }
    }
    return `C${assigned.size + 1}`
  }, [])

  // Auto-select counter prefix for a new Cashier when staffList/options change
  useEffect(() => {
    if (staffForm.role === 'cashier' && !staffForm.counter_prefix) {
      const opts = getAvailableCounterOptions(staffList)
      const nextCtr = getFirstUnassignedCounter(staffList, opts)
      setStaffForm(f => ({ ...f, counter_prefix: nextCtr }))
    }
  }, [staffList, staffForm.role, staffForm.counter_prefix, getAvailableCounterOptions, getFirstUnassignedCounter])

  const counterOptions = getAvailableCounterOptions(staffList)

  const loadStaff = useCallback(async () => {
    setStaffLoading(true)
    try {
      const res = await authFetch('/staff')
      if (res.ok) setStaffList(await res.json())
      else if (res.status === 403) setStaffError('Only the business owner can manage staff.')
    } catch { setStaffError('Could not load staff.') }
    finally   { setStaffLoading(false) }
  }, [authFetch])

  // Load staff when Staff tab becomes active
  useEffect(() => {
    if (activeTab === 'staff' && !isCashier) loadStaff()
  }, [activeTab, isCashier, loadStaff])

  const handleAddStaff = async (e) => {
    e.preventDefault()
    setStaffError(''); setStaffSuccess('')
    if (!staffForm.username.trim() || !staffForm.password) {
      setStaffError('Username and password are required.')
      return
    }
    setStaffSubmit(true)
    try {
      const res = await authFetch('/staff', {
        method: 'POST',
        body: JSON.stringify({
          username: staffForm.username.trim(),
          password: staffForm.password,
          role: staffForm.role || 'cashier',
          counter_prefix: staffForm.counter_prefix.trim() || null
        }),
      })
      if (res.ok) {
        const created = await res.json()
        setStaffSuccess(`Staff member "${created.username}" created successfully.`)
        // Compute the next auto-selected counter for the next cashier
        const updatedList = [...staffList, created]
        const opts = getAvailableCounterOptions(updatedList)
        const nextCtr = staffForm.role === 'cashier' ? getFirstUnassignedCounter(updatedList, opts) : ''
        setStaffForm({ username: '', password: '', role: 'cashier', counter_prefix: nextCtr })
        loadStaff()
      } else {
        const err = await res.json().catch(() => ({}))
        setStaffError(err.detail || 'Could not create staff.')
      }
    } catch { setStaffError('Network error.') }
    finally   { setStaffSubmit(false) }
  }

  const handleSaveCounterPrefix = async (staffId, newPrefix) => {
    setStaffError(''); setStaffSuccess('')
    
    // Find the staff we are editing (A)
    const staffA = staffList.find(s => s.id === staffId)
    const oldPrefix = staffA ? staffA.counter_prefix : null

    // Check if newPrefix is already taken by another staff B
    const staffB = newPrefix ? staffList.find(s => s.id !== staffId && s.counter_prefix === newPrefix) : null

    try {
      if (staffB) {
        // Swap counters: B gets oldPrefix, A gets newPrefix.
        const p1 = authFetch(`/staff/${staffB.id}`, {
          method: 'PATCH',
          body: JSON.stringify({ counter_prefix: oldPrefix || null })
        })
        const p2 = authFetch(`/staff/${staffId}`, {
          method: 'PATCH',
          body: JSON.stringify({ counter_prefix: newPrefix || null })
        })
        const [res1, res2] = await Promise.all([p1, p2])
        if (res1.ok && res2.ok) {
          setStaffSuccess(`Swapped counters: "${staffA.username}" gets ${newPrefix}, "${staffB.username}" gets ${oldPrefix || 'None'}.`)
          loadStaff()
        } else {
          setStaffError('Could not swap counters.')
        }
      } else {
        // Normal update for A
        const res = await authFetch(`/staff/${staffId}`, {
          method: 'PATCH',
          body: JSON.stringify({ counter_prefix: newPrefix || null })
        })
        if (res.ok) {
          setStaffSuccess(`Updated counter prefix for "${staffA?.username || ''}" to ${newPrefix || 'None'}.`)
          loadStaff()
        } else {
          const err = await res.json().catch(() => ({}))
          setStaffError(err.detail || 'Could not update counter.')
        }
      }
    } catch {
      setStaffError('Network error.')
    }
  }

  const handleResetPassword = async () => {
    if (!resetPw || !resetTarget) return
    setResetError('')
    try {
      const res = await authFetch(`/staff/${resetTarget.id}`, { method: 'PATCH', body: JSON.stringify({ password: resetPw }) })
      if (res.ok) {
        setStaffSuccess(`Password reset for "${resetTarget.username}".`)
        setResetTarget(null); setResetPw('')
      } else {
        const err = await res.json().catch(() => ({}))
        setResetError(err.detail || 'Could not reset password.')
      }
    } catch { setResetError('Network error.') }
  }

  const handleRemoveStaff = async () => {
    if (!removeTarget) return
    try {
      const res = await authFetch(`/staff/${removeTarget.id}`, { method: 'DELETE' })
      if (res.ok) {
        setStaffSuccess(`Removed "${removeTarget.username}".`)
        setStaffList(prev => prev.filter(x => x.id !== removeTarget.id))
        setRemoveTarget(null)
      } else {
        const err = await res.json().catch(() => ({}))
        setStaffError(err.detail || 'Could not remove staff.')
        setRemoveTarget(null)
      }
    } catch { setStaffError('Network error.'); setRemoveTarget(null) }
  }

  // Click a preview element → scroll its setting into view on the left and flash it.
  const jumpToSetting = (key) => {
    const el = document.getElementById('set-' + key)
    if (!el) return
    el.scrollIntoView({ behavior: 'smooth', block: 'center' })
    el.classList.add('setting-flash')
    setTimeout(() => el.classList.remove('setting-flash'), 1600)
  }
  // Wrapper that makes a preview element clickable → jumps to its setting.
  const Editable = ({ k, children, style, title }) => (
    <div
      onClick={(e) => { e.stopPropagation(); jumpToSetting(k) }}
      title={title || 'Click to edit this setting'}
      style={{ cursor: 'pointer', ...style }}
    >
      {children}
    </div>
  )
  const [settings, setSettings] = useState(null)
  const [saving, setSaving] = useState(false)
  const [toast, setToast] = useState(null)   // { type: 'success'|'error', msg }
  const [templates, setTemplates] = useState([])

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

  const handleUpdateTemplate = async (templateKey) => {
    try {
      const res = await authFetch('/business/setup', {
        method: 'POST',
        body: JSON.stringify({ template_key: templateKey })
      })
      if (res.ok) {
        const data = await res.json().catch(() => ({}))
        if (data.business_types) setBizTypes(data.business_types)
        clearBillingProfileCache()
        await refreshConfig()
        setToast({ type: 'success', msg: 'Business category changed successfully!' })
      } else {
        const err = await res.json().catch(() => ({}))
        setToast({ type: 'error', msg: err.detail || 'Failed to update business category.' })
      }
    } catch (err) {
      logger.error('Failed to update business category:', err)
      setToast({ type: 'error', msg: 'Network error.' })
    }
  }

  // ── Multi-type businesses (plan Phase 2): ordered list, first = primary ────
  const [bizTypes, setBizTypes] = useState([])
  const [addTypeKey, setAddTypeKey] = useState('')
  useEffect(() => {
    authFetch('/business/billing-profile')
      .then(res => res.ok ? res.json() : null)
      .then(data => {
        if (data?.profile?.business_types) setBizTypes(data.profile.business_types)
      })
      .catch(err => logger.warn('[Settings] billing-profile fetch failed:', err))
  }, [authFetch])

  const saveBusinessTypes = async (keys) => {
    try {
      const res = await authFetch('/business/setup', {
        method: 'POST',
        body: JSON.stringify({ template_keys: keys })
      })
      if (res.ok) {
        const data = await res.json().catch(() => ({}))
        setBizTypes(data.business_types || keys)
        clearBillingProfileCache()
        await refreshConfig()
        setToast({ type: 'success', msg: 'Business types updated!' })
      } else {
        const err = await res.json().catch(() => ({}))
        setToast({ type: 'error', msg: err.detail || 'Failed to update business types.' })
      }
    } catch (err) {
      logger.error('Failed to update business types:', err)
      setToast({ type: 'error', msg: 'Network error.' })
    }
  }

  const handleAddBusinessType = () => {
    if (!addTypeKey || bizTypes.includes(addTypeKey)) return
    saveBusinessTypes([...bizTypes, addTypeKey])
    setAddTypeKey('')
  }

  const handleRemoveBusinessType = (key) => {
    if (key === bizTypes[0]) return   // primary is changed via the selector above
    saveBusinessTypes(bizTypes.filter(k => k !== key))
  }

  // ============================================================================
  // ── 4. DATA LOADERS & SAVE ROUTINES ──
  // ============================================================================
  // ── Load settings ──────────────────────────────────────────────────────────
  const loadSettings = useCallback(async () => {
    logger.debug('[Settings] Fetching app settings from backend…')
    try {
      const res = await authFetch('/settings')
      logger.debug('[Settings] GET /settings response status:', res.status)
      if (res.ok) {
        const data = await res.json()
        logger.info('[Settings] Loaded successfully. Sections:', Object.keys(data))
        logger.debug('[Settings] Full settings payload:', data)
        setSettings(data)
      } else {
        const err = await res.json().catch(() => ({}))
        logger.warn('[Settings] GET /settings returned non-OK status:', res.status, err.detail)
      }
    } catch (err) {
      logger.error('[Settings] Failed to fetch settings:', err)
    }
  }, [authFetch])

  useEffect(() => {
    logger.debug('[Settings] Component mounted — triggering loadSettings()')
    loadSettings()
  }, [loadSettings])

  useEffect(() => {
    const pageContent = document.querySelector('.page-content')
    if (pageContent) {
      const originalOverflow = pageContent.style.overflow
      const originalDisplay = pageContent.style.display
      const originalFlexDir = pageContent.style.flexDirection
      const originalHeight = pageContent.style.height
      const originalMinHeight = pageContent.style.minHeight
      
      pageContent.style.overflow = 'hidden'
      pageContent.style.display = 'flex'
      pageContent.style.flexDirection = 'column'
      pageContent.style.height = '100%'
      pageContent.style.minHeight = '0'
      
      return () => {
        pageContent.style.overflow = originalOverflow
        pageContent.style.display = originalDisplay
        pageContent.style.flexDirection = originalFlexDir
        pageContent.style.height = originalHeight
        pageContent.style.minHeight = originalMinHeight
      }
    }
  }, [])

  // ── Patch a single key inside a section ───────────────────────────────────
  const patch = (section, key, value) => {
    logger.debug(`[Settings] Patching ${section}.${key} =`, value)
    setSettings(prev => ({
      ...prev,
      [section]: { ...prev[section], [key]: value }
    }))
  }

  // ── Tab change ─────────────────────────────────────────────────────────────
  const handleTabChange = (tabId) => {
    logger.debug('[Settings] Tab changed to:', tabId)
    setActiveTab(tabId)
    setSearchParams({ tab: tabId })
  }

  // ── Save all settings to backend ───────────────────────────────────────────
  const save = async () => {
    logger.info('[Settings] Saving settings to backend…')
    logger.debug('[Settings] Payload being sent:', settings)
    setSaving(true)
    try {
      const res = await authFetch('/settings', {
        method: 'PUT',
        body: JSON.stringify(settings)
      })
      logger.debug('[Settings] PUT /settings response status:', res.status)
      if (res.ok) {
        const updated = await res.json()
        logger.info('[Settings] Save successful. Updated sections:', Object.keys(updated))
        setSettings(updated)
        if (fetchSettings) {
          await fetchSettings()
        }
        setToast({ type: 'success', msg: 'Settings saved successfully!' })
      } else {
        const err = await res.json().catch(() => ({}))
        logger.warn('[Settings] PUT /settings failed:', res.status, err.detail)
        throw new Error(err.detail || 'Save failed')
      }
    } catch (err) {
      logger.error('[Settings] Exception while saving settings:', err)
      setToast({ type: 'error', msg: err.message })
    } finally {
      setSaving(false)
      setTimeout(() => setToast(null), 3500)
    }
  }

  // ── Loading state ──────────────────────────────────────────────────────────
  if (!settings) {
    return (
      <AppLayout title="App Settings">
        <BrandLoader message="Loading your app settings…" />
      </AppLayout>
    )
  }

  const gen = settings.general || {}
  const tx  = settings.transactions || {}
  const inv = settings.inventory || {}
  const pr  = settings.print || {}
  const lb  = settings.labels || {}
  const g   = gen
  const t   = tx

  // ── Customisable receipt header: drag to reorder, click L/C/R to align ──────
  const headerLayout = getHeaderLayout(pr)
  const moveHeaderLine = (from, to) => patch('print', 'header_layout', moveItem(headerLayout, from, to))
  const setHeaderAlign = (key, align) =>
    patch('print', 'header_layout', headerLayout.map(l => (l.key === key ? { ...l, align } : l)))

  logger.debug('[Settings] Rendering with activeTab:', activeTab)

  // ============================================================================
  // ── 5. RENDER SETTINGS LAYOUT (JSX) ──
  // ============================================================================
  return (
    <AppLayout title="App Settings">
      <div className="slide-up" style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden', height: '100%', minHeight: 0 }}>

        {/* ── Page header (sticky, title + subtitle + Save button) ── */}
        <div className="page-header" style={{ flexShrink: 0 }}>
          <div className="page-header-left">
            <h1 className="page-title">App Settings</h1>
            <p className="page-subtitle">Configure how your billing system behaves — transactions, printing, stock, and more.</p>
          </div>
          <button
            className="btn btn-primary"
            onClick={save}
            disabled={saving}
            style={{ display: 'flex', alignItems: 'center', gap: 8, flexShrink: 0 }}
          >
            {saving ? <span className="spinner" style={{ width: 14, height: 14 }} /> : <CheckIcon size={14} />}
            Save Changes
          </button>
        </div>

        {/* Toast */}
        {toast && (
          <div style={{
            background: toast.type === 'success' ? 'var(--success-dim)' : 'var(--danger-dim)',
            color:      toast.type === 'success' ? 'var(--success)'     : 'var(--danger)',
            border:     `1px solid ${toast.type === 'success' ? 'var(--success)' : 'var(--danger)'}`,
            padding: '10px 16px',
            borderRadius: 'var(--radius-md)',
            marginTop: 12,
            marginBottom: 12,
            fontSize: '0.88rem',
            display: 'flex',
            alignItems: 'center',
            gap: 8,
            flexShrink: 0,
          }}>
            {toast.type === 'success' && <CheckIcon size={14} />}
            {toast.msg}
          </div>
        )}

        {/* ── Panel container (one big card) ── */}
        <div className="card" style={{
          display: 'flex',
          flexDirection: 'column',
          overflow: 'hidden',
          flex: 1,
          padding: 0,
          marginTop: 12,
          borderRadius: 'var(--radius-lg, 12px)',
          minHeight: 0,
        }}>
          {/* Tab strip inside the card */}
          <div style={{
            display: 'flex',
            gap: 4,
            borderBottom: '1px solid var(--border)',
            background: 'var(--bg-2)',
            overflowX: 'auto',
            padding: '0 24px',
            flexShrink: 0,
          }}>
            {visibleTabs.map(tab => (
              <button
                key={tab.id}
                onClick={() => handleTabChange(tab.id)}
                style={{
                  background: 'none',
                  border: 'none',
                  padding: '12px 18px',
                  cursor: 'pointer',
                  fontSize: '0.83rem',
                  fontWeight: activeTab === tab.id ? 700 : 500,
                  color: activeTab === tab.id ? 'var(--accent)' : 'var(--text-muted)',
                  borderBottom: activeTab === tab.id ? '2.5px solid var(--accent)' : '2.5px solid transparent',
                  marginBottom: -1,
                  whiteSpace: 'nowrap',
                  transition: 'all 0.15s',
                }}
              >
                <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
                  {tab.icon}
                  <span>{tab.label}</span>
                </span>
              </button>
            ))}
          </div>

          {/* Scrollable contents inside the card */}
          <div style={{
            flex: 1,
            overflowY: 'auto',
            padding: '24px 28px 28px',
          }}>

          {/* ═══════════════════════════ GENERAL ══════════════════════════════ */}
          {activeTab === 'general' && (
            <>
              {!isCashier && (
                <>
                  <SectionHeader title="Advanced Sync & Hosting" />
                  <SettingRow
                    label="Cloud Sync & Database Hosting"
                    description="Configure where your data resides (Local Only, Hybrid Sync, or Cloud Only) and manage automated cloud backups."
                  >
                    <button
                      onClick={() => handleTabChange('advanced')}
                      className="btn btn-primary"
                      style={{
                        display: 'flex',
                        alignItems: 'center',
                        gap: 8,
                        background: 'linear-gradient(135deg, var(--accent) 0%, #4f46e5 100%)',
                        border: 'none',
                        padding: '10px 18px',
                        borderRadius: 8,
                        fontWeight: 700,
                        boxShadow: '0 4px 12px rgba(99, 99, 255, 0.2)',
                      }}
                    >
                      <ZapIcon size={14} />
                      Manage Hosting & Backups →
                    </button>
                  </SettingRow>

                  <SectionHeader title="Business Category" />
                  <SettingRow label="Active Business Type" description="Select your business vertical to automatically configure terminology, layouts, and custom fields.">
                    <CustomSelect
                      className="form-input"
                      style={{ width: 220 }}
                      value={config?.key || 'general'}
                      onChange={e => handleUpdateTemplate(e.target.value)}
                    >
                      {templates.map(t => (
                        <option key={t.key} value={t.key}>
                          {t.label}
                        </option>
                      ))}
                    </CustomSelect>
                  </SettingRow>

                  <SettingRow
                    label="Business Types"
                    description="Businesses running more than one vertical (e.g. supermarket + mobile repair) can register secondary types. The counter can switch between them per bill."
                  >
                    <div style={{ display: 'flex', flexDirection: 'column', gap: 10, alignItems: 'flex-end' }}>
                      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, justifyContent: 'flex-end' }}>
                        {bizTypes.map((key, i) => {
                          const label = templates.find(t => t.key === key)?.label || key
                          return (
                            <span
                              key={key}
                              style={{
                                display: 'inline-flex', alignItems: 'center', gap: 6,
                                padding: '4px 10px', borderRadius: 999, fontSize: '0.78rem',
                                fontWeight: 600,
                                background: i === 0 ? 'var(--accent)' : 'var(--bg-subtle, #f1f5f9)',
                                color: i === 0 ? '#fff' : 'var(--text-muted)',
                                border: '1px solid var(--border, #e2e8f0)',
                              }}
                            >
                              {label}{i === 0 && ' (Primary)'}
                              {i > 0 && (
                                <button
                                  onClick={() => handleRemoveBusinessType(key)}
                                  title={`Remove ${label}`}
                                  style={{
                                    border: 'none', background: 'transparent', cursor: 'pointer',
                                    color: 'inherit', padding: 0, lineHeight: 1, fontSize: '0.85rem',
                                  }}
                                >
                                  ×
                                </button>
                              )}
                            </span>
                          )
                        })}
                      </div>
                      <div style={{ display: 'flex', gap: 6 }}>
                        <CustomSelect
                          className="form-input"
                          style={{ width: 180 }}
                          value={addTypeKey}
                          onChange={e => setAddTypeKey(e.target.value)}
                        >
                          <option value="">Add a business type…</option>
                          {templates.filter(t => !bizTypes.includes(t.key)).map(t => (
                            <option key={t.key} value={t.key}>{t.label}</option>
                          ))}
                        </CustomSelect>
                        <button
                          className="btn btn-secondary"
                          onClick={handleAddBusinessType}
                          disabled={!addTypeKey}
                          style={{ padding: '6px 14px' }}
                        >
                          Add
                        </button>
                      </div>
                    </div>
                  </SettingRow>
                </>
              )}

              <SectionHeader title="Appearance" />
              <SettingRow
                label="App Display Size"
                description="Scale the entire application interface to suit your screen and preference."
              >
                <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                  {[80, 90, 100, 110, 120, 130].map(v => {
                    const active = (g.app_zoom ?? 100) === v
                    return (
                      <button
                        key={v}
                        onClick={async () => {
                          patch('general', 'app_zoom', v)
                          localStorage.setItem('billing_app_zoom', String(v))
                          document.documentElement.style.zoom = `${v}%`
                          document.documentElement.style.setProperty('--zoom', v / 100)
                          document.documentElement.style.minHeight = ''
                          
                          // Auto-save zoom level to backend
                          try {
                            const newSettings = {
                              ...settings,
                              general: { ...settings.general, app_zoom: v }
                            }
                            await authFetch('/settings', {
                              method: 'PUT',
                              body: JSON.stringify(newSettings)
                            })
                          } catch (err) {
                            logger.error('[Settings] Auto-saving zoom failed:', err)
                          }
                        }}
                        className={`btn ${active ? 'btn-primary' : 'btn-secondary'}`}
                        style={{ padding: '6px 12px', minWidth: 50 }}
                      >
                        {v}%
                      </button>
                    )
                  })}
                </div>
              </SettingRow>

              {!isCashier && (
                <>
                  <SectionHeader title="Localization & Formats" />
                  <SettingRow label="Date Format" description="Set the display format for dates throughout the app.">
                    <CustomSelect
                      className="form-input"
                      style={{ width: 220 }}
                      value={g.date_format || 'DD/MM/YYYY'}
                      onChange={e => patch('general', 'date_format', e.target.value)}
                    >
                      <option value="DD/MM/YYYY">DD/MM/YYYY</option>
                      <option value="MM/DD/YYYY">MM/DD/YYYY</option>
                      <option value="YYYY-MM-DD">YYYY-MM-DD</option>
                    </CustomSelect>
                  </SettingRow>

                  <SettingRow label="Quantity Decimals" description="Number of decimal places shown for quantities.">
                    <CustomSelect
                      className="form-input"
                      style={{ width: 220 }}
                      value={g.quantity_decimal_places ?? 2}
                      onChange={e => patch('general', 'quantity_decimal_places', parseInt(e.target.value))}
                    >
                      <option value={1}>1 decimal place (0.0)</option>
                      <option value={2}>2 decimal places (0.00)</option>
                      <option value={3}>3 decimal places (0.000)</option>
                    </CustomSelect>
                  </SettingRow>

                  <SettingRow label="Amount Decimals" description="Number of decimal places shown for rates and amounts.">
                    <CustomSelect
                      className="form-input"
                      style={{ width: 220 }}
                      value={g.amount_decimal_places ?? 2}
                      onChange={e => patch('general', 'amount_decimal_places', parseInt(e.target.value))}
                    >
                      <option value={2}>2 decimal places (0.00)</option>
                      <option value={3}>3 decimal places (0.000)</option>
                    </CustomSelect>
                  </SettingRow>

                  <SectionHeader title="Passcode & Session Security" />
                  
                  <SettingRow 
                    label="Passcode App Lock" 
                    description="Require a passcode to unlock the app session after inactivity."
                  >
                    <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                      <span style={{ fontSize: '0.82rem', fontWeight: 600, color: hasLock ? 'var(--success)' : 'var(--text-muted)' }}>
                        {hasLock ? 'Enabled (PIN set)' : 'Disabled'}
                      </span>
                      <button 
                        type="button" 
                        className={`btn ${hasLock ? 'btn-secondary' : 'btn-primary'}`}
                        onClick={() => setShowPasscodeModal(true)}
                        style={{ padding: '6px 14px', fontSize: '0.82rem' }}
                      >
                        {hasLock ? 'Manage Lock' : 'Enable Lock'}
                      </button>
                    </div>
                  </SettingRow>

                  <SettingRow 
                    label="Auto-Lock Timeout" 
                    description="Lock the session automatically after a period of user inactivity."
                  >
                    <CustomSelect
                      className="form-input"
                      style={{ width: 220 }}
                      value={g.lock_timeout_minutes ?? 60}
                      onChange={e => patch('general', 'lock_timeout_minutes', parseInt(e.target.value))}
                    >
                      <option value={0}>Never Auto-Lock</option>
                      <option value={15}>15 Minutes</option>
                      <option value={30}>30 Minutes</option>
                      <option value={60}>1 Hour</option>
                      <option value={120}>2 Hours</option>
                    </CustomSelect>
                  </SettingRow>

                  <SettingRow 
                    label="Privacy Mode" 
                    description="Hide sensitive business revenue and profit figures on the dashboard."
                  >
                    <Toggle 
                      id="privacy_mode" 
                      checked={g.privacy_mode === true} 
                      onChange={v => patch('general', 'privacy_mode', v)} 
                    />
                  </SettingRow>

                </>
              )}
            </>
          )}

          {/* ═══════════════════════════ TRANSACTIONS ═════════════════════════ */}
          {activeTab === 'transactions' && (
            <>
              <SectionHeader title="Tax & Invoice" />
              <SettingRow label="Tax Invoice Format" description="Enable GST-compliant Tax Invoice numbering (mandatory for GSTIN holders).">
                <Toggle id="tax_invoice" checked={t.tax_invoice_enabled} onChange={v => patch('transactions', 'tax_invoice_enabled', v)} />
              </SettingRow>
              <SettingRow label="GST Composite Scheme" description="For businesses under the GST Composition Levy (no input tax credit).">
                <Toggle id="composite" checked={t.composite_scheme} onChange={v => patch('transactions', 'composite_scheme', v)} />
              </SettingRow>
              <SettingRow label="e-Way Bill Number Field" description="Show an e-Way Bill number field on transactions.">
                <Toggle id="eway" checked={t.eway_bill_enabled} onChange={v => patch('transactions', 'eway_bill_enabled', v)} />
              </SettingRow>

              <SectionHeader title="Discounts" />
              <SettingRow label="Discounts Enabled" description="Allow discounts to be applied on invoice line items.">
                <Toggle id="discount" checked={t.discount_enabled} onChange={v => patch('transactions', 'discount_enabled', v)} />
              </SettingRow>
              {t.discount_enabled && (
                <SettingRow label="Discount in Amount (₹)" description="Off = percentage discount. On = fixed ₹ amount discount.">
                  <Toggle id="discount_amt" checked={t.discount_in_amount} onChange={v => patch('transactions', 'discount_in_amount', v)} />
                </SettingRow>
              )}

              <SectionHeader title="Payment Reminders" />
              <SettingRow label="Payment Reminders" description="Send automatic follow-up reminders for overdue balances.">
                <Toggle id="reminders" checked={t.payment_reminder_enabled} onChange={v => patch('transactions', 'payment_reminder_enabled', v)} />
              </SettingRow>
              {t.payment_reminder_enabled && (
                <SettingRow label="Reminder After (days)" description="Send a reminder this many days past the due date.">
                  <input
                    type="number"
                    min={1}
                    max={90}
                    value={t.payment_reminder_days}
                    onChange={e => patch('transactions', 'payment_reminder_days', parseInt(e.target.value) || 1)}
                    className="form-input"
                    style={{ width: 80, padding: '6px 10px', textAlign: 'center' }}
                  />
                </SettingRow>
              )}
              <SettingRow label="Payment Terms" description="Enable due-date payment terms on invoices (e.g. Net 30).">
                <Toggle id="pay_terms" checked={t.payment_terms_enabled} onChange={v => patch('transactions', 'payment_terms_enabled', v)} />
              </SettingRow>

              <SectionHeader title="Document Types" />
              <SettingRow label="Estimates / Quotations" description="Enable the Estimates module for pre-invoice quoting.">
                <Toggle id="estimates" checked={t.estimate_enabled} onChange={v => patch('transactions', 'estimate_enabled', v)} />
              </SettingRow>
              <SettingRow label="Proforma Invoices" description="Enable Proforma Invoice documents (advance billing before goods delivery).">
                <Toggle id="proforma" checked={t.proforma_invoice_enabled} onChange={v => patch('transactions', 'proforma_invoice_enabled', v)} />
              </SettingRow>
              <SettingRow label="Delivery Challans" description="Enable Delivery Challan documents for goods dispatched without invoice.">
                <Toggle id="challan" checked={t.delivery_challan_enabled} onChange={v => patch('transactions', 'delivery_challan_enabled', v)} />
              </SettingRow>
              <SettingRow label="Sale Orders" description="Enable Sale Orders module for pre-billing order booking.">
                <Toggle id="sale_ord" checked={t.sale_order_enabled} onChange={v => patch('transactions', 'sale_order_enabled', v)} />
              </SettingRow>
              <SettingRow label="Purchase Orders" description="Enable Purchase Order creation for supplier communication.">
                <Toggle id="pur_ord" checked={t.purchase_order_enabled} onChange={v => patch('transactions', 'purchase_order_enabled', v)} />
              </SettingRow>

              <SectionHeader title="Stock Control" />
              <SettingRow label="Prevent Negative Stock" description="Block a sale if the item stock would go below zero.">
                <Toggle id="neg_stock" checked={t.prevent_negative_stock} onChange={v => patch('transactions', 'prevent_negative_stock', v)} />
              </SettingRow>

              <SectionHeader title="Totals" />
              <SettingRow label="Round Off Total" description="Apply rounding to the final invoice amount.">
                <Toggle id="round" checked={t.round_off_enabled} onChange={v => patch('transactions', 'round_off_enabled', v)} />
              </SettingRow>
              {t.round_off_enabled && (
                <SettingRow label="Rounding Method">
                  <CustomSelect
                    className="form-input"
                    style={{ width: 160 }}
                    value={t.round_off_type}
                    onChange={e => patch('transactions', 'round_off_type', e.target.value)}
                  >
                    <option value="nearest">Nearest Rupee</option>
                    <option value="ceil">Round Up</option>
                    <option value="floor">Round Down</option>
                  </CustomSelect>
                </SettingRow>
              )}

              <SectionHeader title="POS Billing Table Columns" />
              <SettingRow label="Show SKU / Item Code" description="Show SKU or Item Code column in billing table.">
                <Toggle id="pos_show_sku" checked={t.pos_show_sku !== false} onChange={v => patch('transactions', 'pos_show_sku', v)} />
              </SettingRow>
              <SettingRow label="Show Item Unit" description="Show measurement unit column (e.g. pcs) in billing table.">
                <Toggle id="pos_show_unit" checked={t.pos_show_unit !== false} onChange={v => patch('transactions', 'pos_show_unit', v)} />
              </SettingRow>
              <SettingRow label="Show Item Discount" description="Show Discount column on each item in billing table.">
                <Toggle id="pos_show_discount" checked={t.pos_show_discount !== false} onChange={v => patch('transactions', 'pos_show_discount', v)} />
              </SettingRow>
              <SettingRow label="Show Item Tax (GST)" description="Show GST / Tax applied column on each item in billing table.">
                <Toggle id="pos_show_tax" checked={t.pos_show_tax !== false} onChange={v => patch('transactions', 'pos_show_tax', v)} />
              </SettingRow>
              <SettingRow label="Show HSN Column" description="Show HSN Code column in billing table.">
                <Toggle id="pos_show_hsn" checked={t.pos_show_hsn === true} onChange={v => patch('transactions', 'pos_show_hsn', v)} />
              </SettingRow>
              <SettingRow label="Show MRP Column" description="Show Maximum Retail Price (MRP) column in billing table.">
                <Toggle id="pos_show_mrp" checked={t.pos_show_mrp === true} onChange={v => patch('transactions', 'pos_show_mrp', v)} />
              </SettingRow>
              <SettingRow label="Show Batch Selector Column" description="Show Batch Selector column on each item in billing table.">
                <Toggle id="pos_show_batch" checked={t.pos_show_batch !== false} onChange={v => patch('transactions', 'pos_show_batch', v)} />
              </SettingRow>
              <SettingRow label="Show Serial / IMEI Column" description="Show Serial Number / IMEI column in billing table (electronics, mobile, repair).">
                <Toggle id="pos_show_serial" checked={t.pos_show_serial === true} onChange={v => patch('transactions', 'pos_show_serial', v)} />
              </SettingRow>
            </>
          )}

          {/* ═══════════════════════════ INVENTORY ════════════════════════════ */}
          {activeTab === 'inventory' && (
            <>
              <SectionHeader title="Stock Management" />
              <SettingRow label="Stock Tracking" description="Track item quantities in real-time as transactions are saved.">
                <Toggle id="stock" checked={inv.stock_tracking} onChange={v => patch('inventory', 'stock_tracking', v)} />
              </SettingRow>
              <SettingRow label="Item Units" description="Enable custom units of measurement (kg, pcs, litre, etc.) per item.">
                <Toggle id="units" checked={inv.item_units_enabled} onChange={v => patch('inventory', 'item_units_enabled', v)} />
              </SettingRow>
              <SettingRow label="Item Categories" description="Organise items into categories for filtering and reports.">
                <Toggle id="cats" checked={inv.item_categories_enabled} onChange={v => patch('inventory', 'item_categories_enabled', v)} />
              </SettingRow>
              <SettingRow label="Barcode Scanning" description="Enable barcode scanning to add items to invoices at the counter.">
                <Toggle id="barcode" checked={inv.barcode_scanning} onChange={v => patch('inventory', 'barcode_scanning', v)} />
              </SettingRow>
              <SettingRow label="Auto-Update Sale Price from Bills" description="Automatically update an item's sale price when a purchase bill is saved.">
                <Toggle id="auto_price" checked={inv.auto_update_sale_price} onChange={v => patch('inventory', 'auto_update_sale_price', v)} />
              </SettingRow>

              <SectionHeader title="Pricing" />
              <SettingRow label="MRP Field" description="Show an MRP (Maximum Retail Price) field on each item.">
                <Toggle id="mrp" checked={inv.mrp_enabled} onChange={v => patch('inventory', 'mrp_enabled', v)} />
              </SettingRow>
              <SettingRow label="Wholesale Price" description="Enable a separate Wholesale Price on each item for wholesale-tier customers.">
                <Toggle id="wholesale" checked={inv.wholesale_price} onChange={v => patch('inventory', 'wholesale_price', v)} />
              </SettingRow>

              <SectionHeader title="Advanced Tracking" />
              <SettingRow label="Batch Tracking" description="Track items by batch/lot numbers (e.g. manufacturing batches, imports).">
                <Toggle id="batch" checked={inv.batch_tracking} onChange={v => patch('inventory', 'batch_tracking', v)} />
              </SettingRow>
              <SettingRow label="Expiry Date Tracking" description="Track and display item expiry dates (essential for pharma, FMCG, F&B).">
                <Toggle id="expiry" checked={inv.expiry_date_tracking} onChange={v => patch('inventory', 'expiry_date_tracking', v)} />
              </SettingRow>
              <SettingRow label="Manufacturing Date" description="Track the manufacturing date alongside expiry dates.">
                <Toggle id="mfg_date" checked={inv.manufacturing_date_tracking} onChange={v => patch('inventory', 'manufacturing_date_tracking', v)} />
              </SettingRow>
              <SettingRow label="Serial Number Tracking" description="Assign and track unique serial numbers per unit sold (electronics, equipment).">
                <Toggle id="serial" checked={inv.serial_tracking} onChange={v => patch('inventory', 'serial_tracking', v)} />
              </SettingRow>
            </>
          )}

          {/* ═══════════════════════════ PRINT ════════════════════════════════ */}
          {activeTab === 'print' && (
            <div className="print-settings-layout" style={{
              display: 'flex',
              gap: '30px',
              alignItems: 'flex-start',
              flexWrap: 'wrap',
              marginTop: '15px'
            }}>
              {/* Left Column: Form Settings */}
              <div style={{ flex: 1, minWidth: '320px' }}>
                <SectionHeader title="Appearance" />
                {previewMode === 'pdf' && (<>
                <SettingRow id="set-theme_color" label="Invoice Theme Colour" description="Accent colour used in invoice headers and totals.">
                  <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                    <input
                      type="color"
                      value={pr.theme_color}
                      onChange={e => patch('print', 'theme_color', e.target.value)}
                      style={{ width: 40, height: 32, border: 'none', borderRadius: 6, cursor: 'pointer', background: 'none' }}
                    />
                    <span style={{ fontSize: '0.82rem', fontFamily: 'monospace', color: 'var(--text-muted)' }}>{pr.theme_color}</span>
                  </div>
                </SettingRow>
                <SettingRow label="Invoice Layout Theme" description="Choose visual theme for regular printing.">
                  <CustomSelect className="form-input" style={{ width: 140 }} value={pr.invoice_theme || 'classic'} onChange={e => patch('print', 'invoice_theme', e.target.value)}>
                    <option value="classic">Classic (Traditional Style)</option>
                    <option value="modern">Modern Professional</option>
                    <option value="minimal">Minimal Compact</option>
                  </CustomSelect>
                </SettingRow>
                <SettingRow label="Page Size">
                  <CustomSelect className="form-input" style={{ width: 140 }} value={pr.page_size} onChange={e => patch('print', 'page_size', e.target.value)}>
                    <option value="A4">A4</option>
                    <option value="A5">A5</option>
                    <option value="Letter">Letter</option>
                  </CustomSelect>
                </SettingRow>
                <SettingRow label="Page Orientation">
                  <CustomSelect className="form-input" style={{ width: 140 }} value={pr.print_orientation || 'portrait'} onChange={e => patch('print', 'print_orientation', e.target.value)}>
                    <option value="portrait">Portrait</option>
                    <option value="landscape">Landscape</option>
                  </CustomSelect>
                </SettingRow>
                </>)}
                <SettingRow id="set-text_size" label="Text Size">
                  <CustomSelect className="form-input" style={{ width: 140 }} value={gen.text_size || pr.text_size || 'medium'} onChange={e => patch('general', 'text_size', e.target.value)}>
                    <option value="small">Small</option>
                    <option value="medium">Medium</option>
                    <option value="large">Large</option>
                  </CustomSelect>
                </SettingRow>
                <SettingRow label="Print Copies" description="Number of copies to print automatically per invoice.">
                  <input type="number" min={1} max={5} value={pr.copy_count}
                    onChange={e => patch('print', 'copy_count', parseInt(e.target.value) || 1)}
                    className="form-input" style={{ width: 80, padding: '6px 10px', textAlign: 'center' }} />
                </SettingRow>
                <SettingRow label="Thermal Printer Mode" description="Optimise output for local thermal receipt printers.">
                  <Toggle id="thermal" checked={pr.thermal_printer_mode} onChange={v => patch('print', 'thermal_printer_mode', v)} />
                </SettingRow>
                {previewMode === 'thermal' && (
                  <>
                    <SettingRow id="set-thermal_page_size" label="Thermal Page Size" description="Choose width of your receipt paper roll.">
                      <CustomSelect className="form-input" style={{ width: 140 }} value={gen.thermal_page_size || pr.thermal_page_size || '3inch'} onChange={e => patch('general', 'thermal_page_size', e.target.value)}>
                        <option value="3inch">3 Inch (80mm)</option>
                        <option value="2inch">2 Inch (58mm)</option>
                      </CustomSelect>
                    </SettingRow>
                    <SettingRow label="Thermal Theme">
                      <CustomSelect className="form-input" style={{ width: 140 }} value={pr.thermal_theme || 'theme_standard'} onChange={e => patch('print', 'thermal_theme', e.target.value)}>
                        <option value="theme_standard">Standard Thermal</option>
                        <option value="theme_compact">Compact Thermal</option>
                      </CustomSelect>
                    </SettingRow>
                  </>
                )}

                <SectionHeader title="Invoice Details & Table Columns" />
                <SettingRow id="set-print_logo" label="Print Logo"><Toggle id="p_logo" checked={pr.print_logo} onChange={v => patch('print', 'print_logo', v)} /></SettingRow>
                <SettingRow id="set-print_company_name" label="Print Company Name"><Toggle id="p_name" checked={pr.print_company_name} onChange={v => patch('print', 'print_company_name', v)} /></SettingRow>
                <SettingRow id="set-print_company_address" label="Print Address"><Toggle id="p_addr" checked={pr.print_company_address} onChange={v => patch('print', 'print_company_address', v)} /></SettingRow>
                <SettingRow id="set-print_company_phone" label="Print Phone"><Toggle id="p_phone" checked={pr.print_company_phone} onChange={v => patch('print', 'print_company_phone', v)} /></SettingRow>
                <SettingRow id="set-print_company_email" label="Print Email"><Toggle id="p_email" checked={pr.print_company_email} onChange={v => patch('print', 'print_company_email', v)} /></SettingRow>
                <SettingRow id="set-print_gstin" label="Print GSTIN"><Toggle id="p_gst" checked={pr.print_gstin} onChange={v => patch('print', 'print_gstin', v)} /></SettingRow>
                <SettingRow id="set-fssai_no" label="FSSAI Licence No." description="Printed at the foot of the receipt (food businesses).">
                  <input type="text" className="form-input" style={{ width: 200 }} value={pr.fssai_no || ''}
                    onChange={e => patch('print', 'fssai_no', e.target.value)} placeholder="e.g. 10122010000279" />
                </SettingRow>
                <SettingRow id="set-prices_incl_gst" label="Show 'Prices Incl. GST' note"><Toggle id="p_incl" checked={pr.prices_incl_gst} onChange={v => patch('print', 'prices_incl_gst', v)} /></SettingRow>

                <SettingRow id="set-print_item_sno" label="Print Serial Number (#)"><Toggle id="p_sno" checked={pr.print_item_sno !== false} onChange={v => patch('print', 'print_item_sno', v)} /></SettingRow>
                <SettingRow id="set-print_item_hsn" label="Print HSN/SAC Codes" description="Print HSN or SAC code alongside each line item."><Toggle id="p_hsn" checked={pr.print_item_hsn} onChange={v => patch('print', 'print_item_hsn', v)} /></SettingRow>
                <SettingRow id="set-print_item_discount" label="Print Discount Column"><Toggle id="p_disc" checked={pr.print_item_discount !== false} onChange={v => patch('print', 'print_item_discount', v)} /></SettingRow>
                <SettingRow id="set-print_item_tax" label="Print Tax Column"><Toggle id="p_coltax" checked={pr.print_item_tax !== false} onChange={v => patch('print', 'print_item_tax', v)} /></SettingRow>
                <SettingRow id="set-print_tax_breakdown" label="Print Tax Breakdown" description="Show CGST/SGST/IGST breakdown at the bottom."><Toggle id="p_tax" checked={pr.print_tax_breakdown} onChange={v => patch('print', 'print_tax_breakdown', v)} /></SettingRow>
                <SettingRow id="set-print_amount_in_words" label="Amount in Words" description='E.g. "Three Hundred Rupees Only".'><Toggle id="p_words" checked={pr.print_amount_in_words} onChange={v => patch('print', 'print_amount_in_words', v)} /></SettingRow>

                <SectionHeader title="Terms & Signature" />
                <SettingRow id="set-print_terms_conditions" label="Print Terms & Conditions"><Toggle id="p_tnc" checked={pr.print_terms_conditions} onChange={v => patch('print', 'print_terms_conditions', v)} /></SettingRow>
                {pr.print_terms_conditions && (
                  <div style={{ paddingBottom: 14, borderBottom: '1px solid var(--border)' }}>
                    <label className="form-label" style={{ fontSize: '0.78rem' }}>Terms & Conditions Text</label>
                    <textarea
                      className="form-textarea"
                      rows={3}
                      value={pr.terms_conditions_text}
                      onChange={e => patch('print', 'terms_conditions_text', e.target.value)}
                      placeholder="e.g. Thank you for your business!"
                      style={{ marginTop: 6 }}
                    />
                  </div>
                )}
                <SettingRow id="set-print_signature" label="Authorised Signature"><Toggle id="p_sig" checked={pr.print_signature} onChange={v => patch('print', 'print_signature', v)} /></SettingRow>
                {pr.print_signature && (
                  <SettingRow label="Signature Label">
                    <input type="text" className="form-input" style={{ width: 220 }}
                      value={pr.signature_label}
                      onChange={e => patch('print', 'signature_label', e.target.value)}
                      placeholder="Authorised Signatory" />
                  </SettingRow>
                )}
                <SettingRow label="Customer Signature Field"><Toggle id="p_csig" checked={pr.customer_signature} onChange={v => patch('print', 'customer_signature', v)} /></SettingRow>
                {pr.customer_signature && (
                  <SettingRow label="Customer Signature Label">
                    <input type="text" className="form-input" style={{ width: 220 }}
                      value={pr.customer_signature_label}
                      onChange={e => patch('print', 'customer_signature_label', e.target.value)}
                      placeholder="Customer Signature" />
                  </SettingRow>
                )}
                {!IS_LOCAL_APP && (
                  <SettingRow id="set-print_invoice_qr" label="Online Invoice QR Code" hint="Shows a scannable QR on the thermal bill so customers can view the invoice online (Cloud only)">
                    <Toggle id="p_qr" checked={pr.print_invoice_qr} onChange={v => patch('print', 'print_invoice_qr', v)} />
                  </SettingRow>
                )}
              </div>

              {/* Right Column: Sticky live visual preview panel (50% — click any element to edit) */}
              <div className="live-print-preview-container" style={{
                position: 'sticky',
                top: '20px',
                flex: 1,
                minWidth: '340px',
                background: 'var(--bg-3)',
                border: '1px solid var(--border)',
                borderRadius: 'var(--radius-lg)',
                padding: '24px',
                boxShadow: 'var(--shadow-md)'
              }}>
                <div style={{ marginBottom: '6px', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <span style={{ fontSize: '0.85rem', fontWeight: 800, color: 'var(--text-primary)' }}>Live Print Preview</span>
                  {/* Toggle which format to preview — independent of the saved mode */}
                  <div style={{ display: 'flex', border: '1px solid var(--border)', borderRadius: '999px', overflow: 'hidden' }}>
                    {[['thermal', 'Thermal'], ['pdf', 'PDF / A4']].map(([m, label]) => (
                      <button
                        key={m}
                        type="button"
                        onClick={() => setPreviewMode(m)}
                        style={{
                          padding: '4px 12px', fontSize: '0.72rem', fontWeight: 700, cursor: 'pointer', border: 'none',
                          background: previewMode === m ? 'var(--accent)' : 'transparent',
                          color: previewMode === m ? '#fff' : 'var(--text-muted)',
                        }}
                      >
                        {label}
                      </button>
                    ))}
                  </div>
                </div>
                <div style={{ marginBottom: '12px', fontSize: '0.7rem', color: 'var(--text-muted)' }}>
                  Tip: click any part of the preview to jump to its setting.
                </div>

                {previewMode === 'thermal' ? (
                  /* THERMAL RECEIPT PREVIEW */
                  <div style={{
                    background: '#ffffff',
                    border: '1px solid #e2e8f0',
                    boxShadow: '0 4px 12px rgba(0, 0, 0, 0.05)',
                    borderRadius: '4px',
                    padding: '16px',
                    color: '#1e293b',
                    fontFamily: 'monospace',
                    fontSize: (gen.text_size || pr.text_size || 'medium') === 'small' ? '0.68em' : (gen.text_size || pr.text_size || 'medium') === 'large' ? '0.85em' : '0.75em',
                    lineHeight: 1.4,
                    width: '100%',
                    maxWidth: (gen.thermal_page_size || pr.thermal_page_size || '3inch') === '2inch' ? '220px' : '300px',
                    margin: '0 auto',
                    position: 'relative'
                  }}>
                    <div style={{ borderBottom: '1px dashed #94a3b8', paddingBottom: '4px', marginBottom: '6px' }}>
                      {headerLayout.map((line, i) => {
                        if (!isHeaderLineEnabled(line.key, pr)) return null
                        const c = PREVIEW_HEADER_CONTENT[line.key] || { node: line.key, style: {} }
                        return (
                          <div
                            key={line.key}
                            draggable
                            onDragStart={() => setDragKey(line.key)}
                            onDragEnd={() => setDragKey(null)}
                            onDragOver={(e) => e.preventDefault()}
                            onDrop={(e) => {
                              e.preventDefault()
                              const from = headerLayout.findIndex(l => l.key === dragKey)
                              if (from > -1 && from !== i) moveHeaderLine(from, i)
                              setDragKey(null)
                            }}
                            className="preview-header-line"
                            title="Drag to reorder · L / C / R to align"
                            style={{ display: 'flex', alignItems: 'center', gap: 4, cursor: 'grab', borderRadius: 3, opacity: dragKey === line.key ? 0.4 : 1 }}
                          >
                            <span style={{ opacity: 0.35, fontSize: '0.9em' }}>⠿</span>
                            <div style={{ flex: 1, textAlign: line.align, ...c.style }}>{c.node}</div>
                            <span className="hdr-align" style={{ display: 'inline-flex', gap: 1 }}>
                              {[['left', 'L'], ['center', 'C'], ['right', 'R']].map(([a, lbl]) => (
                                <button
                                  key={a}
                                  type="button"
                                  onClick={() => setHeaderAlign(line.key, a)}
                                  title={`Align ${a}`}
                                  style={{
                                    fontSize: '0.75em', lineHeight: 1, padding: '2px 4px', cursor: 'pointer',
                                    border: 'none', borderRadius: 2, fontWeight: 700,
                                    background: line.align === a ? 'var(--accent)' : 'transparent',
                                    color: line.align === a ? '#fff' : '#94a3b8',
                                  }}
                                >
                                  {lbl}
                                </button>
                              ))}
                            </span>
                          </div>
                        )
                      })}
                    </div>

                    <div style={{ marginBottom: '6px', fontSize: '0.85em', display: 'flex', flexDirection: 'column', gap: '1px' }}>
                      <div style={{ display: 'flex', justifyContent: 'space-between' }}><span><b>Bill No:</b> 6471</span><span><b>Counter:</b> {user?.counter_prefix || 'POS'}</span></div>
                      <div style={{ display: 'flex', justifyContent: 'space-between' }}><span><b>Date:</b> {new Date().toLocaleDateString('en-IN')}</span><span><b>Time:</b> {new Date().toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit' })}</span></div>
                      <div><b>Cashier:</b> {user?.username || 'POS'}</div>
                    </div>

                    <table style={{ width: '100%', borderCollapse: 'collapse', marginBottom: '8px', fontSize: '0.85em' }}>
                      <thead>
                        <tr style={{ borderBottom: '1px dashed #94a3b8' }}>
                          {pr.print_item_sno !== false && <th style={{ textAlign: 'left' }}>#</th>}
                          <th style={{ textAlign: 'left' }}>Item</th>
                          <th style={{ textAlign: 'right' }}>MRP</th>
                          <th style={{ textAlign: 'right' }}>Rate</th>
                          <th style={{ textAlign: 'center' }}>Qty</th>
                          <th style={{ textAlign: 'right' }}>Amt</th>
                        </tr>
                      </thead>
                      <tbody>
                        <tr>
                          {pr.print_item_sno !== false && <td>1</td>}
                          <td>Parle-G {pr.print_item_hsn && <span style={{ fontSize: '0.85em', color: '#64748b' }}>(1905)</span>}</td>
                          <td style={{ textAlign: 'right' }}>10.00</td>
                          <td style={{ textAlign: 'right' }}>10.00</td>
                          <td style={{ textAlign: 'center' }}>2</td>
                          <td style={{ textAlign: 'right' }}>20.00</td>
                        </tr>
                        <tr style={{ borderBottom: '1px dashed #94a3b8' }}>
                          {pr.print_item_sno !== false && <td>2</td>}
                          <td>Tata Salt {pr.print_item_hsn && <span style={{ fontSize: '0.85em', color: '#64748b' }}>(2501)</span>}</td>
                          <td style={{ textAlign: 'right' }}>30.00</td>
                          <td style={{ textAlign: 'right' }}>28.00</td>
                          <td style={{ textAlign: 'center' }}>1</td>
                          <td style={{ textAlign: 'right' }}>28.00</td>
                        </tr>
                      </tbody>
                    </table>

                    <div style={{ display: 'flex', flexDirection: 'column', gap: '2px', alignItems: 'flex-end', borderBottom: '1px dashed #94a3b8', paddingBottom: '6px', marginBottom: '6px' }}>
                      <div style={{ display: 'flex', justifyContent: 'space-between', width: '120px', fontSize: '0.9em' }}>
                        <span>Subtotal:</span>
                        <span>₹46.00</span>
                      </div>
                      {pr.print_item_tax !== false && (
                        <div style={{ display: 'flex', justifyContent: 'space-between', width: '120px', fontSize: '0.9em' }}>
                          <span>GST (18%):</span>
                          <span>₹4.00</span>
                        </div>
                      )}
                      <div style={{ display: 'flex', justifyContent: 'space-between', width: '120px', fontSize: '1.05em', fontWeight: 'bold' }}>
                        <span>Grand Total:</span>
                        <span>₹48.00</span>
                      </div>
                    </div>

                    {/* Total quantity vs distinct items + savings (matches the M.R. Traders receipt) */}
                    <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.85em', marginBottom: '4px' }}>
                      <span>Qty: 3</span>
                      <span>Items: 2</span>
                    </div>
                    <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.95em', fontWeight: 'bold', color: '#16a34a', marginBottom: '8px' }}>
                      <span>You have Saved:</span>
                      <span>₹2.00</span>
                    </div>

                    {pr.print_tax_breakdown !== false && (
                      <Editable k="print_tax_breakdown" style={{ fontSize: '0.75em', color: '#475569', marginBottom: '8px' }}>
                        <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                          <thead>
                            <tr style={{ borderBottom: '1px dotted #94a3b8' }}>
                              <th style={{ textAlign: 'left' }}>Tax%</th>
                              <th style={{ textAlign: 'right' }}>Taxable</th>
                              <th style={{ textAlign: 'right' }}>CGST</th>
                              <th style={{ textAlign: 'right' }}>SGST</th>
                            </tr>
                          </thead>
                          <tbody>
                            <tr><td>5%</td><td style={{ textAlign: 'right' }}>48.00</td><td style={{ textAlign: 'right' }}>1.20</td><td style={{ textAlign: 'right' }}>1.20</td></tr>
                          </tbody>
                        </table>
                      </Editable>
                    )}

                    {(pr.fssai_no || pr.prices_incl_gst) && (
                      <div style={{ fontSize: '0.75em', color: '#64748b', textAlign: 'center', marginBottom: '8px' }}>
                        {pr.prices_incl_gst && <div>E. &amp; O.E. · Prices Incl. GST</div>}
                        {pr.fssai_no && <div>FSSAI: {pr.fssai_no}</div>}
                      </div>
                    )}

                    {pr.print_amount_in_words && (
                      <Editable k="print_amount_in_words" style={{ fontSize: '0.8em', color: '#64748b', fontStyle: 'italic', marginBottom: '8px', textAlign: 'center' }}>
                        Rupees Forty-Eight Only
                      </Editable>
                    )}

                    {pr.print_terms_conditions && pr.terms_conditions_text && (
                      <Editable k="print_terms_conditions" style={{ fontSize: '0.8em', color: '#64748b', textAlign: 'center', borderTop: '1px dashed #94a3b8', paddingTop: '4px', marginTop: '4px' }}>
                        <b>Terms:</b> {pr.terms_conditions_text}
                      </Editable>
                    )}

                    {(pr.print_signature || pr.customer_signature) && (
                      <div style={{ marginTop: '16px', display: 'flex', justifyContent: 'space-between', alignItems: 'flex-end' }}>
                        {pr.customer_signature ? (
                          <div style={{ borderTop: '1px dashed #64748b', width: '110px', textAlign: 'center', paddingTop: '2px', fontSize: '0.75em' }}>
                            {pr.customer_signature_label || 'Customer Signature'}
                          </div>
                        ) : <div />}
                        {pr.print_signature ? (
                          <div style={{ borderTop: '1px dashed #64748b', width: '110px', textAlign: 'center', paddingTop: '2px', fontSize: '0.75em' }}>
                            {pr.signature_label || 'Authorised Signatory'}
                          </div>
                        ) : <div />}
                      </div>
                    )}

                    {!IS_LOCAL_APP && pr.print_invoice_qr && (
                      <div style={{ textAlign: 'center', marginTop: '10px', paddingTop: '8px', borderTop: '1px dashed #94a3b8' }}>
                        <div style={{ display: 'inline-block', background: '#fff', padding: '4px', border: '1px solid #e2e8f0', borderRadius: '4px' }}>
                          <div style={{ width: 60, height: 60, background: 'repeating-linear-gradient(45deg,#cbd5e1 0,#cbd5e1 2px,#fff 0,#fff 8px)', borderRadius: 2, display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: '0.55em', color: '#64748b', flexDirection: 'column', gap: 2 }}>
                            <span>QR</span>
                          </div>
                        </div>
                        <div style={{ fontSize: '0.6em', color: '#64748b', marginTop: 2 }}>Scan to view invoice online</div>
                      </div>
                    )}

                    <div style={{ textAlign: 'center', marginTop: 10, fontSize: '0.65em', color: '#94a3b8', borderTop: '1px dashed #e2e8f0', paddingTop: 6 }}>
                      Computer generated invoice · {pr.counter_id || 'BA-XXXXXX'}
                    </div>
                  </div>
                ) : (
                  /* A4 INVOICE PREVIEW */
                  <div style={{
                    background: '#ffffff',
                    border: '1px solid #cbd5e1',
                    boxShadow: '0 4px 15px rgba(0,0,0,0.06)',
                    borderRadius: '6px',
                    padding: '20px',
                    color: '#334155',
                    fontSize: (gen.text_size || pr.text_size || 'medium') === 'small' ? '0.68em' : (gen.text_size || pr.text_size || 'medium') === 'large' ? '0.85em' : '0.75em',
                    lineHeight: 1.4,
                    width: '100%',
                    position: 'relative'
                  }}>
                    {/* Header bar colored by theme_color */}
                    <div style={{ display: 'flex', justifyContent: 'space-between', borderBottom: `2px solid ${pr.theme_color || '#3b82f6'}`, paddingBottom: '12px', marginBottom: '12px' }}>
                      <div>
                        {pr.print_logo && <Editable k="print_logo" style={{ fontSize: '1.4rem', marginBottom: '4px' }}><WarehouseIcon size={24} style={{ color: 'var(--text-muted)' }} /></Editable>}
                        {pr.print_company_name && <Editable k="print_company_name" style={{ fontWeight: 800, fontSize: '1rem', color: pr.theme_color || '#3b82f6' }}>MY COMPLIANT COMPANY</Editable>}
                        {pr.print_company_address && <Editable k="print_company_address" style={{ color: '#64748b', fontSize: '0.65rem' }}>45, GST Boulevard, Industrial Area, Bangalore</Editable>}
                        {(pr.print_company_phone || pr.print_company_email) && (
                          <Editable k="print_company_phone" style={{ color: '#64748b', fontSize: '0.65rem' }}>
                            {pr.print_company_phone && `Ph: +91 98765 43210`} {pr.print_company_email && `| Email: info@company.com`}
                          </Editable>
                        )}
                        {pr.print_gstin && <Editable k="print_gstin" style={{ fontWeight: 'bold', fontSize: '0.65rem', color: '#475569', marginTop: '2px' }}>GSTIN: 29AAAAA1111A1Z1</Editable>}
                      </div>
                      <div style={{ textAlign: 'right' }}>
                        <Editable k="theme_color" title="Click to change the theme colour" style={{ fontWeight: 900, fontSize: '1.2rem', color: pr.theme_color || '#3b82f6', letterSpacing: '0.05em' }}>TAX INVOICE</Editable>
                        <div style={{ fontSize: '0.65rem', color: '#64748b', marginTop: '4px' }}>
                          Invoice #: <b>INV-2026-0428</b><br />
                          Date: <b>{new Date().toLocaleDateString('en-IN')}</b>
                        </div>
                      </div>
                    </div>

                    <table style={{ width: '100%', borderCollapse: 'collapse', marginBottom: '12px' }}>
                      <thead>
                        <tr style={{ background: '#f8fafc', borderBottom: `1px solid #e2e8f0` }}>
                          {pr.print_item_sno !== false && <th style={{ textAlign: 'left', padding: '6px 4px', fontWeight: 700 }}>#</th>}
                          <th style={{ textAlign: 'left', padding: '6px 4px', fontWeight: 700 }}>Description of Goods</th>
                          {pr.print_item_hsn && <th style={{ textAlign: 'center', padding: '6px 4px', fontWeight: 700 }}>HSN/SAC</th>}
                          <th style={{ textAlign: 'center', padding: '6px 4px', fontWeight: 700 }}>Qty</th>
                          {pr.print_item_discount !== false && <th style={{ textAlign: 'right', padding: '6px 4px', fontWeight: 700 }}>Discount</th>}
                          {pr.print_item_tax !== false && <th style={{ textAlign: 'center', padding: '6px 4px', fontWeight: 700 }}>GST Rate</th>}
                          <th style={{ textAlign: 'right', padding: '6px 4px', fontWeight: 700 }}>Amount</th>
                        </tr>
                      </thead>
                      <tbody>
                        <tr style={{ borderBottom: '1px solid #f1f5f9' }}>
                          {pr.print_item_sno !== false && <td style={{ padding: '6px 4px' }}>1</td>}
                          <td style={{ padding: '6px 4px', fontWeight: 600 }}>Parle-G Biscuit Pack</td>
                          {pr.print_item_hsn && <td style={{ textAlign: 'center', padding: '6px 4px' }}>1905</td>}
                          <td style={{ textAlign: 'center', padding: '6px 4px' }}>2 pcs</td>
                          {pr.print_item_discount !== false && <td style={{ textAlign: 'right', padding: '6px 4px' }}>₹0.00</td>}
                          {pr.print_item_tax !== false && <td style={{ textAlign: 'center', padding: '6px 4px' }}>18%</td>}
                          <td style={{ textAlign: 'right', padding: '6px 4px' }}>₹20.00</td>
                        </tr>
                        <tr style={{ borderBottom: '1px solid #cbd5e1' }}>
                          {pr.print_item_sno !== false && <td style={{ padding: '6px 4px' }}>2</td>}
                          <td style={{ padding: '6px 4px', fontWeight: 600 }}>Tata Pure Iodised Salt</td>
                          {pr.print_item_hsn && <td style={{ textAlign: 'center', padding: '6px 4px' }}>2501</td>}
                          <td style={{ textAlign: 'center', padding: '6px 4px' }}>1 pcs</td>
                          {pr.print_item_discount !== false && <td style={{ textAlign: 'right', padding: '6px 4px' }}>₹2.00</td>}
                          {pr.print_item_tax !== false && <td style={{ textAlign: 'center', padding: '6px 4px' }}>5%</td>}
                          <td style={{ textAlign: 'right', padding: '6px 4px' }}>₹28.00</td>
                        </tr>
                      </tbody>
                    </table>

                    <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '12px' }}>
                      <div style={{ width: '55%' }}>
                        {pr.print_amount_in_words && (
                          <div style={{ fontSize: '0.65rem', color: '#64748b' }}>
                            Amount Chargeable (in words):<br />
                            <b>INR Forty-Eight Rupees Only</b>
                          </div>
                        )}
                      </div>
                      <div style={{ width: '40%', display: 'flex', flexDirection: 'column', gap: '3px' }}>
                        <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.68em' }}>
                          <span>Subtotal:</span>
                          <span>₹46.00</span>
                        </div>
                        {pr.print_item_tax !== false && (
                          <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.68em' }}>
                            <span>Total GST:</span>
                            <span>₹4.00</span>
                          </div>
                        )}
                        <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.75rem', fontWeight: 900, borderTop: '1px solid #cbd5e1', paddingTop: '4px', color: pr.theme_color || '#3b82f6' }}>
                          <span>Grand Total:</span>
                          <span>₹48.00</span>
                        </div>
                      </div>
                    </div>

                    {pr.print_tax_breakdown && (
                      <Editable k="print_tax_breakdown" style={{ background: '#f8fafc', border: '1px solid #e2e8f0', borderRadius: '4px', padding: '6px', fontSize: '0.6rem', color: '#64748b', marginBottom: '12px' }}>
                        <b>GST BREAKDOWN:</b><br />
                        Intrastate Transaction (CGST + SGST applied):<br />
                        - CGST @ 9% on ₹20.00 = ₹1.80 | SGST @ 9% on ₹20.00 = ₹1.80<br />
                        - CGST @ 2.5% on ₹28.00 = ₹0.70 | SGST @ 2.5% on ₹28.00 = ₹0.70
                      </Editable>
                    )}

                    {pr.print_terms_conditions && pr.terms_conditions_text && (
                      <Editable k="print_terms_conditions" style={{ fontSize: '0.65rem', borderTop: '1px solid #f1f5f9', paddingTop: '6px', marginTop: '6px', color: '#64748b' }}>
                        <b>Terms & Conditions:</b> {pr.terms_conditions_text}
                      </Editable>
                    )}

                    <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: '24px' }}>
                      <div>
                        {pr.customer_signature && (
                          <div style={{ borderTop: '1px solid #94a3b8', width: '130px', textAlign: 'center', paddingTop: '4px', fontSize: '0.65rem', marginTop: '16px' }}>
                            {pr.customer_signature_label || 'Customer Signature'}
                          </div>
                        )}
                      </div>
                      <div style={{ textAlign: 'right' }}>
                        {pr.print_signature && (
                          <div style={{ display: 'inline-block', borderTop: '1px solid #94a3b8', width: '130px', textAlign: 'center', paddingTop: '4px', fontSize: '0.65rem', marginTop: '16px' }}>
                            {pr.signature_label || 'Authorised Signatory'}
                          </div>
                        )}
                      </div>
                    </div>
                  </div>
                )}
              </div>
            </div>
          )}

          {/* ═══════════════════════════ LABELS ═══════════════════════════════ */}
          {activeTab === 'labels' && (
            <>
              <div style={{ paddingTop: 12, paddingBottom: 8, fontSize: '0.82rem', color: 'var(--text-muted)', lineHeight: 1.6 }}>
                Rename any transaction type to match your business terminology. These names appear on invoices, menus, and reports.
              </div>
              {[
                { key: 'sale',             label: 'Sales Invoice' },
                { key: 'purchase',         label: 'Purchase Bill' },
                { key: 'estimate',         label: 'Estimate / Quote' },
                { key: 'proforma',         label: 'Proforma Invoice' },
                { key: 'delivery_challan', label: 'Delivery Challan' },
                { key: 'sale_return',      label: 'Sale Return / Credit Note' },
                { key: 'purchase_return',  label: 'Purchase Return / Debit Note' },
                { key: 'payment_in',       label: 'Payment Received' },
                { key: 'payment_out',      label: 'Payment Made' },
                { key: 'expense',          label: 'Expense' },
                { key: 'income',           label: 'Other Income' },
                { key: 'sale_order',       label: 'Sale Order' },
                { key: 'purchase_order',   label: 'Purchase Order' },
              ].map(({ key, label }) => (
                <SettingRow key={key} label={label}>
                  <input
                    type="text"
                    className="form-input"
                    style={{ width: 220 }}
                    value={lb[key] || ''}
                    onChange={e => patch('labels', key, e.target.value)}
                    placeholder={label}
                  />
                </SettingRow>
              ))}
            </>
          )}

          {/* ═══════════════════════════ LOCK & STAFF ═════════════════════════ */}
          {/* ═══════════════════════════ STAFF MANAGEMENT ═════════════════════════ */}
          {activeTab === 'staff' && !isCashier && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 32 }}>
              
              <div>
                <SectionHeader title="Staff & Role Management" />
                <p style={{ fontSize: '0.82rem', color: 'var(--text-muted)', marginBottom: 20, marginTop: 4, lineHeight: 1.5 }}>
                  Create and manage staff sub-accounts for your business. Define user roles (Cashier or Supply Adder) and assign custom billing counters.
                </p>

                {staffError && (
                  <div style={{
                    background: 'var(--danger-dim)',
                    color: 'var(--danger)',
                    border: '1px solid var(--danger)',
                    padding: '10px 14px',
                    borderRadius: 'var(--radius-md)',
                    marginBottom: 16,
                    fontSize: '0.82rem',
                    display: 'flex',
                    alignItems: 'center',
                    gap: 8
                  }}>
                    <CloseIcon size={14} /> {staffError}
                  </div>
                )}

                {staffSuccess && (
                  <div style={{
                    background: 'var(--success-dim)',
                    color: 'var(--success)',
                    border: '1px solid var(--success)',
                    padding: '10px 14px',
                    borderRadius: 'var(--radius-md)',
                    marginBottom: 16,
                    fontSize: '0.82rem',
                    display: 'flex',
                    alignItems: 'center',
                    gap: 8
                  }}>
                    <CheckIcon size={14} /> {staffSuccess}
                  </div>
                )}

                {/* Add Staff Form */}
                <form onSubmit={handleAddStaff} className="card" style={{ 
                  background: 'var(--bg-3)', 
                  border: '1px solid var(--border)',
                  padding: 20,
                  display: 'grid', 
                  gridTemplateColumns: '1fr 1fr 1fr 1fr auto', 
                  gap: 16, 
                  alignItems: 'end', 
                  marginBottom: 24,
                  borderRadius: 'var(--radius-md)'
                }}>
                  <div className="form-group" style={{ margin: 0 }}>
                    <label className="form-label" style={{ fontSize: '0.78rem', fontWeight: 600 }}>Username</label>
                    <input 
                      className="form-input"
                      value={staffForm.username} 
                      onChange={e => setStaffForm(f => ({ ...f, username: e.target.value }))}
                      placeholder="e.g. staff_john" 
                      autoComplete="off" 
                      style={{ height: 38 }}
                    />
                  </div>
                  <div className="form-group" style={{ margin: 0 }}>
                    <label className="form-label" style={{ fontSize: '0.78rem', fontWeight: 600 }}>Password</label>
                    <input 
                      type="password" 
                      className="form-input"
                      value={staffForm.password} 
                      onChange={e => setStaffForm(f => ({ ...f, password: e.target.value }))}
                      placeholder="Min 8 characters" 
                      autoComplete="new-password"
                      style={{ height: 38 }}
                    />
                  </div>
                  <div className="form-group" style={{ margin: 0 }}>
                    <label className="form-label" style={{ fontSize: '0.78rem', fontWeight: 600 }}>Role</label>
                    <CustomSelect
                      className="form-input"
                      value={staffForm.role || 'cashier'}
                      onChange={e => {
                        const nextRole = e.target.value
                        setStaffForm(f => {
                          const nextCtr = nextRole === 'cashier' ? getFirstUnassignedCounter(staffList, counterOptions) : ''
                          return { ...f, role: nextRole, counter_prefix: nextCtr }
                        })
                      }}
                      style={{ height: 38 }}
                    >
                      <option value="cashier">Cashier</option>
                      <option value="supply adder">Supply Adder</option>
                    </CustomSelect>
                  </div>
                  <div className="form-group" style={{ margin: 0 }}>
                    <label className="form-label" style={{ fontSize: '0.78rem', fontWeight: 600 }}>Counter Prefix</label>
                    <CustomSelect
                      className="form-input"
                      value={staffForm.counter_prefix || ''}
                      onChange={e => setStaffForm(f => ({ ...f, counter_prefix: e.target.value }))}
                      style={{ height: 38 }}
                    >
                      <option value="">None</option>
                      {counterOptions.map(opt => (
                        <option key={opt} value={opt}>{opt}</option>
                      ))}
                    </CustomSelect>
                  </div>
                  <button type="submit" className="btn btn-primary" disabled={staffSubmit} style={{ height: 38, padding: '0 20px', fontWeight: 600 }}>
                    {staffSubmit ? 'Adding…' : '+ Add Staff'}
                  </button>
                </form>

                {/* Staff List */}
                {staffLoading ? (
                  <div style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '20px 0', color: 'var(--text-muted)' }}>
                    <span className="spinner" style={{ width: 16, height: 16 }} />
                    <span style={{ fontSize: '0.82rem' }}>Loading staff accounts…</span>
                  </div>
                ) : staffList.length === 0 ? (
                  <div style={{ padding: '24px 0', textAlign: 'center', color: 'var(--text-muted)', fontSize: '0.82rem', border: '1px dashed var(--border)', borderRadius: 'var(--radius-md)' }}>
                    No staff members registered yet. Create a staff login above.
                  </div>
                ) : (
                  <div className="data-table-wrap" style={{ border: '1px solid var(--border)', borderRadius: 'var(--radius-md)', overflow: 'hidden' }}>
                    <table className="data-table" style={{ margin: 0 }}>
                      <thead>
                        <tr>
                          <th>Username</th>
                          <th>Role</th>
                          <th>Counter Prefix</th>
                          <th style={{ textAlign: 'right' }}>Actions</th>
                        </tr>
                      </thead>
                      <tbody>
                        {staffList.map(s => (
                          <tr key={s.id}>
                            <td className="td-primary" style={{ fontWeight: 600 }}>{s.username}</td>
                            <td>
                              <span className="badge badge-muted" style={{ textTransform: 'capitalize' }}>{s.role}</span>
                            </td>
                            <td>
                              <CustomSelect
                                className="form-input"
                                value={s.counter_prefix || ''}
                                onChange={e => handleSaveCounterPrefix(s.id, e.target.value)}
                                style={{ width: 100, height: 30, fontSize: '0.78rem', padding: '2px 8px', margin: 0 }}
                              >
                                <option value="">None</option>
                                {counterOptions.map(opt => (
                                  <option key={opt} value={opt}>{opt}</option>
                                ))}
                              </CustomSelect>
                            </td>
                            <td style={{ textAlign: 'right', whiteSpace: 'nowrap' }}>
                              <button 
                                type="button" 
                                className="btn btn-ghost btn-sm" 
                                onClick={() => { setResetTarget(s); setResetPw(''); setResetError('') }} 
                                style={{ marginRight: 8, fontSize: '0.78rem' }}
                              >
                                Reset password
                              </button>
                              <button 
                                type="button" 
                                className="btn btn-ghost btn-sm" 
                                onClick={() => setRemoveTarget(s)} 
                                style={{ color: 'var(--danger)', fontSize: '0.78rem' }}
                              >
                                Remove
                              </button>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </div>

            </div>
          )}

          {/* ═══════════════════════════ ADVANCED ═════════════════════════════ */}
          {activeTab === 'advanced' && !isCashier && (
            <>
              <SectionHeader title="Hosting & Sync Mode" />
              <HostingModeSection
                // Effective mode is platform-aware: the web/browser is ALWAYS
                // cloud (it can't reach a local backend), regardless of the
                // account's stored hosting_mode. Only the downloaded app honours
                // the stored Local/Hybrid/Cloud choice.
                currentMode={IS_LOCAL_APP ? (g.hosting_mode || 'local') : 'cloud'}
                onModeChange={(newMode) => {
                  // patch saves to current backend; switchMode then updates
                  // API_BASE and forces logout so user gets a new JWT from
                  // the new backend (IDs differ between local and cloud DBs)
                  patch('general', 'hosting_mode', newMode)
                  switchMode(newMode)
                }}
                token={token}
                autoSwitchTarget={IS_LOCAL_APP ? searchParams.get('switch') : null}
                onAutoSwitchConsumed={() => {
                  // one-shot: strip ?switch= so a refresh doesn't re-open the flow
                  setSearchParams(prev => {
                    const next = new URLSearchParams(prev)
                    next.delete('switch')
                    return next
                  }, { replace: true })
                }}
              />
              {IS_LOCAL_APP && g.hosting_mode === 'hybrid' && (
                <SettingRow label="Sync Interval" description="How frequently local changes are synced to the cloud.">
                  <CustomSelect
                    className="form-input"
                    style={{ width: 220 }}
                    value={g.sync_interval ?? 30}
                    onChange={e => patch('general', 'sync_interval', parseInt(e.target.value))}
                  >
                    <option value={10}>Every 10 Seconds</option>
                    <option value={30}>Every 30 Seconds</option>
                    <option value={60}>Every 1 Minute</option>
                    <option value={300}>Every 5 Minutes</option>
                  </CustomSelect>
                </SettingRow>
              )}

              <SectionHeader title="Real-Time Synchronization Settings" />
              {((g.hosting_mode || 'local') === 'local') && (
                <div style={{ fontSize: '0.74rem', color: 'var(--text-muted)', margin: '-2px 0 8px', lineHeight: 1.5 }}>
                  Real-time sync runs only in <strong>Hybrid</strong> or <strong>Cloud</strong> mode. In Local mode there’s no background sync, so these settings have no effect.
                </div>
              )}
              <div style={((g.hosting_mode || 'local') === 'local')
                ? { opacity: 0.45, pointerEvents: 'none', filter: 'grayscale(0.6)' }
                : undefined}>
                <SettingRow label="Global Real-Time Sync" description="Enable or disable all real-time background updates globally.">
                  <Toggle id="realtime_sync_global" checked={g.realtime_sync_global !== false} onChange={v => patch('general', 'realtime_sync_global', v)} />
                </SettingRow>

                {g.realtime_sync_global !== false && (
                  <div style={{ marginLeft: 24, paddingLeft: 16, borderLeft: '2px solid var(--border)', display: 'flex', flexDirection: 'column', gap: 16, marginTop: 16 }}>
                    <SettingRow label="POS Sales Page Sync" description="Enable real-time active cart and sales listing synchronization.">
                      <Toggle id="realtime_sync_sales" checked={g.realtime_sync_sales !== false} onChange={v => patch('general', 'realtime_sync_sales', v)} />
                    </SettingRow>
                    <SettingRow label="Inventory Page Sync" description="Enable real-time product and stock level update synchronization.">
                      <Toggle id="realtime_sync_stock" checked={g.realtime_sync_stock !== false} onChange={v => patch('general', 'realtime_sync_stock', v)} />
                    </SettingRow>
                    <SettingRow label="Customers Page Sync" description="Enable real-time customer and vendor ledger synchronization.">
                      <Toggle id="realtime_sync_parties" checked={g.realtime_sync_parties !== false} onChange={v => patch('general', 'realtime_sync_parties', v)} />
                    </SettingRow>
                    <SettingRow label="Purchases Page Sync" description="Enable real-time purchase bill and debit note synchronization.">
                      <Toggle id="realtime_sync_purchases" checked={g.realtime_sync_purchases !== false} onChange={v => patch('general', 'realtime_sync_purchases', v)} />
                    </SettingRow>
                  </div>
                )}
              </div>

              <SectionHeader title="Data & Backup" />
              <SettingRow label="Auto Backup" description="Periodically request backup files for storage.">
                <Toggle id="auto_backup" checked={g.auto_backup === true} onChange={v => patch('general', 'auto_backup', v)} />
              </SettingRow>
              {g.auto_backup && (
                <SettingRow label="Backup Reminder Interval" description="How often to remind for data backups.">
                  <CustomSelect
                    className="form-input"
                    style={{ width: 220 }}
                    value={g.backup_reminder_days ?? 7}
                    onChange={e => patch('general', 'backup_reminder_days', parseInt(e.target.value))}
                  >
                    <option value={7}>Every 7 Days</option>
                    <option value={15}>Every 15 Days</option>
                    <option value={30}>Every 30 Days</option>
                  </CustomSelect>
                </SettingRow>
              )}
            </>
          )}
          </div>
        </div>

      </div>

      {/* ── Passcode Modal (rendered globally outside tab scopes) ── */}
      <PasscodeModal
        open={showPasscodeModal}
        hasLock={hasLock}
        onClose={() => setShowPasscodeModal(false)}
        setupPasscode={setupPasscode}
        clearPasscode={clearPasscode}
      />

      {/* ── Reset Password Modal ── */}
      {resetTarget && (
        <div style={overlayStyle} onMouseDown={(e) => e.stopPropagation()}>
          <div style={boxStyle}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 4 }}>
              <div style={{ fontWeight: 700, fontSize: '1rem', color: 'var(--text-primary)', display: 'flex', alignItems: 'center', gap: 6 }}>
                <LockIcon size={18} /> Reset Password
              </div>
              <button 
                type="button" 
                onClick={() => setResetTarget(null)}
                style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'var(--text-muted)', display: 'flex', padding: 4 }}
              >
                <CloseIcon size={18} />
              </button>
            </div>

            <div style={{ fontSize: '0.82rem', color: 'var(--text-muted)', lineHeight: 1.4 }}>
              Enter a new password for cashier account <strong>{resetTarget.username}</strong>.
            </div>

            <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
              <input
                type="password"
                placeholder="New Password (min 8 characters)"
                value={resetPw}
                onChange={e => setResetPw(e.target.value)}
                onKeyDown={e => e.key === 'Enter' && handleResetPassword()}
                style={inputStyle}
                autoFocus
              />
              
              {resetError && (
                <div style={{ fontSize: '0.78rem', color: 'var(--danger)', textAlign: 'center' }}>
                  {resetError}
                </div>
              )}
            </div>

            <div style={{ display: 'flex', gap: 8, marginTop: 4 }}>
              <button 
                className="btn btn-ghost" 
                onClick={() => setResetTarget(null)} 
                style={{ flex: 1 }}
              >
                Cancel
              </button>
              <button 
                className="btn btn-primary" 
                onClick={handleResetPassword} 
                style={{ flex: 2 }}
              >
                Update Password
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ── Remove Cashier Confirmation Modal ── */}
      {removeTarget && (
        <div style={overlayStyle} onMouseDown={(e) => e.stopPropagation()}>
          <div style={boxStyle}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 4 }}>
              <div style={{ fontWeight: 700, fontSize: '1rem', color: 'var(--danger)', display: 'flex', alignItems: 'center', gap: 6 }}>
                ⚠️ Delete Account
              </div>
              <button 
                type="button" 
                onClick={() => setRemoveTarget(null)}
                style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'var(--text-muted)', display: 'flex', padding: 4 }}
              >
                <CloseIcon size={18} />
              </button>
            </div>

            <div style={{ fontSize: '0.84rem', color: 'var(--text-muted)', lineHeight: 1.5 }}>
              Are you sure you want to remove the cashier account <strong>{removeTarget.username}</strong>? They will be signed out immediately and won't be able to log in to this business anymore.
            </div>

            <div style={{ display: 'flex', gap: 8, marginTop: 8 }}>
              <button 
                className="btn btn-ghost" 
                onClick={() => setRemoveTarget(null)} 
                style={{ flex: 1 }}
              >
                Cancel
              </button>
              <button 
                className="btn" 
                onClick={handleRemoveStaff}
                style={{ 
                  flex: 2, 
                  background: 'var(--danger)', 
                  color: '#fff', 
                  border: 'none',
                  fontWeight: 600
                }}
              >
                Confirm Delete
              </button>
            </div>
          </div>
        </div>
      )}
    </AppLayout>
  )
}
