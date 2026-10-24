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
import React, { useEffect, useId, useRef } from 'react'
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
  const dialogRef = useRef(null)
  const previousFocus = useRef(null)
  const onCloseRef = useRef(onClose)
  const titleId = useId()
  onCloseRef.current = onClose

  useEffect(() => {
    if (!open) return
    previousFocus.current = document.activeElement
    const onKey = (e) => {
      if (e.key !== 'Escape') return
      const dialogs = document.querySelectorAll('[role="dialog"][aria-modal="true"]')
      if (dialogs[dialogs.length - 1] === dialogRef.current) onCloseRef.current?.()
    }
    document.addEventListener('keydown', onKey)
    const prevOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    const focusFirst = () => {
      const dialog = dialogRef.current
      if (!dialog) return
      // A field the form autoFocused already has the cursor: keep it there.
      if (dialog.contains(document.activeElement) && document.activeElement !== dialog) return
      // Otherwise the first field to type in, not the header's close button -
      // a cashier opening "Record payment" should be able to type at once.
      const field = dialog.querySelector(
        'input:not([disabled]):not([type="hidden"]), select:not([disabled]), textarea:not([disabled])'
      )
      const focusables = dialog.querySelectorAll(
        'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'
      )
      ;(field || focusables[0] || dialog).focus()
    }
    const frame = window.requestAnimationFrame
      ? window.requestAnimationFrame(focusFirst)
      : window.setTimeout(focusFirst, 0)
    return () => {
      document.removeEventListener('keydown', onKey)
      document.body.style.overflow = prevOverflow
      if (window.cancelAnimationFrame) window.cancelAnimationFrame(frame)
      else window.clearTimeout(frame)
      previousFocus.current?.focus?.()
    }
  }, [open])

  const trapFocus = (event) => {
    if (event.key !== 'Tab') return
    const focusables = [...(dialogRef.current?.querySelectorAll(
      'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'
    ) || [])]
    if (!focusables.length) { event.preventDefault(); dialogRef.current?.focus(); return }
    const first = focusables[0]
    const last = focusables[focusables.length - 1]
    if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus() }
    else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus() }
  }

  if (!open) return null

  return createPortal(
    <div
      className="modal-overlay"
      onMouseDown={(e) => {
        if (closeOnOverlay && e.target === e.currentTarget) onClose?.()
      }}
      onTouchStart={(e) => {
        // Prevent touch events from reaching elements underneath the overlay
        if (e.target === e.currentTarget) {
          e.stopPropagation()
          if (closeOnOverlay) onClose?.()
        } else {
          e.stopPropagation()
        }
      }}
    >
      <div
        ref={dialogRef}
        className={`modal${size ? ` modal-${size}` : ''}`}
        role="dialog"
        aria-modal="true"
        aria-labelledby={title ? titleId : undefined}
        aria-label={title ? undefined : 'Dialog'}
        tabIndex="-1"
        onKeyDown={trapFocus}
      >
        {(title || showClose) && (
          <div className="modal-header">
            <div id={titleId} className="modal-title">{title}</div>
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
