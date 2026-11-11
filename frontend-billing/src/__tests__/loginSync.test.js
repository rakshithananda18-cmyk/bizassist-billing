// @vitest-environment jsdom
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
vi.mock('../config', () => ({ IS_LOCAL_APP: true, CLOUD_URL: 'http://cloud', LOCAL_URL: 'http://local' }))
import { reconcileBizIdOnLogin, requestBackgroundSync } from '../utils/loginSync'
import { setHostingPreference } from '../utils/deviceMode'

const response = (body = {}, status = 200) => ({ ok: status >= 200 && status < 300, status, json: async () => body })
const profile = { public_id: 'BA-TEST', is_premium: true }
function transport({ cloudProfile = profile, localProfile = profile, activation = { hosting_mode: 'hybrid', sync_started: true, initial_restore_pending: true }, activationStatus = 200, flushStatus = 202 } = {}) {
  return vi.fn(async (url, options) => {
    if (url === 'http://cloud/profile') return response(cloudProfile)
    if (url === 'http://local/profile') return response(localProfile)
    if (url === 'http://local/api/sync/cloud-token') return response(activation, activationStatus)
    if (url === 'http://local/api/sync/flush?pull=true') return response(flushStatus === 202 ? { status: 'triggered' } : { detail: 'Cloud service is unavailable' }, flushStatus)
    throw new Error(`Unexpected request ${url}`)
  })
}
function events(type) {
  return vi.mocked(window.dispatchEvent).mock.calls.map(([event]) => event).filter(event => event.type === type)
}
beforeEach(() => {
  localStorage.clear()
  localStorage.setItem('bizassist_hosting_mode', 'local')
  localStorage.setItem('bizassist_device_mode_owner', 'BA-TEST')
  Object.defineProperty(navigator, 'onLine', { value: true, configurable: true })
  vi.spyOn(window, 'dispatchEvent')
})
afterEach(() => { vi.useRealTimers(); vi.restoreAllMocks(); vi.unstubAllGlobals() })

