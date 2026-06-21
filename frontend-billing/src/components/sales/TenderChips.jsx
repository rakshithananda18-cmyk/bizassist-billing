// src/components/sales/TenderChips.jsx
// ====================================
// The smart cash-tender chips in the POS payment popup — the "tap once instead
// of typing" moment. Lifted out of Sales.jsx unchanged. Presentational: it owns
// the chip layout and the Exact/round labels, but delegates the actual state
// change to the parent via onSelect(value). The chip values come from the pure,
// unit-tested suggestedTenders() so the chips can't drift from the math.
import React from 'react'
import { fmt } from '../../utils/format'
import { suggestedTenders } from '../../utils/invoiceMath'

export default function TenderChips({ grandTotal, onSelect }) {
  return (
    <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
      {suggestedTenders(grandTotal).map(val => (
        <button
          key={val}
          type="button"
          style={{
            background: '#fafaf9',
            border: '1px solid var(--border)',
            borderRadius: '20px',
            padding: '6px 14px',
            color: '#1c1917',
            fontSize: '0.8rem',
            fontWeight: '600',
            cursor: 'pointer',
            transition: 'all 0.15s ease',
          }}
          onClick={() => onSelect(val)}
        >
          {val === Math.ceil(grandTotal - 1e-9) ? `Exact ${fmt(val)}` : fmt(val)}
        </button>
      ))}
    </div>
  )
}
