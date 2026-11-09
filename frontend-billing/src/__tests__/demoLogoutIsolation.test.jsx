import React from 'react'
import { act, cleanup, render } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('../utils/networkDiscovery', () => ({
  discoverLocalBackend: async () => null, getNetworkMode: () => 'cloud', clearDiscoveryCache: vi.fn(),
}))
vi.mock('../config/aiDashboard', () => ({ notifyAiLogout: vi.fn(), getAiDashboardUrl: () => 'https://ai.example.test' }))

import { AuthProvider, useAuth } from '../contexts/AuthContext'
import { DEMO_TOKEN, isDemoRequested } from '../demo/demoEngine'
import { notifyAiLogout } from '../config/aiDashboard'

let auth
let channels
function Harness() { auth = useAuth(); return null }
const savedEntries = () => Object.fromEntries(Object.entries(localStorage))

beforeEach(() => {
  window.history.replaceState({}, '', '/?demo=1&embed=1&tour=1')
  localStorage.setItem('billing_token', 'real-owner-token')
  localStorage.setItem('billing_user', JSON.stringify({ id: 7, username: 'owner', public_id: 'BA-OWNER' }))
  localStorage.setItem('bizassist_cloud_token', 'real-cloud-token')
  localStorage.setItem('pos_upi_vpa', 'owner@bank')
  channels = []
  vi.clearAllMocks()
  vi.stubGlobal('fetch', vi.fn(() => { throw new Error('Demo logout must not reach the network') }))
  vi.stubGlobal('BroadcastChannel', class {
    constructor() { this.postMessage = vi.fn(); this.close = vi.fn(); channels.push(this) }
  })
})
afterEach(() => {
  cleanup()
  window.history.replaceState({}, '', '/')
  vi.unstubAllGlobals()
})

describe('demo logout isolation', () => {
  it('exits the demo while preserving the owner credentials and other sessions', async () => {
    const saved = savedEntries()
    render(<AuthProvider><Harness /></AuthProvider>)
    expect(auth.token).toBe(DEMO_TOKEN)

    await act(async () => { await auth.logout() })

    expect(auth.user).toBeNull()
    expect(auth.token).toBeNull()
    expect(auth.isDemoMode).toBe(false)
    expect(auth.businessConfig).toBeNull()
    expect(isDemoRequested()).toBe(false)
    expect(savedEntries()).toEqual(saved)
    expect(fetch).not.toHaveBeenCalled()
    expect(notifyAiLogout).not.toHaveBeenCalled()
    expect(channels.every(channel => channel.postMessage.mock.calls.length === 0)).toBe(true)
    expect(document.querySelector('iframe')).toBeNull()
  })

  it('ignores owner storage, token-refresh, and logout-channel activity during the demo', () => {
    render(<AuthProvider><Harness /></AuthProvider>)
    act(() => {
      window.dispatchEvent(new StorageEvent('storage', { key: 'billing_token', newValue: null }))
      window.dispatchEvent(new StorageEvent('storage', { key: 'billing_token', newValue: 'another-owner-token' }))
      window.dispatchEvent(new CustomEvent('auth_token_refreshed', { detail: { token: 'refreshed-owner-token' } }))
      for (const channel of channels) channel.onmessage?.({ data: { type: 'LOGOUT' } })
    })

    expect(auth.user.is_demo).toBe(true)
    expect(auth.token).toBe(DEMO_TOKEN)
    expect(auth.isDemoMode).toBe(true)
    expect(channels).toHaveLength(0)
    expect(localStorage.getItem('billing_token')).toBe('real-owner-token')
    expect(fetch).not.toHaveBeenCalled()
  })
})
