/*
 * Bug condition exploration, task 1.7 (C11). Property 1 (bug condition) and Property 12
 * (admin console reliability). Clause 1.45, expected 2.45.
 *
 * These cases encode the expected behaviour and must FAIL on the unfixed code.
 * Expected counterexamples, read from src/pages/admin/AdminInfrastructure.jsx:
 *   - With cpu_percent, memory, thread_count and region null (and listed in `unavailable`),
 *     the page invents values: CPU Utilization "0%", Process Memory (RSS) "0 MB" and Region
 *     "asia-south1 (Mumbai)". No row says "unavailable".
 *   - autoRefresh starts true, so a 15 s interval requests /admin/infrastructure-metrics
 *     again: 5 requests after 65 s instead of 1.
 *   - A 503 with {"detail": "Platform administration service is not configured"} shows the
 *     "Cloud Run Telemetry Endpoint Pending Deployment" banner with "(Telemetry service
 *     returned HTTP 503)" but never the detail, in a plain div without role="alert", and the
 *     tiles below show invented healthy values (asia-south1 (Mumbai), CONNECTED,
 *     BOM1 (Mumbai Edge)).
 * The error case follows the console's existing load-error pattern (role="alert" with a
 * Retry button, as on the Overview, Directory, Usage and Metrics pages), which 2.45 names.
 *
 * Run in frontend-admin: npx vitest run --pool=threads --reporter=dot, then npm run lint.
 */
import { act, cleanup, render, screen, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import AdminInfrastructure from '../pages/admin/AdminInfrastructure'
import { DialogProvider } from '../contexts/DialogContext'

const auth = vi.hoisted(() => ({ authFetch: vi.fn(), adminUser: { username: 'operator', role: 'admin' }, adminLogout: vi.fn(), loading: false }))
vi.mock('../contexts/AuthContext', () => ({ useAuth: () => auth }))

// The metrics response of an image without psutil and without CLOUD_RUN_REGION (C12.1).
const METRICS_WITH_GAPS = {
  status: 'ok',
  timestamp: '2026-11-07T06:30:00+00:00',
  unavailable: ['cpu_percent', 'memory', 'thread_count', 'region'],
  cloud_run: {
    provider: 'Google Cloud Run', service_name: 'staterbill-api', revision: 'staterbill-api-00042-abc',
    region: null, status: 'ACTIVE', role: 'Primary Production Backend', uptime_seconds: 3600,
    memory: null, cpu_percent: null, thread_count: null, python_version: '3.12.4', platform: 'linux',
  },
  huggingface: null,
  supabase: {
    provider: 'Supabase PostgreSQL', dialect: 'postgresql', status: 'CONNECTED', size_str: '48 MB', size_bytes: 50331648,
    connection_pool: { active: 2, idle: 3, total: 5, max: 60, utilization_pct: 8.3 },
    cache_hit_ratio_pct: 97.1,
    table_counts: { users: 12, invoices: 340, products: 88, payments: 120, audit_logs: 410 },
  },
  vercel: {
    provider: 'Vercel Edge Global Network', status: 'ONLINE',
    endpoints: [{ name: 'StaterBill Web Application', domain: 'staterbill.com', url: 'https://staterbill.com', status: 'ONLINE', latency_ms: 120, edge_pop: 'bom1', code: 200 }],
  },
}
const reply = (status, body) => ({
  ok: status >= 200 && status < 300, status, headers: new Headers({ 'content-type': 'application/json' }),
  json: async () => body, text: async () => JSON.stringify(body),
})
const metricsRequests = () => auth.authFetch.mock.calls.filter(([url]) => String(url).includes('/admin/infrastructure-metrics'))
const mount = () => render(<DialogProvider><MemoryRouter><AdminInfrastructure /></MemoryRouter></DialogProvider>)
const rowOf = label => screen.getByText(label).parentElement

beforeEach(() => { auth.authFetch.mockReset() })
afterEach(() => { cleanup(); vi.useRealTimers() })

describe('Infrastructure page (1.45)', () => {
  it('shows "unavailable" for a metric the server could not read', async () => {
    auth.authFetch.mockImplementation(async () => reply(200, METRICS_WITH_GAPS))
    mount()
    await screen.findByText('CPU Utilization')
    expect(rowOf('CPU Utilization')).toHaveTextContent(/unavailable/i)
    expect(rowOf('CPU Utilization')).not.toHaveTextContent('0%')
    expect(rowOf('Process Memory (RSS)')).toHaveTextContent(/unavailable/i)
    expect(rowOf('Process Memory (RSS)')).not.toHaveTextContent('0 MB')
    expect(rowOf('Region')).toHaveTextContent(/unavailable/i)
    expect(rowOf('Region')).not.toHaveTextContent('asia-south1')
  })

  it('does not refresh on its own by default', async () => {
    vi.useFakeTimers()
    auth.authFetch.mockImplementation(async () => reply(200, METRICS_WITH_GAPS))
    mount()
    await act(async () => { await vi.advanceTimersByTimeAsync(0) })
    expect(metricsRequests()).toHaveLength(1)
    await act(async () => { await vi.advanceTimersByTimeAsync(65_000) })
    expect(metricsRequests()).toHaveLength(1)
  })

  it('shows the HTTP status and detail of a failed request in a retryable alert, without invented values', async () => {
    auth.authFetch.mockImplementation(async () => reply(503, { detail: 'Platform administration service is not configured' }))
    mount()
    const [detail] = await screen.findAllByText(/Platform administration service is not configured/)
    const alert = detail.closest('[role="alert"]')
    expect(alert).not.toBeNull()
    expect(alert).toHaveTextContent('503')
    expect(within(alert).getByRole('button', { name: /retry/i })).toBeInTheDocument()
    expect(screen.queryByText(/Pending Deployment/)).not.toBeInTheDocument()
    for (const invented of ['asia-south1 (Mumbai)', 'CONNECTED', 'BOM1 (Mumbai Edge)']) {
      expect(screen.queryAllByText(invented)).toHaveLength(0)
    }
  })
})
