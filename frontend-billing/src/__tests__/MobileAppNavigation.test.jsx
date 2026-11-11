import React from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'

const auth = vi.hoisted(() => ({ value: null }))
vi.mock('../contexts/AuthContext', () => ({ useAuth: () => auth.value }))
vi.mock('../contexts/LockContext', () => ({ useLock: () => ({ hasLock: false, lock: vi.fn(), resetInactivityTimer: vi.fn() }) }))
vi.mock('../components/NotificationBell', () => ({ default: () => null }))
vi.mock('../components/PageHelp', () => ({ default: () => null }))
vi.mock('../components/UniversalSearch', () => ({ default: () => null }))
vi.mock('../components/help/SmartHelpCenterModal', () => ({ default: () => null }))
vi.mock('../components/hosting/SyncNudgeModal', () => ({ default: () => null }))
vi.mock('../components/hosting/WebLocalOnlyNotice', () => ({ default: () => null }))

import AppLayout from '../layouts/AppLayout'

const originalMatchMedia = window.matchMedia
function mount(path = '/sales', mobile = true, role = 'enterprise') {
  window.matchMedia = query => ({ matches: mobile && query.includes('max-width: 768px'), media: query, addEventListener() {}, removeEventListener() {} })
  auth.value = {
    user: { id: 1, username: 'demo-owner', public_id: 'BA-DEMO', role, is_demo: true },
    profile: { business_name: 'Sample Store' }, settings: { general: { hosting_mode: 'hybrid' }, subscription: { plan: 'pro' } },
    token: 'demo-token', isDemoMode: true, appReady: true, businessConfig: {}, setAppReady: vi.fn(), logout: vi.fn(), fetchSettings: vi.fn(),
  }
  render(<MemoryRouter initialEntries={[path]}><Routes>
    <Route path="*" element={<AppLayout><div>Workspace content</div></AppLayout>} />
  </Routes></MemoryRouter>)
}

beforeEach(() => { localStorage.clear(); sessionStorage.clear() })
afterEach(() => { cleanup(); window.matchMedia = originalMatchMedia })

describe('Mobile workspace navigation', () => {
  it('keeps icon-only navigation accessible in portrait billing and navigates between workspaces', async () => {
    mount()
    const nav = screen.getByRole('navigation', { name: 'Primary' })
    const links = within(nav).getAllByRole('link')
    expect(links).toHaveLength(5)
    for (const link of links) {
      expect(link).toHaveAccessibleName()
      expect(link.querySelector('svg')).toBeTruthy()
      expect(link.textContent.trim()).toBe('')
    }
    expect(within(nav).getByRole('link', { name: 'Billing Counter' })).toHaveAttribute('aria-current', 'page')
    expect(screen.queryByText('Rotate Your Device')).not.toBeInTheDocument()
    await userEvent.setup().click(within(nav).getByRole('link', { name: 'Stock & Purchases' }))
    expect(within(nav).getByRole('link', { name: 'Stock & Purchases' })).toHaveAttribute('aria-current', 'page')
    expect(within(nav).getByRole('link', { name: 'Home' })).not.toHaveAttribute('aria-current')
  })

  it('opens and dismisses the navigation drawer from billing', async () => {
    mount()
    const user = userEvent.setup()
    const open = screen.getByRole('button', { name: 'Open menu' })
    await user.click(open)
    const menu = screen.getByRole('dialog', { name: 'Navigation menu' })
    expect(open).toHaveAttribute('aria-expanded', 'true')
    expect(within(menu).getByRole('link', { name: 'Dashboard' })).toBeInTheDocument()
    await user.keyboard('{Escape}')
    expect(screen.queryByRole('dialog', { name: 'Navigation menu' })).not.toBeInTheDocument()
    expect(open).toHaveAttribute('aria-expanded', 'false')
  })

  it('retains the full desktop billing layout without a sidebar', () => {
    mount('/sales', false)
    expect(document.querySelector('.sidebar')).toBeNull()
    expect(document.querySelector('.app-shell')).toHaveClass('pos-layout-shell')
  })
})
