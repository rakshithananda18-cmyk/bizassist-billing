import { act, cleanup, renderHook } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const runtime = vi.hoisted(() => ({ local: true, online: true, channels: [], connections: [], pull: vi.fn(), connect: vi.fn() }))
vi.mock('../config', () => ({ API_BASE: 'https://billing-api.example.invalid', get IS_LOCAL_APP() { return runtime.local } }))
vi.mock('../utils/logger', () => ({ logger: { info: vi.fn(), warn: vi.fn(), debug: vi.fn() } }))
vi.mock('../sync/syncManager', () => ({ syncManager: { pull: (...args) => runtime.pull(...args) } }))
vi.mock('../sync/sseConnection', () => ({ createSseConnection: (...args) => runtime.connect(...args) }))

import { useRealtimeLeader } from '../hooks/useRealtimeLeader'

const owner = { id: 7, user_id: 7, public_id: 'BA-REALTIME' }
const settings = { general: { hosting_mode: 'hybrid', realtime_sync_global: false } }
const leaderKey = 'realtime_leader_tab:BA-REALTIME:7'
const heartbeatKey = 'realtime_leader_ts:BA-REALTIME:7'
const emit = (type) => act(() => { window.dispatchEvent(new Event(type)) })
const message = (data) => act(() => { runtime.channels.at(-1).onmessage({ data }) })
const mount = (token = 'owner-session', value = settings, user = owner) => renderHook(
  props => useRealtimeLeader(props.token, props.settings, props.user),
  { initialProps: { token, settings: value, user } },
)

beforeEach(() => {
  vi.useFakeTimers()
  vi.setSystemTime(new Date('2026-11-13T12:00:00Z'))
  runtime.local = true
  runtime.online = true
  runtime.channels = []
  runtime.connections = []
  runtime.pull.mockReset().mockResolvedValue(undefined)
  runtime.connect.mockReset().mockImplementation(options => {
    const connection = { options, close: vi.fn(), readyState: 1 }
    runtime.connections.push(connection)
    return connection
  })
  localStorage.clear()
  delete window.__syncStatus
  vi.spyOn(navigator, 'onLine', 'get').mockImplementation(() => runtime.online)
  vi.stubGlobal('EventSource', class { static OPEN = 1 })
  vi.stubGlobal('BroadcastChannel', class {
    constructor(name) {
      this.name = name
      this.postMessage = vi.fn()
      this.close = vi.fn()
      runtime.channels.push(this)
    }
  })
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, json: async () => ({ ticket: 'one-time +/ticket' }) }))
})

afterEach(() => {
  cleanup()
  vi.clearAllTimers()
  vi.useRealTimers()
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
  delete window.__syncStatus
})

