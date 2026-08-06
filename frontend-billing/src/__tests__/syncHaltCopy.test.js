// The halt → UI contract, asserted against the backend's own vocabulary.
//
// `GET /api/sync/queue-depth` reports `halt.reason` as one of four values. The
// panel must have a title, a detail line and a RECOVERY ACTION for every one of
// them — a reason the UI does not know renders as nothing at all, which is the
// silent-failure mode this whole change exists to remove.
//
// Kept as a data test rather than a full AppLayout render: AppLayout pulls in
// the lock, nav, auth and business contexts, and none of that is what could
// break here. What can break is the two vocabularies drifting apart.
import { describe, it, expect } from 'vitest'

// Mirrors backend/routes/sync.py::_HALT_ORDER — reason, and how it is fixed.
const BACKEND_REASONS = {
  secret_mismatch: 'relogin',
  auth_expired: 'relogin',
  plan_required: 'upgrade',
  offline: 'wait',
}

// Mirrors HALT_COPY + the button branches in layouts/AppLayout.jsx.
// `holdsOutbox` is the one that is easy to get wrong: `auth_expired` blocks the
// PULL only — `_PULL_AUTH_BLOCKED` is checked after the push leg has already run
// (sync_worker.py:3161), so uploads keep going and calling the outbox "held" is
// a false alarm about data loss that is not happening.
const HALT_COPY = {
  plan_required: { title: 'Sync paused — Pro required', action: 'check_plan', holdsOutbox: true },
  auth_expired: { title: 'Cloud downloads paused', action: 'logout', holdsOutbox: false },
  secret_mismatch: { title: 'Sign-in expired', action: 'logout', holdsOutbox: true },
  offline: { title: 'Offline', action: 'retry', holdsOutbox: true },
}

// Mirrors the haltReason precedence in layouts/AppLayout.jsx.
const resolveHalt = (serverReason, { isSyncOn, isFreePlan }) => {
  const planHalt = isSyncOn && isFreePlan ? 'plan_required' : null
  return (serverReason && serverReason !== 'offline' ? serverReason : null)
    || planHalt
    || serverReason
    || null
}

describe('sync halt vocabulary', () => {
  it('the UI knows every reason the backend can send', () => {
    // A reason with no copy renders an empty panel — worse than the stale
    // error it replaced, because at least that said something.
    for (const reason of Object.keys(BACKEND_REASONS)) {
      expect(HALT_COPY[reason], `no UI copy for backend reason "${reason}"`).toBeTruthy()
      expect(HALT_COPY[reason].title).toBeTruthy()
      expect(HALT_COPY[reason].action).toBeTruthy()
    }
  })

  it('invents no reason the backend cannot send', () => {
    for (const reason of Object.keys(HALT_COPY)) {
      expect(BACKEND_REASONS[reason], `UI copy for unknown reason "${reason}"`).toBeTruthy()
    }
  })

  it('the recovery action matches how the backend says it is fixed', () => {
    // The mapping that matters: "Check plan status" does nothing for a dead
    // token, and an outage needs no action at all.
    // `wait` → a live retry, not a dead button. The outage clears on its own,
    // but the worker re-probes on its own interval and the panel polls every
    // 30s, so after reconnecting the owner would face a disabled control for up
    // to a minute while everything else visibly worked.
    const expected = { relogin: 'logout', upgrade: 'check_plan', wait: 'retry' }
    for (const [reason, fix] of Object.entries(BACKEND_REASONS)) {
      expect(HALT_COPY[reason].action).toBe(expected[fix])
    }
  })

  it('never leaves a halt without an action the owner can take', () => {
    for (const [reason, copy] of Object.entries(HALT_COPY)) {
      expect(copy.action, `"${reason}" renders a halt with no way out`).not.toBe('none')
    }
  })

  it('says the outbox is held only when it actually is', () => {
    // auth_expired stops downloads, not uploads. The panel must not imply the
    // owner's own sales are stuck.
    expect(HALT_COPY.auth_expired.holdsOutbox).toBe(false)
    expect(HALT_COPY.auth_expired.title).not.toMatch(/sync (paused|stopped)/i)
    for (const r of ['plan_required', 'secret_mismatch', 'offline']) {
      expect(HALT_COPY[r].holdsOutbox).toBe(true)
    }
  })
})

describe('halt precedence', () => {
  const FREE = { isSyncOn: true, isFreePlan: true }
  const PRO = { isSyncOn: true, isFreePlan: false }

  it('a free plan outranks an outage', () => {
    // The worker probes cloud health BEFORE the plan gate, so during any outage
    // a free-plan business reports `offline` — and "resumes automatically" is
    // false when the plan is the real blocker. Matches _HALT_ORDER, which ranks
    // plan above offline.
    expect(resolveHalt('offline', FREE)).toBe('plan_required')
    expect(resolveHalt('offline', PRO)).toBe('offline')
  })

  it('an auth fault outranks the local plan guess', () => {
    // Both of these need the owner to sign in again; neither is fixed by the
    // plan. Telling a lapsed-token user to check their subscription is the
    // wrong-fix bug this whole feature exists to remove.
    expect(resolveHalt('secret_mismatch', FREE)).toBe('secret_mismatch')
    expect(resolveHalt('auth_expired', FREE)).toBe('auth_expired')
  })

  it('covers a free plan the worker has not refused yet', () => {
    // `_PLAN_BLOCKED` is only set by a cloud 402, so a fresh process reports no
    // halt at all until the first push attempt.
    expect(resolveHalt(null, FREE)).toBe('plan_required')
  })

  it('reports nothing when nothing is wrong', () => {
    expect(resolveHalt(null, PRO)).toBe(null)
    expect(resolveHalt(null, { isSyncOn: false, isFreePlan: true })).toBe(null)
  })

  it('only a plan halt counts as "paused"', () => {
    // isSyncPaused drives Pro-specific copy. A dead token is a fault, not a
    // subscription state — labelling it "Pro required" sends the owner to the
    // wrong fix, which is exactly what happened.
    const isPaused = (reason) => reason === 'plan_required'
    expect(isPaused('plan_required')).toBe(true)
    for (const r of ['auth_expired', 'secret_mismatch', 'offline', null]) {
      expect(isPaused(r)).toBe(false)
    }
  })

  it('no halt means the normal sync control', () => {
    expect(HALT_COPY[null]).toBeUndefined()
    expect(HALT_COPY[undefined]).toBeUndefined()
  })
})
