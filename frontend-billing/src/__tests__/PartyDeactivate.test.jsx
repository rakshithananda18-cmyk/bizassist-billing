// Deactivating a customer / vendor. The backend already accepted `is_active` on
// PATCH /billing/customers/{id} and /billing/vendors/{id} — only the UI was
// missing, so this covers the seam that was actually absent: the row reflects
// the flag, and the right-click action PATCHes the correct collection.
//
// The action lives in the context menu rather than the row's action rail on
// purpose: the rail is icon-only because text buttons there made Actions the
// widest column in the grid and pushed it past its container.
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import Parties from '../pages/Parties'

const CUSTOMERS = [
  { id: 7, name: 'Dormant Traders', phone: '9000000001', is_active: false, outstanding_balance: 0 },
  { id: 8, name: 'Active Traders', phone: '9000000002', is_active: true, outstanding_balance: 0 },
]

let authFetch
beforeEach(() => {
  authFetch = vi.fn(async (path, opts = {}) => {
    if (opts.method === 'PATCH') return { ok: true, status: 200, json: async () => ({}) }
    if (path.startsWith('/billing/customers')) {
      return { ok: true, status: 200, json: async () => ({ items: CUSTOMERS, total: 2 }) }
    }
    return { ok: true, status: 200, json: async () => ({ items: [], total: 0 }) }
  })
})

// Passthrough shell — PageShell renders AppLayout, which needs the lock and
// nav contexts. None of that is under test here.
vi.mock('../layouts/AppLayout', () => ({
  default: ({ children }) => <div>{children}</div>,
}))
vi.mock('../contexts/AuthContext', () => ({
  useAuth: () => ({ authFetch, user: { id: 1, role: 'owner' }, settings: {} }),
}))
vi.mock('../contexts/ConfirmContext', () => ({ useConfirm: () => async () => true }))

const renderPage = () => render(<MemoryRouter><Parties /></MemoryRouter>)

describe('party deactivation', () => {
  it('tags an inactive party and dims its row', async () => {
    renderPage()
    const name = await screen.findByText('Dormant Traders')
    expect(screen.getByText('Inactive')).toBeInTheDocument()
    expect(name.closest('tr')).toHaveClass('row-inactive')

    // The active one carries neither.
    const active = screen.getByText('Active Traders')
    expect(active.closest('tr')).not.toHaveClass('row-inactive')
  })

  it('deactivates an active customer from the row menu', async () => {
    renderPage()
    const row = (await screen.findByText('Active Traders')).closest('tr')
    fireEvent.contextMenu(row)

    fireEvent.click(await screen.findByText('Deactivate Customer'))

    await waitFor(() => {
      const patch = authFetch.mock.calls.find(([, o]) => o?.method === 'PATCH')
      expect(patch).toBeTruthy()
      expect(patch[0]).toBe('/billing/customers/8')
      expect(JSON.parse(patch[1].body)).toEqual({ is_active: false })
    })
  })

  it('offers reactivation for an inactive one', async () => {
    renderPage()
    const row = (await screen.findByText('Dormant Traders')).closest('tr')
    fireEvent.contextMenu(row)

    fireEvent.click(await screen.findByText('Reactivate Customer'))

    await waitFor(() => {
      const patch = authFetch.mock.calls.find(([, o]) => o?.method === 'PATCH')
      expect(JSON.parse(patch[1].body)).toEqual({ is_active: true })
    })
  })
})
