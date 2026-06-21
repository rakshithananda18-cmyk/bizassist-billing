// src/utils/share.js — pure builders for UPI deep-links, WhatsApp shares, QR URLs.
// =============================================================================
// The UPI string and the WhatsApp URL were hand-rolled at several call sites
// (CheckoutModal, TotalBreakupModal, Parties). That's money/comms-critical and
// must not drift, so they live here once, pure and unit-tested. Behaviour is
// kept identical to the originals (notably: the VPA is NOT url-encoded, matching
// what real UPI apps expect).

/**
 * UPI payment deep-link: `upi://pay?pa=&pn=&am=&cu=INR[&tn=]`.
 * @param {{vpa:string, payeeName?:string, amount?:number, note?:string}} args
 * @returns {string}
 */
export function buildUpiUri({ vpa, payeeName = 'BizAssist Merchant', amount = 0, note } = {}) {
  const amt = (parseFloat(amount) || 0).toFixed(2)
  let uri = `upi://pay?pa=${vpa || ''}&pn=${encodeURIComponent(payeeName)}&am=${amt}&cu=INR`
  if (note) uri += `&tn=${encodeURIComponent(note)}`
  return uri
}

/** Normalise an Indian phone to country-coded digits (bare 10-digit → 91XXXXXXXXXX). */
export function normalizePhoneIN(phone) {
  let p = String(phone || '').replace(/\D/g, '')
  if (p.length === 10) p = '91' + p
  return p
}

/** WhatsApp click-to-chat URL with a pre-filled, URL-encoded message. */
export function buildWhatsAppShareUrl(phone, message) {
  return `https://api.whatsapp.com/send?phone=${normalizePhoneIN(phone)}&text=${encodeURIComponent(message || '')}`
}

/** QR-image URL (qrserver) encoding arbitrary data — used to render the UPI QR. */
export function qrImageUrl(data, size = 120) {
  return `https://api.qrserver.com/v1/create-qr-code/?size=${size}x${size}&margin=4&data=${encodeURIComponent(data || '')}`
}
