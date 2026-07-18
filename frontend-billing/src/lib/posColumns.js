// ============================================================================
// lib/posColumns.js — POS cart column model (split from Sales.jsx, §2.5)
// ----------------------------------------------------------------------------
// Pure helpers for the cart table's column order: labels, default order, the
// saved-order migration (older saves predate batch/serial/rate/attrs columns),
// reordering, and sticky-offset computation. No React, no localStorage — the
// page owns persistence; these are unit-testable functions.
// ============================================================================

export const colLabels = {
  sku: 'Item Code',
  name: 'Item Name',
  batch: 'Batch',
  serial: 'Serial / IMEI',
  attrs: 'Item Details (Size/Color/Warranty…)',
  price_option: 'Price Option',
  mrp: 'MRP',
  hsn: 'HSN',
  qty: 'Quantity',
  unit: 'Unit',
  rate: 'Price Per Unit Before Tax',
  price: 'Total Before Tax',
  discount: 'Discount',
  tax: 'Tax',
  total: 'Total After Tax'
}

export const DEFAULT_COLUMN_ORDER = [
  'sku', 'name', 'batch', 'serial', 'attrs', 'price_option', 'mrp', 'hsn',
  'qty', 'unit', 'rate', 'price', 'discount', 'tax', 'total'
]

/**
 * Migrate a saved column order from an older app version by inserting any
 * columns that didn't exist when it was saved. Returns the (mutated) array,
 * or null when the input isn't a usable saved order.
 * Insertion rules mirror the original Sales.jsx logic exactly:
 *   batch → after name · price_option → after batch · serial → after batch ·
 *   rate → after qty · attrs → after serial (else appended).
 */
export function normalizeColumnOrder(parsed) {
  if (!Array.isArray(parsed) || parsed.length === 0) return null
  if (!parsed.includes('batch')) {
    const nameIdx = parsed.indexOf('name')
    if (nameIdx !== -1) {
      parsed.splice(nameIdx + 1, 0, 'batch')
    } else {
      parsed.push('batch')
    }
  }
  if (!parsed.includes('price_option')) {
    const batchIdx = parsed.indexOf('batch')
    if (batchIdx !== -1) {
      parsed.splice(batchIdx + 1, 0, 'price_option')
    } else {
      parsed.push('price_option')
    }
  }
  if (!parsed.includes('serial')) {
    const batchIdx = parsed.indexOf('batch')
    if (batchIdx !== -1) {
      parsed.splice(batchIdx + 1, 0, 'serial')
    } else {
      parsed.push('serial')
    }
  }
  if (!parsed.includes('rate')) {
    const qtyIdx = parsed.indexOf('qty')
    if (qtyIdx !== -1) {
      parsed.splice(qtyIdx + 1, 0, 'rate')
    } else {
      parsed.push('rate')
    }
  }
  if (!parsed.includes('attrs')) {
    const serialIdx = parsed.indexOf('serial')
    if (serialIdx !== -1) {
      parsed.splice(serialIdx + 1, 0, 'attrs')
    } else {
      parsed.push('attrs')
    }
  }
  return parsed
}

/** Swap a column one slot up/down. Returns a NEW array (input untouched). */
export function moveColumn(order, index, direction) {
  const nextOrder = [...order]
  if (direction === 'up' && index > 0) {
    const temp = nextOrder[index - 1]
    nextOrder[index - 1] = nextOrder[index]
    nextOrder[index] = temp
  } else if (direction === 'down' && index < nextOrder.length - 1) {
    const temp = nextOrder[index + 1]
    nextOrder[index + 1] = nextOrder[index]
    nextOrder[index] = temp
  }
  return nextOrder
}

/**
 * Sticky-left pixel offsets for the frozen sku/name columns. Freezing stops at
 * the first visible column that isn't sku/name (matches original behavior).
 */
export function getStickyLeftOffsets(order, visibleObj) {
  const offsets = {}
  let currentOffset = 40
  let freezeAllowed = true

  for (let i = 0; i < order.length; i++) {
    const col = order[i]
    const isVisible = col === 'sku' ? visibleObj.sku :
                      col === 'mrp' ? visibleObj.mrp :
                      col === 'hsn' ? visibleObj.hsn :
                      col === 'unit' ? visibleObj.unit :
                      col === 'discount' ? visibleObj.discount :
                      col === 'tax' ? visibleObj.tax :
                      col === 'batch' ? visibleObj.batch :
                      col === 'price_option' ? visibleObj.price_option :
                      col === 'rate' ? visibleObj.rate :
                      true

    if (!isVisible) continue

    if (freezeAllowed && (col === 'sku' || col === 'name')) {
      offsets[col] = currentOffset
      if (col === 'sku') {
        currentOffset += 95
      } else if (col === 'name') {
        currentOffset += 180
      }
    } else {
      freezeAllowed = false
    }
  }
  return offsets
}
