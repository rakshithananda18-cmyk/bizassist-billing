import React from 'react'
import { cleanup, render, screen, within } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
vi.mock('../config', () => ({ API_BASE: 'http://localhost:8001', CLOUD_URL: 'https://cloud.test', IS_LOCAL_APP: true }))
vi.mock('../utils/telemetry', () => ({ sendDiagnostics: vi.fn() }))
import BootHealthCheck from '../components/BootHealthCheck'

const response = body => ({ ok: true, headers: { get: () => null }, json: async () => body })
const row = label => within(screen.getByText(label).closest('div'))
beforeEach(() => {
  vi.stubGlobal('fetch', vi.fn(async () => response({ status: 'ok', db: 'connected', db_type: 'sqlite', version: '1.2.6' })))
})
afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.restoreAllMocks() })

it('shows the active endpoint and actual server/database details', async () => {
  render(<BootHealthCheck />)
  await screen.findByText('sqlite · Version 1.2.6')
  expect(screen.getByText('Active server: http://localhost:8001')).toBeInTheDocument()
  expect(row('Database connection').getByText('✓')).toBeInTheDocument()
  expect(fetch.mock.calls.map(([url]) => url)).toEqual(['http://localhost:8001/health', 'https://cloud.test/health'])
})

it('treats HTTP-200 database failures as unhealthy', async () => {
  fetch.mockResolvedValue(response({ status: 'error', db: 'disconnected' }))
  render(<BootHealthCheck />)
  await screen.findAllByText('DB disconnected')
  expect(row("This device's backend").getByText('✕')).toBeInTheDocument()
  expect(row('Database connection').getByText('✕')).toBeInTheDocument()
})

it('shows local server details while an optional cloud check is still pending', async () => {
  fetch.mockImplementation((url, { signal }) => String(url).startsWith('http://localhost')
    ? Promise.resolve(response({ status: 'ok', db: 'connected', db_type: 'sqlite', version: '1.2.6' }))
    : new Promise((resolve, reject) => {
      signal.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')), { once: true })
    }))
  render(<BootHealthCheck />)
  await screen.findByText('sqlite · Version 1.2.6')
  expect(row('Database connection').getByText('✓')).toBeInTheDocument()
  expect(row('Cloud server (for sync)').getByText('checking…')).toBeInTheDocument()
})

it('does not claim a verified database connection when the server is unreachable', async () => {
  fetch.mockRejectedValue(new TypeError('Network blocked'))
  render(<BootHealthCheck />)
  await screen.findAllByText('Network blocked')
  expect(row('Database connection').getByText('Not verified')).toBeInTheDocument()
  expect(row('Database connection').queryByText('✓')).toBeNull()
})

it.each([{}, { status: 'unknown' }, null])('rejects an invalid successful health payload: %j', async body => {
  fetch.mockResolvedValue(response(body))
  render(<BootHealthCheck />)
  await screen.findAllByText('Server returned an invalid health response.')
  expect(row('Database connection').getByText('Not verified')).toBeInTheDocument()
})

it('cancels pending health requests when details close', () => {
  fetch.mockImplementation((url, { signal }) => new Promise((resolve, reject) => {
    signal.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')), { once: true })
  }))
  const { unmount } = render(<BootHealthCheck />)
  const signals = fetch.mock.calls.map(([, options]) => options.signal)
  expect(signals).toHaveLength(2)
  unmount()
  expect(signals.every(signal => signal.aborted)).toBe(true)
})
