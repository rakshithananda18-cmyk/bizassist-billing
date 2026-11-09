import React from 'react'
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const state = vi.hoisted(() => ({
  user: { id: 999999, role: 'owner', is_demo: true }, framed: true, fetch: vi.fn(),
}))
vi.mock('../demo/guidedTourRuntime', async importOriginal => {
  const actual = await importOriginal()
  return { ...actual, isEmbeddedGuidedTour: (location = window.location, framed = state.framed) => actual.isEmbeddedGuidedTour(location, framed) }
})
vi.mock('../contexts/AuthContext', () => ({
  useAuth: () => ({ user: state.user, authFetch: state.fetch, profile: {}, settings: { general: {}, inventory: {}, transactions: {} } }),
  useBusinessConfig: () => ({ config: {}, attributesSchema: [] }),
}))
vi.mock('../contexts/ConfirmContext', () => ({ useConfirm: () => vi.fn() }))
vi.mock('../layouts/AppLayout', () => ({ default: ({ children }) => <main>{children}</main> }))
vi.mock('../components/common/HeaderSearchSlot', () => ({ default: () => null }))
vi.mock('../hooks/usePageLifecycle', () => ({ usePageLifecycle: () => ({ isRefreshing: false }) }))

import { isProtectedTourPreview } from '../demo/tourPrivacy'
import Dashboard from '../pages/Dashboard'
import Stock from '../pages/Stock'
import PriceSelectorModal from '../components/sales/PriceSelectorModal'

const response = data => ({ ok: true, json: async () => data })
beforeEach(() => {
  window.history.replaceState({}, '', '/?demo=1&embed=1&tour=1')
  state.user = { id: 999999, role: 'owner', is_demo: true }
  state.framed = true
  state.fetch.mockReset()
})
afterEach(() => { cleanup(); window.history.replaceState({}, '', '/'); vi.restoreAllMocks() })

describe('public tour redaction', () => {
  it('requires an embedded sample tour and never protects a real signed-in store', () => {
    const tour = { search: '?demo=1&embed=1&tour=1' }
    expect(isProtectedTourPreview({ is_demo: true }, tour, true)).toBe(true)
    expect(isProtectedTourPreview({ is_demo: true }, tour, false)).toBe(false)
    expect(isProtectedTourPreview({ is_demo: false }, tour, true)).toBe(false)
    expect(isProtectedTourPreview({ is_demo: true }, { search: '?demo=1' }, true)).toBe(false)
    expect(isProtectedTourPreview({ is_demo: true }, { search: '?embed=1&tour=1' }, true)).toBe(false)
  })

  it('omits private price rows while keeping Standard Price functional', () => {
    const options = [
      { label: 'Standard Price', price: 620, formatted_date: 'Base Product' },
      { label: 'Wholesale Price', price: 589.45, formatted_date: 'Private wholesale date' },
      { label: 'Distributor Price', price: 558.89, formatted_date: 'Private distributor date' },
    ]
    const select = vi.fn()
    const props = { options, productName: 'Sample Rice', selectedIndex: 0, onSelect: select, onHoverIndex: vi.fn(), onClose: vi.fn() }
    const view = render(<PriceSelectorModal {...props} protectTour />)
    expect(screen.getByText('Full workflow available after sign-in.')).toBeInTheDocument()
    expect(view.container).not.toHaveTextContent('Wholesale Price')
    expect(view.container).not.toHaveTextContent('589.45')
    expect(view.container).not.toHaveTextContent('Private distributor date')
    fireEvent.click(screen.getByText('Standard Price'))
    expect(select).toHaveBeenCalledWith(620, 'Standard Price')
    view.rerender(<PriceSelectorModal {...props} />)
    expect(screen.getByText('Wholesale Price')).toBeInTheDocument()
    expect(view.container).toHaveTextContent('589.45')
    fireEvent.click(screen.getByText('Wholesale Price'))
    expect(select).toHaveBeenLastCalledWith(589.45, 'Wholesale Price')
  })

  it('does not request or mount advanced analytics in the tour, restoring them for a real store', async () => {
    state.fetch.mockImplementation(async path => response(path === '/dashboard-summary'
      ? { total_revenue: 12500, gross_margin: 37.83 }
      : path === '/dashboard-charts' ? { monthly_revenue: [], aging_overview: [], top_products: [] } : []))
    const view = render(<MemoryRouter><Dashboard /></MemoryRouter>)
    await screen.findByText('Full workflow available after sign-in.')
    const margin = screen.getByText('Gross Margin').closest('.vsummary-card')
    expect(margin).not.toHaveTextContent('37.83')
    expect(state.fetch).not.toHaveBeenCalledWith('/dashboard-charts')
    expect(screen.queryByText('Monthly Revenue Trajectory')).not.toBeInTheDocument()
    expect(screen.getByText('₹12,500')).toBeInTheDocument()

    state.user = { id: 7, role: 'owner', is_demo: false }
    view.rerender(<MemoryRouter><Dashboard /></MemoryRouter>)
    await screen.findByText('Monthly Revenue Trajectory')
    expect(state.fetch).toHaveBeenCalledWith('/dashboard-charts')
    expect(screen.getByText('37.83%')).toBeInTheDocument()
  })

  it('keeps catalogue basics readable while excluding cost and margin values and formula titles', async () => {
    const product = { id: 1, name: 'Sample Catalogue Item', sku: 'SAMPLE-1', quantity: 18, stock_qty: 18,
      selling_price: 500, mrp: 600, cost_price: 321.67, wholesale_price: 459.01, distributor_price: 429.02, is_active: true }
    state.fetch.mockImplementation(async path => response(path.startsWith('/billing/products')
      ? { items: [product], total: 1, page: 1, limit: 200 } : []))
    const view = render(<MemoryRouter><Stock embedded /></MemoryRouter>)
    fireEvent.click(screen.getByRole('button', { name: 'Catalogue', exact: true }))
    const row = (await screen.findByText('Sample Catalogue Item')).closest('tr')
    expect(row).toHaveTextContent('18')
    expect(row).toHaveTextContent('500.00')
    expect(row).not.toHaveTextContent('321.67')
    expect(row).not.toHaveTextContent('459.01')
    expect(row).not.toHaveTextContent('429.02')
    expect(view.container.querySelector('[title="Return on cost = (Sell−Cost)/Cost"]')).toBeNull()
    expect(within(row).getAllByRole('img', { name: 'Value available after sign-in' })).toHaveLength(7)

    state.user = { id: 7, role: 'owner', is_demo: false }
    view.rerender(<MemoryRouter><Stock embedded /></MemoryRouter>)
    await waitFor(() => expect(row).toHaveTextContent('321.67'))
    expect(row).toHaveTextContent('459.01')
    expect(view.container.querySelector('[title="Return on cost = (Sell−Cost)/Cost"]')).not.toBeNull()
  })
})
