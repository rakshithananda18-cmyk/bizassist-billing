import React from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { beforeEach, describe, expect, it, vi } from 'vitest'

let customers = []
vi.mock('../../lib/auth', () => ({ useAuth: () => ({ me: { public_id: 'BA-ONE', business_name: 'Business' } }) }))
vi.mock('../../components/MapView', () => ({ default: () => null, escapeHtml: value => String(value) }))
vi.mock('../../components/ui', () => ({
  Empty: ({ children }) => <div>{children}</div>, ErrorNote: () => null, Loader: () => null,
  Modal: ({ children }) => <div>{children}</div>, PageHeader: () => null,
  useLoad: () => ({ data: customers }), useToast: () => vi.fn(),
}))

import { ShopForm, shopFormPayload } from './Shops'

const form = {
  name: 'Old snapshot', phone: '9999999999', address: 'Old address', contact_name: 'Manager',
  area: 'North', notes: 'Side entrance', lat: '12.97', lng: '77.59', is_active: true,
}
beforeEach(() => { customers = [] })

describe('Billing-linked shop editing', () => {
  it('never writes stale shared identity while editing linked field data', () => {
    const patch = shopFormPayload(form, '17')
    expect(patch).not.toHaveProperty('name')
    expect(patch).not.toHaveProperty('phone')
    expect(patch).not.toHaveProperty('address')
    expect(patch).toEqual({ contact_name: 'Manager', area: 'North', notes: 'Side entrance', lat: 12.97, lng: 77.59, is_active: true })
  })

  it('keeps identity editable for a standalone delivery point and handles empty or zero coordinates', () => {
    const patch = shopFormPayload({ ...form, lat: '', lng: '0' }, '')
    expect(patch).toMatchObject({ name: 'Old snapshot', phone: '9999999999', address: 'Old address', lat: null, lng: 0 })
  })

  it('shows current Billing values read-only, including a removed phone instead of the old snapshot', () => {
    customers = [{ id: 17, name: 'Updated customer', phone: null, address: 'New billing address' }]
    const html = renderToStaticMarkup(<ShopForm shop={{ ...form, id: 3, customer_id: 17 }} />)
    const name = html.match(/<input[^>]*id="shop-name"[^>]*>/)?.[0]
    const phone = html.match(/<input[^>]*id="shop-phone"[^>]*>/)?.[0]
    expect(name).toContain('disabled=""')
    expect(name).toContain('value="Updated customer"')
    expect(phone).toContain('disabled=""')
    expect(phone).toContain('value=""')
    expect(html).toContain('New billing address')
    expect(html).toContain('Name, phone and address follow the Billing customer')
  })

  it('leaves shared fields enabled for an unlinked delivery point', () => {
    const html = renderToStaticMarkup(<ShopForm shop={{ ...form, id: 3, customer_id: null }} />)
    const name = html.match(/<input[^>]*id="shop-name"[^>]*>/)?.[0]
    expect(name).not.toContain('disabled')
    expect(name).toContain('value="Old snapshot"')
  })
})
