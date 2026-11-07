// @vitest-environment jsdom
import { describe, it, expect } from 'vitest'
import { isSessionRejection, readableError, retryDelayMs } from '../api/httpErrors'
import { getApiBase } from '../config'
describe('cloud error boundaries', () => {
  it.each([429, 500, 502, 503, 504])('does not expose gateway HTML for %s', status => {
    expect(readableError(status, 'text/html', '<html>gateway error</html>')).not.toContain('<')
  })
  it.each([401, 404])('requires the session marker and own origin for %s', status => {
    const response = (url, marker) => ({ status, url, headers: new Headers(marker ? { 'WWW-Authenticate': 'Bearer error="invalid_token"' } : {}) })
    expect(isSessionRejection(response(`${getApiBase()}/profile`, true))).toBe(true)
    expect(isSessionRejection(response(`${getApiBase()}/profile`, false))).toBe(false)
    expect(isSessionRejection(response('https://unrelated.test/profile', true))).toBe(false)
  })
  it('honours seconds and dates while bounding retries', () => {
    expect(retryDelayMs(0, '12')).toBe(12000)
    expect(retryDelayMs(0, '120')).toBe(30000)
    expect(retryDelayMs(0, new Date(Date.now() + 10000).toUTCString())).toBeGreaterThan(8500)
    expect(retryDelayMs(1, 'bad')).toBe(2000)
  })
})
