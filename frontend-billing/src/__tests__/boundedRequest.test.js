import { afterEach, expect, it, vi } from 'vitest'
import { boundedJsonFetch, requestBudget } from '../api/boundedRequest'

afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals() })

it('uses one recovery deadline across requests and their response bodies', async () => {
  vi.useFakeTimers()
  let resolveFirst
  const fetch = vi.fn()
    .mockImplementationOnce(() => new Promise(resolve => { resolveFirst = resolve }))
    .mockResolvedValueOnce({ ok: true, status: 200, json: () => new Promise(() => {}) })
  vi.stubGlobal('fetch', fetch)
  const request = requestBudget(3000)
  const first = request('/cloud/login', {}, 2500)
  await vi.advanceTimersByTimeAsync(2000)
  resolveFirst({ ok: true, status: 200, json: async () => ({ token: 'synthetic' }) })
  expect(await (await first).json()).toEqual({ token: 'synthetic' })
  const second = expect(request('/local/mirror', {}, 2500)).rejects.toMatchObject({ code: 'AUTH_REQUEST_TIMEOUT' })
  await vi.advanceTimersByTimeAsync(1000)
  await second
  expect(fetch).toHaveBeenCalledTimes(2)
})

it('cancels a pending response-body read when its initiating request is aborted', async () => {
  const controller = new AbortController()
  vi.stubGlobal('fetch', vi.fn(async () => ({ ok: true, status: 200, json: () => new Promise(() => {}) })))
  const pending = expect(boundedJsonFetch('/auth/recovery', { signal: controller.signal })).rejects.toMatchObject({ code: 'AUTH_REQUEST_TIMEOUT' })
  await Promise.resolve()
  controller.abort()
  await pending
})

it('does not issue the next recovery request after account ownership changes', async () => {
  let current = true
  const request = requestBudget(3000, () => current)
  const fetch = vi.fn(async () => ({ ok: true, status: 200, json: async () => ({}) }))
  vi.stubGlobal('fetch', fetch)
  await request('/cloud/login')
  current = false
  await expect(request('/local/mirror')).rejects.toMatchObject({ name: 'AbortError' })
  expect(fetch).toHaveBeenCalledOnce()
})
