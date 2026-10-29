import React from 'react'
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import AdminSettings from '../pages/admin/AdminSettings'
import AdminLayout from '../layouts/AdminLayout'
import AdminTelemetry from '../pages/admin/AdminTelemetry'
import AdminCache from '../pages/admin/AdminCache'
import { DialogProvider } from '../contexts/DialogContext'
import { formatAdminTime } from '../utils/adminPreferences'

const auth = vi.hoisted(() => ({ authFetch: vi.fn(), adminUser: { username: 'operator', public_id: 'BA-TEST01' }, adminLogout: vi.fn() }))
vi.mock('../contexts/AuthContext', () => ({ useAuth: () => auth }))
const response = data => ({ ok: true, json: async () => data })
const cache = { context_cache: [{ user_id: 1, size_chars: 120, built_at: 0 }], query_cache: [{ user_id: 1, query_count: 3 }] }

function mount(tab = 'appearance', withLayout = false) {
  return render(<DialogProvider><MemoryRouter initialEntries={[`/admin/settings?tab=${tab}`]}>
    {withLayout ? <Routes><Route element={<AdminLayout />}><Route path="/admin/settings" element={<AdminSettings />} /></Route></Routes> : <AdminSettings />}
  </MemoryRouter></DialogProvider>)
}

beforeEach(() => {
  localStorage.clear()
  document.documentElement.classList.remove('dark-mode')
  Object.defineProperty(window, 'innerWidth', { configurable: true, value: 1440 })
  auth.adminUser = { username: 'operator', public_id: 'BA-TEST01' }
  auth.authFetch.mockReset().mockImplementation(async (url, options) => {
    if (url.endsWith('/admin/router-mode')) return response(options?.method === 'POST' ? { mode: JSON.parse(options.body).mode, message: 'Routing updated' } : { mode: 'legacy' })
    if (url.endsWith('/admin/cache-stats')) return response(cache)
    if (url.endsWith('/admin/health-check')) return response({ db_type: 'postgresql', postgres: 'error', sqlite: 'unknown' })
    if (url.endsWith('/admin/feedbacks')) return response([{ id: 1, username: 'merchant-one', message: 'Printer alignment issue', created_at: '2026-10-29T06:30:00' }])
    if (url.endsWith('/admin/telemetry/stats')) return response({ rows: 1, size_mb: 1, max_mb: 200, retention_days: 30 })
    if (url.includes('/admin/telemetry?')) return response({ events: [{ level: 'info', event: 'startup', received_at: '2026-10-29T06:30:00', bizid: 'BA-TEST' }] })
    return response({ message: 'Completed' })
  })
})
afterEach(() => { cleanup(); vi.useRealTimers(); vi.restoreAllMocks() })

