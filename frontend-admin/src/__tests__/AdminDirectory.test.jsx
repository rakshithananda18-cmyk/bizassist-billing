import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import AdminBusinesses from '../pages/admin/AdminBusinesses'

const auth = vi.hoisted(() => ({ authFetch: vi.fn() }))
vi.mock('../contexts/AuthContext', () => ({ useAuth: () => auth }))
vi.mock('../contexts/DialogContext', () => ({ useDialog: () => ({ showAlert: vi.fn(), showConfirm: vi.fn(), showError: vi.fn() }) }))
const response = data => ({ ok: true, json: async () => data })
const stores = [
  { id: 1, business_name: 'Orchard Grocery', username: 'orchard', bizid: 'BA-ORCHARD', email: 'owner@orchard.test', total_revenue: 900, plan: 'pro', online_last_24h: true, invoice_count: 4, inventory_count: 20 },
  { id: 2, business_name: 'River Traders', username: 'river', bizid: 'BA-RIVER', total_revenue: 1500, needs_attention: true, invoice_count: 5, inventory_count: 12 },
  { id: 3, business_name: 'Hill Retail', username: 'hill', bizid: 'BA-HILL', total_revenue: 0 },
]

beforeEach(() => {
  localStorage.clear()
  auth.authFetch.mockReset().mockImplementation(async url => response(url.endsWith('/deleted-businesses') ? [] : stores))
})
afterEach(cleanup)
const mount = () => render(<MemoryRouter><AdminBusinesses /></MemoryRouter>)

describe('merchant directory work views', () => {
  it('filters only explicit connection and attention signals, and combines the view with account search', async () => {
    mount()
    await screen.findByRole('link', { name: 'Orchard Grocery' })
    await userEvent.click(screen.getByRole('button', { name: /Needs attention/ }))
    expect(screen.getByRole('link', { name: 'River Traders' })).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'Hill Retail' })).toBeNull()
    expect(screen.queryByRole('link', { name: 'Orchard Grocery' })).toBeNull()
    await userEvent.click(screen.getByRole('button', { name: /Reported in 24h/ }))
    expect(screen.getByRole('link', { name: 'Orchard Grocery' })).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'River Traders' })).toBeNull()
    await userEvent.type(screen.getByRole('searchbox', { name: 'Search merchant accounts' }), 'owner@orchard.test')
    expect(screen.getByRole('link', { name: 'Orchard Grocery' })).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Clear Filter' }))
    expect(screen.getByRole('link', { name: 'Hill Retail' })).toBeInTheDocument()
    expect(screen.getByRole('combobox', { name: 'Directory focus' })).toHaveValue('all')
    const hillRow = screen.getByRole('link', { name: 'Hill Retail' }).closest('tr')
    expect(hillRow).toHaveTextContent('No sync reported')
    expect(hillRow).not.toHaveTextContent('Attention')
  })

  it('keeps Open and Inspect visible while retaining the typed-name wipe guard behind More actions', async () => {
    mount()
    const row = (await screen.findByRole('link', { name: 'Orchard Grocery' })).closest('tr')
    expect(within(row).getByRole('link', { name: 'Open' })).toHaveAttribute('href', '/admin/businesses/1')
    expect(within(row).getByRole('button', { name: 'Inspect' })).toBeInTheDocument()
    fireEvent.click(within(row).getByText('More'))
    await userEvent.click(within(row).getByRole('button', { name: 'Wipe', exact: true }))
    const wipe = screen.getByRole('button', { name: 'Wipe Everything' })
    expect(wipe).toBeDisabled()
    await userEvent.type(screen.getByPlaceholderText('Type the business name exactly'), 'Wrong business')
    expect(wipe).toBeDisabled()
    expect(auth.authFetch.mock.calls.some(([, options]) => options?.method === 'DELETE')).toBe(false)
    await userEvent.click(screen.getByRole('button', { name: 'Cancel', exact: true }))
    expect(screen.queryByRole('button', { name: 'Wipe Everything' })).toBeNull()
  })

  it('uses deleted-store counts and retains the last loaded audit records after a refresh failure', async () => {
    let deletedCalls = 0
    auth.authFetch.mockImplementation(async url => url.endsWith('/deleted-businesses')
      ? ++deletedCalls === 1 ? response([
        { id: 9, bizid: 'BA-OLD1', business_name: 'Archived Store', username: 'archived', reason: 'admin_wipe' },
        { id: 10, bizid: 'BA-OLD2', business_name: 'Old Corner Shop', username: 'oldshop', reason: 'admin_wipe' },
      ]) : { ok: false }
      : response(stores))
    mount()
    await screen.findByRole('link', { name: 'Orchard Grocery' })
    await userEvent.click(screen.getByRole('button', { name: /Deleted \/ Wiped Stores/ }))
    await screen.findByText('Archived Store')
    await userEvent.type(screen.getByRole('searchbox', { name: 'Search merchant accounts' }), 'Archived')
    expect(screen.getByRole('status')).toHaveTextContent('Showing 1 of 2 deleted stores')
    await userEvent.click(screen.getByRole('button', { name: 'Refresh directory' }))
    await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent('Showing the last loaded deleted-store records.'))
    expect(screen.getByText('Archived Store')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Retry deleted stores' })).toBeInTheDocument()
  })
})
