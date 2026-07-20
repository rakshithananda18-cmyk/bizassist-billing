import React, { useState, useEffect, useRef } from 'react'
import { LockIcon } from '../Icons'
import { overlayStyle, boxStyle, inputStyle } from './SettingsPrimitives'

// ── Passcode Setup Modal ──────────────────────────────────────────────────
export default function PasscodeModal({ open, hasLock, onClose, setupPasscode, clearPasscode }) {
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

