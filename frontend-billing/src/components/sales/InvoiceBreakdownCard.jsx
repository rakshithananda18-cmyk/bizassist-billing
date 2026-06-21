// src/components/sales/InvoiceBreakdownCard.jsx
// ============================================
// The "Invoice Breakdown" card inside the POS payment popup, lifted out of
// Sales.jsx unchanged. Pure presentation: receives the already-computed amounts
// and renders subtotal / CGST / SGST / IGST / total-tax / grand-total. CGST/SGST
// rows show only for intra-state, IGST only for inter-state (driven by the
// amounts being > 0, exactly as before). No business logic here.
import React from 'react'
import { fmt } from '../../utils/format'

export default function InvoiceBreakdownCard({
  subtotal,
  discount = 0,
  cgstAmt,
  sgstAmt,
  igstAmt,
  gstAmt,
  grandTotal,
}) {
  return (
    <div style={{ background: '#fafaf9', padding: '16px', borderRadius: 'var(--radius-md)', border: '1px solid var(--border)', display: 'flex', flexDirection: 'column', gap: '8px' }}>
      <div style={{ fontSize: '0.85rem', fontWeight: 'bold', color: '#78716c', textTransform: 'uppercase', marginBottom: '4px' }}>Invoice Breakdown</div>
      <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.85rem', color: '#1c1917' }}>
        <span>Subtotal (Without Tax):</span>
        <span>{fmt(subtotal)}</span>
      </div>
      {discount > 0 && (
        <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.85rem', color: '#16a34a', fontWeight: 600 }}>
          <span>Bill Discount:</span>
          <span>− {fmt(discount)}</span>
        </div>
      )}
      {cgstAmt > 0 && (
        <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.85rem', color: '#444440' }}>
          <span>CGST:</span>
          <span>{fmt(cgstAmt)}</span>
        </div>
      )}
      {sgstAmt > 0 && (
        <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.85rem', color: '#444440' }}>
          <span>SGST:</span>
          <span>{fmt(sgstAmt)}</span>
        </div>
      )}
      {igstAmt > 0 && (
        <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.85rem', color: '#444440' }}>
          <span>IGST:</span>
          <span>{fmt(igstAmt)}</span>
        </div>
      )}
      <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.85rem', color: '#444440' }}>
        <span>Total Tax:</span>
        <span>{fmt(gstAmt)}</span>
      </div>
      <div style={{ borderTop: '1px dashed var(--border)', margin: '4px 0' }} />
      <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '1.2rem', fontWeight: 900, color: 'var(--accent)' }}>
        <span>Grand Total:</span>
        <span>{fmt(grandTotal)}</span>
      </div>
    </div>
  )
}
