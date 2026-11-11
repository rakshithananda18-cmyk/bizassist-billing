import React from 'react'
import { act, cleanup, fireEvent, render, renderHook, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { useReadinessProbe } from '../hooks/useReadinessProbe'
import PreflightModal from '../components/hosting/PreflightModal'
import HostingModeSection from '../components/settings/HostingModeSection'

vi.mock('../config', () => ({
  IS_LOCAL_APP: true,
  LOCAL_URL: 'http://local-backend',
  CLOUD_URL: 'https://cloud-backend',
  PRIMARY_CLOUD_RUN_URL: 'https://cloud-backend',
  SECONDARY_HF_URL: '',
  API_BASE: 'http://local-backend',
  updateApiBase: vi.fn(),
}))

const online = { status: 'online', ms: 10, error: null }
const offline = { status: 'offline', ms: null, error: 'Unreachable' }
const checking = { status: 'checking', ms: null, error: null }
const healthy = () => ({ ok: true, json: async () => ({ status: 'ok', db: 'connected' }) })
const deferred = () => {
  let resolve
  const promise = new Promise(done => { resolve = done })
  return { promise, resolve }
}

beforeEach(() => {
  vi.useFakeTimers()
  vi.stubGlobal('fetch', vi.fn(async () => healthy()))
})

afterEach(() => {
  cleanup()
  vi.clearAllTimers()
  vi.useRealTimers()
  vi.unstubAllGlobals()
})

describe('hosting readiness', () => {
  it('settles healthy probes with the standby backend disabled', async () => {
    const { result } = renderHook(useReadinessProbe)
    await act(async () => {})
    expect(result.current.localProbe.status).toBe('online')
    expect(result.current.cloudProbe.status).toBe('online')
    expect(result.current.internetProbe.status).toBe('online')
    expect(result.current.hfProbe).toBeNull()
  })

  it('publishes local readiness while the cloud check is still pending', async () => {
    const cloud = deferred()
    fetch.mockImplementation(url => String(url).startsWith('https://cloud-backend') ? cloud.promise : Promise.resolve(healthy()))
    const { result } = renderHook(useReadinessProbe)
    await act(async () => {})
    expect(result.current.localProbe.status).toBe('online')
    expect(result.current.internetProbe.status).toBe('online')
    expect(result.current.cloudProbe.status).toBe('checking')
    await act(async () => cloud.resolve(healthy()))
    expect(result.current.cloudProbe.status).toBe('online')
  })

  it.each([
    ['disconnected database', async () => ({ status: 'ok', db: 'error' })],
    ['invalid health body', async () => ({})],
    ['malformed JSON', async () => { throw new SyntaxError('Invalid JSON') }],
  ])('rejects HTTP 200 with %s for backend readiness', async (_label, json) => {
    fetch.mockImplementation(async () => ({ ok: true, json }))
    const { result } = renderHook(useReadinessProbe)
    await act(async () => {})
    expect(result.current.localProbe.status).toBe('offline')
    expect(result.current.cloudProbe.status).toBe('offline')
  })

  it('does not replace a newer recheck with a late result from the previous run', async () => {
    const staleCloud = deferred()
    let cloudCalls = 0
    fetch.mockImplementation(url => {
      if (String(url).startsWith('https://cloud-backend') && ++cloudCalls === 1) return staleCloud.promise
      return Promise.resolve(healthy())
    })
    const { result } = renderHook(useReadinessProbe)
    await act(async () => {})
    await act(async () => result.current.recheck())
    expect(result.current.cloudProbe.status).toBe('online')
    await act(async () => staleCloud.resolve({ ok: false, status: 503 }))
    expect(result.current.cloudProbe.status).toBe('online')
  })

  it('keeps the timeout active while reading the health response body', async () => {
    fetch.mockImplementation(async (url, { signal }) => {
      if (!String(url).includes('/health')) return healthy()
      return {
        ok: true,
        json: () => new Promise((_resolve, reject) => {
          signal.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')))
        }),
      }
    })
    const { result } = renderHook(useReadinessProbe)
    await act(async () => {})
    await act(async () => vi.advanceTimersByTime(6000))
    expect(result.current.localProbe.status).toBe('offline')
    expect(result.current.cloudProbe.status).toBe('offline')
  })
})

describe('preflight progress controls', () => {
  const props = () => ({
    targetMode: 'hybrid', localProbe: online, cloudProbe: online, internetProbe: online,
    onClose: vi.fn(), onProceed: vi.fn(), onRetry: vi.fn(),
  })

  it('continues once with the latest callback despite repeated parent renders', () => {
    const original = props()
    const latestProceed = vi.fn()
    const { rerender } = render(<PreflightModal {...original} />)
    act(() => vi.advanceTimersByTime(300))
    rerender(<PreflightModal {...original} onProceed={latestProceed} />)
    act(() => vi.advanceTimersByTime(300))
    expect(latestProceed).toHaveBeenCalledTimes(1)
    expect(original.onProceed).not.toHaveBeenCalled()
    fireEvent.click(screen.getByRole('button', { name: /Continue/ }))
    act(() => vi.advanceTimersByTime(1000))
    expect(latestProceed).toHaveBeenCalledTimes(1)
  })

  it.each([offline, checking])('requires only the local backend for Local mode (%s cloud)', cloudProbe => {
    const original = props()
    render(<PreflightModal {...original} targetMode="local" cloudProbe={cloudProbe} internetProbe={offline} />)
    expect(screen.queryByText('Cloud Backend (P2)')).not.toBeInTheDocument()
    act(() => vi.advanceTimersByTime(600))
    expect(original.onProceed).toHaveBeenCalledTimes(1)
  })

  it('allows cancel while required connectivity checks are pending', () => {
    const original = props()
    render(<PreflightModal {...original} localProbe={checking} />)
    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }))
    expect(original.onClose).toHaveBeenCalledTimes(1)
    expect(original.onProceed).not.toHaveBeenCalled()
  })

  it('retries connectivity instead of closing the modal', () => {
    const original = props()
    render(<PreflightModal {...original} cloudProbe={offline} />)
    fireEvent.click(screen.getByRole('button', { name: 'Retry All' }))
    expect(original.onRetry).toHaveBeenCalledTimes(1)
    expect(original.onClose).not.toHaveBeenCalled()
    expect(original.onProceed).not.toHaveBeenCalled()
  })

  it('does not pass absent or unknown required probe states', () => {
    const original = props()
    const { rerender } = render(<PreflightModal {...original} localProbe={null} />)
    expect(screen.queryByRole('button', { name: /Continue/ })).not.toBeInTheDocument()
    rerender(<PreflightModal {...original} localProbe={{ status: 'error' }} />)
    act(() => vi.advanceTimersByTime(1000))
    expect(original.onProceed).not.toHaveBeenCalled()
  })
})

