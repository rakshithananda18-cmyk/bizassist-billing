import { API_BASE, getApiBase } from '../config'

export function isOwnApiResponse(res, requestUrl) {
  try {
    const base = new URL(getApiBase() || API_BASE, window.location.href)
    const actual = new URL(res.url || requestUrl || '', window.location.href)
    return actual.origin === base.origin && (base.pathname === '/' || actual.pathname.startsWith(`${base.pathname.replace(/\/$/, '')}/`))
  } catch { return false }
}

export function isSessionRejection(res, requestUrl) {
  return [401, 404].includes(res.status) && isOwnApiResponse(res, requestUrl)
    && /\binvalid_token\b/i.test(res.headers?.get?.('WWW-Authenticate') || '')
}

export function readableError(status, contentType, bodyText) {
  if (typeof bodyText === 'object' && bodyText !== null) {
    const detail = bodyText.detail || bodyText.message
    if (typeof detail === 'string') return detail
    if (Array.isArray(detail)) return detail.map(item => item.msg || 'Invalid request').join('; ')
  }
  if (typeof bodyText === 'string' && /json/i.test(contentType || '')) {
    try { return readableError(status, contentType, JSON.parse(bodyText)) } catch { /* gateway mislabelled as JSON */ }
  }
  if (status === 429) return 'The server is busy. Trying again…'
  if ([502, 503].includes(status)) return 'The server is starting. Trying again…'
  if (status === 504) return 'The server took too long to respond.'
  if (status >= 500) return 'The server could not complete the request. Please try again.'
  if (typeof bodyText === 'string' && bodyText.trim() && !/<(?:!doctype|html|body|head)\b/i.test(bodyText)) return bodyText.slice(0, 500)
  return `Request failed (${status}). Please try again.`
}

export function retryDelayMs(attempt, retryAfter) {
  if (retryAfter != null && String(retryAfter).trim()) {
    const seconds = Number(retryAfter)
    const delay = Number.isFinite(seconds) ? seconds * 1000 : Date.parse(retryAfter) - Date.now()
    if (Number.isFinite(delay)) return Math.min(30000, Math.max(0, delay))
  }
  return Math.min(30000, 1000 * 2 ** attempt)
}
