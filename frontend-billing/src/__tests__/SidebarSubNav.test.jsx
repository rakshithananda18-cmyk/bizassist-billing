import React from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'

const auth = vi.hoisted(() => ({ value: null }))
vi.mock('../contexts/AuthContext', () => ({ useAuth: () => auth.value }))
vi.mock('../contexts/LockContext', () => ({
  useLock: () => ({ hasLock: false, lock: () => {}, resetInactivityTimer: () => {} }),
}))
vi.mock('../components/PageHelp', () => ({ default: () => null }))
vi.mock('../components/UniversalSearch', () => ({ default: () => null }))
vi.mock('../components/hosting/SyncNudgeModal', () => ({ default: () => null }))
vi.mock('../components/hosting/WebLocalOnlyNotice', () => ({ default: () => null }))

import AppLayout from '../layouts/AppLayout'

function renderApp(initialEntry = '/stock/inventory', role = 'owner') {
  auth.value = {
    user: { id: 1, username: 'testuser', role },
    profile: { business_name: 'Test Store' },
    settings: { general: { hosting_mode: 'local' }, subscription: { plan: 'pro' } },
    businessConfig: {},
    appReady: true,
    setAppReady: vi.fn(),
    authFetch: vi.fn(async () => ({ ok: true, json: async () => ({}) })),
    logout: vi.fn(),
    fetchSettings: vi.fn(),
  }

  return render(
    <MemoryRouter initialEntries={[initialEntry]}>
      <Routes>
        <Route path="/stock" element={<AppLayout title="Stock">Stock Root</AppLayout>} />
        <Route path="/stock/inventory" element={<AppLayout title="Inventory">Inventory Workspace</AppLayout>} />
        <Route path="/stock/purchase" element={<AppLayout title="Purchases">Purchases Workspace</AppLayout>} />
        <Route path="/parties" element={<AppLayout title="Parties">Parties Root</AppLayout>} />
        <Route path="/parties/contacts" element={<AppLayout title="Contacts">Contacts Workspace</AppLayout>} />
        <Route path="/parties/payments" element={<AppLayout title="Payments">Payments Workspace</AppLayout>} />
        <Route path="/dashboard" element={<AppLayout title="Dashboard">Dashboard Workspace</AppLayout>} />
      </Routes>
    </MemoryRouter>
  )
}

beforeEach(() => {
  localStorage.setItem('billing_theme', 'light')
})
afterEach(cleanup)

describe('Sidebar Sub-Nav Tree (Accordion)', () => {
  it('displays sub-pages tree when active on /stock/inventory and highlights the active sub-page', () => {
    renderApp('/stock/inventory')
    const sidebar = document.querySelector('.sidebar-nav')

    // Main item is present and active
    const stockNavLink = within(sidebar).getByRole('link', { name: /^Stock & Purchases$/i })
    expect(stockNavLink).toHaveClass('active')

    // Sub-items are rendered
    const itemsLink = within(sidebar).getByRole('link', { name: /^Stock & Items$/i })
    const purchaseLink = within(sidebar).getByRole('link', { name: /Purchase Bills/i })
    expect(itemsLink).toBeInTheDocument()
    expect(purchaseLink).toBeInTheDocument()

    // Sub-item has active class
    expect(itemsLink).toHaveClass('active')
    expect(purchaseLink).not.toHaveClass('active')
  })

  it('auto-collapses stock sub-tree when on another main page like /dashboard', () => {
    renderApp('/dashboard')
    const sidebar = document.querySelector('.sidebar-nav')

    // On dashboard page, Stock sub-items should NOT be visible
    expect(within(sidebar).queryByRole('link', { name: /^Stock & Items$/i })).not.toBeInTheDocument()
    expect(within(sidebar).queryByRole('link', { name: /Purchase Bills/i })).not.toBeInTheDocument()

    // Dashboard item is active
    expect(within(sidebar).getByRole('link', { name: /^Dashboard$/i })).toHaveClass('active')
  })

  it('navigates to sub-page and updates selection without separate collapse buttons', async () => {
    renderApp('/stock/inventory')
    const sidebar = document.querySelector('.sidebar-nav')
    const user = userEvent.setup()

    const purchaseLink = within(sidebar).getByRole('link', { name: /Purchase Bills/i })
    await user.click(purchaseLink)

    expect(screen.getByText('Purchases Workspace')).toBeInTheDocument()
    expect(purchaseLink).toHaveClass('active')
  })

  it('hides owner-only sub-pages like Purchases from cashier role', () => {
    renderApp('/stock/inventory', 'cashier')
    const sidebar = document.querySelector('.sidebar-nav')

    // Cashier sees Stock & Items, but NOT Purchases
    expect(within(sidebar).getByRole('link', { name: /^Stock & Items$/i })).toBeInTheDocument()
    expect(within(sidebar).queryByRole('link', { name: /Purchase Bills/i })).not.toBeInTheDocument()
  })
})
