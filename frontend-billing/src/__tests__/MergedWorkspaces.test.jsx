// ============================================================================
// MergedWorkspaces.test.jsx — Parties (Contacts+Payments) and Stock
// (Inventory+Purchases) combined pages: path-route tab selection (/parties/payments),
// legacy ?tab= support, lazy single-mount of the active view, and cashier
// gating of the Purchase Bills tab.
// ============================================================================
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import { MemoryRouter, Routes, Route } from 'react-router-dom'
import Khata from '../pages/Khata'
import Godown from '../pages/Godown'

// Passthrough layout — avoids pulling in nav/sidebar internals.
vi.mock('../layouts/AppLayout', () => ({
  default: ({ children, title }) => <div data-testid="layout" data-title={title}>{children}</div>,
}))

// The heavy views themselves are not under test here — stub them so the tabs
// and mounting logic are what's exercised. Each stub renders the headerTabs
// it receives, mirroring the real pages (workspace tabs live INSIDE the
// page's own header row).
vi.mock('../pages/Parties', () => ({ default: ({ headerTabs }) => <div>PARTIES_VIEW{headerTabs}</div> }))
vi.mock('../pages/Payments', () => ({ default: ({ headerTabs }) => <div>PAYMENTS_VIEW{headerTabs}</div> }))
vi.mock('../pages/Stock', () => ({ default: ({ headerTabs }) => <div>STOCK_VIEW{headerTabs}</div> }))
vi.mock('../pages/Purchases', () => ({ default: ({ headerTabs }) => <div>PURCHASES_VIEW{headerTabs}</div> }))

let mockUser = { id: 1, role: 'owner' }
vi.mock('../contexts/AuthContext', () => ({
  useAuth: () => ({ user: mockUser }),
}))

beforeEach(() => {
  localStorage.clear()
  mockUser = { id: 1, role: 'owner' }
})

// Register base + :tab routes so the canonicalizing redirect can land.
const renderAt = (ui, base, path) => render(
  <MemoryRouter initialEntries={[path]}>
    <Routes>
      <Route path={base} element={ui} />
      <Route path={`${base}/:tab`} element={ui} />
    </Routes>
  </MemoryRouter>
)

describe('Parties (Contacts & Payments workspace)', () => {
  it('defaults to the Contacts view and mounts ONLY it', async () => {
    renderAt(<Khata />, '/parties', '/parties')
    expect(await screen.findByText('PARTIES_VIEW')).toBeInTheDocument()
    expect(screen.queryByText('PAYMENTS_VIEW')).not.toBeInTheDocument()
    expect(screen.getByText('Contacts & Dues')).toBeInTheDocument()
    expect(screen.getByText('Transactions')).toBeInTheDocument()
  })

  it('serves /parties/payments as a real route', async () => {
    renderAt(<Khata />, '/parties', '/parties/payments')
    expect(await screen.findByText('PAYMENTS_VIEW')).toBeInTheDocument()
    expect(screen.queryByText('PARTIES_VIEW')).not.toBeInTheDocument()
  })

  it('still honors legacy ?tab=payments deep links', async () => {
    renderAt(<Khata />, '/parties', '/parties?tab=payments')
    expect(await screen.findByText('PAYMENTS_VIEW')).toBeInTheDocument()
  })

  it('falls back to the remembered tab on bare /parties', async () => {
    localStorage.setItem('khata_last_tab', 'payments')
    renderAt(<Khata />, '/parties', '/parties')
    expect(await screen.findByText('PAYMENTS_VIEW')).toBeInTheDocument()
  })
})

describe('Stock (Stock & Purchases workspace)', () => {
  it('defaults to the Inventory view with both tabs for owners', async () => {
    renderAt(<Godown />, '/stock', '/stock')
    expect(await screen.findByText('STOCK_VIEW')).toBeInTheDocument()
    expect(screen.getByText('Purchase Bills')).toBeInTheDocument()
  })

  it('serves /stock/purchase as a real route', async () => {
    renderAt(<Godown />, '/stock', '/stock/purchase')
    expect(await screen.findByText('PURCHASES_VIEW')).toBeInTheDocument()
    expect(screen.queryByText('STOCK_VIEW')).not.toBeInTheDocument()
  })

  it('hides the Purchase Bills tab from cashiers and refuses the deep link', async () => {
    mockUser = { id: 2, role: 'cashier' }
    renderAt(<Godown />, '/stock', '/stock/purchase')
    // deep link to purchase falls back to inventory; the tab is not rendered
    expect(await screen.findByText('STOCK_VIEW')).toBeInTheDocument()
    expect(screen.queryByText('Purchase Bills')).not.toBeInTheDocument()
    expect(screen.queryByText('PURCHASES_VIEW')).not.toBeInTheDocument()
  })
})
