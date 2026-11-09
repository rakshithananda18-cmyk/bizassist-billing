import { API_BASE, getApiBase } from '../config'
import { tokenStorage } from '../utils/tokenStorage'
import { isOwnApiResponse, isSessionRejection, retryDelayMs } from './httpErrors'

let refreshing = null
let sessionGeneration = 0
export const invalidateSessionRefresh = () => { sessionGeneration++ }
const isDemoEnvironment = () => {
  try {
    if (typeof window === 'undefined') return false
    const s = (window.location.search || '').toLowerCase()
    const p = (window.location.pathname || '').toLowerCase()
    if (p.startsWith('/demo') || s.includes('demo=1') || s.includes('demo=true')) return true
    try {
      if (sessionStorage.getItem('stater_demo_active') === '1') return true
    } catch {}
    if (tokenStorage.getItem('billing_token') === 'demo-guest-jwt-token-staterbill') return true
  } catch {}
  return false
}

const unauthorized = () => {
  if (isDemoEnvironment()) return
  window.dispatchEvent(new CustomEvent('auth_unauthorized'))
}

export async function refreshSession() {
  if (refreshing) return refreshing
  const oldToken = tokenStorage.getItem('billing_token')
  if (!oldToken) return null
  const base = getApiBase() || API_BASE
  const generation = sessionGeneration
  refreshing = (async () => {
    const controller = new AbortController()
    const timer = setTimeout(() => controller.abort(), 65000)
    try {
      const res = await fetch(`${base}/auth/refresh`, { method: 'POST', headers: { Authorization: `Bearer ${oldToken}` }, signal: controller.signal })
      if (generation !== sessionGeneration || tokenStorage.getItem('billing_token') !== oldToken || (getApiBase() || API_BASE) !== base) return null
      if (res.status === 401) { unauthorized(); return null }
      if (!res.ok) return null
      const data = await res.json()
      const next = data.token || data.access_token
      if (next && tokenStorage.getItem('billing_token') === oldToken) {
        tokenStorage.setItem('billing_token', next)
        window.dispatchEvent(new CustomEvent('auth_token_refreshed', { detail: { token: next } }))
        return next
      }
      return null
    } finally { clearTimeout(timer) }
  })().catch(() => null).finally(() => { refreshing = null })
  return refreshing
}

export async function sessionFetch(url, options = {}) {
  if (isDemoEnvironment()) {
    try {
      if (url.includes('/profile')) {
        return {
          ok: true, status: 200, json: async () => ({
            id: 999999, user_id: 999999, username: 'demo_owner', business_name: 'ARES Retail Supermarket (Demo)', role: 'owner', plan: 'pro', is_premium: true, is_demo: true,
          })
        }
      }
      if (url.includes('/business/config')) {
        return {
          ok: true, status: 200, json: async () => ({
            config: { business_name: 'ARES Retail Supermarket (Demo)', currency: 'INR', demo: true },
            attributes_schema: []
          })
        }
      }
      if (url.includes('/settings')) {
        return {
          ok: true, status: 200, json: async () => ({
            general: { business_name: 'ARES Retail Supermarket (Demo)', hosting_mode: 'cloud', theme: 'system' }
          })
        }
      }
    } catch {}
    return { ok: true, status: 200, json: async () => ({}) }
  }
  const initialToken = tokenStorage.getItem('billing_token')
  const res = await fetch(url, options)
  // An old in-flight request must never end a newer business's session.
  if (tokenStorage.getItem('billing_token') !== initialToken) return res
  if (isSessionRejection(res, url)) { unauthorized(); return res }
  if (res.status === 401 && isOwnApiResponse(res, url) && !url.endsWith('/auth/refresh')) {
    const next = await refreshSession()
    if (next) {
      const retried = await fetch(url, { ...options, headers: { ...options.headers, Authorization: `Bearer ${next}` } })
      if (tokenStorage.getItem('billing_token') === next && isSessionRejection(retried, url)) unauthorized()
      return retried
    }
  }
  return res
}

export async function resilientSessionFetch(url, options = {}, { budgetMs = 65000 } = {}) {
  const controller = new AbortController()
  const started = Date.now()
  const abort = () => controller.abort()
  options.signal?.addEventListener('abort', abort, { once: true })
  if (options.signal?.aborted) controller.abort()
  const deadline = setTimeout(abort, budgetMs)
  const safe = ['GET', 'HEAD'].includes((options.method || 'GET').toUpperCase())
    || new Headers(options.headers || {}).has('X-Client-Request-Id')
  try {
    for (let attempt = 0; ; attempt++) {
      let response, networkError
      try {
        response = await sessionFetch(url, { ...options, signal: controller.signal })
        if (!safe || attempt >= 3 || ![429, 502, 503, 504].includes(response.status)) return response
      } catch (error) {
        if (!safe || attempt >= 3 || controller.signal.aborted) throw error
        networkError = error
      }
      const delay = retryDelayMs(attempt, response?.headers?.get?.('Retry-After'))
      if (Date.now() - started + delay >= budgetMs) {
        if (response) return response
        throw networkError
      }
      await new Promise((resolve, reject) => {
        const finish = () => { controller.signal.removeEventListener('abort', cancelled); resolve() }
        const timer = setTimeout(finish, delay)
        function cancelled() { clearTimeout(timer); controller.signal.removeEventListener('abort', cancelled); reject(new DOMException('Aborted', 'AbortError')) }
        controller.signal.addEventListener('abort', cancelled, { once: true })
        if (controller.signal.aborted) cancelled()
      })
    }
  } finally {
    clearTimeout(deadline)
    options.signal?.removeEventListener('abort', abort)
  }
}
