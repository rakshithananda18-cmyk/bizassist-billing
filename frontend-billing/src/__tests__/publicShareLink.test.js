/**
 * Regression: on the desktop app, invoice share links were built from
 * window.location.origin (localhost/LAN) — unreachable for the customer.
 * They must always use the public web origin (PUBLIC_WEB_URL).
 */
import { describe, it, expect } from 'vitest'
import { buildPublicInvoiceLink } from '../invoice/share'
import { PUBLIC_WEB_URL } from '../config'

describe('buildPublicInvoiceLink', () => {
  it('always uses the public web origin, never the current (localhost) origin', () => {
    const link = buildPublicInvoiceLink('tok-123')
    expect(link).toBe(`${PUBLIC_WEB_URL}/public/invoice/tok-123`)
    expect(link).not.toContain('localhost')
    expect(link).not.toContain('127.0.0.1')
  })

  it('PUBLIC_WEB_URL has no trailing slash and is https', () => {
    expect(PUBLIC_WEB_URL.endsWith('/')).toBe(false)
    expect(PUBLIC_WEB_URL.startsWith('https://')).toBe(true)
  })
})