describe('Pro login background sync', () => {
  it('verifies backend-specific identities and queues restoration without a data popup or bulk transfer', async () => {
    const fetch = transport()
    vi.stubGlobal('fetch', fetch)
    expect(await reconcileBizIdOnLogin('local-token', 'cloud-token')).toMatchObject({ accepted: true, pending: true })
    expect(fetch.mock.calls[0][1].headers.Authorization).toBe('Bearer cloud-token')
    expect(fetch.mock.calls[1][1].headers.Authorization).toBe('Bearer local-token')
    const activation = fetch.mock.calls.find(([url]) => url.endsWith('/api/sync/cloud-token'))
    expect(activation[1].headers.Authorization).toBe('Bearer local-token')
    expect(JSON.parse(activation[1].body)).toEqual({ token: 'cloud-token', enable_sync: true })
    expect(fetch.mock.calls).toHaveLength(3)
    expect(events('cloud-data-available')).toHaveLength(0)
    expect(events('sync-flushed')).toHaveLength(0)
    expect(events('sync-event').map(event => event.detail)).toEqual([expect.objectContaining({ status: 'pending', accepted: true, initial_restore_pending: true })])
  })

  it('does not activate a cloud account without confirmed Pro even if the local flag is Pro', async () => {
    const fetch = transport({ cloudProfile: { ...profile, is_premium: false } })
    vi.stubGlobal('fetch', fetch)
    expect(await reconcileBizIdOnLogin('local-token', 'cloud-token')).toMatchObject({ skipped: true, reason: 'plan_required' })
    expect(fetch.mock.calls).toHaveLength(2)
    expect(events('sync-event')).toHaveLength(0)
  })

  it('does not activate different business identities', async () => {
    const fetch = transport({ cloudProfile: { ...profile, public_id: 'OTHER-BUSINESS' } })
    vi.stubGlobal('fetch', fetch)
    expect(await reconcileBizIdOnLogin('local-token', 'cloud-token')).toMatchObject({ skipped: true, reason: 'identity_mismatch' })
    expect(fetch.mock.calls).toHaveLength(2)
  })

  it.each(['local-only', 'offline', 'cloud-routing', 'no-cloud-token'])('skips requests for %s', async reason => {
    if (reason === 'local-only') setHostingPreference('BA-TEST', 'local')
    if (reason === 'offline') Object.defineProperty(navigator, 'onLine', { value: false, configurable: true })
    if (reason === 'cloud-routing') localStorage.setItem('bizassist_hosting_mode', 'cloud')
    const fetch = transport()
    vi.stubGlobal('fetch', fetch)
    expect(await reconcileBizIdOnLogin('local-token', reason === 'no-cloud-token' ? null : 'cloud-token')).toMatchObject({ skipped: true })
    expect(fetch).not.toHaveBeenCalled()
  })

  it('abandons delayed identity replies after an account switch', async () => {
    let current = true, release
    const deferred = new Promise(resolve => { release = resolve })
    const fetch = vi.fn(() => deferred)
    vi.stubGlobal('fetch', fetch)
    const pending = reconcileBizIdOnLogin('local-token', 'cloud-token', { isCurrent: () => current })
    current = false
    release(response(profile))
    expect(await pending).toMatchObject({ skipped: true })
    expect(fetch.mock.calls).toHaveLength(2)
    expect(events('sync-event')).toHaveLength(0)
  })

  it('rechecks Local-only after waiting for the serialized hosting write queue', async () => {
    const fetch = transport()
    vi.stubGlobal('fetch', fetch)
    const result = await reconcileBizIdOnLogin('local-token', 'cloud-token', {
      runModeWrite: async operation => { setHostingPreference('BA-TEST', 'local'); return operation() },
    })
    expect(result).toMatchObject({ skipped: true })
    expect(fetch.mock.calls).toHaveLength(2)
    expect(events('sync-event')).toHaveLength(0)
  })

  it('reports activation rejection without blocking sign-in', async () => {
    vi.stubGlobal('fetch', transport({ activation: { detail: 'The Pro subscription has expired' }, activationStatus: 402 }))
    expect(await reconcileBizIdOnLogin('local-token', 'cloud-token')).toMatchObject({ accepted: false, error: 'The Pro subscription has expired' })
    expect(events('sync-event')[0].detail).toMatchObject({ accepted: false, status: 'failed' })
    expect(events('sync-flushed')).toHaveLength(0)
  })

  it('uses the worker flush when activation is ready but has not scheduled a run', async () => {
    const fetch = transport({ activation: { hosting_mode: 'hybrid', sync_started: false } })
    vi.stubGlobal('fetch', fetch)
    expect(await reconcileBizIdOnLogin('local-token', 'cloud-token')).toMatchObject({ accepted: true, pending: true })
    expect(fetch.mock.calls.at(-1)[0]).toBe('http://local/api/sync/flush?pull=true')
  })
})

describe('manual background sync request', () => {
  it('treats HTTP 202 as pending rather than completed', async () => {
    vi.stubGlobal('fetch', transport())
    expect(await requestBackgroundSync('local-token')).toMatchObject({ accepted: true, pending: true })
    expect(events('sync-event')[0].detail.status).toBe('pending')
    expect(events('sync-flushed')).toHaveLength(0)
  })

  it('rejects HTTP failures and never emits a completed event', async () => {
    vi.stubGlobal('fetch', transport({ flushStatus: 503 }))
    await expect(requestBackgroundSync('local-token')).rejects.toThrow('Cloud service is unavailable')
    expect(events('sync-event')[0].detail).toMatchObject({ status: 'failed', accepted: false })
    expect(events('sync-flushed')).toHaveLength(0)
  })

  it('discards a delayed kickoff result when its session changed', async () => {
    let current = true, release
    vi.stubGlobal('fetch', vi.fn(() => new Promise(resolve => { release = resolve })))
    const pending = requestBackgroundSync('local-token', { isCurrent: () => current })
    current = false
    release(response({}, 202))
    expect(await pending).toMatchObject({ skipped: true })
    expect(events('sync-event')).toHaveLength(0)
  })

  it('bounds an unresponsive worker request', async () => {
    vi.useFakeTimers()
    vi.stubGlobal('fetch', vi.fn((_url, options) => new Promise((_resolve, reject) => {
      options.signal.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')), { once: true })
    })))
    const pending = expect(requestBackgroundSync('local-token')).rejects.toThrow(/timed out/)
    await vi.advanceTimersByTimeAsync(10000)
    await pending
    expect(events('sync-flushed')).toHaveLength(0)
  })
})
