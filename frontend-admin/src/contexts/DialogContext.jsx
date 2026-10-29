import React, { createContext, useContext, useEffect, useRef, useState } from 'react'
import { Icon } from '../components/icons'

const DialogContext = createContext(null)

export function useDialog() {
  return useContext(DialogContext)
}

export function DialogProvider({ children }) {
  const [dialog, setDialog] = useState(null) // { type: 'alert'|'confirm', message, resolve }
  const dialogRef = useRef(null)

  useEffect(() => {
    if (!dialog) return undefined
    const previousFocus = document.activeElement
    const controls = () => Array.from(dialogRef.current?.querySelectorAll('button:not([disabled])') || [])
    controls()[0]?.focus()
    const onKey = event => {
      if (event.key === 'Escape') {
        event.preventDefault()
        event.stopImmediatePropagation()
        dialog.resolve(false)
        setDialog(null)
      } else if (event.key === 'Tab') {
        const buttons = controls()
        const index = buttons.indexOf(document.activeElement)
        if (event.shiftKey && index <= 0) { event.preventDefault(); buttons.at(-1)?.focus() }
        else if (!event.shiftKey && (index < 0 || index === buttons.length - 1)) { event.preventDefault(); buttons[0]?.focus() }
      }
    }
    document.addEventListener('keydown', onKey, true)
    return () => {
      document.removeEventListener('keydown', onKey, true)
      if (previousFocus?.isConnected) previousFocus.focus?.()
    }
  }, [dialog])

  const showAlert = (message) => {
    return new Promise((resolve) => {
      setDialog({ type: 'alert', message, resolve })
    })
  }

  const showConfirm = (message) => {
    return new Promise((resolve) => {
      setDialog({ type: 'confirm', message, resolve })
    })
  }

  const formatDialogMessage = (payload, fallback = 'Unknown error') => {
    if (!payload) return fallback
    if (typeof payload === 'string') return payload
    if (payload instanceof Error) return payload.message || fallback
    if (typeof payload === 'object') {
      return payload.error || payload.detail || payload.message || payload.statusText || fallback
    }
    return String(payload)
  }

  const showError = (error, title = 'Error') => {
    const message = formatDialogMessage(error, 'Unknown error')
    return showAlert(title ? `${title}: ${message}` : message)
  }

  const handleClose = (value) => {
    if (dialog && dialog.resolve) {
      dialog.resolve(value)
    }
    setDialog(null)
  }

  return (
    <DialogContext.Provider value={{ showAlert, showConfirm, showError }}>
      {children}
      {dialog && (
        <div className="custom-modal-overlay" style={{ zIndex: 99999 }}>
          <div className="custom-modal-card" ref={dialogRef} role="alertdialog" aria-modal="true" aria-label={dialog.type === 'confirm' ? 'Confirm Action' : 'Notification'} style={{ maxWidth: 420 }}>
            <div className="custom-modal-title">
              {dialog.type === 'confirm' ? (
                <span style={{ display: 'inline-flex', alignItems: 'center', gap: 8 }}>
                  <Icon name="warn" size={18} style={{ color: 'var(--warning)' }} /> Confirm Action
                </span>
              ) : (
                <span style={{ display: 'inline-flex', alignItems: 'center', gap: 8 }}>
                  <Icon name="alert" size={18} style={{ color: 'var(--accent)' }} /> Notification
                </span>
              )}
            </div>
            <div className="custom-modal-body" style={{ margin: '10px 0 16px', fontSize: '13.5px', lineHeight: '1.5', color: 'var(--text-primary)' }}>
              {dialog.message.split('\n').map((line, idx) => (
                <div key={idx} style={{ marginBottom: line ? '6px' : '10px' }}>{line}</div>
              ))}
            </div>
            <div className="custom-modal-actions" style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
              {dialog.type === 'confirm' && (
                <button className="btn-flush" onClick={() => handleClose(false)}>
                  Cancel
                </button>
              )}
              <button className="btn-primary" onClick={() => handleClose(true)}>
                {dialog.type === 'confirm' ? 'Confirm' : 'OK'}
              </button>
            </div>
          </div>
        </div>
      )}
    </DialogContext.Provider>
  )
}
