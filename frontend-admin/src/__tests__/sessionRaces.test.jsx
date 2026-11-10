import { StrictMode } from 'react'
import { act, cleanup, render, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { AuthProvider, useAuth } from '../contexts/AuthContext'
import { API_BASE } from '../config'

let current
const owner = { username: 'owner', public_id: 'BA-ONE', token: 'owner-token', role: 'enterprise' }
function Probe() { current = useAuth(); return <div>{current.user?.username || 'signed out'}</div> }
const response = (status, body, headers = {}) => new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json', ...headers } })
beforeEach(() => { localStorage.clear(); sessionStorage.clear(); window.history.replaceState({}, '', '/') })
afterEach(() => { cleanup(); vi.unstubAllGlobals(); localStorage.clear(); sessionStorage.clear(); window.history.replaceState({}, '', '/') })
describe('session and hand-off races', () => {
  it('redeems the URL ticket once across StrictMode effects', async () => {
    window.history.replaceState({}, '', '/?sso=one-use')
    let resolve
    const pending = new Promise(done => { resolve = done })
    const fetcher = vi.fn(() => pending)
    vi.stubGlobal('fetch', fetcher)
    render(<StrictMode><AuthProvider><Probe /></AuthProvider></StrictMode>)
    await act(async () => resolve(response(200, owner)))
    await waitFor(() => expect(current.user?.username).toBe('owner'))
    expect(fetcher).toHaveBeenCalledTimes(1)
    expect(window.location.search).not.toContain('sso=')
  })
  it('ignores a slow ticket after a logout from the trusted opener', async () => {
    let resolve
    const pending = new Promise(done => { resolve = done })
    const opener = {}
    vi.stubGlobal('opener', opener)
    vi.stubGlobal('fetch', vi.fn(() => pending))
    render(<AuthProvider><Probe /></AuthProvider>)
    await act(async () => window.dispatchEvent(new MessageEvent('message', { source: opener, origin: 'https://staterbill.com', data: { type: 'SSO_TICKET', ticket: 'one-use' } })))
    await act(async () => window.dispatchEvent(new MessageEvent('message', { source: opener, origin: 'https://staterbill.com', data: { type: 'AUTH_LOGOUT' } })))
    await act(async () => resolve(response(200, owner)))
    expect(current.user).toBeNull()
    expect(localStorage.getItem('user')).toBeNull()
  })
  it.each([false, true])('only ends the session for an explicit rejection marker: %s', async marked => {
    localStorage.setItem('user', JSON.stringify(owner))
    vi.stubGlobal('fetch', vi.fn(async url => String(url).endsWith('/auth/refresh')
      ? response(503, { detail: 'Starting' })
      : response(401, { detail: 'Not authenticated' }, marked ? { 'WWW-Authenticate': 'Bearer error="invalid_token"' } : {})))
    render(<AuthProvider><Probe /></AuthProvider>)
    await waitFor(() => expect(current.user?.username).toBe('owner'))
    await act(async () => { await current.authFetch(`${API_BASE}/profile`) })
    expect(current.user === null).toBe(marked)
  })
})

