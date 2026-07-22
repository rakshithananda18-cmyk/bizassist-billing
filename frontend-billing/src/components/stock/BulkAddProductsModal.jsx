// components/stock/BulkAddProductsModal.jsx — Smart dual-mode product manager.
// =============================================================================
// Mode A — "Add Products":  spreadsheet-style table for adding many new products
//   at once. Each row has the core fields visible; More ▾ reveals full details
//   matching the Edit Product form (all prices, tax, codes, category, brand).
//   Duplicate detection (name / SKU / barcode) flags rows before save.
//   A new blank row appears automatically as you type in the last row.
//
// Mode B — "Update Stock":  batch stock-in / stock-out for EXISTING products.
//   A searchable product picker populates rows with the current stock.
//   Each row takes qty + movement type + reason and saves independently via
//   POST /billing/products/{id}/stock/adjustment.
//
// Both modes save row-by-row and show per-row status (saving / ✓ / error).
// =============================================================================
import React, { useState, useEffect, useRef } from 'react'
import { useAuth } from '../../contexts/AuthContext'
import { CloseIcon, PlusIcon, InventoryIcon, SearchIcon, SyncIcon } from '../Icons'

// ─────────────────────────── constants / helpers ─────────────────────────────

const BLANK_ADD_ROW = () => ({
  name: '', sku: '', barcode: '', category: '', unit: 'pcs',
  hsn_sac: '', brand: '', description: '',
  selling_price: '', wholesale_price: '', distributor_price: '',
  cost_price: '', mrp: '',
  cgst_rate: '', sgst_rate: '',
  opening_stock: '', min_stock: '',
  _status: null, _open: false, _key: Math.random(),
})

const BLANK_STOCK_ROW = (product = null) => ({
  product_id: product?.id ?? '',
  product_name: product?.name ?? '',
  product_unit: product?.unit ?? 'pcs',
  current_stock: product ? (product.stock_qty ?? product.quantity ?? 0) : '',
  movement_type: 'stock_in',
  quantity: '',
  reason: '',
  reference: '',
  _status: null, _key: Math.random(),
})

const num   = (v) => (v === '' || v == null ? 0 : parseFloat(v) || 0)
const numNull = (v) => (v === '' || v == null ? null : parseFloat(v) || 0)

// Pill-style tab button
function Tab({ active, onClick, children }) {
  return (
    <button
      type="button"
      onClick={onClick}
      style={{
        padding: '6px 18px',
        borderRadius: 20,
        border: 'none',
        cursor: 'pointer',
        fontWeight: 700,
        fontSize: '0.8rem',
        background: active ? 'var(--accent)' : 'transparent',
        color: active ? '#fff' : 'var(--text-muted)',
        transition: 'all 0.15s',
      }}
    >
      {children}
    </button>
  )
}

// Tiny label above an input in the "More ▾" panel
function MLabel({ children }) {
  return (
    <div style={{ fontSize: '0.67rem', fontWeight: 700, textTransform: 'uppercase',
      letterSpacing: '0.05em', color: 'var(--text-muted)', marginBottom: 3 }}>
      {children}
    </div>
  )
}

// ─────────────────────────── main component ─────────────────────────────────

