// components/stock/LabelPrintModal.jsx — barcode label printing.
// ===============================================================
// The stock-staff feature the owners asked for: pick products, set how many
// labels each, pick a label size, print. Labels carry the business name,
// product name, price and a scannable Code 128 barcode (barcode field → SKU
// fallback → P<id>), rendered offline by utils/code128 — no internet, no
// external fonts, works in the packaged app.
//
// Print isolation: same portal pattern as the shift summary — @media print
// hides everything except #labels-print-root; @page removes margins so label
// stock sheets line up.
import React, { useState, useMemo } from 'react'
import { createPortal } from 'react-dom'
import { useAuth } from '../../contexts/AuthContext'
import { code128Svg, sanitizeBarcodeValue } from '../../utils/code128'

const SIZES = {
  '50x25': { w: 50, h: 25, label: '50 × 25 mm (standard)' },
  '38x25': { w: 38, h: 25, label: '38 × 25 mm (compact)' },
  '65x35': { w: 65, h: 35, label: '65 × 35 mm (large)' },
}

const PRINT_CSS = `
@media print {
  body > *:not(#labels-print-root) { display: none !important; }
  #labels-print-root { display: block !important; position: static !important; }
  @page { margin: 4mm; }
}
#labels-print-root { display: none; }
`

const fmt = (n) => `₹${Number(n || 0).toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`

function barcodeValueFor(p) {
  return sanitizeBarcodeValue(p.barcode || p.sku || `P${p.id}`)
}

// Which pieces print on each label — owner-selectable, persisted per device.
export const LABEL_FIELD_OPTIONS = [
  { key: 'business', label: 'Business name' },
  { key: 'name',     label: 'Item name' },
  { key: 'sku',      label: 'Item code (SKU)' },
  { key: 'mrp',      label: 'MRP' },
  { key: 'price',    label: 'Special / selling price' },
  { key: 'barcode',  label: 'Barcode + code text' },
]
const DEFAULT_FIELDS = { business: true, name: true, sku: false, mrp: false, price: true, barcode: true }
const FIELDS_STORAGE_KEY = 'label_print_fields'

export function loadLabelFields() {
  try {
    const saved = JSON.parse(localStorage.getItem(FIELDS_STORAGE_KEY) || 'null')
    return saved ? { ...DEFAULT_FIELDS, ...saved } : { ...DEFAULT_FIELDS }
  } catch { return { ...DEFAULT_FIELDS } }
}