describe('Admin settings API contracts', () => {
  it.each(['Flush Caches', 'Reset Chroma'])('shows rejected %s operations as errors rather than success', async action => {
    auth.authFetch.mockImplementation(async (url, options) => options?.method === 'POST'
      ? { ok: false, json: async () => ({ detail: 'Maintenance access denied' }) }
      : response(cache))
    render(<DialogProvider><AdminCache /></DialogProvider>)
    await userEvent.click(screen.getByRole('button', { name: action }))
    await userEvent.click(screen.getByRole('button', { name: 'Confirm', exact: true }))
    expect(await screen.findByText('Error: Maintenance access denied')).toBeInTheDocument()
    expect(screen.queryByText(/successfully\./)).not.toBeInTheDocument()
  })
  it('confirms a routing change and sends only a supported server mode', async () => {
    mount('router')
    const select = screen.getByRole('combobox', { name: 'Router orchestration policy' })
    await waitFor(() => expect(select).toHaveValue('legacy'))
    expect(screen.queryByText('Primary LLM Provider Tier')).not.toBeInTheDocument()
    await userEvent.selectOptions(select, 'new')
    await userEvent.click(screen.getByRole('button', { name: 'Save Router Configuration' }))
    expect(auth.authFetch.mock.calls.filter(([, opts]) => opts?.method === 'POST')).toHaveLength(0)
    await userEvent.click(screen.getByRole('button', { name: 'Confirm', exact: true }))
    await screen.findByText('Routing updated')
    const request = auth.authFetch.mock.calls.find(([, opts]) => opts?.method === 'POST')
    expect(JSON.parse(request[1].body)).toEqual({ mode: 'new' })
  })

  it('uses real health/cache fields and requires confirmation before a cache mutation', async () => {
    mount('system')
    await screen.findByText(/Server database: postgresql/)
    expect(screen.queryByText(/Healthy \(connected\)/)).not.toBeInTheDocument()
    expect(screen.getByText('error')).toBeInTheDocument()
    await screen.findByText('1 merchant contexts · 3 cached query responses')
    await userEvent.click(screen.getByRole('button', { name: 'Flush All Cache' }))
    expect(screen.getByRole('alertdialog', { name: 'Confirm Action' })).toBeInTheDocument()
    expect(auth.authFetch.mock.calls.some(([, options]) => options?.method === 'POST')).toBe(false)
    await userEvent.click(screen.getByRole('button', { name: 'Confirm', exact: true }))
    await screen.findByText('System query response caches have been cleared.')
    expect(auth.authFetch).toHaveBeenCalledWith(expect.stringMatching(/\/admin\/flush-all-cache$/), { method: 'POST' })
  })

  it('fetches the admin-scoped support queue and shows merchant identity', async () => {
    mount('feedback')
    await screen.findByText('Printer alignment issue')
    expect(screen.getByText('merchant-one')).toBeInTheDocument()
    expect(auth.authFetch).toHaveBeenCalledWith(expect.stringMatching(/\/admin\/feedbacks$/))
    expect(auth.authFetch.mock.calls.some(([url]) => url.endsWith('/feedback'))).toBe(false)
  })

  it('keeps a system confirmation keyboard-contained and cancels safely with Escape', async () => {
    mount('system')
    await screen.findByText(/Server database: postgresql/)
    const flush = screen.getByRole('button', { name: 'Flush All Cache' })
    await userEvent.click(flush)
    expect(screen.getByRole('button', { name: 'Cancel', exact: true })).toHaveFocus()
    await userEvent.tab({ shift: true })
    expect(screen.getByRole('button', { name: 'Confirm', exact: true })).toHaveFocus()
    await userEvent.keyboard('{Escape}')
    expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument()
    expect(flush).toHaveFocus()
    expect(auth.authFetch.mock.calls.some(([, options]) => options?.method === 'POST')).toBe(false)
  })

  it('shows a support request failure instead of claiming there are no tickets', async () => {
    auth.authFetch.mockImplementation(async url => url.endsWith('/admin/feedbacks') ? { ok: false } : response({ mode: 'legacy' }))
    mount('feedback')
    expect(await screen.findByRole('alert')).toHaveTextContent('Support tickets could not be loaded')
    expect(screen.queryByText('No merchant support tickets currently on file.')).not.toBeInTheDocument()
  })

  it('links quotas to the working per-business controls without unsaved dummy fields', async () => {
    mount('limits')
    await act(async () => {})
    expect(screen.getByRole('link', { name: 'Manage business limits' })).toHaveAttribute('href', '/admin/businesses')
    expect(screen.queryByRole('spinbutton')).not.toBeInTheDocument()
  })

  it('does not invent a BizID when the signed-in session has none', async () => {
    auth.adminUser = { username: 'operator' }
    mount()
    await act(async () => {})
    expect(screen.getByText('Unavailable')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Copy BizID' })).toBeDisabled()
    expect(screen.queryByText('BA-H2GQZZ')).not.toBeInTheDocument()
  })

  it('falls back to appearance when a tab query is unknown', async () => {
    mount('missing-tab')
    await act(async () => {})
    expect(screen.getByText('Interface Theme & Surface')).toBeInTheDocument()
  })

  it('switches sections through the phone settings selector', async () => {
    mount('appearance')
    const sections = screen.getByRole('combobox', { name: 'Settings section' })
    expect(sections).toHaveValue('appearance')
    await userEvent.selectOptions(sections, 'limits')
    expect(screen.getByRole('link', { name: 'Manage business limits' })).toBeInTheDocument()
    expect(sections).toHaveValue('limits')
  })
})

describe('Admin shell and shared appearance', () => {
  it('keeps settings and header theme controls synchronized', async () => {
    mount('appearance', true)
    await userEvent.click(screen.getByRole('button', { name: /Deep Charcoal Dark/ }))
    expect(document.documentElement).toHaveClass('dark-mode')
    expect(await screen.findByRole('button', { name: 'Switch to Light Theme' })).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Switch to Light Theme' }))
    await waitFor(() => expect(document.documentElement).not.toHaveClass('dark-mode'))
    expect(localStorage.getItem('theme')).toBe('light')
  })

  it('opens a complete mobile menu even when desktop rail mode was saved', async () => {
    localStorage.setItem('admin_sidebar_collapsed', 'true')
    Object.defineProperty(window, 'innerWidth', { configurable: true, value: 390 })
    mount('appearance', true)
    const sidebar = document.getElementById('admin-sidebar')
    expect(sidebar).not.toHaveClass('collapsed')
    const open = screen.getByRole('button', { name: 'Open navigation menu' })
    await userEvent.click(open)
    expect(sidebar).toHaveClass('open')
    expect(open).toHaveAttribute('aria-expanded', 'true')
    fireEvent.keyDown(document, { key: 'Escape' })
    expect(sidebar).not.toHaveClass('open')
  })

  it('focuses and contains the mobile drawer, then restores the trigger on Escape', async () => {
    Object.defineProperty(window, 'innerWidth', { configurable: true, value: 390 })
    mount('appearance', true)
    const sidebar = document.getElementById('admin-sidebar')
    expect(sidebar).toHaveAttribute('inert')
    expect(sidebar).toHaveAttribute('aria-hidden', 'true')
    const open = screen.getByRole('button', { name: 'Open navigation menu' })
    const user = userEvent.setup()
    await user.click(open)
    expect(screen.getByRole('dialog', { name: 'Admin Navigation' })).toHaveAttribute('aria-modal', 'true')
    const close = screen.getByRole('button', { name: 'Close navigation menu' })
    expect(close).toHaveFocus()
    expect(open.closest('.main-area')).toHaveAttribute('inert')
    await user.tab({ shift: true })
    expect(screen.getByRole('button', { name: 'Settings and profile menu' })).toHaveFocus()
    await user.tab()
    expect(close).toHaveFocus()
    await user.tab()
    expect(screen.getByRole('link', { name: 'Dashboard & Router' })).toHaveFocus()
    await user.keyboard('{Escape}')
    expect(open).toHaveFocus()
    expect(open).toHaveAttribute('aria-expanded', 'false')
    expect(sidebar).toHaveAttribute('inert')
    expect(open.closest('.main-area')).not.toHaveAttribute('inert')
  })

  it('offers a keyboard-accessible profile popover without fabricated gateway health', async () => {
    mount('appearance', true)
    const profile = screen.getByRole('button', { name: 'Settings and profile menu' })
    profile.focus()
    await userEvent.keyboard('{Enter}')
    expect(profile).toHaveAttribute('aria-expanded', 'true')
    expect(screen.getByText('BizID: BA-TEST01')).toBeInTheDocument()
    expect(screen.queryByText('Gateway Live')).not.toBeInTheDocument()
  })
})

describe('Telemetry preference consumers', () => {
  it('formats naive UTC API timestamps in the selected timezone', () => {
    expect(formatAdminTime('2026-10-29T06:30:00', 'UTC')).toContain('6:30:00')
    expect(formatAdminTime('2026-10-29T06:30:00', 'IST')).toContain('12:00:00')
    expect(formatAdminTime('invalid', 'UTC')).toBe('invalid')
  })

  it('refreshes at the chosen interval and stops when the telemetry page unmounts', async () => {
    vi.useFakeTimers()
    localStorage.setItem('admin_poll_interval', '5')
    localStorage.setItem('admin_time_format', 'UTC')
    Object.defineProperty(document, 'hidden', { configurable: true, value: false })
    const view = render(<AdminTelemetry />)
    await act(async () => {})
    expect(screen.getByText(/6:30:00/)).toBeInTheDocument()
    expect(auth.authFetch.mock.calls.filter(([url]) => url.includes('/admin/telemetry?'))).toHaveLength(1)
    await act(async () => vi.advanceTimersByTimeAsync(5000))
    expect(auth.authFetch.mock.calls.filter(([url]) => url.includes('/admin/telemetry?'))).toHaveLength(2)
    view.unmount()
    const calls = auth.authFetch.mock.calls.length
    await act(async () => vi.advanceTimersByTimeAsync(10000))
    expect(auth.authFetch).toHaveBeenCalledTimes(calls)
  })
})
