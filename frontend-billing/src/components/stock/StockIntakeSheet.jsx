// components/stock/StockIntakeSheet.jsx
// ============================================================================
// The unified stock intake surface — a POS-style fullscreen panel embedded
// directly inside the Stock page (no separate modal) — v7 with sidebar editor.
//
// ── What it does ────────────────────────────────────────────────────────────
// • Barcode scanner bar at the top (just like POS — cursor always there)
//   - Known barcode  → EXISTING row appears, cursor jumps to +Qty
//   - Unknown barcode→ NEW row opens (all product fields inline)
//   - Same barcode again → increments qty on the existing row (no duplicates)
// • Manual product search: type name → dropdown → pick → row appears
// • Upload bill: PDF / image → AI OCR → rows auto-populate
//              : CSV         → parsed client-side → rows auto-populate
// • Every row has:  Product · Type badge · Current stock · +Qty · Cost₹ · Sell₹ · Batch · Expiry
// • "More ▾" per row: full product fields for NEW rows (name, category, HSN, unit, etc.)
// • Global bill reference field → auto-fills all empty reason cells
// • Batch auto-fills to today's date (editable)
// • Save All: EXISTING rows → stock/adjustment, NEW rows → POST product → adjustment
//
// ── Batch / Lot pricing design ──────────────────────────────────────────────
// Every intake can set a cost price and selling price per batch. This drives
// the batch-aware pricing system: when a product has multiple batches with
// different selling prices, POS will offer a batch picker.
// ============================================================================
import React, { useState, useEffect, useRef, useCallback } from 'react'
import { useAuth } from '../../contexts/AuthContext'
import { logger } from '../../utils/logger'
import {
  SearchIcon, PlusIcon, UploadIcon, CloseIcon, CheckIcon,
  ZapIcon, InventoryIcon, AlertIcon, SyncIcon, PackageIcon,
  EditIcon, PrinterIcon
} from '../Icons'
import ContextMenu from '../common/ContextMenu'

// ── Intake grid columns (order MUST match the <tbody> cell order) ────────────
// Drives the header + the POS-style fold-collapse. Collapse ≠ hide: it's a
// quick per-device fold (right-click a header → Collapse; click the folded
// strip to expand), persisted in localStorage. Essential columns (#, Product,
// +Qty) are non-collapsible.
const INTAKE_COLS = [
  { key: 'sno',     label: '#',         width: 32,  collapsible: false },
  { key: 'product', label: 'Product',   width: 148, collapsible: false, align: 'left' },
  { key: 'type',    label: 'Type',      short: 'TYPE',    width: 56 },
  { key: 'current', label: 'Current',   short: 'CURRENT', width: 58,  align: 'right' },
  { key: 'qty',     label: '+ Qty *',   width: 64,  align: 'right', collapsible: false },
  { key: 'free',    label: 'Free',      short: 'FREE',    width: 52,  align: 'right', title: 'Free units received (added to stock, no cost)' },
  { key: 'cost',    label: 'Cost ₹',    short: 'COST',    width: 84,  align: 'right', title: 'Purchase rate per unit (before tax)' },
  { key: 'sell',    label: 'Sell ₹',    short: 'SELL',    width: 84,  align: 'right', title: 'Selling price per unit' },
  { key: 'mrp',     label: 'MRP ₹',     short: 'MRP',     width: 96,  align: 'right' },
  { key: 'disc',    label: 'Disc%',     short: 'DISC%',   width: 52,  align: 'right', title: 'Discount off MRP' },
  { key: 'discamt', label: 'Disc Amt',  short: 'DISC ₹',  width: 70,  align: 'right', title: 'MRP − Sell, per unit' },
  { key: 'tax',     label: 'Tax%',      short: 'TAX%',    width: 48,  align: 'right', title: 'GST rate on this item' },
  { key: 'taxamt',  label: 'Tax Amt',   short: 'TAX ₹',   width: 76,  align: 'right', title: 'GST on the amount' },
  { key: 'amount',  label: 'Amount ₹',  short: 'AMOUNT',  width: 82,  align: 'right', title: 'Qty × Cost (before tax)' },
  { key: 'netamt',  label: 'Net Amt ₹', short: 'NET AMT', width: 98,  align: 'right', title: 'Amount + Tax (payable to supplier)' },
  { key: 'roi',     label: 'ROI%',      short: 'ROI%',    width: 54,  align: 'right', title: 'Return on cost = (Sell−Cost)/Cost' },
  { key: 'profit',  label: 'Profit%',   short: 'PROFIT',  width: 58,  align: 'right', title: 'Margin on selling = (Sell−Cost)/Sell' },
  { key: 'netcost', label: 'NetCost',   short: 'NETCOST', width: 82,  align: 'right', title: 'Landed cost incl. GST' },
  { key: 'batch',   label: 'Batch / Lot', short: 'BATCH', width: 92 },
  { key: 'expiry',  label: 'Expiry',    short: 'EXPIRY',  width: 96 },
  { key: 'reason',  label: 'Reason',    short: 'REASON',  width: 120 },
  { key: 'status',  label: 'Status',    short: 'STATUS',  width: 70 },
]
const INTAKE_COLLAPSED_W = 26   // folded strip width (px)

// ─────────────────────────────────────────────────────────────────────────────
// Helpers
// ─────────────────────────────────────────────────────────────────────────────

const num = (v) => (v === '' || v == null ? 0 : parseFloat(v) || 0)
const numNull = (v) => (v === '' || v == null ? null : parseFloat(v) || 0)
const today = () => {
  const d = new Date()
  return `${d.toLocaleString('en-US', { month: 'short' }).toUpperCase()}-${String(d.getDate()).padStart(2, '0')}-${d.getFullYear()}`
}
const todayISO = () => new Date().toISOString().slice(0, 10)

// Default row for a NEW product (not yet in catalogue)
const BLANK_NEW_ROW = (barcode = '') => ({
  _key: Math.random(),
  _type: 'new',          // 'new' | 'existing'
  _open: !!barcode,      // auto-expand if barcode came from scan
  _status: null,         // null | 'saving' | 'ok' | error string
  // product fields (for new)
  name: '', barcode, sku: '', category: '', unit: 'pcs',
  hsn_sac: '', brand: '', description: '',
  cgst_rate: '', sgst_rate: '',
  min_stock: '',
  wholesale_price: '',
  distributor_price: '',
  mrp: '',
  // intake fields
  qty: '',
  free: '',
  cost_price: '',
  selling_price: '',
  batch: today(),
  expiry: '',
  reason: '',
})

