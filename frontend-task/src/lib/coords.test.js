import { describe, expect, it } from 'vitest'
import { parseCoords } from './coords'

describe('parseCoords', () => {
  it('reads plain coordinates', () => {
    expect(parseCoords('12.9716, 77.5946')).toEqual({ lat: 12.9716, lng: 77.5946 })
  })
  it('reads Google Maps links', () => {
    expect(parseCoords('https://www.google.com/maps/place/X/@12.9716,77.5946,17z/data=!3d12.9717!4d77.5947'))
      .toEqual({ lat: 12.9717, lng: 77.5947 })
    expect(parseCoords('https://www.google.com/maps/@12.9716,77.5946,15z')).toEqual({ lat: 12.9716, lng: 77.5946 })
    expect(parseCoords('https://maps.google.com/?q=12.9716,77.5946')).toEqual({ lat: 12.9716, lng: 77.5946 })
  })
  it('rejects junk', () => {
    expect(parseCoords('https://maps.app.goo.gl/abc')).toBeNull()
    expect(parseCoords('0.0, 0.0')).toBeNull()
    expect(parseCoords('')).toBeNull()
  })
})
