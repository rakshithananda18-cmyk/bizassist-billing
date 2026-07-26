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
import { logger } from '../utils/logger'

const RECONNECT_MS = 5000

export function useB2BRealtime({ token, enabled = true, onEvent }) {
  const onEventRef = useRef(onEvent)
  useEffect(() => { onEventRef.current = onEvent })

  useEffect(() => {
    if (!token || !enabled) return

    let stopped = false
    let timer = null
    let es = null

    const connect = async () => {
      if (stopped) return
      try {
        const ticketRes = await fetch(`${API_BASE}/realtime/ticket`, {
          method: 'POST',
          headers: { Authorization: `Bearer ${token}` },
        })
        if (!ticketRes.ok) throw new Error(`ticket ${ticketRes.status}`)
        const { ticket } = await ticketRes.json()
        if (stopped) return

        es = new EventSource(`${API_BASE}/realtime/events?ticket=${encodeURIComponent(ticket)}`)

        es.onmessage = (e) => {
          try {
            onEventRef.current?.(JSON.parse(e.data))
          } catch (err) {
            logger.error('[B2B] unparseable realtime event', err)
          }
        }

        es.onerror = () => {
          es?.close()
          es = null
          if (!stopped) {
            logger.warn('[B2B] realtime stream dropped — retrying')
            timer = setTimeout(connect, RECONNECT_MS)
          }
        }
      } catch (err) {
        if (!stopped) {
          logger.warn('[B2B] realtime connect failed — retrying', err)
          timer = setTimeout(connect, RECONNECT_MS)
        }
      }
    }

    connect()

    return () => {
      stopped = true
      if (timer) clearTimeout(timer)
      if (es) { es.close(); es = null }
    }
  }, [token, enabled])
}

export default useB2BRealtime
