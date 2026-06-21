import React, { createContext, useContext, useState } from 'react'

const DialogContext = createContext(null)

export function useDialog() {
  return useContext(DialogContext)
}

export function DialogProvider({ children }) {
  const [dialog, setDialog] = useState(null) // { type: 'alert'|'confirm', message, resolve }

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
          <div className="custom-modal-card" style={{ maxWidth: 420 }}>
            <div className="custom-modal-title">
              {dialog.type === 'confirm' ? '⚠️ Confirm Action' : 'ℹ️ Notification'}
            </div>
            <div className="custom-modal-body" style={{ margin: '8px 0', fontSize: '14px', lineHeight: '1.5' }}>
              {dialog.message.split('\n').map((line, idx) => (
                <div key={idx} style={{ marginBottom: line ? '6px' : '12px' }}>{line}</div>
              ))}
            </div>
            <div className="custom-modal-actions">
              {dialog.type === 'confirm' && (
                <button className="custom-modal-btn cancel-btn" onClick={() => handleClose(false)}>
                  Cancel
                </button>
              )}
              <button className="custom-modal-btn confirm-btn" onClick={() => handleClose(true)}>
                OK
              </button>
            </div>
          </div>
        </div>
      )}
    </DialogContext.Provider>
  )
}
