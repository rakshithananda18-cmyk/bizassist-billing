import React from 'react'
import { afterEach, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'

const auth = vi.hoisted(() => ({ fetch: vi.fn() }))
vi.mock('../contexts/AuthContext', () => ({ useAuth: () => ({
  authFetch: auth.fetch, user: { id: 1, role: 'owner' }, settings: {},
}) }))
vi.mock('../contexts/ConfirmContext', () => ({ useConfirm: () => vi.fn() }))
vi.mock('../layouts/AppLayout', () => ({ default: ({ children }) => <main>{children}</main> }))
import Parties from '../pages/Parties'
import Payments from '../pages/Payments'

afterEach(cleanup)

it.each([
  ['contacts', Parties, '/billing/customers?per_page=500', 'Contacts are unavailable', 'Retry contacts'],
  ['transactions', Payments, '/billing/payments', 'Transactions are unavailable', 'Retry transactions'],
])('keeps failed %s reads distinct from empty lists and supports retry', async (_name, Page, failedPath, message, retry) => {
  auth.fetch.mockReset().mockImplementation(async path => path === failedPath
    ? { ok: false, status: 503 } : { ok: true, json: async () => [] })
  render(<MemoryRouter><Page /></MemoryRouter>)
  expect(await screen.findByRole('alert')).toHaveTextContent(message)
  auth.fetch.mockResolvedValue({ ok: true, json: async () => [] })
  fireEvent.click(screen.getByRole('button', { name: retry }))
  await waitFor(() => expect(screen.queryByRole('alert')).not.toBeInTheDocument())
  expect(auth.fetch.mock.calls.filter(([path]) => path === failedPath)).toHaveLength(2)
})
