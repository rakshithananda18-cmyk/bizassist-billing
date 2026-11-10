import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
const accepted = vi.hoisted(() => vi.fn())
vi.mock('./theme', () => ({
  acceptBillingAppearance: accepted,
  sanitizeBillingUrl: value => value === 'http://localhost:5174' ? value : null,
}))
import { startBillingBridge, takeBillingLaunch } from './billingBridge'
let handlers
let opener
let replaceState
beforeEach(() => {
  accepted.mockReset()
  handlers = new Map()
  opener = { postMessage: vi.fn() }
  replaceState = vi.fn()
  vi.stubGlobal('window', {
    opener, location: { href: 'http://localhost:5176/?from_billing=1&sso=one-use&billing_origin=http%3A%2F%2Flocalhost%3A5174&billing_business=BA-1&billing_launch=launch-1' },
    history: { state: {}, replaceState },
    addEventListener: (name, fn) => handlers.set(name, fn), removeEventListener: name => handlers.delete(name),
  })
})
afterEach(() => vi.unstubAllGlobals())
describe('verified Billing appearance bridge', () => {
  it('removes the handoff and context from the URL before returning them', () => {
    expect(takeBillingLaunch()).toEqual({ ticket: 'one-use', origin: 'http://localhost:5174', expectedBusiness: 'BA-1', launchId: 'launch-1', requested: true })
    expect(String(replaceState.mock.calls[0][2])).toBe('http://localhost:5176/')
  })
  it('accepts only the opener, trusted origin, current launch and authenticated business', () => {
    const launch = takeBillingLaunch()
    const close = startBillingBridge({ kind: 'owner', public_id: 'BA-1' }, launch)
    const message = { source: opener, origin: launch.origin, data: { type: 'BIZASSIST_FIELD_APPEARANCE', launchId: 'launch-1', appearance: { businessId: 'BA-1' } } }
    const receive = handlers.get('message')
    receive({ ...message, source: {} })
    receive({ ...message, origin: 'https://attacker.test' })
    receive({ ...message, data: { ...message.data, launchId: 'old' } })
    receive({ ...message, data: { ...message.data, appearance: { businessId: 'BA-2' } } })
    expect(accepted).not.toHaveBeenCalled()
    receive(message)
    expect(accepted).toHaveBeenCalledWith({ businessId: 'BA-1', billingUrl: launch.origin })
    close()
    expect(handlers.has('message')).toBe(false)
  })
  it('does not expose owner workspace messaging to staff or a mismatched business', () => {
    startBillingBridge({ kind: 'staff', public_id: 'BA-1' }, takeBillingLaunch())
    startBillingBridge({ kind: 'owner', public_id: 'BA-2' }, takeBillingLaunch())
    expect(opener.postMessage).not.toHaveBeenCalled()
  })
})
