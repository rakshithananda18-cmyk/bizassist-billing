// Render tests for <InvoiceBreakdownCard> — the breakdown card inside the POS
// payment popup. Presentational: CGST/SGST show for intra-state, IGST for
// inter-state (driven by which amounts are > 0).
import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import InvoiceBreakdownCard from '../components/sales/InvoiceBreakdownCard'

const base = {
  subtotal: 200,
  cgstAmt: 18,
  sgstAmt: 18,
  igstAmt: 0,
  gstAmt: 36,
  grandTotal: 236,
}

describe('InvoiceBreakdownCard', () => {
  it('shows subtotal, CGST/SGST split and grand total (intra-state)', () => {
    render(<InvoiceBreakdownCard {...base} />)
    expect(screen.getByText('Invoice Breakdown')).toBeInTheDocument()
    expect(screen.getByText('CGST:')).toBeInTheDocument()
    expect(screen.getByText('SGST:')).toBeInTheDocument()
    expect(screen.queryByText('IGST:')).toBeNull()
    expect(screen.getByText('Grand Total:')).toBeInTheDocument()
    expect(screen.getByText('₹236')).toBeInTheDocument()
  })

  it('shows IGST for inter-state and hides CGST/SGST', () => {
    render(<InvoiceBreakdownCard {...base} cgstAmt={0} sgstAmt={0} igstAmt={36} />)
    expect(screen.getByText('IGST:')).toBeInTheDocument()
    expect(screen.queryByText('CGST:')).toBeNull()
    expect(screen.queryByText('SGST:')).toBeNull()
  })

  it('shows the Bill Discount line only when discount > 0', () => {
    const { rerender } = render(<InvoiceBreakdownCard {...base} discount={0} />)
    expect(screen.queryByText('Bill Discount:')).toBeNull()
    rerender(<InvoiceBreakdownCard {...base} discount={38} />)
    expect(screen.getByText('Bill Discount:')).toBeInTheDocument()
    expect(screen.getByText('− ₹38')).toBeInTheDocument()
  })
})
