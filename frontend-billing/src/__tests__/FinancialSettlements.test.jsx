import React from 'react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { render, screen, fireEvent, waitFor, cleanup } from '@testing-library/react'
import FinancialSettlements from '../components/payments/FinancialSettlements'
afterEach(cleanup)
function transport(post) {
  return vi.fn(async (path, options) => {
    if (options?.method === 'POST') return post(path, options)
    const base = path.split('?')[0]
    const data = base === '/purchases' ? [{ id: 1, invoice_number: 'BILL-1', supplier_name: 'Supplier', status: 'confirmed', outstanding: 100 }]
      : base === '/customer-credits' ? { items: [{ id: 4, invoice_no: 'CN-1', customer_id: 7, customer: 'Customer', available_credit: 40 }], total: 1 }
      : base === '/invoices' ? [{ id: 2, invoice_no: 'INV-2', customer_id: 7, outstanding: 60 }, { id: 3, invoice_no: 'OTHER-CUSTOMER', customer_id: 8, outstanding: 90 }]
      : { items: [], total: 0 }
    return { ok: true, json: async () => data }
  })
}
async function open(fetch) {
  render(<FinancialSettlements authFetch={fetch} />)
  fireEvent.click(screen.getByRole('button', { name: 'Supplier payments & customer credits' }))
  await screen.findByRole('option', { name: /BILL-1/ })
}
describe('financial settlement user flows', () => {
  it('retries the same supplier payment with one durable intent key', async () => {
    const post = vi.fn().mockRejectedValueOnce(new TypeError('Connection lost')).mockResolvedValue({ ok: true, json: async () => ({ id: 9 }) })
    const fetch = transport(post)
    await open(fetch)
    fireEvent.change(screen.getByLabelText('Settlement source'), { target: { value: '1' } })
    fireEvent.change(screen.getByLabelText('Settlement amount'), { target: { value: '50' } })
    fireEvent.click(screen.getByRole('button', { name: 'Pay supplier' }))
    await screen.findByRole('alert')
    fireEvent.click(screen.getByRole('button', { name: 'Pay supplier' }))
    await waitFor(() => expect(post).toHaveBeenCalledTimes(2))
    const first = JSON.parse(post.mock.calls[0][1].body), second = JSON.parse(post.mock.calls[1][1].body)
    expect(post.mock.calls[0][0]).toBe('/supplier-payments')
    expect(first).toMatchObject({ purchase_invoice_id: 1, amount: 50, payment_mode: 'Bank' })
    expect(second.idempotency_key).toBe(first.idempotency_key)
    await screen.findByText(/₹50 recorded/)
  })
  it('offers same-customer allocation targets and posts explicit source/target links', async () => {
    const post = vi.fn(async () => ({ ok: true, json: async () => ({ id: 10 }) }))
    await open(transport(post))
    fireEvent.change(screen.getByLabelText('Settlement type'), { target: { value: 'allocate' } })
    await screen.findByRole('option', { name: /CN-1/ })
    fireEvent.change(screen.getByLabelText('Settlement source'), { target: { value: '4' } })
    expect(screen.queryByRole('option', { name: /OTHER-CUSTOMER/ })).not.toBeInTheDocument()
    fireEvent.change(screen.getByLabelText('Target invoice'), { target: { value: '2' } })
    fireEvent.change(screen.getByLabelText('Settlement amount'), { target: { value: '20' } })
    fireEvent.click(screen.getByRole('button', { name: 'Apply customer credit' }))
    await waitFor(() => expect(post).toHaveBeenCalledOnce())
    expect(post.mock.calls[0][0]).toBe('/customer-credit-allocations')
    expect(JSON.parse(post.mock.calls[0][1].body)).toMatchObject({ credit_note_id: 4, target_invoice_id: 2, amount: 20 })
  })
})
