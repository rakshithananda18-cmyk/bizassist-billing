import React from 'react'
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'

const auth = vi.hoisted(() => ({ value: null }))
vi.mock('../contexts/AuthContext', () => ({ useAuth: () => auth.value }))
vi.mock('../contexts/LockContext', () => ({ useLock: () => ({ hasLock: false, lock: () => {}, resetInactivityTimer: () => {} }) }))
vi.mock('../config', async importOriginal => ({ ...(await importOriginal()), IS_LOCAL_APP: true }))
vi.mock('../components/PageHelp', () => ({ default: () => null }))
vi.mock('../components/UniversalSearch', () => ({ default: () => null }))
vi.mock('../components/NotificationBell', () => ({ default: () => null }))
vi.mock('../components/hosting/SyncNudgeModal', () => ({ default: () => null }))
vi.mock('../components/hosting/WebLocalOnlyNotice', () => ({ default: () => null }))
vi.mock('../utils/telemetry', () => ({ sendDiagnostics: vi.fn() }))
import AppLayout from '../layouts/AppLayout'
import { setHostingPreference } from '../utils/deviceMode'

beforeEach(() => {
  localStorage.clear()
  localStorage.setItem('bizassist_hosting_mode', 'local')
  setHostingPreference('owner', 'local')
  Object.defineProperty(window, 'innerWidth', { configurable: true, value: 1440 })
  auth.value = {
    user: { id: 1, username: 'owner', role: 'owner' }, token: 'session-token',
    profile: { business_name: 'Sample Store' },
    settings: { general: { hosting_mode: 'local' }, subscription: { plan: 'pro' } },
    businessConfig: {}, appReady: true, setAppReady: vi.fn(), authFetch: vi.fn(), logout: vi.fn(), fetchSettings: vi.fn(),
  }
  vi.stubGlobal('fetch', vi.fn(async url => ({ ok: true, headers: { get: () => null }, json: async () =>
    String(url).endsWith('/health') ? { status: 'ok', db: 'connected', db_type: 'sqlite', version: '1.2.6' } : {} })))
})
afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.restoreAllMocks() })

it('releases Sync now after acceptance even while the following status read is slow', async () => {
  localStorage.setItem('bizassist_hosting_mode', 'hybrid')
  setHostingPreference('owner', 'hybrid')
  auth.value = { ...auth.value, settings: { general: { hosting_mode: 'hybrid' }, subscription: { plan: 'pro' } } }
  let depthReads = 0
  vi.stubGlobal('fetch', vi.fn(async url => ({
    ok: true, status: 202, headers: { get: () => null },
    json: () => {
      if (String(url).endsWith('/api/sync/queue-depth')) {
        depthReads++
        if (depthReads > 1) return new Promise(() => {})
        return Promise.resolve({ pending_count: 0, pull: { initialized: true } })
      }
      return Promise.resolve({})
    },
  })))
  render(<MemoryRouter><AppLayout title="Home">Workspace</AppLayout></MemoryRouter>)
  await waitFor(() => expect(depthReads).toBe(1))
  fireEvent.click(screen.getByRole('button', { name: 'View server and sync health details' }))
  fireEvent.click(screen.getByRole('button', { name: 'Sync now', exact: true }))
  await waitFor(() => expect(depthReads).toBeGreaterThan(1))
  expect(screen.getByRole('button', { name: 'Sync now', exact: true })).toBeEnabled()
  expect(screen.getByText(/Background sync requested/)).toBeInTheDocument()
  expect(fetch.mock.calls.filter(([url]) => String(url).includes('/api/sync/flush?pull=true'))).toHaveLength(1)
})

