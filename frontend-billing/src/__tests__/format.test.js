// Smoke tests for the shared money/words/date formatters.
// These cover the invoice-critical helpers that were extracted out of the
// 3,000-line Sales.jsx into utils/format.js — so a regression in the amount,
// the amount-in-words on a printed invoice, or the default date is caught here.
import { describe, it, expect } from 'vitest'
import { fmt, numberToWords, getTodayDateStr } from '../utils/format'

describe('fmt (rupee money)', () => {
  it('formats with Indian grouping + rupee sign', () => {
    expect(fmt(1234.5)).toBe('₹1,234.5')
  })
  it('renders an em-dash for null/undefined', () => {
    expect(fmt(null)).toBe('—')
    expect(fmt(undefined)).toBe('—')
  })
  it('shows zero (not a dash)', () => {
    expect(fmt(0)).toBe('₹0')
  })
})

describe('numberToWords (invoice amount in words)', () => {
  it('handles rupees + paise', () => {
    expect(numberToWords(1234.5)).toBe(
      'One Thousand Two Hundred and Thirty Four Rupees and Fifty Paise Only',
    )
  })
  it('handles zero', () => {
    expect(numberToWords(0)).toBe('Zero Rupees Only')
  })
  it('handles a round hundred', () => {
    expect(numberToWords(100)).toBe('One Hundred Rupees Only')
  })
  it('uses Indian lakh/crore grouping', () => {
    expect(numberToWords(2500000)).toBe('Twenty Five Lakh Rupees Only')
  })
})

describe('getTodayDateStr', () => {
  it('returns an ISO YYYY-MM-DD date', () => {
    expect(getTodayDateStr()).toMatch(/^\d{4}-\d{2}-\d{2}$/)
  })
})
