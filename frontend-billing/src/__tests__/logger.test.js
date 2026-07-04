// Logger: tags every line with [BizId=…], no 💎, and forwards warn/error to
// the telemetry sink (so front-end warnings/errors are captured server-side).
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'

vi.mock('../utils/telemetry', () => ({ logEvent: vi.fn() }))

import { logger, setBizId, getBizId } from '../utils/logger'
import { logEvent } from '../utils/telemetry'

beforeEach(() => {
  vi.spyOn(console, 'log').mockImplementation(() => {})
  vi.spyOn(console, 'warn').mockImplementation(() => {})
  vi.spyOn(console, 'error').mockImplementation(() => {})
  logEvent.mockClear()
  setBizId(null)
})
afterEach(() => vi.restoreAllMocks())

describe('logger [BizId] + telemetry forwarding', () => {
  it('stamps [BizId=…] and drops the diamond', () => {
    setBizId('BA-9')
    expect(getBizId()).toBe('BA-9')
    logger.info('hello')
    const firstArg = console.log.mock.calls[0][0]
    expect(firstArg).toContain('[BizId=BA-9]')
    expect(firstArg).not.toContain('💎')
  })

  it('shows [BizId=-] when no business is set', () => {
    logger.info('x')
    expect(console.log.mock.calls[0][0]).toContain('[BizId=-]')
  })

  it('forwards warn and error to telemetry but not info', () => {
    setBizId('BA-7')
    logger.info('quiet')
    expect(logEvent).not.toHaveBeenCalled()
    logger.warn('careful')
    logger.error('boom')
    expect(logEvent).toHaveBeenCalledTimes(2)
    const [evtName, payload, level] = logEvent.mock.calls[0]
    expect(evtName).toBe('log_warn')
    expect(level).toBe('warn')
    expect(payload.biz_id).toBe('BA-7')
  })
})
