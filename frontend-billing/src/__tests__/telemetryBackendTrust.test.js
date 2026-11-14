// @vitest-environment jsdom
import { afterEach, expect, it, vi } from 'vitest'
afterEach(() => { vi.unstubAllGlobals(); vi.doUnmock('../config'); vi.resetModules(); localStorage.clear() })

it('never sends diagnostics to a substituted arbitrary backend', async () => {
  vi.resetModules()
  vi.doMock('../config', () => ({ API_BASE: 'https://attacker.example' }))
  localStorage.clear()
  const request = vi.fn().mockResolvedValue({ ok: true })
  vi.stubGlobal('fetch', request)
  const { sendDiagnostics } = await vi.importActual('../utils/telemetry')
  expect(sendDiagnostics('manual', { check: 'explicit consent' }, { userInitiated: true })).toBe(true)
  expect(request).toHaveBeenCalledOnce()
  const [url, options] = request.mock.calls[0]
  expect(url).toBe('https://staterbill-api-1076771386585.asia-south1.run.app/api/telemetry/log')
  expect(options.credentials).toBe('omit')
  expect(localStorage.getItem('web_device_id')).toBeNull()
})
