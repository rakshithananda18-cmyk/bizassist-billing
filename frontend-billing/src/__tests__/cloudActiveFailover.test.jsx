// @vitest-environment jsdom
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import React, { useRef } from 'react'
import { render, act } from '@testing-library/react'
import { AuthProvider, useAuth } from '../contexts/AuthContext'
import {
  PRIMARY_CLOUD_RUN_URL,
  SECONDARY_HF_URL,
  getActiveCloudUrl,
  switchActiveCloudUrl,
  updateApiBase,
} from '../config'

function Consumer({ authRef }) {
  const auth = useAuth()
  authRef.current = auth
  return <div>Harness ready</div>
}

describe('Dual-Cloud Active Failover', () => {
  let authRef

  beforeEach(() => {
    localStorage.clear()
    sessionStorage.clear()
    updateApiBase('cloud')
    switchActiveCloudUrl(PRIMARY_CLOUD_RUN_URL)
    authRef = { current: null }
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('automatically falls over to backup cloud when primary times out on login', async () => {
    const primaryUrl = PRIMARY_CLOUD_RUN_URL
    const backupUrl = SECONDARY_HF_URL

    const fetchMock = vi.fn(async (url) => {
      const u = String(url)
      // Background config/settings queries return empty 200
      if (u.includes('/settings') || u.includes('/profile') || u.includes('/business/config')) {
        return { ok: true, status: 200, json: async () => ({ general: { hosting_mode: 'cloud' } }) }
      }
      // Primary times out
      if (u.startsWith(primaryUrl)) {
        const err = new Error('Gateway Timeout')
        err.name = 'AbortError'
        throw err
      }
      // Backup responds with valid session
      if (u.startsWith(backupUrl) && u.includes('/login')) {
        return {
          ok: true,
          status: 200,
          json: async () => ({
            id: 1,
            user_id: 1,
            public_id: 'BA-MUMBAI',
            username: 'owner',
            business_name: 'Stater Bill Store',
            role: 'owner',
            token: 'valid-backup-jwt-token',
          }),
        }
      }
      return { ok: false, status: 404, json: async () => ({}) }
    })

    vi.stubGlobal('fetch', fetchMock)

    render(
      <AuthProvider>
        <Consumer authRef={authRef} />
      </AuthProvider>
    )

    expect(getActiveCloudUrl()).toBe(primaryUrl)

    await act(async () => {
      await authRef.current.login('owner', 'secret123')
    })

    // Active cloud must have switched to backup
    expect(getActiveCloudUrl()).toBe(backupUrl)
    const savedUser = JSON.parse(localStorage.getItem('billing_user'))
    expect(savedUser).toMatchObject({
      username: 'owner',
      public_id: 'BA-MUMBAI',
    })
    expect(localStorage.getItem('billing_token')).toBe('valid-backup-jwt-token')
  })

  it('transparently retries authFetch on backup cloud when primary returns HTTP 503', async () => {
    const primaryUrl = PRIMARY_CLOUD_RUN_URL
    const backupUrl = SECONDARY_HF_URL

    const fetchMock = vi.fn(async (url) => {
      const u = String(url)
      // Login on primary
      if (u.startsWith(primaryUrl) && u.includes('/login')) {
        return {
          ok: true,
          status: 200,
          json: async () => ({
            id: 1,
            user_id: 1,
            public_id: 'BA-MUMBAI',
            username: 'owner',
            business_name: 'Stater Bill Store',
            role: 'owner',
            token: 'jwt-session-token',
          }),
        }
      }
      // Primary fails on products with 503
      if (u.startsWith(primaryUrl) && u.includes('/products')) {
        return {
          ok: false,
          status: 503,
          statusText: 'Service Unavailable',
          json: async () => ({ detail: 'Service Unavailable' }),
        }
      }
      // Backup succeeds on products
      if (u.startsWith(backupUrl) && u.includes('/products')) {
        return {
          ok: true,
          status: 200,
          json: async () => [{ id: 101, name: 'Filter Coffee' }],
        }
      }
      return { ok: false, status: 404, json: async () => ({}) }
    })

    vi.stubGlobal('fetch', fetchMock)

    render(
      <AuthProvider>
        <Consumer authRef={authRef} />
      </AuthProvider>
    )

    await act(async () => {
      await authRef.current.login('owner', 'secret123')
    })

    expect(getActiveCloudUrl()).toBe(primaryUrl)

    let response
    await act(async () => {
      response = await authRef.current.authFetch('/billing/products')
    })

    expect(response.ok).toBe(true)
    const data = await response.json()
    expect(data).toEqual([{ id: 101, name: 'Filter Coffee' }])
    expect(getActiveCloudUrl()).toBe(backupUrl)
  })
})