describe('Local-only selection', () => {
  it.each([
    ['card', 'hybrid'], ['deep link', 'hybrid'], ['card', 'local'], ['deep link', 'local'],
  ])('saves Local using the %s from %s without cloud preflight or data migration', async (entry, currentMode) => {
    fetch.mockRejectedValue(new TypeError('Failed to fetch'))
    const onModeChange = vi.fn()
    const onAutoSwitchConsumed = vi.fn()
    render(<HostingModeSection currentMode={currentMode} onModeChange={onModeChange}
      token="local-session" autoSwitchTarget={entry === 'deep link' ? 'local' : null}
      onAutoSwitchConsumed={onAutoSwitchConsumed} />)
    if (entry === 'card') fireEvent.click(screen.getByText('Local Only'))
    await act(async () => {})
    expect(onModeChange).toHaveBeenCalledTimes(1)
    expect(onModeChange).toHaveBeenCalledWith('local')
    expect(screen.getByText(/Cloud sync pauses in both directions/)).toBeInTheDocument()
    expect(screen.queryByText(/Running preflight checks/)).not.toBeInTheDocument()
    expect(screen.queryByText(/Move to Local-Only Mode/)).not.toBeInTheDocument()
    expect(fetch.mock.calls.every(([url, options]) => !String(url).includes('data-transfer') && options?.method !== 'PUT')).toBe(true)
    if (entry === 'deep link') expect(onAutoSwitchConsumed).toHaveBeenCalledTimes(1)
  })
})
