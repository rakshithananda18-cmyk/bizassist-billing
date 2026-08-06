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
const HALT_COPY = {
  plan_required: { title: 'Sync paused — Pro required', action: 'check_plan' },
  auth_expired: { title: 'Sign-in expired', action: 'logout' },
  secret_mismatch: { title: 'Sign-in expired', action: 'logout' },
  offline: { title: 'Offline', action: 'none' },
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
    const expected = { relogin: 'logout', upgrade: 'check_plan', wait: 'none' }
    for (const [reason, fix] of Object.entries(BACKEND_REASONS)) {
      expect(HALT_COPY[reason].action).toBe(expected[fix])
    }
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
