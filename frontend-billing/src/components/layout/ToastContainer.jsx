// ============================================================================
// ToastContainer — global toast portal, extracted verbatim from
// layouts/AppLayout.jsx (repo restructure). Rendered at document.body to
// escape overflow:hidden on .app-shell. Presentational only.
// ============================================================================
import React from 'react'
import { createPortal } from 'react-dom'
import { CheckIcon, AlertIcon, SummaryIcon, CloseIcon } from '../Icons'

export default function ToastContainer({ toasts, onDismiss }) {
  if (!toasts.length) return null
  return createPortal(
    <div style={{
      position: 'fixed',
      bottom: 24,
      right: 24,
      zIndex: 99999,
      display: 'flex',
      flexDirection: 'column',
      gap: 10,
      maxWidth: 360,
      pointerEvents: 'none'
    }}>
      {toasts.map(toast => (
        <div key={toast.id} style={{
          pointerEvents: 'auto',
          background: 'var(--bg-3, #fff)',
          border: '1px solid var(--border, #e2e8f0)',
          borderLeft: `4px solid ${
            toast.type === 'success' ? 'var(--success, #22c55e)' :
            toast.type === 'error' ? 'var(--danger, #ef4444)' :
            toast.type === 'warning' ? 'var(--warning, #f59e0b)' : 'var(--accent, #3b82f6)'
          }`,
          padding: '12px 16px',
          borderRadius: 'var(--radius-md, 8px)',
          boxShadow: '0 10px 30px -5px rgba(0,0,0,0.25)',
          display: 'flex',
          alignItems: 'center',
          gap: 12,
          animation: 'slideIn 0.2s ease-out',
          minWidth: 240
        }}>
          <span style={{ display: 'inline-flex', alignItems: 'center', flexShrink: 0 }}>
            {toast.type === 'success' ? <CheckIcon size={16} style={{ color: 'var(--success, #22c55e)' }} /> :
             toast.type === 'error' ? <AlertIcon size={16} style={{ color: 'var(--danger, #ef4444)' }} /> :
             toast.type === 'warning' ? <AlertIcon size={16} style={{ color: 'var(--warning, #f59e0b)' }} /> :
             <SummaryIcon size={16} style={{ color: 'var(--accent, #3b82f6)' }} />}
          </span>
          <span style={{ fontSize: '0.82rem', fontWeight: 500, color: 'var(--text, #1e293b)', lineHeight: 1.4, flex: 1 }}>
            {toast.msg}
          </span>
          <button
            onClick={() => onDismiss(toast.id)}
            style={{
              background: 'none',
              border: 'none',
              color: 'var(--text-muted, #64748b)',
              cursor: 'pointer',
              marginLeft: 4,
              display: 'flex',
              alignItems: 'center',
              padding: 0,
              flexShrink: 0
            }}
            aria-label="Close"
          >
            <CloseIcon size={14} />
          </button>
        </div>
      ))}
    </div>,
    document.body
  )
}
