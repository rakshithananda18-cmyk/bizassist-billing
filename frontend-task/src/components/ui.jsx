// components/ui.jsx — small shared pieces aligned with bizassist-billing
import React, { createContext, useCallback, useContext, useEffect, useId, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { CloseIcon } from './Icons'
import { SkylineLoader } from './Logo'

export function PageHeader({ title, subtitle, children, badge }) {
  return (
    <div className="page-header">
      <div className="page-header-left">
        <div className="row" style={{ gap: 8 }}>
          <h1 className="page-title" style={{ margin: 0 }}>{title}</h1>
          {badge && <span className="badge badge-accent">{badge}</span>}
        </div>
        {subtitle && <div className="page-subtitle">{subtitle}</div>}
      </div>
      {children && <div className="row wrap">{children}</div>}
    </div>
  )
}

export function Card({ title, subtitle, action, plain = false, glass = false, children, className = '', style }) {
  const classes = ['card', plain && 'plain', glass && 'card-glass', className].filter(Boolean).join(' ')
  return (
    <div className={classes} style={style}>
      {(title || subtitle || action) && (
        <div className="row-between" style={{ marginBottom: 14 }}>
          <div>
            {title && <h3>{title}</h3>}
            {subtitle && <div className="xs muted" style={{ marginTop: -10, marginBottom: 4 }}>{subtitle}</div>}
          </div>
          {action && <div className="row wrap">{action}</div>}
        </div>
      )}
      {children}
    </div>
  )
}

export function Stat({ label, value, sub, progress, icon, badge, trend }) {
  return (
    <div className="stat-card">
      <div className="row-between">
        <div className="stat-label">{label}</div>
        {icon && <div className="stat-icon accent">{icon}</div>}
      </div>
      <div className="stat-value">{value}</div>
      {progress != null && (
        <div className={`progress ${progress >= 100 ? 'ok' : ''}`}>
          <span style={{ width: `${Math.min(100, Math.max(0, progress))}%` }} />
        </div>
      )}
      {(sub || badge || trend != null) && (
        <div className="row-between" style={{ marginTop: 2 }}>
          {sub && <div className="stat-sub">{sub}</div>}
          {badge && <span className="stat-badge">{badge}</span>}
          {trend != null && (
            <span className={`stat-badge ${trend >= 0 ? 'up' : 'down'}`}>
              {trend >= 0 ? '↑' : '↓'} {Math.abs(trend)}%
            </span>
          )}
        </div>
      )}
    </div>
  )
}

export function Badge({ kind = 'muted', children, className = '', style }) {
  return (
    <span className={`badge badge-${kind} ${className}`.trim()} style={style}>
      {children}
    </span>
  )
}

export function PageTabs({ tabs = [], active, onChange }) {
  return (
    <nav className="page-tabs" role="tablist">
      {tabs.map(t => {
        const id = typeof t === 'string' ? t : t.id
        const label = typeof t === 'string' ? t : t.label
        const count = typeof t === 'object' ? t.count : undefined
        const isSelected = active === id
        return (
          <button
            key={id}
            type="button"
            role="tab"
            aria-selected={isSelected}
            className={`page-tab ${isSelected ? 'active' : ''}`}
            onClick={() => onChange?.(id)}
          >
            <span>{label}</span>
            {count != null && <span className="page-tab-count">{count}</span>}
          </button>
        )
      })}
    </nav>
  )
}

export function Loader({ label = 'Loading…' }) {
  return (
    <div className="empty" style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 12 }}>
      <SkylineLoader size={56} />
      <span className="small muted">{label}</span>
    </div>
  )
}

export function Empty({ children }) {
  return <div className="empty">{children}</div>
}

export function ErrorNote({ error }) {
  if (!error) return null
  return <div className="alert alert-danger">{error.message || String(error)}</div>
}