// Row seeded from an existing product
const ROW_FROM_PRODUCT = (product) => ({
  _key: Math.random(),
  _type: 'existing',
  _open: false,
  _status: null,
  _product: product,
  _price_mode: 'update',    // 'update' = overwrite product price | 'new_batch' = keep old price
  product_id: product.id,
  name: product.name || '',
  barcode: product.barcode || '',
  sku: product.sku || '',
  category: product.category || '',
  brand: product.brand || '',
  hsn_sac: product.hsn_sac || '',
  cgst_rate: product.cgst_rate != null ? String(product.cgst_rate) : '',
  sgst_rate: product.sgst_rate != null ? String(product.sgst_rate) : '',
  min_stock: product.min_stock != null ? String(product.min_stock) : '',
  description: product.description || '',
  wholesale_price: product.wholesale_price != null ? String(product.wholesale_price) : '',
  distributor_price: product.distributor_price != null ? String(product.distributor_price) : '',
  mrp: product.mrp != null ? String(product.mrp) : '',
  barcodes: product.barcodes || [],
  current_stock: product.stock_qty ?? product.quantity ?? 0,
  current_sell:  product.selling_price ?? null,   // shown as reference
  current_cost:  product.cost_price    ?? null,
  unit: product.unit || 'pcs',
  qty: '',
  free: '',
  cost_price: product.cost_price != null ? String(product.cost_price) : '',
  selling_price: product.selling_price != null ? String(product.selling_price) : '',
  batch: today(),
  expiry: '',
  reason: '',
})

// Parse a CSV file client-side. Returns array of plain objects.
function parseCSV(text) {
  const lines = text.trim().split('\n')
  if (lines.length < 2) return []
  const headers = lines[0].split(',').map(h => h.trim().replace(/^"|"$/g, '').toLowerCase())
  return lines.slice(1).map(line => {
    const vals = line.split(',').map(v => v.trim().replace(/^"|"$/g, ''))
    const obj = {}
    headers.forEach((h, i) => { obj[h] = vals[i] || '' })
    return obj
  })
}

// Map a CSV row (product columns) to either an intake row
const CSV_ALIASES = {
  'product name': 'name', 'product_name': 'name', 'name': 'name',
  'barcode': 'barcode', 'sku': 'sku',
  'quantity': 'qty', 'qty': 'qty', 'opening_stock': 'qty', 'stock': 'qty',
  'cost price': 'cost_price', 'cost_price': 'cost_price', 'unit_price': 'cost_price',
  'selling price': 'selling_price', 'selling_price': 'selling_price', 'retail price': 'selling_price',
  'mrp': 'selling_price',
  'category': 'category', 'unit': 'unit', 'hsn': 'hsn_sac', 'hsn_sac': 'hsn_sac',
  'batch': 'batch', 'expiry': 'expiry', 'expiry_date': 'expiry',
}

// ─────────────────────────────────────────────────────────────────────────────
// Sub-components
// ─────────────────────────────────────────────────────────────────────────────

function Badge({ type }) {
  const cfg = type === 'existing'
    ? { bg: 'rgba(20,184,166,.15)', color: '#14b8a6', text: 'IN STOCK' }
    : { bg: 'rgba(249,115,22,.15)', color: '#f97316', text: 'NEW' }
  return (
    <span style={{
      display: 'inline-block', padding: '2px 7px', borderRadius: 4,
      fontSize: '0.62rem', fontWeight: 800, letterSpacing: '0.06em',
      background: cfg.bg, color: cfg.color,
    }}>
      {cfg.text}
    </span>
  )
}

function StatusChip({ status }) {
  if (!status) return null
  if (status === 'ok')     return <span style={{ color: '#22c55e', fontWeight: 700, fontSize: '0.75rem' }}>✓ saved</span>
  if (status === 'saving') return <span style={{ color: 'var(--text-muted)', fontSize: '0.74rem' }}>saving…</span>
  return <span style={{ color: '#ef4444', fontSize: '0.71rem' }} title={status}>{String(status).slice(0, 38)}</span>
}

function TCell({ children, style = {} }) {
  return (
    <td style={{ padding: '5px 6px', verticalAlign: 'top', ...style }}>
      {children}
    </td>
  )
}

// Compact numeric input cell
function NumCell({ value, onChange, disabled, placeholder = '0', highlight }) {
  return (
    <input
      type="number"
      min={0}
      step="any"
      className="form-input"
      style={{
        width: '100%', height: 32, padding: '3px 7px', fontSize: '0.82rem',
        textAlign: 'right', fontVariantNumeric: 'tabular-nums',
        background: highlight ? 'rgba(20,184,166,.06)' : undefined,
      }}
      placeholder={placeholder}
      value={value}
      disabled={disabled}
      onChange={e => onChange(e.target.value)}
    />
  )
}

// Compact text input cell
function TextCell({ value, onChange, disabled, placeholder = '' }) {
  return (
    <input
      type="text"
      className="form-input"
      style={{ width: '100%', height: 32, padding: '3px 7px', fontSize: '0.79rem' }}
      placeholder={placeholder}
      value={value}
      disabled={disabled}
      onChange={e => onChange(e.target.value)}
    />
  )
}

// ─────────────────────────────────────────────────────────────────────────────
// Main Component
// ─────────────────────────────────────────────────────────────────────────────

