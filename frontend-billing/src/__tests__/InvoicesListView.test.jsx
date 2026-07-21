// InvoicesListView: all-invoices table with norms-aware actions.
import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, cleanup, waitFor, fireEvent } from '@testing-library/react'
import React from 'react'

import InvoicesListView from '../components/payments/InvoicesListView'

const invoices = [
  { id: 1, invoice_no: 'INV-1', customer_name: 'Acme', invoice_date: '2026-07-20',
    total_amount: 500, outstanding: 300, status: 'Partial',
    can_record_payment: true, can_return: true, editable: false },
  { id: 2, invoice_no: 'INV-2', customer_name: 'Beta', invoice_date: '2026-07-19',
    total_amount: 200, outstanding: 0, status: 'Paid',
    can_record_payment: false, can_return: true, editable: false },
  { id: 3, invoice_no: 'CN-1', customer_name: 'Acme', invoice_date: '2026-07-18',
    total_amount: 50, outstanding: 0, status: 'credit_note',
    can_record_payment: false, can_return: false, editable: false },
]

function authFetch() {
  return vi.fn(async (path) => {
    if (path.startsWith('/invoices')) return { ok: true, json: async () => invoices }
    return { ok: false, json: async () => ([]) }
  })
}

const mockActions = () => ({ view: vi.fn(), print: vi.fn(), share: vi.fn(), recordPayment: vi.fn(), openReturn: vi.fn(), modals: null })

afterEach(cleanup)

describe('InvoicesListView', () => {
  it('lists invoices and gates actions by norms', async () => {
    render(<InvoicesListView authFetch={authFetch()} actions={mockActions()} />)
    await waitFor(() => expect(screen.getByText('INV-1')).toBeInTheDocument())
    // Actions are icon buttons (title = accessible name). Only the Partial
    // invoice can take a payment (INV-2 Paid, CN-1 credit note).
    expect(screen.getAllByRole('button', { name: 'Record payment' }).length).toBe(1)
    expect(screen.getByText('CN-1')).toBeInTheDocument()
  })

  it('fires the shared actions', async () => {
    const actions = mockActions()
    render(<InvoicesListView authFetch={authFetch()} actions={actions} />)
    await waitFor(() => expect(screen.getByText('INV-1')).toBeInTheDocument())

    fireEvent.click(screen.getAllByRole('button', { name: 'View invoice' })[0])
    expect(actions.view).toHaveBeenCalledWith('INV-1')

    fireEvent.click(screen.getByRole('button', { name: 'Record payment' }))
    expect(actions.recordPayment).toHaveBeenCalledWith(expect.objectContaining({ invoice_no: 'INV-1' }))
  })

  it('filters by search', async () => {
    render(<InvoicesListView authFetch={authFetch()} actions={mockActions()} />)
    await waitFor(() => expect(screen.getByText('INV-1')).toBeInTheDocument())
    fireEvent.change(screen.getByPlaceholderText(/Search invoice/), { target: { value: 'Beta' } })
    expect(screen.queryByText('INV-1')).not.toBeInTheDocument()
    expect(screen.getByText('INV-2')).toBeInTheDocument()
  })
})
