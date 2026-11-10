import { afterEach, expect, it, vi } from 'vitest'
import { boundedFetch, isSessionRejection } from '../utils/httpErrors'
afterEach(() => { vi.unstubAllGlobals(); vi.useRealTimers() })
it('honours Retry-After for a safe GET during startup', async () => {
  vi.useFakeTimers()
  const fetcher = vi.fn().mockResolvedValueOnce(new Response('<html>Starting</html>', { status: 503, headers: { 'Retry-After': '3', 'Content-Type': 'text/html' } })).mockResolvedValueOnce(new Response('{}', { status: 200 }))
  vi.stubGlobal('fetch', fetcher)
  const pending = boundedFetch('/api/settings')
  await vi.advanceTimersByTimeAsync(2999)
  expect(fetcher).toHaveBeenCalledTimes(1)
  await vi.advanceTimersByTimeAsync(1)
  expect((await pending).status).toBe(200)
  expect(fetcher).toHaveBeenCalledTimes(2)
})
it('does not repeat a mutation and makes an HTML failure readable', async () => {
  const fetcher = vi.fn(async () => new Response('<html>Unavailable</html>', { status: 503, headers: { 'Content-Type': 'text/html' } }))
  vi.stubGlobal('fetch', fetcher)
  const response = await boundedFetch('/api/login', { method: 'POST' })
  expect(response.status).toBe(503)
  expect((await response.json()).detail).toMatch(/server is starting/i)
  expect(fetcher).toHaveBeenCalledTimes(1)
})
it('requires the explicit session rejection header', () => {
  expect(isSessionRejection(new Response('{}', { status: 401 }))).toBe(false)
  expect(isSessionRejection(new Response('{}', { status: 401, headers: { 'WWW-Authenticate': 'Bearer error="invalid_token"' } }))).toBe(true)
})

