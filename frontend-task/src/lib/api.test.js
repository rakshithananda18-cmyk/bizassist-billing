/*
 * Bug condition exploration, task 1.7 (C10). Property 1 (bug condition). Clauses 1.4 and
 * 1.5, expected 2.4 and 2.5.
 *
 * The cases in "connection failures and the ticket exchange during a cold start" encode
 * the expected behaviour and must FAIL on the unfixed code. The "business-scoped requests"
 * case is existing behaviour and keeps passing.
 *
 * Expected counterexamples, read from src/lib/api.js (request() maps every fetch failure
 * to one offline message and never retries):
 *   - A fetch that rejects while navigator.onLine is true rejects with
 *     'No connection — check mobile data / Wi-Fi.' instead of
 *     'Could not reach the Field Team server. It may be starting up.'
 *   - api.post('/api/auth/exchange', { ticket }) for a 90 s field_team ticket (iat inside the
 *     payload, so the retry window is exp - iat + 10 = 100 s from page start) rejects with
 *     ApiError 'Request failed (503)' after the first HTML 503: fetch runs once and is never
 *     retried, with a correct phone clock and with a phone clock 10 minutes fast.
 *
 * Run in frontend-task: npx vitest run --pool=threads --reporter=dot
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { request, tokenStore } from './api'

let stored
let unauthorized
beforeEach(() => {
  stored = new Map()
  unauthorized = vi.fn()
  vi.stubGlobal('localStorage', { getItem: key => stored.get(key) || null, setItem: (key, value) => stored.set(key, value), removeItem: key => stored.delete(key) })
  vi.stubGlobal('window', { dispatchEvent: unauthorized })
})
afterEach(() => vi.unstubAllGlobals())

describe('business-scoped requests', () => {
  it.each([false, true])('keeps unmarked 401s separate from rejected sessions (marked=%s)', async marked => {
    tokenStore.set('current-token')
    vi.stubGlobal('fetch', vi.fn(async () => ({
      ok: false, status: 401,
      headers: new Headers(marked ? { 'WWW-Authenticate': 'Bearer error="invalid_token"' } : {}),
      text: async () => JSON.stringify({ detail: 'Not authenticated' }),
    })))
    await expect(request('GET', '/api/auth/me')).rejects.toMatchObject({ status: 401, sessionRejected: marked })
    expect(unauthorized).toHaveBeenCalledTimes(marked ? 1 : 0)
  })
  it.each([200, 401])('discards an old-business HTTP %s response without signing out the new session', async status => {
    let resolve
    tokenStore.set('old')
    vi.stubGlobal('fetch', vi.fn(() => new Promise(done => { resolve = done })))
    const pending = request('GET', '/api/shops')
    const rejected = expect(pending).rejects.toMatchObject({ status: 409 })
    tokenStore.set('new')
    resolve({ ok: status === 200, status, text: async () => JSON.stringify({ detail: 'old data' }) })
    await rejected
    expect(tokenStore.get()).toBe('new')
    expect(unauthorized).not.toHaveBeenCalled()
  })
})

// A field_team hand-off ticket in billing's format, "<exp>.<base64url payload>.<hex HMAC>",
// with iat and aud inside the signed payload (C4). The signature is never checked here.
const MINTED_AT = Math.floor(Date.now() / 1000)
const base64url = text => btoa(text).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '')
const FIELD_TEAM_TICKET = `${MINTED_AT + 90}.${base64url(JSON.stringify({ aud: 'field_team', iat: MINTED_AT, role: 'owner', sub: '7' }))}.${'ab'.repeat(32)}`
const reply = (status, body, contentType = 'application/json') => ({
  ok: status >= 200 && status < 300, status, headers: new Headers({ 'content-type': contentType }),
  text: async () => body, json: async () => JSON.parse(body),
})

describe('connection failures and the ticket exchange during a cold start (1.4, 1.5)', () => {
  beforeEach(() => {
    const browser = { onLine: true }
    vi.stubGlobal('navigator', browser)
    // Browser-like window: the stubs this file needs, everything else from the global scope.
    vi.stubGlobal('window', Object.assign(Object.create(globalThis), { dispatchEvent: unauthorized, navigator: browser }))
  })
  afterEach(() => vi.useRealTimers())

  it('says the Field Team server could not be reached when a request fails while the browser is online', async () => {
    vi.useFakeTimers()
    vi.stubGlobal('fetch', vi.fn(async () => { throw new TypeError('Failed to fetch') }))
    const failure = request('GET', '/api/shops').then(() => null, error => error)
    await vi.advanceTimersByTimeAsync(60_000)
    expect((await failure)?.message).toBe('Could not reach the Field Team server. It may be starting up.')
  })

  it.each([
    ['a correct phone clock', 3],
    ['a phone clock 10 minutes fast', 600],
  ])('retries an HTML 503 from POST /api/auth/exchange inside the exp - iat + 10 window with %s', async (_clock, skewSeconds) => {
    vi.useFakeTimers()
    vi.setSystemTime((MINTED_AT + skewSeconds) * 1000)
    vi.resetModules()
    const { api: pageApi } = await import('./api') // the page starts with this clock
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(reply(503, '<html><title>503 Service Unavailable</title></html>', 'text/html; charset=UTF-8'))
      .mockResolvedValueOnce(reply(200, JSON.stringify({ token: 'field-token', public_id: 'BA-NEW' })))
    vi.stubGlobal('fetch', fetchMock)
    const outcome = pageApi.post('/api/auth/exchange', { ticket: FIELD_TEAM_TICKET })
      .then(data => ({ data }), error => ({ error: error.message }))
    await vi.advanceTimersByTimeAsync(5000)
    expect(await outcome).toEqual({ data: { token: 'field-token', public_id: 'BA-NEW' } })
    expect(fetchMock).toHaveBeenCalledTimes(2)
    expect(fetchMock.mock.calls.every(([url]) => String(url).endsWith('/api/auth/exchange'))).toBe(true)
  })
})
