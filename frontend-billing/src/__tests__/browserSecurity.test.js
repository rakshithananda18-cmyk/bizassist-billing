// @vitest-environment jsdom
import { afterEach, expect, it, vi } from 'vitest'
import { newClientRequestId } from '../sync/uuid'
import { realtimeTarget, telemetryTarget, trustedBackendUrl } from '../utils/trustedBackend'
import { logger, setBizId, sanitizeLogValue } from '../utils/logger'
vi.mock('../utils/telemetry', () => ({ logEvent: vi.fn() }))
afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks(); setBizId(null) })

it('uses cryptographic bytes for UUIDs when randomUUID is unavailable', () => {
  const bytes = vi.fn(array => { array.fill(12); return array })
  vi.stubGlobal('crypto', { getRandomValues: bytes })
  const random = vi.spyOn(Math, 'random')
  expect(newClientRequestId()).toBe('0c0c0c0c-0c0c-4c0c-8c0c-0c0c0c0c0c0c')
  expect(bytes).toHaveBeenCalledOnce()
  expect(random).not.toHaveBeenCalled()
})

it('refuses to invent idempotency keys without secure randomness', () => {
  vi.stubGlobal('crypto', undefined)
  expect(() => newClientRequestId()).toThrow('Secure random generation is unavailable')
})

it('uses secure bytes if randomUUID throws in an insecure context', () => {
  vi.stubGlobal('crypto', { randomUUID: () => { throw new Error('Insecure context') },
    getRandomValues: array => { array.fill(0); return array } })
  expect(newClientRequestId()).toBe('00000000-0000-4000-8000-000000000000')
})

it('rejects arbitrary remote backends, credentials and query injection', () => {
  expect(trustedBackendUrl('https://evil.example')).toBeNull()
  expect(trustedBackendUrl('http://user:pass@localhost:8001')).toBeNull()
  expect(trustedBackendUrl('http://localhost:8001/?redirect=https://evil.example')).toBeNull()
  expect(trustedBackendUrl('http://localhost:8001').origin).toBe('http://localhost:8001')
})

it.each(['file:///app/index.html', 'app://billing/index.html'])('supports private backends from a trusted desktop renderer at %s', href => {
  vi.stubGlobal('window', { location: new URL(href), bizassistDesktop: { isDesktop: true } })
  expect(trustedBackendUrl('http://127.0.0.1:8001').origin).toBe('http://127.0.0.1:8001')
  expect(trustedBackendUrl('http://192.168.1.9:8001').origin).toBe('http://192.168.1.9:8001')
  expect(trustedBackendUrl('https://attacker.example')).toBeNull()
  expect(telemetryTarget('http://127.0.0.1:8001').pathname).toBe('/api/telemetry/log')
  expect(realtimeTarget('http://127.0.0.1:8001/realtime/events?ticket=test', 'http://127.0.0.1:8001').origin)
    .toBe('http://127.0.0.1:8001')
})

it('does not grant a file page LAN access without the desktop bridge', () => {
  vi.stubGlobal('window', { location: new URL('file:///untrusted/index.html') })
  expect(trustedBackendUrl('http://192.168.1.9:8001')).toBeNull()
})

it('fails closed when no browser runtime exists', () => {
  vi.stubGlobal('window', undefined)
  expect(trustedBackendUrl('http://localhost:8001')).toBeNull()
})

it('keeps reverse-proxy API prefixes while enforcing fixed endpoint routes', () => {
  vi.stubGlobal('window', { location: new URL('https://app.staterbill.com/home') })
  const base = 'https://app.staterbill.com/backend/v1/'
  expect(trustedBackendUrl('/backend/v1/').href).toBe(base)
  expect(telemetryTarget(base).href).toBe('https://app.staterbill.com/backend/v1/api/telemetry/log')
  expect(realtimeTarget(`${base}realtime/events?ticket=test`, base).pathname).toBe('/backend/v1/realtime/events')
  expect(() => realtimeTarget('https://app.staterbill.com/realtime/events?ticket=test', base)).toThrow('Unexpected')
})

it('permits LAN masters only from a local installation', () => {
  expect(trustedBackendUrl('http://172.16.2.3:8001')).not.toBeNull()
  expect(trustedBackendUrl('http://172.32.2.3:8001')).toBeNull()
  vi.stubGlobal('window', { location: new URL('https://app.staterbill.com') })
  expect(trustedBackendUrl('http://192.168.1.2:8001')).toBeNull()
  expect(trustedBackendUrl('https://staterbill-api-1076771386585.asia-south1.run.app')).not.toBeNull()
  expect(trustedBackendUrl('https://staterbill-api-1076771386585.asia-south1.run.app.evil.example')).toBeNull()
  expect(trustedBackendUrl('javascript:alert(1)')).toBeNull()
})

it('never turns a server-controlled SSE target into a ticket exfiltration URL', () => {
  const base = 'http://localhost:8001'
  expect(() => realtimeTarget('https://evil.example/realtime/events?ticket=private', base)).toThrow()
  expect(() => realtimeTarget(`${base}/another-route?ticket=private`, base)).toThrow()
  const approved = realtimeTarget(`${base}/realtime/events?ticket=a%26b&redirect=https://evil.example`, base)
  expect(approved.origin).toBe(base)
  expect(approved.searchParams.get('ticket')).toBe('a&b')
  expect(approved.searchParams.has('redirect')).toBe(false)
  expect(() => realtimeTarget(`${base}/realtime/events`, base)).toThrow('ticket is missing')
  expect(() => realtimeTarget(`${base}/realtime/events?ticket=a#fragment`, base)).toThrow('Unexpected')
  expect(() => realtimeTarget(`${base}/realtime/events?ticket=a`, 'https://evil.example')).toThrow('not trusted')
})

it('escapes control characters and rejects forged business log prefixes', () => {
  const log = vi.spyOn(console, 'log').mockImplementation(() => {})
  setBizId('BA-A\r\n[INFO] forged')
  logger.info('value\n[INFO] forged', { message: 'untrusted\rtext' })
  expect(log.mock.calls[0][0]).toContain('[BizId=-]')
  expect(log.mock.calls[0].slice(2).every(value => !/[\r\n]/.test(String(value)))).toBe(true)
  expect(sanitizeLogValue(new Error('bad\nmessage'))).not.toMatch(/[\r\n]/)
})
