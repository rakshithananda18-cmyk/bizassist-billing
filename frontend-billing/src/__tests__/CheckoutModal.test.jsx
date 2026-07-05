// Render/smoke tests for <CheckoutModal> — the POS payment popup extracted from
// Sales.jsx. It's a large interactive component, so this locks the essentials:
// it respects `open`, shows the checkout UI (header, tendering, bill discount),
// and the Save button delegates to onSaveInvoice. Deep keyboard/customer-dropdown
// flows are covered by the pure helpers (invoiceMath, TenderChips) elsewhere.
import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import CheckoutModal from '../components/sales/CheckoutModal'

const baseProps = () => ({
  open: true,
  onClose: vi.fn(),
  form: {
    items: [{ qty: 2, price: 190, discount: 0, cgst_rate: 2.5, sgst_rate: 2.5 }],
    customer_id: '', godown_id: '', due_date: '2026-06-20', notes: '',
    payment_mode: 'cash', amount_received: '',
    bill_discount_type: 'amount', bill_discount_value: '', cash_discount: '',
  },
  setForm: vi.fn(),
  subtotal: 380, gstAmt: 19, grandTotal: 399, payable: 399, roundOff: 0, cashDiscountAmt: 0, cgstAmt: 9.5, sgstAmt: 9.5, igstAmt: 0,
  billDiscountAmt: 0,
  customers: [], setCustomers: vi.fn(),
  godowns: [],
  upiVpa: 'merchant@upi',
  authFetch: vi.fn(),
  onSaveInvoice: vi.fn(),
  submitting: false,
  setAlert: vi.fn(),
  focusTarget: 'amountReceived',
  funcKeys: {},
})

describe('CheckoutModal', () => {
  it('renders nothing when closed', () => {
    const { container } = render(<CheckoutModal {...baseProps()} open={false} />)
    expect(container.firstChild).toBeNull()
  })

  it('shows the checkout UI when open', () => {
    render(<CheckoutModal {...baseProps()} />)
    expect(screen.getByText('POS Checkout')).toBeInTheDocument()
    expect(screen.getByText(/Tendering/)).toBeInTheDocument()
    expect(screen.getByText('Discount (₹)')).toBeInTheDocument()
    expect(screen.getByText('Payable')).toBeInTheDocument()
  })

  it('non-credit shows "Paid & Print" and delegates to onSaveInvoice(true)', () => {
    const props = baseProps()   // payment_mode: 'cash'
    render(<CheckoutModal {...props} />)
    fireEvent.click(screen.getByText(/Paid & Print/))
    expect(props.onSaveInvoice).toHaveBeenCalledWith(true)
  })

  it('credit mode shows "Save & Print"', () => {
    const props = baseProps()
    props.form.payment_mode = 'credit'
    render(<CheckoutModal {...props} />)
    expect(screen.getByText(/Save & Print/)).toBeInTheDocument()
  })

  it('disables the Save button label while submitting', () => {
    render(<CheckoutModal {...baseProps()} submitting={true} />)
    expect(screen.getByText(/Saving Invoice/)).toBeInTheDocument()
  })

  it('typing a discount updates the form', () => {
    const props = baseProps()
    render(<CheckoutModal {...props} />)
    const input = screen.getByTitle(/Discount on the payable/)
    fireEvent.change(input, { target: { value: '3' } })
    expect(props.setForm).toHaveBeenCalled()
  })

  it('shows the discount + payable rows when a cash discount is applied', () => {
    render(<CheckoutModal {...baseProps()} cashDiscountAmt={3} payable={396} />)
    expect(screen.getByText('Payable')).toBeInTheDocument()
    expect(screen.getByText('Cash discount')).toBeInTheDocument()
  })

  it('shows a negative red balance when amount received is short', () => {
    const props = baseProps()
    props.form.amount_received = '300'   // payable 399 → short by 99
    render(<CheckoutModal {...props} />)
    expect(screen.getByText('Balance still due')).toBeInTheDocument()
  })

  it('shows the customer pending-due line from the ledger', async () => {
    const props = baseProps()
    props.form.customer_id = '7'
    props.authFetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ outstanding_total: 1250, entries: [{ invoice_no: 'INV-0009', outstanding: 1250, status: 'Partial' }] }),
    })
    render(<CheckoutModal {...props} />)
    expect(await screen.findByText(/Pending due:/)).toBeInTheDocument()
    expect(screen.getByText(/INV-0009/)).toBeInTheDocument()
  })

  it('syncs amount_received with pay when pay changes', () => {
    const props = baseProps()
    const { rerender } = render(<CheckoutModal {...props} />)
    expect(props.setForm).toHaveBeenCalled()
    props.setForm.mockClear()

    // Rerender with different payable (which computes to different pay)
    rerender(<CheckoutModal {...props} payable={350} />)
    expect(props.setForm).toHaveBeenCalled()
    const updater = props.setForm.mock.calls[0][0]
    const updatedForm = updater({ payment_mode: 'cash', amount_received: '399' })
    expect(updatedForm.amount_received).toBe('350.00')
  })

  it('syncs amount_received to 0 in credit mode', () => {
    const props = baseProps()
    props.form.payment_mode = 'credit'
    render(<CheckoutModal {...props} />)
    expect(props.setForm).toHaveBeenCalled()
    const updater = props.setForm.mock.calls[0][0]
    const updatedForm = updater({ payment_mode: 'credit', amount_received: '399' })
    expect(updatedForm.amount_received).toBe('0')
  })

  it('opens and closes the inline customer drawer', () => {
    const props = baseProps()
    render(<CheckoutModal {...props} />)
    
    // The drawer should be closed initially
    expect(screen.queryByText('Customer Name *')).not.toBeInTheDocument()
    
    // Click the Plus button next to the customer name input
    const plusBtn = screen.getByTitle('Add New Customer')
    fireEvent.click(plusBtn)
    
    // Now the drawer should be open and display customer fields
    expect(screen.getByText('Customer Name *')).toBeInTheDocument()
    expect(screen.getByText('Phone Number')).toBeInTheDocument()
    expect(screen.getByText('GSTIN')).toBeInTheDocument()
    
    // Click the Cancel button in the drawer to close it
    const cancelBtn = screen.getByText('Cancel')
    fireEvent.click(cancelBtn)
    
    // The drawer should be closed now
    expect(screen.queryByText('Customer Name *')).not.toBeInTheDocument()
  })
})
