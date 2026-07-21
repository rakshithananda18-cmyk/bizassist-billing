// SettleDuesModal: owner FIFO lump-sum settle — customer picker, submit,
// allocation result + advance.
import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, cleanup, waitFor, fireEvent } from '@testing-library/react'
import React from 'react'

import SettleDuesModal from '../components/payments/SettleDuesModal'

function authFetchFactory() {
  return vi.fn(async (path, opts) => {
    if (path.startsWith('/customers?')) {
      return { ok: true, json: async () => ([
        { id: 1, name: 'Acme', outstanding: 1100, credit_balance: 0 },
      ]) }
    }
    if (path === '/customers/1/settle' && opts?.method === 'POST') {
      return { ok: true, json: async () => ({
        total_applied: 1000, advance: 0, amount: 1000, credit_balance: 0,
        allocations: [
          { invoice_id: 10, invoice_no: 'INV-1', applied: 500, remaining_after: 0, status: 'Paid' },
          { invoice_id: 11, invoice_no: 'INV-2', applied: 500, remaining_after: 100, status: 'Partial' },
        ],
      }) }
    }
    return { ok: false, json: async () => ({}) }
  })
}

// CustomSelect is a portal-based widget: options only render once opened.
async function pickCustomer() {
  // The customer select's button shows the placeholder until a value is picked.
  fireEvent.click(await screen.findByText('Choose a customer…'))
  fireEvent.click(await screen.findByText(/Acme/))
}

afterEach(cleanup)

describe('SettleDuesModal', () => {
  it('loads customers, settles, and shows the allocation', async () => {
    const authFetch = authFetchFactory()
    const onDone = vi.fn()
    render(<SettleDuesModal authFetch={authFetch} onClose={() => {}} onDone={onDone} />)

    await waitFor(() => expect(authFetch).toHaveBeenCalledWith('/customers?per_page=500'))
    await pickCustomer()
    fireEvent.change(screen.getByPlaceholderText('0.00'), { target: { value: '1000' } })
    fireEvent.click(screen.getByText('Settle'))

    await waitFor(() => expect(screen.getByText(/Applied ₹1,000/)).toBeInTheDocument())
    expect(screen.getByText('INV-1')).toBeInTheDocument()
    expect(screen.getByText('INV-2')).toBeInTheDocument()
    expect(onDone).toHaveBeenCalled()
    expect(authFetch).toHaveBeenCalledWith('/customers/1/settle', expect.objectContaining({ method: 'POST' }))
  })

  it('validates amount before submitting', async () => {
    const authFetch = authFetchFactory()
    render(<SettleDuesModal authFetch={authFetch} onClose={() => {}} onDone={() => {}} />)
    await waitFor(() => expect(authFetch).toHaveBeenCalledWith('/customers?per_page=500'))
    await pickCustomer()
    fireEvent.click(screen.getByText('Settle'))   // amount still empty
    await waitFor(() => expect(screen.getByText(/greater than 0/)).toBeInTheDocument())
  })
})
