// src/sync/outbox.js — the offline write queue (pure, store-injected).
// ====================================================================
// While the counter is offline (or a request fails on a flaky network), the
// mutation is appended here instead of being lost. On reconnect we `flush()` the
// queue IN ORDER, replaying each op with its stable `X-Client-Request-Id` so the
// backend's exactly-once wall (R7b Slice 1) makes a replay a no-op rather than a
// double-post.
//
// FLUSH SEMANTICS (the important part):
//   • success            → drop the op, continue.
//   • transient failure  → network down (status 0) or server 5xx. The op is
//     still valid and will likely succeed later, so we BUMP its attempt count
//     and STOP — preserving FIFO order and not hammering a struggling server.
//   • permanent failure  → a 4xx business/validation rejection (e.g. 422). This
//     op will NEVER succeed as-is, so we DEAD-LETTER it (mark failed) and CONTINUE
//     so one poison op can't wedge the whole queue behind it.
//   • retry cap          → a transient op that has failed `maxAttempts` times is
//     dead-lettered too, so a permanently-unreachable endpoint can't loop forever.
//
// The store is injected (memory in tests, IndexedDB in the app), so this file is
// pure logic with no IndexedDB/browser dependency.

import { newClientRequestId } from './uuid'

export const OUTBOX_STATUS = { PENDING: 'pending', FAILED: 'failed' }
export const DEFAULT_MAX_ATTEMPTS = 5

/** Append a mutation. Returns the stored record (its `id` is the client-request id). */
export async function enqueue(store, { method, path, body, clientRequestId } = {}) {
  if (!method || !path) throw new Error('outbox.enqueue requires { method, path }')
  const record = {
    id: clientRequestId || newClientRequestId(),
    method,
    path,
    body: body ?? null,
    status: OUTBOX_STATUS.PENDING,
    attempts: 0,
    createdAt: new Date().toISOString(),
  }
  return store.add(record)
}

/** Ops still awaiting delivery, FIFO. */
export async function pending(store) {
  return (await store.all()).filter((o) => o.status === OUTBOX_STATUS.PENDING)
}

/** Dead-lettered ops (4xx or retry-exhausted) — surfaced for a "needs attention" UI. */
export async function deadLetters(store) {
  return (await store.all()).filter((o) => o.status === OUTBOX_STATUS.FAILED)
}

const isPermanent = (status) => status >= 400 && status < 500

/**
 * Replay the queue. `sender(op)` performs the HTTP call and must REJECT with an
 * error carrying a numeric `status` (0 = network down) on failure; resolve on
 * success. Returns a summary.
 */
export async function flush(store, sender, { maxAttempts = DEFAULT_MAX_ATTEMPTS } = {}) {
  const summary = { sent: 0, deadLettered: 0, stopped: false, remaining: 0 }
  const ops = await pending(store)

  for (const op of ops) {
    try {
      await sender(op)
      await store.remove(op.id)
      summary.sent++
    } catch (err) {
      const status = err && typeof err.status === 'number' ? err.status : 0
      const attempts = (op.attempts || 0) + 1
      const reason = (err && (err.detail || err.message)) || String(status)

      if (isPermanent(status)) {
        // 4xx — never going to succeed; dead-letter and keep draining the rest.
        await store.update(op.id, {
          status: OUTBOX_STATUS.FAILED, attempts, failedStatus: status, lastError: reason,
        })
        summary.deadLettered++
        continue
      }

      if (attempts >= maxAttempts) {
        // transient, but it has tried too many times — stop looping on it.
        await store.update(op.id, {
          status: OUTBOX_STATUS.FAILED, attempts, failedStatus: status, lastError: 'max attempts: ' + reason,
        })
        summary.deadLettered++
        continue
      }

      // transient (network/5xx): keep it pending, preserve order, try again later.
      await store.update(op.id, { attempts, lastError: reason })
      summary.stopped = true
      break
    }
  }

  summary.remaining = (await pending(store)).length
  return summary
}
