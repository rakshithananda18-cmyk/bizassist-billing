// ============================================================================
// PosLibs.test.js — unit tests for the logic extracted from Sales.jsx (§2.5):
// lib/posColumns, lib/posKeys, lib/priceOptions, lib/posInvoiceNumbers.
// ============================================================================
import { describe, it, expect } from 'vitest'
import { normalizeColumnOrder, moveColumn, getStickyLeftOffsets, DEFAULT_COLUMN_ORDER, colLabels } from '../lib/posColumns'
import { matchesKey, DEFAULT_FUNC_KEYS } from '../lib/posKeys'
import { getPriceOptions, withQty } from '../lib/priceOptions'
import { maxNumInSeries, nextInvoiceNo, syncTabNames } from '../lib/posInvoiceNumbers'

// ── posColumns ───────────────────────────────────────────────────────────────

describe('normalizeColumnOrder', () => {
  it('returns null for junk input', () => {
    expect(normalizeColumnOrder(null)).toBeNull()
    expect(normalizeColumnOrder([])).toBeNull()
    expect(normalizeColumnOrder('sku,name')).toBeNull()
  })

  it('migrates a v1 saved order missing the newer columns', () => {
    const legacy = ['sku', 'name', 'mrp', 'hsn', 'qty', 'unit', 'price', 'discount', 'tax', 'total']
    const out = normalizeColumnOrder(legacy)
    // batch inserted after name; price_option + serial after batch; rate after qty; attrs after serial
    expect(out.indexOf('batch')).toBe(out.indexOf('name') + 1)
    expect(out.indexOf('rate')).toBe(out.indexOf('qty') + 1)
    for (const col of ['batch', 'price_option', 'serial', 'rate', 'attrs']) {
      expect(out).toContain(col)
    }
    // no duplicates
    expect(new Set(out).size).toBe(out.length)
  })

  it('leaves a fully-migrated order untouched', () => {
    const full = [...DEFAULT_COLUMN_ORDER]
    expect(normalizeColumnOrder([...full])).toEqual(full)
  })

  it('every default column has a label', () => {
    for (const col of DEFAULT_COLUMN_ORDER) expect(colLabels[col]).toBeTruthy()
  })
})

describe('moveColumn', () => {
  it('swaps up/down and respects bounds', () => {
    const order = ['a', 'b', 'c']
    expect(moveColumn(order, 1, 'up')).toEqual(['b', 'a', 'c'])
    expect(moveColumn(order, 1, 'down')).toEqual(['a', 'c', 'b'])
    expect(moveColumn(order, 0, 'up')).toEqual(['a', 'b', 'c'])       // no-op at top
    expect(moveColumn(order, 2, 'down')).toEqual(['a', 'b', 'c'])     // no-op at bottom
    expect(order).toEqual(['a', 'b', 'c'])                            // input untouched
  })
})

describe('getStickyLeftOffsets', () => {
  const allVisible = { sku: true, mrp: true, hsn: true, unit: true, discount: true, tax: true, batch: true, price_option: true, rate: true }

  it('freezes sku then name with cumulative offsets', () => {
    const offsets = getStickyLeftOffsets(['sku', 'name', 'qty'], allVisible)
    expect(offsets).toEqual({ sku: 40, name: 135 })
  })

  it('stops freezing once a non-frozen column appears first', () => {
    const offsets = getStickyLeftOffsets(['qty', 'sku', 'name'], allVisible)
    expect(offsets).toEqual({})
  })

  it('skips hidden columns without breaking the freeze', () => {
    const offsets = getStickyLeftOffsets(['sku', 'name', 'qty'], { ...allVisible, sku: false })
    expect(offsets).toEqual({ name: 40 })
  })
})

// ── posKeys ──────────────────────────────────────────────────────────────────

describe('matchesKey', () => {
  const ev = (key, mods = {}) => ({ key, shiftKey: false, ctrlKey: false, altKey: false, ...mods })

  it('matches plain keys exactly', () => {
    expect(matchesKey(ev('F2'), 'F2')).toBe(true)
    expect(matchesKey(ev('F3'), 'F2')).toBe(false)
  })

  it('requires the exact modifier set', () => {
    expect(matchesKey(ev('Enter', { shiftKey: true }), 'Shift+Enter')).toBe(true)
    expect(matchesKey(ev('Enter'), 'Shift+Enter')).toBe(false)
    expect(matchesKey(ev('Enter', { shiftKey: true }), 'Enter')).toBe(false)   // extra modifier ≠ match
    expect(matchesKey(ev('s', { ctrlKey: true }), 'Ctrl+s')).toBe(true)
  })

  it('is false for empty descriptors', () => {
    expect(matchesKey(ev('Enter'), '')).toBe(false)
    expect(matchesKey(ev('Enter'), null)).toBe(false)
  })

  it('all default bindings are non-empty strings', () => {
    for (const v of Object.values(DEFAULT_FUNC_KEYS)) expect(typeof v).toBe('string')
  })
})

// ── priceOptions ─────────────────────────────────────────────────────────────

