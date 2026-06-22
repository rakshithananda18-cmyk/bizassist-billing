// src/__tests__/sync_outbox.test.js
// R7b Slice 3 — offline outbox + cursor pure logic.
import { describe, it, expect } from 'vitest'
import { createMemoryStore } from '../sync/stores'
import { enqueue, flush, pending, deadLetters, OUTBOX_STATUS } from '../sync/outbox'
import { mergeCursor, cursorParam } from '../sync/cursor'
import { newClientRequestId } from '../sync/uuid'

const err = (status) => Object.assign(new Error('x'), { status })

describe('outbox enqueue/flush', () => {
  it('flushes in FIFO order and drops sent ops', async () => {
    const s = createMemoryStore()
    await enqueue(s, { method: 'POST', path: '/a', body: { n: 1 } })
    await enqueue(s, { method: 'POST', path: '/b', body: { n: 2 } })
    const seen = []
    const r = await flush(s, async (op) => { seen.push(op.path) })
    expect(seen).toEqual(['/a', '/b'])
    expect(r.sent).toBe(2)
    expect((await pending(s)).length).toBe(0)
  })

  it('reuses the stable clientRequestId as the op id (exactly-once header)', async () => {
    const s = createMemoryStore()
    const rec = await enqueue(s, { method: 'POST', path: '/sales', clientRequestId: 'fixed-id' })
    expect(rec.id).toBe('fixed-id')
    let header
    await flush(s, async (op) => { header = op.id })
    expect(header).toBe('fixed-id')
  })

  it('STOPS on a transient failure (network/5xx) and preserves order', async () => {
    const s = createMemoryStore()
    await enqueue(s, { method: 'POST', path: '/a' })
    await enqueue(s, { method: 'POST', path: '/b' })
    const r = await flush(s, async (op) => { if (op.path === '/a') throw err(0) })
    expect(r.stopped).toBe(true)
    expect(r.sent).toBe(0)
    expect((await pending(s)).map((o) => o.path)).toEqual(['/a', '/b']) // nothing lost, order kept
    expect((await pending(s))[0].attempts).toBe(1)
  })

  it('DEAD-LETTERS a 4xx and keeps draining the rest', async () => {
    const s = createMemoryStore()
    await enqueue(s, { method: 'POST', path: '/bad' })
    await enqueue(s, { method: 'POST', path: '/good' })
    const sent = []
    const r = await flush(s, async (op) => { if (op.path === '/bad') throw err(422); sent.push(op.path) })
    expect(sent).toEqual(['/good'])         // poison op didn't wedge the queue
    expect(r.deadLettered).toBe(1)
    expect(r.sent).toBe(1)
    const dead = await deadLetters(s)
    expect(dead.length).toBe(1)
    expect(dead[0].status).toBe(OUTBOX_STATUS.FAILED)
    expect(dead[0].failedStatus).toBe(422)
  })

  it('dead-letters a transient op after maxAttempts', async () => {
    const s = createMemoryStore()
    await enqueue(s, { method: 'POST', path: '/x' })
    for (let i = 0; i < 3; i++) await flush(s, async () => { throw err(0) }, { maxAttempts: 3 })
    expect((await pending(s)).length).toBe(0)
    expect((await deadLetters(s)).length).toBe(1)
  })
})

describe('cursor merge', () => {
  it('advances monotonically and never goes backward', () => {
    const a = mergeCursor({}, { invoice: 10, stock: 5 })
    expect(a).toEqual({ invoice: 10, stock: 5 })
    const b = mergeCursor(a, { invoice: 12, stock: 4 }) // stock lower → ignored
    expect(b).toEqual({ invoice: 12, stock: 5 })
  })

  it('cursorParam is undefined for an empty cursor (full backfill)', () => {
    expect(cursorParam({})).toBeUndefined()
    expect(cursorParam({ invoice: 3 })).toBe('{"invoice":3}')
  })
})

describe('clientRequestId', () => {
  it('returns a non-empty unique string', () => {
    const a = newClientRequestId()
    const b = newClientRequestId()
    expect(typeof a).toBe('string')
    expect(a.length).toBeGreaterThan(8)
    expect(a).not.toBe(b)
  })
})
