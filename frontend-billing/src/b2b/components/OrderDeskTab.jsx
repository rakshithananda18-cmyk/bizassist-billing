// ============================================================================
// b2b/components/OrderDeskTab.jsx — the "Order" tab: a B2B storefront.
// ----------------------------------------------------------------------------
// Reordering from a supplier should feel like shopping, not like filing a form.
// So this is a product GRID, not a spreadsheet: image tile, name, price with the
// struck-through list price, a savings badge, a stock chip, and an Add-to-cart
// button that turns into a stepper once the item is in the order. The cart lives
// behind a badged cart button and slides in on the right.
//
//   ┌────────────────────────────────────────────────────────────┐
//   │ [Supplier ▾] [scan / search] [sort ▾]        [🛒 Cart · 3] │
//   │ ( All 16 )( Grocery 8 )( Household 5 )…  ← category rail   │
//   ├────────────────────────────────────────────────────────────┤
//   │ ▢ ▢ ▢ ▢   product tiles: price · saving · stock · Add      │
//   └────────────────────────────────────────────────────────────┘
//
// The cart is a DRAWER, not a permanent column — it slides over the grid when
// the cart button is pressed, or the first time an item is added.
//
// BARCODE SCANNING: a GTIN is the same code in both businesses' systems, so the
// buyer's counter scanner works against the supplier's catalogue with zero
// setup. Scanning and searching share ONE field (ScanSearchField): typing
// filters, Enter resolves the value as a code (barcode → SKU → exact name),
// adds one unit and flashes the tile.
//
// Renders only. Fetching and order placement are injected; the money maths
// lives in useOrderCart.
// ============================================================================
import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  CartIcon, CheckIcon, CloseIcon, ConnectionIcon, PackageIcon, SyncIcon, TruckIcon,
} from '../../components/Icons'
import CustomSelect from '../../components/common/CustomSelect'
import ScanSearchField from '../../components/common/ScanSearchField'
import useOrderCart from '../useOrderCart'

const fmt = (n) =>
  n != null ? `₹${Number(n).toLocaleString('en-IN', { maximumFractionDigits: 2 })}` : '—'

const SORTS = [
  { value: 'name', label: 'Name (A–Z)' },
  { value: 'price_asc', label: 'Price: low to high' },
  { value: 'price_desc', label: 'Price: high to low' },
  { value: 'discount', label: 'Biggest saving' },
]

/**
 * Resolve a scanned code to a catalogue row.
 * Exported for unit testing — this is the part that must not mis-pick, since a
 * wrong match silently orders the wrong item.
 * Match order: any barcode (exact) → SKU (case-insensitive) → exact name.
 */
export function findByCode(catalog, rawCode) {
  const code = String(rawCode || '').trim()
  if (!code) return null
  const lower = code.toLowerCase()

  const byBarcode = catalog.find(p =>
    (p.barcodes || []).some(b => String(b) === code) || String(p.barcode || '') === code
  )
  if (byBarcode) return byBarcode

  const bySku = catalog.find(p => String(p.sku || '').toLowerCase() === lower)
  if (bySku) return bySku

  return catalog.find(p => String(p.name || '').toLowerCase() === lower) || null
}

/** Two-letter monogram tile — products have no images in the catalogue payload,
 *  so this keeps the grid visually scannable without a broken-image placeholder. */
function Thumb({ name }) {
  const initials = String(name || '?')
    .split(/\s+/).filter(Boolean).slice(0, 2).map(w => w[0]).join('').toUpperCase()
  // Deterministic hue from the name so the same product always looks the same.
  let h = 0
  for (let i = 0; i < String(name || '').length; i++) h = (h * 31 + name.charCodeAt(i)) % 360
  return (
    <div className="b2b-tile-thumb" style={{ '--tile-h': h }} aria-hidden="true">
      {initials || '—'}
    </div>
  )
}

function StockChip({ stock }) {
  if (stock === null || stock === undefined || stock === '') return null
  const label = typeof stock === 'number' ? `${stock} in stock` : String(stock)
  const bad = label === 'Out of Stock' || stock === 0
  const warn = label === 'Low Stock' || (typeof stock === 'number' && stock > 0 && stock <= 10)
  return (
    <span className={`b2b-stock-chip${bad ? ' is-bad' : warn ? ' is-warn' : ''}`}>{label}</span>
  )
}

