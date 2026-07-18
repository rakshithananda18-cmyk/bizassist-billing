// ============================================================================
// UnsavedChangesModal.jsx
// Styled in-app modal that fires when React Router's useBlocker intercepts
// a navigation attempt while the page has unsaved state.
//
// Usage:
//   const { blocker, dirtyMessage } = usePageLifecycle({ isDirty, ... })
//   <UnsavedChangesModal blocker={blocker} message={dirtyMessage} />
// ============================================================================

import React, { useEffect } from 'react'
import { createPortal } from 'react-dom'

export default function UnsavedChangesModal({ blocker, message }) {
  const isBlocked = blocker?.state === 'blocked'

  // Dismiss on Escape
  useEffect(() => {
    if (!isBlocked) return
    function onKey(e) {
      if (e.key === 'Escape') blocker.reset()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [isBlocked, blocker])

  if (!isBlocked) return null

  return createPortal(
    <>
      {/* Backdrop */}
      <div
        onClick={() => blocker.reset()}
        style={{
          position: 'fixed', inset: 0,
          background: 'rgba(0,0,0,0.45)',
          backdropFilter: 'blur(3px)',
          zIndex: 999990,
          animation: 'ucm-fade-in 0.15s ease',
        }}
      />

      {/* Dialog */}
      <div
        role="alertdialog"
        aria-modal="true"
        aria-labelledby="ucm-title"
        aria-describedby="ucm-desc"
        style={{
          position: 'fixed',
          top: '50%', left: '50%',
          transform: 'translate(-50%,-50%)',
          zIndex: 999991,
          width: 380,
          background: 'var(--bg-2)',
          border: '1px solid var(--border)',
          borderRadius: 14,
          boxShadow: '0 24px 60px rgba(0,0,0,0.35)',
          padding: '28px 28px 24px',
          animation: 'ucm-slide-in 0.18s cubic-bezier(.34,1.56,.64,1)',
        }}
      >
        {/* Icon */}
        <div style={{
          width: 44, height: 44, borderRadius: 12,
          background: 'rgba(234,179,8,0.12)',
          border: '1px solid rgba(234,179,8,0.3)',
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          marginBottom: 16,
        }}>
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none"
            stroke="#eab308" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/>
            <line x1="12" y1="9" x2="12" y2="13"/>
            <line x1="12" y1="17" x2="12.01" y2="17"/>
          </svg>
        </div>

        <h3 id="ucm-title" style={{
          margin: '0 0 8px',
          fontSize: '1rem', fontWeight: 700,
          color: 'var(--text-primary)',
        }}>
          Unsaved changes
        </h3>

        <p id="ucm-desc" style={{
          margin: '0 0 24px',
          fontSize: '0.875rem',
          color: 'var(--text-secondary)',
          lineHeight: 1.5,
        }}>
          {message || 'You have unsaved changes. Are you sure you want to leave?'}
        </p>

        <div style={{ display: 'flex', gap: 10, justifyContent: 'flex-end' }}>
          <button
            className="btn btn-secondary"
            onClick={() => blocker.reset()}
            style={{ minWidth: 80 }}
          >
            Stay
          </button>
          <button
            className="btn btn-primary"
            onClick={() => blocker.proceed()}
            style={{
              minWidth: 120,
              background: '#ef4444',
              borderColor: '#ef4444',
            }}
          >
            Leave anyway
          </button>
        </div>
      </div>

      <style>{`
        @keyframes ucm-fade-in {
          from { opacity: 0 } to { opacity: 1 }
        }
        @keyframes ucm-slide-in {
          from { opacity: 0; transform: translate(-50%,-54%) scale(0.96); }
          to   { opacity: 1; transform: translate(-50%,-50%) scale(1); }
        }
      `}</style>
    </>,
    document.body
  )
}
