// audit T6 — reconcileBizIdOnLogin: the cross-device sync nudge is premium-gated
// and bidirectional (cloud-ahead → pull, device-ahead → push).
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { reconcileBizIdOnLogin } from '../utils/loginSync'

const CLOUD = 'https://rakshit-dev-bizassist.hf.space'

// Build a fetch mock: cloud/local /profile carry is_premium; counts drive the
// divergence direction. `premium`, `cloudTotal`, `localTotal` are per-test.
function mockFetch({ premium, cloudTotal, localTotal }) {
  return vi.fn(async (url) => {
    const u = String(url)
    const json = async (body) => ({ ok: true, json: async () => body })
    if (u.includes('/profile')) {
      return json({ public_id: 'BA-TEST', is_premium: premium })
    }
    if (u.includes('/api/data-transfer/count')) {
      const isCloud = u.startsWith(CLOUD)
      return json({ invoices: isCloud ? cloudTotal : localTotal })
    }
    return { ok: false, json: async () => ({}) }
  })
}

function captureSyncEvents() {
  const events = []
  vi.spyOn(window, 'dispatchEvent').mockImplementation((e) => {
    if (e && e.type === 'cloud-data-available') events.push(e.detail)
    return true
  })
  return events
}

beforeEach(() => {
  localStorage.clear()
  localStorage.setItem('bizassist_hosting_mode', 'local')
  if (typeof navigator !== 'undefined') {
    try { Object.defineProperty(navigator, 'onLine', { value: true, configurable: true }) } catch {}
  }
})
afterEach(() => vi.restoreAllMocks())

describe('reconcileBizIdOnLogin (T6)', () => {
  it('does NOT nudge a free account even when cloud has more data', async () => {
    vi.stubGlobal('fetch', mockFetch({ premium: false, cloudTotal: 100, localTotal: 5 }))
    const events = captureSyncEvents()
    await reconcileBizIdOnLogin('local-token', 'cloud-token')
    expect(events).toHaveLength(0)
    vi.unstubAllGlobals()
  })

  it('nudges premium cloud→local when the cloud is ahead', async () => {
    vi.stubGlobal('fetch', mockFetch({ premium: true, cloudTotal: 100, localTotal: 5 }))
    const events = captureSyncEvents()
    await reconcileBizIdOnLogin('local-token', 'cloud-token')
    expect(events).toHaveLength(1)
    expect(events[0].direction).toBe('cloud-to-local')
    expect(events[0].delta).toBe(95)
    vi.unstubAllGlobals()
  })

  it('nudges premium local→cloud when the device is ahead', async () => {
    vi.stubGlobal('fetch', mockFetch({ premium: true, cloudTotal: 5, localTotal: 40 }))
    const events = captureSyncEvents()
    await reconcileBizIdOnLogin('local-token', 'cloud-token')
    expect(events).toHaveLength(1)
    expect(events[0].direction).toBe('local-to-cloud')
    expect(events[0].delta).toBe(35)
    vi.unstubAllGlobals()
  })
})
