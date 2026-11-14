// src/sync/uuid.js — stable client-request ids for offline-safe mutations.
// ======================================================================
// Each user-intent mutation (save bill, record payment, confirm purchase) gets
// ONE id, generated at the moment of intent and reused for every retry / offline
// outbox replay. The backend's `X-Client-Request-Id` wall (R7b Slice 1) keys its
// exactly-once replay on this value, so the SAME id on a retry returns the SAME
// response instead of double-posting.
//
// Prefer the platform `crypto.randomUUID` (available in every browser the app
// targets); use Web Crypto bytes where randomUUID needs a secure context.

export function newClientRequestId() {
  try {
    if (typeof globalThis !== 'undefined' && globalThis.crypto && globalThis.crypto.randomUUID) {
      return globalThis.crypto.randomUUID()
    }
  } catch {
    /* fall through to the polyfill */
  }
  if (!globalThis.crypto?.getRandomValues) throw new Error('Secure random generation is unavailable')
  const bytes = globalThis.crypto.getRandomValues(new Uint8Array(16))
  bytes[6] = (bytes[6] & 0x0f) | 0x40
  bytes[8] = (bytes[8] & 0x3f) | 0x80
  const hex = [...bytes].map(value => value.toString(16).padStart(2, '0')).join('')
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`
}

export default newClientRequestId