it('does not apply a late previous-business restore response after its JSON finishes', async () => {
  let finishPreviousJson
  localStorage.setItem('bizassist_hosting_mode', 'hybrid')
  auth.value = { ...auth.value, user: { id: 1, public_id: 'BIZ-FIRST', username: 'owner', role: 'owner' },
    token: 'first-token', settings: { general: { hosting_mode: 'hybrid' }, subscription: { plan: 'pro' } } }
  vi.stubGlobal('fetch', vi.fn(async (url, options) => {
    const depth = String(url).endsWith('/api/sync/queue-depth')
    return { ok: true, headers: { get: () => null }, json: () => {
      if (depth && options?.headers?.Authorization === 'Bearer first-token') {
        return new Promise(resolve => { finishPreviousJson = resolve })
      }
      return Promise.resolve(depth ? { pending_count: 0, pull: { initialized: true, initial_restore_pending: false, has_more: false } } : {})
    } }
  }))
  const app = () => <MemoryRouter><AppLayout title="Home">Workspace</AppLayout></MemoryRouter>
  const view = render(app())
  await waitFor(() => expect(finishPreviousJson).toBeTypeOf('function'))
  auth.value = { ...auth.value, user: { id: 2, public_id: 'BIZ-SECOND', username: 'second', role: 'owner' }, token: 'second-token' }
  view.rerender(app())
  await waitFor(() => expect(fetch.mock.calls.some(([, options]) => options?.headers?.Authorization === 'Bearer second-token')).toBe(true))
  await act(async () => { finishPreviousJson({ pending_count: 99, pull: { initial_restore_pending: true, has_more: true } }) })
  expect(screen.queryAllByText(/Restoring cloud data/)).toHaveLength(0)
})

it('opens server health in Local mode only when requested and restores keyboard focus on close', async () => {
  render(<MemoryRouter><AppLayout title="Home">Workspace</AppLayout></MemoryRouter>)
  const trigger = screen.getByRole('button', { name: 'View server and sync health details' })
  expect(trigger).toHaveTextContent('Server health')
  expect(fetch.mock.calls.filter(([url]) => String(url).endsWith('/health'))).toHaveLength(0)
  fireEvent.click(trigger)
  const details = screen.getByRole('dialog', { name: 'Server and sync health details' })
  expect(trigger).toHaveAttribute('aria-expanded', 'true')
  expect(details).toHaveFocus()
  await screen.findByText('sqlite · Version 1.2.6')
  expect(screen.getByText('Local only — cloud sync paused')).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: 'Sync now', exact: true })).toBeNull()
  vi.spyOn(window.navigator, 'onLine', 'get').mockReturnValue(false)
  fireEvent(window, new Event('offline'))
  expect(screen.getByText('Network State').nextElementSibling).toHaveTextContent('Offline')
  fireEvent.keyDown(document, { key: 'Escape' })
  await waitFor(() => expect(screen.queryByRole('dialog', { name: 'Server and sync health details' })).toBeNull())
  expect(trigger).toHaveFocus()
})

it('closes health details before dismissing the mobile navigation drawer', async () => {
  vi.spyOn(window, 'matchMedia').mockImplementation(query => ({
    matches: query === 'screen and (max-width: 600px)', media: query,
    addEventListener: () => {}, removeEventListener: () => {},
  }))
  render(<MemoryRouter><AppLayout title="Home">Workspace</AppLayout></MemoryRouter>)
  fireEvent.click(screen.getByRole('button', { name: 'Open menu' }))
  await waitFor(() => expect(screen.getByRole('button', { name: 'Close menu' })).toHaveFocus())
  const trigger = screen.getByRole('button', { name: 'View server and sync health details' })
  fireEvent.click(trigger)
  expect(screen.getByRole('dialog', { name: 'Server and sync health details' })).toBeInTheDocument()
  fireEvent.keyDown(document, { key: 'Escape' })
  expect(screen.queryByRole('dialog', { name: 'Server and sync health details' })).toBeNull()
  expect(screen.getByRole('dialog', { name: 'Navigation menu' })).toHaveAttribute('aria-modal', 'true')
  expect(document.getElementById('mobile-navigation')).toHaveClass('open')
  expect(trigger).toHaveFocus()
})
