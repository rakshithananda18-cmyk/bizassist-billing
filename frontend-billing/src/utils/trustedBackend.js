const CLOUD_BACKEND = 'https://staterbill-api-1076771386585.asia-south1.run.app'

function privateHost(hostname) {
  if (['localhost', '127.0.0.1', '[::1]', '::1'].includes(hostname) || hostname.endsWith('.local')) return true
  const octets = hostname.split('.').map(Number)
  if (octets.length !== 4 || octets.some(part => !Number.isInteger(part) || part < 0 || part > 255)) return false
  return octets[0] === 10 || octets[0] === 192 && octets[1] === 168
    || octets[0] === 172 && octets[1] >= 16 && octets[1] <= 31
}

/** Accept configured cloud origins; LAN access is limited to a local install. */
export function trustedBackendUrl(value) {
  if (typeof window === 'undefined' || !window.location) return null
  let candidate
  // Electron file/app renderers have the opaque origin "null", which is not a
  // valid URL base even when the requested backend itself is absolute.
  try { candidate = new URL(value) } catch {
    try { candidate = new URL(value, window.location.href) } catch { return null }
  }
  if (!['http:', 'https:'].includes(candidate.protocol) || candidate.username || candidate.password) return null
  if (!/^\/(?:[A-Za-z0-9._~-]+\/)*[A-Za-z0-9._~-]*$/.test(candidate.pathname)
      || candidate.search || candidate.hash) return null
  const remote = [CLOUD_BACKEND, import.meta.env.VITE_API_URL, import.meta.env.VITE_CLOUD_TELEMETRY_URL, window.location.origin]
    .filter(Boolean).some(base => {
      try { return new URL(base).origin === candidate.origin } catch { return false }
    })
  if (remote && (candidate.protocol === 'https:' || privateHost(candidate.hostname))) return candidate
  const desktopRenderer = window.bizassistDesktop?.isDesktop === true
    && ['file:', 'app:'].includes(window.location.protocol)
  if ((privateHost(window.location.hostname) || desktopRenderer) && privateHost(candidate.hostname)) return candidate
  return null
}

export function telemetryTarget(base) {
  const backend = trustedBackendUrl(base)
  return backend ? new URL(`${backend.pathname.replace(/\/$/, '')}/api/telemetry/log`, backend.origin) : null
}

export function realtimeTarget(value, base) {
  const backend = trustedBackendUrl(base)
  if (!backend) throw new Error('Realtime backend is not trusted')
  const supplied = new URL(value, backend)
  const path = `${backend.pathname.replace(/\/$/, '')}/realtime/events`
  if (supplied.origin !== backend.origin || supplied.pathname !== path
      || supplied.username || supplied.password || supplied.hash) throw new Error('Unexpected realtime endpoint')
  // Construct the destination from the approved backend and fixed route. Only
  // the ticket value is carried over from the supplied endpoint.
  const target = new URL(path, backend.origin)
  const ticket = supplied.searchParams.get('ticket')
  if (!ticket) throw new Error('Realtime ticket is missing')
  target.searchParams.set('ticket', ticket)
  return target
}
