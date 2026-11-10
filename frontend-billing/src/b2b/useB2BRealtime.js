// ============================================================================
// b2b/useB2BRealtime.js
// ----------------------------------------------------------------------------
// ONE EventSource for the whole B2B workspace.
//
// The old B2BOrders page opened its own SSE stream on top of the app-wide
// `sync-event` listener it also registered, so every visit added a second
// long-lived server connection per user (review finding F-6). Splitting the
// page into four tabs would have multiplied that. This hook is mounted once by
// the page and fans events out to the tabs through plain callbacks.
//
// It subscribes to the SAME backend that issued the session token. An earlier
// revision pointed it at the cloud hub — but the SSE ticket is minted from that
// token, and a local token is not valid on the cloud, so it could only ever
// authenticate as the wrong business or not at all. Cross-network B2B events
// reach a local hub through the existing cloud->local relay
// (backend/routes/realtime_relay.py), which is the correct bridge.
//
// Also handles: ticket minting, exponential-ish reconnect, teardown on unmount,
// and respecting the owner's `realtime_sync_global` setting.
// ============================================================================
import { useEffect, useRef } from 'react'
import { API_BASE } from '../config'
import { createSseConnection } from '../sync/sseConnection'

export function useB2BRealtime({ token, enabled = true, onEvent }) {
  const onEventRef = useRef(onEvent)
  useEffect(() => { onEventRef.current = onEvent })
  useEffect(() => {
    if (!token || !enabled) return
    const connection = createSseConnection({
      fetchTicket: async () => {
        const response = await fetch(`${API_BASE}/realtime/ticket`, {
          method: 'POST', headers: { Authorization: `Bearer ${token}` }, signal: AbortSignal.timeout(65000),
        })
        if (!response.ok) throw new Error(`Ticket ${response.status}`)
        const { ticket } = await response.json()
        return `${API_BASE}/realtime/events?ticket=${encodeURIComponent(ticket)}`
      },
      onEvent: data => onEventRef.current?.(data),
      onGap: () => onEventRef.current?.({ type: 'sync.reconnect' }),
    })
    const online = () => connection.reconnect()
    window.addEventListener('online', online)
    return () => { connection.close(); window.removeEventListener('online', online) }
  }, [token, enabled])
}
export default useB2BRealtime
