// @vitest-environment jsdom
import { beforeEach, afterEach, it, expect, vi } from 'vitest'
import { request } from '../api/client'
import { getApiBase } from '../config'
import { tokenStorage } from '../utils/tokenStorage'
import { refreshSession, sessionFetch, resilientSessionFetch, invalidateSessionRefresh } from '../api/session'

beforeEach(() => { localStorage.clear(); invalidateSessionRefresh(); tokenStorage.setItem('billing_token', 'current-session') })
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

it('announces a burst of current-session rejections once', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => response(401, { detail: 'Expired' }, true)))
  const rejected = vi.fn()
  window.addEventListener('auth_unauthorized', rejected)
  await Promise.all([
    sessionFetch(`${getApiBase()}/profile`),
    sessionFetch(`${getApiBase()}/settings`),
    sessionFetch(`${getApiBase()}/business/config`),
  ])
  expect(rejected).toHaveBeenCalledOnce()
  tokenStorage.setItem('billing_token', 'new-session')
  invalidateSessionRefresh()
  await sessionFetch(`${getApiBase()}/profile`)
  expect(rejected).toHaveBeenCalledTimes(2)
  window.removeEventListener('auth_unauthorized', rejected)
})

it('does not let an old refresh block or clear the new session refresh', async () => {
  let finishOld, finishNew
  const fetch = vi.fn()
    .mockResolvedValueOnce({ ok: true, status: 200, json: () => new Promise(resolve => { finishOld = resolve }) })
    .mockResolvedValueOnce({ ok: true, status: 200, json: () => new Promise(resolve => { finishNew = resolve }) })
  vi.stubGlobal('fetch', fetch)
  const previous = refreshSession()
  await vi.waitFor(() => expect(finishOld).toBeTypeOf('function'))
  tokenStorage.setItem('billing_token', 'new-login')
  invalidateSessionRefresh()
  const current = refreshSession()
  await vi.waitFor(() => expect(finishNew).toBeTypeOf('function'))
  finishOld({ token: 'old-refresh' })
  expect(await previous).toBeNull()
  const shared = refreshSession()
  expect(fetch).toHaveBeenCalledTimes(2)
  finishNew({ token: 'new-login-refreshed' })
  expect(await current).toBe('new-login-refreshed')
  expect(await shared).toBe('new-login-refreshed')
  expect(tokenStorage.getItem('billing_token')).toBe('new-login-refreshed')
})

it('bounds a refresh whose response body never completes', async () => {
  vi.useFakeTimers()
  vi.stubGlobal('fetch', vi.fn(async () => ({ ok: true, status: 200, json: () => new Promise(() => {}) })))
  const pending = refreshSession()
  await vi.advanceTimersByTimeAsync(65000)
  expect(await pending).toBeNull()
  expect(tokenStorage.getItem('billing_token')).toBe('current-session')
})

it('cancels a stale HTTP rejection rather than returning it to a new session', async () => {
  let respond
  vi.stubGlobal('fetch', vi.fn(() => new Promise(resolve => { respond = resolve })))
  const rejected = vi.fn()
  window.addEventListener('auth_unauthorized', rejected)
  const pending = sessionFetch(`${getApiBase()}/profile`)
  tokenStorage.setItem('billing_token', 'new-owner')
  invalidateSessionRefresh()
  respond(response(401, { detail: 'Expired' }, true))
  await expect(pending).rejects.toMatchObject({ name: 'AbortError' })
  expect(rejected).not.toHaveBeenCalled()
  window.removeEventListener('auth_unauthorized', rejected)
})

it('honors the caller deadline while allowing a shared refresh to finish for other requests', async () => {
  vi.useFakeTimers()
  let finishRefresh
  const fetch = vi.fn()
    .mockResolvedValueOnce(response(401, {}))
    .mockResolvedValueOnce({ ok: true, status: 200, json: () => new Promise(resolve => { finishRefresh = resolve }) })
  vi.stubGlobal('fetch', fetch)
  const request = expect(resilientSessionFetch(`${getApiBase()}/profile`, {
    headers: { Authorization: 'Bearer current-session' },
  }, { budgetMs: 1000 })).rejects.toMatchObject({ name: 'AbortError' })
  await vi.advanceTimersByTimeAsync(0)
  expect(finishRefresh).toBeTypeOf('function')
  const shared = refreshSession()
  await vi.advanceTimersByTimeAsync(1000)
  await request
  finishRefresh({ token: 'background-refreshed-session' })
  expect(await shared).toBe('background-refreshed-session')
  expect(fetch).toHaveBeenCalledTimes(2)
})
