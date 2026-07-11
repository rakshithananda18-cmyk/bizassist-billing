// TwoFactorCard — admin TOTP 2FA enrollment (REVIEW_1 §4.1).
// ==========================================================
// Status → Setup (shows base32 key + otpauth URI for any authenticator app)
// → Confirm with a live 6-digit code → Enabled. Disabling requires a valid
// current code, so a stolen browser session can't silently strip the factor.
import { useState, useEffect, useCallback } from 'react'
import { useAuth } from '../contexts/AuthContext'
import { logger } from '../utils/logger'
import { API_BASE } from '../config'
import { Section, Button } from './ui'
import { Icon } from './icons'

export default function TwoFactorCard() {
  const { authFetch } = useAuth()
  const [status, setStatus] = useState(null)        // { enabled, pending }
  const [setup, setSetup] = useState(null)          // { secret, otpauth_uri }
  const [code, setCode] = useState('')
  const [msg, setMsg] = useState(null)              // { ok, text }
  const [busy, setBusy] = useState(false)
  const [copied, setCopied] = useState(false)

  const load = useCallback(async () => {
    try {
      const res = await authFetch(`${API_BASE}/admin/2fa/status`)
      if (res.ok) setStatus(await res.json())
    } catch (err) { logger.error(err) }
  }, [authFetch])

  useEffect(() => { load() }, [load])

  async function post(path, body) {
    setBusy(true); setMsg(null)
    try {
      const res = await authFetch(`${API_BASE}${path}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        ...(body ? { body: JSON.stringify(body) } : {}),
      })
      const data = await res.json().catch(() => ({}))
      if (!res.ok) throw new Error(data.detail || 'Request failed')
      return data
    } finally {
      setBusy(false)
    }
  }

  async function handleSetup() {
    try {
      const data = await post('/admin/2fa/setup')
      setSetup(data)
      setCode('')
      setMsg(null)
    } catch (err) { setMsg({ ok: false, text: err.message }) }
  }

  async function handleConfirm(e) {
    e.preventDefault()
    try {
      const data = await post('/admin/2fa/confirm', { code })
      setMsg({ ok: true, text: data.message })
      setSetup(null); setCode('')
      load()
    } catch (err) { setMsg({ ok: false, text: err.message }) }
  }

  async function handleDisable(e) {
    e.preventDefault()
    try {
      const data = await post('/admin/2fa/disable', { code })
      setMsg({ ok: true, text: data.message })
      setCode('')
      load()
    } catch (err) { setMsg({ ok: false, text: err.message }) }
  }

  const codeInput = (
    <input
      type="text" inputMode="numeric" maxLength={6} placeholder="6-digit code"
      value={code} onChange={e => setCode(e.target.value.replace(/\D/g, ''))}
      style={{
        width: 130, padding: '7px 10px', borderRadius: 8, textAlign: 'center',
        border: '1px solid var(--border-color)', background: 'transparent',
        color: 'var(--text-color)', fontFamily: "'Geist Mono',monospace",
        letterSpacing: '0.3em', fontSize: 14,
      }}
    />
  )

  return (
    <Section title="Admin sign-in security (2FA)" icon={<Icon name="settings" size={16} />} collapsible style={{ marginTop: 24 }}>
      {status === null ? (
        <div className="vskel" style={{ padding: 10 }}></div>
      ) : status.enabled ? (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
          <div style={{ fontSize: 13 }}>
            <span className="tag" style={{ background: 'rgba(58,154,92,0.12)', color: '#3a9a5c', fontWeight: 700, textTransform: 'uppercase', fontSize: 10, marginRight: 8 }}>Enabled</span>
            Every admin sign-in asks for a 6-digit code from your authenticator app
            {status.confirmed_at ? <span style={{ color: 'var(--secondary-text)' }}> (since {String(status.confirmed_at).slice(0, 10)})</span> : null}.
          </div>
          <form onSubmit={handleDisable} style={{ display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap' }}>
            {codeInput}
            <Button variant="danger" type="submit" disabled={busy || code.length !== 6}>Disable 2FA</Button>
            <span style={{ fontSize: 12, color: 'var(--secondary-text)' }}>Enter a current code to disable.</span>
          </form>
        </div>
      ) : setup ? (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          <div style={{ fontSize: 13 }}>
            Add this key to Google Authenticator / Authy / 1Password (choose "enter a setup key", account name <b>BizAssist Admin</b>, time-based):
          </div>
          <div style={{
            display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap',
            background: 'var(--hover-bg)', borderRadius: 8, padding: '10px 14px',
          }}>
            <code style={{ fontFamily: "'Geist Mono',monospace", fontSize: 15, letterSpacing: '0.12em', wordBreak: 'break-all' }}>
              {setup.secret}
            </code>
            <Button variant="secondary" type="button" onClick={() => {
              navigator.clipboard.writeText(setup.secret)
              setCopied(true); setTimeout(() => setCopied(false), 1500)
            }}>{copied ? 'Copied' : 'Copy key'}</Button>
          </div>
          <details style={{ fontSize: 12, color: 'var(--secondary-text)' }}>
            <summary style={{ cursor: 'pointer' }}>otpauth:// URI (for apps that accept links)</summary>
            <code style={{ fontSize: 11, wordBreak: 'break-all' }}>{setup.otpauth_uri}</code>
          </details>
          <form onSubmit={handleConfirm} style={{ display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap' }}>
            {codeInput}
            <Button variant="primary" type="submit" disabled={busy || code.length !== 6}>Confirm & enable</Button>
            <Button variant="secondary" type="button" onClick={() => { setSetup(null); setCode('') }}>Cancel</Button>
          </form>
        </div>
      ) : (
        <div style={{ display: 'flex', alignItems: 'center', gap: 14, flexWrap: 'wrap' }}>
          <div style={{ fontSize: 13, flex: 1, minWidth: 260 }}>
            <span className="tag" style={{ background: 'rgba(214,158,46,0.14)', color: '#b7791f', fontWeight: 700, textTransform: 'uppercase', fontSize: 10, marginRight: 8 }}>Off</span>
            This console can grant plans, revoke sessions and wipe data — protect it with a second factor.
            Takes one minute with any authenticator app.
          </div>
          <Button variant="primary" onClick={handleSetup} disabled={busy}>Set up 2FA</Button>
        </div>
      )}
      {msg && (
        <div style={{ marginTop: 10, fontSize: 12.5, fontWeight: 600, color: msg.ok ? '#3a9a5c' : '#c53030' }}>
          {msg.ok ? '✓ ' : ''}{msg.text}
        </div>
      )}
    </Section>
  )
}
