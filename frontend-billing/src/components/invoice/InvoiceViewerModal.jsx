// ============================================================================
// InvoiceViewerModal — full-screen invoice viewer portal, extracted verbatim
// from pages/Payments.jsx / pages/Dashboard.jsx where it was duplicated
// (repo restructure). Renders at document.body; embedded InvoiceViewer so
// Back/× both close the modal.
// ============================================================================
import React from 'react'
import { createPortal } from 'react-dom'
import InvoiceViewer from '../../invoice/InvoiceViewer'

export default function InvoiceViewerModal({ invoiceNo, onClose }) {
  if (!invoiceNo) return null
  return createPortal(
    <div
      role="dialog"
      aria-modal="true"
      aria-label="Invoice viewer"
      className="no-print"
      style={{
        position: 'fixed', inset: 0, zIndex: 1200,
        display: 'flex', flexDirection: 'column',
        background: 'rgba(0,0,0,0.55)',
        backdropFilter: 'blur(4px)',
        animation: 'fadeInBackdrop 0.18s ease',
      }}
      onClick={(e) => { if (e.target === e.currentTarget) onClose() }}
    >
      <style>{`
        @keyframes fadeInBackdrop { from { opacity: 0 } to { opacity: 1 } }
        @keyframes slideUpModal { from { transform: translateY(32px); opacity: 0 } to { transform: none; opacity: 1 } }
      `}</style>

      {/* Modal shell */}
      <div style={{
        margin: 'auto',
        width: '96vw', maxWidth: 1200,
        height: '92vh',
        background: 'var(--bg-2)',
        borderRadius: 'var(--radius-lg, 14px)',
        border: '1px solid var(--border)',
        boxShadow: '0 24px 80px rgba(0,0,0,0.45)',
        display: 'flex', flexDirection: 'column',
        overflow: 'hidden',
        animation: 'slideUpModal 0.22s cubic-bezier(0.34,1.56,0.64,1)',
      }}>
        {/* Close strip */}
        <div style={{
          display: 'flex', justifyContent: 'flex-end', alignItems: 'center',
          padding: '6px 10px 0',
          flexShrink: 0,
        }}>
          <button
            onClick={onClose}
            aria-label="Close invoice viewer"
            style={{
              background: 'var(--bg-3)', border: '1px solid var(--border)',
              borderRadius: '50%', width: 28, height: 28,
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              cursor: 'pointer', color: 'var(--text-secondary)',
              fontSize: '1.1rem', lineHeight: 1, flexShrink: 0,
              transition: 'background 0.15s, color 0.15s',
            }}
            onMouseEnter={e => { e.currentTarget.style.background = 'var(--danger-dim)'; e.currentTarget.style.color = 'var(--danger)' }}
            onMouseLeave={e => { e.currentTarget.style.background = 'var(--bg-3)'; e.currentTarget.style.color = 'var(--text-secondary)' }}
          >
            ×
          </button>
        </div>

        {/* The full InvoiceViewer — embedded mode so Back/× both close the modal */}
        <div style={{ flex: 1, minHeight: 0, overflow: 'hidden' }}>
          <InvoiceViewer
            key={invoiceNo}
            invoiceNo={invoiceNo}
            embedded
            onBack={onClose}
          />
        </div>
      </div>
    </div>,
    document.body
  )
}
