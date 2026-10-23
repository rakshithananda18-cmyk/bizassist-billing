// lib/api.js — the one place the app talks to the backend (same contract as
// billing's src/api/client.js: Bearer token, JSON in/out, ApiError with detail).
const BASE = (import.meta.env.VITE_API_URL || '').replace(/\/$/, '')
const TOKEN_KEY = 'task_token'

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
  let res
  try {
    res = await fetch(url, {
      method,
      headers: {
        ...(body !== undefined ? { 'Content-Type': 'application/json' } : {}),
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: body !== undefined ? JSON.stringify(body) : undefined,
    })
  } catch {
    throw new ApiError('No connection — check mobile data / Wi-Fi.', 0)
  }
  const text = await res.text()
  let data = null
  if (text) { try { data = JSON.parse(text) } catch { data = text } }
  if (!res.ok) {
    // 401: session gone. 402: the business is not on BizAssist Pro (any more).
    if ((res.status === 401 || res.status === 402) && token) window.dispatchEvent(new CustomEvent('task:unauthorized', { detail: detailText(data?.detail) }))
    throw new ApiError(detailText(data?.detail) || `Request failed (${res.status})`, res.status, data)
  }
  return data
}

export const api = {
  get: (p, query) => request('GET', p, { query }),
  post: (p, body) => request('POST', p, { body: body ?? {} }),
  put: (p, body) => request('PUT', p, { body }),
  patch: (p, body) => request('PATCH', p, { body }),
}