const PRODUCTS = [
  { id: 1, selling_price: 90, wholesale_price: 80, distributor_price: 70, mrp: 100 },
  { id: 2, selling_price: 50, wholesale_price: 0, distributor_price: null, mrp: 0 },
]

describe('getPriceOptions', () => {
  it('returns [] for custom/unknown items', () => {
    expect(getPriceOptions(null, PRODUCTS, {})).toEqual([])
    expect(getPriceOptions({ is_custom: true, product_id: 1 }, PRODUCTS, {})).toEqual([])
    expect(getPriceOptions({ product_id: 999 }, PRODUCTS, {})).toEqual([])
  })

  it('lists base tiers, drops zero/null prices, dedupes by value', () => {
    const opts = getPriceOptions({ product_id: 2 }, PRODUCTS, {})
    expect(opts).toHaveLength(1)
    expect(opts[0]).toMatchObject({ label: 'Standard Price', price: 50 })
  })

  it('appends batch prices latest-first and dedupes against base tiers', () => {
    const batches = {
      1: [
        { batch_no: 'OLD', selling_price: 85, mrp: 100, created_at: '2026-01-01' },
        { batch_no: 'NEW', selling_price: 95, mrp: 110, created_at: '2026-06-01' },
      ],
    }
    const opts = getPriceOptions({ product_id: 1 }, PRODUCTS, batches)
    const labels = opts.map(o => o.label)
    // base 90/80/70/100 kept; batch NEW (95, 110) before batch OLD (85); batch OLD mrp 100 deduped
    expect(labels.indexOf('Batch NEW Price')).toBeLessThan(labels.indexOf('Batch OLD Price'))
    expect(opts.map(o => o.price)).toEqual([90, 80, 70, 100, 95, 110, 85])
  })
})

describe('withQty (MRP-scheme overcharge bug)', () => {
  it('rescales the absolute scheme discount when qty changes', () => {
    // Chose ₹200 with MRP ₹230: discount = (230-200)×qty. At qty 4 the line
    // must bill ₹800, not ₹920 — the original overcharge bug.
    const products = [{ id: 7, mrp: 230 }]
    const item = { product_id: 7, qty: 1, price: 230, discount: 30, selected_price: 200 }
    const updated = withQty(item, 4, products)
    expect(updated.qty).toBe(4)
    expect(updated.price).toBe(230)
    expect(updated.price * 4 - updated.discount).toBe(800)
  })

  it('leaves custom-priced lines alone (price above MRP → no scheme)', () => {
    const products = [{ id: 7, mrp: 230 }]
    const item = { product_id: 7, qty: 1, price: 250, discount: 0, selected_price: 250 }
    const updated = withQty(item, 3, products)
    expect(updated.qty).toBe(3)
    expect(updated.price).toBe(250)
    expect(updated.discount).toBe(0)
  })

  it('only sets qty for lines without a product_id', () => {
    const updated = withQty({ product_id: '', qty: 1, price: 10, discount: 2 }, 5, [])
    expect(updated).toMatchObject({ qty: 5, price: 10, discount: 2 })
  })
})

// ── posInvoiceNumbers ────────────────────────────────────────────────────────

describe('maxNumInSeries / nextInvoiceNo', () => {
  const invoices = [
    { invoice_number: 'CTR1-0007' },
    { invoice_number: 'CTR1-0012' },
    { invoice_number: 'CTR2-0044' },   // other counter's series — must not leak
    { invoice_no: 'CTR1-0003' },       // legacy field name
  ]

  it('scopes the max to the given prefix', () => {
    expect(maxNumInSeries(invoices, 'CTR1-')).toBe(12)
    expect(maxNumInSeries(invoices, 'CTR2-')).toBe(44)
    expect(maxNumInSeries(invoices, 'ZZZ-')).toBe(0)
  })

  it('pads the next number to 4 digits', () => {
    expect(nextInvoiceNo(invoices, 'CTR1-')).toBe('CTR1-0013')
    expect(nextInvoiceNo([], 'CTR1-')).toBe('CTR1-0001')
  })
})

describe('syncTabNames', () => {
  const invoices = [{ invoice_number: 'CTR1-0005' }]

  it('renumbers placeholder tabs from the series and skips used numbers', () => {
    const tabs = [
      { id: '1', name: 'Invoice #1001', form: { items: [] } },
      { id: '2', name: 'Invoice #1002', form: { items: [] } },
    ]
    const out = syncTabNames(tabs, invoices, 'CTR1-')
    expect(out.map(t => t.name)).toEqual(['CTR1-0006', 'CTR1-0007'])
  })

  it('keeps a real name on a tab that has items', () => {
    const tabs = [{ id: '1', name: 'CTR1-0009', form: { items: [{ qty: 1 }] } }]
    const out = syncTabNames(tabs, invoices, 'CTR1-')
    expect(out[0].name).toBe('CTR1-0009')
  })

  it('renumbers an item-holding tab whose name collides with a committed invoice', () => {
    const tabs = [{ id: '1', name: 'CTR1-0005', form: { items: [{ qty: 1 }] } }]
    const out = syncTabNames(tabs, invoices, 'CTR1-')
    expect(out[0].name).toBe('CTR1-0006')
  })
})
