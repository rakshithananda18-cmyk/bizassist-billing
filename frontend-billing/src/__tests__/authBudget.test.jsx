import React from 'react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { act, cleanup, render } from '@testing-library/react'
vi.mock('../config', async original => ({
  ...(await original()), IS_LOCAL_APP: false, API_BASE: 'https://api.test',
  getApiBase: () => 'https://api.test',
}))
vi.mock('../utils/networkDiscovery', () => ({ discoverLocalBackend: async () => null, getNetworkMode: () => 'cloud', clearDiscoveryCache: vi.fn() }))
import { AuthProvider, useAuth } from '../contexts/AuthContext'
let auth
function Harness() { auth = useAuth(); return null }
beforeEach(() => { localStorage.clear(); sessionStorage.clear(); vi.useFakeTimers() })
afterEach(() => { cleanup(); vi.useRealTimers(); vi.unstubAllGlobals(); vi.restoreAllMocks() })
const pendingUntilAbort = options => new Promise((_, reject) => options.signal.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError'))))

it('lets a web sign-in outlive the old eight-second limit and bounds the cold-start wait', async () => {
  vi.stubGlobal('fetch', vi.fn((url, options) => pendingUntilAbort(options)))
  render(<AuthProvider><Harness /></AuthProvider>)
  let message
  const done = auth.login('owner', 'password').catch(error => { message = error.message })
  await act(async () => { await vi.advanceTimersByTimeAsync(8000) })
  expect(message).toBeUndefined()
  await act(async () => { await vi.advanceTimersByTimeAsync(57000); await done })
  expect(message).toBe('The server did not respond. Check your connection and try again.')
})

it('recovers a signup that committed before the response was lost', async () => {
  const user = { token: 'created-account-token', public_id: 'BA-RECOVERED', user_id: 7, username: 'owner', role: 'owner' }
  const fetch = vi.fn((url, options) => {
    if (url.endsWith('/signup')) return pendingUntilAbort(options)
    if (url.endsWith('/login')) return Promise.resolve(new Response(JSON.stringify(user), { status: 200 }))
    return Promise.resolve(new Response(JSON.stringify({ general: {}, subscription: { plan: 'pro' } }), { status: 200 }))
  })
  vi.stubGlobal('fetch', fetch)
  render(<AuthProvider><Harness /></AuthProvider>)
  let completed = false
  const done = auth.signup({ username: 'owner', password: 'Password1', business_name: 'Mine' }).then(() => { completed = true })
  await act(async () => { await vi.advanceTimersByTimeAsync(65000); await done })
  expect(completed).toBe(true)
  expect(localStorage.getItem('billing_token')).toBe(user.token)
  const signupCalls = fetch.mock.calls.filter(([url]) => url.endsWith('/signup'))
  expect(signupCalls).toHaveLength(1)
  expect(signupCalls[0][1].headers['X-Client-Request-Id']).toBeTruthy()
})
