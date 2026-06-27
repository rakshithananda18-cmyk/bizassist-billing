// src/sync/applyDelta.js — Real-Time Sync Robustness, Phase 1 (delta push).
// =========================================================================
// Patch an in-memory list from a single SSE delta instead of refetching the
// whole list. The backend now ships the changed record on the SSE event
// (`services/realtime.py::delta_event`) as `{ op, rid, uid, payload, ... }`.
//
//   setCustomers(prev => applyDelta(prev, e.detail, { kind: 'customer' }))
//
// Keying: cloud mode is the only place we patch (every client reads the SAME
// cloud DB, so the row `id` is a stable shared key). We therefore key on `rid`
// (falling back to the payload's own `id`), and on `uid` when present — that
// keeps it correct if/when a Phase-2 cross-DB feed reuses this helper.

/** True when this event carries a usable delta payload we can splice in. */
export function hasDelta(detail) {
  return !!(detail && detail.payload && detail.op)
}

/**
 * Return a NEW array with the delta applied. Pure — never mutates `list`.
 *
 * @param {Array}  list           current list of DTOs
 * @param {Object} detail         the SSE event detail ({ op, rid, uid, kind, payload })
 * @param {Object} [opts]
 * @param {string} [opts.kind]    if set, ignore deltas whose `kind` differs
 *                                (e.g. patch only 'customer' rows on the party channel)
 * @param {string} [opts.key='id'] the DTO field that identifies a row
 * @returns {Array} the patched list (or the same ref if nothing applied)
 */
export function applyDelta(list, detail, opts = {}) {
  const { kind, key = 'id' } = opts
  if (!hasDelta(detail)) return list
  if (kind && detail.kind && detail.kind !== kind) return list

  const arr = Array.isArray(list) ? list : []
  const payload = detail.payload || {}

  // Identity: prefer the explicit row id from the event, then the payload's own
  // key, then uid. Compared loosely so a numeric id matches its string form.
  const idOf = (row) =>
    row == null ? undefined
      : (row[key] != null ? row[key]
        : (row.uid != null ? `uid:${row.uid}` : undefined))
  const targetId =
    detail.rid != null ? detail.rid
      : (payload[key] != null ? payload[key]
        : (detail.uid != null ? `uid:${detail.uid}` : undefined))
  if (targetId == null) return list // can't locate it safely → caller should refetch

  const sameId = (a, b) => a != null && b != null && String(a) === String(b)
  const idx = arr.findIndex((row) => sameId(idOf(row), targetId)
    || (detail.uid != null && row && sameId(row.uid, detail.uid)))

  if (detail.op === 'delete') {
    if (idx === -1) return list
    const next = arr.slice()
    next.splice(idx, 1)
    return next
  }

  // upsert
  const next = arr.slice()
  if (idx === -1) next.unshift(payload) // new row → top of list
  else next[idx] = { ...next[idx], ...payload }
  return next
}

export default applyDelta
