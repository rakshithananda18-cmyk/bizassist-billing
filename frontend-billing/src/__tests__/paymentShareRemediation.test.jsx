import { describe, it, expect, vi, afterEach } from 'vitest'
import { renderHook, act, cleanup } from '@testing-library/react'
vi.mock('../contexts/AuthContext', () => ({
  useAuth: () => ({
    user: { id: 2, business_name: 'Business B' },
    profile: { upi_vpa: 'business-b@bank' },
  }),
}))
vi.mock('../components/invoice/InvoiceViewerModal', () => ({ default: () => null }))
vi.mock('../components/parties/SaleReturnModal', () => ({ default: () => null }))
vi.mock('../components/payments/RecordPaymentModal', () => ({ default: () => null }))
import useInvoiceActions from '../hooks/useInvoiceActions'

afterEach(() => { cleanup(); vi.restoreAllMocks(); localStorage.clear() })

describe('Remediation verification: invoice share money contract (WEB-02 & WEB-03)', () => {
  it('correctly uses server outstanding balance and current business profile VPA', () => {
    // Foreign device key from previous business
    localStorage.setItem('pos_upi_vpa', 'previous-business-a@bank')
    const open = vi.spyOn(window, 'open').mockImplementation(() => null)
    const { result } = renderHook(() => useInvoiceActions(vi.fn()))

    act(() => result.current.share({
      invoice_no: 'INV-1',
      total_amount: 100,
      paid_amount: 0,
      credited_amount: 40,
      outstanding: 60,
      customer_phone: '9876543210',
    }))

    expect(open).toHaveBeenCalled()
    const message = new URL(open.mock.calls[0][0]).searchParams.get('text')

    // WEB-03 verification: Uses credit-adjusted server outstanding (60, not 100)
    expect(message).toContain('Balance Due: ₹60')
    expect(message).not.toContain('Balance Due: ₹100')

    // WEB-02 verification: Uses current business B VPA, NOT previous business A VPA
    expect(message).toContain('pa=business-b@bank')
    expect(message).not.toContain('previous-business-a@bank')
  })
})
