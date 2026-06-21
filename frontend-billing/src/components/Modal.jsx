// src/components/Modal.jsx — one modal, matching the app's existing markup.
// ========================================================================
// The `.modal-overlay > .modal > (.modal-header/.modal-body/.modal-footer)`
// structure is hand-repeated ~4× in Sales.jsx (and across other pages). This
// renders that exact structure via a portal, plus the behaviours every modal
// should have: ESC to close, click-outside to close, and body-scroll lock.
//
//   <Modal open={show} title="Add customer" onClose={() => setShow(false)}
//          size="lg" footer={<button onClick={save}>Save</button>}>
//     ...form...
//   </Modal>
import React, { useEffect } from 'react'
import { createPortal } from 'react-dom'
import { CloseIcon } from './Icons'

export default function Modal({
  open,
  title,
  onClose,
  children,
  footer = null,
  size = '',                 // '' | 'lg' → adds .modal-lg
  closeOnOverlay = true,
  showClose = true,
}) {
  // ESC to close + lock background scroll while open.
  useEffect(() => {
    if (!open) return
    const onKey = (e) => { if (e.key === 'Escape') onClose?.() }
    document.addEventListener('keydown', onKey)
    const prevOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => {
      document.removeEventListener('keydown', onKey)
      document.body.style.overflow = prevOverflow
    }
  }, [open, onClose])

  if (!open) return null

  return createPortal(
    <div
      className="modal-overlay"
      onMouseDown={(e) => {
        if (closeOnOverlay && e.target === e.currentTarget) onClose?.()
      }}
    >
      <div className={`modal${size ? ` modal-${size}` : ''}`} role="dialog" aria-modal="true">
        {(title || showClose) && (
          <div className="modal-header">
            <div className="modal-title">{title}</div>
            {showClose && (
              <button type="button" className="modal-close" aria-label="Close" onClick={onClose}>
                <CloseIcon />
              </button>
            )}
          </div>
        )}
        <div className="modal-body">{children}</div>
        {footer && <div className="modal-footer">{footer}</div>}
      </div>
    </div>,
    document.body,
  )
}
