/**
 * Regression: free user logs in first (device mode 'local'), then the Pro
 * owner logs in on the same install — the stale device-global
 * `bizassist_hosting_mode` hid the sidebar sync/refresh panel and got PUT
 * back onto the Pro account by the fetchSettings reconcile.
 * See utils/deviceMode.js.
 */
import { describe, it, expect, beforeEach } from 'vitest'
import { reconcileDeviceModeOnLogin } from '../utils/deviceMode'

const MODE = 'bizassist_hosting_mode'
const OWNER = 'bizassist_device_mode_owner'

describe('reconcileDeviceModeOnLogin', () => {
  beforeEach(() => {
    localStorage.clear()
  })

  it('clears a stale non-cloud mode when a different account logs in (free → pro switch)', () => {
    // Free user's session left device mode 'local'
    localStorage.setItem(MODE, 'local')
    localStorage.setItem(OWNER, 'BIZ-FREE-1111')

    const cleared = reconcileDeviceModeOnLogin('BIZ-PRO-2222')

    expect(cleared).toBe('local')
    expect(localStorage.getItem(MODE)).toBeNull()           // account's server mode now wins
    expect(localStorage.getItem(OWNER)).toBe('BIZ-PRO-2222')
  })

  it('clears stale hybrid mode on account switch too', () => {
    localStorage.setItem(MODE, 'hybrid')
    localStorage.setItem(OWNER, 'BIZ-A')
    expect(reconcileDeviceModeOnLogin('BIZ-B')).toBe('hybrid')
    expect(localStorage.getItem(MODE)).toBeNull()
  })

  it("preserves 'cloud' on account switch (device routing — terminal has no local copy)", () => {
    localStorage.setItem(MODE, 'cloud')
    localStorage.setItem(OWNER, 'BIZ-A')
    expect(reconcileDeviceModeOnLogin('BIZ-B')).toBeNull()
    expect(localStorage.getItem(MODE)).toBe('cloud')
    expect(localStorage.getItem(OWNER)).toBe('BIZ-B')
  })

  it('keeps the device mode when the SAME account logs in again', () => {
    localStorage.setItem(MODE, 'hybrid')
    localStorage.setItem(OWNER, 'BIZ-A')
    expect(reconcileDeviceModeOnLogin('BIZ-A')).toBeNull()
    expect(localStorage.getItem(MODE)).toBe('hybrid')
  })

  it('keeps the mode for staff of the same business (shared BizID)', () => {
    localStorage.setItem(MODE, 'hybrid')
    localStorage.setItem(OWNER, 'BIZ-A') // owner logged in earlier
    expect(reconcileDeviceModeOnLogin('BIZ-A')).toBeNull() // cashier shares the BizID
    expect(localStorage.getItem(MODE)).toBe('hybrid')
  })

  it('clears an unowned stale mode on first login after upgrade (self-heals affected devices)', () => {
    // Device broken by the old bug: mode set, no owner stamp yet
    localStorage.setItem(MODE, 'local')
    expect(reconcileDeviceModeOnLogin('BIZ-PRO-2222')).toBe('local')
    expect(localStorage.getItem(MODE)).toBeNull()
    expect(localStorage.getItem(OWNER)).toBe('BIZ-PRO-2222')
  })

  it('is a no-op without an owner id', () => {
    localStorage.setItem(MODE, 'local')
    expect(reconcileDeviceModeOnLogin(null)).toBeNull()
    expect(localStorage.getItem(MODE)).toBe('local')
  })
})
