import React from 'react'
import { act, cleanup, render } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('../utils/networkDiscovery', () => ({
  discoverLocalBackend: async () => null, getNetworkMode: () => 'cloud', clearDiscoveryCache: vi.fn(),
}))
vi.mock('../sync/syncManager', () => ({ syncManager: { setScope: vi.fn(), clearScope: vi.fn() } }))
vi.mock('../hooks/useSessionRefresh', () => ({ useSessionRefresh: vi.fn() }))

import { AuthProvider, useAuth } from '../contexts/AuthContext'
import { DEMO_TOKEN, isAuthEntryPath, isDemoRequested } from '../demo/demoEngine'
import { sessionFetch } from '../api/session'

let auth
function Harness() { auth = useAuth(); return null }

beforeEach(() => {
  sessionStorage.setItem('stater_demo_active', '1')
  vi.stubGlobal('fetch', vi.fn(async url => {
    const path = String(url)
    const data = path.includes('/profile') ? { plan: 'pro' }
      : path.includes('/settings') ? { general: { hosting_mode: 'cloud' }, subscription: { plan: 'pro' } }
      : path.includes('/business/config') ? { config: {}, attributes_schema: [] }
      : { real_auth_transport: true }
    return new Response(JSON.stringify(data), { status: 200, headers: { 'Content-Type': 'application/json' } })
  }))
})

afterEach(() => {
  cleanup()
  window.history.replaceState({}, '', '/')
  vi.unstubAllGlobals()
})

describe('leaving the marketing demo for authentication', () => {
  it.each(['/login', '/login/', '/register', '/register/'])('opens %s in normal mode and clears only the demo marker', async path => {
    window.history.replaceState({}, '', `${path}?demo=1`)
    sessionStorage.setItem('unrelated-session-preference', 'keep')

    expect(isDemoRequested()).toBe(false)
    // Detection stays pure; AuthProvider owns ending the remembered session.
    expect(sessionStorage.getItem('stater_demo_active')).toBe('1')

    await act(async () => { render(<AuthProvider><Harness /></AuthProvider>) })

    expect(auth.isDemoMode).toBe(false)
    expect(auth.user).toBeNull()
    expect(auth.token).toBeNull()
    expect(auth.loading).toBe(false)
    expect(sessionStorage.getItem('stater_demo_active')).toBeNull()
    expect(sessionStorage.getItem('unrelated-session-preference')).toBe('keep')
    expect(localStorage.getItem('billing_token')).toBeNull()

    const response = await sessionFetch('/auth-entry-probe')
    expect(await response.json()).toEqual({ real_auth_transport: true })
    expect(fetch).toHaveBeenCalledWith('/auth-entry-probe', {})
    window.history.replaceState({}, '', '/')
    expect(isDemoRequested()).toBe(false)
  })

  it('preserves an existing owner session when entering real authentication', async () => {
    const owner = { id: 7, user_id: 7, username: 'owner', public_id: 'BA-OWNER', role: 'owner' }
    const savedOwner = JSON.stringify(owner)
    localStorage.setItem('billing_user', savedOwner)
    localStorage.setItem('billing_token', 'real-owner-token')
    localStorage.setItem('bizassist_cloud_token', 'real-cloud-token')
    window.history.replaceState({}, '', '/register/')

    await act(async () => { render(<AuthProvider><Harness /></AuthProvider>) })

    expect(auth.isDemoMode).toBe(false)
    expect(auth.user).toMatchObject(owner)
    expect(auth.token).toBe('real-owner-token')
    expect(auth.token).not.toBe(DEMO_TOKEN)
    expect(sessionStorage.getItem('stater_demo_active')).toBeNull()
    expect(localStorage.getItem('billing_user')).toBe(savedOwner)
    expect(localStorage.getItem('billing_token')).toBe('real-owner-token')
    expect(localStorage.getItem('bizassist_cloud_token')).toBe('real-cloud-token')

    cleanup()
    window.history.replaceState({}, '', '/')
    await act(async () => { render(<AuthProvider><Harness /></AuthProvider>) })
    expect(auth.isDemoMode).toBe(false)
    expect(auth.user).toMatchObject(owner)
  })

  it('keeps explicit and remembered demos on ordinary app routes', () => {
    for (const path of ['/login-help', '/register/store', '/sales', '/']) {
      expect(isAuthEntryPath(path)).toBe(false)
      window.history.replaceState({}, '', path)
      expect(isDemoRequested()).toBe(true)
    }
    sessionStorage.removeItem('stater_demo_active')
    window.history.replaceState({}, '', '/sales?demo=1')
    expect(isDemoRequested()).toBe(true)
  })
})
