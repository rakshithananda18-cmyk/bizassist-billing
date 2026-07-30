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
