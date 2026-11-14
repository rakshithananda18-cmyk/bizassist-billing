// @vitest-environment jsdom
import { afterEach, expect, it, vi } from 'vitest'
import { runAsync } from '../utils/asyncAction'
import { logger } from '../utils/logger'
vi.mock('../utils/logger', () => ({ logger: { error: vi.fn() } }))
afterEach(() => vi.clearAllMocks())

it('starts synchronously so form/keyboard cancellation remains timely', () => {
  const event = { preventDefault: vi.fn() }
  runAsync(() => { event.preventDefault(); return Promise.resolve() })
  expect(event.preventDefault).toHaveBeenCalledOnce()
})

it.each(['sync', 'async'])('reports a %s failure without an unhandled rejection', async kind => {
  const toast = vi.fn()
  window.addEventListener('show_toast', toast)
  const error = new Error('Network failed')
  runAsync(() => { if (kind === 'sync') throw error; return Promise.reject(error) }, { message: 'Reload failed.' })
  await Promise.resolve()
  expect(logger.error).toHaveBeenCalledWith('[UI action failed]', error)
  expect(toast.mock.calls[0][0].detail).toMatchObject({ type: 'error', msg: 'Reload failed.' })
  window.removeEventListener('show_toast', toast)
})

it('keeps diagnostic-only failures quiet and does not reject if reporting fails', async () => {
  logger.error.mockImplementationOnce(() => { throw new Error('Console unavailable') })
  runAsync(() => Promise.reject(new Error('Beacon unavailable')), { notify: false })
  await Promise.resolve()
  expect(logger.error).toHaveBeenCalledOnce()
})

it('logs diagnostic-only errors without showing a user notification', async () => {
  const toast = vi.fn()
  window.addEventListener('show_toast', toast)
  runAsync(() => Promise.reject(new Error('Optional beacon unavailable')), { notify: false })
  await Promise.resolve()
  expect(logger.error).toHaveBeenCalledOnce()
  expect(toast).not.toHaveBeenCalled()
  window.removeEventListener('show_toast', toast)
})

it.each([new DOMException('Cancelled', 'AbortError'), new Error('Session changed'), new Error('Session expired')])(
  'does not report expected cancellation or stale-session errors: %s', async error => {
    const toast = vi.fn()
    window.addEventListener('show_toast', toast)
    runAsync(() => Promise.reject(error))
    await Promise.resolve()
    expect(logger.error).not.toHaveBeenCalled()
    expect(toast).not.toHaveBeenCalled()
    window.removeEventListener('show_toast', toast)
  })
