import React from 'react'
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, useLocation } from 'react-router-dom'
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

const enableHybrid = () => {
  localStorage.setItem('bizassist_hosting_mode', 'hybrid')
  setHostingPreference('owner', 'hybrid')
  auth.value = { ...auth.value, settings: { general: { hosting_mode: 'hybrid' }, subscription: { plan: 'pro' } } }
}

it.each(['pro', 'free'])('shows cloud connection status without inventing a local queue failure (%s)', async plan => {
  localStorage.setItem('bizassist_hosting_mode', 'cloud')
  auth.value.settings = { general: { hosting_mode: 'hybrid', sync_bootstrap_pending: true }, subscription: { plan } }
  render(<MemoryRouter><AppLayout title="Dashboard">Cloud workspace</AppLayout></MemoryRouter>)
  act(() => window.dispatchEvent(new CustomEvent('sync-status-change', { detail: { status: 'connected', isOnline: true, error: null } })))
  const trigger = screen.getByRole('button', { name: 'View sync details' })
  await waitFor(() => expect(trigger).toHaveTextContent('Sync Live'))
  expect(trigger).toHaveStyle({ whiteSpace: 'nowrap' })
  fireEvent.click(trigger)
  expect(screen.getByText('Connected')).toBeInTheDocument()
  expect(screen.getByText('This workspace uses cloud data directly.')).toBeInTheDocument()
  expect(screen.queryByText(/Sync status is unavailable|Sync status unavailable|Restoring cloud data|Cloud restore is/)).not.toBeInTheDocument()
  expect(fetch.mock.calls.some(([url]) => /\/api\/sync\/(queue-depth|status)/.test(String(url)))).toBe(false)
})

it('keeps an unreadable queue visibly unknown instead of presenting an empty or fully synced outbox', async () => {
  enableHybrid()
  vi.stubGlobal('fetch', vi.fn(async url => ({ ok: true, status: 200, headers: { get: () => null }, json: async () =>
    String(url).endsWith('/api/sync/queue-depth')
      ? { pending_count: null, status_error: 'Outbox could not be read', readiness: { state: 'unknown' }, pull: { initialized: true } }
      : {} })))
  render(<MemoryRouter><AppLayout title="Home">Workspace</AppLayout></MemoryRouter>)
  await waitFor(() => expect(screen.getByRole('button', { name: 'View sync details' })).toHaveTextContent(/Sync status unavailable|Sync status unknown/))
  fireEvent.click(screen.getByRole('button', { name: 'View sync details' }))
  expect(screen.queryByText('Fully Synced')).toBeNull()
  expect(screen.queryByText('No local changes waiting')).toBeNull()
  expect(screen.queryByText(/0 — no local changes waiting/)).toBeNull()
})

it('shows the pending cloud restore on Billing while records are still incomplete', async () => {
  enableHybrid()
  auth.value.settings.general.sync_bootstrap_pending = true
  vi.stubGlobal('fetch', vi.fn(async url => ({ ok: true, status: 200, headers: { get: () => null }, json: async () =>
    String(url).endsWith('/api/sync/queue-depth')
      ? { pending_count: 0, pull: { initialized: false, initial_restore_pending: true, has_more: true } }
      : {} })))
  render(<MemoryRouter initialEntries={['/sales']}><AppLayout title="Billing">Billing workspace</AppLayout></MemoryRouter>)
  await waitFor(() => expect(screen.getAllByText(/Restoring cloud data|Cloud restore is/).length).toBeGreaterThan(0))
  expect(screen.getByText('Billing workspace')).toBeInTheDocument()
  expect(screen.getAllByRole('status').some(element => /restor/i.test(element.textContent))).toBe(true)
})

it('keeps the first-restore warning after choosing Local-only while the mirror is partial', async () => {
  auth.value.settings.general.sync_bootstrap_pending = true
  vi.stubGlobal('fetch', vi.fn(async url => ({ ok: true, status: 200, headers: { get: () => null }, json: async () =>
    String(url).endsWith('/api/sync/queue-depth')
      ? { pending_count: 0, pull: { initialized: false, initial_restore_pending: true, has_more: true } }
      : {} })))
  render(<MemoryRouter initialEntries={['/sales']}><AppLayout title="Billing">Billing workspace</AppLayout></MemoryRouter>)
  await waitFor(() => expect(fetch.mock.calls.some(([url]) => String(url).endsWith('/api/sync/queue-depth'))).toBe(true))
  expect(screen.getAllByRole('status').some(element => /restor/i.test(element.textContent))).toBe(true)
})

