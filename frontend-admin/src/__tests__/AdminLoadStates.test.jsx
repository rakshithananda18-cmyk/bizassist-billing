import React from 'react'
import { act, cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { MemoryRouter } from 'react-router-dom'
import AdminDashboard from '../pages/admin/AdminDashboard'
import AdminBusinesses from '../pages/admin/AdminBusinesses'
import AdminUsage from '../pages/admin/AdminUsage'
import AdminMetrics from '../pages/admin/AdminMetrics'

const auth = vi.hoisted(() => ({ authFetch: vi.fn(), adminUser: { username: 'qa-admin' }, adminLogout: vi.fn() }))
vi.mock('../contexts/AuthContext', () => ({ useAuth: () => auth }))
vi.mock('../contexts/DialogContext', () => ({ useDialog: () => ({ showAlert: vi.fn(), showConfirm: vi.fn(), showError: vi.fn() }) }))
const response = data => ({ ok: true, json: async () => data })
const deferred = () => { let resolve; const promise = new Promise(done => { resolve = done }); return { promise, resolve } }
const business = name => ({ id: 1, username: 'qa-merchant', business_name: name, bizid: 'BA-QATEST', total_revenue: 1200, upload_count: 3, inventory_count: 4, invoice_count: 2 })
const usage = name => ({ username: 'qa-merchant', business_name: name, queries_today: 2, queries_limit: 10, tokens_today: 200, tokens_limit: 1000, complex_today: 1, complex_limit: 2, requests_per_minute: 5 })
const metrics = name => ({
  activity: { total: 4, active_7d: 2, active_30d: 3 }, plan_mix: { free: 2, pro: 2 },
  funnel: { registered: 4, first_invoice: 3, ten_invoices: 2, sync_enabled: 2, used_ai: 1 },
  churn_risk: [{ business_id: 1, business_name: name, bizid: 'BA-QATEST', plan: 'free', invoice_count: 5, days_silent: 20 }],
  expiring_within_14d: [],
})

const pages = [
  { name: 'overview', Component: AdminDashboard, path: '/admin/businesses', good: [business('QA merchant')], updated: [{ ...business('QA merchant'), total_revenue: 2400 }], marker: '₹1,200', updatedMarker: '₹2,400', refresh: 'Refresh overview', retry: 'Retry overview', empty: 'Registered Businesses' },
  { name: 'directory', Component: AdminBusinesses, path: '/admin/businesses', good: [business('QA merchant')], updated: [business('QA updated merchant')], marker: 'QA merchant', updatedMarker: 'QA updated merchant', refresh: 'Refresh directory', retry: 'Retry directory', empty: 'No enterprise businesses registered yet.' },
  { name: 'usage', Component: AdminUsage, path: '/admin/usage-stats', good: [usage('QA merchant')], updated: [usage('QA updated merchant')], marker: 'QA merchant', updatedMarker: 'QA updated merchant', refresh: 'Refresh Stats', retry: 'Retry usage', empty: 'No usage data logged yet today.' },
  { name: 'metrics', Component: AdminMetrics, path: '/admin/metrics', good: metrics('QA merchant'), updated: metrics('QA updated merchant'), marker: 'QA merchant', updatedMarker: 'QA updated merchant', refresh: 'Refresh', retry: 'Retry metrics', empty: 'No businesses at churn risk right now.' },
]

beforeEach(() => { auth.authFetch.mockReset() })
afterEach(() => { cleanup(); vi.restoreAllMocks() })

function serve(page, responses) {
  auth.authFetch.mockImplementation(url => {
    if (url.endsWith('/admin/router-mode')) return Promise.resolve(response({ mode: 'legacy' }))
    if (url.endsWith(page.path)) return Promise.resolve(responses.shift())
    throw new Error(`Unexpected test request: ${url}`)
  })
}
function mount(Component, strict = false) {
  const content = <MemoryRouter><Component /></MemoryRouter>
  return render(strict ? <React.StrictMode>{content}</React.StrictMode> : content)
}

describe.each(pages)('Admin $name load state', page => {
  it.each([
    ['HTTP failure', { ok: false }],
    ['malformed HTTP 200 response', response({ message: 'not a data payload' })],
  ])('shows a retryable %s without inventing a zero or empty result', async (_, failure) => {
    serve(page, [failure, response(page.good)])
    mount(page.Component)
    expect(await screen.findByRole('alert')).toHaveTextContent('could not be loaded')
    expect(screen.queryByText(page.empty)).not.toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: page.retry, exact: true }))
    await screen.findByText(page.marker, { exact: true })
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('retains known data with a stale-data notice after a failed refresh and recovers on retry', async () => {
    serve(page, [response(page.good), { ok: false }, response(page.updated)])
    mount(page.Component)
    await screen.findByText(page.marker, { exact: true })
    await userEvent.click(screen.getByRole('button', { name: page.refresh, exact: true }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Showing the last loaded')
    expect(screen.getByText(page.marker, { exact: true })).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: page.retry, exact: true }))
    await screen.findByText(page.updatedMarker, { exact: true })
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('ignores an older request after StrictMode starts a newer load', async () => {
    const oldRequest = deferred()
    serve(page, [oldRequest.promise, response(page.good)])
    mount(page.Component, true)
    await screen.findByText(page.marker, { exact: true })
    await act(async () => oldRequest.resolve({ ok: false }))
    expect(screen.getByText(page.marker, { exact: true })).toBeInTheDocument()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })
})

it('renders finite percentages when saved usage quotas are zero', async () => {
  const record = { ...usage('Zero quota business'), queries_today: 0, queries_limit: 0, tokens_today: 0, tokens_limit: 0, complex_today: 1, complex_limit: 0 }
  serve(pages[2], [response([record])])
  const view = mount(AdminUsage)
  await screen.findByText('Zero quota business')
  expect(screen.getAllByText('0% used')).toHaveLength(2)
  expect(screen.getByText('100% used')).toBeInTheDocument()
  expect(view.container.innerHTML).not.toContain('NaN')
  expect(view.container.innerHTML).not.toContain('Infinity')
})
