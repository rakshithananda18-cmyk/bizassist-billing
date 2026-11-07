// @vitest-environment jsdom
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { createSseConnection } from '../sync/sseConnection'
let streams
beforeEach(() => {
  vi.useFakeTimers(); streams = []
  vi.stubGlobal('EventSource', class {
    constructor(url) { this.url = url; this.events = {}; this.close = vi.fn(); streams.push(this) }
    addEventListener(name, callback) { this.events[name] = callback }
  })
})
afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals() })
it('rotates quietly, resumes the last id and refreshes only on a replay gap', async () => {
  const onGap = vi.fn(), onStatus = vi.fn(), onEvent = vi.fn()
  const connection = createSseConnection({ fetchTicket: async () => 'https://api.test/realtime/events?ticket=fresh', onGap, onStatus, onEvent, random: () => 0.5 })
  await vi.advanceTimersByTimeAsync(0)
  streams[0].events.hello({ data: '{"replay":"none"}' })
  streams[0].onmessage({ data: '{"entity":"product"}', lastEventId: 'epoch-12' })
  streams[0].events.rotate()
  await vi.advanceTimersByTimeAsync(500)
  expect(streams[0].close).toHaveBeenCalledOnce()
  expect(streams[1].url).toContain('last_event_id=epoch-12')
  streams[1].events.hello({ data: '{"replay":"complete"}' })
  expect(onGap).not.toHaveBeenCalled()
  expect(onStatus).not.toHaveBeenCalledWith('degraded')
  streams[1].events.hello({ data: '{"replay":"gap"}' })
  expect(onGap).toHaveBeenCalledOnce()
  connection.close()
})
it('shows degradation only after thirty seconds and cancels delayed work on teardown', async () => {
  const onStatus = vi.fn()
  const connection = createSseConnection({ fetchTicket: async () => { throw new Error('waking') }, onStatus, random: () => 0.5 })
  await vi.advanceTimersByTimeAsync(29999)
  expect(onStatus).not.toHaveBeenCalled()
  await vi.advanceTimersByTimeAsync(1)
  expect(onStatus).toHaveBeenCalledWith('degraded')
  connection.close()
  expect(vi.getTimerCount()).toBe(0)
})
it('retains the hello cursor when a gap is followed by a silent disconnect', async () => {
  const connection = createSseConnection({ fetchTicket: async () => 'https://api.test/realtime/events?ticket=fresh', random: () => 0.5 })
  await vi.advanceTimersByTimeAsync(0)
  streams[0].events.hello({ data: '{"replay":"gap","cursor":"new-epoch-47"}' })
  streams[0].onerror()
  await vi.advanceTimersByTimeAsync(1000)
  expect(streams[1].url).toContain('last_event_id=new-epoch-47')
  connection.close()
})