export default function StockIntakeSheet({ products = [], onSaved, onExit, prefillProduct, rows = [], setRows, distributor, setDistributor, editingRowKey, setEditingRowKey, adjustments, isSidebarCollapsed, setIsSidebarCollapsed, onPrint }) {
  const { authFetch } = useAuth()

  const [globalRef, setGlobalRef] = useState('')   // bill reference, fills all empty reasons
  const [saving, setSaving] = useState(false)
  const [summary, setSummary] = useState(null)
  const [scanCode, setScanCode] = useState('')
  const [searching, setSearching] = useState(false)
  const [searchQ, setSearchQ] = useState('')
  const [showDrop, setShowDrop] = useState(false)
  const [uploading, setUploading] = useState(false)
  const [uploadErr, setUploadErr] = useState(null)
  const [scanErr, setScanErr] = useState(null)

  // ── Fold-collapsible columns (POS-style paper-fold strips) ─────────────────
  // Right-click a header → Collapse; click the folded strip (or the menu) to
  // expand. Persisted per device so the intake sheet reopens as it was left.
  const [collapsedCols, setCollapsedCols] = useState(() => {
    try { return JSON.parse(localStorage.getItem('stock_intake_collapsed_columns')) || {} } catch { return {} }
  })
  const [headerCtxMenu, setHeaderCtxMenu] = useState(null)
  const setColumnCollapsed = (key, val) => {
    const c = INTAKE_COLS.find(x => x.key === key)
    if (!c || c.collapsible === false) return
    setCollapsedCols(prev => {
      const next = { ...prev }
      if (val) next[key] = true; else delete next[key]
      try { localStorage.setItem('stock_intake_collapsed_columns', JSON.stringify(next)) } catch { /* ignore */ }
      return next
    })
  }
  const openHeaderMenu = (key, e) => {
    e.preventDefault()
    const c = INTAKE_COLS.find(x => x.key === key)
    const items = []
    if (c && c.collapsible !== false) {
      items.push(collapsedCols[key]
        ? { label: `Expand "${c.label}"`, action: () => setColumnCollapsed(key, false) }
        : { label: `Collapse "${c.label}"`, action: () => setColumnCollapsed(key, true) })
    }
    if (Object.keys(collapsedCols).length > 0) {
      items.push({ label: 'Expand all columns', action: () => {
        setCollapsedCols({})
        try { localStorage.removeItem('stock_intake_collapsed_columns') } catch { /* ignore */ }
      } })
    }
    if (items.length) setHeaderCtxMenu({ x: e.clientX, y: e.clientY, items })
  }
  // Fold the body cells of collapsed columns to a narrow strip via nth-child
  // (header th are rendered folded inline; body cells stay untouched in JSX).
  const collapsedBodyCss = INTAKE_COLS.map((c, i) => collapsedCols[c.key]
    ? `.intake-grid td:nth-child(${i + 1}){width:${INTAKE_COLLAPSED_W}px!important;min-width:${INTAKE_COLLAPSED_W}px!important;max-width:${INTAKE_COLLAPSED_W}px!important;padding:0!important;overflow:hidden;background:var(--bg-3);}
.intake-grid td:nth-child(${i + 1})>*{visibility:hidden!important;}`
    : '').filter(Boolean).join('\n')
  const intakeTableMinWidth = INTAKE_COLS.reduce((s, c) => s + (collapsedCols[c.key] ? INTAKE_COLLAPSED_W : c.width), 0) + 100

  const scanRef  = useRef(null)
  const fileRef  = useRef(null)

  const gross = rows.reduce((s, r) => s + (num(r.qty) * num(r.cost_price)), 0)
  const getRowGst = (r) => (num(r.cgst_rate) + num(r.sgst_rate)) || num(r.igst_rate)
  const taxTotal = rows.reduce((s, r) => s + (num(r.qty) * num(r.cost_price) * getRowGst(r) / 100), 0)
  const itemDisc = parseFloat(adjustments?.item_disc) || 0
  const cess = parseFloat(adjustments?.cess) || 0
  const cashDisc = parseFloat(adjustments?.cash_disc) || 0
  const payable = gross - itemDisc + taxTotal + cess - cashDisc

  // Focus scan bar on mount
  useEffect(() => {
    setTimeout(() => scanRef.current?.focus(), 80)
  }, [])

  // Pre-load a product from the catalogue '± Stock' button
  useEffect(() => {
    if (!prefillProduct) return
    addExistingRow(prefillProduct)
    setTimeout(() => scanRef.current?.focus(), 80)
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [prefillProduct])

  // ── Row helpers ─────────────────────────────────────────────────────────

  const setRow = (key, patch) => {
    setRows(prev => prev.map(r => r._key === key ? { ...r, ...patch, _status: null } : r))
  }

  const addBarcodeToRow = async (rowKey) => {
    const row = rows.find(r => r._key === rowKey)
    if (!row) return
    const code = (row._newBarcode || '').trim()
    if (!code) return
    if (row._type === 'existing') {
      try {
        const res = await authFetch(`/billing/products/${row.product_id}/barcodes`, {
          method: 'POST', body: JSON.stringify({ barcode: code }),
        })
        const data = await res.json().catch(() => ({}))
        if (!res.ok) throw new Error(data.detail || 'Could not add barcode.')
        
        setRow(rowKey, {
          barcodes: [...(row.barcodes || []), data.barcode ? data : { barcode: code }],
          _newBarcode: ''
        })
      } catch (err) {
        setScanErr(err.message)
      }
    }
  }

  const handleEditPopup = (row) => {
    if (!onEditProduct) return
    const merged = {
      ...(row._product || {}),
      id: row.product_id,
      name: row.name || '',
      barcode: row.barcode || '',
      sku: row.sku || '',
      category: row.category || '',
      unit: row.unit || 'pcs',
      brand: row.brand || '',
      hsn_sac: row.hsn_sac || '',
      cgst_rate: row.cgst_rate !== '' ? parseFloat(row.cgst_rate) : null,
      sgst_rate: row.sgst_rate !== '' ? parseFloat(row.sgst_rate) : null,
      min_stock: row.min_stock !== '' ? parseFloat(row.min_stock) : null,
      description: row.description || '',
      selling_price: row.selling_price !== '' ? parseFloat(row.selling_price) : (row._product?.selling_price || ''),
      cost_price: row.cost_price !== '' ? parseFloat(row.cost_price) : (row._product?.cost_price || ''),
      wholesale_price: row.wholesale_price !== '' ? parseFloat(row.wholesale_price) : (row._product?.wholesale_price || ''),
      distributor_price: row.distributor_price !== '' ? parseFloat(row.distributor_price) : (row._product?.distributor_price || ''),
      mrp: row.mrp !== '' ? parseFloat(row.mrp) : (row._product?.mrp || ''),
    }
    onEditProduct(merged)
  }

  const removeRow = (key) => setRows(prev => prev.filter(r => r._key !== key))

  // Add / merge: if same product_id already in rows → focus that row, else append
  const addExistingRow = useCallback((product) => {
    setRows(prev => {
      const existing = prev.find(r => r._type === 'existing' && r.product_id === product.id)
      if (existing) {
        // just highlight — don't duplicate
        return prev
      }
      return [...prev, ROW_FROM_PRODUCT(product)]
    })
  }, [])

  const addNewRow = useCallback((barcode = '') => {
    setRows(prev => [...prev, BLANK_NEW_ROW(barcode)])
  }, [])

  // ── Barcode scan ────────────────────────────────────────────────────────

  const handleScan = useCallback(async () => {
    const code = scanCode.trim()
    if (!code) return
    setScanErr(null); setSearching(true)
    try {
      const res = await authFetch(`/billing/sales/barcode/${encodeURIComponent(code)}`)
      if (res.ok) {
        const data = await res.json()
        const p = data.product || data
        if (p?.id) {
          // Check if row already exists for this product
          setRows(prev => {
            const exists = prev.find(r => r._type === 'existing' && r.product_id === p.id)
            if (exists) {
              // Flash the row instead of duplicating
              setScanCode('')
              return prev
            }
            setScanCode('')
            // The /sales/barcode payload is lean (no stock/cost). Enrich from
            // the full catalogue record we already hold so Current + Cost + the
            // "was ₹" reference show correctly instead of 0.
            const full = products.find(x => x.id === p.id)
            return [...prev, ROW_FROM_PRODUCT(full ? { ...p, ...full } : p)]
          })
          return
        }
      }
      // Not found — open a NEW row with this barcode
      addNewRow(code)
      setScanCode('')
    } catch (err) {
      logger.warn('[INTAKE] scan failed', err)
      setScanErr('Lookup failed — check connection')
    } finally {
      setSearching(false)
      setTimeout(() => scanRef.current?.focus(), 60)
    }
  }, [scanCode, authFetch, addNewRow, products])

  // ── Product search dropdown ─────────────────────────────────────────────

  const filteredProducts = searchQ.trim()
    ? products.filter(p => {
        const q = searchQ.toLowerCase()
        return p.name?.toLowerCase().includes(q) || p.sku?.toLowerCase().includes(q) || p.barcode?.includes(q)
      }).slice(0, 10)
    : []

  const pickSearchProduct = (p) => {
    addExistingRow(p)
    setSearchQ(''); setShowDrop(false)
    setTimeout(() => scanRef.current?.focus(), 60)
  }

  // ── Bill / CSV upload ───────────────────────────────────────────────────

  const handleFileUpload = async (file) => {
    if (!file) return
    setUploadErr(null); setUploading(true)
    const ext = file.name.split('.').pop().toLowerCase()

    if (ext === 'csv') {
      // Parse client-side
      try {
        const text = await file.text()
        const csvRows = parseCSV(text)
        const newRows = csvRows
          .filter(r => r.name || r.product_name || r.barcode)
          .map(r => {
            const mapped = {}
            Object.entries(r).forEach(([k, v]) => {
              const alias = CSV_ALIASES[k.toLowerCase()]
              if (alias) mapped[alias] = v
            })
            // Try to match to existing catalogue
            const name = mapped.name || ''
            const barcode = mapped.barcode || ''
            const match = products.find(p =>
              (barcode && (p.barcode === barcode || p.sku === barcode)) ||
              (name && p.name?.toLowerCase() === name.toLowerCase())
            )
            if (match) {
              const row = ROW_FROM_PRODUCT(match)
              row.qty         = mapped.qty || ''
              row.cost_price  = mapped.cost_price || ''
              row.selling_price = mapped.selling_price || ''
              row.batch       = mapped.batch || today()
              row.expiry      = mapped.expiry || ''
              return row
            }
            // New product from CSV
            const row = BLANK_NEW_ROW(barcode)
            Object.assign(row, { name: name, ...mapped })
            return row
          })
        setRows(prev => [...prev, ...newRows])
      } catch (e) {
        setUploadErr('CSV parse failed: ' + e.message)
      } finally {
        setUploading(false)
      }
      return
    }

    // PDF / image → AI OCR
    try {
      const fd = new FormData()
      fd.append('file', file)
      const res = await authFetch('/billing/purchases/upload', { method: 'POST', headers: {}, body: fd })
      if (!res.ok) {
        const err = await res.json().catch(() => ({}))
        throw new Error(err.detail || `Upload failed (${res.status})`)
      }
      const data = await res.json()
      const billRef = data.invoice_number || data.supplier_name || ''
      if (billRef && !globalRef) setGlobalRef(billRef)

      if (setDistributor) {
        setDistributor({
          vendor_id: null,
          name: data.supplier_name || '',
          gstin: data.supplier_gstin || '',
          pan: data.supplier_pan || '',
          fssai: data.supplier_fssai || '',
          phone: data.supplier_phone || '',
          address: data.supplier_address || '',
          invoice_no: data.invoice_number || '',
          invoice_date: data.invoice_date || todayISO(),
        })
      }

      const parsed = data.items || []
      const newRows = parsed.map(item => {
        const pid = item.product_id
        const match = pid ? products.find(p => p.id === pid) : null
        if (match) {
          const row = ROW_FROM_PRODUCT(match)
          row.qty          = String(item.quantity || '')
          row.cost_price   = String(item.unit_price || '')
          row.batch        = item.batch || today()
          row.expiry       = item.expiry || ''
          row._confidence  = item.confidence_score
          return row
        }
        // Unmatched from bill → new row
        const row = BLANK_NEW_ROW(item.barcode || '')
        row.name      = item.product_name || ''
        row.hsn_sac   = item.hsn_sac || ''
        row.unit      = item.unit || 'pcs'
        row.cgst_rate = String(item.cgst_rate || '')
        row.sgst_rate = String(item.sgst_rate || '')
        row.qty       = String(item.quantity || '')
        row.cost_price = String(item.unit_price || '')
        row.batch     = item.batch || today()
        row.expiry    = item.expiry || ''
        row._open     = true  // auto-open so user can confirm name
        return row
      })
      setRows(prev => [...prev, ...newRows])
    } catch (err) {
      setUploadErr(err.message || 'Upload failed')
    } finally {
      setUploading(false)
    }
  }

  // ── Save all ────────────────────────────────────────────────────────────

  const readyRows = rows.filter(r => {
    if (r._status === 'ok') return false
    if (num(r.qty) + num(r.free) <= 0) return false
    if (r._type === 'existing') return true
    return r.name?.trim()
  })

  const saveAll = async () => {
    if (readyRows.length === 0) return
    setSaving(true); setSummary(null)
    let ok = 0, failed = 0
    const keys = readyRows.map(r => r._key)

    for (const key of keys) {
      setRow(key, { _status: 'saving' })
      const row = rows.find(r => r._key === key)
      if (!row) continue

      const reason = row.reason?.trim() || globalRef.trim() || 'Stock intake'
      const batchNote = row.batch ? ` [batch: ${row.batch}]` : ''
      const note = reason + batchNote + (row.expiry ? ` [exp: ${row.expiry}]` : '')

      try {
        let pid = row.product_id

        // NEW product: create it first
        if (row._type === 'new') {
          const createRes = await authFetch('/billing/products', {
            method: 'POST',
            body: JSON.stringify({
              name: row.name.trim(),
              barcode: row.barcode || null,
              sku: row.sku || null,
              category: row.category || null,
              unit: row.unit || 'pcs',
              hsn_sac: row.hsn_sac || null,
              brand: row.brand || null,
              description: row.description || null,
              selling_price: num(row.selling_price),
              cost_price: num(row.cost_price),
              wholesale_price: row.wholesale_price !== '' ? num(row.wholesale_price) : 0,
              distributor_price: row.distributor_price !== '' ? num(row.distributor_price) : 0,
              mrp: row.mrp !== '' ? num(row.mrp) : 0,
              cgst_rate: num(row.cgst_rate),
              sgst_rate: num(row.sgst_rate),
              min_stock: num(row.min_stock),
              opening_stock: 0,
              attributes: {},
            }),
          })
          if (!createRes.ok) {
            const err = await createRes.json().catch(() => ({}))
            throw new Error(err.detail || `Create failed (${createRes.status})`)
          }
          const created = await createRes.json()
          pid = created.id
        }

        // Stock adjustment
        const adjRes = await authFetch(`/billing/products/${pid}/stock/adjustment`, {
          method: 'POST',
          body: JSON.stringify({ qty_delta: num(row.qty) + num(row.free), note }),
        })
        if (!adjRes.ok) {
          const err = await adjRes.json().catch(() => ({}))
          throw new Error(err.detail || `Stock update failed (${adjRes.status})`)
        }

        // Update product details on existing product
        if (row._type === 'existing') {
          const newSell = num(row.selling_price)
          const newCost = num(row.cost_price)
          const patchBody = {
            name: row.name?.trim(),
            barcode: row.barcode?.trim() || null,
            sku: row.sku?.trim() || null,
            category: row.category?.trim() || null,
            unit: row.unit || 'pcs',
            brand: row.brand?.trim() || null,
            hsn_sac: row.hsn_sac?.trim() || null,
            cgst_rate: row.cgst_rate !== '' ? num(row.cgst_rate) : null,
            sgst_rate: row.sgst_rate !== '' ? num(row.sgst_rate) : null,
            min_stock: row.min_stock !== '' ? num(row.min_stock) : null,
            description: row.description?.trim() || null,
            wholesale_price: row.wholesale_price !== '' ? num(row.wholesale_price) : null,
            distributor_price: row.distributor_price !== '' ? num(row.distributor_price) : null,
            mrp: row.mrp !== '' ? num(row.mrp) : null,
          }
          if (row._price_mode === 'update') {
            if (newSell > 0) patchBody.selling_price = newSell
            if (newCost > 0) patchBody.cost_price = newCost
          }
          await authFetch(`/billing/products/${pid}`, {
            method: 'PATCH',
            body: JSON.stringify(patchBody),
          }).catch(() => {}) // non-critical
        }

        setRow(key, { _status: 'ok' })
        ok++
      } catch (err) {
        setRow(key, { _status: err.message || 'Error' })
        failed++
      }
    }

    setSaving(false)
    setSummary({ ok, failed })
    if (ok > 0) onSaved?.(ok)
  }

  // ─────────────────────────────────────────────────────────────────────────
  // Render
  // ─────────────────────────────────────────────────────────────────────────

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', minHeight: 0 }}>

      {/* ── Top bar: scanner + search + upload + global ref ─────────────── */}
      <div style={{
        display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap',
        padding: '10px 0', borderBottom: '2px solid var(--border)', flexShrink: 0,
      }}>
        {/* Scanner input */}
        <div style={{ display: 'flex', gap: 6, flex: '0 0 auto' }}>
          <div style={{ position: 'relative' }}>
            <span style={{
              position: 'absolute', left: 10, top: '50%', transform: 'translateY(-50%)',
              color: 'var(--accent)', display: 'flex', pointerEvents: 'none',
            }}>
              <ZapIcon size={15} />
            </span>
            <input
              ref={scanRef}
              className="form-input"
              style={{
                paddingLeft: 32, width: 240, fontFamily: "'Geist Mono',monospace",
                fontSize: '0.85rem', border: '2px solid var(--accent)',
                borderRadius: 8,
              }}
              placeholder="Scan barcode… (Enter)"
              value={scanCode}
              onChange={e => { setScanCode(e.target.value); setScanErr(null) }}
              onKeyDown={e => { if (e.key === 'Enter') { e.preventDefault(); handleScan() } }}
              disabled={saving}
            />
          </div>
          <button
            className="btn btn-primary btn-sm"
            onClick={handleScan}
            disabled={saving || searching || !scanCode.trim()}
            style={{ whiteSpace: 'nowrap' }}
          >
            {searching ? '…' : 'Find'}
          </button>
        </div>

        {/* Product name search */}
        <div style={{ position: 'relative', flex: '1 1 200px', maxWidth: 260 }}>
          <span style={{
            position: 'absolute', left: 9, top: '50%', transform: 'translateY(-50%)',
            color: 'var(--text-muted)', display: 'flex', pointerEvents: 'none',
          }}>
            <SearchIcon size={14} />
          </span>
          <input
            className="form-input"
            style={{ paddingLeft: 30, fontSize: '0.82rem' }}
            placeholder="Search existing product…"
            value={searchQ}
            onChange={e => { setSearchQ(e.target.value); setShowDrop(true) }}
            onFocus={() => setShowDrop(true)}
            onBlur={() => setTimeout(() => setShowDrop(false), 180)}
            disabled={saving}
          />
          {showDrop && filteredProducts.length > 0 && (
            <div style={{
              position: 'absolute', top: '100%', left: 0, zIndex: 200,
              background: 'var(--bg-1)', border: '1px solid var(--border)',
              borderRadius: 8, boxShadow: '0 8px 24px rgba(0,0,0,.18)',
              width: '100%', maxHeight: 220, overflowY: 'auto', marginTop: 3,
            }}>
              {filteredProducts.map(p => (
                <button
                  key={p.id}
                  type="button"
                  onMouseDown={() => pickSearchProduct(p)}
                  style={{
                    display: 'flex', width: '100%', textAlign: 'left', gap: 10,
                    padding: '8px 12px', background: 'transparent', border: 'none',
                    cursor: 'pointer', fontSize: '0.8rem', alignItems: 'center',
                    borderBottom: '1px solid var(--border)',
                  }}
                  onMouseEnter={e => e.currentTarget.style.background = 'var(--bg-2)'}
                  onMouseLeave={e => e.currentTarget.style.background = 'transparent'}
                >
                  <span style={{ flex: 1, fontWeight: 600 }}>{p.name}</span>
                  <span style={{ fontSize: '0.71rem', color: p.stock_qty <= 0 ? '#ef4444' : 'var(--text-muted)', fontVariantNumeric: 'tabular-nums' }}>
                    {p.stock_qty ?? p.quantity ?? 0} {p.unit || 'pcs'}
                  </span>
                </button>
              ))}
            </div>
          )}
        </div>

        {/* Add blank new-product row */}
        <button
          className="btn btn-secondary btn-sm"
          onClick={() => addNewRow('')}
          disabled={saving}
        >
          <PlusIcon size={13} /> New product
        </button>

        <div style={{ flex: 1 }} />

        {/* Global bill reference */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <label style={{ fontSize: '0.73rem', fontWeight: 600, color: 'var(--text-muted)', whiteSpace: 'nowrap' }}>
            Bill ref:
          </label>
          <input
            className="form-input"
            style={{ width: 140, fontSize: '0.8rem' }}
            placeholder="INV#, GRN# …"
            value={globalRef}
            onChange={e => setGlobalRef(e.target.value)}
            disabled={saving}
          />
        </div>

        {/* Upload bill */}
        <div style={{ position: 'relative' }}>
          <input
            ref={fileRef}
            type="file"
            accept=".pdf,.png,.jpg,.jpeg,.webp,.csv"
            style={{ display: 'none' }}
            onChange={e => { handleFileUpload(e.target.files?.[0]); e.target.value = '' }}
          />
          <button
            className="btn btn-secondary btn-sm"
            onClick={() => fileRef.current?.click()}
            disabled={saving || uploading}
            title="Upload PDF, image, or CSV to auto-fill rows"
            style={{ whiteSpace: 'nowrap' }}
          >
            <UploadIcon size={13} />
            {uploading ? ' Parsing…' : ' Upload bill'}
          </button>
        </div>
      </div>

      {/* Error bars */}
      {scanErr && (
        <div className="alert alert-danger" style={{ margin: '6px 0', padding: '6px 12px', fontSize: '0.8rem', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <span>{scanErr}</span>
          <button onClick={() => setScanErr(null)} style={{ marginLeft: 8, background: 'none', border: 'none', cursor: 'pointer', color: 'inherit', display: 'inline-flex', alignItems: 'center' }}>
            <CloseIcon size={10} strokeWidth={2.5} />
          </button>
        </div>
      )}
      {uploadErr && (
        <div className="alert alert-danger" style={{ margin: '6px 0', padding: '6px 12px', fontSize: '0.8rem', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <span>{uploadErr}</span>
          <button onClick={() => setUploadErr(null)} style={{ marginLeft: 8, background: 'none', border: 'none', cursor: 'pointer', color: 'inherit', display: 'inline-flex', alignItems: 'center' }}>
            <CloseIcon size={10} strokeWidth={2.5} />
          </button>
        </div>
      )}

      {/* ── Table ────────────────────────────────────────────────────────── */}
      <div style={{ flex: 1, overflow: 'auto', minHeight: 0 }}>
        {rows.length === 0 ? (
          <div style={{
            display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center',
            height: '100%', gap: 12, color: 'var(--text-muted)',
          }}>
            <ZapIcon size={32} />
            <div style={{ fontSize: '1rem', fontWeight: 600 }}>Scan a barcode or upload a bill to start</div>
            <div style={{ fontSize: '0.8rem' }}>
              Each scan adds a row · Upload PDF/CSV to fill many rows at once
            </div>
          </div>
        ) : (
          <>
          {/* Match the POS cart table look */}
          <style>{`
            .intake-grid { width: 100%; border-collapse: separate; border-spacing: 0; text-align: left; }
            .intake-grid thead tr { background: var(--bg-3); }
            .intake-grid th {
              padding: 6px 7px; font-size: 10px; font-weight: 600; letter-spacing: 0.04em;
              text-transform: uppercase; color: var(--text-secondary); white-space: nowrap;
              border-bottom: 1px solid var(--border); border-right: 1px solid var(--border);
            }
            .intake-grid td {
              padding: 3px 5px; font-size: 12px; vertical-align: middle;
              border-bottom: 1px solid var(--border); border-right: 1px solid var(--border);
            }
            .intake-grid th:last-child, .intake-grid td:last-child { border-right: none; }
            .intake-grid tbody tr:hover { background: var(--accent-glow); }
            .intake-grid .form-input {
              border: 1px solid var(--border) !important; border-radius: 4px !important;
              background: var(--bg-2) !important; height: 27px !important;
              padding: 3px 4px !important; text-align: center; box-shadow: none !important;
            }
            .intake-grid .form-input:focus {
              border-color: var(--accent) !important; background: var(--bg) !important;
            }
            .intake-grid .row-del { display: none; }
            .intake-grid tbody tr:hover .row-sno { display: none; }
            .intake-grid tbody tr:hover .row-del { display: inline-flex; }
            .intake-grid .row-edit-btn { display: none; }
            .intake-grid tbody tr:hover .row-edit-btn { display: inline-flex; }
            .intake-grid .row-edit-btn.is-active { display: inline-flex; }
           `}</style>
          {/* Folded-column body strips (POS-style). Header th are folded inline. */}
          {collapsedBodyCss && <style>{collapsedBodyCss}</style>}
          <table className="intake-grid" style={{ fontSize: '0.78rem', minWidth: intakeTableMinWidth }}>
            <thead>
              <tr>
                {INTAKE_COLS.map((c) => {
                  const collapsed = !!collapsedCols[c.key]
                  const canCollapse = c.collapsible !== false
                  return (
                    <th
                      key={c.key}
                      title={collapsed
                        ? `Show "${c.label}"`
                        : (canCollapse ? `${c.title ? c.title + ' · ' : ''}Right-click to collapse` : (c.title || undefined))}
                      onClick={collapsed ? () => setColumnCollapsed(c.key, false) : undefined}
                      onContextMenu={canCollapse ? (e) => openHeaderMenu(c.key, e) : undefined}
                      style={{
                        padding: collapsed ? '6px 0' : '7px 8px',
                        fontSize: '0.72rem', fontWeight: 800, textTransform: 'uppercase',
                        letterSpacing: '0.06em', color: collapsed ? 'var(--accent)' : 'var(--text-secondary)',
                        textAlign: collapsed ? 'center' : (c.align || 'left'),
                        verticalAlign: collapsed ? 'middle' : undefined,
                        whiteSpace: 'nowrap', borderBottom: '1px solid var(--border)',
                        background: collapsed ? 'var(--bg-3)' : 'var(--bg-2, rgba(0,0,0,.03))',
                        cursor: canCollapse ? 'pointer' : 'default', userSelect: 'none',
                        ...(collapsed
                          ? { width: INTAKE_COLLAPSED_W, minWidth: INTAKE_COLLAPSED_W, maxWidth: INTAKE_COLLAPSED_W }
                          : { width: c.width }),
                      }}
                    >
                      {collapsed ? (
                        // Vertical column name (POS-style folded strip).
                        <span style={{
                          display: 'inline-block', writingMode: 'vertical-rl', transform: 'rotate(180deg)',
                          fontSize: '9px', fontWeight: 800, letterSpacing: '0.08em', lineHeight: '24px',
                          whiteSpace: 'nowrap',
                        }}>
                          {c.short || c.label}
                        </span>
                      ) : c.label}
                    </th>
                  )
                })}
              </tr>
            </thead>
            <tbody>
              {rows.map((r, _idx) => {
                const done = r._status === 'ok'
                const rowStyle = {
                  opacity: done ? 0.5 : 1,
                  background: r._type === 'new' ? 'rgba(249,115,22,.04)' : 'transparent',
                  borderBottom: '1px solid var(--border)',
                }
                const cellDisabled = done || saving

                // Live figures for the reference-style columns (all computed).
                const _q = parseFloat(r.qty) || 0
                const _c = parseFloat(r.cost_price) || 0
                const _s = parseFloat(r.selling_price) || 0
                const _m = parseFloat(r.mrp) || 0
                const _f = parseFloat(r.free) || 0
                const _gst = (parseFloat(r.cgst_rate) || 0) + (parseFloat(r.sgst_rate) || 0) || (parseFloat(r.igst_rate) || 0)
                const _amount = _q * _c                       // taxable value (cost is before-tax)
                const _taxAmt = _amount * _gst / 100
                const _netAmt = _amount + _taxAmt             // amount incl. GST (payable to supplier)
                const _disc = _m > 0 && _s > 0 ? ((_m - _s) / _m) * 100 : null
                const _discAmt = _m > 0 && _s > 0 && _m > _s ? (_m - _s) : null
                const _roi = _s > 0 && _c > 0 ? ((_s - _c) / _c) * 100 : null
                const _profit = _s > 0 && _c > 0 ? ((_s - _c) / _s) * 100 : null
                const _netCost = _c > 0 ? _c * (1 + _gst / 100) : null   // landed cost incl. GST
                const _money2 = n => (n != null && n !== 0 ? n.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 }) : '—')

                return (
                  <React.Fragment key={r._key}>
                    <tr style={rowStyle}>
                      {/* # serial (delete on hover, POS-style) */}
                      <TCell style={{ textAlign: 'center', verticalAlign: 'middle', padding: '0 2px' }}>
                        <span className="row-sno" style={{ fontSize: '0.72rem', color: 'var(--text-muted)', fontVariantNumeric: 'tabular-nums' }}>{_idx + 1}</span>
                        <button className="row-del" type="button" onClick={() => removeRow(r._key)} disabled={saving}
                          title="Remove this row"
                          style={{ background: 'transparent', border: 'none', cursor: 'pointer', color: '#ef4444', alignItems: 'center', justifyContent: 'center', margin: '0 auto' }}>
                          <CloseIcon size={10} strokeWidth={2} />
                        </button>
                      </TCell>

                      {/* Product name + inline edit pencil (edit/delete no longer own columns) */}
                      <TCell>
                        <div style={{ display: 'flex', alignItems: 'flex-start', gap: 5 }}>
                          <div style={{ flex: 1, minWidth: 0 }}>
                            {r._type === 'existing' ? (
                              <div>
                                <div style={{ fontWeight: 600, fontSize: '0.82rem', lineHeight: 1.2 }}>{r.name}</div>
                                {r._confidence != null && r._confidence < 0.95 && (
                                  <div style={{ fontSize: '0.63rem', color: '#eab308' }}>
                                    ⚠ {Math.round(r._confidence * 100)}% match from bill
                                  </div>
                                )}
                                <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginTop: 3, flexWrap: 'wrap' }}>
                                  {(r.current_cost != null || r.current_sell != null) && (
                                    <span style={{ fontSize: '0.6rem', color: 'var(--text-muted)', whiteSpace: 'nowrap' }}>
                                      was{r.current_cost != null ? ` cost ₹${r.current_cost}` : ''}{r.current_sell != null ? ` · sell ₹${r.current_sell}` : ''}
                                    </span>
                                  )}
                                  <button
                                    type="button"
                                    title={r._price_mode === 'update'
                                      ? 'Mode: Update product price (click to switch to New Batch)'
                                      : 'Mode: New Batch — old price kept (click to switch to Update)'}
                                    onClick={() => setRow(r._key, { _price_mode: r._price_mode === 'update' ? 'new_batch' : 'update' })}
                                    style={{
                                      fontSize: '0.56rem', fontWeight: 700, lineHeight: 1,
                                      padding: '2px 5px', borderRadius: 4, cursor: 'pointer', border: 'none',
                                      background: r._price_mode === 'update' ? 'rgba(192,97,42,.15)' : 'rgba(99,102,241,.15)',
                                      color: r._price_mode === 'update' ? 'var(--accent)' : '#818cf8',
                                    }}
                                  >
                                    {r._price_mode === 'update' ? '↑ Update price' : '⊕ New Batch'}
                                  </button>
                                </div>
                              </div>
                            ) : (
                              <TextCell
                                value={r.name}
                                placeholder="Product name *"
                                disabled={cellDisabled}
                                onChange={v => setRow(r._key, { name: v })}
                              />
                            )}
                          </div>
                          <button
                            type="button"
                            className={`row-edit-btn ${editingRowKey === r._key ? 'is-active' : ''}`}
                            onClick={() => {
                              const nextKey = editingRowKey === r._key ? null : r._key
                              setEditingRowKey(nextKey)
                              if (nextKey && isSidebarCollapsed) {
                                setIsSidebarCollapsed(false)
                              }
                            }}
                            title={r._type === 'new' ? 'More fields' : 'Edit details'}
                            style={{
                              flexShrink: 0, marginTop: 2,
                              background: editingRowKey === r._key ? 'var(--accent-muted, rgba(192,97,42,.14))' : 'transparent',
                              border: '1px solid var(--border)', borderRadius: 4, cursor: 'pointer',
                              padding: 0, alignItems: 'center', justifyContent: 'center',
                              color: editingRowKey === r._key ? 'var(--accent)' : 'var(--text-muted)',
                              borderColor: editingRowKey === r._key ? 'var(--accent)' : 'var(--border)',
                              height: 22, width: 22
                            }}
                          >
                            <EditIcon size={11} />
                          </button>
                        </div>
                      </TCell>

                      {/* Type badge */}
                      <TCell style={{ verticalAlign: 'middle' }}>
                        <Badge type={r._type} />
                      </TCell>

                      {/* Current stock */}
                      <TCell style={{ textAlign: 'right', verticalAlign: 'middle' }}>
                        {r._type === 'existing' ? (
                          <span style={{
                            fontWeight: 700, fontSize: '0.88rem',
                            color: r.current_stock <= 0 ? '#ef4444' : 'var(--text-primary)',
                            fontVariantNumeric: 'tabular-nums',
                          }}>
                            {r.current_stock}
                            <span style={{ fontSize: '0.65rem', color: 'var(--text-muted)', marginLeft: 2 }}>{r.unit}</span>
                          </span>
                        ) : (
                          <span style={{ color: 'var(--text-muted)', fontSize: '0.72rem' }}>—</span>
                        )}
                      </TCell>

                      {/* +Qty */}
                      <TCell>
                        <NumCell
                          value={r.qty}
                          onChange={v => setRow(r._key, { qty: v })}
                          disabled={cellDisabled}
                          highlight={r._type === 'existing'}
                        />
                      </TCell>

                      {/* Free units (added to stock, no cost) */}
                      <TCell>
                        <NumCell
                          value={r.free}
                          onChange={v => setRow(r._key, { free: v })}
                          disabled={cellDisabled}
                          placeholder="0"
                        />
                      </TCell>

                      {/* Cost price (Rate — before tax) */}
                      <TCell>
                        <NumCell
                          value={r.cost_price}
                          onChange={v => setRow(r._key, { cost_price: v })}
                          disabled={cellDisabled}
                          placeholder="cost"
                        />
                      </TCell>

                      {/* Selling price */}
                      <TCell>
                        <NumCell
                          value={r.selling_price}
                          onChange={v => setRow(r._key, { selling_price: v })}
                          disabled={cellDisabled}
                          placeholder="sell"
                        />
                      </TCell>

                      {/* MRP (editable — persists with the row) */}
                      <TCell>
                        <NumCell
                          value={r.mrp}
                          onChange={v => setRow(r._key, { mrp: v })}
                          disabled={cellDisabled}
                          placeholder="mrp"
                        />
                      </TCell>

                      {/* Disc% off MRP (computed) */}
                      <TCell style={{ textAlign: 'right', verticalAlign: 'middle' }}>
                        <span style={{ fontSize: '0.76rem', color: 'var(--text-muted)', fontVariantNumeric: 'tabular-nums' }}>
                          {_disc != null ? `${_disc.toFixed(1)}%` : '—'}
                        </span>
                      </TCell>

                      {/* Disc Amt (MRP − Sell per unit) */}
                      <TCell style={{ textAlign: 'right', verticalAlign: 'middle' }}>
                        <span style={{ fontSize: '0.76rem', color: 'var(--text-muted)', fontVariantNumeric: 'tabular-nums' }}>{_money2(_discAmt)}</span>
                      </TCell>

                      {/* Tax% (GST rate) */}
                      <TCell style={{ textAlign: 'right', verticalAlign: 'middle' }}>
                        <span style={{ fontSize: '0.76rem', color: 'var(--text-muted)', fontVariantNumeric: 'tabular-nums' }}>{_gst ? `${_gst.toFixed(0)}%` : '—'}</span>
                      </TCell>

                      {/* Tax Amt (GST on amount) */}
                      <TCell style={{ textAlign: 'right', verticalAlign: 'middle' }}>
                        <span style={{ fontSize: '0.76rem', color: 'var(--text-muted)', fontVariantNumeric: 'tabular-nums' }}>{_money2(_taxAmt)}</span>
                      </TCell>

                      {/* Amount = Qty × Cost (before tax) */}
                      <TCell style={{ textAlign: 'right', verticalAlign: 'middle' }}>
                        <span style={{ fontSize: '0.8rem', fontWeight: 600, fontVariantNumeric: 'tabular-nums' }}>
                          {_amount > 0 ? _amount.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 }) : '—'}
                        </span>
                      </TCell>

                      {/* Net Amt = Amount + Tax (payable to supplier) */}
                      <TCell style={{ textAlign: 'right', verticalAlign: 'middle' }}>
                        <span style={{ fontSize: '0.8rem', fontWeight: 700, fontVariantNumeric: 'tabular-nums' }}>{_money2(_netAmt)}</span>
                      </TCell>

                      {/* ROI% return on cost (computed) */}
                      <TCell style={{ textAlign: 'right', verticalAlign: 'middle' }}>
                        <span style={{ fontSize: '0.76rem', fontVariantNumeric: 'tabular-nums', color: _roi == null ? 'var(--text-muted)' : _roi >= 0 ? 'var(--success, #16a34a)' : '#ef4444' }}>
                          {_roi != null ? `${_roi.toFixed(1)}%` : '—'}
                        </span>
                      </TCell>

                      {/* Profit% margin (computed) */}
                      <TCell style={{ textAlign: 'right', verticalAlign: 'middle' }}>
                        <span style={{
                          fontSize: '0.76rem', fontVariantNumeric: 'tabular-nums',
                          color: _profit == null ? 'var(--text-muted)' : _profit >= 0 ? 'var(--success, #16a34a)' : '#ef4444',
                        }}>
                          {_profit != null ? `${_profit.toFixed(1)}%` : '—'}
                        </span>
                      </TCell>

                      {/* NetCost = cost incl. GST (computed) */}
                      <TCell style={{ textAlign: 'right', verticalAlign: 'middle' }}>
                        <span style={{ fontSize: '0.76rem', color: 'var(--text-muted)', fontVariantNumeric: 'tabular-nums' }}>{_money2(_netCost)}</span>
                      </TCell>

                      {/* Batch */}
                      <TCell>
                        <TextCell
                          value={r.batch}
                          onChange={v => setRow(r._key, { batch: v })}
                          disabled={cellDisabled}
                          placeholder={today()}
                        />
                      </TCell>

                      {/* Expiry */}
                      <TCell>
                        <input
                          type="date"
                          className="form-input"
                          style={{ width: '100%', height: 32, padding: '3px 6px', fontSize: '0.76rem' }}
                          value={r.expiry}
                          disabled={cellDisabled}
                          onChange={e => setRow(r._key, { expiry: e.target.value })}
                        />
                      </TCell>

                      {/* Reason */}
                      <TCell>
                        <TextCell
                          value={r.reason}
                          onChange={v => setRow(r._key, { reason: v })}
                          disabled={cellDisabled}
                          placeholder={globalRef || 'reason / bill no.'}
                        />
                      </TCell>

                      {/* Status */}
                      <TCell style={{ verticalAlign: 'middle' }}>
                        <StatusChip status={r._status} />
                      </TCell>

                    </tr>

                  </React.Fragment>
                )
              })}
            </tbody>
          </table>
          </>
        )}
      </div>

      {/* Right-click header → collapse/expand columns (folded strips persist) */}
      <ContextMenu menu={headerCtxMenu} onClose={() => setHeaderCtxMenu(null)} />


      {/* ── Footer: summary + save ───────────────────────────────────────── */}
      <div style={{
        display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap',
        padding: '10px 0', borderTop: '1px solid var(--border)', flexShrink: 0,
      }}>
        <span style={{ fontSize: '0.79rem', color: 'var(--text-muted)', flex: 1 }}>
          {summary ? (
            <b style={{ color: summary.failed ? '#ef4444' : '#22c55e' }}>
              ✓ {summary.ok} saved{summary.failed ? ` · ${summary.failed} failed — fix and save again` : ''}
            </b>
          ) : rows.length === 0 ? (
            'No items yet — scan a barcode or upload a bill'
          ) : (
            `${readyRows.length} item${readyRows.length !== 1 ? 's' : ''} ready · ${rows.filter(r => r._status === 'ok').length} already saved`
          )}
        </span>

        {isSidebarCollapsed && rows.length > 0 && (
          <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
            <div
              onClick={() => setIsSidebarCollapsed(false)}
              style={{
                display: 'flex', alignItems: 'center', gap: 14,
                padding: '6px 12px', background: 'var(--bg-3)',
                border: '1px solid var(--border)', borderRadius: 6,
                fontSize: '0.78rem', cursor: 'pointer',
                transition: 'background .15s, border-color .15s',
              }}
              onMouseEnter={e => { e.currentTarget.style.background = 'var(--bg-4)'; e.currentTarget.style.borderColor = 'var(--accent)' }}
              onMouseLeave={e => { e.currentTarget.style.background = 'var(--bg-3)'; e.currentTarget.style.borderColor = 'var(--border)' }}
              title="Click to expand distributor & summary details"
            >
              {distributor?.name && (
                <div>
                  <span style={{ color: 'var(--text-muted)' }}>Distributor:</span>{' '}
                  <strong style={{ color: 'var(--accent)' }}>{distributor.name}</strong>
                </div>
              )}
              {distributor?.invoice_no && (
                <div>
                  <span style={{ color: 'var(--text-muted)' }}>Inv:</span>{' '}
                  <strong>{distributor.invoice_no}</strong>
                </div>
              )}
              <div>
                <span style={{ color: 'var(--text-muted)' }}>Payable:</span>{' '}
                <strong style={{ color: '#22c55e' }}>₹{payable.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</strong>
              </div>
              <div style={{ fontSize: '0.68rem', color: 'var(--text-muted)', marginLeft: 4 }}>
                Expand ↗
              </div>
            </div>
            <button
              className="btn btn-secondary"
              type="button"
              style={{ height: 32, padding: '0 10px', display: 'inline-flex', alignItems: 'center', gap: 5, fontSize: '0.76rem', fontWeight: 600, marginRight: 6 }}
              onClick={onPrint}
              title="Print Purchase / GRN Summary"
            >
              <PrinterIcon size={12} /> Print
            </button>
          </div>
        )}

        {onExit && (
          <button className="btn btn-secondary" disabled={saving} onClick={onExit}>
            {summary?.ok && !summary?.failed ? 'Done' : 'Cancel'}
          </button>
        )}
        <button
          className="btn btn-primary"
          style={{ fontWeight: 700, minWidth: 140 }}
          disabled={saving || readyRows.length === 0}
          onClick={saveAll}
        >
          {saving
            ? <><span className="spinner" style={{ width: 13, height: 13, borderWidth: 2, marginRight: 6 }} />Saving…</>
            : `Save ${readyRows.length || ''} item${readyRows.length !== 1 ? 's' : ''}`
          }
        </button>
      </div>
    </div>
  )
}
