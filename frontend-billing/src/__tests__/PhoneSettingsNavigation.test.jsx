import React from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'

const state = vi.hoisted(() => ({ phone: true, authFetch: vi.fn() }))
vi.mock('../layouts/AppLayout', () => ({ default: ({ children }) => <div>{children}</div> }))
vi.mock('../contexts/AuthContext', () => ({
  useAuth: () => ({ user: { id: 1, role: 'owner' }, authFetch: state.authFetch, fetchSettings: vi.fn(), networkMode: 'cloud' }),
  useBusinessConfig: () => ({ config: {}, refreshConfig: vi.fn() }),
}))
vi.mock('../contexts/LockContext', () => ({ useLock: () => ({ hasLock: false }) }))
vi.mock('../contexts/ConfirmContext', () => ({ useConfirm: () => async () => true }))
vi.mock('../components/settings/AppearanceSettings', () => ({ default: () => <div>Appearance preferences</div> }))
vi.mock('../components/settings/OpsHealthPanel', () => ({ default: () => <div>Business data health</div> }))

import Settings from '../pages/Settings'

beforeEach(() => {
  state.phone = true
  localStorage.clear()
  state.authFetch.mockReset().mockResolvedValue({ ok: true, json: async () => ({ general: {}, subscription: { plan: 'pro', status: 'active' } }) })
  vi.stubGlobal('matchMedia', vi.fn(query => ({ matches: state.phone && query === 'screen and (max-width: 600px)', media: query, addEventListener() {}, removeEventListener() {} })))
  vi.stubGlobal('fetch', vi.fn(async url => ({ ok: true, headers: { get: () => null }, json: async () =>
    String(url).endsWith('/health') ? { status: 'ok', db: 'connected', db_type: 'sqlite' } : [] })))
})
afterEach(() => { cleanup(); vi.unstubAllGlobals() })

const mount = (path = '/settings') => render(<MemoryRouter initialEntries={[path]}><Settings /></MemoryRouter>)

describe('Phone Settings navigation', () => {
  it('keeps system checks in Ops & Health and runs them only when requested', async () => {
    mount('/settings?tab=ops_health')
    const check = await screen.findByRole('button', { name: 'Check system' })
    expect(check).toHaveAttribute('aria-expanded', 'false')
    expect(fetch.mock.calls.filter(([url]) => String(url).endsWith('/health'))).toHaveLength(0)
    fireEvent.click(check)
    expect(await screen.findByText('System check')).toBeVisible()
    expect(await screen.findByText('sqlite')).toBeVisible()
    expect(check).toHaveAttribute('aria-expanded', 'true')
    expect(fetch.mock.calls.some(([url]) => String(url).endsWith('/health'))).toBe(true)
    fireEvent.click(screen.getByRole('button', { name: 'Hide check' }))
    expect(screen.queryByText('System check')).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Check system' })).toHaveAttribute('aria-expanded', 'false')
  })

  it('shows staff records before the optional add-staff form on a phone', async () => {
    state.authFetch.mockImplementation(async path => ({ ok: true, json: async () => path === '/staff' ? [{ id: 1, username: 'counter_one', phone: '9000000000', role: 'cashier', counter_prefix: 'C1' }] : { general: {}, subscription: { plan: 'pro', status: 'active' } } }))
    mount('/settings?tab=staff')
    expect(await screen.findByText('counter_one')).toBeVisible()
    expect(screen.getByText(/Add staff/, { selector: 'summary' }).closest('details')).not.toHaveAttribute('open')
    expect(screen.getByPlaceholderText('e.g. staff_john')).not.toBeVisible()
    expect(state.authFetch.mock.calls.some(([, options]) => options?.method === 'POST')).toBe(false)
  })

  it('opens a focused section from the searchable launcher and returns without changing settings', async () => {
    mount()
    const search = await screen.findByRole('searchbox', { name: 'Find a settings section' })
    expect(screen.queryByText('Appearance preferences')).not.toBeInTheDocument()
    fireEvent.change(search, { target: { value: 'display' } })
    expect(screen.queryByRole('button', { name: /Staff Management/ })).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /General Display/ }))
    expect(await screen.findByText('Appearance preferences')).toBeInTheDocument()
    expect(screen.queryByRole('searchbox')).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Back to settings' }))
    expect(await screen.findByRole('searchbox', { name: 'Find a settings section' })).toHaveValue('display')
    expect(state.authFetch.mock.calls.some(([, options]) => options?.method === 'PUT')).toBe(false)
  })

  it('opens a deep-linked section directly on a phone', async () => {
    mount('/settings?tab=general')
    expect(await screen.findByText('Appearance preferences')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Back to settings' })).toBeInTheDocument()
    expect(screen.queryByRole('searchbox', { name: 'Find a settings section' })).not.toBeInTheDocument()
  })

  it('retains the existing split section navigation above the phone breakpoint', async () => {
    state.phone = false
    mount()
    expect(await screen.findByText('Appearance preferences')).toBeInTheDocument()
    expect(screen.getAllByRole('tablist', { name: 'Settings sections' }).length).toBeGreaterThan(0)
    expect(screen.queryByRole('button', { name: 'Back to settings' })).not.toBeInTheDocument()
    expect(screen.queryByRole('searchbox', { name: 'Find a settings section' })).not.toBeInTheDocument()
  })
})
