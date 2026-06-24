import React, { useState, useEffect, useCallback, useRef } from 'react'
import AppLayout from '../layouts/AppLayout'
import { useAuth, useBusinessConfig } from '../contexts/AuthContext'
import { useLock } from '../contexts/LockContext'
import { API_BASE } from '../config'
import { BillsIcon, CheckIcon, InventoryIcon, PrinterIcon, SettingsIcon, TagIcon, WarehouseIcon } from '../components/Icons'
import { logger } from '../utils/logger'
import { SkylineLoader } from '../components/Logo'
import { getHeaderLayout, isHeaderLineEnabled, moveItem } from '../utils/printLayout'

// Sample content shown for each draggable header line in the live preview.
const PREVIEW_HEADER_CONTENT = {
  logo:            { node: <WarehouseIcon size={24} style={{ color: 'var(--text-muted)' }} />, style: { fontSize: '1rem', lineHeight: 1 } },
  company_name:    { node: 'MY RETAIL STORE', style: { fontWeight: 'bold', fontSize: '0.88rem' } },
  company_address: { node: '123 Market Road, Bengaluru', style: { fontSize: '0.62rem', color: '#64748b' } },
  company_contact: { node: 'Ph: +91 98765 43210 · store@gmail.com', style: { fontSize: '0.62rem', color: '#64748b' } },
  gstin:           { node: 'GSTIN: 29AAAAA1111A1Z1', style: { fontSize: '0.62rem', color: '#64748b', fontWeight: 'bold' } },
}

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
]

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

  return (
    <div style={overlayStyle} onMouseDown={(e) => e.stopPropagation()}>
      <div style={boxStyle}>
        <div style={{ fontWeight: 700, fontSize: '1rem', color: 'var(--text-primary)' }}>
          {step === 'menu'    && '🔒 Passcode Lock'}
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

// ─── Main Component ───────────────────────────────────────────────────────────
export default function Settings() {
  const { authFetch } = useAuth()
  const { config, refreshConfig } = useBusinessConfig()
  const { hasLock, setupPasscode, clearPasscode } = useLock()
  const [showPasscodeModal, setShowPasscodeModal] = useState(false)
  const [activeTab, setActiveTab] = useState('general')
  // Which format the print preview shows (independent of the saved thermal_printer_mode).
  const [previewMode, setPreviewMode] = useState('thermal')
  const [dragKey, setDragKey] = useState(null)   // header line being dragged in the preview

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

  const g   = settings.general
  const t   = settings.transactions
  const inv = settings.inventory
  const pr  = settings.print
  const lb  = settings.labels

  // ── Customisable receipt header: drag to reorder, click L/C/R to align ──────
  const headerLayout = getHeaderLayout(pr)
  const moveHeaderLine = (from, to) => patch('print', 'header_layout', moveItem(headerLayout, from, to))
  const setHeaderAlign = (key, align) =>
    patch('print', 'header_layout', headerLayout.map(l => (l.key === key ? { ...l, align } : l)))

  logger.debug('[Settings] Rendering with activeTab:', activeTab)

  return (
    <AppLayout title="App Settings">
      <div className="slide-up">

        {/* ── Page header (sticky, title + subtitle + Save button) ── */}
        <div className="page-header">
          <div className="page-header-left">
            <h1 className="page-title">App Settings</h1>
            <p className="page-subtitle">Configure how your billing system behaves — transactions, printing, stock, and more.</p>
          </div>
          <button
            className="btn btn-accent"
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
            fontSize: '0.88rem',
            display: 'flex',
            alignItems: 'center',
            gap: 8,
          }}>
            {toast.type === 'success' && <CheckIcon size={14} />}
            {toast.msg}
          </div>
        )}

        {/* Tab strip — pinned directly below the page-header */}
        <div className="page-subbar" style={{
          display: 'flex',
          gap: 4,
          borderBottom: '2px solid var(--border)',
          background: 'var(--bg)',
          overflowX: 'auto',
          marginTop: 0,
          marginLeft: -36,
          marginRight: -36,
          paddingLeft: 36,
          paddingRight: 36,
          marginBottom: 20,
        }}>
          {TABS.map(tab => (
            <button
              key={tab.id}
              onClick={() => handleTabChange(tab.id)}
              style={{
                background: 'none',
                border: 'none',
                padding: '10px 18px',
                cursor: 'pointer',
                fontSize: '0.83rem',
                fontWeight: activeTab === tab.id ? 700 : 500,
                color: activeTab === tab.id ? 'var(--accent)' : 'var(--text-muted)',
                borderBottom: activeTab === tab.id ? '2px solid var(--accent)' : '2px solid transparent',
                marginBottom: -2,
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

        {/* ── Panel body ── */}
        <div className="card" style={{ padding: '4px 28px 28px', borderTopLeftRadius: 0, borderTopRightRadius: 0, marginTop: 0 }}>

          {/* ═══════════════════════════ GENERAL ══════════════════════════════ */}
          {activeTab === 'general' && (
            <>
              <SectionHeader title="Business Category" />
              <SettingRow label="Active Business Type" description="Select your business vertical to automatically configure terminology, layouts, and custom fields.">
                <select
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
                </select>
              </SettingRow>

              <SectionHeader title="Security" />
              <SettingRow label="Passcode Lock" description="Require a passcode to unlock the app after inactivity or manual lock.">
                <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                  {g.passcode_lock && (
                    <button
                      className="btn btn-secondary"
                      style={{ fontSize: '0.78rem', padding: '5px 12px' }}
                      onClick={() => setShowPasscodeModal(true)}
                    >
                      {hasLock ? 'Change PIN' : 'Set PIN'}
                    </button>
                  )}
                  <Toggle id="passcode_lock" checked={g.passcode_lock} onChange={v => {
                    patch('general', 'passcode_lock', v)
                    if (!v) clearPasscode()
                  }} />
                </div>
              </SettingRow>
              {g.passcode_lock && (
                <SettingRow label="Auto-Lock Timeout" description="Lock the session automatically after this period of inactivity.">
                  <select
                    className="form-input"
                    style={{ width: 160 }}
                    value={g.lock_timeout_minutes ?? 60}
                    onChange={e => patch('general', 'lock_timeout_minutes', parseInt(e.target.value))}
                  >
                    <option value={0}>Never</option>
                    <option value={30}>30 minutes</option>
                    <option value={60}>1 hour</option>
                    <option value={120}>2 hours</option>
                  </select>
                </SettingRow>
              )}
              <SettingRow label="Privacy Mode" description="Hide revenue amounts and balances on the dashboard. Useful in customer-facing environments.">
                <Toggle id="privacy_mode" checked={g.privacy_mode} onChange={v => patch('general', 'privacy_mode', v)} />
              </SettingRow>

              <SectionHeader title="Backup" />
              <SettingRow label="Auto Backup" description="Automatically back up your data on schedule.">
                <Toggle id="auto_backup" checked={g.auto_backup} onChange={v => patch('general', 'auto_backup', v)} />
              </SettingRow>
              {g.auto_backup && (
                <SettingRow label="Backup Reminder (days)" description="Alert if no backup taken within this many days.">
                  <input
                    type="number"
                    min={1}
                    max={90}
                    value={g.backup_reminder_days}
                    onChange={e => patch('general', 'backup_reminder_days', parseInt(e.target.value) || 7)}
                    className="form-input"
                    style={{ width: 80, padding: '6px 10px', textAlign: 'center' }}
                  />
                </SettingRow>
              )}

              <SectionHeader title="Number Formats" />
              <SettingRow label="Date Format" description="How dates are displayed across invoices and reports.">
                <select
                  className="form-input"
                  style={{ width: 180 }}
                  value={g.date_format}
                  onChange={e => patch('general', 'date_format', e.target.value)}
                >
                  <option value="DD/MM/YYYY">DD/MM/YYYY</option>
                  <option value="MM/DD/YYYY">MM/DD/YYYY</option>
                  <option value="YYYY-MM-DD">YYYY-MM-DD</option>
                </select>
              </SettingRow>
              <SettingRow label="Quantity Decimal Places" description="Decimal digits for item quantities (e.g. 2.50 kg).">
                <select
                  className="form-input"
                  style={{ width: 100 }}
                  value={g.quantity_decimal_places}
                  onChange={e => patch('general', 'quantity_decimal_places', parseInt(e.target.value))}
                >
                  {[0,1,2,3].map(n => <option key={n} value={n}>{n}</option>)}
                </select>
              </SettingRow>
              <SettingRow label="Amount Decimal Places" description="Decimal digits for currency amounts (e.g. ₹ 100.00).">
                <select
                  className="form-input"
                  style={{ width: 100 }}
                  value={g.amount_decimal_places}
                  onChange={e => patch('general', 'amount_decimal_places', parseInt(e.target.value))}
                >
                  {[0,1,2].map(n => <option key={n} value={n}>{n}</option>)}
                </select>
              </SettingRow>

              <SectionHeader title="Appearance" />
              <SettingRow
                label="App Display Size"
                description={`Scale the entire application UI. Current: ${g.app_zoom ?? 100}%`}
              >
                <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                  <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)', minWidth: 28 }}>80%</span>
                  <input
                    type="range"
                    min={80} max={130} step={5}
                    value={g.app_zoom ?? 100}
                    onChange={e => {
                      const v = parseInt(e.target.value)
                      patch('general', 'app_zoom', v)
                      // Live preview while dragging
                      document.documentElement.style.zoom = `${v}%`
                    }}
                    style={{ width: 140, accentColor: 'var(--accent)' }}
                  />
                  <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)', minWidth: 28 }}>130%</span>
                  <span style={{
                    minWidth: 46, textAlign: 'center', fontWeight: 700,
                    fontSize: '0.85rem', color: 'var(--accent)',
                  }}>
                    {g.app_zoom ?? 100}%
                  </span>
                  {(g.app_zoom ?? 100) !== 100 && (
                    <button
                      className="btn btn-ghost"
                      style={{ fontSize: '0.75rem', padding: '4px 8px' }}
                      onClick={() => {
                        patch('general', 'app_zoom', 100)
                        document.documentElement.style.zoom = '100%'
                      }}
                    >
                      Reset
                    </button>
                  )}
                </div>
              </SettingRow>

              {/* Passcode modal */}
              <PasscodeModal
                open={showPasscodeModal}
                hasLock={hasLock}
                onClose={() => setShowPasscodeModal(false)}
                setupPasscode={setupPasscode}
                clearPasscode={clearPasscode}
              />
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
                  <select
                    className="form-input"
                    style={{ width: 160 }}
                    value={t.round_off_type}
                    onChange={e => patch('transactions', 'round_off_type', e.target.value)}
                  >
                    <option value="nearest">Nearest Rupee</option>
                    <option value="ceil">Round Up</option>
                    <option value="floor">Round Down</option>
                  </select>
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
                  <select className="form-input" style={{ width: 140 }} value={pr.invoice_theme || 'classic'} onChange={e => patch('print', 'invoice_theme', e.target.value)}>
                    <option value="classic">Classic (Vyapar Style)</option>
                    <option value="modern">Modern Professional</option>
                    <option value="minimal">Minimal Compact</option>
                  </select>
                </SettingRow>
                <SettingRow label="Page Size">
                  <select className="form-input" style={{ width: 140 }} value={pr.page_size} onChange={e => patch('print', 'page_size', e.target.value)}>
                    <option value="A4">A4</option>
                    <option value="A5">A5</option>
                    <option value="Letter">Letter</option>
                  </select>
                </SettingRow>
                <SettingRow label="Page Orientation">
                  <select className="form-input" style={{ width: 140 }} value={pr.print_orientation || 'portrait'} onChange={e => patch('print', 'print_orientation', e.target.value)}>
                    <option value="portrait">Portrait</option>
                    <option value="landscape">Landscape</option>
                  </select>
                </SettingRow>
                </>)}
                <SettingRow id="set-text_size" label="Text Size">
                  <select className="form-input" style={{ width: 140 }} value={pr.text_size} onChange={e => patch('print', 'text_size', e.target.value)}>
                    <option value="small">Small</option>
                    <option value="medium">Medium</option>
                    <option value="large">Large</option>
                  </select>
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
                    <SettingRow label="Thermal Paper Size" description="Choose width of your receipt paper roll.">
                      <select className="form-input" style={{ width: 140 }} value={pr.thermal_page_size || '3inch'} onChange={e => patch('print', 'thermal_page_size', e.target.value)}>
                        <option value="3inch">3 Inch (80mm)</option>
                        <option value="2inch">2 Inch (58mm)</option>
                      </select>
                    </SettingRow>
                    <SettingRow label="Thermal Theme">
                      <select className="form-input" style={{ width: 140 }} value={pr.thermal_theme || 'theme_standard'} onChange={e => patch('print', 'thermal_theme', e.target.value)}>
                        <option value="theme_standard">Standard Thermal</option>
                        <option value="theme_compact">Compact Thermal</option>
                      </select>
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
                <SettingRow id="set-counter_id" label="Counter / Terminal ID" description="Shown in the receipt header (e.g. CTR1, CTR2).">
                  <input type="text" className="form-input" style={{ width: 120 }} value={pr.counter_id || ''}
                    onChange={e => patch('print', 'counter_id', e.target.value)} placeholder="CTR1" />
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
                    fontSize: pr.text_size === 'small' ? '0.68rem' : pr.text_size === 'large' ? '0.85rem' : '0.75rem',
                    lineHeight: 1.4,
                    width: '100%',
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
                            <span style={{ opacity: 0.35, fontSize: '0.7rem' }}>⠿</span>
                            <div style={{ flex: 1, textAlign: line.align, ...c.style }}>{c.node}</div>
                            <span className="hdr-align" style={{ display: 'inline-flex', gap: 1 }}>
                              {[['left', 'L'], ['center', 'C'], ['right', 'R']].map(([a, lbl]) => (
                                <button
                                  key={a}
                                  type="button"
                                  onClick={() => setHeaderAlign(line.key, a)}
                                  title={`Align ${a}`}
                                  style={{
                                    fontSize: '0.55rem', lineHeight: 1, padding: '2px 4px', cursor: 'pointer',
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

                    <div style={{ marginBottom: '6px', fontSize: '0.64rem', display: 'flex', flexDirection: 'column', gap: '1px' }}>
                      <div style={{ display: 'flex', justifyContent: 'space-between' }}><span><b>Bill No:</b> 6471</span><span><b>Counter:</b> {pr.counter_id || 'CTR1'}</span></div>
                      <div style={{ display: 'flex', justifyContent: 'space-between' }}><span><b>Date:</b> {new Date().toLocaleDateString('en-IN')}</span><span><b>Time:</b> {new Date().toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit' })}</span></div>
                      <div><b>Cashier:</b> POS</div>
                    </div>

                    <table style={{ width: '100%', borderCollapse: 'collapse', marginBottom: '8px', fontSize: '0.64rem' }}>
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
                          <td>Parle-G {pr.print_item_hsn && <span style={{ fontSize: '0.55rem', color: '#64748b' }}>(1905)</span>}</td>
                          <td style={{ textAlign: 'right' }}>10.00</td>
                          <td style={{ textAlign: 'right' }}>10.00</td>
                          <td style={{ textAlign: 'center' }}>2</td>
                          <td style={{ textAlign: 'right' }}>20.00</td>
                        </tr>
                        <tr style={{ borderBottom: '1px dashed #94a3b8' }}>
                          {pr.print_item_sno !== false && <td>2</td>}
                          <td>Tata Salt {pr.print_item_hsn && <span style={{ fontSize: '0.55rem', color: '#64748b' }}>(2501)</span>}</td>
                          <td style={{ textAlign: 'right' }}>30.00</td>
                          <td style={{ textAlign: 'right' }}>28.00</td>
                          <td style={{ textAlign: 'center' }}>1</td>
                          <td style={{ textAlign: 'right' }}>28.00</td>
                        </tr>
                      </tbody>
                    </table>

                    <div style={{ display: 'flex', flexDirection: 'column', gap: '2px', alignItems: 'flex-end', borderBottom: '1px dashed #94a3b8', paddingBottom: '6px', marginBottom: '6px' }}>
                      <div style={{ display: 'flex', justifyContent: 'space-between', width: '120px', fontSize: '0.68rem' }}>
                        <span>Subtotal:</span>
                        <span>₹46.00</span>
                      </div>
                      {pr.print_item_tax !== false && (
                        <div style={{ display: 'flex', justifyContent: 'space-between', width: '120px', fontSize: '0.68rem' }}>
                          <span>GST (18%):</span>
                          <span>₹4.00</span>
                        </div>
                      )}
                      <div style={{ display: 'flex', justifyContent: 'space-between', width: '120px', fontSize: '0.72rem', fontWeight: 'bold' }}>
                        <span>Grand Total:</span>
                        <span>₹48.00</span>
                      </div>
                    </div>

                    {/* Total quantity vs distinct items + savings (matches the M.R. Traders receipt) */}
                    <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.66rem', marginBottom: '4px' }}>
                      <span>Qty: 3</span>
                      <span>Items: 2</span>
                    </div>
                    <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.7rem', fontWeight: 'bold', color: '#16a34a', marginBottom: '8px' }}>
                      <span>You have Saved:</span>
                      <span>₹2.00</span>
                    </div>

                    {pr.print_tax_breakdown && (
                      <Editable k="print_tax_breakdown" style={{ fontSize: '0.56rem', color: '#475569', marginBottom: '8px' }}>
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
                      <div style={{ fontSize: '0.56rem', color: '#64748b', textAlign: 'center', marginBottom: '8px' }}>
                        {pr.prices_incl_gst && <div>E. &amp; O.E. · Prices Incl. GST</div>}
                        {pr.fssai_no && <div>FSSAI: {pr.fssai_no}</div>}
                      </div>
                    )}

                    {pr.print_amount_in_words && (
                      <Editable k="print_amount_in_words" style={{ fontSize: '0.6rem', color: '#64748b', fontStyle: 'italic', marginBottom: '8px', textAlign: 'center' }}>
                        Rupees Forty-Eight Only
                      </Editable>
                    )}

                    {pr.print_terms_conditions && pr.terms_conditions_text && (
                      <Editable k="print_terms_conditions" style={{ fontSize: '0.6rem', color: '#64748b', textAlign: 'center', borderTop: '1px dashed #94a3b8', paddingTop: '4px', marginTop: '4px' }}>
                        <b>Terms:</b> {pr.terms_conditions_text}
                      </Editable>
                    )}

                    {pr.print_signature && (
                      <div style={{ marginTop: '16px', display: 'flex', justifyContent: 'flex-end' }}>
                        <div style={{ borderTop: '1px dashed #64748b', width: '110px', textAlign: 'center', paddingTop: '2px', fontSize: '0.58rem' }}>
                          {pr.signature_label || 'Authorised Signatory'}
                        </div>
                      </div>
                    )}

                    {pr.customer_signature && (
                      <div style={{ marginTop: '12px', display: 'flex', justifyContent: 'flex-start' }}>
                        <div style={{ borderTop: '1px dashed #64748b', width: '110px', textAlign: 'center', paddingTop: '2px', fontSize: '0.58rem' }}>
                          {pr.customer_signature_label || 'Customer Signature'}
                        </div>
                      </div>
                    )}
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
                    fontSize: pr.text_size === 'small' ? '0.68rem' : pr.text_size === 'large' ? '0.85rem' : '0.75rem',
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
                        <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.68rem' }}>
                          <span>Subtotal:</span>
                          <span>₹46.00</span>
                        </div>
                        {pr.print_item_tax !== false && (
                          <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.68rem' }}>
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
        </div>

        {/* ── Bottom save bar ── */}
        <div style={{ marginTop: 20, display: 'flex', justifyContent: 'flex-end', paddingBottom: 32 }}>
          <button
            className="btn btn-accent"
            onClick={save}
            disabled={saving}
            style={{ display: 'flex', alignItems: 'center', gap: 8 }}
          >
            {saving ? <span className="spinner" style={{ width: 14, height: 14 }} /> : <CheckIcon size={14} />}
            Save Changes
          </button>
        </div>

      </div>
    </AppLayout>
  )
}
