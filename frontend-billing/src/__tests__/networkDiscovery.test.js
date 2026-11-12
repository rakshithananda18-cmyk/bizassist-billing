import { afterEach, beforeEach, expect, it, vi } from 'vitest'

const config = vi.hoisted(() => ({ local: false }))
vi.mock('../config', () => ({ CLOUD_URL: 'https://cloud.test', get IS_LOCAL_APP() { return config.local } }))
import { clearDiscoveryCache, discoverLocalBackend, getDiscoveredLocalBackend, getNetworkMode, probeLocalBackend } from '../utils/networkDiscovery'

const CACHE = 'bizassist_discovered_local_url'
const healthy = { status: 'ok', db: 'connected', db_type: 'sqlite', version: 'test' }
const json = body => new Response(JSON.stringify(body), { status: 200, headers: { 'content-type': 'application/json' } })
const user = id => localStorage.setItem('billing_user', JSON.stringify({ public_id: id }))
const cached = (bizId, url, extra = {}) => localStorage.setItem(CACHE, JSON.stringify({ bizId, url, ts: Date.now(), ...extra }))

beforeEach(() => {
  const values = new Map()
  vi.stubGlobal('localStorage', {
    getItem: key => values.get(key) ?? null,
    setItem: (key, value) => values.set(key, String(value)),
    removeItem: key => values.delete(key),
  })
  vi.stubGlobal('location', { protocol: 'https:' })
  vi.stubGlobal('fetch', vi.fn())
  config.local = false
  user('BA-A')
  clearDiscoveryCache()
})
afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); vi.restoreAllMocks() })

it('filters insecure LAN registry URLs before any health fetch on the HTTPS web app', async () => {
  fetch.mockResolvedValue(json({ biz_id: 'BA-A', backends: [{ url: 'http://192.168.88.9:8001' }] }))
  expect(await discoverLocalBackend('BA-A')).toBeNull()
  expect(fetch.mock.calls.map(([url]) => url)).toEqual(['https://cloud.test/discover/BA-A'])
  expect(getDiscoveredLocalBackend()).toBeNull()
  expect(getNetworkMode()).toBe('cloud')
})

it('can verify a compatible HTTPS local server without converting the web session into a local login', async () => {
  fetch.mockImplementation(async url => String(url).includes('/discover/')
    ? json({ biz_id: 'BA-A', backends: [{ url: 'http://192.168.88.9:8001' }, { url: 'https://local.test:8001/' }] })
    : json(healthy))
  expect(await discoverLocalBackend('BA-A')).toBe('https://local.test:8001')
  expect(fetch.mock.calls.map(([url]) => url)).toEqual(['https://cloud.test/discover/BA-A', 'https://local.test:8001/health'])
  expect(getDiscoveredLocalBackend()).toBe('https://local.test:8001')
  expect(getNetworkMode()).toBe('cloud')
  expect(fetch.mock.calls[1][1]).toMatchObject({ credentials: 'omit', redirect: 'error' })
  expect(fetch.mock.calls[1][1].headers).toBeUndefined()
})

it('uses only a matching fresh cache and validates its server again', async () => {
  cached('BA-A', 'https://local.test:8001')
  fetch.mockResolvedValue(json(healthy))
  expect(await discoverLocalBackend('BA-A')).toBe('https://local.test:8001')
  expect(fetch.mock.calls.map(([url]) => url)).toEqual(['https://local.test:8001/health'])
})

it.each([
  { bizId: 'BA-OTHER', url: 'https://old.test' },
  { url: 'https://legacy-unscoped.test' },
  { bizId: 'BA-A', url: 'http://192.168.88.9:8001' },
  { bizId: 'BA-A', url: 'http://127.0.0.1.evil.test:8001' },
  { bizId: 'BA-A', url: 'javascript:alert(1)' },
  { bizId: 'BA-A', url: 'https://user:password@local.test' },
  { bizId: 'BA-A', url: 'https://local.test', ts: 0 },
  { bizId: 'BA-A', url: 'https://local.test', ts: Number.MAX_SAFE_INTEGER },
])('discards incompatible or unscoped cached hints without probing: %j', entry => {
  localStorage.setItem(CACHE, JSON.stringify({ ts: Date.now(), ...entry }))
  expect(getDiscoveredLocalBackend()).toBeNull()
  expect(localStorage.getItem(CACHE)).toBeNull()
  expect(fetch).not.toHaveBeenCalled()
})

it('does not let a delayed discovery overwrite another business connection hint', async () => {
  let finishA
  fetch.mockImplementation(async url => {
    if (url.endsWith('/discover/BA-A')) return json({ biz_id: 'BA-A', backends: [{ url: 'https://a.test' }] })
    if (url === 'https://a.test/health') return { ok: true, json: () => new Promise(resolve => { finishA = resolve }) }
    if (url.endsWith('/discover/BA-B')) return json({ biz_id: 'BA-B', backends: [{ url: 'https://b.test' }] })
    return json(healthy)
  })
  const a = discoverLocalBackend('BA-A')
  await vi.waitFor(() => expect(finishA).toBeTypeOf('function'))
  user('BA-B')
  expect(await discoverLocalBackend('BA-B')).toBe('https://b.test')
  finishA(healthy)
  expect(await a).toBeNull()
  expect(getDiscoveredLocalBackend('BA-B')).toBe('https://b.test')
})

it('bounds a stalled health response body', async () => {
  vi.useFakeTimers()
  fetch.mockResolvedValue({ ok: true, json: () => new Promise(() => {}) })
  const result = probeLocalBackend('https://local.test')
  await vi.advanceTimersByTimeAsync(1501)
  expect(await result).toMatchObject({ ok: false, error: 'Connection check timed out.' })
})

it('bounds a stalled registry response body and does not proceed to LAN probes', async () => {
  vi.useFakeTimers()
  fetch.mockResolvedValue({ ok: true, json: () => new Promise(() => {}) })
  const result = discoverLocalBackend('BA-A')
  await vi.advanceTimersByTimeAsync(4001)
  expect(await result).toBeNull()
  expect(fetch).toHaveBeenCalledOnce()
})

it('preserves HTTP local app checks and reports its actual selected mode', async () => {
  config.local = true
  location.protocol = 'http:'
  fetch.mockResolvedValue(json(healthy))
  expect(await discoverLocalBackend('BA-A')).toBeNull()
  expect(fetch).not.toHaveBeenCalled()
  expect(await probeLocalBackend('http://192.168.88.9:8001')).toMatchObject({ ok: true })
  expect(getNetworkMode()).toBe('local')
  localStorage.setItem('bizassist_hosting_mode', 'cloud')
  expect(getNetworkMode()).toBe('cloud')
})

it.each(['http://localhost:8001', 'http://127.0.0.1:8001', 'http://[::1]:8001'])('retains explicit loopback checks where permitted by the browser: %s', async url => {
  fetch.mockResolvedValue(json(healthy))
  expect(await probeLocalBackend(url)).toMatchObject({ ok: true })
})

it('does not treat an unhealthy or wrong-business server as a verified local database', async () => {
  fetch.mockResolvedValueOnce(json({ ...healthy, db: 'disconnected' })).mockResolvedValueOnce(json({ ...healthy, public_id: 'BA-OTHER' }))
  expect(await probeLocalBackend('https://local.test')).toMatchObject({ ok: false })
  expect(await probeLocalBackend('https://local.test', { expectedBizId: 'BA-A' })).toMatchObject({ ok: false })
})
