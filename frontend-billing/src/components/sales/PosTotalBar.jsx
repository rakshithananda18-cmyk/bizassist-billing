// src/components/sales/PosTotalBar.jsx
// ====================================
// The always-visible bottom totals bar for the POS counter.
// Includes the subtotal, tax, inline keyboard shortcuts (always visible), and grand total with Pay button.
import React from 'react'
import { fmt } from '../../utils/format'

export default function PosTotalBar({
  subtotal,
  gstAmt,
  grandTotal,
  onPay,
  funcKeys = {},
}) {
  const searchKey = funcKeys?.barcodeFocus || 'F9'
  const customerKey = funcKeys?.customerFocus || 'F11'
  const saveKey = funcKeys?.saveInvoice || 'Ctrl+S'
  const printKey = funcKeys?.printInvoice || 'Ctrl+P'
  const newBillKey = funcKeys?.newBill || 'Ctrl+T'
  const closeTabKey = funcKeys?.closeTab || 'Ctrl+W'

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
      {/* Left side: Subtotal & Tax */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '20px', flexShrink: 0 }}>
        <div style={{ display: 'flex', flexDirection: 'column' }}>
          <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)', fontWeight: 600, textTransform: 'uppercase' }}>Subtotal</span>
          <span style={{ fontSize: '1.05rem', fontWeight: 700, color: 'var(--text-primary)' }}>{fmt(subtotal)}</span>
        </div>
        <div style={{ display: 'flex', flexDirection: 'column' }}>
          <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)', fontWeight: 600, textTransform: 'uppercase' }}>Tax</span>
          <span style={{ fontSize: '1.05rem', fontWeight: 700, color: 'var(--text-primary)' }}>{fmt(gstAmt)}</span>
        </div>
      </div>

      {/* Middle: Fixed Keyboard Shortcuts Inline (Not pill-shaped, just clean inline layout) */}
      <div style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        gap: '16px',
        fontSize: '0.74rem',
        color: 'var(--text-muted)',
        borderLeft: '1px solid var(--border)',
        borderRight: '1px solid var(--border)',
        padding: '0 24px',
        margin: '0 16px',
        flex: 1,
        overflow: 'hidden',
        whiteSpace: 'nowrap'
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '5px' }}>
          <kbd style={{ background: 'var(--bg-3)', border: '1px solid var(--border)', borderBottom: '2px solid var(--border)', borderRadius: '4px', padding: '1px 5px', fontSize: '0.66rem', color: 'var(--text-primary)', fontWeight: 'bold' }}>{searchKey}</kbd>
          <span style={{ fontWeight: 500 }}>Search</span>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: '5px' }}>
          <kbd style={{ background: 'var(--bg-3)', border: '1px solid var(--border)', borderBottom: '2px solid var(--border)', borderRadius: '4px', padding: '1px 5px', fontSize: '0.66rem', color: 'var(--text-primary)', fontWeight: 'bold' }}>{customerKey}</kbd>
          <span style={{ fontWeight: 500 }}>Customer</span>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: '5px' }}>
          <kbd style={{ background: 'var(--bg-3)', border: '1px solid var(--border)', borderBottom: '2px solid var(--border)', borderRadius: '4px', padding: '1px 5px', fontSize: '0.66rem', color: 'var(--text-primary)', fontWeight: 'bold' }}>{saveKey}</kbd>
          <span style={{ fontWeight: 500 }}>Save</span>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: '5px' }}>
          <kbd style={{ background: 'var(--bg-3)', border: '1px solid var(--border)', borderBottom: '2px solid var(--border)', borderRadius: '4px', padding: '1px 5px', fontSize: '0.66rem', color: 'var(--text-primary)', fontWeight: 'bold' }}>{printKey}</kbd>
          <span style={{ fontWeight: 500 }}>Print</span>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: '5px' }}>
          <kbd style={{ background: 'var(--bg-3)', border: '1px solid var(--border)', borderBottom: '2px solid var(--border)', borderRadius: '4px', padding: '1px 5px', fontSize: '0.66rem', color: 'var(--text-primary)', fontWeight: 'bold' }}>{newBillKey}</kbd>
          <span style={{ fontWeight: 500 }}>New Tab</span>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: '5px' }}>
          <kbd style={{ background: 'var(--bg-3)', border: '1px solid var(--border)', borderBottom: '2px solid var(--border)', borderRadius: '4px', padding: '1px 5px', fontSize: '0.66rem', color: 'var(--text-primary)', fontWeight: 'bold' }}>{closeTabKey}</kbd>
          <span style={{ fontWeight: 500 }}>Close Tab</span>
        </div>
      </div>

      {/* Right side: Grand Total & Pay button */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '24px', flexShrink: 0 }}>
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
