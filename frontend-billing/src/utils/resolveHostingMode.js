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
 * @param {boolean} [args.planKnown=true] - the plan was actually READ from the
 *   session, not inferred. See the note on optimism below.
 * @returns {'local'|'hybrid'|'cloud'}
 */
export function resolveHostingMode({ isLocalApp, plan, savedMode, deviceMode, planKnown = true } = {}) {
  // 1. URL lock — a browser on a non-local origin has no local backend at all.
  if (!isLocalApp) return HOSTING_CLOUD

  // 2. Device routing — if this install is pointed at the cloud, say so. Claiming
  //    'hybrid' here would render an outbox that lives on a backend we are not
  //    talking to.
  if (deviceMode === HOSTING_CLOUD) return HOSTING_CLOUD

  // An UNREADABLE plan resolves optimistically, and only for display.
  //
  // This is asymmetric on purpose, because the two mistakes are not equal:
  //
  //   Guess "not Pro"  -> a Pro owner's account resolves to 'local', the hybrid
  //                       controls disappear, App.jsx reads the downgraded value
  //                       out of settings.general.hosting_mode, and the device
  //                       looks offline-only. That is the SAME visible outage
  //                       this module was written to end, entered from the other
  //                       side.
  //   Guess "Pro"      -> hybrid UI shows for a free account. It grants nothing:
  //                       `sync_business` 402s a non-Pro business cloud-side, and
  //                       `shouldPersistMode` refuses to WRITE the value while
  //                       `planKnown` is false, so nothing is recorded either.
  //
  // So: optimistic to render, never optimistic to persist. The settings response
  // normally carries `subscription`, so this is the degraded path — and a
  // degraded path must not silently switch a working device off.
  const isPro = plan === 'pro' || !planKnown

  // 3. Explicit, still-valid opt-out by the owner.
  if (savedMode === HOSTING_LOCAL) return HOSTING_LOCAL
  if (savedMode === HOSTING_HYBRID) return isPro ? HOSTING_HYBRID : HOSTING_LOCAL

  // 4. Derived default. A saved 'cloud' on a local install lands here on purpose.
  return isPro ? HOSTING_HYBRID : HOSTING_LOCAL
}

/**
 * True when the account's stored value disagrees with what actually applies AND
 * this session is entitled to author that value.
 *
 * WHY THE ENTITLEMENT CHECK EXISTS — READ BEFORE RELAXING IT
 * ---------------------------------------------------------
 * `resolveHostingMode` answers a question about THIS DEVICE. But
 * `general.hosting_mode` lives on `users.settings`, and `users` is in
 * `_SYNC_TABLES` — it is an ACCOUNT-scoped, LWW-synced field. Persisting a
 * device-scoped answer into an account-scoped field is how one device's truth
 * becomes another device's corruption.
 *
 * The concrete failure that produced this guard:
 *   1. Owner opens the web dashboard. `isLocalApp` is false, so rule 1 returns
 *      'cloud' — correct for that tab, which genuinely has no local backend.
 *   2. The old `shouldPersistMode` saw 'cloud' !== 'hybrid' and PUT 'cloud' onto
 *      the cloud `users` row, making it the newer copy.
 *   3. `users` syncs. The desktop pulled 'cloud' over its own 'hybrid'.
 *   4. `sync_worker.run_hybrid_sync` reads that field and does
 *      `if hosting_mode != "hybrid": continue`. The desktop stopped syncing —
 *      silently, with no error anywhere — and `models.py` stopped queueing new
 *      rows to the outbox at all.
 *   5. Loading Settings on the desktop re-derived 'hybrid' and PUT it back, so
 *      the two devices then flipped the field on every single page load.
 *
 * This is the same "hosting_mode='cloud' … NOT being queued for sync" outage the
 * derivation rewrite was written to end, re-entered through the web door.
 *
 * Two rules, both fail-CLOSED — when in doubt, do not write:
 *
 *   • Only a local install may author the field. A web tab cannot observe
 *     whether the owner runs a local backend, so it has nothing to say about it.
 *   • A downgrade away from 'hybrid' requires a KNOWN plan. If the plan is
 *     unreadable, `resolveHostingMode` falls back to a guess, and a wrong guess
 *     here writes 'local' and stops the sync worker just as dead as 'cloud' did.
 *     An unknown plan therefore persists nothing.
 *
 * @param {string}  resolved   - output of resolveHostingMode()
 * @param {string}  savedMode  - the account's stored general.hosting_mode
 * @param {object}  [ctx]
 * @param {boolean} [ctx.isLocalApp=true] - config.IS_LOCAL_APP for this session
 * @param {boolean} [ctx.planKnown=true]  - the plan was actually read, not guessed
 */
export function shouldPersistMode(resolved, savedMode, ctx = {}) {
  const { isLocalApp = true, planKnown = true } = ctx

  if (!resolved || resolved === savedMode) return false

  // A web session is a viewer of this account, never the author of how it is hosted.
  if (!isLocalApp) return false

  // Losing 'hybrid' is the destructive direction: it is what switches the sync
  // worker off. Never do it on a guess.
  if (savedMode === HOSTING_HYBRID && resolved !== HOSTING_HYBRID && !planKnown) return false

  return true
}


/**
 * canShowLiveCounters — may this session render the Live Counters view?
 *
 * Lives here, beside `resolveHostingMode`, because it is a decision ABOUT the
 * resolved mode and the page that used to own it got it wrong by re-deriving
 * that mode itself. POSLiveCounter read `localStorage.bizassist_hosting_mode`
 * first — the one input `resolveHostingMode` deliberately discards (a device
 * flag counts only when it says 'cloud'; a Pro account otherwise defaults to
 * hybrid). A stale 'local' therefore refused the view while Settings, reading
 * the resolved value, showed "Local + Cloud — Active", and the refusal told the
 * owner to change a setting that was already changed.
 *
 * @param {string|null} hostingMode  RESOLVED mode (settings.general.hosting_mode,
 *                                   which AuthContext sets to realMode). Null
 *                                   until /settings answers.
 * @param {boolean} sseConnected     live SSE probe — a connected stream proves
 *                                   the capability regardless of the stored mode.
 * @returns {{allowed: boolean, known: boolean}}
 *   `known` is false while the mode is still unresolved. Callers must not render
 *   a refusal then: unknown means "say nothing yet", not "assume the restrictive
 *   answer", which is what flashed a wrong banner on every cold load.
 */
export function canShowLiveCounters({ hostingMode = null, sseConnected = false } = {}) {
  const known = Boolean(hostingMode)
  return {
    known,
    allowed: known ? (hostingMode !== HOSTING_LOCAL || sseConnected) : sseConnected,
  }
}
