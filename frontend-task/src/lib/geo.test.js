// @vitest-environment jsdom
import { describe, expect, it } from 'vitest'
import {
  buildUpiUri,
  distanceBetweenM,
  formatDistance,
  whatsappHref,
} from './geo'

describe('geo and smart mobile utilities', () => {
  it('computes haversine distance between two points', () => {
    // Bangalore Majestic to MG Road (~4.5km)
    const lat1 = 12.9778, lng1 = 77.5713
    const lat2 = 12.9756, lng2 = 77.6066
    const dist = distanceBetweenM(lat1, lng1, lat2, lng2)
    expect(dist).toBeGreaterThan(3500)
    expect(dist).toBeLessThan(4500)
  })

  it('handles null and invalid coordinates safely', () => {
    expect(distanceBetweenM(null, 77.5, 12.9, 77.6)).toBeNull()
    expect(distanceBetweenM(12.9, null, 12.9, 77.6)).toBeNull()
    expect(distanceBetweenM(12.9, 77.5, undefined, 77.6)).toBeNull()
    expect(distanceBetweenM(NaN, 77.5, 12.9, 77.6)).toBeNull()
  })

  it('formats distance in meters and kilometers correctly', () => {
    expect(formatDistance(null)).toBeNull()
    expect(formatDistance(45)).toBe('45 m')
    expect(formatDistance(950)).toBe('950 m')
    expect(formatDistance(1200)).toBe('1.2 km')
    expect(formatDistance(5432)).toBe('5.4 km')
  })

  it('builds WhatsApp share URLs correctly with Indian phone numbers', () => {
    expect(whatsappHref(null)).toBeNull()
    expect(whatsappHref('')).toBeNull()
    expect(whatsappHref('9876543210')).toBe('https://wa.me/919876543210')
    expect(whatsappHref('+91 98765 43210', 'Arriving soon')).toBe('https://wa.me/919876543210?text=Arriving%20soon')
  })

  it('builds UPI deep links correctly', () => {
    const uri = buildUpiUri({
      vpa: 'merchant@upi',
      payeeName: 'Distributor Meds',
      amount: 1450.5,
      note: 'INV-101',
    })
    expect(uri).toContain('upi://pay?pa=merchant@upi')
    expect(uri).toContain('am=1450.50')
    expect(uri).toContain('cu=INR')
    expect(uri).toContain('tn=INV-101')
  })

  it('rejects unknown/invalid payees and nonpositive or invalid amounts', () => {
    for (const vpa of [undefined, '', 'unknown', 'payee@upi&pa=other@upi']) expect(buildUpiUri({ vpa, amount: 10 })).toBeNull()
    for (const amount of [0, -1, '12oops', Infinity, NaN]) expect(buildUpiUri({ vpa: 'merchant@upi', amount })).toBeNull()
  })

  it('does not label invalid coordinates or distances as proximity', () => {
    expect(distanceBetweenM('', 77, 12, 77)).toBeNull()
    expect(distanceBetweenM(91, 77, 12, 77)).toBeNull()
    expect(formatDistance(NaN)).toBeNull()
    expect(formatDistance(-10)).toBeNull()
    expect(distanceBetweenM(0, 0, 0, 180)).toBeGreaterThan(20_000_000)
  })
})
