// ============================================================================
// b2b/useB2BConnections.js
// ----------------------------------------------------------------------------
// Owns the connection graph: the accepted links (customers + suppliers), the
// requests waiting on ME, the requests waiting on THEM, and every mutation that
// can move a link between those buckets.
//
// The page and the tabs consume this; none of them talk to the network. That
// keeps the ordering surface, the connections surface and the order queues all
// reading one consistent snapshot, and means a mutation refreshes every tab at
// once rather than each tab holding its own stale copy.
// ============================================================================
import { useCallback, useEffect, useRef, useState } from 'react'
import * as b2b from './b2bClient'
import { logger } from '../utils/logger'

const EMPTY = {
  as_seller: [], as_buyer: [],
  incoming_requests: [], outgoing_requests: [],
  // Pending rows the backend cannot attribute to a sender (legacy / imported /
  // mirrored). Nobody may approve them — R3, see core/connection/service.py —
  // so they get their own bucket and a "re-send" affordance rather than an
  // Approve button that would 403.
  unclaimed_requests: [],
  counts: { accepted: 0, incoming: 0, outgoing: 0, unclaimed: 0 },
  total: 0,
}

export function useB2BConnections(authFetch, { onError, onSuccess } = {}) {
  const [data, setData] = useState(EMPTY)
  const [loading, setLoading] = useState(true)
  const [busyId, setBusyId] = useState(null)     // connection id mid-mutation

  // Keep the callbacks in refs so `load` stays referentially stable — otherwise
  // every parent re-render would re-fire the effect that calls it.
  const onErrorRef = useRef(onError)
  const onSuccessRef = useRef(onSuccess)
  useEffect(() => { onErrorRef.current = onError })
  useEffect(() => { onSuccessRef.current = onSuccess })

  const load = useCallback(async () => {
    setLoading(true)
    try {
      setData(await b2b.fetchConnections(authFetch))
    } catch (err) {
      logger.error('[B2B] failed to load connections', err)
      onErrorRef.current?.(err.message || 'Failed to load connections.')
      setData(EMPTY)
    } finally {
      setLoading(false)
    }
  }, [authFetch])

  useEffect(() => { load() }, [load])

  /** Run a mutation, surface the outcome, then resync. One code path for all
   *  five actions so success/error/busy handling can never drift between them. */
  const mutate = useCallback(async (id, fn, successMsg) => {
    setBusyId(id)
    try {
      const result = await fn()
      // A handler that already surfaced a warning owns the messaging — don't
      // paper over it with a success banner a beat later.
      if (successMsg && !result?._warned) onSuccessRef.current?.(successMsg)
      await load()
      return result
    } catch (err) {
      onErrorRef.current?.(err.message || 'Something went wrong.')
      return null
    } finally {
      setBusyId(null)
    }
  }, [load])

  /**
   * Look a BizID up before the user commits to sending. Returns the public
   * profile (name, type, `reachable`, `network_mode`) or null when it doesn't
   * exist. Never throws — this runs on keystroke-ish input, and a lookup failure
   * must not become an error banner.
   */
  const probe = useCallback(async (bizid) => {
    try {
      return await b2b.lookupBizId(authFetch, bizid)
    } catch {
      return undefined   // undefined = "couldn't check", distinct from null = "not found"
    }
  }, [authFetch])

  const sendRequest = useCallback((payload) => mutate(
    null,
    async () => {
      const result = await b2b.requestConnection(authFetch, payload)
      // The backend attaches `warning` when the target is a local-only install
      // that can't receive the request yet. Surface it verbatim rather than
      // claiming success the user won't get.
      if (result?.warning) {
        onErrorRef.current?.(result.warning)
        return { ...result, _warned: true }
      }
      return result
    },
    `Request sent to ${String(payload.bizid || '').toUpperCase()} — you'll be connected once they approve.`,
  ), [authFetch, mutate])

  const approve = useCallback((conn) => mutate(
    conn.id,
    () => b2b.approveConnection(authFetch, conn.id),
    `Connected with ${conn.counterparty_name || conn.requested_by_name || 'the business'}.`,
  ), [authFetch, mutate])

  const reject = useCallback((conn) => mutate(
    conn.id,
    () => b2b.rejectConnection(authFetch, conn.id),
    'Request declined.',
  ), [authFetch, mutate])

  const cancel = useCallback((conn) => mutate(
    conn.id,
    () => b2b.cancelConnectionRequest(authFetch, conn.id),
    'Request withdrawn.',
  ), [authFetch, mutate])

  const revoke = useCallback((conn) => mutate(
    conn.id,
    () => b2b.revokeConnection(authFetch, conn.id),
    'Connection revoked.',
  ), [authFetch, mutate])

  const savePolicy = useCallback((conn, policy) => mutate(
    conn.id,
    () => b2b.updateConnectionPolicy(authFetch, conn.id, policy),
    'Connection policy updated.',
  ), [authFetch, mutate])

  return {
    ...data,
    loading,
    busyId,
    reload: load,
    probe,
    sendRequest,
    approve,
    reject,
    cancel,
    revoke,
    savePolicy,
  }
}

export default useB2BConnections
