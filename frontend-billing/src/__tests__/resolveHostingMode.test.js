import { describe, it, expect } from 'vitest'
import { resolveHostingMode, shouldPersistMode } from '../utils/resolveHostingMode'

describe('resolveHostingMode — URL lock', () => {
  it('forces cloud on a non-local origin regardless of plan', () => {
    expect(resolveHostingMode({ isLocalApp: false, plan: 'pro' })).toBe('cloud')
    expect(resolveHostingMode({ isLocalApp: false, plan: 'free' })).toBe('cloud')
  })

  it('cannot be overridden by a stored mode', () => {
    expect(resolveHostingMode({
      isLocalApp: false, plan: 'pro', savedMode: 'hybrid', deviceMode: 'hybrid',
    })).toBe('cloud')
  })
})

describe('resolveHostingMode — derived from plan', () => {
  it('gives a Pro desktop user hybrid with nothing stored', () => {
    expect(resolveHostingMode({ isLocalApp: true, plan: 'pro' })).toBe('hybrid')
  })

  it('gives a free desktop user local', () => {
    expect(resolveHostingMode({ isLocalApp: true, plan: 'free' })).toBe('local')
    expect(resolveHostingMode({ isLocalApp: true })).toBe('local')
  })

  it('degrades a stored hybrid to local when the plan is no longer Pro', () => {
    expect(resolveHostingMode({
      isLocalApp: true, plan: 'free', savedMode: 'hybrid',
    })).toBe('local')
  })

  it('restores hybrid automatically when a free plan upgrades to Pro', () => {
    expect(resolveHostingMode({
      isLocalApp: true, plan: 'pro', savedMode: 'local',
    })).toBe('local')  // explicit opt-out is still honoured
    expect(resolveHostingMode({
      isLocalApp: true, plan: 'pro', savedMode: undefined,
    })).toBe('hybrid')
  })
})

describe('resolveHostingMode — explicit opt-out', () => {
  it('honours a deliberate local-only choice on a Pro desktop', () => {
    expect(resolveHostingMode({
      isLocalApp: true, plan: 'pro', savedMode: 'local',
    })).toBe('local')
  })

  it('honours a deliberate hybrid choice while Pro is active', () => {
    expect(resolveHostingMode({
      isLocalApp: true, plan: 'pro', savedMode: 'hybrid',
    })).toBe('hybrid')
  })
})

describe('resolveHostingMode — the regression that caused this', () => {
  // A Pro owner on the desktop app whose account had been corrupted to 'cloud'
  // by the old reconcile. The backend then refused to queue any row:
  //   "hosting_mode='cloud' (not 'hybrid'), so invoices rows are NOT being queued"
  // which emptied the outbox and hid both sync buttons.
  it('does not honour a stored cloud on a local install — self-heals to hybrid', () => {
    expect(resolveHostingMode({
      isLocalApp: true, plan: 'pro', savedMode: 'cloud', deviceMode: null,
    })).toBe('hybrid')
  })

  it('self-heals a free account the same way, to local', () => {
    expect(resolveHostingMode({
      isLocalApp: true, plan: 'free', savedMode: 'cloud', deviceMode: null,
    })).toBe('local')
  })

  it('still reports cloud when the DEVICE is genuinely routed there', () => {
    // getApiBase() sends every request to CLOUD_URL in this state, so claiming
    // hybrid would render an outbox living on a backend we are not talking to.
    expect(resolveHostingMode({
      isLocalApp: true, plan: 'pro', savedMode: 'hybrid', deviceMode: 'cloud',
    })).toBe('cloud')
  })

  it('is stable — re-resolving its own output never changes it', () => {
    const cases = [
      { isLocalApp: true, plan: 'pro' },
      { isLocalApp: true, plan: 'free' },
      { isLocalApp: false, plan: 'pro' },
      { isLocalApp: true, plan: 'pro', savedMode: 'cloud' },
      { isLocalApp: true, plan: 'free', savedMode: 'hybrid' },
    ]
    for (const c of cases) {
      const once = resolveHostingMode(c)
      const twice = resolveHostingMode({ ...c, savedMode: once })
      expect(twice).toBe(once)   // no oscillation, no repeated PUTs
    }
  })
})

describe('shouldPersistMode', () => {
  it('persists only when the stored value disagrees', () => {
    expect(shouldPersistMode('hybrid', 'cloud')).toBe(true)
    expect(shouldPersistMode('hybrid', undefined)).toBe(true)
    expect(shouldPersistMode('hybrid', 'hybrid')).toBe(false)
  })
})

