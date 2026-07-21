// New Money workspace views: PartyAccount drill-down + CashbookView.
import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, cleanup, waitFor, fireEvent } from '@testing-library/react'
import React from 'react'

import PartyAccount from '../components/money/PartyAccount'
import CashbookView from '../components/money/CashbookView'
import InvoicesListView from '../components/payments/InvoicesListView'

const mockActions = () => ({ view: vi.fn(), print: vi.fn(), share: vi.fn(), recordPayment: vi.fn(), openReturn: vi.fn(), modals: null })

afterEach(cleanup)

describe('PartyAccount', () => {
  const party = { id: 1, name: 'Acme', phone: '999', outstanding_balance: 300, credit_balance: 0 }
  const ledger = {
    customer_name: 'Acme', outstanding_total: 300, credit_balance: 0,
    entries: [
      { type: 'invoice', invoice_no: 'INV-1', invoice_id: 10, date: '2026-07-20', total_amount: 500, paid_amount: 200, outstanding: 300, status: 'Partial' },
    ],
  }
  const authFetch = () => vi.fn(async (p) => p.includes('/ledger') ? { ok: true, json: async () => ledger } : { ok: false, json: async () => ({}) })

  it('shows outstanding, the ledger, and fires actions', async () => {
    const onSettle = vi.fn(), actions = mockActions()
    render(<PartyAccount authFetch={authFetch()} party={party} actions={actions} onSettle={onSettle} onBack={() => {}} onRecordPayment={() => {}} onReminder={() => {}} />)
    await waitFor(() => expect(screen.getByText('INV-1')).toBeInTheDocument())
    expect(screen.getAllByText('₹300').length).toBeGreaterThan(0)  // header + ledger

    fireEvent.click(screen.getByText('Settle dues'))
    expect(onSettle).toHaveBeenCalledWith(party)
    // The ledger row uses the shared InvoiceActions → view() from the hook.
    fireEvent.click(screen.getByTitle('View invoice'))
    expect(actions.view).toHaveBeenCalledWith('INV-1')
  })
})

describe('CashbookView', () => {
  const authFetch = () => vi.fn(async (p) => {
    if (p === '/payments') return { ok: true, json: async () => ([{ id: 1, date: '2026-07-20', type: 'received', party_name: 'Acme', amount: 200, method: 'UPI' }]) }
    if (p === '/billing/expenses') return { ok: true, json: async () => ([{ id: 2, expense_date: '2026-07-19', category: 'Rent', amount: 5000, payment_mode: 'Cash' }]) }
    return { ok: false, json: async () => ([]) }
  })

  it('merges receipts and expenses and filters by chip', async () => {
    render(<CashbookView authFetch={authFetch()} />)
    await waitFor(() => expect(screen.getByText('Acme')).toBeInTheDocument())
    expect(screen.getByText('Rent')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'Expenses' }))
    expect(screen.queryByText('Acme')).not.toBeInTheDocument()  // receipt filtered out
    expect(screen.getByText('Rent')).toBeInTheDocument()
  })
})

describe('InvoicesListView status chips', () => {
  const invoices = [
    { id: 1, invoice_no: 'INV-1', customer_id: 5, customer_name: 'A', outstanding: 300, status: 'Partial', invoice_type: 'B2C', can_record_payment: true, can_return: true },
    { id: 2, invoice_no: 'INV-2', customer_id: 5, customer_name: 'A', outstanding: 0, status: 'Paid', invoice_type: 'B2C', can_record_payment: false, can_return: true },
  ]
  const authFetch = () => vi.fn(async () => ({ ok: true, json: async () => invoices }))

  it('filters by the Paid chip', async () => {
    render(<InvoicesListView authFetch={authFetch()} showStatusChips actions={mockActions()} />)
    await waitFor(() => expect(screen.getByText('INV-1')).toBeInTheDocument())
    // Status chips now live inside the Filters popover — open it, then pick Paid.
    fireEvent.click(screen.getByRole('button', { name: 'Filters' }))
    fireEvent.click(screen.getByRole('button', { name: 'Paid' }))
    expect(screen.queryByText('INV-1')).not.toBeInTheDocument()
    expect(screen.getByText('INV-2')).toBeInTheDocument()
  })
})
