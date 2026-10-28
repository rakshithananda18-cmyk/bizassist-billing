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
