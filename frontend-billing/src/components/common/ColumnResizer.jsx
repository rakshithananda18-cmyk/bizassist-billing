// ============================================================================
// components/common/ColumnResizer.jsx
// ----------------------------------------------------------------------------
// The drag grip that sits on the right edge of a resizable <th>. Rendered from
// useResizableColumns' resizerProps(), which supplies every handler:
//
//   <th {...cols.headerProps('name')}>Item Name<ColumnResizer {...cols.resizerProps('name')} /></th>
//
// Interaction contract
//   · pointer-down + drag → resize (handled by the hook)
//   · double-click        → auto-fit the column to its widest cell
//   · ← / →               → nudge by 8px (16px with Shift) for keyboard users
//   · click               → swallowed, so a resizable header can still sort
// ============================================================================
import React from 'react'

export default function ColumnResizer({
  colKey,
  active = false,
  disabled = false,
  onResizeStart,
  onAutoFit,
  onNudge,
}) {
  if (disabled) return null

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onAutoFit?.(); return }
    if (e.key !== 'ArrowLeft' && e.key !== 'ArrowRight') return
    e.preventDefault()
    const step = (e.shiftKey ? 16 : 8) * (e.key === 'ArrowLeft' ? -1 : 1)
    onNudge?.(step)
  }

  return (
    <span
      role="separator"
      aria-orientation="vertical"
      aria-label={`Resize ${colKey} column`}
      tabIndex={0}
      className={`col-resizer${active ? ' is-active' : ''}`}
      onPointerDown={onResizeStart}
      onDoubleClick={(e) => { e.preventDefault(); e.stopPropagation(); onAutoFit?.() }}
      onClick={(e) => { e.preventDefault(); e.stopPropagation() }}
      onKeyDown={handleKeyDown}
      title="Drag to resize · double-click to fit content"
    />
  )
}
