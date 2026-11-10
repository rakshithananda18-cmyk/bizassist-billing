/*
 * Bug condition exploration, task 1.7 (C11). Property 1 (bug condition) and Property 6.
 * Clause 1.15, expected 2.15.
 *
 * These cases encode the expected behaviour and must FAIL on the unfixed code.
 * Expected counterexamples, read from src/contexts/AuthContext.jsx:
 *   - With ?sso=<ticket> and a stored session for business BA-OLD, a refused redemption
 *     (401 from /redeem-ticket) or a network error is only logged ("[SSO] Ticket redemption
 *     rejected by server" / "... failed"). initAuth then falls back to localStorage, so
 *     user = { username: 'other-owner', public_id: 'BA-OLD', ... } is restored and `user`
 *     and `biz_name` stay in localStorage: clearSession() is never called.
 *   - Without a stored session the app lands on the Login page with no message: no element
 *     says "Billing could not sign you in. Open Dashboard BIZASSIST from Billing again, or
 *     sign in here."
 *
 * Run in frontend-ai: npx vitest run --pool=threads --reporter=dot
 */
import { cleanup, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import App from '../App'
import { AuthProvider, useAuth } from '../contexts/AuthContext'

const OTHER_BUSINESS = { username: 'other-owner', role: 'owner', token: 'other-business-token', public_id: 'BA-OLD', business_name: 'Old Traders' }
let current
let fetchMock

function Probe() {
  current = useAuth()
  return <p>{current.loading ? 'loading' : current.user?.username || 'signed out'}</p>
}

function reply(url, status, body) {
  const res = new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
  Object.defineProperty(res, 'url', { value: url })
  return res
}
const failures = {
  'a refused ticket (401)': url => reply(url, 401, { detail: 'Invalid or expired ticket' }),
  'a network error': async () => { throw new TypeError('Failed to fetch') },
}
function serve(redeem) {
  fetchMock = vi.fn(async input => {
    const url = String(input)
    return url.endsWith('/redeem-ticket') ? redeem(url) : reply(url, 200, {})
  })
  vi.stubGlobal('fetch', fetchMock)
}
const redemptions = () => fetchMock.mock.calls.filter(([input]) => String(input).endsWith('/redeem-ticket'))

beforeEach(() => {
  localStorage.clear()
  window.history.replaceState({}, '', '/?sso=billing-ticket')
  // jsdom has no matchMedia (the Login page reads it) and no real scrollTo.
  vi.stubGlobal('matchMedia', vi.fn(() => ({ matches: false, addEventListener: vi.fn(), removeEventListener: vi.fn(), addListener: vi.fn(), removeListener: vi.fn() })))
  vi.stubGlobal('scrollTo', vi.fn())
})
afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
  localStorage.clear()
  window.history.replaceState({}, '', '/')
})

describe('AI dashboard after a failed ?sso= redemption (1.15)', () => {
  it.each(Object.keys(failures))('clears the stored session of another business after %s', async failure => {
    localStorage.setItem('user', JSON.stringify(OTHER_BUSINESS))
    localStorage.setItem('biz_name', OTHER_BUSINESS.business_name)
    serve(failures[failure])
    render(<AuthProvider><Probe /></AuthProvider>)
    await waitFor(() => expect(current.loading).toBe(false))
    expect(redemptions().length).toBeGreaterThan(0)
    expect(current.user).toBeNull()
    expect(localStorage.getItem('user')).toBeNull()
    expect(localStorage.getItem('biz_name')).toBeNull()
  })

  it('tells the owner that Billing could not sign them in and offers a way to sign in', async () => {
    serve(failures['a refused ticket (401)'])
    render(<App />)
    const messages = await screen.findAllByText(/Billing could not sign you in/)
    expect(messages.length).toBeGreaterThan(0)
    expect(screen.getAllByRole('button', { name: /sign in/i }).length).toBeGreaterThan(0)
  })
})
