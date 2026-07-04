import { API_BASE } from '../config'

// In-flight de-duplication for GET /chat/sessions.
//
// Several components (Chat, InsightsPanel) load the session list and all listen
// to the same 'ai-sessions-updated' event — so a single user action used to fire
// ~4 identical requests. While one request is in flight, concurrent callers share
// it.
//
// IMPORTANT: pass force=true for refreshes that follow a mutation (send / delete /
// rename / new chat). Otherwise a refresh that lands while a PRE-mutation request
// is still in flight would be handed that stale result — making a new session
// missing from the sidebar or a deleted one linger.

let inflight = null

export function fetchSessions(authFetch, force = false) {
  // Reuse an in-flight request only when not forcing — this collapses the
  // concurrent-mount burst without ever serving stale post-mutation data.
  if (inflight && !force) return inflight

  const p = (async () => {
    try {
      const res = await authFetch(`${API_BASE}/chat/sessions`)
      if (!res.ok) throw new Error(`chat/sessions ${res.status}`)
      return await res.json()
    } finally {
      // Only clear if we're still the current request (a newer forced request
      // may have replaced us).
      if (inflight === p) inflight = null
    }
  })()
  inflight = p
  return p
}
