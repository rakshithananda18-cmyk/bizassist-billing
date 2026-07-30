/**
 * resolveHostingMode — the ONE place that decides which hosting mode is in effect.
 *
 * The mode is DERIVED, not remembered. Its three inputs are facts about the
 * current session, so it self-corrects and cannot go stale:
 *
 *   1. URL      — a non-localhost origin (Vercel, any shared link) has no local
 *                 backend to talk to, so it is always 'cloud'. Platform lock;
 *                 nothing overrides it.
 *   2. PLAN     — Local + Cloud is a Pro capability. A free plan resolves to
 *                 'local', and a lapsed Pro degrades back to 'local' on its own
 *                 rather than sitting in a hybrid mode the backend will refuse
 *                 to sync (sync_business 402s a non-Pro business).
 *   3. DEVICE   — where this install is actually routed. `getApiBase()` redirects
 *                 to the cloud only when the device key is exactly 'cloud', so a
 *                 device pinned there must report 'cloud' or the UI would claim a
 *                 local outbox that the session cannot reach.
 *
 * WHY DERIVED
 * -----------
 * `general.hosting_mode` used to be the source of truth, and a stale device value
 * outranked it and was PUT back over it on every settings load. A Pro desktop
 * user who chose Local + Cloud had it silently rewritten to 'cloud', which made
 * the backend stop queueing rows entirely ("hosting_mode='cloud' … NOT being
 * queued for sync"), emptied the outbox, and hid every hybrid-gated control. No
 * amount of re-picking it in Settings survived the next page load.
 *
 * A saved 'local' or 'hybrid' is still honoured as a deliberate opt-out — a Pro
 * owner may genuinely want local-only for privacy or an offline counter. A saved
 * 'cloud' on a local install is NOT honoured: it is indistinguishable from the
 * corruption above, and cloud-only on desktop is reachable through the explicit
 * switch flow, which sets the device routing key rather than the account field.
 */

export const HOSTING_LOCAL = 'local'
export const HOSTING_HYBRID = 'hybrid'
export const HOSTING_CLOUD = 'cloud'

/**
 * @param {object}  args
 * @param {boolean} args.isLocalApp - origin is localhost/LAN (see config.IS_LOCAL_APP)
 * @param {string}  [args.plan]     - subscription plan, e.g. 'pro' | 'free'
 * @param {string}  [args.savedMode]- account's general.hosting_mode, if any
 * @param {string}  [args.deviceMode]- localStorage 'bizassist_hosting_mode', if any
 * @returns {'local'|'hybrid'|'cloud'}
 */
export function resolveHostingMode({ isLocalApp, plan, savedMode, deviceMode } = {}) {
  // 1. URL lock — a browser on a non-local origin has no local backend at all.
  if (!isLocalApp) return HOSTING_CLOUD

  // 2. Device routing — if this install is pointed at the cloud, say so. Claiming
  //    'hybrid' here would render an outbox that lives on a backend we are not
  //    talking to.
  if (deviceMode === HOSTING_CLOUD) return HOSTING_CLOUD

  const isPro = plan === 'pro'

  // 3. Explicit, still-valid opt-out by the owner.
  if (savedMode === HOSTING_LOCAL) return HOSTING_LOCAL
  if (savedMode === HOSTING_HYBRID) return isPro ? HOSTING_HYBRID : HOSTING_LOCAL

  // 4. Derived default. A saved 'cloud' on a local install lands here on purpose.
  return isPro ? HOSTING_HYBRID : HOSTING_LOCAL
}

/**
 * True when the account's stored value disagrees with what actually applies, so
 * callers can quietly re-persist it instead of leaving a misleading row in the DB
 * (the backend's sync-queue gate reads that stored value directly).
 */
export function shouldPersistMode(resolved, savedMode) {
  return !!resolved && resolved !== savedMode
}
