import React from 'react'
import { afterEach, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import RecordPaymentModal from '../components/payments/RecordPaymentModal'

afterEach(cleanup)
const draw = type => render(<RecordPaymentModal
  form={{ type, date: '2026-10-29', invoice_ref: '', amount: '', method: 'Cash', note: '' }}
  setField={vi.fn()} onSubmit={vi.fn()} onClose={vi.fn()} submitting={false} />)

it('does not offer an actionable supplier-payment choice', () => {
  draw('received')
  fireEvent.click(screen.getByRole('button', { name: 'Received (from customer)' }))
  expect(screen.getByRole('option', { name: 'Supplier payments — unavailable' })).toBeDisabled()
  expect(screen.getByText(/This form records customer receipts/)).toBeInTheDocument()
})

it('cannot submit a stale unsupported supplier-payment form', () => {
  draw('made')
  expect(screen.getByRole('button', { name: /Record Payment/ })).toBeDisabled()
})
