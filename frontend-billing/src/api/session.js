import { API_BASE, getApiBase } from '../config'
import { tokenStorage } from '../utils/tokenStorage'
import { isOwnApiResponse, isSessionRejection, retryDelayMs } from './httpErrors'

let refreshing = null
let sessionGeneration = 0
export const invalidateSessionRefresh = () => { sessionGeneration++ }
const unauthorized = () => window.dispatchEvent(new CustomEvent('auth_unauthorized'))

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
