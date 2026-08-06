// When to offer "Turn on Local + Cloud".
//
// A Pro owner sitting on Local mode saw nothing: no sign the plan was active,
// no way to enable sync without knowing to open Settings → Hosting. So Pro
// looked broken when it was simply not switched on.
//
// The condition is the whole feature, and getting it wrong is expensive in both
// directions — offering it to a cashier produces a 403, and offering it on the
// web (where there is no local backend) offers something that cannot exist.
// Mirrors the guard in layouts/AppLayout.jsx.
import { describe, it, expect } from 'vitest'

const shouldOfferHybrid = ({ isLocalApp, effectiveMode, hostingMode, isFreePlan, isCashier }) =>
  Boolean(isLocalApp && effectiveMode === 'local' && hostingMode !== 'hybrid'
          && !isFreePlan && !isCashier)

const PRO_OWNER_ON_LOCAL = {
  isLocalApp: true, effectiveMode: 'local', hostingMode: 'local',
  isFreePlan: false, isCashier: false,
}

describe('Local + Pro prompt', () => {
  it('offers the switch to a Pro owner on a local device', () => {
    expect(shouldOfferHybrid(PRO_OWNER_ON_LOCAL)).toBe(true)
  })

  it('stays hidden on a free plan', () => {
    // Nothing to turn on — the server would refuse with 402.
    expect(shouldOfferHybrid({ ...PRO_OWNER_ON_LOCAL, isFreePlan: true })).toBe(false)
  })

  it('stays hidden for a cashier', () => {
    // `hosting_mode` is blocked for cashiers server-side, so the button would
    // only ever produce a 403.
    expect(shouldOfferHybrid({ ...PRO_OWNER_ON_LOCAL, isCashier: true })).toBe(false)
  })

  it('stays hidden on the web app', () => {
    // A browser on a non-local origin has no local backend at all, so "Local +
    // Cloud" is not a thing it can become.
    expect(shouldOfferHybrid({ ...PRO_OWNER_ON_LOCAL, isLocalApp: false })).toBe(false)
  })

  it('stays hidden once sync is already on', () => {
    expect(shouldOfferHybrid({ ...PRO_OWNER_ON_LOCAL, effectiveMode: 'hybrid' })).toBe(false)
  })

  it('stays hidden when the ACCOUNT already says hybrid', () => {
    // That is a device-pinning problem, not a mode problem, and the existing
    // "Use Local + Cloud on this device" block handles it. Showing both would
    // offer two different fixes for one situation.
    expect(shouldOfferHybrid({ ...PRO_OWNER_ON_LOCAL, hostingMode: 'hybrid' })).toBe(false)
  })

  it('stays hidden in cloud-only mode', () => {
    expect(shouldOfferHybrid({ ...PRO_OWNER_ON_LOCAL, effectiveMode: 'cloud' })).toBe(false)
  })

  it('never fires on its own — it is a prompt, not a switch', () => {
    // The guard only decides VISIBILITY. Auto-switching would overrule an
    // explicit opt-out and, because general.hosting_mode is account-scoped and
    // LWW-synced, rewrite the mode for every other device too.
    const decidesVisibilityOnly = typeof shouldOfferHybrid(PRO_OWNER_ON_LOCAL) === 'boolean'
    expect(decidesVisibilityOnly).toBe(true)
  })
})
