// src/api/client.js — the one place the frontend talks to the backend.
// ====================================================================
// Today every page hand-rolls `fetch(`${API_BASE}/...`, { headers: { Authorization }})`
// with its own error handling. That's ~16 copies of the same boilerplate and an
// easy place for bugs (a forgotten token, inconsistent error parsing). This wraps
// `fetch` (the convention this app already uses — NOT axios) so a call is one line:
//
//     import { api } from '../api/client'
//     const data = await api.get('/sales/products/search', { q })
//     const inv  = await api.post('/sales', payload)
//
// It auto-attaches the Bearer token, prefixes API_BASE, parses JSON, and throws a
// real Error (with the backend's `detail`) on non-2xx so callers can try/catch.
import { API_BASE } from '../config'
import { logger } from '../utils/logger'

const TOKEN_KEY = 'billing_token'

export function getToken() {
  try { return localStorage.getItem(TOKEN_KEY) } catch { return null }
}

/** Raised on any non-2xx response. `status` + `detail` come from the backend. */
export class ApiError extends Error {
  constructor(message, { status, detail, body } = {}) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.detail = detail
    this.body = body
  }
}

function buildUrl(path, query) {
  const base = path.startsWith('http') ? path : `${API_BASE}${path.startsWith('/') ? '' : '/'}${path}`
  if (!query || Object.keys(query).length === 0) return base
  const qs = new URLSearchParams()
  for (const [k, v] of Object.entries(query)) {
    if (v !== undefined && v !== null && v !== '') qs.append(k, v)
  }
  const s = qs.toString()
  return s ? `${base}?${s}` : base
}

/**
 * Core request. `opts`:
 *   query  — object → querystring
 *   body   — object → JSON body (sets Content-Type)
 *   signal — AbortSignal
 *   raw    — true → resolve the Response (for blobs/PDF), skip JSON parse
 *   headers— extra headers
 */
export async function request(method, path, { query, body, signal, raw, headers } = {}) {
  const token = getToken()
  const url = buildUrl(path, query)
  const init = {
    method,
    signal,
    headers: {
      ...(body !== undefined ? { 'Content-Type': 'application/json' } : {}),
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...headers,
    },
  }
  if (body !== undefined) init.body = JSON.stringify(body)

  let res
  try {
    res = await fetch(url, init)
  } catch (err) {
    // Network / CORS / aborted — never block the counter on this; surface clearly.
    if (err.name === 'AbortError') throw err
    logger.error('[api] network error', method, url, err?.message)
    throw new ApiError('Network error — could not reach the server.', { status: 0 })
  }

  if (raw) {
    if (!res.ok) throw await toError(res, method, url)
    return res
  }

  // Parse JSON when present; tolerate empty bodies (204 etc.).
  let data = null
  const text = await res.text()
  if (text) {
    try { data = JSON.parse(text) } catch { data = text }
  }

  if (!res.ok) throw await toError(res, method, url, data)
  return data
}

async function toError(res, method, url, data) {
  let detail
  if (data && typeof data === 'object') detail = data.detail || data.message
  else if (typeof data === 'string') detail = data
  if (detail === undefined) {
    try { detail = (await res.clone().json())?.detail } catch { /* ignore */ }
  }
  logger.error('[api]', method, url, '→', res.status, detail || '')
  return new ApiError(detail || `Request failed (${res.status})`, {
    status: res.status, detail, body: data,
  })
}

export const api = {
  get:   (path, query, opts)        => request('GET',    path, { ...opts, query }),
  post:  (path, body, opts)         => request('POST',   path, { ...opts, body }),
  put:   (path, body, opts)         => request('PUT',    path, { ...opts, body }),
  patch: (path, body, opts)         => request('PATCH',  path, { ...opts, body }),
  del:   (path, opts)               => request('DELETE', path, { ...opts }),
  // Escape hatch for binary responses (e.g. invoice PDF): returns the Response.
  raw:   (path, query, opts)        => request('GET',    path, { ...opts, query, raw: true }),
}

export default api
