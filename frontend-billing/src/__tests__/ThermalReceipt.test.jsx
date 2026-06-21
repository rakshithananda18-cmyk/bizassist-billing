// Render tests for <ThermalReceipt> — the print receipt extracted from Sales.jsx
// (R5 step 1). Presentational only: given already-computed POS figures it must
// render the M.R. Traders-style receipt (MRP + Rate columns, per-slab GST table,
// PAYABLE / cash-discount lines, "You have Saved"). Locks the verbatim extraction.
//
// The component renders through a portal into document.body, so we query `screen`
// (which scopes to document.body) and explicitly unmount between tests.
import { describe, it, expect, afterEach } from 'vitest'
import { render, screen, cleanup } from '@testing-library/react'
import ThermalReceipt from '../components/sales/ThermalReceipt'

afterEach(() => {
  cleanup()
  // Portal content lives on document.body — make sure nothing bleeds between tests.
  const node = document.getElementById('thermal-receipt')
  if (node) node.remove()
})

// Intra-state cart: Rice (5% slab) + Soap (12% slab), reconciled to the rupee.
//   subtotal 320 · CGST 12.2 · SGST 12.2 · grand 344.40 · cash disc 3 · payable 341
const base = {
  settings: { print: { print_amount_in_words: true } },
  profile: { business_name: 'MR Traders', address: '12 MG Road, Bengaluru' },
  activeTab: { name: 'B1' },
  form: {
    payment_mode: 'cash',
    amount_received: 341,
    notes: '',
    customer_id: null,
    items: [
      { product: 'Rice', hsn_sac: '1006', unit: 'Nos', qty: 2, price: 100, discount: 0, cgst_rate: 2.5, sgst_rate: 2.5 },
      { product: 'Soap', hsn_sac: '3401', unit: 'Nos', qty: 1, price: 120, discount: 0, cgst_rate: 6, sgst_rate: 6 },
    ],
  },
  customers: [],
  user: { username: 'cashier1' },
  isIntrastate: true,
  subtotal: 320,
  billDiscountAmt: 0,
  cgstAmt: 12.2,
  sgstAmt: 12.2,
  igstAmt: 0,
  cashDiscountAmt: 3,
  roundOff: -0.4,
  grandTotal: 344.4,
  payable: 341,
  changeToReturn: 0,
  colFooter: { qty: 3, discount: 0 },
}

describe('ThermalReceipt', () => {
  it('renders the header, item rows and per-slab GST table', () => {
    render(<ThermalReceipt {...base} />)
    expect(screen.getByText('MR TRADERS')).toBeInTheDocument()      // name upper-cased
    expect(screen.getByText('Rice')).toBeInTheDocument()
    expect(screen.getByText('Soap')).toBeInTheDocument()
    expect(screen.getByText('Tax%')).toBeInTheDocument()            // per-slab GST table header
    // 5% / 12% appear in both the item GST column and the slab table → ≥1 each.
    expect(screen.getAllByText('5%').length).toBeGreaterThan(0)     // Rice slab
    expect(screen.getAllByText('12%').length).toBeGreaterThan(0)    // Soap slab
  })

  it('shows the PAYABLE + cash-discount lines and "You have Saved" when a cash discount applies', () => {
    render(<ThermalReceipt {...base} />)
    expect(screen.getByText('PAYABLE:')).toBeInTheDocument()
    // ₹341.00 shows as both PAYABLE and Amount Received.
    expect(screen.getAllByText('₹341.00').length).toBeGreaterThan(0)
    expect(screen.getByText(/Cash Discount:/)).toBeInTheDocument()
    expect(screen.getByText('Round Off:')).toBeInTheDocument()
    expect(screen.getByText('You have Saved:')).toBeInTheDocument()
    // saving = line discount 0 + bill 0 + cash 3 → ₹3.00 (also the cash-discount line)
    expect(screen.getAllByText('₹3.00').length).toBeGreaterThan(0)
  })

  it('falls back to a single GRAND TOTAL when there is no cash discount or round-off', () => {
    render(<ThermalReceipt {...base} cashDiscountAmt={0} roundOff={0} payable={344.4} colFooter={{ qty: 3, discount: 0 }} />)
    expect(screen.getByText('GRAND TOTAL:')).toBeInTheDocument()
    expect(screen.queryByText('PAYABLE:')).not.toBeInTheDocument()
  })

  it('returns nothing when there is no active bill', () => {
    const { container } = render(<ThermalReceipt {...base} activeTab={null} />)
    expect(container.firstChild).toBeNull()
    expect(document.getElementById('thermal-receipt')).toBeNull()
  })
})
