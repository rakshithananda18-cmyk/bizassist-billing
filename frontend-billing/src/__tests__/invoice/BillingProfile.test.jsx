// Phase 2 frontend tests:
//   • ThermalCompact renders the payload (GST + balance-due states)
//   • useBillingProfile: fetch + session cache + FAIL-OPEN on error
//   • CheckoutModal customer-first gating: blocks save without a customer when
//     the profile requires one; saves normally otherwise (and when profile is null)
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, cleanup, waitFor, fireEvent } from '@testing-library/react'
import ThermalCompact from '../../invoice/templates/ThermalCompact'
import { gstPayload, plainPayload } from './fixtures'

// ── api mock (for the hook) ───────────────────────────────────────────────────
const apiGet = vi.fn()
vi.mock('../../api/client', () => ({
  api: { get: (...a) => apiGet(...a), post: vi.fn(() => Promise.resolve({})), put: vi.fn() },
}))

// ── billing-profile hook mock control (for CheckoutModal gating tests) ───────
let mockProfile = null
vi.mock('../../hooks/useBillingProfile', async (importOriginal) => {
  const real = await importOriginal()
  return {
    ...real,
    useBillingProfile: vi.fn((mode) => ({ profile: mockProfile, loading: false })),
    __real: real,
  }
})

import CheckoutModal from '../../components/sales/CheckoutModal'

afterEach(() => {
  cleanup()
  mockProfile = null
})

// ── ThermalCompact ────────────────────────────────────────────────────────────

describe('ThermalCompact', () => {
  it('renders header, items, GST totals and payments', () => {
    render(<ThermalCompact payload={gstPayload()} />)
    expect(screen.getByText('Mehta Hardware')).toBeInTheDocument()
    expect(screen.getByText(/Bill: INV-42/)).toBeInTheDocument()
    expect(screen.getByText('Steel Bolt M8')).toBeInTheDocument()
    expect(screen.getByText('CGST')).toBeInTheDocument()
    expect(screen.getByText('TOTAL')).toBeInTheDocument()
    expect(screen.getByText(/Computer generated invoice/)).toBeInTheDocument()
  })

  it('non-GST payload shows no tax rows and a balance line', () => {
    render(<ThermalCompact payload={plainPayload()} />)
    expect(screen.queryByText('CGST')).not.toBeInTheDocument()
    expect(screen.queryByText(/GSTIN/)).not.toBeInTheDocument()
    expect(screen.getByText('BALANCE DUE')).toBeInTheDocument()
  })

  it('never mutates the payload', () => {
    const p = gstPayload()
    const snap = JSON.parse(JSON.stringify(p))
    render(<ThermalCompact payload={p} />)
    expect(p).toEqual(snap)
  })
})

// ── CheckoutModal gating ──────────────────────────────────────────────────────

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
  subtotal: 380, gstAmt: 19, grandTotal: 399, payable: 399, roundOff: 0,
  cashDiscountAmt: 0, cgstAmt: 9.5, sgstAmt: 9.5, igstAmt: 0, billDiscountAmt: 0,
  customers: [], setCustomers: vi.fn(),
  godowns: [],
  upiVpa: 'merchant@upi',
  authFetch: vi.fn(() => Promise.resolve({ ok: false })),
  onSaveInvoice: vi.fn(),
  submitting: false,
  setAlert: vi.fn(),
  focusTarget: 'amountReceived',
  funcKeys: {},
})

describe('CheckoutModal customer-first gating (Phase 2)', () => {
  it('blocks save when the profile requires a customer and none is selected', () => {
    mockProfile = {
      mode_key: 'wholesale', label: 'Wholesale / Distribution',
      customer_required: true, terminology: { customer: 'Buyer' },
    }
    const props = baseProps()
    render(<CheckoutModal {...props} />)
    fireEvent.click(screen.getByText(/Paid & Print/))
    expect(props.onSaveInvoice).not.toHaveBeenCalled()
    expect(props.setAlert).toHaveBeenCalledWith(
      expect.objectContaining({ type: 'danger', msg: expect.stringContaining('Buyer') }))
  })

  it('saves when the profile requires a customer and one IS selected', () => {
    mockProfile = { mode_key: 'wholesale', customer_required: true, terminology: {} }
    const props = baseProps()
    props.form.customer_id = '7'
    render(<CheckoutModal {...props} />)
    fireEvent.click(screen.getByText(/Paid & Print/))
    expect(props.onSaveInvoice).toHaveBeenCalledWith(true)
  })

  it('FAIL-OPEN: saves without a customer when the profile is unavailable', () => {
    mockProfile = null
    const props = baseProps()
    render(<CheckoutModal {...props} />)
    fireEvent.click(screen.getByText(/Paid & Print/))
    expect(props.onSaveInvoice).toHaveBeenCalledWith(true)
  })

  it('does not gate when the vertical does not require a customer', () => {
    mockProfile = { mode_key: 'supermarket', customer_required: false, terminology: {} }
    const props = baseProps()
    render(<CheckoutModal {...props} />)
    fireEvent.click(screen.getByText(/Save Bill Only/))
    expect(props.onSaveInvoice).toHaveBeenCalledWith(false)
  })
})

// ── useBillingProfile (real implementation, mocked api) ──────────────────────

describe('useBillingProfile (real hook)', () => {
  it('fetches, caches, and fails open', async () => {
    const { __real } = await import('../../hooks/useBillingProfile')
    const { renderHook } = await import('@testing-library/react')
    __real.clearBillingProfileCache()

    apiGet.mockResolvedValueOnce({ profile: { mode_key: 'pharmacy', customer_required: false } })
    const r1 = renderHook(() => __real.useBillingProfile())
    await waitFor(() => expect(r1.result.current.profile?.mode_key).toBe('pharmacy'))
    expect(apiGet).toHaveBeenCalledTimes(1)

    // second consumer hits the session cache — no extra request
    const r2 = renderHook(() => __real.useBillingProfile())
    await waitFor(() => expect(r2.result.current.profile?.mode_key).toBe('pharmacy'))
    expect(apiGet).toHaveBeenCalledTimes(1)

    // fail-open on error
    __real.clearBillingProfileCache()
    apiGet.mockRejectedValueOnce(new Error('offline'))
    const r3 = renderHook(() => __real.useBillingProfile())
    await waitFor(() => expect(r3.result.current.loading).toBe(false))
    expect(r3.result.current.profile).toBeNull()
  })

  it('mode param requests that vertical explicitly (no cache)', async () => {
    const { __real } = await import('../../hooks/useBillingProfile')
    const { renderHook } = await import('@testing-library/react')
    __real.clearBillingProfileCache()
    apiGet.mockResolvedValueOnce({ profile: { mode_key: 'repair' } })
    const r = renderHook(() => __real.useBillingProfile('repair'))
    await waitFor(() => expect(r.result.current.profile?.mode_key).toBe('repair'))
    expect(apiGet).toHaveBeenCalledWith('/business/billing-profile', { mode: 'repair' })
  })
})
