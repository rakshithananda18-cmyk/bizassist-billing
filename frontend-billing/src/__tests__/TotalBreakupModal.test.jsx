// Render tests for the first component extracted out of Sales.jsx.
// Presentational only — verifies it shows the right amounts and respects `open`.
import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import TotalBreakupModal from '../components/sales/TotalBreakupModal'

const base = {
  open: true,
  onClose: () => {},
  subtotal: 200,
  gstAmt: 36,
  isIntrastate: true,
  cgstAmt: 18,
  sgstAmt: 18,
  igstAmt: 0,
  grandTotal: 236,
  amountReceived: 500,
  changeToReturn: 264,
  paymentMode: 'cash',
  upiVpa: 'merchant@upi',
}

describe('TotalBreakupModal', () => {
  it('renders nothing when closed', () => {
    const { container } = render(<TotalBreakupModal {...base} open={false} />)
    expect(container.firstChild).toBeNull()
  })

  it('shows subtotal, CGST/SGST split and grand total when open (intra-state)', () => {
    render(<TotalBreakupModal {...base} />)
    expect(screen.getByText(/Total Breakup Details/)).toBeInTheDocument()
    expect(screen.getByText('CGST:')).toBeInTheDocument()
    expect(screen.getByText('SGST:')).toBeInTheDocument()
    expect(screen.queryByText('IGST:')).toBeNull()
    expect(screen.getByText('₹236')).toBeInTheDocument()   // grand total
  })

  it('shows IGST for inter-state', () => {
    render(<TotalBreakupModal {...base} isIntrastate={false} cgstAmt={0} sgstAmt={0} igstAmt={36} />)
    expect(screen.getByText('IGST:')).toBeInTheDocument()
    expect(screen.queryByText('CGST:')).toBeNull()
  })

  it('shows the UPI QR block only for UPI payment', () => {
    const { rerender } = render(<TotalBreakupModal {...base} paymentMode="cash" />)
    expect(screen.queryByText(/Scan to pay/)).toBeNull()
    rerender(<TotalBreakupModal {...base} paymentMode="upi" />)
    expect(screen.getByText(/Scan to pay/)).toBeInTheDocument()
  })
})
