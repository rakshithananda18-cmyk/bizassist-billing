import { useEffect } from 'react'

/**
 * Generic modal shell — the shared template for popups/forms.
 * Handles overlay, centered card, title + close button, scroll for tall
 * content, click-outside-to-close and Escape-to-close.
 */
export default function Modal({
  title,
  onClose,
  children,
  footer,
  maxWidth = 480,
  closeOnOverlay = true,
}) {
  useEffect(() => {
    function onKey(e) {
      if (e.key === 'Escape' && onClose) onClose()
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [onClose])

  return (
    <div
      className="custom-modal-overlay"
      onClick={closeOnOverlay && onClose ? onClose : undefined}
    >
      <div
        className="custom-modal-card"
        style={{ maxWidth }}
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
      >
        {(title || onClose) && (
          <div className="custom-modal-header">
            {title ? <span className="custom-modal-title">{title}</span> : <span />}
            {onClose && (
              <button
                type="button"
                className="custom-modal-close"
                onClick={onClose}
                title="Close"
                aria-label="Close"
              >
                ×
              </button>
            )}
          </div>
        )}

        <div className="custom-modal-body">{children}</div>

        {footer && <div className="custom-modal-actions">{footer}</div>}
      </div>
    </div>
  )
}
