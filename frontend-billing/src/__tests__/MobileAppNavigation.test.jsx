import React from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act, cleanup, render, screen, within } from '@testing-library/react'
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
function mount(path = '/sales', mobile = true, role = 'enterprise', zoom = 100) {
  let width = typeof mobile === 'number' ? mobile : mobile ? 390 : 1280
  const mediaQueries = []
  const matches = query => {
    const max = query.match(/max-width:\s*(\d+)px/)
    return max ? width <= Number(max[1]) : false
  }
  window.matchMedia = query => {
    const listeners = new Set()
    const media = { matches: matches(query), media: query, addEventListener: (_event, listener) => listeners.add(listener), removeEventListener: (_event, listener) => listeners.delete(listener) }
    mediaQueries.push({ media, listeners })
    return media
  }
  auth.value = {
    user: { id: 1, username: 'demo-owner', public_id: 'BA-DEMO', role, is_demo: true },
    profile: { business_name: 'Sample Store' }, settings: { general: { hosting_mode: 'hybrid' }, subscription: { plan: 'pro' } },
    token: 'demo-token', isDemoMode: true, appReady: true, businessConfig: { general: { app_zoom: zoom } }, setAppReady: vi.fn(), logout: vi.fn(), fetchSettings: vi.fn(),
  }
  render(<MemoryRouter initialEntries={[path]}><Routes>
    <Route path="*" element={<AppLayout><div>Workspace content</div></AppLayout>} />
  </Routes></MemoryRouter>)
  return nextWidth => act(() => {
    width = nextWidth
    mediaQueries.forEach(({ media, listeners }) => {
      const next = matches(media.media)
      if (media.matches === next) return
      media.matches = next
      listeners.forEach(listener => listener(media))
    })
  })
}

beforeEach(() => { localStorage.clear(); sessionStorage.clear() })
afterEach(() => { cleanup(); window.matchMedia = originalMatchMedia; document.documentElement.style.zoom = ''; document.documentElement.style.removeProperty('--zoom') })

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

  it('uses desktop navigation in the former 601–768px mobile range, including at 75% app scale', () => {
    mount('/stock', 700, 'enterprise', 75)
    const sidebar = document.getElementById('mobile-navigation')
    expect(sidebar).not.toHaveAttribute('role', 'dialog')
    expect(sidebar).not.toHaveAttribute('aria-hidden')
    expect(sidebar).not.toHaveAttribute('inert')
    expect(document.documentElement.style.zoom).toBe('75%')
  })

  it('switches directly between phone and desktop navigation on resize and clears the drawer overlay', async () => {
    const resize = mount('/stock', 600, 'enterprise', 75)
    expect(document.documentElement.style.zoom).toBe('100%')
    await userEvent.setup().click(screen.getByRole('button', { name: 'Open menu' }))
    expect(screen.getByRole('dialog', { name: 'Navigation menu' })).toBeInTheDocument()
    expect(document.querySelector('.mobile-drawer-backdrop')).toBeTruthy()
    resize(601)
    expect(screen.queryByRole('dialog', { name: 'Navigation menu' })).not.toBeInTheDocument()
    expect(document.querySelector('.mobile-drawer-backdrop')).toBeNull()
    expect(document.documentElement.style.zoom).toBe('75%')
    resize(390)
    expect(document.getElementById('mobile-navigation')).toHaveAttribute('inert', '')
    expect(document.documentElement.style.zoom).toBe('100%')
  })
})