export function Modal({ title, onClose, children, footer, wide }) {
  const overlay = useRef(null)
  const dialog = useRef(null)
  const previousFocus = useRef(null)
  const onCloseRef = useRef(onClose)
  const titleId = useId()
  onCloseRef.current = onClose
  useEffect(() => {
    previousFocus.current = document.activeElement
    const onKey = (e) => {
      if (e.key !== 'Escape') return
      const open = document.querySelectorAll('.modal-overlay')
      if (open[open.length - 1] === overlay.current) onCloseRef.current?.()
    }
    window.addEventListener('keydown', onKey)
    const previousOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    const focusFirst = () => {
      const focusables = dialog.current?.querySelectorAll(
        'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'
      )
      ;(focusables?.[0] || dialog.current)?.focus()
    }
    const frame = window.requestAnimationFrame ? window.requestAnimationFrame(focusFirst) : window.setTimeout(focusFirst, 0)
    return () => {
      window.removeEventListener('keydown', onKey)
      document.body.style.overflow = previousOverflow
      if (window.cancelAnimationFrame) window.cancelAnimationFrame(frame)
      else window.clearTimeout(frame)
      previousFocus.current?.focus?.()
    }
  }, [])
  const trapFocus = (event) => {
    if (event.key !== 'Tab') return
    const focusables = [...(dialog.current?.querySelectorAll(
      'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'
    ) || [])]
    if (!focusables.length) { event.preventDefault(); dialog.current?.focus(); return }
    const first = focusables[0]
    const last = focusables[focusables.length - 1]
    if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus() }
    else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus() }
  }
  return createPortal(
    <div ref={overlay} className="modal-overlay" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose?.() }}>
      <div ref={dialog} className="modal" style={wide ? { maxWidth: 820 } : undefined} role="dialog" aria-modal="true" aria-labelledby={title ? titleId : undefined} aria-label={title ? undefined : 'Dialog'} tabIndex="-1" onKeyDown={trapFocus}>
        <div className="modal-header">
          <div id={titleId} className="modal-title">{title}</div>
          <button type="button" className="btn btn-ghost btn-sm" onClick={onClose} aria-label="Close"><CloseIcon size={18} /></button>
        </div>
        <div className="modal-body">{children}</div>
        {footer && <div className="modal-footer">{footer}</div>}
      </div>
    </div>,
    document.body,
  )
}

export function ConfirmDialog({ title, message, confirmLabel = 'Confirm', onConfirm, onCancel, danger = true }) {
  return (
    <Modal
      title={title}
      onClose={onCancel}
      footer={(
        <div className="row" style={{ justifyContent: 'flex-end', gap: 8 }}>
          <button type="button" className="btn btn-ghost" onClick={onCancel}>Cancel</button>
          <button type="button" className={`btn ${danger ? 'btn-danger' : 'btn-primary'}`} onClick={onConfirm}>{confirmLabel}</button>
        </div>
      )}
    >
      <p style={{ margin: 0 }}>{message}</p>
    </Modal>
  )
}

const ToastContext = createContext(() => {})

export function ToastProvider({ children }) {
  const [items, setItems] = useState([])
  const push = useCallback((message, kind = 'info') => {
    const id = Math.random().toString(36).slice(2)
    setItems(xs => [...xs, { id, message, kind }].slice(-3))
    setTimeout(() => setItems(xs => xs.filter(x => x.id !== id)), kind === 'error' ? 6000 : 3500)
  }, [])
  return (
    <ToastContext.Provider value={push}>
      {children}
      <div className="toasts" aria-live="polite">
        {items.map(t => <div key={t.id} className={`toast ${t.kind}`}>{t.message}</div>)}
      </div>
    </ToastContext.Provider>
  )
}

export const useToast = () => useContext(ToastContext)

export function useLoad(fn, deps = []) {
  const [state, setState] = useState({ data: null, error: null, loading: true })
  const request = useRef(0)
  const load = useCallback(async () => {
    const current = ++request.current
    setState(s => ({ ...s, loading: true }))
    try {
      const data = await fn()
      if (current === request.current) setState({ data, error: null, loading: false })
    } catch (error) {
      if (current === request.current) setState(s => ({ ...s, error, loading: false }))
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps)
  useEffect(() => { load(); return () => { request.current += 1 } }, [load])
  return { ...state, reload: load }
}

export function StatusBadge({ status }) {
  const map = {
    planned: ['badge-muted', 'Planned'], in_progress: ['badge-accent', 'On route'], completed: ['badge-success', 'Completed'],
    cancelled: ['badge-muted', 'Cancelled'], pending: ['badge-muted', 'Pending'], arrived: ['badge-accent', 'At shop'],
    done: ['badge-success', 'Done'], skipped: ['badge-warning', 'Skipped'], present: ['badge-success', 'On time'],
    late: ['badge-warning', 'Late'], new: ['badge-accent', 'New'], acknowledged: ['badge-muted', 'Seen'],
    fulfilled: ['badge-success', 'Fulfilled'], closed: ['badge-muted', 'Closed'],
  }
  const [cls, label] = map[status] || ['badge-muted', status]
  return <span className={`badge ${cls}`}>{label}</span>
}
