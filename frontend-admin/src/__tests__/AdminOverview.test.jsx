import React from 'react'
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import AdminDashboard from '../pages/admin/AdminDashboard'

const state = vi.hoisted(() => ({ fetch: vi.fn(), confirm: vi.fn(), alert: vi.fn(), error: vi.fn() }))
vi.mock('../contexts/AuthContext', () => ({ useAuth: () => ({ authFetch: state.fetch, adminUser: { username: 'operator' } }) }))
vi.mock('../contexts/DialogContext', () => ({ useDialog: () => ({ showConfirm: state.confirm, showAlert: state.alert, showError: state.error }) }))
const response = data => ({ ok: true, json: async () => data })
const businesses = [
  { id: 7, business_name: 'Zara Stores', bizid: 'BA-ZARA', total_revenue: 1200, upload_count: 2, inventory_count: 20, invoice_count: 4 },
  { id: 3, business_name: 'Asha Retail', bizid: 'BA-ASHA', total_revenue: 800, upload_count: 3, inventory_count: 8, invoice_count: 2 },
]
beforeEach(() => {
  vi.clearAllMocks()
  state.confirm.mockResolvedValue(false)
  state.fetch.mockImplementation(async (url, options) => {
    if (url.endsWith('/admin/businesses')) return response(businesses)
    if (url.endsWith('/admin/router-mode')) return response({ mode: options?.method === 'POST' ? JSON.parse(options.body).mode : 'legacy' })
    return response({ message: 'Completed' })
  })
})
afterEach(cleanup)

describe('operations overview', () => {
  it('shows truthful aggregate data and links real business records to their workspaces', async () => {
    render(<MemoryRouter><AdminDashboard /></MemoryRouter>)
    await screen.findByText('₹2,000')
    expect(screen.getByText('Registered Businesses').closest('.overview-stat')).toHaveTextContent('2')
    expect(screen.getByText('Files uploaded').closest('.overview-stat')).toHaveTextContent('5')
    const directory = screen.getByRole('region', { name: 'Business directory' })
    const rows = within(directory).getAllByRole('row')
    expect(rows[1]).toHaveTextContent('Asha Retail')
    expect(rows[2]).toHaveTextContent('Zara Stores')
    expect(within(directory).getByRole('link', { name: 'Asha Retail' })).toHaveAttribute('href', '/admin/businesses/3')
    expect(screen.getByRole('link', { name: /Follow adoption/ })).toHaveAttribute('href', '/admin/metrics')
    expect(screen.getByRole('link', { name: /Check diagnostics/ })).toHaveAttribute('href', '/admin/health')
    expect(screen.queryByText('active sandboxes')).not.toBeInTheDocument()
  })

  it('keeps unreported business counts separate from zero', async () => {
    state.fetch.mockImplementation(async url => response(url.endsWith('/admin/businesses')
      ? [{ id: 1, business_name: 'Limited record', total_revenue: 0, upload_count: 0 }] : { mode: 'legacy' }))
    render(<MemoryRouter><AdminDashboard /></MemoryRouter>)
    const row = (await screen.findByText('Limited record')).closest('tr')
    expect(within(row).getAllByText('—')).toHaveLength(2)
    expect(row).toHaveTextContent('BizID unavailable')
  })

  it('keeps maintenance and routing changes behind their existing confirmations', async () => {
    render(<MemoryRouter><AdminDashboard /></MemoryRouter>)
    const cache = await screen.findByRole('button', { name: 'System Cache' })
    await userEvent.click(cache)
    expect(cache).toHaveAttribute('aria-expanded', 'true')
    await userEvent.click(screen.getByRole('button', { name: 'Wipe All Business Data' }))
    expect(state.confirm).toHaveBeenCalledWith(expect.stringContaining('permanently delete'))
    expect(state.fetch.mock.calls.some(([, opts]) => opts?.method === 'DELETE')).toBe(false)

    await userEvent.click(screen.getByRole('button', { name: /New AI Router/ }))
    expect(state.fetch.mock.calls.some(([, opts]) => opts?.method === 'POST')).toBe(false)
    state.confirm.mockResolvedValue(true)
    await userEvent.click(screen.getByRole('button', { name: /New AI Router/ }))
    await waitFor(() => expect(state.fetch.mock.calls.some(([, opts]) => opts?.method === 'POST')).toBe(true))
    const request = state.fetch.mock.calls.find(([, opts]) => opts?.method === 'POST')
    expect(request[0]).toMatch(/\/admin\/router-mode$/)
    expect(JSON.parse(request[1].body)).toEqual({ mode: 'new' })
  })

  it('closes maintenance tools with Escape without running an operation', async () => {
    render(<MemoryRouter><AdminDashboard /></MemoryRouter>)
    const cache = await screen.findByRole('button', { name: 'System Cache' })
    await userEvent.click(cache)
    fireEvent.keyDown(window, { key: 'Escape' })
    expect(cache).toHaveAttribute('aria-expanded', 'false')
    expect(screen.queryByRole('button', { name: 'Wipe All Business Data' })).not.toBeInTheDocument()
    expect(state.fetch.mock.calls.some(([, opts]) => ['POST', 'DELETE'].includes(opts?.method))).toBe(false)
  })
})
