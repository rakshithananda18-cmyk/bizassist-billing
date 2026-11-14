import { useEffect, useState, useRef } from 'react'
import { API_BASE, IS_LOCAL_APP } from '../config'
import { logger } from '../utils/logger'
import { syncManager } from '../sync/syncManager'
import { createSseConnection } from '../sync/sseConnection'

export function useRealtimeLeader(token, settings, user) {
  const tabIdRef = useRef(Math.random().toString(36).substring(2, 11))
  const tabId = tabIdRef.current
  const channelRef = useRef(null)
  const esRef = useRef(null)
  const reconnectTimeoutRef = useRef(null)
  const consecutiveFailureCountRef = useRef(0)

  // ── Derive STABLE PRIMITIVES outside the effect ─────────────────────────────
  // CRITICAL: do NOT put the whole `settings` object in the useEffect deps array.
  // Settings is refreshed every ~2s by the cloud subscription sync, creating a
  // new object reference each time. That triggers the effect to re-run, tearing
  // down the SSE connection and immediately reconnecting — causing the "thrashing"
  // visible in logs as rapid subscribe/unsubscribe every 3-4 seconds.
  //
  // Instead, extract only the two primitives that actually control SSE behaviour.
  // A string and a boolean are compared by value, so the effect only re-runs
  // when the user genuinely changes their hosting mode or disables realtime sync.
  const clientMode = (typeof localStorage !== 'undefined' && localStorage.getItem('bizassist_hosting_mode')) || null
  const hostingMode = !IS_LOCAL_APP
    ? 'cloud'
    : (clientMode || settings?.general?.hosting_mode || 'local')
  // In hybrid mode, SSE is the sync heartbeat backbone — always keep it on.
  // Only pure local mode and an explicit global=false on cloud-only mode blocks SSE.
  const isRealtimeGlobalEnabled = hostingMode === 'hybrid'
    ? true
    : settings?.general?.realtime_sync_global !== false

  useEffect(() => {
    if (!token || !user || user?.is_demo || token === 'demo-guest-jwt-token-staterbill') {
      const detail = { status: 'connected', error: null, lastSyncTime: Date.now(), lastEntity: null, isOnline: true }
      window.__syncStatus = detail
      window.dispatchEvent(new CustomEvent('sync-status-change', { detail }))
      return
    }

    if (hostingMode === 'local' || !isRealtimeGlobalEnabled) {
      logger.info(`[REALTIME] Real-time stream disabled. mode=${hostingMode}, global_enabled=${isRealtimeGlobalEnabled}`)
      const detail = { status: 'disconnected', error: null, lastSyncTime: null, lastEntity: null, isOnline: navigator.onLine }
      window.__syncStatus = detail
      window.dispatchEvent(new CustomEvent('sync-status-change', { detail }))
      return
    }

    // Initialize BroadcastChannel
    const scope = `${user.public_id || ''}:${user.user_id || user.id || ''}`
    const leaderKey = `realtime_leader_tab:${scope}`
    const heartbeatKey = `realtime_leader_ts:${scope}`
    const channel = new BroadcastChannel(`bizassist_sse_leader:${scope}`)
    channelRef.current = channel

    // A late SSE onopen/onerror can fire AFTER this effect's cleanup closed the
    // channel (StrictMode remount, unmount, reconnect), and postMessage on a
    // closed channel throws "InvalidStateError: Channel is closed" — uncaught,
    // it also spams window_error telemetry. Route every broadcast through this
    // guard so a closed channel is a quiet no-op.
    let channelClosed = false
    const safePost = (msg) => {
      if (channelClosed) return
      try { channel.postMessage(msg) } catch { /* channel already closed */ }
    }

    let lastSyncTime = localStorage.getItem(`sync_last_time_${user.id}`) || null
    let lastEntity = localStorage.getItem(`sync_last_entity_${user.id}`) || null
    let connectionError = null
    let isCurrentLeader = false
    // Session-only pause: set after repeated SSE failures so we stop hammering the
    // cloud WITHOUT persisting realtime_sync_global=false to the server. Resets on
    // page refresh, network re-online, or an explicit reconnect — so the sync can
    // never get permanently stuck off from a transient blip (the old behaviour).
    let sessionPaused = false

    // isOnlineOverride lets follower tabs pass the correct isOnline value from the
    // broadcast message instead of reading navigator.onLine locally (which may
    // differ from the leader's reading on some browsers).
    const emitStatus = (status, errOverride = null, isOnlineOverride = null) => {
      const detail = {
        status,
        error: errOverride || connectionError,
        lastSyncTime,
        lastEntity,
        isOnline: isOnlineOverride !== null ? isOnlineOverride : navigator.onLine
      }
      window.__syncStatus = detail
      window.dispatchEvent(new CustomEvent('sync-status-change', { detail }))
    }

    // Process an SSE event (pull changes locally, update localStorage, notify other components/tabs)
    const processEvent = async (data, isLeaderOrigin = false) => {
      // Dispatch to all window listeners immediately (includes sync.progress for the popover).
      window.dispatchEvent(new CustomEvent('sync-event', { detail: data }))

      // Progress and reconnect events are tracking/control-only — don't update
      // lastSyncTime, don't toast. Progress fires many times per batch; reconnect
      // is a silent re-fetch signal. Both still get dispatched to window listeners.
      if (data.type === 'sync.progress' || data.type === 'sync.reconnect') return


      lastSyncTime = new Date().toISOString()
      localStorage.setItem(`sync_last_time_${user.id}`, lastSyncTime)
      if (data.entity) {
        lastEntity = data.entity
        localStorage.setItem(`sync_last_entity_${user.id}`, lastEntity)
      }
      connectionError = null
      emitStatus('connected')

      if (data.entity) {
        window.dispatchEvent(new CustomEvent('show_toast', {
          detail: { type: 'info', msg: `Syncing remote ${data.entity} updates…` }
        }))
      }

      // Only the leader triggers syncManager.pull() to avoid concurrent duplicate requests.
      // Fire-and-forget with a 5s timeout so a slow/offline cloud NEVER blocks the live
      // counter UI. The pull is best-effort — the next SSE event will try again.
      const isPullPing = data.type === 'sync.pull_ping' || data.entity === 'pull_ping'
      const isRelevantEntity = ['invoice', 'payment', 'purchase', 'product', 'party', 'order', 'godown'].includes(data.entity)

      if (isLeaderOrigin && (isRelevantEntity || isPullPing)) {
        logger.info('[REALTIME] Leader pulling deltas for entity:', data.entity || 'pull_ping')
        const pullWithTimeout = Promise.race([
          syncManager.pull(),
          new Promise((_, reject) => setTimeout(() => reject(new Error('pull timeout')), 5000))
        ])
        pullWithTimeout.catch(err => {
          logger.warn('[REALTIME] Leader pull skipped (non-blocking):', err?.message || err)
        })
      }
    }

    const connectSSE = () => {
      esRef.current?.close()
      if (!isCurrentLeader || !navigator.onLine) return
      emitStatus('connecting')
      esRef.current = createSseConnection({
        baseUrl: API_BASE,
        fetchTicket: async () => {
          const response = await fetch(`${API_BASE}/realtime/ticket`, {
            method: 'POST', headers: { Authorization: `Bearer ${token}` },
            signal: AbortSignal.timeout(65000),
          })
          if (!response.ok) throw new Error(`Ticket ${response.status}`)
          const { ticket } = await response.json()
          return `${API_BASE}/realtime/events?ticket=${encodeURIComponent(ticket)}`
        },
        onEvent: data => { void processEvent(data, true); safePost({ type: 'sync_event', data }) },
        onGap: () => {
          const data = { type: 'sync.reconnect' }
          void processEvent(data, true)
          safePost({ type: 'sync_event', data })
          void syncManager.pull().catch(() => {})
        },
        onStatus: status => {
          if (!isCurrentLeader || channelClosed) return
          if (status === 'degraded') {
            connectionError = 'Live sync interrupted. Retrying…'
            emitStatus('error')
            safePost({ type: 'status_change', status: 'error', error: connectionError })
            window.dispatchEvent(new CustomEvent('show_toast', { detail: { type: 'warning', msg: connectionError } }))
          } else {
            connectionError = null
            consecutiveFailureCountRef.current = 0
            emitStatus('connected')
            safePost({ type: 'status_change', status: 'connected', error: null, restored: status === 'restored' })
            if (status === 'restored') window.dispatchEvent(new CustomEvent('show_toast', { detail: { type: 'success', msg: 'Live sync restored' } }))
          }
        },
      })
    }

    const checkLeadership = () => {
      const currentLeader = localStorage.getItem(leaderKey)
      const lastHeartbeat = parseInt(localStorage.getItem(heartbeatKey) || '0', 10)
      const now = Date.now()

      if (!currentLeader || currentLeader === tabId || now - lastHeartbeat > 8000) {
        // Claim leadership
        localStorage.setItem(leaderKey, tabId)
        localStorage.setItem(heartbeatKey, now.toString())
        
        if (!isCurrentLeader) {
          logger.info(`[REALTIME] Tab ${tabId} elected as leader.`)
          isCurrentLeader = true
          safePost({ type: 'leader_claimed', tabId })
          connectSSE()
        }
      } else {
        if (isCurrentLeader) {
          logger.info(`[REALTIME] Tab ${tabId} demoted from leader.`)
          isCurrentLeader = false
          if (esRef.current) {
            esRef.current.close()
            esRef.current = null
          }
          if (reconnectTimeoutRef.current) {
            clearTimeout(reconnectTimeoutRef.current)
            reconnectTimeoutRef.current = null
          }
        }
      }
    }

    const releaseLeadership = () => {
      const currentLeader = localStorage.getItem(leaderKey)
      if (currentLeader === tabId) {
        localStorage.removeItem(leaderKey)
        localStorage.removeItem(heartbeatKey)
        safePost({ type: 'leader_left', tabId })
      }
      if (reconnectTimeoutRef.current) {
        clearTimeout(reconnectTimeoutRef.current)
        reconnectTimeoutRef.current = null
      }
    }

    // Channel message handling
    channel.onmessage = (event) => {
      const msg = event.data
      if (!msg) return

      if (msg.type === 'leader_claimed') {
        if (msg.tabId !== tabId && isCurrentLeader) {
          logger.info(`[REALTIME] Yielding leadership to Tab ${msg.tabId}`)
          isCurrentLeader = false
          if (esRef.current) {
            esRef.current.close()
            esRef.current = null
          }
        }
      } else if (msg.type === 'leader_left') {
        // Run election immediately
        checkLeadership()
      } else if (msg.type === 'sync_event') {
        if (!isCurrentLeader) {
          // Followers process the event locally (but do NOT call pull())
          processEvent(msg.data, false)
        }
      } else if (msg.type === 'status_change') {
        if (!isCurrentLeader) {
          // Pass isOnline from broadcast so follower shows correct Online/Offline state.
          const broadcastIsOnline = typeof msg.isOnline === 'boolean' ? msg.isOnline : null
          emitStatus(msg.status, msg.error, broadcastIsOnline)
          if (msg.status === 'connected' && msg.restored) {
            window.dispatchEvent(new CustomEvent('show_toast', {
              detail: { type: 'success', msg: 'Live sync restored' }
            }))
          } else if (msg.status === 'offline') {
            window.dispatchEvent(new CustomEvent('show_toast', {
              detail: { type: 'warning', msg: 'Network connection lost. Billing works offline.' }
            }))
          } else if (msg.status === 'error') {
            window.dispatchEvent(new CustomEvent('show_toast', {
              detail: { type: 'error', msg: msg.error || 'Sync stream interrupted. Reconnecting…' }
            }))
          }
        }
      } else if (msg.type === 'settings_updated_auto_disable') {
        if (!isCurrentLeader) {
          logger.warn('[REALTIME] Follower notified that settings were auto-disabled due to:', msg.reason)
          window.dispatchEvent(new CustomEvent('realtime-sync-auto-disabled', { detail: { reason: msg.reason } }))
          window.dispatchEvent(new CustomEvent('refresh-settings'))
        }
      } else if (msg.type === 'reconnect_request') {
        if (isCurrentLeader) {
          logger.info('[REALTIME] Leader received reconnect request from follower.')
          connectSSE()
        }
      }
    }

    // Initial election
    checkLeadership()

    // Heartbeat and election checking loop
    const heartbeatInterval = setInterval(() => {
      if (isCurrentLeader) {
        localStorage.setItem(heartbeatKey, Date.now().toString())
      } else {
        checkLeadership()
      }
    }, 4000)

    const handleOnline = () => {
      logger.info('[REALTIME] Network online detected.')
      sessionPaused = false                     // network recovered — allow reconnects again
      consecutiveFailureCountRef.current = 0
      connectionError = null
      emitStatus('connecting')
      if (reconnectTimeoutRef.current) {
        clearTimeout(reconnectTimeoutRef.current)
        reconnectTimeoutRef.current = null
      }
      if (isCurrentLeader) {
        connectSSE()
      }
    }

    const handleOffline = () => {
      logger.warn('[REALTIME] Network offline detected.')
      connectionError = 'No internet connection. Client is offline.'
      // Use 'offline' as a dedicated status so the UI can distinguish it from a
      // genuine connection error. emitStatus uses navigator.onLine (already false).
      emitStatus('offline')
      if (reconnectTimeoutRef.current) {
        clearTimeout(reconnectTimeoutRef.current)
        reconnectTimeoutRef.current = null
      }
      if (isCurrentLeader) {
        // Broadcast isOnline:false explicitly so follower tabs show "Offline" not "Error".
        safePost({ type: 'status_change', status: 'offline', error: connectionError, isOnline: false })
      }
      window.dispatchEvent(new CustomEvent('show_toast', {
        detail: { type: 'warning', msg: 'Network connection lost. Billing works offline.' }
      }))
    }

    const handleReconnectRequest = () => {
      logger.info('[REALTIME] Reconnect requested.')
      sessionPaused = false                     // explicit user reconnect clears the pause
      consecutiveFailureCountRef.current = 0
      if (isCurrentLeader) {
        connectSSE()
      } else {
        // followers forward to the leader (or ask leader to reconnect) via channel
        safePost({ type: 'reconnect_request' })
      }
    }

    const handleStatusRequest = () => {
      logger.debug('[REALTIME] Status request received.')
      if (isCurrentLeader) {
        const currentStatus = esRef.current && esRef.current.readyState === EventSource.OPEN ? 'connected' : (navigator.onLine ? 'connecting' : 'error')
        emitStatus(currentStatus)
      } else {
        const detail = window.__syncStatus || { status: 'connecting', error: null, lastSyncTime, lastEntity, isOnline: navigator.onLine }
        window.dispatchEvent(new CustomEvent('sync-status-change', { detail }))
      }
    }

    window.addEventListener('online', handleOnline)
    window.addEventListener('offline', handleOffline)
    window.addEventListener('sync-reconnect-request', handleReconnectRequest)
    window.addEventListener('sync-status-request', handleStatusRequest)
    window.addEventListener('beforeunload', releaseLeadership)

    return () => {
      logger.info(`[REALTIME] Cleaning up realtime listener for Tab ${tabId}.`)
      clearInterval(heartbeatInterval)
      if (reconnectTimeoutRef.current) {
        clearTimeout(reconnectTimeoutRef.current)
        reconnectTimeoutRef.current = null
      }
      releaseLeadership()
      if (esRef.current) {
        esRef.current.close()
        esRef.current = null
      }
      channelClosed = true   // stop any late SSE handler from posting to it
      channel.close()
      window.removeEventListener('online', handleOnline)
      window.removeEventListener('offline', handleOffline)
      window.removeEventListener('sync-reconnect-request', handleReconnectRequest)
      window.removeEventListener('sync-status-request', handleStatusRequest)
      window.removeEventListener('beforeunload', releaseLeadership)
    }
  }, [user?.id, user?.user_id, user?.public_id, token, hostingMode, isRealtimeGlobalEnabled])
}
