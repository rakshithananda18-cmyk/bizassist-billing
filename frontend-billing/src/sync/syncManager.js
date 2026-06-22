// src/sync/syncManager.js — wires the offline sync core to the app.
// =================================================================
// Ties together the three pure pieces — outbox (push), cursor (pull), and the
// stable client-request id — with online/offline detection and the HTTP client.
// The transport is injected so the queue/flush/pull logic is unit-testable in
// node without a real network or `api/client`.
//
//   const sm = createSyncManager()           // app: real transport + IndexedDB
//   sm.start()                               // flush whenever we come back online
//   const r = await sm.mutate({ method:'POST', path:'/sales', body })
//   if (r.queued) showOfflineToast()         // saved locally; will sync on reconnect
//   const delta = await sm.pull()            // refresh local cache from the server
//
// `mutate` is the safe way to do a money mutation: it always uses ONE stable
// `X-Client-Request-Id`, so whether the request goes out now, is retried after a
// network blip, or is replayed from the outbox on reconnect, the backend wall
// (R7b Slice 1) guarantees exactly-once.

import { request as defaultRequest, api as defaultApi } from '../api/client'
import { logger } from '../utils/logger'
import { createDefaultStore } from './stores'
import { enqueue, flush, pending, deadLetters } from './outbox'
import { newClientRequestId } from './uuid'
import { mergeCursor, cursorParam, SYNC_CURSOR_KEY } from './cursor'

// Default transport over the real api/client. `request` returns parsed JSON and
// throws ApiError (with numeric `.status`, 0 = network) — exactly what the
// outbox/mutate logic below keys on.
function defaultTransport() {
  return {
    request: (method, path, opts) => defaultRequest(method, path, opts),
    get: (path, query, opts) => defaultApi.get(path, query, opts),
  }
}

const isTransient = (status) => status === 0 || status >= 500

export function createSyncManager({ transport = defaultTransport(), store = createDefaultStore(), isOnline } = {}) {
  const online = isOnline || (() => (typeof navigator === 'undefined' ? true : navigator.onLine !== false))

  // Replay/send one op with its stable id attached.
  const send = (op) =>
    transport.request(op.method, op.path, {
      body: op.body,
      headers: { 'X-Client-Request-Id': op.id },
    })

  /**
   * Do a retry-safe mutation. Offline → queue and return { queued:true }. Online
   * → send with a stable id; on a TRANSIENT failure (network/5xx) queue it for
   * later under the SAME id; on a 4xx business error throw to the caller (a
   * validation problem won't fix itself by retrying).
   */
  async function mutate({ method, path, body } = {}) {
    const id = newClientRequestId()

    if (!online()) {
      await enqueue(store, { method, path, body, clientRequestId: id })
      logger.info('[SYNC] queued (offline)', method, path)
      return { queued: true, clientRequestId: id }
    }

    try {
      const data = await send({ id, method, path, body })
      return { data, clientRequestId: id, queued: false }
    } catch (err) {
      const status = err && typeof err.status === 'number' ? err.status : 0
      if (isTransient(status)) {
        await enqueue(store, { method, path, body, clientRequestId: id })
        logger.warn('[SYNC] send failed — queued for retry', method, path, status)
        return { queued: true, clientRequestId: id, error: err }
      }
      throw err // 4xx — surface to the caller
    }
  }

  /** Enqueue a mutation WITHOUT trying to send it now (used by the POS offline
   * save path, which has already decided it's offline). Returns the stored op. */
  async function queue({ method, path, body, clientRequestId } = {}) {
    const rec = await enqueue(store, { method, path, body, clientRequestId })
    logger.info('[SYNC] queued', method, path)
    return rec
  }

  /** The pending (not-yet-synced) ops, FIFO — for a "N unsynced" badge and to
   * feed offline invoice numbers back into the client's number allocation. */
  async function listPending() {
    return pending(store)
  }

  /** Drain the outbox if we're online. No-op when offline. */
  async function flushOutbox(opts) {
    if (!online()) return { skipped: true, sent: 0, remaining: (await pending(store)).length }
    const summary = await flush(store, send, opts)
    if (summary.sent || summary.deadLettered) logger.info('[SYNC] flush', summary)
    return summary
  }

  /** Pull server-side deltas since our stored cursor, advancing it monotonically. */
  async function pull() {
    const prev = (await store.getMeta(SYNC_CURSOR_KEY)) || {}
    const res = await transport.get('/sync/pull', { since: cursorParam(prev) })
    const next = mergeCursor(prev, res && res.cursor)
    await store.setMeta(SYNC_CURSOR_KEY, next)
    return { changes: (res && res.changes) || {}, cursor: next, hasMore: !!(res && res.has_more) }
  }

  /** Begin flushing on every `online` event (and once now). Returns an unsubscribe. */
  function start() {
    if (typeof window === 'undefined' || !window.addEventListener) return () => {}
    const onOnline = () => { flushOutbox().catch(() => {}) }
    window.addEventListener('online', onOnline)
    flushOutbox().catch(() => {}) // drain any backlog left from a previous session
    return () => window.removeEventListener('online', onOnline)
  }

  return {
    mutate,
    queue,
    flushOutbox,
    pull,
    start,
    store,
    pending: listPending,
    pendingCount: async () => (await pending(store)).length,
    deadLetters: () => deadLetters(store),
  }
}

// App-wide singleton (real transport + durable store).
export const syncManager = createSyncManager()
export default syncManager
