import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import AdminBusinessDetail from '../pages/admin/AdminBusinessDetail'
import AdminBusinesses from '../pages/admin/AdminBusinesses'
import { DialogProvider } from '../contexts/DialogContext'

const auth = vi.hoisted(() => ({ authFetch: vi.fn() }))
vi.mock('../contexts/AuthContext', () => ({ useAuth: () => auth }))
const business = { id: 7, username: 'merchant', business_name: 'Seven Traders', total_revenue: 25, invoice_count: 1, inventory_count: 0, upload_count: 0 }
const response = body => ({ ok: true, json: async () => body })
beforeEach(() => { auth.authFetch.mockReset() })
afterEach(cleanup)

it('loads diagnostics only for the business being viewed', async () => {
  auth.authFetch.mockImplementation(async url => {
    const path = new URL(url, window.location.origin)
    if (path.pathname.endsWith('/businesses/7')) return response(business)
    if (path.pathname.endsWith('/sync-doctor')) return response([{ business_id: 7, health: 'green' }])
    if (path.pathname.endsWith('/server-log')) return response({ lines: [] })
    return response({})
  })
  render(<DialogProvider><MemoryRouter initialEntries={['/admin/businesses/7']}><Routes><Route path="/admin/businesses/:id" element={<AdminBusinessDetail />} /></Routes></MemoryRouter></DialogProvider>)
  await screen.findByText('Seven Traders')
  await waitFor(() => expect(auth.authFetch.mock.calls.some(([url]) => String(url).includes('/server-log?'))).toBe(true))
  const urls = auth.authFetch.mock.calls.map(([url]) => new URL(url, window.location.origin))
  expect(urls.some(url => url.pathname === '/admin/businesses')).toBe(false)
  expect(urls.find(url => url.pathname === '/admin/sync-doctor')?.searchParams.get('business_id')).toBe('7')
})

it('requests another inspector page and keeps the already loaded rows', async () => {
  auth.authFetch.mockImplementation(async url => {
    const path = new URL(url, window.location.origin)
    if (path.pathname.endsWith('/businesses')) return response([business])
    if (path.pathname.endsWith('/business-details/7') && path.searchParams.has('section')) return response({ invoices: [{ invoice_id: 'PAGE-TWO', amount: 20 }], has_more: false })
    return response({ ...business, uploads: [], inventory: [], payments: [], chat_history: [], invoices: [{ invoice_id: 'PAGE-ONE', amount: 5 }], pagination: { sections: { invoices: true } } })
  })
  render(<DialogProvider><MemoryRouter><AdminBusinesses /></MemoryRouter></DialogProvider>)
  fireEvent.click(await screen.findByRole('button', { name: 'Inspect' }))
  fireEvent.click(await screen.findByRole('button', { name: 'Load more invoices' }))
  await waitFor(() => expect(screen.queryByRole('button', { name: 'Load more invoices' })).toBeNull())
  expect(screen.getByText(/Invoices & Sales \(2\)/)).toBeInTheDocument()
  expect(screen.getByText('PAGE-ONE')).toBeInTheDocument()
  expect(screen.getByText('PAGE-TWO')).toBeInTheDocument()
  const page = auth.authFetch.mock.calls.map(([url]) => new URL(url, window.location.origin)).find(url => url.searchParams.has('section'))
  expect(page.searchParams.get('offset')).toBe('1')
  expect(page.searchParams.get('limit')).toBe('50')
})
