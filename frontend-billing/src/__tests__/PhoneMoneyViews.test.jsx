import React from 'react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, screen, within } from '@testing-library/react'
import { renderWithAuth as render } from './renderWithAuth'
import InvoicesListView from '../components/payments/InvoicesListView'
import OrdersTab from '../b2b/components/OrdersTab'

vi.mock('../hooks/usePhoneLayout', () => ({ default: () => true }))
afterEach(cleanup)

describe('Phone money records', () => {
  it('keeps invoice actions behind disclosure, preserves norms and filters the same records', async () => {
    const rows = [
      { id: 1, invoice_no: 'INV-1', customer_name: 'Acme', total_amount: 500, outstanding: 300, status: 'Partial', can_record_payment: true, can_return: true },
      { id: 2, invoice_no: 'INV-2', customer_name: 'Beta', total_amount: 200, outstanding: 0, status: 'Paid', can_record_payment: false, can_return: false },
    ]
    const actions = { view: vi.fn(), print: vi.fn(), share: vi.fn(), recordPayment: vi.fn(), openReturn: vi.fn() }
    render(<InvoicesListView authFetch={async () => ({ ok: true, json: async () => rows })} actions={actions} />)
    const name = await screen.findByRole('button', { name: 'Acme' })
    expect(screen.queryByRole('table')).not.toBeInTheDocument()
    const record = name.closest('article')
    const disclosure = record.querySelector('details')
    expect(disclosure).not.toHaveAttribute('open')
    fireEvent.click(within(record).getByText('Details & actions'))
    // jsdom does not toggle native details on synthetic clicks.
    disclosure.open = true
    fireEvent.click(within(record).getByRole('button', { name: 'Record payment' }))
    expect(actions.recordPayment).toHaveBeenCalledWith(rows[0])
    const paid = screen.getByRole('button', { name: 'Beta' }).closest('article')
    expect(within(paid).queryByText('Record payment')).not.toBeInTheDocument()
    fireEvent.change(screen.getByPlaceholderText(/Search invoice/), { target: { value: 'Beta' } })
    expect(screen.queryByRole('button', { name: 'Acme' })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Beta' })).toBeInTheDocument()
  })

  it('retains direction-based B2B status changes in phone order details', () => {
    const order = { id: 1, order_number: 'ORD-1', status: 'pending', created_at: '2026-11-11', buyer_name: 'Retail Shop', buyer_bizid: 'BA-BUYER', total_amount: 300 }
    const change = vi.fn(), open = vi.fn()
    render(<OrdersTab direction="incoming" userId={1} orders={[order]} stats={{ count: 1, open: 1, openValue: 300 }} loading={false} search="" setSearch={vi.fn()} statusFilter="" setStatusFilter={vi.fn()} sort={{}} toggleSort={vi.fn()} onChangeStatus={change} onOpenOrder={open} />)
    expect(screen.queryByRole('table')).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'View order' }))
    expect(open).toHaveBeenCalledWith(order)
    const record = screen.getByRole('button', { name: 'Retail Shop' }).closest('article')
    record.querySelector('details').open = true
    fireEvent.click(within(record).getByRole('button', { name: 'Accept' }))
    expect(change).toHaveBeenCalledWith(1, 'accepted')
  })
})
