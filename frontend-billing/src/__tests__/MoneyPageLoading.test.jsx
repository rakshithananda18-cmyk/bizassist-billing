import React from 'react'
import { afterEach, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'

const auth = vi.hoisted(() => ({ fetch: vi.fn() }))
vi.mock('../contexts/AuthContext', () => ({ useAuth: () => ({ user: { id: 1, role: 'owner' }, authFetch: auth.fetch }) }))
vi.mock('../layouts/AppLayout', () => ({ default: ({ children }) => <main>{children}</main> }))
vi.mock('../components/common/HeaderSearchSlot', () => ({ default: () => null }))
vi.mock('../hooks/useInvoiceActions', () => ({ default: () => ({ modals: null }) }))
import Money from '../pages/Money'

afterEach(cleanup)

it('distinguishes loading and an unavailable account list from no customers', async () => {
  let reject
  auth.fetch.mockReset().mockReturnValueOnce(new Promise((_resolve, fail) => { reject = fail }))
  render(<MemoryRouter><Money /></MemoryRouter>)
  expect(screen.getByRole('status')).toHaveTextContent('Loading customer accounts')
  expect(screen.queryByText('No customers found')).not.toBeInTheDocument()
  reject(new Error('Network unavailable'))
  await screen.findByRole('button', { name: 'Retry customers' })
  expect(screen.queryByText('No customers found')).not.toBeInTheDocument()
  auth.fetch.mockResolvedValue({ ok: true, json: async () => [{ id: 1, name: 'Fixture customer', outstanding_balance: 25 }] })
  fireEvent.click(screen.getByRole('button', { name: 'Retry customers' }))
  await screen.findByText('Fixture customer')
})