export default function BulkAddProductsModal({ open, onClose, onSaved, existingProducts = [] }) {
  const auth = useAuth()
  const authFetch = auth?.authFetch
  const settings = auth?.settings
  const inv = settings?.inventory || {}
  const showWholesale = inv.wholesale_price !== false
  const showMrp = inv.mrp_enabled !== false

  // mode: 'add' | 'stock'
  const [mode, setMode] = useState('add')

  // ── Add-mode state ──────────────────────────────────────────
  const [addRows, setAddRows] = useState([BLANK_ADD_ROW()])
  const [addSaving, setAddSaving] = useState(false)
  const [addSummary, setAddSummary] = useState(null)

  // ── Stock-update mode state ──────────────────────────────────
  const [stockRows, setStockRows] = useState([BLANK_STOCK_ROW()])
  const [stockSaving, setStockSaving] = useState(false)
  const [stockSummary, setStockSummary] = useState(null)
  const [productSearch, setProductSearch] = useState('')
  const [showProductDropdown, setShowProductDropdown] = useState(false)
  const [activeStockRowIdx, setActiveStockRowIdx] = useState(null)
  const searchRef = useRef(null)

  // Reset on open
  useEffect(() => {
    if (open) {
      setMode('add')
      setAddRows([BLANK_ADD_ROW()])
      setAddSummary(null)
      setStockRows([BLANK_STOCK_ROW()])
      setStockSummary(null)
      setProductSearch('')
    }
  }, [open])

  if (!open) return null

  // ── Duplicate detection for Add-mode ─────────────────────────
  const existingNames    = new Set(existingProducts.map(p => (p.name  || '').trim().toLowerCase()).filter(Boolean))
  const existingSkus     = new Set(existingProducts.map(p => (p.sku   || '').trim().toLowerCase()).filter(Boolean))
  const existingBarcodes = new Set(existingProducts.map(p => (p.barcode || '').trim()).filter(Boolean))

  const dupReason = (r) => {
    if (r.name.trim()    && existingNames.has(r.name.trim().toLowerCase()))    return 'name already exists'
    if (r.sku.trim()     && existingSkus.has(r.sku.trim().toLowerCase()))      return 'SKU already exists'
    if (r.barcode.trim() && existingBarcodes.has(r.barcode.trim()))            return 'barcode already exists'
    return null
  }

  // ─────────────────────── ADD MODE ───────────────────────────

  const setAddCell = (i, key, val) => {
    setAddRows(prev => {
      const next = prev.map((r, idx) => idx === i ? { ...r, [key]: val, _status: null } : r)
      // auto-append blank row when typing in the last row's name
      if (i === prev.length - 1 && key === 'name' && val !== '') next.push(BLANK_ADD_ROW())
      return next
    })
  }

  const toggleAddOpen = (i) => setAddRows(prev => prev.map((r, idx) => idx === i ? { ...r, _open: !r._open } : r))
  const removeAddRow  = (i) => setAddRows(prev => prev.filter((_, idx) => idx !== i))

  const addRowsReady = addRows.filter(r => r.name.trim() && !dupReason(r) && r._status !== 'ok')

  const saveAddAll = async () => {
    if (addRowsReady.length === 0) return
    setAddSaving(true); setAddSummary(null)
    let ok = 0, failed = 0
    const next = [...addRows]
    for (let i = 0; i < next.length; i++) {
      const r = next[i]
      if (!r.name.trim() || r._status === 'ok') continue
      const dup = dupReason(r)
      if (dup) { next[i] = { ...r, _status: `skipped — ${dup}` }; setAddRows([...next]); continue }
      next[i] = { ...r, _status: 'saving' }; setAddRows([...next])
      try {
        const res = await authFetch('/billing/products', {
          method: 'POST',
          body: JSON.stringify({
            name: r.name.trim(),
            description: r.description || null,
            brand: r.brand || null,
            sku: r.sku || null,
            barcode: r.barcode || null,
            category: r.category || null,
            unit: r.unit || 'pcs',
            hsn_sac: r.hsn_sac || null,
            selling_price:     num(r.selling_price),
            wholesale_price:   num(r.wholesale_price),
            distributor_price: num(r.distributor_price),
            cost_price:        num(r.cost_price),
            mrp:               numNull(r.mrp),
            cgst_rate:         num(r.cgst_rate),
            sgst_rate:         num(r.sgst_rate),
            opening_stock:     num(r.opening_stock),
            min_stock:         num(r.min_stock),
            attributes: {},
          }),
        })
        if (res.ok) {
          next[i] = { ...next[i], _status: 'ok', _open: false }; ok++
        } else {
          const err = await res.json().catch(() => ({}))
          next[i] = { ...next[i], _status: err.detail || `HTTP ${res.status}` }; failed++
        }
      } catch {
        next[i] = { ...next[i], _status: 'network error' }; failed++
      }
      setAddRows([...next])
    }
    setAddSaving(false)
    setAddSummary({ ok, failed })
    if (failed === 0 && ok > 0) onSaved?.(ok)
  }

  // ─────────────────────── STOCK UPDATE MODE ──────────────────

  const setStockCell = (i, key, val) => {
    setStockRows(prev => prev.map((r, idx) => idx === i ? { ...r, [key]: val, _status: null } : r))
  }

  const removeStockRow = (i) => setStockRows(prev => prev.filter((_, idx) => idx !== i))

  const pickProduct = (product, rowIdx) => {
    // If rowIdx is null — adding from the product search bar at the bottom
    if (rowIdx === null) {
      // Check if already in the list
      if (stockRows.some(r => r.product_id === product.id)) {
        setProductSearch(''); setShowProductDropdown(false); return
      }
      setStockRows(prev => {
        // Replace last blank row or append
        const lastBlank = prev.findLastIndex(r => !r.product_id)
        if (lastBlank >= 0) {
          const next = [...prev]
          next[lastBlank] = BLANK_STOCK_ROW(product)
          return next
        }
        return [...prev, BLANK_STOCK_ROW(product)]
      })
    } else {
      setStockRows(prev => prev.map((r, idx) => idx === rowIdx ? BLANK_STOCK_ROW(product) : r))
    }
    setProductSearch(''); setShowProductDropdown(false); setActiveStockRowIdx(null)
  }

  const filteredProducts = existingProducts.filter(p => {
    if (!productSearch.trim()) return true
    const q = productSearch.toLowerCase()
    return p.name?.toLowerCase().includes(q) || p.sku?.toLowerCase().includes(q) || p.barcode?.includes(q)
  }).slice(0, 12)

  const stockRowsReady = stockRows.filter(r => r.product_id && r.quantity && num(r.quantity) > 0 && r.reason.trim() && r._status !== 'ok')

  const saveStockAll = async () => {
    if (stockRowsReady.length === 0) return
    setStockSaving(true); setStockSummary(null)
    let ok = 0, failed = 0
    const next = [...stockRows]
    for (let i = 0; i < next.length; i++) {
      const r = next[i]
      if (!r.product_id || !r.quantity || num(r.quantity) <= 0 || !r.reason.trim() || r._status === 'ok') continue
      next[i] = { ...r, _status: 'saving' }; setStockRows([...next])
      try {
        const delta = r.movement_type === 'stock_out' ? -num(r.quantity) : num(r.quantity)
        const noteParts = [r.reason.trim()]
        if (r.reference) noteParts.push(`ref: ${r.reference}`)
        const res = await authFetch(`/billing/products/${r.product_id}/stock/adjustment`, {
          method: 'POST',
          body: JSON.stringify({ qty_delta: delta, note: noteParts.join(' — ') }),
        })
        if (res.ok) {
          const data = await res.json().catch(() => ({}))
          const newQty = data.new_qty ?? data.stock_qty ?? (num(r.current_stock) + delta)
          next[i] = { ...next[i], _status: 'ok', current_stock: newQty }; ok++
        } else {
          const err = await res.json().catch(() => ({}))
          next[i] = { ...next[i], _status: err.detail || `HTTP ${res.status}` }; failed++
        }
      } catch {
        next[i] = { ...next[i], _status: 'network error' }; failed++
      }
      setStockRows([...next])
    }
    setStockSaving(false)
    setStockSummary({ ok, failed })
    if (ok > 0) onSaved?.(ok)
  }

  // ─────────────────────── INLINE INPUT HELPERS ───────────────

  const addInput = (r, i, key, opts = {}) => (
    <input
      className="form-input"
      style={{
        width: '100%', height: 34, padding: '4px 9px',
        fontSize: '0.79rem',
        textAlign: opts.num ? 'right' : 'left',
        fontFamily: opts.mono ? "'Geist Mono',monospace" : undefined,
        ...opts.style,
      }}
      type={opts.num ? 'number' : 'text'}
      inputMode={opts.num ? 'decimal' : undefined}
      min={opts.num ? 0 : undefined}
      step={opts.num ? 'any' : undefined}
      placeholder={opts.placeholder || ''}
      value={r[key]}
      disabled={r._status === 'ok' || addSaving}
      onChange={e => setAddCell(i, key, e.target.value)}
    />
  )

  const stockInput = (r, i, key, opts = {}) => (
    <input
      className="form-input"
      style={{
        width: '100%', height: 34, padding: '4px 9px',
        fontSize: '0.79rem',
        textAlign: opts.num ? 'right' : 'left',
        ...opts.style,
      }}
      type={opts.num ? 'number' : 'text'}
      inputMode={opts.num ? 'decimal' : undefined}
      min={opts.num ? 0 : undefined}
      step={opts.num ? 'any' : undefined}
      placeholder={opts.placeholder || ''}
      value={r[key]}
      disabled={r._status === 'ok' || stockSaving}
      onChange={e => setStockCell(i, key, e.target.value)}
    />
  )

  const statusChip = (status) => {
    if (status === 'ok')     return <span style={{ color: '#22c55e', fontWeight: 700, fontSize: '0.74rem' }}>✓ saved</span>
    if (status === 'saving') return <span style={{ color: 'var(--text-muted)', fontSize: '0.74rem' }}>saving…</span>
    if (status)              return <span style={{ color: '#ef4444', fontSize: '0.72rem' }} title={status}>{String(status).slice(0, 42)}</span>
    return null
  }

  const hdr = (text, align = 'left') => (
    <span style={{ textAlign: align, display: 'block', fontSize: '0.66rem', fontWeight: 800,
      textTransform: 'uppercase', letterSpacing: '0.05em', color: 'var(--text-muted)' }}>
      {text}
    </span>
  )

  // ─────────────────────── RENDER ─────────────────────────────

  return (
    <div
      className="modal-overlay"
      style={{ zIndex: 3000 }}
      onClick={e => e.target === e.currentTarget && !addSaving && !stockSaving && onClose()}
    >
      <div
        className="modal"
        style={{
          maxWidth: mode === 'add' ? 980 : 860,
          width: '97%',
          maxHeight: '92vh',
          display: 'flex',
          flexDirection: 'column',
          transition: 'max-width 0.2s',
        }}
      >
        {/* ── Header ── */}
        <div className="modal-header" style={{ flexShrink: 0 }}>
          <span className="modal-title" style={{ display: 'inline-flex', alignItems: 'center', gap: 8 }}>
            <InventoryIcon size={16} />
            <span>Manage Products</span>
          </span>

          {/* mode toggle */}
          <div style={{ display: 'flex', gap: 4, background: 'var(--bg-2, rgba(0,0,0,.05))', borderRadius: 22, padding: 3, marginLeft: 12 }}>
            <Tab active={mode === 'add'}   onClick={() => setMode('add')}>
              ＋ Add Products
            </Tab>
            <Tab active={mode === 'stock'} onClick={() => setMode('stock')}>
              ↕ Update Stock
            </Tab>
          </div>

          <div style={{ flex: 1 }} />
          <button className="btn btn-ghost btn-icon" onClick={onClose} aria-label="Close">
            <CloseIcon size={16} />
          </button>
        </div>

        {/* ──────────────────── ADD PRODUCTS MODE ──────────────────── */}
        {mode === 'add' && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 10, padding: '10px 18px 16px', flex: 1, minHeight: 0 }}>
            <div style={{ fontSize: '0.76rem', color: 'var(--text-muted)', flexShrink: 0 }}>
              One row per new product — only <b>Name</b> is required. <b>More ▾</b> reveals prices, tax, codes.
              A new row appears automatically as you type. Existing products are flagged.
            </div>

            {/* Header row */}
            <div style={{
              display: 'grid',
              gridTemplateColumns: showMrp ? '2.4fr 1.3fr 0.85fr 0.85fr 0.7fr 0.55fr 100px 24px 22px' : '2.4fr 1.3fr 0.85fr 0.7fr 0.55fr 100px 24px 22px',
              gap: 8, padding: '0 4px', flexShrink: 0,
            }}>
              {hdr('Product name *')}
              {hdr('Barcode')}
              {hdr('Retail ₹', 'right')}
              {showMrp && hdr('MRP ₹', 'right')}
              {hdr('Stock')}
              {hdr('Unit')}
              {hdr('Status')}
              <span />
              <span />
            </div>

            {/* Rows */}
            <div style={{ overflowY: 'auto', flex: 1, minHeight: 0, display: 'flex', flexDirection: 'column', gap: 6 }}>
              {addRows.map((r, i) => {
                const dup = r.name.trim() ? dupReason(r) : null
                return (
                  <div
                    key={r._key}
                    style={{
                      border: `1px solid ${r._status === 'ok' ? '#22c55e40' : dup ? '#eab30840' : 'var(--border)'}`,
                      borderRadius: 8, padding: '6px 8px',
                      opacity: r._status === 'ok' ? 0.6 : 1,
                      background: r._open ? 'var(--bg-2, rgba(0,0,0,.02))' : 'transparent',
                      transition: 'border-color 0.15s',
                    }}
                  >
                    {/* Main row */}
                    <div style={{ display: 'grid', gridTemplateColumns: showMrp ? '2.4fr 1.3fr 0.85fr 0.85fr 0.7fr 0.55fr 100px 24px 22px' : '2.4fr 1.3fr 0.85fr 0.7fr 0.55fr 100px 24px 22px', gap: 8, alignItems: 'center' }}>
                      {addInput(r, i, 'name', { placeholder: 'e.g. Sunflower Oil 15L' })}
                      {addInput(r, i, 'barcode', { placeholder: 'scan / type', mono: true })}
                      {addInput(r, i, 'selling_price', { num: true })}
                      {showMrp && addInput(r, i, 'mrp', { num: true })}
                      {addInput(r, i, 'opening_stock', { num: true, placeholder: '0' })}
                      {addInput(r, i, 'unit', { placeholder: 'pcs' })}

                      {/* Status chip */}
                      <span style={{ fontSize: '0.68rem', lineHeight: 1.25 }}>
                        {r._status === 'ok' && <span style={{ color: '#22c55e', fontWeight: 700 }}>✓ added</span>}
                        {r._status === 'saving' && <span style={{ color: 'var(--text-muted)' }}>saving…</span>}
                        {!r._status && dup && (
                          <span style={{ color: '#eab308', fontWeight: 600 }}
                            title={`${dup} — will be skipped. Edit the name/SKU/barcode or use Update Stock mode.`}>
                            ⚠ exists
                          </span>
                        )}
                        {r._status && r._status !== 'ok' && r._status !== 'saving' && (
                          <span style={{ color: '#ef4444' }} title={r._status}>{String(r._status).slice(0, 36)}</span>
                        )}
                      </span>

                      {/* More toggle */}
                      <button
                        type="button"
                        onClick={() => toggleAddOpen(i)}
                        title="More fields: wholesale/distributor price, tax, SKU, brand, category"
                        style={{
                          background: 'transparent', border: 'none', cursor: 'pointer',
                          color: r._open ? 'var(--accent)' : 'var(--text-muted)',
                          fontSize: '0.78rem', fontWeight: 700, padding: 2,
                        }}
                      >{r._open ? '▴' : '▾'}</button>

                      {/* Remove row */}
                      {addRows.length > 1 && (
                        <button
                          type="button"
                          onClick={() => removeAddRow(i)}
                          disabled={addSaving}
                          style={{
                            background: 'transparent', border: 'none', cursor: 'pointer',
                            color: 'var(--text-muted)', fontSize: '0.9rem', padding: 0, lineHeight: 1,
                          }}
                          title="Remove this row"
                        >×</button>
                      )}
                    </div>

                    {/* Expanded extra fields */}
                    {r._open && (
                      <div style={{ marginTop: 10, paddingTop: 10, borderTop: '1px dashed var(--border)' }}>
                        {/* Pricing */}
                        <div style={{ fontSize: '0.66rem', fontWeight: 800, textTransform: 'uppercase',
                          letterSpacing: '0.06em', color: 'var(--text-muted)', marginBottom: 6 }}>
                          Pricing
                        </div>
                        <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', marginBottom: 10 }}>
                          {[
                            ...(showWholesale ? [['Wholesale ₹', 'wholesale_price']] : []),
                            ['Distributor ₹', 'distributor_price'],
                            ['Cost ₹', 'cost_price'],
                            ['Min Stock', 'min_stock'],
                          ].map(([label, key]) => (
                            <div key={key} style={{ flex: 1, minWidth: 110 }}>
                              <MLabel>{label}</MLabel>
                              {addInput(r, i, key, { num: true })}
                            </div>
                          ))}
                        </div>

                        {/* Tax */}
                        <div style={{ fontSize: '0.66rem', fontWeight: 800, textTransform: 'uppercase',
                          letterSpacing: '0.06em', color: 'var(--text-muted)', marginBottom: 6 }}>
                          Tax (GST)
                        </div>
                        <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', marginBottom: 10 }}>
                          {[
                            ['HSN / SAC', 'hsn_sac', {}],
                            ['CGST %', 'cgst_rate', { num: true }],
                            ['SGST %', 'sgst_rate', { num: true }],
                          ].map(([label, key, opts]) => (
                            <div key={key} style={{ flex: 1, minWidth: 100 }}>
                              <MLabel>{label}</MLabel>
                              {addInput(r, i, key, opts)}
                            </div>
                          ))}
                        </div>

                        {/* Codes & Meta */}
                        <div style={{ fontSize: '0.66rem', fontWeight: 800, textTransform: 'uppercase',
                          letterSpacing: '0.06em', color: 'var(--text-muted)', marginBottom: 6 }}>
                          Codes & Details
                        </div>
                        <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
                          {[
                            ['SKU / Item code', 'sku', {}],
                            ['Brand', 'brand', {}],
                            ['Category', 'category', { placeholder: 'e.g. Oils' }],
                            ['Description', 'description', {}],
                          ].map(([label, key, opts]) => (
                            <div key={key} style={{ flex: 1, minWidth: 120 }}>
                              <MLabel>{label}</MLabel>
                              {addInput(r, i, key, opts)}
                            </div>
                          ))}
                        </div>
                      </div>
                    )}
                  </div>
                )
              })}
            </div>

            {/* Footer */}
            <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexShrink: 0, flexWrap: 'wrap' }}>
              <button
                className="btn btn-secondary btn-sm"
                type="button"
                onClick={() => setAddRows(prev => [...prev, BLANK_ADD_ROW()])}
                disabled={addSaving}
              >
                <PlusIcon size={12} /> Add row
              </button>
              <span style={{ flex: 1, fontSize: '0.76rem', color: 'var(--text-muted)' }}>
                {addSummary
                  ? <b style={{ color: addSummary.failed ? '#ef4444' : '#22c55e' }}>
                      {addSummary.ok} added{addSummary.failed ? `, ${addSummary.failed} failed — fix and Save again` : ''}
                    </b>
                  : `${addRowsReady.length} product${addRowsReady.length !== 1 ? 's' : ''} ready to save`
                }
              </span>
              <button className="btn btn-secondary" disabled={addSaving} onClick={onClose}>
                {addSummary?.ok ? 'Done' : 'Cancel'}
              </button>
              <button
                className="btn btn-primary"
                style={{ fontWeight: 700 }}
                disabled={addSaving || addRowsReady.length === 0}
                onClick={saveAddAll}
              >
                {addSaving ? 'Saving…' : `Save ${addRowsReady.length || ''} product${addRowsReady.length !== 1 ? 's' : ''}`}
              </button>
            </div>
          </div>
        )}

        {/* ──────────────────── UPDATE STOCK MODE ──────────────────── */}
        {mode === 'stock' && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 10, padding: '10px 18px 16px', flex: 1, minHeight: 0 }}>
            <div style={{ fontSize: '0.76rem', color: 'var(--text-muted)', flexShrink: 0 }}>
              Pick products from your catalogue and set the quantity + direction to batch-update stock.
              A <b>reason is required</b> for every row — it's recorded in the activity log.
            </div>

            {/* Stock rows header */}
            <div style={{
              display: 'grid',
              gridTemplateColumns: '2.4fr 0.8fr 1fr 1.1fr 1.6fr 0.9fr 90px 22px',
              gap: 8, padding: '0 4px', flexShrink: 0,
            }}>
              {hdr('Product')}
              {hdr('Current', 'center')}
              {hdr('Direction')}
              {hdr('Qty', 'right')}
              {hdr('Reason *')}
              {hdr('Reference')}
              {hdr('Status')}
              <span />
            </div>

            {/* Stock rows */}
            <div style={{ overflowY: 'auto', flex: 1, minHeight: 0, display: 'flex', flexDirection: 'column', gap: 6 }}>
              {stockRows.map((r, i) => (
                <div
                  key={r._key}
                  style={{
                    border: `1px solid ${r._status === 'ok' ? '#22c55e40' : 'var(--border)'}`,
                    borderRadius: 8, padding: '6px 8px',
                    opacity: r._status === 'ok' ? 0.6 : 1,
                    background: r.product_id ? 'transparent' : 'var(--bg-2, rgba(0,0,0,.02))',
                  }}
                >
                  <div style={{ display: 'grid', gridTemplateColumns: '2.4fr 0.8fr 1fr 1.1fr 1.6fr 0.9fr 90px 22px', gap: 8, alignItems: 'center' }}>
                    {/* Product cell — click to pick */}
                    <div style={{ position: 'relative' }}>
                      <input
                        className="form-input"
                        style={{ width: '100%', height: 34, padding: '4px 9px', fontSize: '0.79rem', cursor: 'pointer' }}
                        placeholder="Search & pick product…"
                        value={activeStockRowIdx === i ? productSearch : (r.product_name || '')}
                        readOnly={r._status === 'ok' || stockSaving}
                        onFocus={() => {
                          if (r._status === 'ok') return
                          setActiveStockRowIdx(i)
                          setProductSearch(r.product_name || '')
                          setShowProductDropdown(true)
                        }}
                        onChange={e => {
                          setProductSearch(e.target.value)
                          setShowProductDropdown(true)
                        }}
                        onBlur={() => setTimeout(() => {
                          setShowProductDropdown(false)
                          setActiveStockRowIdx(null)
                        }, 200)}
                      />
                      {showProductDropdown && activeStockRowIdx === i && (
                        <div style={{
                          position: 'absolute', top: '100%', left: 0, zIndex: 100,
                          background: 'var(--bg-1)', border: '1px solid var(--border)',
                          borderRadius: 8, boxShadow: 'var(--shadow-md)',
                          minWidth: 260, maxHeight: 200, overflowY: 'auto',
                          marginTop: 2,
                        }}>
                          {filteredProducts.length === 0
                            ? <div style={{ padding: '10px 14px', fontSize: '0.76rem', color: 'var(--text-muted)' }}>No products found</div>
                            : filteredProducts.map(p => (
                              <button
                                key={p.id}
                                type="button"
                                onMouseDown={() => pickProduct(p, i)}
                                style={{
                                  display: 'block', width: '100%', textAlign: 'left',
                                  padding: '8px 14px', background: 'transparent', border: 'none',
                                  cursor: 'pointer', fontSize: '0.8rem',
                                  borderBottom: '1px solid var(--border)',
                                }}
                                onMouseEnter={e => e.currentTarget.style.background = 'var(--bg-2)'}
                                onMouseLeave={e => e.currentTarget.style.background = 'transparent'}
                              >
                                <div style={{ fontWeight: 600, color: 'var(--text-primary)' }}>{p.name}</div>
                                <div style={{ fontSize: '0.69rem', color: 'var(--text-muted)', marginTop: 1 }}>
                                  Stock: {p.stock_qty ?? p.quantity ?? 0} {p.unit || 'pcs'}
                                  {p.sku && ` · SKU: ${p.sku}`}
                                </div>
                              </button>
                            ))
                          }
                        </div>
                      )}
                    </div>

                    {/* Current stock badge */}
                    <div style={{ textAlign: 'center' }}>
                      {r.product_id
                        ? <span style={{ fontWeight: 700, fontSize: '0.85rem', color: r.current_stock <= 0 ? '#ef4444' : 'var(--text-primary)' }}>
                            {r.current_stock} <span style={{ fontSize: '0.65rem', color: 'var(--text-muted)', fontWeight: 400 }}>{r.product_unit}</span>
                          </span>
                        : <span style={{ color: 'var(--text-muted)', fontSize: '0.72rem' }}>—</span>
                      }
                    </div>

                    {/* Movement type */}
                    <select
                      className="form-select"
                      style={{ height: 34, fontSize: '0.78rem', padding: '0 8px' }}
                      value={r.movement_type}
                      disabled={!r.product_id || r._status === 'ok' || stockSaving}
                      onChange={e => setStockCell(i, 'movement_type', e.target.value)}
                    >
                      <option value="stock_in">↑ Stock In</option>
                      <option value="stock_out">↓ Stock Out</option>
                      <option value="adjustment">⇌ Adjustment</option>
                    </select>

                    {/* Quantity */}
                    {stockInput(r, i, 'quantity', { num: true, placeholder: '0', style: { textAlign: 'right' } })}

                    {/* Reason */}
                    {stockInput(r, i, 'reason', { placeholder: 'e.g. Purchase received' })}

                    {/* Reference */}
                    {stockInput(r, i, 'reference', { placeholder: 'PO / GRN #' })}

                    {/* Status */}
                    <span style={{ lineHeight: 1.2 }}>{statusChip(r._status)}</span>

                    {/* Remove */}
                    {stockRows.length > 1 && (
                      <button
                        type="button"
                        onClick={() => removeStockRow(i)}
                        disabled={stockSaving}
                        style={{
                          background: 'transparent', border: 'none', cursor: 'pointer',
                          color: 'var(--text-muted)', fontSize: '0.9rem', padding: 0, lineHeight: 1,
                        }}
                        title="Remove this row"
                      >×</button>
                    )}
                  </div>
                </div>
              ))}
            </div>

            {/* Quick-add product search bar */}
            <div style={{ flexShrink: 0, position: 'relative' }}>
              <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                <div style={{ position: 'relative', flex: 1 }}>
                  <span style={{
                    position: 'absolute', left: 10, top: '50%', transform: 'translateY(-50%)',
                    color: 'var(--text-muted)', display: 'flex', alignItems: 'center',
                  }}>
                    <SearchIcon size={14} />
                  </span>
                  <input
                    ref={searchRef}
                    className="form-input"
                    style={{ paddingLeft: 32, fontSize: '0.79rem' }}
                    placeholder="Search catalogue to add a product row…"
                    value={activeStockRowIdx === null ? productSearch : ''}
                    onChange={e => {
                      setProductSearch(e.target.value)
                      setActiveStockRowIdx(null)
                      setShowProductDropdown(true)
                    }}
                    onFocus={() => { setActiveStockRowIdx(null); setShowProductDropdown(true) }}
                    onBlur={() => setTimeout(() => setShowProductDropdown(false), 200)}
                  />
                  {showProductDropdown && activeStockRowIdx === null && (
                    <div style={{
                      position: 'absolute', bottom: '100%', left: 0, zIndex: 100,
                      background: 'var(--bg-1)', border: '1px solid var(--border)',
                      borderRadius: 8, boxShadow: 'var(--shadow-md)',
                      width: '100%', maxHeight: 200, overflowY: 'auto',
                      marginBottom: 2,
                    }}>
                      {filteredProducts.length === 0
                        ? <div style={{ padding: '10px 14px', fontSize: '0.76rem', color: 'var(--text-muted)' }}>No products found</div>
                        : filteredProducts.map(p => (
                          <button
                            key={p.id}
                            type="button"
                            onMouseDown={() => pickProduct(p, null)}
                            style={{
                              display: 'flex', width: '100%', textAlign: 'left',
                              padding: '8px 14px', background: 'transparent', border: 'none',
                              cursor: 'pointer', fontSize: '0.8rem', alignItems: 'center', gap: 8,
                              borderBottom: '1px solid var(--border)',
                            }}
                            onMouseEnter={e => e.currentTarget.style.background = 'var(--bg-2)'}
                            onMouseLeave={e => e.currentTarget.style.background = 'transparent'}
                          >
                            <span style={{ flex: 1 }}>
                              <span style={{ fontWeight: 600 }}>{p.name}</span>
                              {p.sku && <span style={{ color: 'var(--text-muted)', fontSize: '0.72rem', marginLeft: 6 }}>{p.sku}</span>}
                            </span>
                            <span style={{ fontSize: '0.72rem', color: p.stock_qty <= 0 ? '#ef4444' : 'var(--text-muted)', fontVariantNumeric: 'tabular-nums' }}>
                              {p.stock_qty ?? p.quantity ?? 0} {p.unit || 'pcs'}
                            </span>
                          </button>
                        ))
                      }
                    </div>
                  )}
                </div>
                <button
                  className="btn btn-secondary btn-sm"
                  type="button"
                  onClick={() => setStockRows(prev => [...prev, BLANK_STOCK_ROW()])}
                  disabled={stockSaving}
                >
                  <PlusIcon size={12} /> Add row
                </button>
              </div>
            </div>

            {/* Footer */}
            <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexShrink: 0, flexWrap: 'wrap' }}>
              <span style={{ flex: 1, fontSize: '0.76rem', color: 'var(--text-muted)' }}>
                {stockSummary
                  ? <b style={{ color: stockSummary.failed ? '#ef4444' : '#22c55e' }}>
                      {stockSummary.ok} updated{stockSummary.failed ? `, ${stockSummary.failed} failed` : ''}
                    </b>
                  : `${stockRowsReady.length} row${stockRowsReady.length !== 1 ? 's' : ''} ready to save`
                }
              </span>
              <button className="btn btn-secondary" disabled={stockSaving} onClick={onClose}>
                {stockSummary?.ok ? 'Done' : 'Cancel'}
              </button>
              <button
                className="btn btn-primary"
                style={{ fontWeight: 700 }}
                disabled={stockSaving || stockRowsReady.length === 0}
                onClick={saveStockAll}
              >
                <span style={{ marginRight: 5, display: 'inline-flex', alignItems: 'center', verticalAlign: 'middle' }}><SyncIcon size={13} /></span>
                {stockSaving ? 'Saving…' : `Save ${stockRowsReady.length || ''} update${stockRowsReady.length !== 1 ? 's' : ''}`}
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
