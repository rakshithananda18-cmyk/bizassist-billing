import React from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'

const state = vi.hoisted(() => ({
  product: { id: 31, name: 'Rice 5kg', sku: 'RC5', selling_price: 100, wholesale_price: 90, stock_qty: 20, is_active: true },
  products: [], mobile: true,
  user: { id: 7, username: 'price-test-owner', role: 'enterprise', public_id: 'BA-PRICE' },
  authFetch: vi.fn(),
}))

vi.mock('../contexts/AuthContext', () => ({
  useAuth: () => ({ authFetch: state.authFetch, user: state.user, profile: {}, networkMode: 'local' }),
  useBusinessConfig: () => ({ config: {}, attributesSchema: [], t: (_key, fallback) => fallback }),
}))
vi.mock('../contexts/ConfirmContext', () => ({ useConfirm: () => async () => true }))
vi.mock('../layouts/AppLayout', () => ({ default: ({ children }) => <>{children}</> }))
vi.mock('../hooks/useBillingProfile', () => ({ useBillingProfile: () => ({ profile: { entry_mode: 'search', line_fields: [] } }) }))
vi.mock('../hooks/usePageLifecycle', () => ({ usePageLifecycle: () => ({ blocker: null }) }))
vi.mock('../sync/syncManager', () => ({ syncManager: { pending: async () => [], flushOutbox: async () => ({ sent: 0 }), queue: vi.fn() } }))
vi.mock('../hooks/usePaymentFlow', () => ({ default: () => ({ showPaymentPopup: false }) }))
vi.mock('../components/sales/PosTopBar', () => ({ default: () => null }))
vi.mock('../components/sales/CheckoutModal', () => ({ default: () => null }))
vi.mock('../components/sales/TotalBreakupModal', () => ({ default: () => null }))
vi.mock('../components/sales/PrintReceiptModal', () => ({ default: () => null }))
vi.mock('../components/sales/ThermalReceipt', () => ({ default: () => null }))

import Sales from '../pages/Sales'

let paneVisibility
beforeEach(() => {
  state.products = [state.product]
  state.mobile = true
  vi.stubGlobal('matchMedia', vi.fn(query => ({
    matches: state.mobile && query === 'screen and (max-width: 600px)', media: query,
    addEventListener() {}, removeEventListener() {},
  })))
  // jsdom does not apply viewport media queries. Apply the phone pane rule so
  // visibility assertions exercise a picker launched from the Products pane.
  paneVisibility = document.createElement('style')
  paneVisibility.textContent = '.sales-counter[data-mobile-pane="products"] .pos-cart-wrapper { display: none !important; }'
  document.head.appendChild(paneVisibility)
  state.authFetch.mockReset().mockImplementation(async path => ({
    ok: true,
    json: async () => path === '/settings' ? { general: { realtime_sync_sales: false }, transactions: {}, inventory: {} }
      : path === '/shifts/current' ? { shift: { id: 1, offline: true } }
        : path.split('?')[0] === '/products' ? state.products
          : path === '/products/31/stock' ? { batches: [] } : [],
  }))
})
afterEach(() => {
  cleanup()
  paneVisibility.remove()
  vi.unstubAllGlobals()
})

describe('Mobile catalogue pricing', () => {
  it('shows and applies a multi-price picker before opening the hidden Current bill pane', async () => {
    const { container } = render(<MemoryRouter><Sales /></MemoryRouter>)
    fireEvent.click(await screen.findByRole('button', { name: 'Add Rice 5kg to bill' }))
    const title = await screen.findByText('Price Selection — Rice 5kg')
    const picker = title.closest('.modal')
    expect(container.querySelector('.sales-counter')).toHaveAttribute('data-mobile-pane', 'products')
    expect(picker).toBeVisible()

    fireEvent.click(within(picker).getByText('Wholesale Price'))
    expect(screen.queryByText('Price Selection — Rice 5kg')).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /Current bill/ }))
    expect(screen.getByRole('spinbutton', { name: 'Rate for Rice 5kg' })).toHaveValue(90)
  })

  it('keeps every matching product reachable in mobile catalogue searches', async () => {
    state.products = [
      ...Array.from({ length: 11 }, (_, index) => ({ ...state.product, id: index + 100, name: `Rice pack ${index + 1}`, sku: `RICE${index + 1}` })),
      { ...state.product, id: 200, name: 'Sunflower Oil', sku: 'OIL1' },
    ]
    render(<MemoryRouter><Sales /></MemoryRouter>)
    await screen.findByRole('button', { name: 'Add Sunflower Oil to bill' })
    fireEvent.change(screen.getByRole('combobox', { name: 'Search products or scan barcode' }), { target: { value: 'Rice' } })
    await waitFor(() => expect(screen.queryByRole('button', { name: 'Add Sunflower Oil to bill' })).not.toBeInTheDocument())
    expect(screen.getAllByRole('button', { name: /^Add Rice pack \d+ to bill$/ })).toHaveLength(11)
    expect(screen.getByRole('button', { name: 'Add Rice pack 11 to bill' })).toBeInTheDocument()
    expect(screen.queryByRole('listbox')).not.toBeInTheDocument()
  })

  it('keeps the desktop autocomplete limited to eight ranked results', async () => {
    state.mobile = false
    state.products = Array.from({ length: 11 }, (_, index) => ({ ...state.product, id: index + 100, name: `Rice pack ${index + 1}`, sku: `RICE${index + 1}` }))
    render(<MemoryRouter><Sales /></MemoryRouter>)
    const search = screen.getByRole('combobox', { name: 'Search products or scan barcode' })
    await waitFor(() => expect(search).not.toBeDisabled())
    fireEvent.change(search, { target: { value: 'Rice' } })
    const autocomplete = await screen.findByRole('listbox')
    expect(within(autocomplete).getAllByRole('option')).toHaveLength(8)
    expect(screen.queryByRole('button', { name: 'Add Rice pack 11 to bill' })).not.toBeInTheDocument()
  })
})
