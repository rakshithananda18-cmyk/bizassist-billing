import React from 'react'
import { act, cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { MemoryRouter, useNavigate } from 'react-router-dom'
import Reports from '../pages/Reports'

const authFetch = vi.fn()
vi.mock('../contexts/AuthContext', () => ({ useAuth: () => ({ authFetch }) }))
vi.mock('../layouts/AppLayout', () => ({ default: ({ children }) => <div>{children}</div> }))
vi.mock('../components/common/CustomSelect', () => ({ default: ({ children, ...props }) => <select {...props}>{children}</select> }))
vi.mock('../components/reports/RegisterView', () => ({ default: ({ reportData }) => <pre data-testid="rows">{JSON.stringify(reportData)}</pre> }))

const response = data => ({ ok: true, headers: { get: () => null }, json: async () => data })
const deferred = () => { let resolve; const promise = new Promise(done => { resolve = done }); return { promise, resolve } }
function Navigation() {
  const navigate = useNavigate()
  return <button onClick={() => navigate('/reports?tab=party-ledger')}>Open party deep link</button>
}
function show(entry = '/reports') {
  return render(<MemoryRouter initialEntries={[entry]}><Navigation /><Reports /></MemoryRouter>)
}
beforeEach(() => { localStorage.clear(); authFetch.mockReset().mockResolvedValue(response([])) })
afterEach(cleanup)

describe('Reports navigation and request ownership', () => {
  it('follows router deep links both at mount and while the page remains mounted', async () => {
    show('/reports?tab=gst')
    expect(screen.getByRole('heading', { level: 2, name: /GST Report/ })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Open party deep link' }))
    expect(await screen.findByRole('heading', { level: 2, name: /Party Ledger/ })).toBeInTheDocument()
    expect(authFetch).toHaveBeenCalledWith('/billing/customers', expect.objectContaining({ signal: expect.any(AbortSignal) }))
  })

  it('ignores an older report response after another report is selected', async () => {
    const first = deferred()
    authFetch.mockReturnValueOnce(first.promise).mockResolvedValueOnce(response([{ reference: 'CURRENT-GST' }]))
    show()
    fireEvent.click(screen.getByRole('tab', { name: /Sales Register/ }))
    fireEvent.click(screen.getByRole('tab', { name: /GST Report/ }))
    expect(await screen.findByTestId('rows')).toHaveTextContent('CURRENT-GST')
    await act(async () => first.resolve(response([{ reference: 'STALE-SALES' }])))
    expect(screen.getByRole('heading', { level: 2, name: /GST Report/ })).toBeInTheDocument()
    expect(screen.getByTestId('rows')).not.toHaveTextContent('STALE-SALES')
  })

  it('does not relabel an in-flight result with a newly selected date range', async () => {
    const pending = deferred()
    authFetch.mockReturnValueOnce(pending.promise)
    show()
    fireEvent.click(screen.getByRole('tab', { name: /Sales Register/ }))
    fireEvent.change(screen.getByLabelText('From date'), { target: { value: '2026-01-01' } })
    await act(async () => pending.resolve(response([{ reference: 'OLD-PERIOD' }])))
    expect(screen.queryByTestId('rows')).not.toBeInTheDocument()
    expect(screen.getByText('Run Sales Register')).toBeInTheDocument()
  })

  it('can switch the mobile report category after a report has already been selected', () => {
    show('/reports?tab=gst')
    const categories = screen.getByRole('tablist', { name: 'Report categories' })
    const books = within(categories).getByRole('tab', { name: 'Books & Ledgers' })
    fireEvent.click(books)
    expect(books).toHaveAttribute('aria-selected', 'true')
    expect(screen.getByRole('option', { name: 'Party Ledger' })).toBeInTheDocument()
  })

  it('ignores a late customer list after changing the party type to vendors', async () => {
    const customers = deferred()
    authFetch.mockReturnValueOnce(customers.promise).mockResolvedValueOnce(response([{ id: 2, name: 'Current Vendor' }]))
    show('/reports?tab=party-ledger')
    fireEvent.click(screen.getByRole('button', { name: 'vendor' }))
    expect(await screen.findByRole('option', { name: 'Current Vendor' })).toBeInTheDocument()
    await act(async () => customers.resolve(response([{ id: 1, name: 'Late Customer' }])))
    expect(screen.queryByRole('option', { name: 'Late Customer' })).not.toBeInTheDocument()
  })
})
