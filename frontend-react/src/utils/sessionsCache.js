import { API_BASE } from '../config'

// In-flight de-duplication for GET /chat/sessions.
//
// Several components (Chat, InsightsPanel) load the session list, and they all
// listen to the same 'ai-sessions-updated' event — so a single user action used
// to fire ~4 identical requests. While one request is in flight, every caller
// shares it. No result caching, so the data is never stale (each fresh call
// after the previous resolves still hits the network).

let inflight = null

export function fetchSessions(authFetch) {
  if (inflight) return inflight
  inflight = (async () => {
    try {
      const res = await authFetch(`${API_BASE}/chat/sessions`)
      if (!res.ok) throw new Error(`chat/sessions ${res.status}`)
      return await res.json()
    } finally {
      inflight = null
    }
  })()
  return inflight
}
