// ============================================================================
// SidebarContextMenu — right-click context menu for sidebar nav items,
// extracted verbatim from layouts/AppLayout.jsx (repo restructure).
// Presentational portal: quick actions, reorder state and persistence stay
// at the call site and arrive as props/callbacks.
//   menu:          { x, y, label, to, flatIndex }
//   quickActions:  [{ icon, label, action }]  (already resolved for menu.to)
//   flatCount:     total nav items (for Move Down disabling)
//   onMove(dir):   move item and keep the menu open on the new index
//   hasCustomOrder / onResetOrder: the "Reset to Default Order" row
// ============================================================================
import React from 'react'
import { createPortal } from 'react-dom'
import { ChevronDownIcon, SyncIcon } from '../Icons'

export default function SidebarContextMenu({ menu, quickActions, flatCount, onMove, hasCustomOrder, onResetOrder, onClose }) {
  return createPortal(
    <div
      onMouseDown={e => e.stopPropagation()}
      style={{
        position: 'fixed',
        top: Math.min(menu.y, window.innerHeight - 260),
        left: menu.x + 4,
        zIndex: 99999,
        background: 'var(--bg-2)',
        border: '1px solid var(--border)',
        borderRadius: 10,
        boxShadow: '0 8px 32px rgba(0,0,0,0.35)',
        minWidth: 210,
        overflow: 'hidden',
        padding: '6px 0',
      }}
    >
      {/* Header */}
      <div style={{
        padding: '6px 14px 8px',
        fontSize: '0.7rem', fontWeight: 700,
        color: 'var(--text-muted)', letterSpacing: '0.08em',
        textTransform: 'uppercase', borderBottom: '1px solid var(--border)',
        marginBottom: 4,
      }}>
        {menu.label}
      </div>

      {/* Page quick actions */}
      {quickActions.map((qa, i) => (
        <button
          key={i}
          onClick={() => { qa.action(); onClose() }}
          style={{
            display: 'flex', alignItems: 'center', gap: 10,
            width: '100%', padding: '7px 14px',
            background: 'transparent', border: 'none',
            color: 'var(--text-primary)', fontSize: '0.82rem',
            fontWeight: 500, cursor: 'pointer', textAlign: 'left',
            transition: `background var(--dur-fast) var(--ease)`,
          }}
          onMouseEnter={e => e.currentTarget.style.background = 'var(--bg-3)'}
          onMouseLeave={e => e.currentTarget.style.background = 'transparent'}
        >
          <span style={{
            display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
            width: 20, height: 20, flexShrink: 0,
            color: 'var(--accent)',
          }}>{qa.icon}</span>
          {qa.label}
        </button>
      ))}

      {/* Divider */}
      <div style={{ height: 1, background: 'var(--border)', margin: '6px 0' }} />

      {/* Reorder */}
      <div style={{
        padding: '4px 14px 2px',
        fontSize: '0.68rem', fontWeight: 700,
        color: 'var(--text-muted)', letterSpacing: '0.08em',
        textTransform: 'uppercase',
      }}>Reorder</div>
      {[
        { label: 'Move Up',   rotateIcon: 'rotate(180deg)', dir: -1, disabled: menu.flatIndex === 0 },
        { label: 'Move Down', rotateIcon: 'rotate(0deg)',   dir:  1, disabled: menu.flatIndex === flatCount - 1 },
      ].map(({ label, rotateIcon, dir, disabled }) => (
        <button
          key={label}
          disabled={disabled}
          onClick={() => onMove(dir)}
          style={{
            display: 'flex', alignItems: 'center', gap: 10,
            width: '100%', padding: '7px 14px',
            background: 'transparent', border: 'none',
            color: disabled ? 'var(--text-muted)' : 'var(--text-primary)',
            fontSize: '0.82rem', fontWeight: 500,
            cursor: disabled ? 'not-allowed' : 'pointer', textAlign: 'left',
            opacity: disabled ? 0.4 : 1,
            transition: `background var(--dur-fast) var(--ease)`,
          }}
          onMouseEnter={e => { if (!disabled) e.currentTarget.style.background = 'var(--bg-3)' }}
          onMouseLeave={e => e.currentTarget.style.background = 'transparent'}
        >
          <span style={{
            display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
            width: 20, height: 20, flexShrink: 0,
            color: disabled ? 'var(--text-muted)' : 'var(--text-secondary)',
            transform: rotateIcon,
          }}><ChevronDownIcon size={13} strokeWidth={2.5} /></span>
          {label}
        </button>
      ))}

      {/* Reset order (only if custom order is active) */}
      {hasCustomOrder && (
        <>
          <div style={{ height: 1, background: 'var(--border)', margin: '6px 0' }} />
          <button
            onClick={onResetOrder}
            style={{
              display: 'flex', alignItems: 'center', gap: 10,
              width: '100%', padding: '7px 14px',
              background: 'transparent', border: 'none',
              color: 'var(--danger, #ef4444)', fontSize: '0.8rem',
              fontWeight: 500, cursor: 'pointer', textAlign: 'left',
              transition: `background var(--dur-fast) var(--ease)`,
            }}
            onMouseEnter={e => e.currentTarget.style.background = 'rgba(239,68,68,.08)'}
            onMouseLeave={e => e.currentTarget.style.background = 'transparent'}
          >
            <span style={{
              display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
              width: 20, height: 20, flexShrink: 0,
              color: 'var(--danger, #ef4444)',
            }}><SyncIcon size={13} /></span>
            Reset to Default Order
          </button>
        </>
      )}
    </div>,
    document.body
  )
}