it('clears an earlier kickoff failure only after the worker reports a newer successful outcome', async () => {
  enableHybrid()
  let queue = { pending_count: 0, last_status: 'success', last_sync_time: '2020-01-01T00:00:00Z', pull: { initialized: true }, readiness: { state: 'ready' } }
  let depthReads = 0
  vi.stubGlobal('fetch', vi.fn(async url => ({ ok: true, status: 200, headers: { get: () => null }, json: async () => {
    if (String(url).endsWith('/api/sync/queue-depth')) { depthReads++; return queue }
    return {}
  } })))
  render(<MemoryRouter><AppLayout title="Home">Workspace</AppLayout></MemoryRouter>)
  await waitFor(() => expect(depthReads).toBe(1))
  act(() => window.dispatchEvent(new CustomEvent('sync-event', { detail: { type: 'sync.trigger', sync_request: true, status: 'failed', error: 'Synthetic kickoff failure' } })))
  expect(screen.getByRole('button', { name: 'View sync details' })).toHaveTextContent('Sync needs attention')
  // An old successful run does not erase a failure from the current request.
  act(() => window.dispatchEvent(new CustomEvent('sync-flushed')))
  await waitFor(() => expect(depthReads).toBeGreaterThan(1))
  expect(screen.getByRole('button', { name: 'View sync details' })).toHaveTextContent('Sync needs attention')
  queue = { ...queue, last_sync_time: new Date(Date.now() + 1000).toISOString() }
  act(() => window.dispatchEvent(new CustomEvent('sync-flushed')))
  await waitFor(() => expect(screen.getByRole('button', { name: 'View sync details' })).not.toHaveTextContent('Sync needs attention'))
})

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
  fireEvent.click(screen.getByRole('button', { name: 'View sync details' }))
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

it('keeps local sync details free of system checks and restores keyboard focus on close', async () => {
  render(<MemoryRouter><AppLayout title="Home">Workspace</AppLayout></MemoryRouter>)
  // Local-only deliberately disables the live stream; this is not a connection failure.
  act(() => window.dispatchEvent(new CustomEvent('sync-status-change', { detail: { status: 'disconnected', error: null, isOnline: true } })))
  const trigger = screen.getByRole('button', { name: 'View sync details' })
  expect(trigger).toHaveTextContent('Local only')
  expect(fetch.mock.calls.filter(([url]) => String(url).endsWith('/health'))).toHaveLength(0)
  fireEvent.click(trigger)
  const details = screen.getByRole('dialog', { name: 'Sync Live details' })
  expect(trigger).toHaveAttribute('aria-expanded', 'true')
  expect(details).toHaveFocus()
  expect(screen.queryByText('System check')).not.toBeInTheDocument()
  expect(screen.queryByText('Network State')).not.toBeInTheDocument()
  expect(fetch.mock.calls.filter(([url]) => String(url).endsWith('/health'))).toHaveLength(0)
  expect(screen.getByText('Local only — cloud sync paused')).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: 'Sync now', exact: true })).toBeNull()
  vi.spyOn(window.navigator, 'onLine', 'get').mockReturnValue(false)
  fireEvent(window, new Event('offline'))
  expect(trigger).toHaveTextContent('Local only')
  fireEvent.keyDown(document, { key: 'Escape' })
  await waitFor(() => expect(screen.queryByRole('dialog', { name: 'Sync Live details' })).toBeNull())
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
  const trigger = screen.getByRole('button', { name: 'View sync details' })
  fireEvent.click(trigger)
  expect(screen.getByRole('dialog', { name: 'Sync Live details' })).toBeInTheDocument()
  fireEvent.keyDown(document, { key: 'Escape' })
  expect(screen.queryByRole('dialog', { name: 'Sync Live details' })).toBeNull()
  expect(screen.getByRole('dialog', { name: 'Navigation menu' })).toHaveAttribute('aria-modal', 'true')
  expect(document.getElementById('mobile-navigation')).toHaveClass('open')
  expect(trigger).toHaveFocus()
})


it('shows a live connection issue in one line and links owners to Settings for system checks', () => {
  function CurrentRoute() {
    const location = useLocation()
    return <output aria-label="Current route">{location.pathname}{location.search}</output>
  }
  render(<MemoryRouter><AppLayout title="Home"><CurrentRoute /></AppLayout></MemoryRouter>)
  act(() => window.dispatchEvent(new CustomEvent('sync-status-change', { detail: {
    status: 'error', isOnline: true, error: 'Backend disconnected.\nReconnecting automatically.',
  } })))
  const trigger = screen.getByRole('button', { name: 'View sync details' })
  expect(trigger).toHaveTextContent('Connection issue')
  fireEvent.click(trigger)
  const issue = screen.getByText('Backend disconnected. Reconnecting automatically.')
  expect(issue).toHaveStyle({ whiteSpace: 'nowrap', textOverflow: 'ellipsis' })
  expect(screen.queryByText('Diagnostic Log:')).not.toBeInTheDocument()
  expect(screen.queryByText('System check')).not.toBeInTheDocument()
  expect(fetch.mock.calls.filter(([url]) => String(url).endsWith('/health'))).toHaveLength(0)
  act(() => window.dispatchEvent(new CustomEvent('sync-status-change', { detail: { status: 'connected', isOnline: true, error: null } })))
  expect(screen.queryByText('Backend disconnected. Reconnecting automatically.')).not.toBeInTheDocument()
  expect(trigger).toHaveTextContent('Local only')
  act(() => window.dispatchEvent(new CustomEvent('sync-status-change', { detail: { status: 'error', isOnline: true, error: 'Backend unavailable' } })))
  fireEvent.click(screen.getByRole('button', { name: 'Open system health in Settings' }))
  expect(screen.getByLabelText('Current route')).toHaveTextContent('/settings?tab=ops_health&field=system-health')
  expect(screen.queryByRole('dialog', { name: 'Sync Live details' })).not.toBeInTheDocument()
})
