import React from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act, cleanup, render } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'

const auth = vi.hoisted(() => ({ value: null }))
vi.mock('../contexts/AuthContext', () => ({ useAuth: () => auth.value }))
vi.mock('../contexts/LockContext', () => ({
  useLock: () => ({ hasLock: false, lock: () => {}, resetInactivityTimer: () => {} }),
}))
vi.mock('../config', async importOriginal => ({ ...(await importOriginal()), IS_LOCAL_APP: true }))
vi.mock('../components/PageHelp', () => ({ default: () => null }))
vi.mock('../components/UniversalSearch', () => ({ default: () => null }))
vi.mock('../components/NotificationBell', () => ({ default: () => null }))
vi.mock('../components/hosting/SyncNudgeModal', () => ({ default: () => null }))
vi.mock('../components/hosting/WebLocalOnlyNotice', () => ({ default: () => null }))

import AppLayout from '../layouts/AppLayout'

beforeEach(() => {
  vi.useFakeTimers()
  localStorage.setItem('bizassist_hosting_mode', 'hybrid')
  auth.value = {
    user: { id: 1, username: 'owner', role: 'owner' },
    profile: { business_name: 'Sample Store' },
    token: 'session-token',
    settings: { general: { hosting_mode: 'hybrid' }, subscription: { plan: 'pro' } },
    businessConfig: {}, appReady: true, setAppReady: vi.fn(),
    authFetch: vi.fn(), logout: vi.fn(), fetchSettings: vi.fn(),
  }
  vi.stubGlobal('fetch', vi.fn(async () => ({ ok: true, json: async () => ({ pending_count: 0 }) })))
})
afterEach(() => {
  cleanup()
  vi.useRealTimers()
  vi.unstubAllGlobals()
})

const showLayout = () => render(<MemoryRouter><AppLayout title="Home">Demo workspace</AppLayout></MemoryRouter>)

describe('demo layout network isolation', () => {
  it.each(['user', 'context'])('skips background sync polling when demo is identified by %s', async source => {
    if (source === 'user') auth.value.user.is_demo = true
    else auth.value.isDemoMode = true
    showLayout()
    await act(async () => { await vi.advanceTimersByTimeAsync(31000) })
    window.dispatchEvent(new CustomEvent('sync-flushed'))
    window.dispatchEvent(new CustomEvent('sync-event', { detail: { type: 'sync.trigger' } }))
    await act(async () => { await vi.advanceTimersByTimeAsync(1000) })

    expect(fetch).not.toHaveBeenCalled()
  })

  it('keeps hybrid status and queue polling active for normal sessions', async () => {
    showLayout()
    await act(async () => { await vi.advanceTimersByTimeAsync(31000) })

    const urls = fetch.mock.calls.map(([url]) => url)
    expect(urls.filter(url => url.endsWith('/api/sync/status'))).toHaveLength(2)
    expect(urls.filter(url => url.endsWith('/api/sync/queue-depth'))).toHaveLength(2)
  })
})
