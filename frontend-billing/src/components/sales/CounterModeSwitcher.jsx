// components/sales/CounterModeSwitcher.jsx — multi-type counter mode (Phase 2).
// =============================================================================
// Visible ONLY when the business registered more than one business type
// (profile.business_types.length > 1). Switching writes the sticky per-device
// mode (localStorage 'pos.counter_mode') via setCounterMode(), which live-
// updates every useBillingProfile consumer — CheckoutModal gating, invoice
// defaults — without touching Sales.jsx state. Self-contained: no props.
import React from 'react'
import { useBillingProfile, setCounterMode } from '../../hooks/useBillingProfile'

/** "b2b_supplier" → "B2B Supplier", "supermarket" → "Supermarket" */
export function humanizeModeKey(key) {
  return String(key || '')
    .split('_')
    .map(w => (w === 'b2b' ? 'B2B' : w.charAt(0).toUpperCase() + w.slice(1)))
    .join(' ')
}

export default function CounterModeSwitcher() {
  const { profile } = useBillingProfile()
  const types = profile?.business_types || []
  if (types.length < 2) return null

  const active = profile?.mode_key || types[0]
  const primary = types[0]

  return (
    <div
      data-testid="counter-mode-switcher"
      role="tablist"
      aria-label="Billing mode"
      style={{ display: 'inline-flex', gap: 3, marginRight: 6, alignItems: 'center' }}
    >
      {types.map(key => {
        const isActive = key === active
        return (
          <button
            key={key}
            type="button"
            role="tab"
            aria-selected={isActive}
            title={`Bill as ${humanizeModeKey(key)}${key === primary ? ' (primary)' : ''}`}
            onClick={() => { if (!isActive) setCounterMode(key === primary ? null : key) }}
            style={{
              fontSize: '0.72rem',
              fontWeight: 700,
              padding: '3px 9px',
              borderRadius: 12,
              cursor: isActive ? 'default' : 'pointer',
              border: isActive ? '1px solid var(--accent, #c15f3c)' : '1px solid rgba(255,255,255,0.15)',
              background: isActive ? 'var(--accent-dim, rgba(193,95,60,0.10))' : 'transparent',
              color: isActive ? 'var(--accent, #c15f3c)' : 'var(--text-muted, #888)',
            }}
          >
            {humanizeModeKey(key)}
          </button>
        )
      })}
    </div>
  )
}
