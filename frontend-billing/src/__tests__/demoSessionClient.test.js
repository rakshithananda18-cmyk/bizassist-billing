// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { api, request } from '../api/client'
import { refreshSession, sessionFetch } from '../api/session'
import { DEMO_PRODUCTS, DEMO_SETTINGS, DEMO_TOKEN, resetDemoData } from '../demo/demoEngine'
import { tokenStorage } from '../utils/tokenStorage'

beforeEach(() => {
  resetDemoData()
  sessionStorage.setItem('stater_demo_active', '1')
  tokenStorage.setItem('billing_token', DEMO_TOKEN)
  vi.stubGlobal('fetch', vi.fn(() => { throw new Error('Demo requests must stay local') }))
})
afterEach(() => vi.unstubAllGlobals())

describe('shared demo session transport', () => {
  it('serves populated product and settings JSON through the normal API client', async () => {
    const products = await api.get('/products', { q: 'Basmati' })
    const settings = await api.get('/settings')

    expect(products.items).toEqual([expect.objectContaining({
      id: DEMO_PRODUCTS[0].id, name: DEMO_PRODUCTS[0].name,
      stock_qty: DEMO_PRODUCTS[0].stock_qty,
    })])
    expect(settings).toEqual(DEMO_SETTINGS)
    expect(fetch).not.toHaveBeenCalled()
  })

  it('handles absolute API URLs and preserves demo validation errors', async () => {
    const products = await request('GET', 'https://api.example.test/api/billing/products', { query: { q: 'Basmati' } })
    expect(products.items[0].name).toBe(DEMO_PRODUCTS[0].name)
    await expect(api.post('/products', { name: '' })).rejects.toMatchObject({
      status: 422, detail: 'Enter a product name.',
    })
    expect(fetch).not.toHaveBeenCalled()
  })

  it('returns the demo token without attempting a real refresh', async () => {
    tokenStorage.setItem('billing_token', 'older-real-session')
    expect(await refreshSession()).toBe(DEMO_TOKEN)
    expect(tokenStorage.getItem('billing_token')).toBe('older-real-session')
    expect(fetch).not.toHaveBeenCalled()
  })

  it('also isolates requests when only the demo token remains', async () => {
    sessionStorage.removeItem('stater_demo_active')
    const response = await sessionFetch('https://api.example.test/api/billing/settings')
    expect(JSON.parse(await response.text())).toEqual(DEMO_SETTINGS)
    expect(await refreshSession()).toBe(DEMO_TOKEN)
    expect(fetch).not.toHaveBeenCalled()
  })
})
