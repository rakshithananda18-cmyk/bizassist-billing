// @vitest-environment jsdom
/*
 * Bug condition exploration, task 1.7 (C10). Property 1 (bug condition). Clause 1.3
 * (and the guard that 1.2 turns off), expected 2.3.
 *
 * This file is the auth.test.jsx case of the plan. It sits next to auth.test.jsx because
 * that file mocks ./theme and ./billingBridge for every case, and the defect lives in
 * those two modules: here only fetch is replaced, and the launch goes through the real
 * takeBillingLaunch() and sanitizeBillingUrl().
 *
 * These cases encode the expected behaviour and must FAIL on the unfixed code.
 * Expected counterexample, read from src/lib/billingBridge.js, src/lib/theme.js and
 * src/lib/auth.jsx: Billing at https://staterbill.com (or www) opens
 * /?from_billing=1&billing_origin=<origin>&billing_launch=launch-1&billing_business=BA-NEW
 * without sso. sanitizeBillingUrl(<origin>) is null, so takeBillingLaunch() returns
 * { origin: null, expectedBusiness: null, requested: false }. AuthProvider then calls
 * refresh(): GET /api/auth/me runs with the stored token of BA-OLD, the page opens BA-OLD,
 * 'task_token' stays 'old-business-token', and no notice names BA-NEW.
 *
 * Run in frontend-task: npx vitest run --pool=threads --reporter=dot
 */
import React from 'react'
import { cleanup, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

let session
let fetchMock
const reply = (status, body) => ({
  ok: status >= 200 && status < 300, status, headers: new Headers({ 'content-type': 'application/json' }),
  text: async () => JSON.stringify(body), json: async () => body,
})
const profileRequests = () => fetchMock.mock.calls.filter(([url]) => String(url).endsWith('/api/auth/me'))

beforeEach(() => {
  vi.resetModules()
  localStorage.clear()
  localStorage.setItem('task_token', 'old-business-token')
  fetchMock = vi.fn(async url => (String(url).endsWith('/api/auth/me')
    ? reply(200, { kind: 'owner', public_id: 'BA-OLD', business_name: 'Old Traders' })
    : reply(404, { detail: 'Not Found' })))
  vi.stubGlobal('fetch', fetchMock)
})
afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
  localStorage.clear()
  window.history.replaceState(null, '', '/')
})

// The launch is read once, when lib/auth.jsx is imported, as in the real page.
async function openFromBilling(origin) {
  const launch = new URLSearchParams({ from_billing: '1', billing_origin: origin, billing_launch: 'launch-1', billing_business: 'BA-NEW' })
  window.history.replaceState(null, '', `/?${launch}`)
  const { AuthProvider, useAuth } = await import('./auth')
  function Probe() {
    session = useAuth()
    return <><p>{session.loading ? 'Opening' : session.me?.public_id || 'Signed out'}</p><p>{session.notice}</p></>
  }
  return render(<AuthProvider><Probe /></AuthProvider>)
}

describe('Field Team opened from Billing at staterbill.com without a ticket (1.3)', () => {
  it.each(['https://staterbill.com', 'https://www.staterbill.com'])('clears the stored session and asks for the named business when %s sends no ticket', async origin => {
    await openFromBilling(origin)
    await waitFor(() => expect(session.loading).toBe(false))
    expect(localStorage.getItem('task_token')).toBeNull()
    expect(profileRequests()).toHaveLength(0)
    expect(screen.queryByText('BA-OLD')).toBeNull()
    expect(screen.getByText('Sign in with the Billing account for BA-NEW to continue.')).toBeTruthy()
  })
})
