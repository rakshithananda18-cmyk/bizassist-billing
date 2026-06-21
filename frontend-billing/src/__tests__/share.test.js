// Tests for the UPI / WhatsApp / QR builders. These produce money- and
// comms-critical strings (a wrong VPA or amount = a failed/wrong payment), so
// they're locked here.
import { describe, it, expect } from 'vitest'
import { buildUpiUri, normalizePhoneIN, buildWhatsAppShareUrl, qrImageUrl } from '../utils/share'

describe('buildUpiUri', () => {
  it('builds a valid UPI deep-link with 2-dp amount and encoded name', () => {
    expect(buildUpiUri({ vpa: 'shop@upi', payeeName: 'Raj Store', amount: 451.5, note: 'POS-Invoicing' }))
      .toBe('upi://pay?pa=shop@upi&pn=Raj%20Store&am=451.50&cu=INR&tn=POS-Invoicing')
  })
  it('leaves the VPA un-encoded (UPI apps expect the raw @)', () => {
    expect(buildUpiUri({ vpa: 'shop@upi', amount: 100 })).toContain('pa=shop@upi')
  })
  it('omits the note when not given and defaults amount to 0.00', () => {
    expect(buildUpiUri({ vpa: 'x@upi' })).toBe('upi://pay?pa=x@upi&pn=BizAssist%20Merchant&am=0.00&cu=INR')
  })
})

describe('normalizePhoneIN', () => {
  it('prefixes 91 to a bare 10-digit number', () => {
    expect(normalizePhoneIN('98765 43210')).toBe('919876543210')
  })
  it('strips non-digits and keeps an already-coded number', () => {
    expect(normalizePhoneIN('+91-98765-43210')).toBe('919876543210')
  })
})

describe('buildWhatsAppShareUrl', () => {
  it('normalises the phone and URL-encodes the message', () => {
    expect(buildWhatsAppShareUrl('9876543210', 'Hi ₹100 due'))
      .toBe('https://api.whatsapp.com/send?phone=919876543210&text=Hi%20%E2%82%B9100%20due')
  })
})

describe('qrImageUrl', () => {
  it('encodes the data into a qrserver image URL', () => {
    expect(qrImageUrl('upi://pay?pa=shop@upi', 120))
      .toBe('https://api.qrserver.com/v1/create-qr-code/?size=120x120&margin=4&data=upi%3A%2F%2Fpay%3Fpa%3Dshop%40upi')
  })
})
