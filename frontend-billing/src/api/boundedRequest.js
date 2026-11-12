// The deadline includes reading the body: fetch resolving only proves that the
// headers arrived, and an interrupted body can otherwise keep sign-in pending.
export async function boundedJsonFetch(url, options = {}, timeoutMs = 10000) {
  const controller = new AbortController()
  const abort = () => controller.abort()
  options.signal?.addEventListener('abort', abort, { once: true })
  if (options.signal?.aborted) abort()
  let timer
  try {
    const deadline = new Promise((_, reject) => {
      const fail = () => {
        const error = new Error('Request timed out. Check the connection and try again.')
        error.code = 'AUTH_REQUEST_TIMEOUT'
        reject(error)
      }
      controller.signal.addEventListener('abort', fail, { once: true })
      timer = setTimeout(abort, Math.max(1, timeoutMs))
      if (controller.signal.aborted) fail()
    })
    return await Promise.race([deadline, (async () => {
      const response = await fetch(url, { ...options, signal: controller.signal })
      let body
      try { body = await response.json() } catch (error) {
        if (controller.signal.aborted) throw error
        body = {}
      }
      // Preserve Response metadata and existing callers while consuming the body
      // under the same deadline. Authentication callers only consume JSON.
      Object.defineProperty(response, 'json', { configurable: true, value: async () => body })
      return response
    })()])
  } finally {
    clearTimeout(timer)
    options.signal?.removeEventListener('abort', abort)
  }
}

export function requestBudget(totalMs = 30000, isCurrent = () => true) {
  const end = Date.now() + totalMs
  return (url, options = {}, perRequestMs = 10000) => {
    if (!isCurrent()) return Promise.reject(new DOMException('Session changed', 'AbortError'))
    const remaining = end - Date.now()
    if (remaining <= 0) {
      const error = new Error('Sign-in recovery timed out. Check the connection and try again.')
      error.code = 'AUTH_REQUEST_TIMEOUT'
      return Promise.reject(error)
    }
    return boundedJsonFetch(url, options, Math.min(remaining, perRequestMs)).then(response => {
      if (!isCurrent()) throw new DOMException('Session changed', 'AbortError')
      return response
    })
  }
}
