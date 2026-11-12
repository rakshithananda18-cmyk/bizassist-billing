// These claims are an unverified UX hint, never proof that a token is valid.
// The server still validates signatures, expiry, revocation and permissions.
export function readSessionClaims(token) {
  if (typeof token !== 'string') return null
  try {
    const segment = token.split('.')[1]
    if (!segment) return null
    const normalized = segment.replace(/-/g, '+').replace(/_/g, '/')
    const bytes = Uint8Array.from(atob(normalized.padEnd(Math.ceil(normalized.length / 4) * 4, '=')), char => char.charCodeAt(0))
    return JSON.parse(new TextDecoder().decode(bytes))
  } catch { return null }
}

export function isSessionTokenExpired(token, now = Date.now()) {
  const exp = readSessionClaims(token)?.exp
  return Number.isFinite(exp) && exp * 1000 <= now
}

export const SESSION_EXPIRED_NOTICE = 'Your session expired. Please sign in again.'
