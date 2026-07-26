// ============================================================================
// components/b2b/useOrderCart.js — cart state + line maths for the Order desk.
// ----------------------------------------------------------------------------
// Deliberately separated from the ordering UI: the maths (line totals, GST
// split, order total) is the part that must be right, and it is the part worth
// testing without rendering anything. The desk component only renders what this
// returns.
// ============================================================================
import { useCallback, useMemo, useState } from 'react'

const r2 = (n) => Math.round((Number(n) || 0) * 100) / 100

/**
 * Pure line calculator — exported so it can be unit-tested directly.
 * Mirrors the backend's per-line computation in core/order/service.create_order:
 * tax is applied on the discounted (connection-priced) unit price × quantity.
 */
export function computeLine(product, quantity) {
  const qty = Number(quantity) || 0
  const unit = Number(product.selling_price) || 0
  const subtotal = r2(unit * qty)
  const cgst = r2(subtotal * ((Number(product.cgst_rate) || 0) / 100))
  const sgst = r2(subtotal * ((Number(product.sgst_rate) || 0) / 100))
  const igst = r2(subtotal * ((Number(product.igst_rate) || 0) / 100))
  return {
    ...product,
    quantity: qty,
    line_subtotal: subtotal,
    line_cgst: cgst,
    line_sgst: sgst,
    line_igst: igst,
    line_total: r2(subtotal + cgst + sgst + igst),
  }
}

/** Pure order roll-up over already-computed lines. */
export function computeTotals(lines) {
  const acc = lines.reduce((a, l) => ({
    subtotal: a.subtotal + l.line_subtotal,
    cgst: a.cgst + l.line_cgst,
    sgst: a.sgst + l.line_sgst,
    igst: a.igst + l.line_igst,
  }), { subtotal: 0, cgst: 0, sgst: 0, igst: 0 })

  const subtotal = r2(acc.subtotal)
  const cgst = r2(acc.cgst)
  const sgst = r2(acc.sgst)
  const igst = r2(acc.igst)
  return { subtotal, cgst, sgst, igst, tax: r2(cgst + sgst + igst), total: r2(subtotal + cgst + sgst + igst) }
}

export function useOrderCart(catalog) {
  const [quantities, setQuantities] = useState({})   // { product_id: qty }
  const [notes, setNotes] = useState('')

  const setQty = useCallback((productId, qty) => {
    setQuantities(prev => {
      const next = Math.max(0, Number(qty) || 0)
      if (next === 0) {
        const copy = { ...prev }
        delete copy[productId]
        return copy
      }
      return { ...prev, [productId]: next }
    })
  }, [])

  const bump = useCallback((productId, delta) => {
    setQuantities(prev => {
      const next = Math.max(0, (prev[productId] || 0) + delta)
      if (next === 0) {
        const copy = { ...prev }
        delete copy[productId]
        return copy
      }
      return { ...prev, [productId]: next }
    })
  }, [])

  const clear = useCallback(() => { setQuantities({}); setNotes('') }, [])

  const lines = useMemo(() => {
    const byId = new Map(catalog.map(p => [p.product_id, p]))
    return Object.entries(quantities)
      .map(([id, qty]) => {
        const product = byId.get(Number(id))
        return product ? computeLine(product, qty) : null
      })
      .filter(Boolean)
  }, [catalog, quantities])

  const totals = useMemo(() => computeTotals(lines), [lines])

  return {
    quantities, setQty, bump, clear,
    notes, setNotes,
    lines, totals,
    itemCount: lines.length,
    unitCount: lines.reduce((s, l) => s + l.quantity, 0),
    isEmpty: lines.length === 0,
  }
}

export default useOrderCart
