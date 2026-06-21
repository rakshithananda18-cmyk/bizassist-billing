// src/components/sales/PosTotalBar.jsx
// ====================================
// The always-visible bottom totals bar for the POS counter (piece (b) of the
// counter redesign), lifted out of Sales.jsx unchanged. Pure presentation: it
// receives already-computed amounts and two callbacks. No business logic here.
// Markup, classNames and inline styles are identical to the original so the
// index.css (.pos-totals-bar) and visuals are unaffected.
import React from 'react'
import { fmt } from '../../utils/format'

export default function PosTotalBar({
  subtotal,
  gstAmt,
  grandTotal,
  onShowShortcuts,
  onPay,
}) {
  return (
    <div className="pos-totals-bar" style={{
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'space-between',
      background: 'var(--glass-bg)',
      backdropFilter: 'blur(20px) saturate(180%)',
      WebkitBackdropFilter: 'blur(20px) saturate(180%)',
      border: '1px solid var(--glass-border)',
      borderRadius: 'var(--radius-lg)',
      padding: '12px 20px',
      marginTop: '10px',
      boxShadow: 'var(--shadow-md)',
      position: 'relative',
      zIndex: 101
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: '20px' }}>
        <div style={{ display: 'flex', flexDirection: 'column' }}>
          <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)', fontWeight: 600, textTransform: 'uppercase' }}>Subtotal</span>
          <span style={{ fontSize: '1rem', fontWeight: 700, color: 'var(--text-primary)' }}>{fmt(subtotal)}</span>
        </div>
        <div style={{ display: 'flex', flexDirection: 'column' }}>
          <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)', fontWeight: 600, textTransform: 'uppercase' }}>Tax</span>
          <span style={{ fontSize: '1rem', fontWeight: 700, color: 'var(--text-primary)' }}>{fmt(gstAmt)}</span>
        </div>

        {/* Shortcuts Help button */}
        <button
          type="button"
          className="btn btn-ghost btn-icon btn-sm"
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            width: '28px',
            height: '28px',
            borderRadius: '50%',
            background: 'var(--bg-3)',
            border: '1px solid var(--border)',
            marginLeft: '10px',
            fontSize: '0.9rem',
            fontWeight: 'bold',
            color: 'var(--text-secondary)'
          }}
          onClick={onShowShortcuts}
          title="Keyboard Shortcuts [?]"
        >
          ?
        </button>
      </div>

      <div style={{ display: 'flex', alignItems: 'center', gap: '24px' }}>
        {/* Inline hints */}
        <div style={{ display: 'flex', gap: '12px', fontSize: '0.75rem', color: 'var(--text-muted)' }}>
          <span>F9: Search</span>
          <span>F11: Customer</span>
        </div>

        <div style={{ display: 'flex', alignItems: 'baseline', gap: '8px' }}>
          <span style={{ fontSize: '0.9rem', color: 'var(--text-secondary)', fontWeight: 600 }}>Grand Total</span>
          <span style={{ fontSize: '1.75rem', fontWeight: 900, color: 'var(--accent)', lineHeight: 1 }}>{fmt(grandTotal)}</span>
        </div>

        <button
          type="button"
          className="btn btn-primary"
          style={{
            background: 'var(--accent)',
            borderColor: 'var(--accent)',
            padding: '10px 24px',
            borderRadius: 'var(--radius-md)',
            fontWeight: 'bold',
            fontSize: '0.95rem',
            display: 'flex',
            alignItems: 'center',
            gap: '6px',
            boxShadow: 'var(--shadow-sm)'
          }}
          onClick={onPay}
        >
          Pay ▸ <span style={{ fontSize: '0.75rem', opacity: 0.8, fontWeight: 'normal' }}>(Enter)</span>
        </button>
      </div>
    </div>
  )
}
