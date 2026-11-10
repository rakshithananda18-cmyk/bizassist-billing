import { beforeEach, afterEach, describe, expect, it, vi } from 'vitest'

vi.unmock('../utils/telemetry')
vi.mock('../config', () => ({ API_BASE: 'https://staterbill-api-1076771386585.asia-south1.run.app' }))

let telemetry, consent, handlers
beforeEach(async () => {
  vi.resetModules()
  vi.useFakeTimers()
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true }))
  handlers = {}
  vi.spyOn(window, 'addEventListener').mockImplementation((name, callback) => { handlers[name] = callback })
  vi.spyOn(document, 'addEventListener').mockImplementation(() => {})
  consent = await import('../utils/storageConsent')
  telemetry = await import('../utils/telemetry')
})
afterEach(() => { vi.clearAllTimers(); vi.useRealTimers(); vi.restoreAllMocks(); vi.unstubAllGlobals() })

describe('optional diagnostics consent', () => {
  it('sends no automatic diagnostics or browser ID before acceptance', async () => {
    telemetry.initTelemetry()
    telemetry.logEvent('print_failed')
    expect(telemetry.sendDiagnostics('boot_health_check')).toBe(false)
    await vi.advanceTimersByTimeAsync(20001)
    expect(fetch).not.toHaveBeenCalled()
    expect(localStorage.getItem('web_device_id')).toBeNull()
  })

  it('keeps essential-only users out of automatic diagnostics', async () => {
    consent.saveStorageConsent(false)
    telemetry.initTelemetry()
    handlers.error({ message: 'print failed', error: new Error('failed') })
    await vi.advanceTimersByTimeAsync(20001)
    expect(fetch).not.toHaveBeenCalled()
  })

  it('sends errors after opt-in and retains the diagnostic ID only then', async () => {
    consent.saveStorageConsent(true)
    telemetry.initTelemetry()
    telemetry.logEvent('print_failed', { template: 'thermal' }, 'warn')
    await vi.advanceTimersByTimeAsync(20001)
    expect(fetch).toHaveBeenCalledTimes(1)
    const body = JSON.parse(fetch.mock.calls[0][1].body)
    expect(body.events[0].event).toBe('print_failed')
    expect(body.device_id).toBe(localStorage.getItem('web_device_id'))
    expect(fetch.mock.calls[0][1].credentials).toBe('omit')
  })

  it('does not flush queued events after diagnostics are declined', async () => {
    consent.saveStorageConsent(true)
    telemetry.initTelemetry()
    telemetry.logEvent('pending_error')
    consent.saveStorageConsent(false)
    handlers[consent.STORAGE_CONSENT_CHANGED]()
    await vi.advanceTimersByTimeAsync(20001)
    expect(fetch).not.toHaveBeenCalled()
    expect(localStorage.getItem('web_device_id')).toBeNull()
  })

  it('allows an explicitly requested report without enabling automatic capture', () => {
    window.history.replaceState({}, '', '/login?sso=private-ticket#fragment')
    expect(telemetry.sendDiagnostics()).toBe(true)
    expect(fetch).toHaveBeenCalledTimes(1)
    const body = JSON.parse(fetch.mock.calls[0][1].body)
    expect(body.device_id).toMatch(/^web-oneoff-/)
    expect(body.events[0].payload.url).toBe(`${window.location.origin}/login`)
    expect(localStorage.getItem('web_device_id')).toBeNull()
    expect(consent.diagnosticsAllowed()).toBe(false)
    window.history.replaceState({}, '', '/')
  })

  it('includes queued context immediately in an opted-in manual report', () => {
    consent.saveStorageConsent(true)
    telemetry.logEvent('print_failed')
    expect(telemetry.sendDiagnostics()).toBe(true)
    const body = JSON.parse(fetch.mock.calls[0][1].body)
    expect(body.events.map(event => event.event)).toEqual(['print_failed', 'diagnostics_report'])
  })

  it('honors Essential only when storage writes fail but the previous opt-in is readable', async () => {
    consent.saveStorageConsent(true)
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new DOMException('Full', 'QuotaExceededError') })
    vi.spyOn(Storage.prototype, 'removeItem').mockImplementation(() => { throw new DOMException('Blocked', 'SecurityError') })
    consent.saveStorageConsent(false)
    expect(JSON.parse(localStorage.getItem(consent.STORAGE_CONSENT_KEY)).diagnostics).toBe(true)
    expect(consent.diagnosticsAllowed()).toBe(false)
    telemetry.logEvent('must_not_send')
    await vi.advanceTimersByTimeAsync(20001)
    expect(fetch).not.toHaveBeenCalled()
  })

  it('removes the previous opt-in when quota prevents saving a refusal', () => {
    consent.saveStorageConsent(true)
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new DOMException('Full', 'QuotaExceededError') })
    consent.saveStorageConsent(false)
    expect(localStorage.getItem(consent.STORAGE_CONSENT_KEY)).toBeNull()
    expect(consent.diagnosticsAllowed()).toBe(false)
  })
})
