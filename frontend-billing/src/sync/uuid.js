// src/sync/uuid.js — stable client-request ids for offline-safe mutations.
// ======================================================================
// Each user-intent mutation (save bill, record payment, confirm purchase) gets
// ONE id, generated at the moment of intent and reused for every retry / offline
// outbox replay. The backend's `X-Client-Request-Id` wall (R7b Slice 1) keys its
// exactly-once replay on this value, so the SAME id on a retry returns the SAME
// response instead of double-posting.
//
// Prefer the platform `crypto.randomUUID` (available in every browser the app
// targets); fall back to an RFC-4122-shaped v4 only if it's missing (old test
// runners), so this never throws.

export function newClientRequestId() {
  try {
    if (typeof globalThis !== 'undefined' && globalThis.crypto && globalThis.crypto.randomUUID) {
      return globalThis.crypto.randomUUID()
    }
  } catch {
    /* fall through to the polyfill */
  }
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (c) => {
    const r = (Math.random() * 16) | 0
    const v = c === 'x' ? r : (r & 0x3) | 0x8
    return v.toString(16)
  })
}

export default newClientRequestId
