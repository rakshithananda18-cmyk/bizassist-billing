// @vitest-environment jsdom
import React from 'react'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
const mocks = vi.hoisted(() => ({ get: vi.fn() }))
vi.mock('../lib/api', () => ({ api: { get: mocks.get } }))
import InvoicePicker from './InvoicePicker'
afterEach(cleanup)

it('cannot pick a returned paid bill for collection and uses the partial-return net due', async () => {
  mocks.get.mockResolvedValue({ invoices: [
    { id: 1, number: 'Returned fixture', total: 100, paid: 100, credited: 40, credit_due: 40, balance_due: 0, lines: [] },
    { id: 2, number: 'Partial return fixture', total: 100, paid: 0, credited: 40, credit_due: 0, balance_due: 60, lines: [] },
  ] })
  const pick = vi.fn()
  render(<InvoicePicker shop={{ id: 1, customer_id: 1, name: 'Fixture shop' }} taskType="payment_collect" onClose={vi.fn()} onPick={pick} />)
  const returned = await screen.findByRole('checkbox', { name: /Returned fixture/ })
  expect(returned.disabled).toBe(true)
  expect(screen.getByText(/credit in Billing/)).toBeTruthy()
  fireEvent.click(screen.getByRole('checkbox', { name: /Partial return fixture/ }))
  fireEvent.click(screen.getByRole('button', { name: 'Use 1' }))
  expect(pick).toHaveBeenCalledWith([expect.objectContaining({ id: 2, balance_due: 60 })])
})