function QtyStepper({ qty, onBump, onSet }) {
  return (
    <div className="b2b-qty field-shell">
      <button type="button" className="b2b-qty-btn" onClick={() => onBump(-1)} aria-label="Decrease">−</button>
      <input
        className="b2b-qty-input"
        type="number" min="0" step="any"
        value={qty || ''} placeholder="0"
        onChange={e => onSet(e.target.value)}
        aria-label="Quantity"
      />
      <button type="button" className="b2b-qty-btn" onClick={() => onBump(1)} aria-label="Increase">+</button>
    </div>
  )
}

export default function OrderDeskTab({
  suppliers = [],
  selectedSupplier,
  onSelectSupplier,
  catalog = [],
  catalogLoading = false,
  connectionsLoading = false,
  onPlaceOrder,
  placing = false,
  onGoToConnections,
  onRefresh,
}) {
  const [query, setQuery] = useState('')
  const [category, setCategory] = useState('')
  const [sort, setSort] = useState('name')
  const [scanError, setScanError] = useState('')
  const [flashId, setFlashId] = useState(null)
  const [cartOpen, setCartOpen] = useState(false)

  const scanRef = useRef(null)
  const cart = useOrderCart(catalog)

  // Switching supplier drops the cart: prices, tiers and product ids are all
  // supplier-scoped, so carrying lines across would silently mis-price them.
  const supplierId = selectedSupplier?.id
  useEffect(() => {
    cart.clear(); setQuery(''); setCategory(''); setScanError(''); setCartOpen(false)
  }, [supplierId]) // eslint-disable-line react-hooks/exhaustive-deps

  // Keep the scanner armed — a hardware scanner just types, so the field must
  // already hold focus when the trigger is pulled.
  useEffect(() => {
    if (selectedSupplier && !catalogLoading) scanRef.current?.focus()
  }, [selectedSupplier, catalogLoading])

  const categories = useMemo(
    () => [...new Set(catalog.map(p => p.category).filter(Boolean))].sort(),
    [catalog]
  )

  /** Item count per category, for the rail's badges. */
  const countByCategory = useMemo(() => {
    const m = new Map()
    catalog.forEach(p => { if (p.category) m.set(p.category, (m.get(p.category) || 0) + 1) })
    return m
  }, [catalog])

  const savingOf = (p) => {
    const was = Number(p.original_selling_price) || 0
    const now = Number(p.selling_price) || 0
    return was > now && was > 0 ? Math.round(((was - now) / was) * 100) : 0
  }

  const visible = useMemo(() => {
    const q = query.trim().toLowerCase()
    const list = catalog.filter(p => {
      if (category && p.category !== category) return false
      if (!q) return true
      return (
        p.name?.toLowerCase().includes(q) ||
        p.sku?.toLowerCase().includes(q) ||
        p.brand?.toLowerCase().includes(q) ||
        p.hsn_sac?.toLowerCase().includes(q) ||
        (p.barcodes || []).some(b => String(b).toLowerCase().includes(q))
      )
    })
    const sorted = [...list]
    if (sort === 'price_asc') sorted.sort((a, b) => (a.selling_price || 0) - (b.selling_price || 0))
    else if (sort === 'price_desc') sorted.sort((a, b) => (b.selling_price || 0) - (a.selling_price || 0))
    else if (sort === 'discount') sorted.sort((a, b) => savingOf(b) - savingOf(a))
    else sorted.sort((a, b) => String(a.name || '').localeCompare(String(b.name || '')))
    return sorted
  }, [catalog, query, category, sort])

  /** Enter/scan handler. Returns TRUE when the code resolved — ScanSearchField
   *  uses that to decide whether to clear itself, so an unmatched value stays
   *  put and keeps filtering (which is what typing a partial name means). */
  const handleScan = useCallback((code) => {
    const hit = findByCode(catalog, code)
    if (!hit) {
      setScanError(`No item matches “${code}” — showing search results instead.`)
      return false
    }
    cart.bump(hit.product_id, 1)
    setCartOpen(true)
    setScanError('')
    setFlashId(hit.product_id)
    setTimeout(() => setFlashId(cur => (cur === hit.product_id ? null : cur)), 900)
    return true
  }, [catalog, cart])

  const submit = async () => {
    const ok = await onPlaceOrder({ lines: cart.lines, totals: cart.totals, notes: cart.notes })
    if (ok) { cart.clear(); setCartOpen(false) }
  }

  // ── 1. Connections loading from backend ──────────────────────────────────
  if (connectionsLoading) {
    return (
      <div className="page-loader" style={{ padding: '48px 24px' }}>
        <span className="spinner" /> Loading connected suppliers…
      </div>
    )
  }

  // ── 2. No suppliers at all → the only useful action is to go connect ─────────
  if (suppliers.length === 0) {
    return (
      <div className="empty-state" style={{ padding: '48px 24px' }}>
        <div className="empty-icon"><ConnectionIcon size={26} /></div>
        <h3>No connected suppliers yet</h3>
        <p style={{ maxWidth: 430, margin: '0 auto 16px' }}>
          You can only order from businesses you're connected to. Send a request with
          their BizID — once they approve it, their catalogue appears here.
        </p>
        <button className="btn btn-primary" onClick={onGoToConnections}>
          <ConnectionIcon size={14} /> Go to Connections
        </button>
      </div>
    )
  }

  const supplierName = selectedSupplier?.counterparty_name || selectedSupplier?.seller_name || ''

  return (
    <div className={`b2b-shop${cartOpen ? ' is-cart-open' : ''}`}>
      <section className="b2b-shop-main">
        {/* ── Toolbar ────────────────────────────────────────────────────── */}
        <div className="b2b-toolbar">
          <CustomSelect
            className="form-select"
            style={{ height: 34, fontSize: '0.82rem', width: 'auto', minWidth: 180, flexShrink: 0 }}
            value={supplierId || ''}
            onChange={e => onSelectSupplier(suppliers.find(s => String(s.id) === e.target.value))}
          >
            {/* CustomSelect reads the label from props.children, so each option
                needs ONE string child — not an expression list. */}
            {suppliers.map(s => (
              <option key={s.id} value={s.id}>
                {[
                  s.counterparty_name || s.seller_name,
                  s.price_tier && s.price_tier !== 'standard' ? s.price_tier : null,
                  s.discount_pct > 0 ? `−${s.discount_pct}%` : null,
                ].filter(Boolean).join(' · ')}
              </option>
            ))}
          </CustomSelect>

          <ScanSearchField
            ref={scanRef}
            value={query}
            onChange={(v) => { setQuery(v); if (scanError) setScanError('') }}
            onScan={handleScan}
            error={scanError}
            placeholder="Scan barcode or search items…"
          />

          <CustomSelect
            className="form-select"
            style={{ height: 34, fontSize: '0.82rem', width: 'auto', minWidth: 150, flexShrink: 0 }}
            value={sort}
            onChange={e => setSort(e.target.value)}
          >
            {SORTS.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
          </CustomSelect>

          <div style={{ flex: 1 }} />

          <span className="b2b-toolbar-count">{visible.length} of {catalog.length}</span>

          {/* Refresh — sits immediately LEFT of the cart. A supplier's catalogue
              is their live data: prices, tier discounts and stock counts change
              on their side while this page is open, and nothing pushes those
              here. Without a manual pull the only way to see current numbers is
              to switch supplier and back. Placed next to the cart because that
              is where the user looks before committing to an order. */}
          {onRefresh && (
            <button
              type="button"
              className={`b2b-refresh-btn${catalogLoading ? ' is-busy' : ''}`}
              onClick={onRefresh}
              disabled={catalogLoading || !selectedSupplier}
              title="Refresh prices and stock from the supplier"
              aria-label="Refresh catalogue"
            >
              <SyncIcon size={15} />
            </button>
          )}

          {/* Cart button — the persistent "where's my order" affordance. */}
          <button
            type="button"
            className={`b2b-cart-btn${cart.itemCount > 0 ? ' has-items' : ''}`}
            onClick={() => setCartOpen(o => !o)}
            title={cart.isEmpty ? 'Your order is empty' : `${cart.itemCount} items · ${fmt(cart.totals.total)}`}
          >
            <CartIcon size={16} />
            <span className="b2b-cart-btn-label">{cart.isEmpty ? 'Cart' : fmt(cart.totals.total)}</span>
            {cart.itemCount > 0 && <span className="b2b-cart-badge">{cart.itemCount}</span>}
          </button>
        </div>

        {scanError && <div className="b2b-scan-error">{scanError}</div>}

        {/* Category rail — the storefront's department bar. Chips beat a select
            here: every department is visible at a glance with its item count,
            and switching is one click instead of open-scan-click. */}
        {categories.length > 0 && (
          <div className="b2b-cat-rail" role="tablist" aria-label="Categories">
            <button
              type="button"
              role="tab"
              aria-selected={!category}
              className={`b2b-cat-tab${!category ? ' is-active' : ''}`}
              onClick={() => setCategory('')}
            >
              All <span className="b2b-cat-n">{catalog.length}</span>
            </button>
            {categories.map(c => (
              <button
                key={c}
                type="button"
                role="tab"
                aria-selected={category === c}
                className={`b2b-cat-tab${category === c ? ' is-active' : ''}`}
                onClick={() => setCategory(category === c ? '' : c)}
              >
                {c} <span className="b2b-cat-n">{countByCategory.get(c) || 0}</span>
              </button>
            ))}
          </div>
        )}

        {/* ── Storefront grid ────────────────────────────────────────────── */}
        {catalogLoading ? (
          <div className="page-loader"><span className="spinner" /> Loading catalogue…</div>
        ) : catalog.length === 0 ? (
          <div className="empty-state" style={{ padding: '40px 24px' }}>
            <div className="empty-icon"><PackageIcon size={22} /></div>
            <h3>No products shared with you</h3>
            <p>{supplierName || 'This supplier'} hasn't published any active products to your connection scope.</p>
          </div>
        ) : visible.length === 0 ? (
          <div className="empty-state" style={{ padding: '40px 24px' }}>
            <div className="empty-icon"><PackageIcon size={22} /></div>
            <h3>Nothing matches</h3>
            <p>Try a different term, or clear the category filter.</p>
          </div>
        ) : (
          <div className="b2b-grid">
            {visible.map(p => {
              const qty = cart.quantities[p.product_id] || 0
              const line = qty > 0 ? cart.lines.find(l => l.product_id === p.product_id) : null
              const saving = savingOf(p)
              const outOfStock = p.stock === 0 || p.stock === 'Out of Stock'
              return (
                <article
                  key={p.product_id}
                  className={`b2b-tile${qty > 0 ? ' is-in-cart' : ''}${flashId === p.product_id ? ' is-flash' : ''}${outOfStock ? ' is-out' : ''}`}
                >
                  <div className="b2b-tile-media">
                    <Thumb name={p.name} />
                    {saving > 0 && <span className="b2b-tile-save">{saving}% off</span>}
                    {qty > 0 && <span className="b2b-tile-incart"><CheckIcon size={11} /> In order</span>}
                  </div>

                  <div className="b2b-tile-body">
                    <h4 className="b2b-tile-name" title={p.name}>{p.name}</h4>
                    <div className="b2b-tile-meta">
                      {p.brand && <span>{p.brand}</span>}
                      {p.sku && <span className="td-mono">{p.sku}</span>}
                    </div>

                    {/* Price block. Deliberately NOT conditional on anything —
                        a tile without a price is useless, so it always renders
                        even when the payload is incomplete. */}
                    <div className="b2b-tile-price">
                      <strong>{fmt(p.selling_price)}</strong>
                      <span className="b2b-tile-unit">/ {p.unit || 'Nos'}</span>
                    </div>

                    {saving > 0 ? (
                      <div className="b2b-tile-savings">
                        <s>{fmt(p.original_selling_price)}</s>
                        <span className="b2b-tile-savetext">
                          You save {fmt((p.original_selling_price || 0) - (p.selling_price || 0))}
                        </span>
                      </div>
                    ) : p.mrp && Number(p.mrp) > Number(p.selling_price || 0) ? (
                      <div className="b2b-tile-savings">
                        <s>MRP {fmt(p.mrp)}</s>
                      </div>
                    ) : null}

                    <div className="b2b-tile-chips">
                      <StockChip stock={p.stock} />
                      {p.category && <span className="b2b-cat-chip">{p.category}</span>}
                    </div>
                  </div>

                  <div className="b2b-tile-action">
                    {qty > 0 ? (
                      <>
                        <QtyStepper
                          qty={qty}
                          onBump={(d) => cart.bump(p.product_id, d)}
                          onSet={(v) => cart.setQty(p.product_id, v)}
                        />
                        <span className="b2b-tile-linetotal">{line ? fmt(line.line_total) : ''}</span>
                      </>
                    ) : (
                      <button
                        type="button"
                        className="b2b-tile-add"
                        onClick={() => cart.bump(p.product_id, 1)}
                        disabled={outOfStock}
                      >
                        <CartIcon size={13} /> {outOfStock ? 'Out of stock' : 'Add'}
                      </button>
                    )}
                  </div>
                </article>
              )
            })}
          </div>
        )}
      </section>

      {/* ── Cart drawer ────────────────────────────────────────────────── */}
      <aside className="b2b-cart" aria-label="Your order">
        <div className="b2b-cart-head">
          <span><CartIcon size={14} style={{ marginRight: 6, verticalAlign: 'middle' }} /> Your order</span>
          <button type="button" className="b2b-cart-close" onClick={() => setCartOpen(false)} aria-label="Close cart">
            <CloseIcon size={14} />
          </button>
        </div>

        {cart.isEmpty ? (
          <div className="b2b-cart-empty">
            <TruckIcon size={22} style={{ opacity: 0.45 }} />
            <p>Nothing here yet.<br />Scan a barcode or hit <strong>Add</strong> on any item.</p>
          </div>
        ) : (
          <div className="b2b-cart-lines">
            {cart.lines.map(l => (
              <div key={l.product_id} className="b2b-cart-line">
                <div className="b2b-cart-line-main">
                  <div className="b2b-cart-line-name" title={l.name}>{l.name}</div>
                  <div className="b2b-cart-line-sub">{l.quantity} × {fmt(l.selling_price)}</div>
                </div>
                <div className="b2b-cart-line-amt">{fmt(l.line_total)}</div>
                <button
                  type="button"
                  className="b2b-cart-line-x"
                  onClick={() => cart.setQty(l.product_id, 0)}
                  aria-label={`Remove ${l.name}`}
                >×</button>
              </div>
            ))}
          </div>
        )}

        <div className="b2b-cart-foot">
          <textarea
            className="form-textarea"
            style={{ minHeight: 42, fontSize: '0.78rem', marginBottom: 8 }}
            placeholder="Note for the supplier — delivery instructions, PO reference…"
            value={cart.notes}
            onChange={e => cart.setNotes(e.target.value)}
          />
          <div className="b2b-cart-total-row"><span>Subtotal</span><span>{fmt(cart.totals.subtotal)}</span></div>
          {cart.totals.tax > 0 && (
            <div className="b2b-cart-total-row"><span>GST</span><span>{fmt(cart.totals.tax)}</span></div>
          )}
          <div className="b2b-cart-total-row is-grand"><span>Total</span><span>{fmt(cart.totals.total)}</span></div>

          <button
            className="btn btn-primary"
            style={{ width: '100%', marginTop: 8 }}
            disabled={cart.isEmpty || placing || !selectedSupplier}
            onClick={submit}
          >
            {placing ? 'Placing order…' : (
              <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
                <CheckIcon size={14} /> Place order
              </span>
            )}
          </button>
          {!cart.isEmpty && (
            <button className="btn btn-ghost btn-sm" style={{ width: '100%', marginTop: 5 }} onClick={cart.clear} disabled={placing}>
              Clear order
            </button>
          )}
        </div>
      </aside>

      {/* Scrim — click anywhere outside to dismiss the drawer. */}
      {cartOpen && <div className="b2b-cart-scrim" onClick={() => setCartOpen(false)} />}
    </div>
  )
}
