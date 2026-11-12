// @vitest-environment jsdom
import { beforeEach, afterEach, it, expect, vi } from 'vitest'
import { request } from '../api/client'
import { getApiBase } from '../config'
import { tokenStorage } from '../utils/tokenStorage'
import { refreshSession, resilientSessionFetch, invalidateSessionRefresh } from '../api/session'

beforeEach(() => { localStorage.clear(); tokenStorage.setItem('billing_token', 'current-session') })
afterEach(() => { vi.useRealTimers(); vi.restoreAllMocks(); vi.unstubAllGlobals() })
const response = (status, body, marker = false) => {
  const res = new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json', ...(marker ? { 'WWW-Authenticate': 'Bearer error="invalid_token"' } : {}) } })
  Object.defineProperty(res, 'url', { value: `${getApiBase()}/profile` })
  return res
}
it('abandons an old retry after an account switch without rejecting the new session', async () => {
  vi.useFakeTimers()
  const rejected = vi.fn()
  window.addEventListener('auth_unauthorized', rejected)
  const fetch = vi.fn().mockResolvedValueOnce(response(503, {})).mockResolvedValue(response(401, {}, true))
  vi.stubGlobal('fetch', fetch)
  const pending = expect(resilientSessionFetch(`${getApiBase()}/profile`, {
    headers: { Authorization: 'Bearer current-session' },
  })).rejects.toMatchObject({ name: 'AbortError' })
  await vi.advanceTimersByTimeAsync(0)
  tokenStorage.setItem('billing_token', 'different-business-session')
  invalidateSessionRefresh()
  await vi.advanceTimersByTimeAsync(2000)
  await pending
  expect(fetch).toHaveBeenCalledOnce()
  expect(rejected).not.toHaveBeenCalled()
  expect(tokenStorage.getItem('billing_token')).toBe('different-business-session')
  window.removeEventListener('auth_unauthorized', rejected)
})
it('discards a stale successful refresh after its response body arrives in a newer account session', async () => {
  let finishBody
  const fetch = vi.fn(async () => ({ ok: true, status: 200, json: () => new Promise(resolve => { finishBody = resolve }) }))
  vi.stubGlobal('fetch', fetch)
  const pending = refreshSession()
  await vi.waitFor(() => expect(finishBody).toBeTypeOf('function'))
  tokenStorage.setItem('billing_token', 'new-account-session')
  invalidateSessionRefresh()
  finishBody({ token: 'stale-refreshed-account-token' })
  expect(await pending).toBeNull()
  expect(tokenStorage.getItem('billing_token')).toBe('new-account-session')
})
it('keeps a session when a resource is missing', async () => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(response(404, { detail: 'Missing report' })))
  const reject = vi.fn(); window.addEventListener('auth_unauthorized', reject)
  await expect(request('GET', '/profile')).rejects.toMatchObject({ status: 404 })
  expect(reject).not.toHaveBeenCalled()
  window.removeEventListener('auth_unauthorized', reject)
})
it('refreshes once on an unmarked 401 and retries with the new token', async () => {
  const fetch = vi.fn().mockResolvedValueOnce(response(401, {})).mockResolvedValueOnce(response(200, { token: 'refreshed-session' })).mockResolvedValueOnce(response(200, { business_name: 'Mine' }))
  vi.stubGlobal('fetch', fetch)
  expect(await request('GET', '/profile')).toEqual({ business_name: 'Mine' })
  expect(fetch).toHaveBeenCalledTimes(3)
  expect(fetch.mock.calls[2][1].headers.Authorization).toBe('Bearer refreshed-session')
})
it('shares an in-flight refresh and rejects marked expired sessions without a retry', async () => {
  const fetch = vi.fn().mockResolvedValue(response(200, { token: 'next' }))
  vi.stubGlobal('fetch', fetch)
  await Promise.all([refreshSession(), refreshSession()])
  expect(fetch).toHaveBeenCalledTimes(1)
  fetch.mockResolvedValue(response(401, { detail: 'Expired' }, true))
  const reject = vi.fn(); window.addEventListener('auth_unauthorized', reject)
  await expect(request('GET', '/profile')).rejects.toMatchObject({ status: 401 })
  expect(reject).toHaveBeenCalledOnce()
  window.removeEventListener('auth_unauthorized', reject)
})