// ─────────────────────────────────────────────────────────────────────────────
// REGRESSION GATE — the web session must never author the account's hosting_mode
//
// `resolveHostingMode` answers a DEVICE question; `general.hosting_mode` lives on
// `users.settings` and `users` is in `_SYNC_TABLES`, making it an ACCOUNT field
// that LWW-syncs to every device. Writing the device answer into it caused:
//
//   web tab derives 'cloud' (true for that tab)
//     -> PUT writes 'cloud' onto the cloud users row (now the newest copy)
//     -> desktop pulls it over its own 'hybrid'
//     -> sync_worker.run_hybrid_sync: `if hosting_mode != "hybrid": continue`
//     -> the desktop stops syncing AND stops queueing rows, silently
//     -> desktop's next Settings load re-derives 'hybrid' and writes it back,
//        so the two devices flip the field on every page load
//
// The resolver is RIGHT to say 'cloud' for a web tab. What must not happen is
// that answer being persisted. These tests pin the split.
// ─────────────────────────────────────────────────────────────────────────────
describe('shouldPersistMode — only a local install may author the account field', () => {
  it('NEVER persists from a web session, even though cloud is correct for it', () => {
    // The exact production sequence. isLocalApp:false + savedMode:'hybrid' is a
    // Pro owner opening the web dashboard while their desktop syncs.
    expect(resolveHostingMode({ isLocalApp: false, plan: 'pro', savedMode: 'hybrid' })).toBe('cloud')
    expect(shouldPersistMode('cloud', 'hybrid', { isLocalApp: false, planKnown: true })).toBe(false)
  })

  it('does not persist from a web session for any resolved value', () => {
    for (const saved of ['local', 'hybrid', 'cloud', undefined]) {
      expect(shouldPersistMode('cloud', saved, { isLocalApp: false, planKnown: true })).toBe(false)
    }
  })

  it('still persists from a local install — the self-heal must keep working', () => {
    // A Pro desktop whose account wrongly stores 'cloud' is the case the
    // derivation exists to repair. Blocking this would trade one outage for another.
    expect(shouldPersistMode('hybrid', 'cloud', { isLocalApp: true, planKnown: true })).toBe(true)
  })

  it('refuses to drop hybrid on a GUESSED plan', () => {
    // Persisting 'local' switches the sync worker off exactly as dead as 'cloud'
    // did. When the settings response carries no subscription block, the plan is
    // unknown and the downgrade must not be written.
    expect(shouldPersistMode('local', 'hybrid', { isLocalApp: true, planKnown: false })).toBe(false)
    // A genuinely-read free plan is a real downgrade and is allowed through.
    expect(shouldPersistMode('local', 'hybrid', { isLocalApp: true, planKnown: true })).toBe(true)
  })

  it('allows an UPGRADE to hybrid even when the plan was not readable', () => {
    // Only the destructive direction is gated.
    expect(shouldPersistMode('hybrid', 'cloud', { isLocalApp: true, planKnown: false })).toBe(true)
  })

  it('defaults to the local-install caller when no context is supplied', () => {
    // Back-compat for existing call sites.
    expect(shouldPersistMode('hybrid', 'cloud')).toBe(true)
  })
})

// ─────────────────────────────────────────────────────────────────────────────
// REGRESSION GATE — an unreadable plan must not switch a working device off
//
// Caught by hostingAuth.test.jsx (T5), and worth pinning here at the unit level
// because the failure was subtle and the fix is a deliberate asymmetry.
//
// The persist guard above needs to know whether the plan was actually READ. The
// obvious way to express "not read" is to treat it as not-Pro — and that is
// wrong, because `resolveHostingMode` also drives what the UI RENDERS:
//
//   guess "not Pro" -> a Pro owner's account resolves to 'local', the hybrid
//                      controls vanish, and App.jsx reads the downgraded value
//                      straight out of settings.general.hosting_mode. That is
//                      the same visible outage this module exists to end,
//                      entered from the other side.
//   guess "Pro"     -> hybrid UI renders for a free account and grants nothing:
//                      sync_business 402s a non-Pro business cloud-side, and
//                      shouldPersistMode refuses to write while planKnown is
//                      false, so the account records nothing either.
//
// Optimistic to RENDER, never optimistic to PERSIST.
// ─────────────────────────────────────────────────────────────────────────────
describe('resolveHostingMode — an unknown plan is optimistic for display only', () => {
  it('keeps a legacy cloud account on hybrid when the plan cannot be read', () => {
    // The exact T5 case: a settings response carrying no `subscription` block.
    expect(resolveHostingMode({
      isLocalApp: true, plan: undefined, planKnown: false, savedMode: 'cloud',
    })).toBe('hybrid')
  })

  it('keeps a hybrid account on hybrid when the plan cannot be read', () => {
    // If this degraded to 'local', the Settings card would already show Local as
    // active and clicking "Local Only" would be a no-op that saves nothing.
    expect(resolveHostingMode({
      isLocalApp: true, plan: undefined, planKnown: false, savedMode: 'hybrid',
    })).toBe('hybrid')
  })

  it('still refuses to PERSIST anything resolved from that guess', () => {
    // The whole point of the asymmetry. Rendering optimistically is free;
    // writing it to a synced, account-scoped field is not.
    expect(shouldPersistMode('local', 'hybrid', { isLocalApp: true, planKnown: false })).toBe(false)
  })

  it('a READ free plan still degrades — this is not a way to bypass the gate', () => {
    expect(resolveHostingMode({
      isLocalApp: true, plan: 'free', planKnown: true, savedMode: 'hybrid',
    })).toBe('local')
  })

  it('planKnown defaults to true so existing call sites are unaffected', () => {
    expect(resolveHostingMode({ isLocalApp: true })).toBe('local')
    expect(resolveHostingMode({ isLocalApp: true, plan: 'free' })).toBe('local')
  })

  it('does not oscillate when the plan is unreadable', () => {
    const c = { isLocalApp: true, planKnown: false, savedMode: 'cloud' }
    const once = resolveHostingMode(c)
    expect(resolveHostingMode({ ...c, savedMode: once })).toBe(once)
  })
})
