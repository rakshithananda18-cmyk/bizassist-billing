// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
const mocks = vi.hoisted(() => ({ post: vi.fn(), token: 'first-session' }))
vi.mock('./api', () => ({ api: { post: mocks.post }, tokenStore: { get: () => mocks.token } }))
import { Tracker } from './tracker'

beforeEach(() => { localStorage.clear(); mocks.post.mockReset(); mocks.token = 'first-session' })
afterEach(() => vi.restoreAllMocks())

describe('GPS buffer identity and retry handling', () => {
  it('cannot replay a different business or worker buffer', async () => {
    const old = new Tracker({ scope: 'BA-FIRST:1' })
    old.buffer.push({ lat: 11, lng: 12 })
    const otherWorker = new Tracker({ scope: 'BA-FIRST:2' })
    const otherBusiness = new Tracker({ scope: 'BA-SECOND:1' })
    expect(otherWorker.buffer.size()).toBe(0)
    expect(otherBusiness.buffer.size()).toBe(0)
    await otherWorker.flush()
    expect(mocks.post).not.toHaveBeenCalled()
    expect(new Tracker({ scope: 'BA-FIRST:1' }).buffer.size()).toBe(1)
  })

  it('does not use a later session to send the old tracker points', async () => {
    const old = new Tracker({ scope: 'BA-FIRST:1' })
    old.buffer.push({ lat: 11, lng: 12 })
    mocks.token = 'different-session'
    await old.flush()
    expect(mocks.post).not.toHaveBeenCalled()
    expect(old.buffer.size()).toBe(1)
  })

  it('preserves original-scoped pending points after an in-flight account switch', async () => {
    let reject
    mocks.post.mockReturnValue(new Promise((_resolve, no) => { reject = no }))
    const old = new Tracker({ scope: 'BA-FIRST:1' })
    old.buffer.push({ lat: 11, lng: 12 })
    const sending = old.flush()
    mocks.token = 'different-session'
    reject({ status: 409, message: 'Session changed' })
    await sending
    expect(old.buffer.size()).toBe(1)
    expect(new Tracker({ scope: 'BA-SECOND:1' }).buffer.size()).toBe(0)
  })

  it('retries queued points on a timer tick without needing a newer GPS fix', async () => {
    mocks.post.mockResolvedValue({ stored: 1 })
    const tracker = new Tracker({ scope: 'BA-FIRST:1' })
    tracker.buffer.push({ lat: 11, lng: 12 })
    tracker.tick()
    await Promise.resolve()
    expect(mocks.post).toHaveBeenCalledTimes(1)
    expect(tracker.buffer.size()).toBe(0)
  })

  it('keeps only unsent chunks when the server temporarily fails', async () => {
    const tracker = new Tracker({ scope: 'BA-FIRST:1' })
    for (let i = 0; i < 120; i++) tracker.buffer.push({ i })
    mocks.post.mockResolvedValueOnce({ stored: 100 }).mockRejectedValueOnce({ status: 503, message: 'Unavailable' })
    await tracker.flush()
    expect(mocks.post).toHaveBeenCalledTimes(2)
    expect(tracker.buffer.read().map(point => point.i)).toEqual(Array.from({ length: 20 }, (_, i) => i + 100))
  })

  it('never replays the legacy unowned buffer and survives non-array JSON', () => {
    localStorage.setItem('task_ping_buffer', JSON.stringify([{ lat: 11, lng: 12 }]))
    const tracker = new Tracker({ scope: 'BA-FIRST:1' })
    expect(tracker.buffer.size()).toBe(0)
    localStorage.setItem(tracker.buffer.key, '{}')
    expect(tracker.buffer.read()).toEqual([])
  })
})