// Exported for tests: jsdom cannot measure millimetres, but it CAN prove which
// rows render for a given field combination and that the price survives when
// the item name is switched off — the case space-between got wrong.
export function Label({ product, size, businessName, fields }) {
  const s = SIZES[size]
  const value = barcodeValueFor(product)
  const svg = code128Svg(value, { height: 40 })
  const priceBits = []
  if (fields.mrp && product.mrp) priceBits.push(`MRP ${fmt(product.mrp)}`)
  if (fields.price) priceBits.push(fmt(product.selling_price))
  const hasHeadRow = fields.name || priceBits.length > 0
  return (
    // FIXED ROWS, not space-between.
    //
    // `justify-content: space-between` on conditionally-rendered children means
    // the layout changes SHAPE with every field toggle: turn the business name
    // off and the item row jumps to the top edge; turn the barcode off and the
    // price row is flung to the bottom. Rows now sit in order from the top and
    // the barcode absorbs whatever is left, so a label looks like itself
    // whatever is switched on.
    <div style={{
      width: `${s.w}mm`, height: `${s.h}mm`, boxSizing: 'border-box',
      display: 'inline-flex', flexDirection: 'column',
      // With no barcode there is nothing to absorb the slack, so centre the
      // few remaining rows instead of stranding them against the top edge.
      justifyContent: fields.barcode ? 'flex-start' : 'center',
      padding: '1.5mm 2mm', border: '1px dotted #bbb', overflow: 'hidden',
      background: '#fff', color: '#000', verticalAlign: 'top',
      fontFamily: "'DM Sans', Arial, sans-serif", pageBreakInside: 'avoid',
    }}>
      {fields.business && (
        <div style={{ flex: '0 0 auto', fontSize: '2.2mm', fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.04em', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
          {businessName || ' '}
        </div>
      )}

      {hasHeadRow && (
        <div style={{ flex: '0 0 auto', display: 'flex', alignItems: 'baseline', gap: '2mm', minWidth: 0 }}>
          {fields.name && (
            // `min-width: 0` is what makes the ellipsis work at all: a flex item
            // defaults to min-width:auto and refuses to shrink below its content,
            // so a long product name pushed the PRICE off the label instead of
            // truncating itself.
            <span style={{ flex: '1 1 auto', minWidth: 0, fontSize: '2.8mm', fontWeight: 700, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
              {product.name}
              {fields.sku && product.sku ? <span style={{ fontWeight: 400, fontSize: '2.2mm' }}> · {product.sku}</span> : null}
            </span>
          )}
          {priceBits.length > 0 && (
            // Never truncated, and `margin-left:auto` keeps it hard right even
            // when the name is switched off — space-between put a lone price on
            // the LEFT, which is the one number the counter reads at a glance.
            <span style={{ flex: '0 0 auto', marginLeft: 'auto', fontSize: '3mm', fontWeight: 800, whiteSpace: 'nowrap' }}>
              {priceBits.join(' | ')}
            </span>
          )}
        </div>
      )}

      {fields.barcode && (
        // `flex: 1` + `min-height: 0` instead of the old
        // `height: max(s.h - 14, 8)mm`. That arithmetic was tuned for the 25 mm
        // sizes and simply over-reserved on 65×35 (21 mm of bars plus padding,
        // name and code text), and it did not shrink when fields were toggled
        // ON. The SVG already scales (preserveAspectRatio="none", 100%×100%),
        // so letting flex size it is both correct and size-independent.
        <div style={{ flex: '1 1 auto', minHeight: 0, display: 'flex', flexDirection: 'column', marginTop: '0.5mm' }}>
          <div style={{ flex: '1 1 auto', minHeight: 0 }}
            dangerouslySetInnerHTML={{ __html: svg || '<div style="font-size:2.5mm;text-align:center">no code</div>' }} />
          <div style={{ flex: '0 0 auto', fontSize: '2.2mm', lineHeight: 1.1, textAlign: 'center', letterSpacing: '0.12em', fontFamily: "'Geist Mono', monospace", whiteSpace: 'nowrap', overflow: 'hidden' }}>
            {value}
          </div>
        </div>
      )}
    </div>
  )
}

export default function LabelPrintModal({ open, onClose, products = [], preselectIds = [] }) {
  const { profile } = useAuth()
  const [search, setSearch] = useState('')
  const [size, setSize] = useState('50x25')
  const [fields, setFields] = useState(loadLabelFields)   // persisted per device
  const [qty, setQty] = useState({})   // product_id -> label count

  // Rows ticked in the inventory table arrive pre-selected with 1 label each.
  React.useEffect(() => {
    if (open && preselectIds.length > 0) {
      setQty(prev => {
        const next = { ...prev }
        preselectIds.forEach(id => { if (!next[id]) next[id] = 1 })
        return next
      })
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open])

  const toggleField = (key) => {
    setFields(prev => {
      const next = { ...prev, [key]: !prev[key] }
      try { localStorage.setItem(FIELDS_STORAGE_KEY, JSON.stringify(next)) } catch { /* ignore */ }
      return next
    })
  }

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase()
    const list = q
      ? products.filter(p =>
          p.name?.toLowerCase().includes(q) ||
          p.sku?.toLowerCase().includes(q) ||
          p.barcode?.toLowerCase().includes(q))
      : products
    return list.slice(0, 200)
  }, [products, search])

  const selected = useMemo(
    () => products.filter(p => (qty[p.id] || 0) > 0),
    [products, qty],
  )
  const totalLabels = selected.reduce((s, p) => s + (qty[p.id] || 0), 0)

  if (!open) return null

  const setCount = (id, val) => {
    const n = Math.max(0, Math.min(500, parseInt(val, 10) || 0))
    setQty(prev => ({ ...prev, [id]: n }))
  }

  const labels = []
  for (const p of selected) {
    for (let i = 0; i < (qty[p.id] || 0); i++) labels.push({ p, i })
  }

  return (
    <>
      <div className="modal-overlay" style={{ zIndex: 3000 }} onClick={e => e.target === e.currentTarget && onClose?.()}>
        <div className="modal" style={{ maxWidth: 760, width: '95%', maxHeight: '88vh', display: 'flex', flexDirection: 'column' }}>
          <div style={{ padding: '18px 22px', display: 'flex', flexDirection: 'column', gap: 12, minHeight: 0 }}>
            <div>
              <h3 style={{ margin: 0, fontSize: '1.05rem' }}>Print Barcode Labels</h3>
              <p style={{ color: 'var(--text-muted)', fontSize: '0.78rem', margin: '4px 0 0' }}>
                Pick products and how many labels each. Labels scan straight into the billing counter.
              </p>
            </div>

            {/* Options row */}
            <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', alignItems: 'center' }}>
              <input
                className="form-input" style={{ flex: 1, minWidth: 180 }}
                placeholder="Search product / SKU / barcode…"
                value={search} onChange={e => setSearch(e.target.value)}
              />
              <select className="form-input" style={{ width: 190 }} value={size} onChange={e => setSize(e.target.value)}>
                {Object.entries(SIZES).map(([k, v]) => <option key={k} value={k}>{v.label}</option>)}
              </select>
            </div>

            {/* Field picker — what prints on each label (choice is remembered) */}
            <div style={{
              display: 'flex', gap: 14, flexWrap: 'wrap', alignItems: 'center',
              padding: '8px 12px', border: '1px solid var(--border)', borderRadius: 8,
            }}>
              <span style={{ fontSize: '0.68rem', fontWeight: 800, textTransform: 'uppercase', letterSpacing: '0.06em', color: 'var(--text-muted)' }}>
                On the label:
              </span>
              {LABEL_FIELD_OPTIONS.map(opt => (
                <label key={opt.key} style={{ display: 'inline-flex', alignItems: 'center', gap: 5, fontSize: '0.78rem', cursor: 'pointer' }}>
                  <input type="checkbox" checked={!!fields[opt.key]} onChange={() => toggleField(opt.key)} />
                  {opt.label}
                </label>
              ))}
            </div>

            {/* Product picker */}
            <div style={{ overflowY: 'auto', border: '1px solid var(--border)', borderRadius: 8, maxHeight: 300 }}>
              <table className="data-table" style={{ width: '100%', fontSize: '0.8rem' }}>
                <thead>
                  <tr><th>Product</th><th>Code</th><th style={{ width: 90 }}>Price</th><th style={{ width: 110 }}>Labels</th></tr>
                </thead>
                <tbody>
                  {filtered.length === 0 ? (
                    <tr><td colSpan={4} style={{ textAlign: 'center', color: 'var(--text-muted)', padding: 18 }}>No products match.</td></tr>
                  ) : filtered.map(p => (
                    <tr key={p.id}>
                      <td style={{ fontWeight: 600 }}>{p.name}</td>
                      <td style={{ fontFamily: "'Geist Mono',monospace", fontSize: '0.72rem' }}>{barcodeValueFor(p) || '—'}</td>
                      <td>{fmt(p.selling_price)}</td>
                      <td>
                        <input
                          type="number" min="0" max="500" className="form-input"
                          style={{ width: 80, height: 30, padding: '2px 8px' }}
                          value={qty[p.id] ?? ''} placeholder="0"
                          onChange={e => setCount(p.id, e.target.value)}
                        />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            {/* Footer */}
            <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
              <span style={{ fontSize: '0.78rem', color: 'var(--text-muted)', flex: 1 }}>
                {totalLabels > 0
                  ? <><b>{totalLabels}</b> label{totalLabels === 1 ? '' : 's'} for <b>{selected.length}</b> product{selected.length === 1 ? '' : 's'}</>
                  : 'Enter a label count next to a product to begin.'}
              </span>
              <button className="btn btn-secondary" onClick={onClose}>Cancel</button>
              <button
                className="btn btn-primary" style={{ fontWeight: 700 }}
                disabled={totalLabels === 0}
                onClick={() => window.print()}
              >
                Print {totalLabels > 0 ? `${totalLabels} Labels` : 'Labels'}
              </button>
            </div>
          </div>
        </div>
      </div>

      {/* Print sheet */}
      {createPortal(
        <div id="labels-print-root">
          <style>{PRINT_CSS}</style>
          <div style={{ fontSize: 0, lineHeight: 0 }}>
            {labels.map(({ p }, idx) => (
              <Label key={idx} product={p} size={size} businessName={profile?.business_name} fields={fields} />
            ))}
          </div>
        </div>,
        document.body,
      )}
    </>
  )
}
