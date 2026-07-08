// src/utils/sessionCache.js
// ─────────────────────────────────────────────────────────────────────────────
// Thin sessionStorage-backed TTL cache for billing counter data.
//
// Why sessionStorage (not localStorage)?
//   • Clears automatically when the tab/browser closes — never serves stale
//     data across reboots or logout/login cycles.
//   • Tab-isolated — two counter tabs each get their own fresh cache.
//   • Fast synchronous reads — no await, no spinner needed.
//
// Invalidation is two-layered:
//   1. Hard TTL — expiresAt timestamp; data is ignored after it expires.
//   2. Event-driven — call invalidateCache("products", userId) when a
//      sync.trigger("product") event fires so the next load re-fetches.
// ─────────────────────────────────────────────────────────────────────────────

const PREFIX = "biz_sc_"

/**
 * Read a cached value.
 * @returns {{ data: any|null, expired: boolean, meta: any|null }}
 */
export function getCached(key, userId) {
  try {
    const raw = sessionStorage.getItem(`${PREFIX}${key}_${userId}`)
    if (!raw) return { data: null, expired: true, meta: null }
    const entry = JSON.parse(raw)
    const expired = Date.now() > (entry.expiresAt || 0)
    return { data: entry.data ?? null, expired, meta: entry.meta ?? null }
  } catch {
    return { data: null, expired: true, meta: null }
  }
}

/**
 * Write a value to cache.
 * @param {string}  key
 * @param {number}  userId
 * @param {any}     data
 * @param {number}  ttlMs    - time-to-live in milliseconds
 * @param {any}     [meta]   - optional metadata (e.g. { count, max_id } for products)
 */
export function setCached(key, userId, data, ttlMs, meta = null) {
  try {
    sessionStorage.setItem(`${PREFIX}${key}_${userId}`, JSON.stringify({
      data,
      meta,
      cachedAt:  Date.now(),
      expiresAt: Date.now() + ttlMs,
    }))
  } catch (e) {
    // sessionStorage might be full (e.g. very large product catalog).
    // Silently ignore — the next load will just fetch from the server.
    console.warn("[sessionCache] write failed (storage full?):", key, e?.name)
  }
}

/**
 * Force-expire a specific cache entry so the next read triggers a fresh fetch.
 */
export function invalidateCache(key, userId) {
  try {
    sessionStorage.removeItem(`${PREFIX}${key}_${userId}`)
  } catch { /* ignore */ }
}

/**
 * Clear every cache entry for this user (call on logout).
 */
export function clearUserCache(userId) {
  try {
    const suffix = `_${userId}`
    Object.keys(sessionStorage)
      .filter(k => k.startsWith(PREFIX) && k.endsWith(suffix))
      .forEach(k => sessionStorage.removeItem(k))
  } catch { /* ignore */ }
}
