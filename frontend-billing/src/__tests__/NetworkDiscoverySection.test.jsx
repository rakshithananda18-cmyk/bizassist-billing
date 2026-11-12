import React from 'react'
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'

const session = vi.hoisted(() => ({ user: { public_id: 'BA-A' } }))
vi.mock('../contexts/AuthContext', () => ({ useAuth: () => session }))
vi.mock('../config', () => ({ CLOUD_URL: 'https://cloud.test', IS_LOCAL_APP: false }))
import NetworkDiscoverySection from '../components/settings/NetworkDiscoverySection'

const CACHE = 'bizassist_discovered_local_url'
const healthy = { status: 'ok', db: 'connected', db_type: 'sqlite', version: 'test' }
const cache = (bizId, url) => localStorage.setItem(CACHE, JSON.stringify({ bizId, url, ts: Date.now() }))
beforeEach(() => {
  localStorage.clear()
  session.user = { public_id: 'BA-A' }
  localStorage.setItem('billing_user', JSON.stringify(session.user))
  vi.stubGlobal('location', { protocol: 'https:' })
  vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify(healthy), { status: 200 })))
})
afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.restoreAllMocks() })

it('does not offer or probe a cached insecure LAN address from the HTTPS workspace', () => {
  cache('BA-A', 'http://192.168.88.9:8001')
  render(<NetworkDiscoverySection networkMode="local" navigate={vi.fn()} />)
  expect(screen.getByText('Cloud', { exact: true })).toBeVisible()
  expect(screen.getByText(/This workspace uses the cloud backend/)).toBeVisible()
  expect(screen.queryByRole('button', { name: 'Test Connection' })).not.toBeInTheDocument()
  expect(screen.queryByText('http://192.168.88.9:8001')).not.toBeInTheDocument()
  expect(fetch).not.toHaveBeenCalled()
})

it('checks a compatible saved server only when explicitly requested', async () => {
  cache('BA-A', 'https://local.test:8001')
  render(<NetworkDiscoverySection networkMode="cloud" navigate={vi.fn()} />)
  expect(fetch).not.toHaveBeenCalled()
  fireEvent.click(screen.getByRole('button', { name: 'Test Connection' }))
  expect(await screen.findByText(/Reachable — .*mode: local · vtest/)).toBeVisible()
  expect(fetch.mock.calls[0][0]).toBe('https://local.test:8001/health')
  expect(fetch.mock.calls[0][1]).toMatchObject({ credentials: 'omit', redirect: 'error' })
  expect(screen.getByText('Cloud', { exact: true })).toBeVisible()
})

it('clears a previous business check and ignores its late response body after an account switch', async () => {
  let finishBody
  cache('BA-A', 'https://a.test')
  fetch.mockResolvedValue({ ok: true, json: () => new Promise(resolve => { finishBody = resolve }) })
  const view = render(<NetworkDiscoverySection networkMode="cloud" navigate={vi.fn()} />)
  fireEvent.click(screen.getByRole('button', { name: 'Test Connection' }))
  await waitFor(() => expect(finishBody).toBeTypeOf('function'))
  session.user = { public_id: 'BA-B' }
  localStorage.setItem('billing_user', JSON.stringify(session.user))
  view.rerender(<NetworkDiscoverySection networkMode="cloud" navigate={vi.fn()} />)
  await act(async () => { finishBody(healthy) })
  expect(screen.queryByText(/Reachable —/)).not.toBeInTheDocument()
  expect(screen.queryByText('https://a.test')).not.toBeInTheDocument()
  expect(screen.queryByRole('button', { name: 'Test Connection' })).not.toBeInTheDocument()
})

it('cancels a pending check when its saved server is cleared', async () => {
  let finishBody
  cache('BA-A', 'https://a.test')
  fetch.mockResolvedValue({ ok: true, json: () => new Promise(resolve => { finishBody = resolve }) })
  render(<NetworkDiscoverySection networkMode="cloud" navigate={vi.fn()} />)
  fireEvent.click(screen.getByRole('button', { name: 'Test Connection' }))
  await waitFor(() => expect(finishBody).toBeTypeOf('function'))
  fireEvent.click(screen.getByRole('button', { name: 'Clear saved server' }))
  await act(async () => { finishBody(healthy) })
  expect(localStorage.getItem(CACHE)).toBeNull()
  expect(screen.queryByText(/Reachable —/)).not.toBeInTheDocument()
})
