// ============================================================================
// lib/priceOptions.js — POS pricing-tier resolution (split from Sales.jsx, §2.5)
// ----------------------------------------------------------------------------
// Pure functions over (item, products, productBatches). This is the most
// bug-prone POS money logic (the qty-rescale overcharge bug lived here), so it
// is extracted and unit-tested. The page binds current state via thin wrappers.
// ============================================================================
import { schemeDiscount } from '../utils/invoiceMath'

/**
 * All selectable price tiers for a cart line: base product prices first, then
 * batch prices (latest batch first), deduped by numeric value, zeros dropped.
 */
export function getPriceOptions(item, products, productBatches) {
  if (!item || item.is_custom || !item.product_id) return []
  const p = products.find(prod => prod.id === item.product_id)
  if (!p) return []

  const rawOptions = []

  // Base standard prices first
  rawOptions.push(
    { label: 'Standard Price', price: p.selling_price, created_at: null, formatted_date: 'Base Product' },
    { label: 'Wholesale Price', price: p.wholesale_price, created_at: null, formatted_date: 'Base Product' },
    { label: 'Distributor Price', price: p.distributor_price, created_at: null, formatted_date: 'Base Product' },
    { label: 'MRP', price: p.mrp, created_at: null, formatted_date: 'Base Product' }
  )

  // Gather batches and sort them by created_at descending (latest first)
  const batches = productBatches[item.product_id] || []
  const sortedBatches = [...batches].sort((a, b) => {
    const dateA = a.created_at ? new Date(a.created_at) : new Date(0)
    const dateB = b.created_at ? new Date(b.created_at) : new Date(0)
    return dateB - dateA
  })

  sortedBatches.forEach(b => {
    if (b.selling_price && b.selling_price > 0) {
      rawOptions.push({
        label: `Batch ${b.batch_no || '—'} Price`,
        price: b.selling_price,
        created_at: b.created_at,
        formatted_date: b.created_at ? new Date(b.created_at).toLocaleDateString('en-GB') : '—'
      })
    }
    if (b.mrp && b.mrp > 0) {
      rawOptions.push({
        label: `Batch ${b.batch_no || '—'} MRP`,
        price: b.mrp,
        created_at: b.created_at,
        formatted_date: b.created_at ? new Date(b.created_at).toLocaleDateString('en-GB') : '—'
      })
    }
  })

  const seen = new Set()
  const options = []
  rawOptions.forEach(opt => {
    const val = parseFloat(opt.price)
    if (val && val > 0 && !seen.has(val)) {
      seen.add(val)
      options.push({
        label: opt.label,
        price: val,
        created_at: opt.created_at,
        formatted_date: opt.formatted_date
      })
    }
  })

  return options
}

/**
 * withQty — return a copy of `item` with qty set and the MRP-scheme discount
 * rescaled to the new qty.
 *
 * The discount is stored as an absolute amount = (MRP − chosen price) × qty,
 * so it MUST rescale when qty changes — otherwise the line bills toward MRP
 * (the overcharge bug: chose ₹200 at qty 1, raised to qty 4, was billing ₹920
 * instead of ₹800). EVERY qty-change path (typing, +, arrow keys) must go
 * through this. Only applies while the line is in scheme mode (a chosen price
 * at/below MRP); a custom-typed price gets qty alone changed.
 */
export function withQty(item, newQty, products) {
  const updated = { ...item, qty: newQty }
  if (updated.product_id) {
    const p = products.find(prod => prod.id === updated.product_id)
    const mrp = p ? (parseFloat(p.mrp) || 0) : (parseFloat(updated.mrp) || 0)
    const selPrice = parseFloat(updated.selected_price) || 0

    if (mrp > 0 && selPrice <= mrp) {
      updated.price = mrp
      updated.discount = schemeDiscount(mrp, selPrice, newQty)
    } else {
      updated.price = selPrice
      updated.discount = 0
    }
  }
  return updated
}
