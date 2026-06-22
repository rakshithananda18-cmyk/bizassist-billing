// src/sync/cursor.js — the delta-pull cursor (pure).
// ===================================================
// `GET /sync/pull` (R7b Slice 2) returns a per-entity high-water map, e.g.
// { invoice: 131, payment: 45, purchase: 7, stock: 312 }. The client persists it
// and sends it back next time. `mergeCursor` advances it MONOTONICALLY — a
// cursor value can only move forward, never backward — so an out-of-order or
// stale response can never make us re-pull or skip rows.

export const SYNC_CURSOR_KEY = 'sync_cursor'

export function mergeCursor(prev = {}, next = {}) {
  const out = { ...(prev || {}) }
  for (const [k, v] of Object.entries(next || {})) {
    const n = Number(v)
    if (!Number.isNaN(n)) {
      const cur = Number(out[k] || 0)
      out[k] = n > cur ? n : cur
    }
  }
  return out
}

/** Serialize for the `?since=` query param. Empty cursor → undefined (full backfill). */
export function cursorParam(cursor) {
  if (!cursor || Object.keys(cursor).length === 0) return undefined
  return JSON.stringify(cursor)
}
