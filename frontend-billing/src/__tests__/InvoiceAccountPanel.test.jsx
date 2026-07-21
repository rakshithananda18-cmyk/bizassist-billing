// InvoiceAccountPanel: per-invoice money view — totals, payments, returns.
import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, cleanup, waitFor } from '@testing-library/react'
import React from 'react'

import InvoiceAccountPanel from '../components/invoice/InvoiceAccountPanel'

const account = {
  invoice_id: 10, invoice_no: 'INV-1', status: 'Partial',
  total: 500, paid: 200, outstanding: 300,
  payments: [{ id: 1, date: '2026-07-20', amount: 200, method: 'UPI', note: '' }],
  returns: [{ id: 9, credit_note_no: 'CN-1', date: '2026-07-21', amount: 50 }],
}

afterEach(cleanup)

describe('InvoiceAccountPanel', () => {
  it('renders payments and returns as themed side-panel sections', async () => {
    const authFetch = vi.fn(async () => ({ ok: true, json: async () => account }))
    render(<InvoiceAccountPanel authFetch={authFetch} invoiceId={10} />)
    // Totals/status now live in the viewer's side panel; this component renders
    // only the itemized receipts + returns.
    await waitFor(() => expect(screen.getByText('Payments Received')).toBeInTheDocument())
    expect(screen.getByText('UPI')).toBeInTheDocument()          // payment row method
    expect(screen.getByText('₹200')).toBeInTheDocument()         // payment amount
    expect(screen.getByText('Returns (Credit Notes)')).toBeInTheDocument()
    expect(screen.getByText('CN-1')).toBeInTheDocument()         // return row
  })

  it('renders nothing when the account cannot be loaded', async () => {
    const authFetch = vi.fn(async () => ({ ok: false, json: async () => ({}) }))
    const { container } = render(<InvoiceAccountPanel authFetch={authFetch} invoiceId={10} />)
    await waitFor(() => expect(container.querySelector('.no-print')).toBeNull())
  })
})
