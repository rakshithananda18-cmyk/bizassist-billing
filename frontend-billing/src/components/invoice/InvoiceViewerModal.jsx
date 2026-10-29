// ============================================================================
// InvoiceViewerModal — full-screen invoice viewer portal, extracted verbatim
// from pages/Payments.jsx / pages/Dashboard.jsx where it was duplicated
// (repo restructure). Renders at document.body; embedded InvoiceViewer so
// Back/× both close the modal.
// ============================================================================
import React, { useEffect, useRef } from 'react'
import { createPortal } from 'react-dom'
import InvoiceViewer from '../../invoice/InvoiceViewer'

export default function InvoiceViewerModal({ invoiceNo, onClose }) {
  const dialogRef = useRef(null)
  const closeRef = useRef(onClose)
  const printEscapeGuard = useRef(0)
  closeRef.current = onClose
  useEffect(() => {
    if (!invoiceNo) return
    const previousFocus = document.activeElement
    const previousOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    const frame = window.requestAnimationFrame(() => {
      const dialog = dialogRef.current
      ;(dialog?.querySelector('button[aria-label="Close invoice viewer"]') || dialog)?.focus()
    })
    const beforePrint = () => { printEscapeGuard.current = Infinity }
    const afterPrint = () => { printEscapeGuard.current = Date.now() + 500 }
    window.addEventListener('beforeprint', beforePrint)
    window.addEventListener('afterprint', afterPrint)
    return () => {
      window.cancelAnimationFrame(frame)
      window.removeEventListener('beforeprint', beforePrint)
      window.removeEventListener('afterprint', afterPrint)
      document.body.style.overflow = previousOverflow
      if (previousFocus?.isConnected) previousFocus.focus?.()
    }
  }, [invoiceNo])

  const handleKey = event => {
    if (event.target.closest?.('[role="alertdialog"]')) return
    if (event.key === 'Escape') {
      event.preventDefault()
      event.stopPropagation()
      if (Date.now() >= printEscapeGuard.current) closeRef.current?.()
    } else if (event.key === 'Tab') {
      const dialog = dialogRef.current
      const controls = dialog?.querySelectorAll('button:not([disabled]), a[href], input:not([disabled]), select:not([disabled]), [tabindex="0"]') || []
      const first = controls[0], last = controls[controls.length - 1]
      if (!first) { event.preventDefault(); dialog?.focus() }
      else if (event.shiftKey && (document.activeElement === first || document.activeElement === dialog)) { event.preventDefault(); last.focus() }
      else if (!event.shiftKey && (document.activeElement === last || document.activeElement === dialog)) { event.preventDefault(); first.focus() }
    }
  }
  if (!invoiceNo) return null
  return createPortal(
    <div
      role="dialog"
      aria-modal="true"
      aria-label="Invoice viewer"
      tabIndex={-1}
      ref={dialogRef}
      onKeyDown={handleKey}
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
        @keyframes slideUpModal { from { transform: translateY(24px); opacity: 0 } to { transform: none; opacity: 1 } }
      `}</style>

      {/* Modal shell */}
      <div style={{
        margin: 'auto',
        width: '96vw', maxWidth: 1240,
        height: '92vh', maxHeight: '92dvh',
        background: 'var(--bg-2)',
        borderRadius: 'var(--radius-lg, 14px)',
        border: '1px solid var(--border)',
        boxShadow: 'var(--shadow-lg, 0 24px 80px rgba(0,0,0,0.45))',
        display: 'flex', flexDirection: 'column',
        overflow: 'hidden',
        animation: 'slideUpModal 0.22s cubic-bezier(0.34,1.56,0.64,1)',
      }}>
        {/* The full InvoiceViewer — embedded mode with integrated toolbar close button */}
        <div style={{ flex: 1, minHeight: 0, overflow: 'hidden' }}>
          <InvoiceViewer
            key={invoiceNo}
            invoiceNo={invoiceNo}
            embedded
            onBack={onClose}
            onClose={onClose}
          />
        </div>
      </div>
    </div>,
    document.body
  )
}
