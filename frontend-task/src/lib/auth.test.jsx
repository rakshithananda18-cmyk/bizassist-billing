// @vitest-environment jsdom
import React, { StrictMode } from 'react'
import { act, cleanup, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const mocks = vi.hoisted(() => ({
  token: null, launch: {}, get: vi.fn(), post: vi.fn(), theme: vi.fn(), bridge: vi.fn(() => () => {}),
}))
vi.mock('./api', () => ({
  api: { get: mocks.get, post: mocks.post },
  tokenStore: { get: () => mocks.token, set: token => { mocks.token = token }, clear: () => { mocks.token = null } },
}))
vi.mock('./theme', () => ({ setThemeBusiness: mocks.theme }))
vi.mock('./billingBridge', () => ({ takeBillingLaunch: () => ({ ...mocks.launch }), startBillingBridge: mocks.bridge }))
let useAuth
let session
function Probe() {
  session = useAuth()
  return <><p>{session.loading ? 'Opening' : session.me?.public_id || 'Signed out'}</p><p>{session.notice}</p></>
}
const deferred = () => { let resolve; const promise = new Promise(done => { resolve = done }); return { promise, resolve } }

beforeEach(() => {
  vi.resetModules()
  mocks.token = null
  mocks.launch = { requested: false }
  mocks.get.mockReset()
  mocks.post.mockReset()
  mocks.theme.mockClear()
  mocks.bridge.mockClear()
})
afterEach(() => { cleanup(); vi.restoreAllMocks() })
async function mount(strict = false) {
  const module = await import('./auth')
  useAuth = module.useAuth
  const tree = <module.AuthProvider><Probe /></module.AuthProvider>
  return render(strict ? <StrictMode>{tree}</StrictMode> : tree)
}

describe('Billing business handoff', () => {
  it('refreshes Billing identity on return without resetting the same-business palette bridge', async () => {
    let now = 1000
    vi.spyOn(Date, 'now').mockImplementation(() => now)
    mocks.token = 'owner-token'
    mocks.get.mockResolvedValueOnce({ kind: 'owner', public_id: 'BA-ONE', business_name: 'Old name' })
    await mount()
    await screen.findByText('BA-ONE')
    await waitFor(() => expect(mocks.bridge.mock.calls.some(([identity]) => identity?.public_id === 'BA-ONE')).toBe(true))
    const bridges = mocks.bridge.mock.calls.length
    mocks.get.mockResolvedValue({ kind: 'owner', public_id: 'BA-ONE', business_name: 'Billing updated name' })
    now = 17000
    await act(async () => window.dispatchEvent(new Event('focus')))
    expect(session.me.business_name).toBe('Billing updated name')
    expect(mocks.bridge).toHaveBeenCalledTimes(bridges)
  })
  it('does not restore another stored business when the handoff fails', async () => {
    mocks.token = 'old-business-token'
    mocks.launch = { requested: true, ticket: 'expired', expectedBusiness: 'BA-NEW' }
    mocks.post.mockRejectedValue(new Error('Ticket expired; reopen from Billing'))
    await mount()
    await screen.findByText('Signed out')
    expect(mocks.token).toBeNull()
    expect(mocks.get).not.toHaveBeenCalled()
    expect(screen.getByText(/Ticket expired/)).toBeTruthy()
  })

  it('clears the previous business even when Billing could not obtain a ticket', async () => {
    mocks.token = 'old-business-token'
    mocks.launch = { requested: true, expectedBusiness: 'BA-NEW' }
    await mount()
    await screen.findByText(/Billing could not hand over/)
    expect(mocks.token).toBeNull()
    expect(mocks.get).not.toHaveBeenCalled()
    expect(mocks.post).not.toHaveBeenCalled()
  })

  it('exchanges once in StrictMode and opens only the verified matching business', async () => {
    mocks.launch = { requested: true, ticket: 'valid', expectedBusiness: 'BA-NEW' }
    mocks.post.mockResolvedValue({ token: 'new-business-token', public_id: 'BA-NEW' })
    mocks.get.mockResolvedValue({ kind: 'owner', public_id: 'BA-NEW' })
    await mount(true)
    await screen.findByText('BA-NEW')
    expect(mocks.post).toHaveBeenCalledTimes(1)
    expect(mocks.theme).toHaveBeenLastCalledWith('BA-NEW')
    expect(mocks.bridge).toHaveBeenLastCalledWith(expect.objectContaining({ public_id: 'BA-NEW' }), expect.objectContaining({ expectedBusiness: 'BA-NEW' }))
  })

  it('refuses a successful exchange that resolves to a different business', async () => {
    mocks.launch = { requested: true, ticket: 'wrong-db', expectedBusiness: 'BA-NEW' }
    mocks.post.mockResolvedValue({ token: 'wrong-business-token' })
    mocks.get.mockResolvedValue({ kind: 'owner', public_id: 'BA-OTHER' })
    await mount()
    await screen.findByText('Signed out')
    expect(screen.queryByText('BA-OTHER')).toBeNull()
    expect(mocks.token).toBeNull()
  })

  it('does not apply a delayed old-business profile after a new sign-in', async () => {
    const old = deferred()
    mocks.token = 'old-token'
    mocks.get.mockImplementationOnce(() => old.promise).mockResolvedValue({ kind: 'owner', public_id: 'BA-NEW' })
    mocks.post.mockResolvedValue({ token: 'new-token' })
    await mount()
    await waitFor(() => expect(mocks.get).toHaveBeenCalledTimes(1))
    await act(async () => session.ownerLogin('owner', 'password'))
    await screen.findByText('BA-NEW')
    await act(async () => old.resolve({ kind: 'owner', public_id: 'BA-OLD' }))
    expect(screen.getByText('BA-NEW')).toBeTruthy()
    expect(screen.queryByText('BA-OLD')).toBeNull()
  })
})
