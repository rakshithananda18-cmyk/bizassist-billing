import React from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, render, screen, waitFor } from '@testing-library/react'
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

function renderLayout(role = 'owner') {
  const authFetch = vi.fn(async path => ({
    ok: true,
    json: async () => path === '/alerts/notifications'
      ? { items: [{ kind: 'low_stock', severity: 'warning', title: '2 products running low', route: '/stock/inventory' }] }
      : { halt: { reason: null } },
  }))
  auth.value = {
    user: { id: 1, username: 'owner', role },
    profile: { business_name: 'SaaS Production' },
    settings: { general: { hosting_mode: 'local', auto_backup: false }, subscription: { plan: 'pro' } },
    businessConfig: {}, appReady: true, setAppReady: vi.fn(),
    authFetch, logout: vi.fn(), fetchSettings: vi.fn(),
  }
  render(
    <MemoryRouter initialEntries={['/']}>
      <Routes>
        <Route path="/" element={<AppLayout title="Home">Workspace</AppLayout>} />
        <Route path="/stock/inventory" element={<div>Inventory workspace opened</div>} />
      </Routes>
    </MemoryRouter>
  )
  return authFetch
}

beforeEach(() => { localStorage.setItem('billing_theme', 'light') })
afterEach(cleanup)

describe('profile notifications', () => {
  it('keeps the closed mobile drawer out of focus and restores focus after Escape', async () => {
    const media = vi.spyOn(window, 'matchMedia').mockImplementation(query => ({
      matches: query === '(max-width: 768px)', media: query,
      addEventListener: () => {}, removeEventListener: () => {},
    }))
    try {
      renderLayout()
      const user = userEvent.setup()
      const open = screen.getByRole('button', { name: 'Open menu' })
      const drawer = document.getElementById('mobile-navigation')
      expect(drawer).toHaveAttribute('inert', '')
      expect(drawer).toHaveAttribute('aria-hidden', 'true')
      await user.click(open)
      expect(screen.getByRole('dialog', { name: 'Navigation menu' })).toHaveAttribute('aria-modal', 'true')
      expect(drawer).not.toHaveAttribute('inert')
      await waitFor(() => expect(screen.getByRole('button', { name: 'Close menu' })).toHaveFocus())
      await user.keyboard('{Escape}')
      expect(drawer).toHaveAttribute('inert', '')
      expect(drawer).toHaveAttribute('aria-hidden', 'true')
      expect(open).toHaveFocus()
    } finally {
      cleanup()
      media.mockRestore()
    }
  })

  it('opens alerts beside the profile without opening settings, then follows the alert', async () => {
    const authFetch = renderLayout()
    const user = userEvent.setup()
    const bell = await screen.findByRole('button', { name: '1 notification' })
    expect(bell.closest('.sidebar-profile-row')).toContainElement(screen.getByTitle('Settings & Profile'))
    expect(authFetch).toHaveBeenCalledWith('/alerts/notifications')

    await user.click(screen.getByTitle('Settings & Profile'))
    expect(screen.getAllByText('Enterprise Account').length).toBeGreaterThan(0)
    await user.click(bell)
    expect(screen.getByText('Needs attention')).toBeInTheDocument()
    expect(screen.queryAllByText('Enterprise Account')).toHaveLength(0)
    await user.click(screen.getByRole('button', { name: /2 products running low/ }))
    expect(screen.getByText('Inventory workspace opened')).toBeInTheDocument()
  })

  it('keeps owner alerts out of a cashier profile', async () => {
    const authFetch = renderLayout('cashier')
    await waitFor(() => expect(screen.getByTitle('Settings & Profile')).toBeInTheDocument())
    expect(screen.queryByRole('button', { name: /notification/i })).not.toBeInTheDocument()
    expect(authFetch).not.toHaveBeenCalled()
  })
})
