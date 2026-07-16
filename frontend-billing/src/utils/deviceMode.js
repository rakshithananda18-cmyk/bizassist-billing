/**
 * deviceMode.js — per-account guard for the device-global hosting mode.
 *
 * `bizassist_hosting_mode` in localStorage is DEVICE-global. If account A
 * (free, mode 'local') logs in and later account B (Pro, Local + Cloud) logs
 * in on the same install, A's stale 'local' used to:
 *   1. hide B's sidebar sync/refresh panel (AppLayout gives localStorage
 *      priority over the account's server-side hosting_mode), and
 *   2. get PUT back onto B's account by the fetchSettings reconcile,
 *      corrupting B's saved 'hybrid' to 'local'.
 *
 * Fix: on an ACCOUNT SWITCH, drop the previous account's device mode so the
 * incoming account's server-side `general.hosting_mode` becomes the truth.
 *
 * EXCEPTION: 'cloud' is kept. It is device ROUTING ("this terminal has no
 * local copy — talk to the cloud"), and the login that just succeeded went
 * through the cloud; removing it would strand the session on the wrong
 * backend. 'local' and 'hybrid' both route to the local backend, so dropping
 * them never changes routing — only which UI mode wins.
 */

const OWNER_KEY = 'bizassist_device_mode_owner'
const MODE_KEY = 'bizassist_hosting_mode'

/**
 * Call on every session save (login/signup). Returns the stale mode that was
 * cleared, or null if nothing was cleared.
 *
 * @param {string} newOwner - stable id of the account logging in (BizID preferred)
 * @param {Storage} storage - injectable for tests; defaults to localStorage
 */
export function reconcileDeviceModeOnLogin(newOwner, storage) {
  const store = storage || (typeof localStorage !== 'undefined' ? localStorage : null)
  if (!store || !newOwner) return null
  let cleared = null
  try {
    const prevOwner = store.getItem(OWNER_KEY)
    if (prevOwner !== String(newOwner)) {
      const staleMode = store.getItem(MODE_KEY)
      if (staleMode && staleMode !== 'cloud') {
        store.removeItem(MODE_KEY)
        cleared = staleMode
      }
      store.setItem(OWNER_KEY, String(newOwner))
    }
  } catch { /* storage unavailable — nothing to reconcile */ }
  return cleared
}
