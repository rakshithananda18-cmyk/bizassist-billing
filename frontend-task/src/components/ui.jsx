// components/ui.jsx — small shared pieces (page header, stat, modal, toasts).
import React, { createContext, useCallback, useContext, useEffect, useState } from 'react'
import { createPortal } from 'react-dom'
import { CloseIcon } from './Icons'
import { SkylineLoader } from './Logo'

export function PageHeader({ title, subtitle, children }) {
  return (
    <div className="page-header">
      <div>
        <div className="page-title">{title}</div>
        {subtitle && <div className="page-subtitle">{subtitle}</div>}
      </div>
      {children && <div className="row wrap">{children}</div>}
    </div>
  )
}

export function Stat({ label, value, sub, progress }) {
  return (
    <div className="stat-card">
      <div className="stat-label">{label}</div>
      <div className="stat-value">{value}</div>
      {progress != null && (
        <div className={`progress ${progress >= 100 ? 'ok' : ''}`}><span style={{ width: `${Math.min(100, progress)}%` }} /></div>
      )}
      {sub && <div className="stat-sub">{sub}</div>}
    </div>
  )
}

export function Loader({ label = 'Loading…' }) {
  return (
    <div className="empty" style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 10 }}>
      <SkylineLoader size={56} />
      <span>{label}</span>
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
  useEffect(() => {
    const onKey = (e) => { if (e.key === 'Escape') onClose?.() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])
  return createPortal(
    <div className="modal-overlay" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose?.() }}>
      <div className="modal" style={wide ? { maxWidth: 820 } : undefined} role="dialog" aria-modal="true">
        <div className="modal-header">
          <div className="modal-title">{title}</div>
          <button className="btn btn-ghost btn-sm" onClick={onClose} aria-label="Close"><CloseIcon size={18} /></button>
        </div>
        <div className="modal-body">{children}</div>
        {footer && <div className="modal-footer">{footer}</div>}
      </div>
    </div>,
    document.body,
  )
}

const ToastContext = createContext(() => {})

export function ToastProvider({ children }) {
  const [items, setItems] = useState([])
  const push = useCallback((message, kind = 'info') => {
    const id = Math.random().toString(36).slice(2)
    setItems(xs => [...xs, { id, message, kind }].slice(-3))  // newest three; older ones are stale
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

// Data loader hook: { data, error, loading, reload }.
export function useLoad(fn, deps = []) {
  const [state, setState] = useState({ data: null, error: null, loading: true })
  const load = useCallback(async () => {
    setState(s => ({ ...s, loading: true }))
    try {
      const data = await fn()
      setState({ data, error: null, loading: false })
    } catch (error) {
      setState(s => ({ ...s, error, loading: false }))
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps)
  useEffect(() => { load() }, [load])
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
