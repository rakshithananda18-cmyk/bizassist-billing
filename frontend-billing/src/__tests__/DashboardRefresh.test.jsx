import React from 'react'
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { MemoryRouter, useLocation } from 'react-router-dom'
const hooks = vi.hoisted(() => ({ resume: null, fetch: vi.fn(), userId: 1 }))
vi.mock('../contexts/AuthContext', () => ({ useAuth: () => ({
  authFetch: hooks.fetch, user: { id: hooks.userId }, profile: { business_name: 'QA workspace' }, settings: { general: { privacy_mode: true } },
}) }))
vi.mock('../layouts/AppLayout', () => ({ default: ({ children }) => <main>{children}</main> }))
vi.mock('../components/ActivityFeed', () => ({ default: () => null }))
vi.mock('../components/common/HeaderSearchSlot', () => ({ default: () => null }))
vi.mock('../components/invoice/InvoiceViewerModal', () => ({ default: ({ invoiceNo }) => invoiceNo ? <div role="dialog" aria-label={`Invoice ${invoiceNo}`} /> : null }))
vi.mock('../hooks/usePageLifecycle', () => ({ usePageLifecycle: ({ onResume }) => { hooks.resume = onResume; return { isRefreshing: false } } }))
import Dashboard from '../pages/Dashboard'
afterEach(() => { cleanup(); hooks.userId = 1 })
const response = data => ({ ok: true, json: async () => data })
it('keeps an explicit temporary chart reveal through a background refresh', async () => {
  hooks.fetch.mockImplementation(async path => response(path === '/payments?limit=5' ? [] : path === '/dashboard-charts'
    ? { monthly_revenue: [], aging_overview: [], top_products: [] } : {}))
  render(<MemoryRouter><Dashboard /></MemoryRouter>)
  fireEvent.click(await screen.findByRole('button', { name: 'Show charts for this visit' }))
  expect(screen.getByText('Monthly Revenue Trajectory')).toBeInTheDocument()
  let release
  const pending = new Promise(resolve => { release = resolve })
  hooks.fetch.mockImplementationOnce(() => pending)
  act(() => { hooks.resume() })
  expect(screen.getByText('Monthly Revenue Trajectory')).toBeInTheDocument()
  await act(async () => { release(response({})); await pending })
  await waitFor(() => expect(screen.getByRole('button', { name: 'Hide charts' })).toBeInTheDocument())
})

it('opens invoices and payment history from the new feed actions with the keyboard', async () => {
  hooks.fetch.mockReset().mockImplementation(async path => response(path === '/dashboard-summary'
    ? { recent_invoices: [{ id: 1, invoice_number: 'QA-42', customer_name: 'QA buyer', total_amount: 100 }] }
    : path === '/payments?limit=5' ? [{ type: 'received', amount: 100, method: 'cash', invoice_ref: 'QA-42' }]
    : {}))
  function Location() { return <output data-testid="location">{useLocation().pathname}</output> }
  render(<MemoryRouter initialEntries={['/dashboard']}><Dashboard /><Location /></MemoryRouter>)
  const invoice = await screen.findByRole('button', { name: /Billed to QA buyer/ })
  fireEvent.keyDown(invoice, { key: 'Enter' })
  expect(screen.getByRole('dialog', { name: 'Invoice QA-42' })).toBeInTheDocument()
  fireEvent.keyDown(screen.getByRole('button', { name: /Payment Received/ }), { key: ' ' })
  expect(screen.getByTestId('location')).toHaveTextContent('/parties/payments')
})

it('shows a retry state instead of zero totals when the business summary fails', async () => {
  hooks.fetch.mockReset().mockImplementation(async path => path === '/dashboard-summary'
    ? { ok: false, status: 503 } : response([]))
  render(<MemoryRouter><Dashboard /></MemoryRouter>)
  expect(await screen.findByRole('alert')).toHaveTextContent('Business summary is unavailable')
  expect(screen.queryByRole('button', { name: /Total Revenue/ })).not.toBeInTheDocument()
  hooks.fetch.mockImplementation(async path => response(path === '/dashboard-summary' ? { total_revenue: 100 } : []))
  fireEvent.click(screen.getByRole('button', { name: 'Retry dashboard' }))
  await screen.findByRole('button', { name: /Total Revenue.*₹100/ })
})

it('distinguishes unavailable payment activity from an empty business day', async () => {
  hooks.fetch.mockReset().mockImplementation(async path => path === '/payments?limit=5'
    ? { ok: false, status: 503 } : response({}))
  render(<MemoryRouter><Dashboard /></MemoryRouter>)
  await screen.findByRole('button', { name: 'Retry activity' })
  expect(screen.queryByText('No recent activity')).not.toBeInTheDocument()
})

it('opens actual invoice and purchase routes from the KPI cards', async () => {
  hooks.fetch.mockReset().mockImplementation(async () => response({}))
  function Location() { return <output data-testid="location">{useLocation().pathname}</output> }
  render(<MemoryRouter initialEntries={['/dashboard']}><Dashboard /><Location /></MemoryRouter>)
  fireEvent.click(await screen.findByRole('button', { name: /Total Revenue/ }))
  expect(screen.getByTestId('location')).toHaveTextContent('/parties/invoices')
  fireEvent.click(screen.getByRole('button', { name: /Purchases \(30d\)/ }))
  expect(screen.getByTestId('location')).toHaveTextContent('/stock/purchase')
})

it('ignores an earlier business summary that arrives after switching accounts', async () => {
  let release
  const previous = new Promise(resolve => { release = resolve })
  let first = true
  hooks.fetch.mockReset().mockImplementation(async path => {
    if (path !== '/dashboard-summary') return response([])
    if (first) { first = false; return previous }
    return response({ total_revenue: 2400 })
  })
  const view = () => <MemoryRouter><Dashboard /></MemoryRouter>
  const root = render(view())
  await waitFor(() => expect(hooks.fetch).toHaveBeenCalledWith('/dashboard-summary'))
  hooks.userId = 2
  root.rerender(view())
  await screen.findByRole('button', { name: /Total Revenue.*₹2,400/ })
  await act(async () => { release(response({ total_revenue: 1500 })); await previous })
  expect(screen.queryByRole('button', { name: /Total Revenue.*₹1,500/ })).not.toBeInTheDocument()
})