describe('business-scoped realtime leadership', () => {
  it.each([
    [null, owner], ['owner-session', null], ['owner-session', { ...owner, is_demo: true }],
    ['demo-guest-jwt-token-staterbill', owner],
  ])('keeps demo and unauthenticated sessions off the network', (token, user) => {
    mount(token, settings, user)
    expect(runtime.channels).toHaveLength(0)
    expect(runtime.connections).toHaveLength(0)
    expect(window.__syncStatus).toMatchObject({ status: 'connected', error: null, isOnline: true })
  })

  it.each(['local', 'cloud-disabled'])('respects an explicit %s realtime decision', mode => {
    runtime.local = mode === 'local'
    mount('owner-session', { general: { hosting_mode: 'local', realtime_sync_global: false } })
    expect(runtime.connections).toHaveLength(0)
    expect(window.__syncStatus.status).toBe('disconnected')
  })

  it('keeps a hybrid stream stable across settings refreshes and cleans up on account changes', () => {
    const hook = mount()
    expect(runtime.connections).toHaveLength(1)
    expect(runtime.channels[0].name).toBe('bizassist_sse_leader:BA-REALTIME:7')
    expect(localStorage.getItem(leaderKey)).toBeTruthy()
    hook.rerender({ token: 'owner-session', settings: { general: { ...settings.general, app_zoom: 110 } }, user: { ...owner } })
    expect(runtime.connections).toHaveLength(1)
    hook.rerender({ token: 'new-session', settings, user: { id: 8, public_id: 'BA-OTHER' } })
    expect(runtime.connections[0].close).toHaveBeenCalledOnce()
    expect(runtime.channels[0].close).toHaveBeenCalledOnce()
    expect(localStorage.getItem(leaderKey)).toBeNull()
    expect(runtime.channels[1].name).toBe('bizassist_sse_leader:BA-OTHER:8')
    expect(runtime.connections).toHaveLength(2)
  })

  it('exchanges the authenticated session for an encoded one-time SSE ticket', async () => {
    mount()
    const url = await runtime.connections[0].options.fetchTicket()
    expect(url).toBe('https://billing-api.example.invalid/realtime/events?ticket=one-time%20%2B%2Fticket')
    expect(fetch).toHaveBeenCalledWith('https://billing-api.example.invalid/realtime/ticket', expect.objectContaining({
      method: 'POST', headers: { Authorization: 'Bearer owner-session' }, signal: expect.any(AbortSignal),
    }))
    fetch.mockResolvedValueOnce({ ok: false, status: 401 })
    await expect(runtime.connections[0].options.fetchTicket()).rejects.toThrow('Ticket 401')
  })

  it('pulls only for leader business changes and keeps progress events from changing last-sync metadata', async () => {
    const dispatch = vi.spyOn(window, 'dispatchEvent')
    mount()
    const options = runtime.connections[0].options
    await act(async () => { options.onEvent({ type: 'changed', entity: 'invoice' }) })
    expect(runtime.pull).toHaveBeenCalledOnce()
    expect(window.__syncStatus).toMatchObject({ status: 'connected', lastEntity: 'invoice' })
    const saved = localStorage.getItem('sync_last_time_7')
    act(() => { vi.advanceTimersByTime(1000) })
    options.onEvent({ type: 'sync.progress', entity: 'product', current: 3 })
    options.onEvent({ type: 'sync.reconnect' })
    expect(localStorage.getItem('sync_last_time_7')).toBe(saved)
    expect(localStorage.getItem('sync_last_entity_7')).toBe('invoice')
    expect(runtime.pull).toHaveBeenCalledOnce()
    options.onGap()
    expect(runtime.pull).toHaveBeenCalledTimes(2)
    expect(runtime.channels[0].postMessage).toHaveBeenCalledWith({ type: 'sync_event', data: { type: 'sync.reconnect' } })
    runtime.pull.mockRejectedValueOnce(new Error('offline cloud'))
    await act(async () => { options.onEvent({ type: 'sync.pull_ping' }) })
    expect(runtime.pull).toHaveBeenCalledTimes(3)
    expect(dispatch.mock.calls.some(([event]) => event.type === 'show_toast' && event.detail.msg.includes('invoice'))).toBe(true)
  })

  it('shows interrupted/restored status and ignores late status callbacks after cleanup', () => {
    const dispatch = vi.spyOn(window, 'dispatchEvent')
    const hook = mount()
    const options = runtime.connections[0].options
    options.onStatus('degraded')
    expect(window.__syncStatus).toMatchObject({ status: 'error', error: 'Live sync interrupted. Retrying…' })
    options.onStatus('restored')
    expect(window.__syncStatus).toMatchObject({ status: 'connected', error: null })
    expect(dispatch.mock.calls.some(([event]) => event.type === 'show_toast' && event.detail.type === 'success')).toBe(true)
    hook.unmount()
    const lastStatus = window.__syncStatus
    options.onStatus('degraded')
    expect(window.__syncStatus).toBe(lastStatus)
    expect(runtime.channels[0].close).toHaveBeenCalledOnce()
  })

  it('followers update their view without duplicate pulls, then take over an expired heartbeat', () => {
    const dispatch = vi.spyOn(window, 'dispatchEvent')
    localStorage.setItem(leaderKey, 'existing-leader')
    localStorage.setItem(heartbeatKey, String(Date.now()))
    mount()
    expect(runtime.connections).toHaveLength(0)
    emit('sync-status-request')
    const statusEvents = dispatch.mock.calls.filter(([event]) => event.type === 'sync-status-change')
    expect(statusEvents.at(-1)[0].detail.status).toBe('connecting')
    message({ type: 'sync_event', data: { type: 'changed', entity: 'payment' } })
    expect(window.__syncStatus.lastEntity).toBe('payment')
    expect(runtime.pull).not.toHaveBeenCalled()
    message({ type: 'status_change', status: 'offline', error: 'leader offline', isOnline: false })
    expect(window.__syncStatus).toMatchObject({ status: 'offline', isOnline: false })
    message({ type: 'status_change', status: 'connected', restored: true })
    message({ type: 'status_change', status: 'error' })
    message({ type: 'settings_updated_auto_disable', reason: 'network policy' })
    emit('sync-reconnect-request')
    expect(runtime.channels[0].postMessage).toHaveBeenCalledWith({ type: 'reconnect_request' })
    act(() => { vi.advanceTimersByTime(12000) })
    expect(runtime.connections).toHaveLength(1)
    expect(localStorage.getItem(leaderKey)).not.toBe('existing-leader')
  })

  it('yields to another tab and respects a newer owner while handling leader departure', () => {
    mount()
    const first = runtime.connections[0]
    localStorage.setItem(leaderKey, 'new-leader')
    localStorage.setItem(heartbeatKey, String(Date.now()))
    message({ type: 'leader_left', tabId: 'older-leader' })
    expect(first.close).toHaveBeenCalledOnce()
    expect(runtime.connections).toHaveLength(1)
    localStorage.removeItem(leaderKey)
    message({ type: 'leader_left', tabId: 'new-leader' })
    expect(runtime.connections).toHaveLength(2)
    message({ type: 'leader_claimed', tabId: 'third-leader' })
    expect(runtime.connections[1].close).toHaveBeenCalledOnce()
    message(null)
  })

  it('broadcasts offline state and reconnects only the elected tab when the network returns', () => {
    mount()
    runtime.online = false
    emit('offline')
    expect(window.__syncStatus).toMatchObject({ status: 'offline', isOnline: false })
    expect(runtime.channels[0].postMessage).toHaveBeenCalledWith(expect.objectContaining({ status: 'offline', isOnline: false }))
    emit('sync-status-request')
    runtime.online = true
    emit('online')
    expect(runtime.connections).toHaveLength(2)
    emit('sync-reconnect-request')
    expect(runtime.connections).toHaveLength(3)
    message({ type: 'reconnect_request' })
    expect(runtime.connections).toHaveLength(4)
    emit('beforeunload')
    expect(localStorage.getItem(leaderKey)).toBeNull()
    expect(localStorage.getItem(heartbeatKey)).toBeNull()
  })
})
