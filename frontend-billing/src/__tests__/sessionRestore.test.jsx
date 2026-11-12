import React from 'react'
import { act, cleanup, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, afterEach, expect, it, vi } from 'vitest'

const discovery = vi.hoisted(() => vi.fn(async () => 'http://192.168.88.9:8001'))
vi.mock('../config', async original => ({
  ...(await original()), IS_LOCAL_APP: false, API_BASE: 'https://api.test', CLOUD_URL: 'https://api.test',
  getApiBase: () => 'https://api.test', updateApiBase: vi.fn(),
}))
vi.mock('../utils/networkDiscovery', () => ({ discoverLocalBackend: discovery, getNetworkMode: () => 'local', clearDiscoveryCache: vi.fn() }))
vi.mock('../utils/googleAuth', () => ({ renderGoogleButton: vi.fn() }))
import { AuthProvider, useAuth } from '../contexts/AuthContext'
import Login from '../pages/Login'
import { invalidateSessionRefresh } from '../api/session'
import { SESSION_EXPIRED_NOTICE } from '../utils/sessionExpiry'

let auth
const jwt = exp => `e30.${btoa(JSON.stringify({ exp, public_id: 'BA-SAVED', user_id: 7 }))}.synthetic`
const savedUser = { id: 7, user_id: 7, public_id: 'BA-SAVED', username: 'owner', role: 'enterprise' }
const response = body => new Response(JSON.stringify(body), { status: 200, headers: { 'Content-Type': 'application/json' } })
function Harness({ showLogin = false }) {
  auth = useAuth()
  if (auth.loading) return <span>Restoring</span>
  if (!auth.user) return showLogin ? <Login /> : <span>Sign in</span>
  return <span>Workspace ready</span>
}
const mount = showLogin => render(<MemoryRouter><AuthProvider><Harness showLogin={showLogin} /></AuthProvider></MemoryRouter>)
beforeEach(() => {
  localStorage.clear(); sessionStorage.clear(); invalidateSessionRefresh(); discovery.mockClear()
  vi.stubGlobal('fetch', vi.fn(async url => response(String(url).endsWith('/settings')
    ? { general: { hosting_mode: 'hybrid' }, subscription: { plan: 'pro' } }
    : String(url).endsWith('/profile') ? { public_id: 'BA-SAVED' }
      : String(url).endsWith('/business/config') ? { config: {}, attributes_schema: [] } : {})))
})
afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals() })

it('returns an expired saved web session to sign-in before protected loaders or refresh run', async () => {
  localStorage.setItem('billing_token', jwt(Math.floor(Date.now() / 1000) - 60))
  localStorage.setItem('billing_user', JSON.stringify(savedUser))
  localStorage.setItem('pos_draft_for_saved_owner', 'preserved draft')
  mount(true)
  await screen.findByText(SESSION_EXPIRED_NOTICE)
  expect(auth.user).toBeNull()
  expect(auth.token).toBeNull()
  expect(localStorage.getItem('billing_token')).toBeNull()
  expect(localStorage.getItem('billing_user')).toBeNull()
  expect(localStorage.getItem('pos_draft_for_saved_owner')).toBe('preserved draft')
  expect(fetch.mock.calls.some(([url]) => /\/auth\/refresh|\/profile$|\/settings$|\/business\/config$|\/realtime/.test(String(url)))).toBe(false)
  expect(discovery).not.toHaveBeenCalled()
})

it('restores an unexpired web session without making an automatic LAN handoff', async () => {
  localStorage.setItem('billing_token', jwt(Math.floor(Date.now() / 1000) + 24 * 3600))
  localStorage.setItem('billing_user', JSON.stringify(savedUser))
  mount()
  await screen.findByText('Workspace ready')
  expect(auth.networkMode).toBe('cloud')
  expect(auth.user.public_id).toBe('BA-SAVED')
  expect(discovery).not.toHaveBeenCalled()
  expect(fetch.mock.calls.some(([url]) => /192\.168|\/auth\/refresh/.test(String(url)))).toBe(false)
})

it('does not restore a saved identity without its credential', async () => {
  localStorage.setItem('billing_user', JSON.stringify(savedUser))
  mount()
  await screen.findByText('Sign in')
  expect(auth.user).toBeNull()
  expect(auth.token).toBeNull()
  expect(fetch).not.toHaveBeenCalled()
})

it('keeps a new web login on cloud even if discovery would find a LAN server', async () => {
  const nextToken = jwt(Math.floor(Date.now() / 1000) + 24 * 3600)
  mount()
  await screen.findByText('Sign in')
  await act(async () => { auth.setSession({ ...savedUser, token: nextToken, db_mode: 'cloud' }) })
  await waitFor(() => expect(auth.user?.public_id).toBe('BA-SAVED'))
  expect(auth.networkMode).toBe('cloud')
  expect(discovery).not.toHaveBeenCalled()
  expect(localStorage.getItem('bizassist_use_lan_db')).toBeNull()
})

it('handles a server-rejected saved session once and cancels sibling loaders', async () => {
  localStorage.setItem('billing_token', jwt(Math.floor(Date.now() / 1000) + 24 * 3600))
  localStorage.setItem('billing_user', JSON.stringify(savedUser))
  const fetch = vi.fn(async () => new Response(JSON.stringify({ detail: 'Account session was revoked' }), {
    status: 401, headers: { 'Content-Type': 'application/json', 'WWW-Authenticate': 'Bearer error="invalid_token"' },
  }))
  vi.stubGlobal('fetch', fetch)
  const notices = vi.fn()
  window.addEventListener('show_toast', notices)
  mount()
  await waitFor(() => expect(auth.user).toBeNull())
  await screen.findByText('Sign in')
  expect(auth.sessionNotice).toBe(SESSION_EXPIRED_NOTICE)
  expect(localStorage.getItem('billing_token')).toBeNull()
  expect(fetch.mock.calls.some(([url]) => String(url).endsWith('/auth/refresh'))).toBe(false)
  expect(notices.mock.calls.filter(([event]) => event.detail?.msg === 'Session expired. Please log in again.')).toHaveLength(1)
  const completedReads = fetch.mock.calls.length
  act(() => window.dispatchEvent(new Event('focus')))
  expect(fetch).toHaveBeenCalledTimes(completedReads)
  window.removeEventListener('show_toast', notices)
})
