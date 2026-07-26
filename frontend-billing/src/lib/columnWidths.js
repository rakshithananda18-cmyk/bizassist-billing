// ============================================================================
// lib/columnWidths.js — persisted, resizable data-table column widths
// ----------------------------------------------------------------------------
// Pure helpers only: storage-key construction, load/save/clear, clamping, and
// the "auto-fit" width derivation from measured content widths. No React, no
// DOM reads — the hook (hooks/useResizableColumns.js) owns measurement and
// re-render; these functions are unit-testable in isolation.
//
// Storage shape (one entry per user + table):
//   localStorage["bizassist.colw.v1.<userId>.<tableId>"] = { sku: 90, name: 260 }
// Only EXPLICITLY sized columns are stored. A column absent from the map is
// rendered at its natural/auto width, which is what "reset" restores.
// ============================================================================
import { logger } from '../utils/logger'

export const STORAGE_PREFIX = 'bizassist.colw.v1'

/** Hard floor/ceiling for any column, in px. Keeps a mis-drag from making a
 *  column unreadable (0px) or from pushing every sibling off-screen. */
export const MIN_COLUMN_WIDTH = 48
export const MAX_COLUMN_WIDTH = 900

/** Extra px added to a measured content width so text never sits flush against
 *  the cell border after an auto-fit. Mirrors the .data-table td padding. */
export const AUTOFIT_PADDING = 24

/**
 * storageKey — namespaced per user AND per table so two users on the same
 * machine (shared counter PC) never inherit each other's layout, and so the
 * POS cart and the Stock grid keep independent widths.
 * A missing userId degrades to "anon" rather than throwing.
 */
export function storageKey(tableId, userId) {
  const uid = userId === 0 || userId ? String(userId) : 'anon'
  return `${STORAGE_PREFIX}.${uid}.${tableId}`
}

/** Clamp a candidate width into [min, max]. Non-finite input → null (= auto). */
export function clampWidth(px, min = MIN_COLUMN_WIDTH, max = MAX_COLUMN_WIDTH) {
  const n = Number(px)
  if (!Number.isFinite(n)) return null
  return Math.round(Math.min(max, Math.max(min, n)))
}

/**
 * sanitizeWidths — accept only { [colKey]: finiteNumber } for known columns.
 * Guards against hand-edited localStorage, stale column keys from an older app
 * version, and NaN leaking in from a bad drag.
 */
export function sanitizeWidths(raw, allowedKeys = null) {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return {}
  const allow = allowedKeys ? new Set(allowedKeys) : null
  const out = {}
  for (const [key, val] of Object.entries(raw)) {
    if (allow && !allow.has(key)) continue
    const w = clampWidth(val)
    if (w != null) out[key] = w
  }
  return out
}

/** Read saved widths. Never throws — a corrupt entry behaves as "no override". */
export function loadWidths(tableId, userId, allowedKeys = null) {
  try {
    const raw = localStorage.getItem(storageKey(tableId, userId))
    if (!raw) return {}
    return sanitizeWidths(JSON.parse(raw), allowedKeys)
  } catch (e) {
    logger.warn('[COLW] failed to read saved column widths', tableId, e)
    return {}
  }
}

/** Persist widths. An empty map removes the entry entirely (clean reset). */
export function saveWidths(tableId, userId, widths) {
  try {
    const key = storageKey(tableId, userId)
    const clean = sanitizeWidths(widths)
    if (Object.keys(clean).length === 0) localStorage.removeItem(key)
    else localStorage.setItem(key, JSON.stringify(clean))
    return true
  } catch (e) {
    logger.warn('[COLW] failed to persist column widths', tableId, e)
    return false
  }
}

/** Drop all overrides for this user+table. */
export function clearWidths(tableId, userId) {
  try {
    localStorage.removeItem(storageKey(tableId, userId))
    return true
  } catch (e) {
    logger.warn('[COLW] failed to clear column widths', tableId, e)
    return false
  }
}

/**
 * nextWidth — width after dragging the grip from startX to currentX.
 * Pure: the hook supplies the width the column had when the drag began.
 */
export function nextWidth(startWidth, startX, currentX, min = MIN_COLUMN_WIDTH, max = MAX_COLUMN_WIDTH) {
  return clampWidth(startWidth + (currentX - startX), min, max)
}

/**
 * autoFitWidth — the width that fits the widest measured cell in a column.
 * `measured` is the list of intrinsic content widths (header + every body cell)
 * gathered by the hook via scrollWidth. Adds cell padding, then clamps.
 * Empty input → null, meaning "leave this column on auto".
 */
export function autoFitWidth(measured, padding = AUTOFIT_PADDING, min = MIN_COLUMN_WIDTH, max = MAX_COLUMN_WIDTH) {
  const nums = (measured || []).map(Number).filter(Number.isFinite)
  if (nums.length === 0) return null
  return clampWidth(Math.max(...nums) + padding, min, max)
}
