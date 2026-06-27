// components/sales/CounterMenu.jsx
// ================================
// Read-only counter badge in the POS top bar (multi-terminal POS, plan §9.3a).
// A "counter" is now STAFF-ASSIGNED (login-bound): the owner sets each account's
// counter prefix in Staff management (owner defaults to "OW"); it arrives on the
// auth user and drives this login's invoice-number series (C1-0001, C2-0001…).
// Staff CANNOT change it at the till — it's owner-controlled, server-stored, and
// can't be manipulated here. So this is purely a display: "Counter: C1".
import React from 'react'

export default function CounterMenu({ prefix, canManage = false, onManage }) {
  const label = (prefix || '').trim() || '—'
  const clickable = canManage && typeof onManage === 'function'
  return (
    <span
      className="pos-counter-badge"
      onClick={clickable ? onManage : undefined}
      title={clickable
        ? 'Manage counters & cashier assignments in Staff management'
        : 'Your billing counter — assigned by the owner in Staff management'}
      style={{
        display: 'inline-flex', alignItems: 'center', gap: 5,
        fontSize: '0.78rem', fontWeight: 600, color: 'var(--text-secondary)',
        padding: '2px 8px', border: '1px solid var(--border)', borderRadius: 6,
        background: 'var(--bg-3)', whiteSpace: 'nowrap',
        cursor: clickable ? 'pointer' : 'default',
      }}
    >
      <span style={{ color: 'var(--text-muted)' }}>Counter:</span> {label}
      {clickable && <span style={{ fontSize: '0.6rem', opacity: 0.7 }}>⚙</span>}
    </span>
  )
}
