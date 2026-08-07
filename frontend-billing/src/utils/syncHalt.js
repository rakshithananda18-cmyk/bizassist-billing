/**
 * Why sync stopped — ONE definition, for every surface that says so.
 *
 * `GET /api/sync/queue-depth` reports `halt.reason` as one of four values, from
 * four in-process worker flags. This module owns what each one MEANS: the
 * precedence between them, the words shown, and how urgent it is.
 *
 * It lives here rather than in AppLayout because the notification bell shows the
 * same conditions. Two components rendering their own copy of these strings is
 * how "Sync paused — Pro required" ends up next to "Cloud downloads paused" for
 * the same underlying state, and there is no way to notice from either file.
 * `syncHaltCopy.test.js` used to mirror these values by hand for exactly that
 * reason; now it imports them.
 */

// Mirrors routes/sync.py::_HALT_ORDER — most actionable first.
export const HALT_REASONS = ['secret_mismatch', 'auth_expired', 'plan_required', 'offline']

/**
 * `auth_expired` is PULL-ONLY. `_PULL_AUTH_BLOCKED` is checked after the push
 * leg has already run (sync_worker.py:3161), so uploads keep working via the
 * self-signed fallback and only cloud→local downloads stop. Saying "sync
 * stopped" there would send an owner hunting for data loss that is not
 * happening. A secret mismatch halts both legs, hence the separate copy.
 *
 * `holdsOutbox` marks the reasons where local changes really are stuck, so a
 * surface can say "N waiting" without lying.
 */
export const HALT_COPY = {
  plan_required: {
    title: 'Sync paused — Pro required',
    detail: 'Cloud sync needs the Pro plan. Nothing is lost — changes wait here.',
    severity: 'warning',
    holdsOutbox: true,
  },
  auth_expired: {
    title: 'Cloud downloads paused',
    detail: 'This device’s cloud sign-in expired. Your changes still upload, but edits from your other devices stop arriving until you sign in again.',
    severity: 'warning',
    holdsOutbox: false,
  },
  secret_mismatch: {
    title: 'Sign-in expired',
    detail: 'This device could not authenticate with the cloud. Sign out and back in to reconnect.',
    // Nothing moves in either direction and it never self-heals — the only halt
    // that is strictly worse than an outage.
    severity: 'danger',
    holdsOutbox: true,
  },
  offline: {
    title: 'Offline',
    detail: 'The cloud is unreachable. Sync resumes automatically.',
    // Clears itself. Colouring it like a fault trains people to ignore faults.
    severity: 'info',
    holdsOutbox: true,
  },
}

/**
 * resolveHaltReason — combine what the server reports with what only the client
 * can know.
 *
 * The client sees one halt the worker cannot: a free plan that has not yet been
 * REFUSED by the cloud. `_PLAN_BLOCKED` is only set by a 402 response, so before
 * the first push attempt of a process there is no flag for the server to report.
 *
 * Precedence follows `_HALT_ORDER`, which ranks the plan ABOVE an outage. It has
 * to: the worker's health probe runs before its plan gate, so a free-plan
 * business whose flag is not set yet reports `offline` during any outage — and
 * "sync resumes automatically" is false when the plan is what is blocking.
 * Anything above `offline` still wins outright.
 *
 * An older backend sends no `halt` at all, so this degrades to the local
 * inference rather than assuming healthy.
 */
export function resolveHaltReason(serverReason, { isSyncOn, isFreePlan } = {}) {
  const planHalt = isSyncOn && isFreePlan ? 'plan_required' : null
  return (serverReason && serverReason !== 'offline' ? serverReason : null)
    || planHalt
    || serverReason
    || null
}
