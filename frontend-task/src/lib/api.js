// lib/api.js — the one place the app talks to the backend (same contract as
// billing's src/api/client.js: Bearer token, JSON in/out, ApiError with detail).
const hostname = typeof window === 'undefined' ? '' : window.location?.hostname || ''
const localHost = !hostname || ['localhost', '[::1]', '::1'].includes(hostname) || hostname.endsWith('.local') || /^(127\.|10\.|192\.168\.|172\.(1[6-9]|2\d|3[01])\.)/.test(hostname)
const BASE = (import.meta.env.VITE_API_URL || (localHost ? '' : 'https://staterbill-task-ftkym77vzq-el.a.run.app')).replace(/\/$/, '')
const TOKEN_KEY = 'task_token'
const PAGE_STARTED = Date.now()
const wait = ms => new Promise(resolve => setTimeout(resolve, ms))

function exchangeWindow(ticket) {
  try {
    const [exp, payload] = ticket.split('.')
    const claims = JSON.parse(atob(payload.replace(/-/g, '+').replace(/_/g, '/')))
    if (Number.isInteger(claims.iat) && Number(exp) > claims.iat) return Math.min(130, Number(exp) - claims.iat + 10) * 1000
  } catch { /* legacy ticket */ }
  return 30000
}

export const tokenStore = {
  get: () => { try { return localStorage.getItem(TOKEN_KEY) } catch { return null } },
  set: (t) => { try { localStorage.setItem(TOKEN_KEY, t) } catch { /* private mode */ } },
  clear: () => { try { localStorage.removeItem(TOKEN_KEY) } catch { /* ignore */ } },
}

export class ApiError extends Error {
  constructor(message, status, body) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.body = body
  }
}

function detailText(detail) {
  if (!detail) return null
  if (typeof detail === 'string') return detail
  // FastAPI validation errors: [{loc, msg}]
  if (Array.isArray(detail)) {
    return detail.map(d => {
      const field = Array.isArray(d.loc) ? d.loc.filter(x => x !== 'body').join('.') : ''
      if (field.startsWith('geo')) return 'Location is required — allow location access and retry.'
      return field ? `${field}: ${d.msg}` : d.msg
    }).join(' · ')
  }
  return String(detail)
}

export async function request(method, path, { body, query } = {}) {
  let url = `${BASE}${path}`
  if (query) {
    const qs = new URLSearchParams(Object.entries(query).filter(([, v]) => v !== undefined && v !== null && v !== ''))
    if ([...qs].length) url += `?${qs}`
  }
  const token = tokenStore.get()
  const exchange = method === 'POST' && path === '/api/auth/exchange' && body?.ticket
  const canRetry = Boolean(exchange || method === 'GET')
  const deadline = exchange ? PAGE_STARTED + exchangeWindow(body.ticket) : Date.now() + 60000
  let res
  let attempt = 0
  for (;;) {
    if (token !== tokenStore.get()) throw new ApiError('Business session changed. Please try again.', 409)
    const controller = new AbortController()
    const timer = setTimeout(() => controller.abort(), Math.min(exchange ? 70000 : 60000, Math.max(1, deadline - Date.now())))
    try {
      res = await fetch(url, {
      method,
      headers: {
        ...(body !== undefined ? { 'Content-Type': 'application/json' } : {}),
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: body !== undefined ? JSON.stringify(body) : undefined,
      signal: controller.signal,
      })
    } catch {
      clearTimeout(timer)
      const delay = [2000, 4000, 8000][attempt++]
      if (canRetry && (typeof navigator === 'undefined' || navigator.onLine !== false) && delay && Date.now() + delay < deadline) { await wait(delay); continue }
      throw new ApiError(typeof navigator !== 'undefined' && navigator.onLine === false
        ? 'No connection — check mobile data / Wi-Fi.'
        : 'Could not reach the Field Team server. It may be starting up.', 0)
    } finally { clearTimeout(timer) }
    const retryable = canRetry && [429, 500, 502, 503, 504].includes(res.status)
    const fallback = [2000, 4000, 8000][attempt++]
    const retryAfter = res.headers?.get?.('Retry-After')
    const retryMs = retryAfter && (Number.isFinite(Number(retryAfter)) ? Number(retryAfter) * 1000 : Date.parse(retryAfter) - Date.now())
    const delay = Number.isFinite(retryMs) && retryAfter ? Math.max(0, retryMs) : fallback
    if (retryable && fallback && Date.now() + delay < deadline) { await wait(delay); continue }
    break
  }
  const text = await res.text()
  let data = null
  if (text) { try { data = JSON.parse(text) } catch { data = text } }
  // A slow response from the previous business must neither populate the new
  // workspace nor sign its owner out after a successful account switch.
  if (token !== tokenStore.get()) throw new ApiError('Business session changed. Please try again.', 409)
  if (!res.ok) {
    // 401: session gone. 402: the business is not on BizAssist Pro (any more).
    const sessionRejected = res.status === 401 && /Bearer\s+.*error\s*=\s*"invalid_token"/i.test(res.headers?.get?.('WWW-Authenticate') || '')
    if ((sessionRejected || res.status === 402) && token) window.dispatchEvent(new CustomEvent('task:unauthorized', { detail: detailText(data?.detail) }))
    const error = new ApiError(detailText(data?.detail) || ([429, 500, 502, 503, 504].includes(res.status) ? 'The Field Team server is starting or busy. Please try again.' : `Request failed (${res.status})`), res.status, data)
    error.sessionRejected = sessionRejected
    throw error
  }
  return data
}

export const api = {
  get: (p, query) => request('GET', p, { query }),
  post: (p, body) => request('POST', p, { body: body ?? {} }),
  put: (p, body) => request('PUT', p, { body }),
  patch: (p, body) => request('PATCH', p, { body }),
}
