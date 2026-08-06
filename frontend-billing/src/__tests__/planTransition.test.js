// Free → Pro without a re-login: only the RISING EDGE may fire.
//
// The effect this guards re-runs the cloud divergence check and clears the sync
// nudge's 4h snooze. Getting the edge wrong is not cosmetic: a false positive on
// every settings poll would re-open a modal the owner just dismissed, and a
// false positive on first load would do it to every Pro user on every login.
import { describe, it, expect } from 'vitest'
import { isUpgradeToPro } from '../utils/planTransition'

describe('isUpgradeToPro', () => {
  it('fires when a free account becomes Pro', () => {
    expect(isUpgradeToPro('free', 'pro')).toBe(true)
  })

  it('does not fire on the first settings fetch', () => {
    // `undefined` means "not loaded yet", not "free". Reading it as free makes
    // an ordinary Pro login indistinguishable from a purchase.
    expect(isUpgradeToPro(undefined, 'pro')).toBe(false)
    expect(isUpgradeToPro(null, 'pro')).toBe(false)
  })

  it('does not fire on the 5-minute poll', () => {
    // The poll re-renders with the same value; an edge here would re-run the
    // divergence check every tick for the life of the session.
    expect(isUpgradeToPro('pro', 'pro')).toBe(false)
  })

  it('does not fire when a plan lapses', () => {
    expect(isUpgradeToPro('pro', 'free')).toBe(false)
    expect(isUpgradeToPro('pro', undefined)).toBe(false)
  })

  it('stays quiet while an account remains free', () => {
    expect(isUpgradeToPro('free', 'free')).toBe(false)
    expect(isUpgradeToPro('free', undefined)).toBe(false)
  })

  it('treats any non-pro previous value as free', () => {
    // The backend has only ever sent 'free' | 'pro', but a missing subscription
    // object yields ''. Anything that is not 'pro' was not paying.
    expect(isUpgradeToPro('', 'pro')).toBe(true)
    expect(isUpgradeToPro('trial', 'pro')).toBe(true)
  })
})
