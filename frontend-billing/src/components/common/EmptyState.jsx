// components/common/EmptyState.jsx — the ONE empty-state (plan Phase 4.2).
// ========================================================================
// Replaces per-page ad-hoc "No data" divs with a single calm pattern:
// small muted icon → one-line title → one muted hint → optional ghost action.
// Works inside cards, table wrappers, and full pages.
import React from 'react'

export default function EmptyState({
  icon = null,             // a rendered icon element, e.g. <TruckIcon size={20} />
  title = 'Nothing here yet',
  hint = null,
  actionLabel = null,
  onAction = null,
  compact = false,         // tighter paddings inside table cells / small cards
  testId = 'empty-state',
}) {
  return (
    <div
      className="empty-state"
      data-testid={testId}
      style={{
        display: 'flex', flexDirection: 'column', alignItems: 'center',
        justifyContent: 'center', textAlign: 'center', gap: 'var(--sp-2, 8px)',
        padding: compact ? 'var(--sp-5, 20px)' : 'var(--sp-8, 40px) var(--sp-5, 20px)',
      }}
    >
      {icon ? (
        <div className="empty-icon" aria-hidden="true" style={{
          width: 40, height: 40, borderRadius: '50%',
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          background: 'var(--bg-3, #f4f4f1)', color: 'var(--text-muted, #555)',
        }}>
          {icon}
        </div>
      ) : null}
      <h3 style={{ margin: 0, fontSize: 'var(--fs-base, 14px)', fontWeight: 700, color: 'var(--text-primary, #000)' }}>
        {title}
      </h3>
      {hint ? (
        <p style={{ margin: 0, fontSize: 'var(--fs-sm, 13px)', color: 'var(--text-muted, #555)', maxWidth: 340 }}>
          {hint}
        </p>
      ) : null}
      {actionLabel && onAction ? (
        <button type="button" className="btn btn-ghost" onClick={onAction}
                style={{ marginTop: 'var(--sp-1, 4px)', color: 'var(--accent, #c15f3c)' }}>
          {actionLabel}
        </button>
      ) : null}
    </div>
  )
}
