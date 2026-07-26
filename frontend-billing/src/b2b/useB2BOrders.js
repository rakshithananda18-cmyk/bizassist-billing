// ============================================================================
// b2b/useB2BOrders.js
// ----------------------------------------------------------------------------
// One order queue, parameterised by direction:
//
//   useB2BOrders(authFetch, { direction: 'incoming' })  → orders placed WITH me
//   useB2BOrders(authFetch, { direction: 'outgoing' })  → orders I placed
//
// Incoming and outgoing differ only in which business is the counterparty and
// which status transitions are offered, so they share this hook rather than two
// near-identical copies (the old page duplicated the fetch/filter/sort logic).
//
// Search / status-filter / sort live here too, so the table component stays a
// pure renderer.
// ============================================================================
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import * as b2b from './b2bClient'
import { logger } from '../utils/logger'

const ROLE_FOR = { incoming: 'seller', outgoing: 'buyer' }

/** Field used for the counterparty column, by direction. */
export const counterpartyOf = (order, direction) =>
  direction === 'incoming'
    ? { name: order.buyer_name, bizid: order.buyer_bizid }
    : { name: order.seller_name, bizid: order.seller_bizid }

export function useB2BOrders(authFetch, { direction, onError } = {}) {
  const [orders, setOrders] = useState([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(true)
  const [search, setSearch] = useState('')
  const [statusFilter, setStatusFilter] = useState('')
  const [sort, setSort] = useState({ key: '', direction: '' })

  const onErrorRef = useRef(onError)
  useEffect(() => { onErrorRef.current = onError })

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const { items, total: t } = await b2b.fetchOrders(authFetch, { role: ROLE_FOR[direction] })
      setOrders(items)
      setTotal(t)
    } catch (err) {
      logger.error('[B2B] failed to load orders', err)
      onErrorRef.current?.(err.message || 'Failed to load orders.')
      setOrders([])
      setTotal(0)
    } finally {
      setLoading(false)
    }
  }, [authFetch, direction])

  useEffect(() => { load() }, [load])

  const changeStatus = useCallback(async (orderId, status) => {
    try {
      const updated = await b2b.updateOrderStatus(authFetch, orderId, status)
      // Patch in place first so the row updates instantly, then resync in the
      // background — the seller's transition also mutates stock and invoices.
      setOrders(prev => prev.map(o => (o.id === orderId ? { ...o, ...updated } : o)))
      load()
      return updated
    } catch (err) {
      onErrorRef.current?.(err.message || 'Failed to update the order status.')
      return null
    }
  }, [authFetch, load])

  /** Toggle sort: asc → desc → off. */
  const toggleSort = useCallback((key) => {
    setSort(prev => {
      if (prev.key !== key) return { key, direction: 'asc' }
      if (prev.direction === 'asc') return { key, direction: 'desc' }
      return { key: '', direction: '' }
    })
  }, [])

  const visible = useMemo(() => {
    const q = search.trim().toLowerCase()
    let items = orders.filter(o => {
      if (statusFilter && o.status !== statusFilter) return false
      if (!q) return true
      const cp = counterpartyOf(o, direction)
      return (
        o.order_number?.toLowerCase().includes(q) ||
        cp.name?.toLowerCase().includes(q) ||
        cp.bizid?.toLowerCase().includes(q)
      )
    })

    if (sort.key && sort.direction) {
      const pick = (o) => {
        if (sort.key === 'party') return counterpartyOf(o, direction).name || ''
        if (sort.key === 'date') return o.created_at || o.order_date || ''
        if (sort.key === 'taxes') return (o.cgst_total || 0) + (o.sgst_total || 0) + (o.igst_total || 0)
        return o[sort.key]
      }
      items = [...items].sort((a, b) => {
        const av = pick(a); const bv = pick(b)
        if (av == null) return 1
        if (bv == null) return -1
        const cmp = typeof av === 'string' ? av.localeCompare(bv) : av - bv
        return sort.direction === 'asc' ? cmp : -cmp
      })
    }
    return items
  }, [orders, search, statusFilter, sort, direction])

  /** Small headline numbers for the tab's summary strip. */
  const stats = useMemo(() => {
    const open = orders.filter(o => !['completed', 'cancelled', 'rejected'].includes(o.status))
    return {
      count: orders.length,
      open: open.length,
      openValue: open.reduce((s, o) => s + (o.total_amount || 0), 0),
      awaitingMe: orders.filter(o => o.status === 'pending').length,
    }
  }, [orders])

  return {
    orders, visible, total, loading, stats,
    search, setSearch,
    statusFilter, setStatusFilter,
    sort, toggleSort,
    reload: load,
    changeStatus,
  }
}

export default useB2BOrders
