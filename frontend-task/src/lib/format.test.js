import { describe, expect, it } from 'vitest'
import { fmtDay, telHref } from './format'
import { mapsDirectionsUrl } from './geo'

describe('format', () => {
  it('formats a business date without timezone drift', () => {
    expect(fmtDay('2026-10-22')).toMatch(/22/)
  })
  it('builds a dialable tel: link', () => {
    expect(telHref('+91 98000-00001')).toBe('tel:+919800000001')
    expect(telHref(null)).toBeUndefined()
  })
  it('builds a keyless Google Maps directions URL', () => {
    expect(mapsDirectionsUrl({ lat: 12.97, lng: 77.59 }))
      .toBe('https://www.google.com/maps/dir/?api=1&destination=12.97%2C77.59&travelmode=driving')
    expect(mapsDirectionsUrl({ name: 'Apollo', address: 'Jayanagar' })).toContain('Apollo%2C%20Jayanagar')
  })
})
