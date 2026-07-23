// ============================================================================
// ConfirmChangesModal — the app-wide "double-check before you save / discard"
// dialog. Driven imperatively through ConfirmContext (useConfirm); you almost
// never render this directly.
//
// Modes:
//   'create'  → "You're about to add …" + summary rows (label: value)
//   'update'  → "Review N change(s)…"   + diff rows (label: from → to)
//   'delete'  → destructive confirm (danger styling)
//   'discard' → "Discard your changes?" + optional list of changed fields
//
// Keyboard: Enter confirms · Escape cancels. Styling mirrors
// UnsavedChangesModal so the whole app feels consistent.
// ============================================================================
import React, { useEffect, useRef } from 'react'
import { createPortal } from 'react-dom'

const ICONS = {
  alert: { color: '#3b82f6', bg: 'rgba(59,130,246,0.12)', border: 'rgba(59,130,246,0.3)',
    path: <><circle cx="12" cy="12" r="10" /><line x1="12" y1="8" x2="12" y2="12" /><line x1="12" y1="16" x2="12.01" y2="16" /></> },
  create: { color: '#22c55e', bg: 'rgba(34,197,94,0.12)', border: 'rgba(34,197,94,0.3)',
    path: <><path d="M12 5v14" /><path d="M5 12h14" /></> },
  update: { color: '#3b82f6', bg: 'rgba(59,130,246,0.12)', border: 'rgba(59,130,246,0.3)',
    path: <><path d="M12 20h9" /><path d="M16.5 3.5a2.12 2.12 0 0 1 3 3L7 19l-4 1 1-4Z" /></> },
  delete: { color: '#ef4444', bg: 'rgba(239,68,68,0.12)', border: 'rgba(239,68,68,0.3)',
    path: <><path d="M3 6h18" /><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6" /><path d="M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" /></> },
  discard: { color: '#eab308', bg: 'rgba(234,179,8,0.12)', border: 'rgba(234,179,8,0.3)',
    path: <><path d="M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z" /><line x1="12" y1="9" x2="12" y2="13" /><line x1="12" y1="17" x2="12.01" y2="17" /></> },
}

const DEFAULT_TITLES = {
  alert: 'Notice',
  create: 'Confirm new record',
  update: 'Confirm changes',
  delete: 'Confirm deletion',
  discard: 'Discard changes?',
}

export default function ConfirmChangesModal({
  open,
  mode = 'update',
  title,
  entity,                 // e.g. product / customer name
  changes = [],           // update: [{ label, from, to }]
  summary = [],           // create: [{ label, value }]
  message,                // overrides the auto description
  confirmText,
  cancelText,
  tertiaryText,           // optional middle button (e.g. "Add to credit")
  onConfirm,
  onCancel,
  onTertiary,
}) {
  const confirmRef = useRef(null)

  useEffect(() => {
    if (!open) return
    const onKey = (e) => {
      if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); onCancel?.() }
      else if (e.key === 'Enter') { e.preventDefault(); e.stopPropagation(); onConfirm?.() }
    }
    window.addEventListener('keydown', onKey, true)
    const t = setTimeout(() => confirmRef.current?.focus(), 40)
    return () => { window.removeEventListener('keydown', onKey, true); clearTimeout(t) }
  }, [open, onConfirm, onCancel])

  if (!open) return null

  const ic = ICONS[mode] || ICONS.update
  const danger = mode === 'delete' || mode === 'discard'
  const isAlert = mode === 'alert'
  const heading = title || DEFAULT_TITLES[mode] || 'Please confirm'
  const primaryLabel = confirmText || (
    mode === 'alert' ? 'OK' :
    mode === 'create' ? 'Add' :
    mode === 'update' ? 'Save changes' :
    mode === 'delete' ? 'Delete' :
    'Discard'
  )
  const secondaryLabel = cancelText || (mode === 'discard' ? 'Keep editing' : 'Cancel')

  const autoMessage = message || (
    mode === 'create' ? <>You're about to add{entity ? <> <strong>{entity}</strong></> : ' this record'}. Please review the details:</> :
    mode === 'update' ? (changes.length
        ? <>Review {changes.length} change{changes.length > 1 ? 's' : ''}{entity ? <> to <strong>{entity}</strong></> : ''} before saving:</>
        : <>No fields changed{entity ? <> on <strong>{entity}</strong></> : ''}. Save anyway?</>) :
    mode === 'delete' ? <>This will permanently delete{entity ? <> <strong>{entity}</strong></> : ' this record'}. This can't be undone.</> :
    <>You have unsaved changes{entity ? <> to <strong>{entity}</strong></> : ''}. Discard them?</>
  )

  return createPortal(
    <>
      <div
        onClick={onCancel}
        style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.45)',
          backdropFilter: 'blur(3px)', zIndex: 999992, animation: 'ccm-fade-in 0.15s ease' }}
      />
      <div
        role="alertdialog"
        aria-modal="true"
        aria-labelledby="ccm-title"
        style={{
          position: 'fixed', top: '50%', left: '50%', transform: 'translate(-50%,-50%)',
          zIndex: 999993, width: 'min(440px, calc(100vw - 32px))',
          background: 'var(--bg-2)', border: '1px solid var(--border)', borderRadius: 14,
          boxShadow: '0 24px 60px rgba(0,0,0,0.35)', padding: '26px 26px 22px',
          maxHeight: 'calc(100vh - 48px)', display: 'flex', flexDirection: 'column',
          animation: 'ccm-slide-in 0.18s cubic-bezier(.34,1.56,.64,1)',
        }}
        onClick={(e) => e.stopPropagation()}
      >
        <div style={{ width: 44, height: 44, borderRadius: 12, background: ic.bg,
          border: `1px solid ${ic.border}`, display: 'flex', alignItems: 'center',
          justifyContent: 'center', marginBottom: 14, flexShrink: 0 }}>
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke={ic.color}
            strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">{ic.path}</svg>
        </div>

        <h3 id="ccm-title" style={{ margin: '0 0 8px', fontSize: '1rem', fontWeight: 700, color: 'var(--text-primary)' }}>
          {heading}
        </h3>
        <p style={{ margin: '0 0 16px', fontSize: '0.875rem', color: 'var(--text-secondary)', lineHeight: 1.5 }}>
          {autoMessage}
        </p>

        {/* Change / summary list */}
        {(changes.length > 0 || summary.length > 0) && (
          <div style={{ overflowY: 'auto', border: '1px solid var(--border)', borderRadius: 10,
            background: 'var(--bg-3)', marginBottom: 20, maxHeight: 260 }}>
            {mode === 'update'
              ? changes.map((c, i) => (
                <div key={c.key || i} style={{ display: 'flex', alignItems: 'baseline', gap: 8,
                  padding: '9px 12px', borderBottom: i < changes.length - 1 ? '1px solid var(--border)' : 'none' }}>
                  <span style={{ flex: '0 0 34%', fontSize: '0.78rem', fontWeight: 600, color: 'var(--text-muted)' }}>{c.label}</span>
                  <span style={{ flex: 1, fontSize: '0.82rem', display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap' }}>
                    <span style={{ color: 'var(--text-muted)', textDecoration: 'line-through', opacity: 0.7 }}>{c.from}</span>
                    <span style={{ color: 'var(--text-muted)' }}>→</span>
                    <strong style={{ color: 'var(--text-primary)' }}>{c.to}</strong>
                  </span>
                </div>
              ))
              : summary.map((s, i) => (
                <div key={s.key || i} style={{ display: 'flex', alignItems: 'baseline', gap: 8,
                  padding: '9px 12px', borderBottom: i < summary.length - 1 ? '1px solid var(--border)' : 'none' }}>
                  <span style={{ flex: '0 0 38%', fontSize: '0.78rem', fontWeight: 600, color: 'var(--text-muted)' }}>{s.label}</span>
                  <strong style={{ flex: 1, fontSize: '0.82rem', color: 'var(--text-primary)', wordBreak: 'break-word' }}>{s.value}</strong>
                </div>
              ))}
          </div>
        )}

        <div style={{ display: 'flex', gap: 10, justifyContent: 'flex-end', flexWrap: 'wrap' }}>
          {!isAlert && (
            <button type="button" className="btn btn-secondary" onClick={onCancel} style={{ minWidth: 90 }}>
              {secondaryLabel}
            </button>
          )}
          {tertiaryText && (
            <button type="button" className="btn btn-secondary" onClick={onTertiary}
              style={{ minWidth: 110, borderColor: '#eab308', color: '#eab308' }}>
              {tertiaryText}
            </button>
          )}
          <button
            ref={confirmRef}
            type="button"
            className="btn btn-primary"
            onClick={onConfirm}
            style={{ minWidth: 120, ...(danger ? { background: '#ef4444', borderColor: '#ef4444' } : {}) }}
          >
            {primaryLabel}
          </button>
        </div>
      </div>

      <style>{`
        @keyframes ccm-fade-in { from { opacity: 0 } to { opacity: 1 } }
        @keyframes ccm-slide-in {
          from { opacity: 0; transform: translate(-50%,-54%) scale(0.96); }
          to   { opacity: 1; transform: translate(-50%,-50%) scale(1); }
        }
      `}</style>
    </>,
    document.body,
  )
}
