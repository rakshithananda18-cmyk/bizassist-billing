import { useEffect, useState, useRef } from 'react'
import { API_BASE } from '../config'
import { logger } from '../utils/logger'
import { syncManager } from '../sync/syncManager'

export function useRealtimeLeader(token, settings, user) {
  const tabIdRef = useRef(Math.random().toString(36).substring(2, 11))
  const tabId = tabIdRef.current
  const channelRef = useRef(null)
  const esRef = useRef(null)

  useEffect(() => {
    if (!token || !user) {
      const detail = { status: 'disconnected', error: null, lastSyncTime: null, lastEntity: null, isOnline: navigator.onLine }
      window.__syncStatus = detail
      window.dispatchEvent(new CustomEvent('sync-status-change', { detail }))
      return
    }

    const hostingMode = settings?.general?.hosting_mode || 'local'
    const isRealtimeGlobalEnabled = settings?.general?.realtime_sync_global !== false
    
    if (hostingMode === 'local' || !isRealtimeGlobalEnabled) {
      logger.info(`[REALTIME] Real-time stream disabled. mode=${hostingMode}, global_enabled=${isRealtimeGlobalEnabled}`)
      const detail = { status: 'disconnected', error: null, lastSyncTime: null, lastEntity: null, isOnline: navigator.onLine }
      window.__syncStatus = detail
      window.dispatchEvent(new CustomEvent('sync-status-change', { detail }))
      return
    }

    // Initialize BroadcastChannel
    const channel = new BroadcastChannel('bizassist_sse_leader')
    channelRef.current = channel

    let lastSyncTime = localStorage.getItem(`sync_last_time_${user.id}`) || null
    let lastEntity = localStorage.getItem(`sync_last_entity_${user.id}`) || null
    let connectionError = null
    let isCurrentLeader = false

    const emitStatus = (status, errOverride = null) => {
      const detail = {
        status,
        error: errOverride || connectionError,
        lastSyncTime,
        lastEntity,
        isOnline: navigator.onLine
      }
      window.__syncStatus = detail
      window.dispatchEvent(new CustomEvent('sync-status-change', { detail }))
    }

    // Process an SSE event (pull changes locally, update localStorage, notify other components/tabs)
    const processEvent = async (data, isLeaderOrigin = false) => {
      lastSyncTime = new Date().toISOString()
      localStorage.setItem(`sync_last_time_${user.id}`, lastSyncTime)
      if (data.entity) {
        lastEntity = data.entity
        localStorage.setItem(`sync_last_entity_${user.id}`, lastEntity)
      }
      connectionError = null
      emitStatus('connected')

      // Dispatch local window level event
      window.dispatchEvent(new CustomEvent('sync-event', { detail: data }))
      if (data.entity) {
        window.dispatchEvent(new CustomEvent('show_toast', {
          detail: { type: 'info', msg: `Syncing remote ${data.entity} updates…` }
        }))
      }

      // Only the leader triggers syncManager.pull() to avoid concurrent duplicate requests
      if (isLeaderOrigin && ['invoice', 'payment', 'purchase', 'product', 'party', 'order', 'godown'].includes(data.entity)) {
        logger.info('[REALTIME] Leader pulling deltas for entity:', data.entity)
        try {
          await syncManager.pull()
        } catch (err) {
          logger.error('[REALTIME] Leader pull failed:', err)
        }
      }
    }

    // Connect to SSE stream (Leader only)
    const connectSSE = async () => {
      if (esRef.current) {
        esRef.current.close()
        esRef.current = null
      }

      if (!navigator.onLine) {
        logger.warn('[REALTIME] Offline, deferring EventSource connection.')
        return
      }

      logger.info('[REALTIME] Connecting to SSE stream. Mode:', hostingMode, 'Leader Tab:', tabId)
      window.dispatchEvent(new CustomEvent('show_toast', {
        detail: { type: 'info', msg: `Connecting to cloud sync stream (${hostingMode} mode)…` }
      }))

      emitStatus('connecting')
      channel.postMessage({ type: 'status_change', status: 'connecting', error: null })

      try {
        // Fetch short-lived ticket first (Feature 1)
        const response = await fetch(`${API_BASE}/realtime/ticket`, {
          method: 'POST',
          headers: {
            'Authorization': `Bearer ${token}`
          }
        })

        if (!response.ok) {
          throw new Error(`Failed to fetch SSE ticket: ${response.statusText}`)
        }

        const { ticket } = await response.json()
        const url = `${API_BASE}/realtime/events?ticket=${encodeURIComponent(ticket)}`
        
        const es = new EventSource(url)
        esRef.current = es

        es.onopen = () => {
          logger.info('[REALTIME] SSE connection established.')
          connectionError = null
          emitStatus('connected')
          channel.postMessage({ type: 'status_change', status: 'connected', error: null })
          window.dispatchEvent(new CustomEvent('show_toast', {
            detail: { type: 'success', msg: 'Cloud real-time sync connected.' }
          }))
        }

        es.onmessage = async (e) => {
          try {
            const data = JSON.parse(e.data)
            logger.debug('[REALTIME] Received SSE event:', data)
            
            // Process event (including pulling from server if needed)
            await processEvent(data, true)

            // Broadcast event to followers
            channel.postMessage({ type: 'sync_event', data })
          } catch (err) {
            logger.error('[REALTIME] SSE parse error:', err)
          }
        }

        es.onerror = (err) => {
          logger.error('[REALTIME] SSE error:', err)
          connectionError = 'Sync stream interrupted. Reconnecting…'
          emitStatus('error')
          channel.postMessage({ type: 'status_change', status: 'error', error: connectionError })
          window.dispatchEvent(new CustomEvent('show_toast', {
            detail: { type: 'error', msg: 'Sync stream interrupted. Reconnecting…' }
          }))
        }
      } catch (err) {
        logger.error('[REALTIME] EventSource setup failed:', err)
        connectionError = err.message || 'Failed to initialize sync client.'
        emitStatus('error')
        channel.postMessage({ type: 'status_change', status: 'error', error: connectionError })
        window.dispatchEvent(new CustomEvent('show_toast', {
          detail: { type: 'error', msg: `Sync connection failed: ${connectionError}` }
        }))
      }
    }

    const checkLeadership = () => {
      const currentLeader = localStorage.getItem('realtime_leader_tab')
      const lastHeartbeat = parseInt(localStorage.getItem('realtime_leader_ts') || '0', 10)
      const now = Date.now()

      if (!currentLeader || currentLeader === tabId || now - lastHeartbeat > 8000) {
        // Claim leadership
        localStorage.setItem('realtime_leader_tab', tabId)
        localStorage.setItem('realtime_leader_ts', now.toString())
        
        if (!isCurrentLeader) {
          logger.info(`[REALTIME] Tab ${tabId} elected as leader.`)
          isCurrentLeader = true
          channel.postMessage({ type: 'leader_claimed', tabId })
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
        }
      }
    }

    const releaseLeadership = () => {
      const currentLeader = localStorage.getItem('realtime_leader_tab')
      if (currentLeader === tabId) {
        localStorage.removeItem('realtime_leader_tab')
        localStorage.removeItem('realtime_leader_ts')
        channel.postMessage({ type: 'leader_left', tabId })
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
          emitStatus(msg.status, msg.error)
          if (msg.status === 'connected') {
            window.dispatchEvent(new CustomEvent('show_toast', {
              detail: { type: 'success', msg: 'Cloud real-time sync connected.' }
            }))
          } else if (msg.status === 'connecting') {
            window.dispatchEvent(new CustomEvent('show_toast', {
              detail: { type: 'info', msg: `Connecting to cloud sync stream (${hostingMode} mode)…` }
            }))
          } else if (msg.status === 'error') {
            window.dispatchEvent(new CustomEvent('show_toast', {
              detail: { type: 'error', msg: msg.error || 'Sync stream interrupted. Reconnecting…' }
            }))
          }
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
        localStorage.setItem('realtime_leader_ts', Date.now().toString())
      } else {
        checkLeadership()
      }
    }, 4000)

    const handleOnline = () => {
      logger.info('[REALTIME] Network online detected.')
      connectionError = null
      emitStatus('connecting')
      if (isCurrentLeader) {
        connectSSE()
      }
    }

    const handleOffline = () => {
      logger.warn('[REALTIME] Network offline detected.')
      connectionError = 'No internet connection. Client is offline.'
      emitStatus('error')
      if (isCurrentLeader) {
        channel.postMessage({ type: 'status_change', status: 'error', error: connectionError })
      }
      window.dispatchEvent(new CustomEvent('show_toast', {
        detail: { type: 'warning', msg: 'Network connection lost. Sync suspended.' }
      }))
    }

    const handleReconnectRequest = () => {
      logger.info('[REALTIME] Reconnect requested.')
      if (isCurrentLeader) {
        connectSSE()
      } else {
        // followers forward to the leader (or ask leader to reconnect) via channel
        channel.postMessage({ type: 'reconnect_request' })
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
      releaseLeadership()
      if (esRef.current) {
        esRef.current.close()
        esRef.current = null
      }
      channel.close()
      window.removeEventListener('online', handleOnline)
      window.removeEventListener('offline', handleOffline)
      window.removeEventListener('sync-reconnect-request', handleReconnectRequest)
      window.removeEventListener('sync-status-request', handleStatusRequest)
      window.removeEventListener('beforeunload', releaseLeadership)
    }
  }, [user, token, settings])
}
