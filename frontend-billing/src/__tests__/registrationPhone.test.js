import { describe, it, expect } from 'vitest'
import { normalizeRegistrationPhone } from '../utils/registrationPhone'

describe('required signup phone', () => {
  it.each(['', '12345', 'call me', '+91 12', '+00000000'])('rejects missing or invalid phone %s', value => {
    expect(() => normalizeRegistrationPhone(value)).toThrow(/phone/i)
  })
  it('normalizes Indian local and formatted country-code numbers identically', () => {
    expect(normalizeRegistrationPhone('98765 43210')).toBe('+919876543210')
    expect(normalizeRegistrationPhone('+91 (98765) 43210')).toBe('+919876543210')
  })
  it('uses the selected country instead of dropping country identity', () => {
    expect(normalizeRegistrationPhone('9123 4567', 'Singapore')).toBe('+6591234567')
    expect(normalizeRegistrationPhone('07700 900123', 'United Kingdom')).toBe('+447700900123')
  })
})
