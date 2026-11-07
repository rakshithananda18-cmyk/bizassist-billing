export function isSessionRejection(response) {
  return response?.status === 401 && /Bearer\s+.*error\s*=\s*"invalid_token"/i.test(response.headers?.get?.('WWW-Authenticate') || '')
}

export function readableError(status, body) {
  const detail = typeof body?.detail === 'string' ? body.detail : null
  if (detail && !/<(?:html|head|body|!doctype)\b/i.test(detail)) return detail
  if ([429, 500, 502, 503, 504].includes(status)) return 'The server is starting or busy. Please try again.'
  return status ? `Request failed (${status})` : 'Could not reach the server. Please try again.'
}

export async function responseError(response) {
  const body = await response.json().catch(() => ({}))
  return new Error(readableError(response.status, body))
}

export async function boundedFetch(url, options = {}) {
  const controller = new AbortController()
  const deadline = Date.now() + 60000
  const timeout = setTimeout(() => controller.abort(), 60000)
  const abort = () => controller.abort()
  if (options.signal?.aborted) controller.abort()
  options.signal?.addEventListener?.('abort', abort, { once: true })
  const retry = (options.method || 'GET').toUpperCase() === 'GET'
  const wait = milliseconds => new Promise((resolve, reject) => {
    const aborted = () => { clearTimeout(timer); reject(new DOMException('Request cancelled', 'AbortError')) }
    const timer = setTimeout(() => { controller.signal.removeEventListener('abort', aborted); resolve() }, milliseconds)
    controller.signal.addEventListener('abort', aborted, { once: true })
    if (controller.signal.aborted) aborted()
  })
  try {
    for (let attempt = 0; ; attempt++) {
      let response
      try { response = await fetch(url, { ...options, signal: controller.signal }) }
      catch (error) {
        if (options.signal?.aborted) throw error
        const delay = [2000, 4000, 8000][attempt]
        if (retry && !controller.signal.aborted && delay && Date.now() + delay < deadline) { await wait(delay); continue }
        throw new Error(readableError(0))
      }
      const fallback = [2000, 4000, 8000][attempt]
      const header = response.headers?.get?.('Retry-After')
      const requestedDelay = header && (Number.isFinite(Number(header)) ? Number(header) * 1000 : Date.parse(header) - Date.now())
      const delay = header && Number.isFinite(requestedDelay) ? Math.max(0, requestedDelay) : fallback
      if (retry && [429, 500, 502, 503, 504].includes(response.status) && fallback && Date.now() + delay < deadline) { await wait(delay); continue }
      if (!response.ok && /text\/html/i.test(response.headers?.get?.('Content-Type') || '')) {
        const headers = new Headers(response.headers)
        headers.set('Content-Type', 'application/json')
        return new Response(JSON.stringify({ detail: readableError(response.status) }), { status: response.status, headers })
      }
      return response
    }
  }
  finally {
    clearTimeout(timeout)
    options.signal?.removeEventListener?.('abort', abort)
  }
}

