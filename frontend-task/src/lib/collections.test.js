import { describe, expect, it } from 'vitest'
import { billingStatus } from './collections'

describe('billingStatus', () => {
  it('is only for finished collections', () => {
    expect(billingStatus({ billing_confirmed: null, amount_collected: 500 })).toBeNull()
  })
  it('follows what the owner confirmed in billing', () => {
    expect(billingStatus({ billing_confirmed: 0, amount_collected: 500 }).text).toContain('confirm in billing')
    expect(billingStatus({ billing_confirmed: 200, amount_collected: 500 }).text).toBe('₹200 of ₹500 recorded in billing')
    expect(billingStatus({ billing_confirmed: 500, amount_collected: 500 }).tone).toBe('success')
  })
})
