import { API_BASE, getApiBase } from '../config'
import { tokenStorage } from '../utils/tokenStorage'
import { isOwnApiResponse, isSessionRejection, retryDelayMs } from './httpErrors'
import { DEMO_TOKEN, handleDemoRequest, isDemoRequested } from '../demo/demoEngine'

let refreshing = null
let sessionGeneration = 0
export const invalidateSessionRefresh = () => { sessionGeneration++ }
const isDemoEnvironment = () => {
  try {
    return isDemoRequested() || tokenStorage.getItem('billing_token') === DEMO_TOKEN
  } catch {}
  return false
}

const unauthorized = () => {
  if (isDemoEnvironment()) return
  window.dispatchEvent(new CustomEvent('auth_unauthorized'))
}

export async function refreshSession() {
  if (isDemoEnvironment()) return DEMO_TOKEN
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
      if (generation !== sessionGeneration || tokenStorage.getItem('billing_token') !== oldToken || (getApiBase() || API_BASE) !== base) return null
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

export async function sessionFetch(url, options = {}, scope = null) {
  if (isDemoEnvironment()) {
    return handleDemoRequest(url, options)
  }
  const initialToken = tokenStorage.getItem('billing_token')
  const generation = scope?.generation ?? sessionGeneration
  const base = scope?.base ?? (getApiBase() || API_BASE)
  const supplied = new Headers(options.headers || {}).get('Authorization')
  const current = () => generation === sessionGeneration && (getApiBase() || API_BASE) === base
    && tokenStorage.getItem('billing_token') === initialToken
  if (!current() || (supplied && supplied !== `Bearer ${initialToken}`)) throw new DOMException('Session changed', 'AbortError')
  const res = await fetch(url, options)
  // An old in-flight request must never end a newer business's session.
  if (!current()) return res
  if (isSessionRejection(res, url)) { unauthorized(); return res }
  if (res.status === 401 && isOwnApiResponse(res, url) && !url.endsWith('/auth/refresh')) {
    const next = await refreshSession()
    if (next && generation === sessionGeneration && (getApiBase() || API_BASE) === base && tokenStorage.getItem('billing_token') === next) {
      if (scope) scope.token = next
      const retried = await fetch(url, { ...options, headers: { ...options.headers, Authorization: `Bearer ${next}` } })
      if (generation === sessionGeneration && (getApiBase() || API_BASE) === base && tokenStorage.getItem('billing_token') === next && isSessionRejection(retried, url)) unauthorized()
      return retried
    }
  }
  return res
}

export async function resilientSessionFetch(url, options = {}, { budgetMs = 65000 } = {}) {
  const scope = { generation: sessionGeneration, base: getApiBase() || API_BASE, token: tokenStorage.getItem('billing_token') }
  const current = () => scope.generation === sessionGeneration && scope.base === (getApiBase() || API_BASE)
    && scope.token === tokenStorage.getItem('billing_token')
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
      if (!current()) throw new DOMException('Session changed', 'AbortError')
      let response, networkError
      try {
        const headers = Object.fromEntries(new Headers(options.headers || {}).entries())
        if (new Headers(options.headers || {}).has('Authorization')) {
          delete headers.authorization
          headers.Authorization = `Bearer ${scope.token}`
        }
        response = await sessionFetch(url, { ...options, headers, signal: controller.signal }, scope)
        if (!current()) return response
        if (!safe || attempt >= 3 || ![429, 502, 503, 504].includes(response.status)) return response
      } catch (error) {
        if (!current()) throw new DOMException('Session changed', 'AbortError')
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
