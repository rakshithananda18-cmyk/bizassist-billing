// @vitest-environment jsdom
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import React, { useRef } from 'react'
import { render, act } from '@testing-library/react'
import { AuthProvider, useAuth } from '../contexts/AuthContext'
import {
  PRIMARY_CLOUD_RUN_URL,
  SECONDARY_HF_URL,
  FALLBACK_CLOUD_URL,
  getActiveCloudUrl,
  switchActiveCloudUrl,
  updateApiBase,
} from '../config'

function Consumer({ authRef }) {
  const auth = useAuth()
  authRef.current = auth
  return <div>Harness ready</div>
}

describe('Single Active Cloud & Disaster Recovery', () => {
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

  it('routes directly to Google Cloud Run Mumbai as the single active cloud', async () => {
    const primaryUrl = PRIMARY_CLOUD_RUN_URL

    const fetchMock = vi.fn(async (url) => {
      const u = String(url)
      if (u.includes('/settings') || u.includes('/profile') || u.includes('/business/config')) {
        return { ok: true, status: 200, json: async () => ({ general: { hosting_mode: 'cloud' } }) }
      }
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
            token: 'valid-google-jwt-token',
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
    expect(FALLBACK_CLOUD_URL).toBeNull()

    await act(async () => {
      await authRef.current.login('owner', 'secret123')
    })

    expect(getActiveCloudUrl()).toBe(primaryUrl)
    const savedUser = JSON.parse(localStorage.getItem('billing_user'))
    expect(savedUser).toMatchObject({
      username: 'owner',
      public_id: 'BA-MUMBAI',
    })
    expect(localStorage.getItem('billing_token')).toBe('valid-google-jwt-token')
  })

  it('allows manual switch to disaster recovery target when needed', async () => {
    const drTarget = 'https://rakshit-dev-bizassist.hf.space'
    expect(getActiveCloudUrl()).toBe(PRIMARY_CLOUD_RUN_URL)

    switchActiveCloudUrl(drTarget)
    expect(getActiveCloudUrl()).toBe(drTarget)

    // Switch back to primary
    switchActiveCloudUrl(PRIMARY_CLOUD_RUN_URL)
    expect(getActiveCloudUrl()).toBe(PRIMARY_CLOUD_RUN_URL)
  })
})
