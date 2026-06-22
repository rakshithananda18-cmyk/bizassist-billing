// src/__tests__/sync_manager.test.js
// R7b Slice 3 — syncManager mutate/flush/pull seam (injected transport).
import { describe, it, expect, vi } from 'vitest'
import { createSyncManager } from '../sync/syncManager'
import { createMemoryStore } from '../sync/stores'
import { SYNC_CURSOR_KEY } from '../sync/cursor'

const err = (status) => Object.assign(new Error('x'), { status })

function setup({ online = true, request, get } = {}) {
  const store = createMemoryStore()
  const transport = {
    request: request || vi.fn(async () => ({ ok: true })),
    get: get || vi.fn(async () => ({ changes: {}, cursor: {}, has_more: false })),
  }
  const sm = createSyncManager({ transport, store, isOnline: () => online })
  return { sm, store, transport }
}

describe('syncManager.mutate', () => {
  it('queues when offline and does NOT call the network', async () => {
    const { sm, store, transport } = setup({ online: false })
    const r = await sm.mutate({ method: 'POST', path: '/sales', body: { x: 1 } })
    expect(r.queued).toBe(true)
    expect(transport.request).not.toHaveBeenCalled()
    expect(await sm.pendingCount()).toBe(1)
    const op = (await store.all())[0]
    expect(op.id).toBe(r.clientRequestId) // queued under the stable id
  })

  it('sends online with a stable X-Client-Request-Id header', async () => {
    const request = vi.fn(async () => ({ id: 99 }))
    const { sm } = setup({ online: true, request })
    const r = await sm.mutate({ method: 'POST', path: '/sales', body: { x: 1 } })
    expect(r.queued).toBe(false)
    expect(r.data).toEqual({ id: 99 })
    const [, , opts] = request.mock.calls[0]
    expect(opts.headers['X-Client-Request-Id']).toBe(r.clientRequestId)
  })

  it('queues for retry on a TRANSIENT failure (network/5xx)', async () => {
    const request = vi.fn(async () => { throw err(0) })
    const { sm } = setup({ online: true, request })
    const r = await sm.mutate({ method: 'POST', path: '/sales' })
    expect(r.queued).toBe(true)
    expect(await sm.pendingCount()).toBe(1)
  })

  it('throws a 4xx business error to the caller (does NOT queue)', async () => {
    const request = vi.fn(async () => { throw err(422) })
    const { sm } = setup({ online: true, request })
    await expect(sm.mutate({ method: 'POST', path: '/sales' })).rejects.toMatchObject({ status: 422 })
    expect(await sm.pendingCount()).toBe(0)
  })
})

describe('syncManager.flushOutbox', () => {
  it('drains a queued op when back online, replaying its id', async () => {
    // Queue while offline...
    const { sm, store } = setup({ online: false })
    const r = await sm.mutate({ method: 'POST', path: '/sales', body: { x: 1 } })
    // ...then come online with a working transport and flush.
    const request = vi.fn(async () => ({ ok: true }))
    const sm2 = createSyncManager({ transport: { request, get: vi.fn() }, store, isOnline: () => true })
    const summary = await sm2.flushOutbox()
    expect(summary.sent).toBe(1)
    expect(await sm2.pendingCount()).toBe(0)
    expect(request.mock.calls[0][2].headers['X-Client-Request-Id']).toBe(r.clientRequestId)
  })

  it('skips when offline', async () => {
    const { sm } = setup({ online: false })
    await sm.mutate({ method: 'POST', path: '/sales' })
    const summary = await sm.flushOutbox()
    expect(summary.skipped).toBe(true)
  })
})

describe('syncManager.pull', () => {
  it('sends the stored cursor and advances it monotonically', async () => {
    const get = vi.fn()
      .mockResolvedValueOnce({ changes: { invoice: [{ id: 3 }] }, cursor: { invoice: 3 }, has_more: false })
      .mockResolvedValueOnce({ changes: { invoice: [{ id: 4 }] }, cursor: { invoice: 4 }, has_more: false })
    const { sm, store } = setup({ online: true, get })

    const first = await sm.pull()
    expect(first.cursor).toEqual({ invoice: 3 })
    expect(get.mock.calls[0][1].since).toBeUndefined() // first pull: full backfill

    const second = await sm.pull()
    expect(second.cursor).toEqual({ invoice: 4 })
    expect(get.mock.calls[1][1].since).toBe('{"invoice":3}') // sends previous cursor
    expect(await store.getMeta(SYNC_CURSOR_KEY)).toEqual({ invoice: 4 })
  })
})
