// ============================================================================
// Page: Stock.jsx  [fullscreen POS-style inventory — v2]
// Description: Inventory & Catalog Manager. Handles product item catalog creation,
//              stock adjustments, barcode bindings, and stock transfers between godowns — v9.
// ============================================================================
import React, { useEffect, useState, useCallback, useRef } from 'react'
import PageShell from '../components/common/PageShell'
import WorkspaceTopBar, { WsDivider } from '../components/common/WorkspaceTopBar'
import { useAuth, useBusinessConfig } from '../contexts/AuthContext'
import { AlertIcon, CheckIcon, CloseIcon, DownloadIcon, EditIcon, InventoryIcon, PlusIcon, SearchIcon, SyncIcon, UploadIcon, ZapIcon, ExpandIcon, SidebarIcon } from '../components/Icons'
import { logger } from '../utils/logger'
import CustomSelect from '../components/common/CustomSelect'
import LabelPrintModal from '../components/stock/LabelPrintModal'
import ProductFormModal, { EMPTY_PRODUCT } from '../components/stock/ProductFormModal'
import ScanStockInModal from '../components/stock/ScanStockInModal'
import BulkAddProductsModal from '../components/stock/BulkAddProductsModal'
import StockIntakeSheet from '../components/stock/StockIntakeSheet'
import IntakePurchasePanel from '../components/stock/IntakePurchasePanel'
import { usePageLifecycle } from '../hooks/usePageLifecycle'
import ContextMenu from '../components/common/ContextMenu'
import UnsavedChangesModal from '../components/common/UnsavedChangesModal'

const fmt = (n) =>
  n != null ? `₹${Number(n).toLocaleString('en-IN', { maximumFractionDigits: 2 })}` : '—'

// Compact numeric (no symbol — the header carries ₹) and percent formatters for
// the dense inventory grid.
const num = (n) =>
  n != null && !Number.isNaN(Number(n))
    ? Number(n).toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
    : '—'
const pct = (n) => (n != null && !Number.isNaN(n) ? `${n.toFixed(1)}%` : '—')

// Total GST rate for a product (intra-state CGST+SGST, else inter-state IGST).
const gstOf = (p) =>
  (Number(p.cgst_rate) || 0) + (Number(p.sgst_rate) || 0) || (Number(p.igst_rate) || 0)

// Derived cost/margin figures shown in the grid (all computed, nothing stored):
//   ROI%     = (sell-cost)/cost   · return on cost
//   Profit%  = (sell-cost)/sell   · margin on selling price
//   Disc%    = (mrp-sell)/mrp     · discount off MRP
//   NetCost  = cost × (1+gst)     · landed cost incl. GST
//   NetMRP   = mrp ÷ (1+gst)      · MRP net of GST (taxable value)
function deriveInv(p) {
  const gst = gstOf(p)
  const cost = Number(p.cost_price) || 0
  const sell = Number(p.selling_price) || 0
  const mrp = Number(p.mrp) || 0
  return {
    gst,
    cost, sell, mrp,
    roi: cost > 0 ? ((sell - cost) / cost) * 100 : null,
    profit: sell > 0 ? ((sell - cost) / sell) * 100 : null,
    discPct: mrp > 0 ? ((mrp - sell) / mrp) * 100 : null,
    netCost: cost > 0 ? cost * (1 + gst / 100) : null,
    netMrp: mrp > 0 ? mrp / (1 + gst / 100) : null,
  }
}

const defaultAdjust = {
  product_id: '',
  movement_type: 'stock_in',
  quantity: '',
  reason: '',
  reference: '',
}

const defaultTransfer = {
  from_godown_id: '',
  to_godown_id: '',
  product_id: '',
  quantity: '',
  notes: '',
}

function getStatus(product) {
  const qty = parseFloat(product.stock_qty ?? product.quantity ?? 0)
  const min = parseFloat(product.min_stock ?? 0)
  if (qty <= 0) return 'Out'
  if (qty <= min) return 'Low'
  return 'In Stock'
}

export default function Stock({ embedded = false, headerTabs = null }) {
  const { authFetch, settings } = useAuth()
  const { attributesSchema } = useBusinessConfig()
  const settingsRef = useRef(settings)
  useEffect(() => {
    settingsRef.current = settings
  }, [settings])

  const [products, setProducts]             = useState([])
  const [godowns, setGodowns]               = useState([])
  const [transfers, setTransfers]           = useState([])
  const [loading, setLoading]               = useState(true)
  const [search, setSearch]                 = useState('')
  const [catFilter, setCatFilter]           = useState('')
  const [activeTab, setActiveTab]           = useState('catalogue') // 'catalogue' | 'intake' | 'godowns'
  const [isFullScreen, setIsFullScreen] = useState(false)
  const [showAddModal, setShowAddModal]     = useState(false)
  const [showLabelModal, setShowLabelModal] = useState(false)
  const [showScanModal, setShowScanModal]   = useState(false)
  const [scanInitialCode, setScanInitialCode] = useState('')   // scan typed into the smart search box
  const [showBulkAdd, setShowBulkAdd]       = useState(false)
  const [editProduct, setEditProduct]       = useState(null)   // product row → edit mode
  const [prefillBarcode, setPrefillBarcode] = useState('')     // unknown scan → add flow
  const [selectedIds, setSelectedIds]       = useState(new Set())  // row selection → label printing
  const [exporting, setExporting]           = useState(false)

  const toggleSelected = (id) => setSelectedIds(prev => {
    const next = new Set(prev)
    if (next.has(id)) next.delete(id); else next.add(id)
    return next
  })

  const handleExport = async () => {
    setExporting(true)
    try {
      const res = await authFetch('/billing/export/products')
      if (!res.ok) throw new Error(res.status === 403 ? 'Export is owner-only.' : 'Export failed.')
      const blob = await res.blob()
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url; a.download = 'products_export.csv'
      document.body.appendChild(a); a.click(); a.remove()
      setTimeout(() => URL.revokeObjectURL(url), 5000)
    } catch (err) {
      setAlert({ type: 'danger', msg: err.message || 'Export failed.' })
    } finally {
      setExporting(false)
    }
  }

  // Smart search box doubles as the scanner input: Enter on a scanned code
  // opens the stock-in flow with the code already looked up.
  const handleSearchEnter = () => {
    const code = search.trim()
    if (!code) return
    setScanInitialCode(code)
    setShowScanModal(true)
  }
  const [showAdjustModal, setShowAdjustModal] = useState(false)
  const [showTransferModal, setShowTransferModal] = useState(false)
  const [adjustForm, setAdjustForm]         = useState(defaultAdjust)
  const [transferForm, setTransferForm]     = useState(defaultTransfer)
  
  const [newGodownName, setNewGodownName]   = useState('')
  const [newGodownAddress, setNewGodownAddress] = useState('')
  
  const [submitting, setSubmitting]         = useState(false)
  const [alert, setAlert]                   = useState(null)

  const formatError = (err, fallback) => {
    if (!err) return fallback
    if (typeof err.detail === 'string') return err.detail
    if (Array.isArray(err.detail)) {
      return err.detail.map(d => `${d.loc ? d.loc.join('.') : 'error'}: ${d.msg || ''}`).join(', ')
    }
    if (err.detail && typeof err.detail === 'object') {
      return JSON.stringify(err.detail)
    }
    return err.message || fallback
  }

  const load = useCallback(() => {
    setLoading(true)
    Promise.all([
      authFetch('/billing/products').then(r => r.ok ? r.json() : []).catch(() => []),
      authFetch('/billing/godowns').then(r => r.ok ? r.json() : []).catch(() => []),
      authFetch('/billing/stock-transfers').then(r => r.ok ? r.json() : []).catch(() => []),
    ]).then(([prodData, godData, transData]) => {
      const items = Array.isArray(prodData) ? prodData : (prodData && Array.isArray(prodData.items) ? prodData.items : [])
      setProducts(items)
      setGodowns(godData)
      setTransfers(transData)
    }).finally(() => setLoading(false))
  }, [authFetch])

  useEffect(() => {
    load()
    const handleSync = (e) => {
      const currentSettings = settingsRef.current
      const isStockSyncEnabled = currentSettings?.general?.realtime_sync_stock !== false
      if (!isStockSyncEnabled) return
      logger.debug('[STOCK] Real-time sync event received:', e.detail)
      if (['product', 'invoice', 'purchase', 'godown'].includes(e.detail.entity) || e.detail?.type === 'sync.reconnect') {
        load()
      }
    }
    window.addEventListener('focus', load)
    window.addEventListener('sync-event', handleSync)
    return () => {
      window.removeEventListener('focus', load)
      window.removeEventListener('sync-event', handleSync)
    }
  }, [load])

  const categories = [...new Set(products.map(p => p.category).filter(Boolean))]

  const [stockStatusFilter, setStockStatusFilter] = useState('')
  const [sortConfig, setSortConfig] = useState({ key: '', direction: '' })

  const handleSort = (key) => {
    let direction = 'asc'
    if (sortConfig.key === key && sortConfig.direction === 'asc') {
      direction = 'desc'
    } else if (sortConfig.key === key && sortConfig.direction === 'desc') {
      setSortConfig({ key: '', direction: '' })
      return
    }
    setSortConfig({ key, direction })
  }

  const getFilteredProducts = () => {
    let items = products.filter(p => {
      if (catFilter && p.category !== catFilter) return false
      
      const status = getStatus(p)
      if (stockStatusFilter === 'in' && status !== 'In Stock') return false
      if (stockStatusFilter === 'low' && status !== 'Low') return false
      if (stockStatusFilter === 'out' && status !== 'Out') return false

      const q = search.toLowerCase()
      return !q || p.name?.toLowerCase().includes(q) || p.sku?.toLowerCase().includes(q)
    })

    if (sortConfig.key && sortConfig.direction) {
      items.sort((a, b) => {
        let aVal = a[sortConfig.key]
        let bVal = b[sortConfig.key]

        if (sortConfig.key === 'stock_qty') {
          aVal = parseFloat(a.stock_qty ?? a.quantity ?? 0)
          bVal = parseFloat(b.stock_qty ?? b.quantity ?? 0)
        } else if (sortConfig.key === 'selling_price' || sortConfig.key === 'wholesale_price' || sortConfig.key === 'distributor_price' || sortConfig.key === 'cost_price') {
          aVal = parseFloat(a[sortConfig.key] ?? 0)
          bVal = parseFloat(b[sortConfig.key] ?? 0)
        } else if (sortConfig.key === 'status') {
          aVal = getStatus(a)
          bVal = getStatus(b)
        }

        if (aVal === undefined || aVal === null) return 1
        if (bVal === undefined || bVal === null) return -1

        if (typeof aVal === 'string') {
          return sortConfig.direction === 'asc'
            ? aVal.localeCompare(bVal)
            : bVal.localeCompare(aVal)
        } else {
          return sortConfig.direction === 'asc'
            ? aVal - bVal
            : bVal - aVal
        }
      })
    }
    return items
  }

  const filtered = getFilteredProducts()

  const totalProducts = products.length
  const lowStock  = products.filter(p => getStatus(p) === 'Low').length
  const outStock  = products.filter(p => getStatus(p) === 'Out').length

  const setAdjField = (k, v) => setAdjustForm(f => ({ ...f, [k]: v }))
  const setTrsfField = (k, v) => setTransferForm(f => ({ ...f, [k]: v }))

  // NOTE: the legacy inline add-product handler/form was removed (T5.3) —
  // adding/editing products is owned by <ProductFormModal /> below.

  const handleAdjust = async (e) => {
    e.preventDefault()
    if (!adjustForm.product_id) {
      setAlert({ type: 'danger', msg: 'Please select a product.' })
      return
    }
    const q = parseFloat(adjustForm.quantity) || 0
    if (q <= 0) {
      setAlert({ type: 'danger', msg: 'Enter a quantity greater than 0.' })
      return
    }
    // ANTI-TAMPER: a reason is mandatory — the backend rejects blank notes and
    // every adjustment is attributed in the owner's activity feed.
    if (!(adjustForm.reason || '').trim()) {
      setAlert({ type: 'danger', msg: 'A reason is required (e.g. "damaged goods", "count correction").' })
      return
    }
    setSubmitting(true)
    try {
      // BUGFIX (2026-07): this used to POST /billing/stock/adjust — an endpoint
      // that never existed (silent 404, the whole modal was dead). The real
      // route is per-product with a signed qty_delta.
      const pid = parseInt(adjustForm.product_id, 10)
      const delta = adjustForm.movement_type === 'stock_out' ? -q : q
      const noteBits = [adjustForm.reason.trim()]
      if (adjustForm.reference) noteBits.push(`ref: ${adjustForm.reference}`)
      const res = await authFetch(`/billing/products/${pid}/stock/adjustment`, {
        method: 'POST',
        body: JSON.stringify({ qty_delta: delta, note: noteBits.join(' — ') }),
      })
      if (res.ok) {
        setAlert({ type: 'success', msg: 'Stock adjusted successfully!' })
        setShowAdjustModal(false)
        setAdjustForm(defaultAdjust)
        load()
      } else {
        const err = await res.json().catch(() => ({}))
        const detail = Array.isArray(err.detail)
          ? err.detail.map(d => `${d.loc?.slice(-1)[0] ?? 'field'}: ${d.msg}`).join('; ')
          : (err.detail || 'Failed to adjust stock.')
        setAlert({ type: 'danger', msg: detail })
      }
    } catch {
      setAlert({ type: 'danger', msg: 'Network error.' })
    } finally {
      setSubmitting(false)
    }
  }

  const handleAddGodown = async (e) => {
    e.preventDefault()
    if (!newGodownName.trim()) return
    setSubmitting(true)
    try {
      const res = await authFetch('/billing/godowns', {
        method: 'POST',
        body: JSON.stringify({ name: newGodownName.trim(), address: newGodownAddress.trim() }),
      })
      if (res.ok) {
        setNewGodownName('')
        setNewGodownAddress('')
        setAlert({ type: 'success', msg: 'Godown added successfully!' })
        load()
      } else {
        const err = await res.json().catch(() => ({}))
        setAlert({ type: 'danger', msg: formatError(err, 'Failed to add godown.') })
      }
    } catch {
      setAlert({ type: 'danger', msg: 'Network error.' })
    } finally {
      setSubmitting(false)
    }
  }

  const handleTransferStock = async (e) => {
    e.preventDefault()
    if (!transferForm.from_godown_id || !transferForm.to_godown_id || !transferForm.product_id || !transferForm.quantity) {
      setAlert({ type: 'danger', msg: 'Please fill out all required transfer fields.' })
      return
    }
    setSubmitting(true)
    try {
      const res = await authFetch('/billing/stock-transfers', {
        method: 'POST',
        body: JSON.stringify({
          transfer_date: (() => {
            const d = new Date()
            const year = d.getFullYear()
            const month = String(d.getMonth() + 1).padStart(2, '0')
            const day = String(d.getDate()).padStart(2, '0')
            return `${year}-${month}-${day}`
          })(),
          from_godown_id: parseInt(transferForm.from_godown_id),
          to_godown_id: parseInt(transferForm.to_godown_id),
          notes: transferForm.notes || null,
          items: [
            {
              product_id: parseInt(transferForm.product_id),
              product_name: products.find(p => p.id === parseInt(transferForm.product_id))?.name || '',
              quantity: parseFloat(transferForm.quantity)
            }
          ]
        }),
      })
      if (res.ok) {
        setAlert({ type: 'success', msg: 'Stock transferred successfully!' })
        setShowTransferModal(false)
        setTransferForm(defaultTransfer)
        load()
      } else {
        const err = await res.json().catch(() => ({}))
        setAlert({ type: 'danger', msg: formatError(err, 'Failed to transfer stock.') })
      }
    } catch {
      setAlert({ type: 'danger', msg: 'Network error.' })
    } finally {
      setSubmitting(false)
    }
  }


  // ─── View state ─────────────────────────────────────────────────────────────
  const [activeView, setActiveView] = useState('intake')  // 'intake' | 'catalogue' | 'godowns'
  const [prefillProduct, setPrefillProduct] = useState(null)  // product to pre-load in intake
  const [ctxMenu, setCtxMenu] = useState(null)  // { x, y, items } for right-click context menu
  const [intakeRows, setIntakeRows] = useState(() => {
    try {
      const saved = localStorage.getItem('bizassist_intake_rows')
      return saved ? JSON.parse(saved) : []
    } catch (e) {
      return []
    }
  })
  const [editingRowKey, setEditingRowKey] = useState(null)

  const [isSidebarCollapsed, setIsSidebarCollapsed] = useState(() => {
    try {
      const saved = localStorage.getItem('bizassist_intake_sidebar_collapsed')
      return saved ? JSON.parse(saved) : false
    } catch (e) {
      return false
    }
  })

  useEffect(() => {
    localStorage.setItem('bizassist_intake_sidebar_collapsed', JSON.stringify(isSidebarCollapsed))
  }, [isSidebarCollapsed])

  const [intakeDistributor, setIntakeDistributor] = useState(() => {
    const todayISO = new Date().toISOString().slice(0, 10)
    try {
      const saved = localStorage.getItem('bizassist_intake_distributor')
      return saved ? JSON.parse(saved) : { vendor_id: null, name: '', gstin: '', pan: '', fssai: '', phone: '', address: '', invoice_no: '', invoice_date: todayISO }
    } catch (e) {
      return { vendor_id: null, name: '', gstin: '', pan: '', fssai: '', phone: '', address: '', invoice_no: '', invoice_date: todayISO }
    }
  })

  const [intakeAdjustments, setIntakeAdjustments] = useState(() => {
    try {
      const saved = localStorage.getItem('bizassist_intake_adjustments')
      return saved ? JSON.parse(saved) : { item_disc: '', cess: '', cash_disc: '' }
    } catch (e) {
      return { item_disc: '', cess: '', cash_disc: '' }
    }
  })

  const [intakePayment, setIntakePayment] = useState(() => {
    try {
      const saved = localStorage.getItem('bizassist_intake_payment')
      return saved ? JSON.parse(saved) : { mode: 'Credit', due_date: '' }
    } catch (e) {
      return { mode: 'Credit', due_date: '' }
    }
  })

  // Persist drafts to localStorage
  useEffect(() => {
    localStorage.setItem('bizassist_intake_rows', JSON.stringify(intakeRows))
  }, [intakeRows])

  useEffect(() => {
    localStorage.setItem('bizassist_intake_distributor', JSON.stringify(intakeDistributor))
  }, [intakeDistributor])

  useEffect(() => {
    localStorage.setItem('bizassist_intake_adjustments', JSON.stringify(intakeAdjustments))
  }, [intakeAdjustments])

  useEffect(() => {
    localStorage.setItem('bizassist_intake_payment', JSON.stringify(intakePayment))
  }, [intakePayment])

  const lowStockItems = products.filter(p => getStatus(p) !== 'In Stock').slice(0, 10)

  // ─── Page lifecycle (onResume refresh + Back guard) ──────────────────────────
  const { blocker, isRefreshing, dirtyMessage } = usePageLifecycle({
    isDirty:      () => intakeRows.length > 0,
    dirtyMessage: `You have ${intakeRows.length} unsaved intake row${intakeRows.length !== 1 ? 's' : ''}. Leave this page?`,
    onResume:     load,   // silently refresh catalogue when tab regains focus
  })

  // Helper to update fields on the currently editing row in parent state
  const setEditingRowField = (field, value) => {
    setIntakeRows(prev => prev.map(r => r._key === editingRowKey ? { ...r, [field]: value, _status: null } : r))
  }

  const printGRN = () => {
    const gstOfLocal = (r) => (parseFloat(r.cgst_rate) || 0) + (parseFloat(r.sgst_rate) || 0) || (parseFloat(r.igst_rate) || 0)
    const money = (n) =>
      n != null
        ? `₹${Number(n).toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
        : '—'

    const gross = intakeRows.reduce((s, r) => {
      const q = parseFloat(r.qty) || 0
      const c = parseFloat(r.cost_price) || 0
      return s + q * c
    }, 0)

    const slabMap = {}
    intakeRows.forEach((r) => {
      const q = parseFloat(r.qty) || 0
      const c = parseFloat(r.cost_price) || 0
      if (q <= 0 || c <= 0) return
      const rate = gstOfLocal(r)
      const amt = q * c
      const tax = amt * rate / 100
      if (!slabMap[rate]) slabMap[rate] = { rate, taxable: 0, tax: 0 }
      slabMap[rate].taxable += amt
      slabMap[rate].tax += tax
    })
    const slabList = Object.values(slabMap).sort((a, b) => a.rate - b.rate)
    const taxTotal = slabList.reduce((s, x) => s + x.tax, 0)
    
    const itemDisc = parseFloat(intakeAdjustments?.item_disc) || 0
    const cess = parseFloat(intakeAdjustments?.cess) || 0
    const cashDisc = parseFloat(intakeAdjustments?.cash_disc) || 0
    const taxable = gross - itemDisc
    const payable = taxable + taxTotal + cess - cashDisc

    const w = window.open('', '_blank', 'width=800,height=900')
    if (!w) return
    const rowsHtml = intakeRows.map((r, i) => {
      const q = parseFloat(r.qty) || 0, f = parseFloat(r.free) || 0
      const c = parseFloat(r.cost_price) || 0, g = gstOfLocal(r)
      const amt = q * c, taxAmt = amt * g / 100
      return `<tr>
        <td>${i + 1}</td><td>${r.name || ''}</td><td style="text-align:right">${q}</td>
        <td style="text-align:right">${f}</td><td style="text-align:right">${c.toFixed(2)}</td>
        <td style="text-align:right">${g}%</td><td style="text-align:right">${taxAmt.toFixed(2)}</td>
        <td style="text-align:right">${(amt + taxAmt).toFixed(2)}</td></tr>`
    }).join('')
    const slabHtml = slabList.map((s) =>
      `<tr><td>GST ${s.rate}%</td><td style="text-align:right">${s.taxable.toFixed(2)}</td><td style="text-align:right">${s.tax.toFixed(2)}</td></tr>`).join('')
    w.document.write(`<!doctype html><html><head><title>Purchase / GRN Summary</title>
      <style>
        body{font-family:Arial,sans-serif;color:#111;padding:24px;font-size:12px}
        h1{font-size:18px;margin:0 0 4px} h2{font-size:13px;margin:18px 0 6px;border-bottom:1px solid #999;padding-bottom:3px}
        table{width:100%;border-collapse:collapse;margin-top:6px} th,td{border:1px solid #bbb;padding:5px 7px;font-size:11px}
        th{background:#eee;text-align:left} .tot{display:flex;justify-content:space-between;padding:3px 0}
        .tot.big{font-size:15px;font-weight:800;border-top:2px solid #333;margin-top:6px;padding-top:6px}
        .grid{display:flex;gap:32px} .grid>div{flex:1}
      </style></head><body>
      <h1>Purchase / GRN Summary</h1>
      <div style="color:#555">${new Date().toLocaleString('en-IN')}</div>
      <div class="grid">
        <div><h2>Distributor</h2>
          <div>${intakeDistributor.name || '—'}</div>
          <div>GSTIN: ${intakeDistributor.gstin || '—'}</div>
          <div>PAN: ${intakeDistributor.pan || '—'}</div>
          <div>FSSAI: ${intakeDistributor.fssai || '—'}</div>
          <div>Phone: ${intakeDistributor.phone || '—'}</div>
          <div>Address: ${intakeDistributor.address || '—'}</div>
        </div>
        <div><h2>Invoice / Payment</h2>
          <div>Invoice No: ${intakeDistributor.invoice_no || '—'}</div><div>Invoice Date: ${intakeDistributor.invoice_date || '—'}</div>
          <div>Payment: ${intakePayment.mode}${intakePayment.due_date ? ' · due ' + intakePayment.due_date : ''}</div></div>
      </div>
      <h2>Items</h2>
      <table><thead><tr><th>#</th><th>Product</th><th style="text-align:right">Qty</th><th style="text-align:right">Free</th>
        <th style="text-align:right">Cost</th><th style="text-align:right">Tax%</th><th style="text-align:right">Tax</th><th style="text-align:right">Net</th></tr></thead>
        <tbody>${rowsHtml}</tbody></table>
      <h2>Tax Breakdown</h2>
      <table><thead><tr><th>Slab</th><th style="text-align:right">Taxable</th><th style="text-align:right">Tax</th></tr></thead><tbody>${slabHtml || '<tr><td colspan=3>—</td></tr>'}</tbody></table>
      <h2>Summary</h2>
      <div class="tot"><span>Gross Amount</span><span>${money(gross)}</span></div>
      <div class="tot"><span>Item Disc</span><span>${money(itemDisc)}</span></div>
      <div class="tot"><span>Taxable</span><span>${money(taxable)}</span></div>
      <div class="tot"><span>Tax</span><span>${money(taxTotal)}</span></div>
      <div class="tot"><span>Cess</span><span>${money(cess)}</span></div>
      <div class="tot"><span>Cash Disc</span><span>-${money(cashDisc)}</span></div>
      <div class="tot big"><span>Payable Amount</span><span>${money(payable)}</span></div>
      </body></html>`)
    w.document.close()
    w.focus()
    setTimeout(() => { w.print() }, 250)
  }

  // Helper to add barcode to editing row from the sidebar
  const addBarcodeToEditingRow = async () => {
    const editingRow = intakeRows.find(r => r._key === editingRowKey)
    if (!editingRow) return
    const code = (editingRow._newBarcode || '').trim()
    if (!code) return
    if (editingRow._type === 'existing') {
      try {
        const res = await authFetch(`/billing/products/${editingRow.product_id}/barcodes`, {
          method: 'POST', body: JSON.stringify({ barcode: code }),
        })
        const data = await res.json().catch(() => ({}))
        if (!res.ok) throw new Error(data.detail || 'Could not add barcode.')
        
        setIntakeRows(prev => prev.map(r => r._key === editingRowKey ? {
          ...r,
          barcodes: [...(r.barcodes || []), data.barcode ? data : { barcode: code }],
          _newBarcode: ''
        } : r))
      } catch (err) {
        setAlert({ type: 'danger', msg: err.message })
      }
    }
  }

  // ── Tab switch helpers ───────────────────────────────────────────────────────
  const goIntake = (product = null) => {
    if (product) setPrefillProduct({ ...product, _seed: Date.now() }) // new ref each time
    setActiveView('intake')
  }

  // Inline SVG icons for warehouse / tag (not in Icons.jsx)
  const WarehouseIcon = ({ size = 14 }) => (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <rect x="2" y="7" width="20" height="14" rx="2"/><path d="M16 21V5a2 2 0 0 0-2-2h-4a2 2 0 0 0-2 2v16"/>
    </svg>
  )
  const TagIcon = ({ size = 14 }) => (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M20.59 13.41l-7.17 7.17a2 2 0 0 1-2.83 0L2 12V2h10l8.59 8.59a2 2 0 0 1 0 2.82z"/><line x1="7" y1="7" x2="7.01" y2="7"/>
    </svg>
  )

  // Tab definitions
  const TABS = [
    { key: 'intake',    label: 'Stock Intake', icon: <ZapIcon size={14} /> },
    { key: 'catalogue', label: 'Catalogue',    icon: <InventoryIcon size={14} /> },
    { key: 'godowns',  label: 'Godowns',       icon: <WarehouseIcon size={14} /> },
  ]

  return (
    <PageShell embedded={embedded} title="Stock & Inventory">
      <style>{`
        .inv-shell { display: flex; flex-direction: column; height: 100%; overflow: hidden; }
        .inv-body { flex: 1; display: flex; min-height: 0; overflow: hidden; }
        .inv-main { flex: 1; min-width: 0; height: 100%; display: flex; flex-direction: column; padding: 0 16px 12px; overflow: hidden; }
        .inv-sidebar {
          width: 340px; flex-shrink: 0; height: 100%; display: flex; flex-direction: column;
          border-left: 1px solid var(--border); background: var(--bg-2); overflow-y: auto;
        }
        .inv-action-btn {
          display: flex; align-items: center; gap: 9px; width: 100%;
          padding: 9px 14px; background: transparent; border: none; border-radius: 6px;
          cursor: pointer; color: var(--text-primary); font-size: 0.82rem; font-weight: 600;
          text-align: left; transition: background var(--dur-fast) var(--ease);
        }
        .inv-action-btn:hover { background: var(--bg-3); }
        .inv-btn-icon {
          display: flex; align-items: center; justify-content: center;
          width: 28px; height: 28px; border-radius: 6px;
          background: var(--bg-4, var(--bg-3)); flex-shrink: 0;
          color: var(--accent);
        }
        .inv-stat-chip {
          display: flex; flex-direction: column; align-items: center; flex: 1;
          padding: 11px 6px; cursor: pointer; border-radius: 0; transition: background var(--dur-fast) var(--ease);
          border: none; background: transparent;
        }
        .inv-stat-chip:hover { background: var(--bg-3); }
        .inv-alert-row {
          display: flex; align-items: center; gap: 8px; padding: 7px 10px;
          border-radius: 7px; border: 1px solid var(--border);
          cursor: pointer; transition: background var(--dur-fast) var(--ease);
        }
        .inv-alert-row:hover { background: var(--bg-3); }
        .inv-full-panel { flex: 1; display: flex; flex-direction: column; min-height: 0; padding: 14px 16px; overflow: hidden; }
        .inv-panel-toolbar {
          display: flex; align-items: center; gap: 8px; flex-wrap: nowrap;
          padding-bottom: 10px; border-bottom: 1px solid var(--border); flex-shrink: 0; margin-bottom: 12px;
          overflow: hidden;
        }
        .inv-table-wrap { flex: 1; overflow-y: auto; border: 1px solid var(--border); border-radius: 8px; }
      `}</style>

      <div className="inv-shell">
        {/* ── Top bar — shared WorkspaceTopBar (identical to Purchases/Parties/Payments) ── */}
        <WorkspaceTopBar
          actions={
            <>
              {/* Alert flash */}
              {alert && (
                <div style={{
                  display: 'flex', alignItems: 'center', gap: 8, padding: '4px 10px', borderRadius: 6,
                  fontSize: '0.78rem', fontWeight: 600,
                  background: alert.type === 'success' ? 'rgba(34,197,94,.12)' : 'rgba(239,68,68,.12)',
                  color: alert.type === 'success' ? '#22c55e' : '#ef4444',
                  border: `1px solid ${alert.type === 'success' ? 'rgba(34,197,94,.3)' : 'rgba(239,68,68,.3)'}`,
                  maxWidth: 340, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis',
                }}>
                  {alert.msg}
                  <button onClick={() => setAlert(null)} style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'inherit', lineHeight: 1, padding: '0 0 0 4px', flexShrink: 0 }}>
                    <CloseIcon size={12} />
                  </button>
                </div>
              )}
              <button
                className="btn btn-secondary btn-sm"
                style={{ display: 'inline-flex', alignItems: 'center', gap: 5 }}
                onClick={() => { setAdjustForm(defaultAdjust); setShowAdjustModal(true) }}
              >
                <ZapIcon size={13} /> Adjust Stock
              </button>
              <button
                className="btn btn-secondary btn-sm"
                style={{ display: 'inline-flex', alignItems: 'center', gap: 5 }}
                onClick={() => { setTransferForm(defaultTransfer); setShowTransferModal(true) }}
              >
                <SyncIcon size={13} /> Transfer Stock
              </button>
              <WsDivider />
              <button className="btn btn-secondary btn-sm" style={{ display: 'inline-flex', alignItems: 'center', gap: 5 }}
                onClick={() => setShowLabelModal(true)}>
                {/* TagIcon replaced with InventoryIcon to keep imports clean */}
                Labels
              </button>
              <button className="btn btn-secondary btn-sm" style={{ display: 'inline-flex', alignItems: 'center', gap: 5 }}
                disabled={exporting} onClick={handleExport}>
                <DownloadIcon size={13} /> {exporting ? 'Exporting…' : 'Export'}
              </button>
              <button className="btn btn-primary btn-sm" style={{ display: 'inline-flex', alignItems: 'center', gap: 5 }}
                onClick={() => { setEditProduct(null); setShowAddModal(true) }}>
                <PlusIcon size={13} /> New Product
              </button>
              {activeView === 'intake' && intakeRows.length > 0 && (
                <button
                  className={`btn btn-secondary btn-sm ${isSidebarCollapsed ? 'active' : ''}`}
                  style={{ display: 'inline-flex', alignItems: 'center', gap: 5, padding: '0 8px', height: 28 }}
                  onClick={() => setIsSidebarCollapsed(!isSidebarCollapsed)}
                  title={isSidebarCollapsed ? 'Expand right panel' : 'Collapse right panel'}
                >
                  <SidebarIcon size={14} />
                </button>
              )}
            </>
          }
        >
          {/* Workspace tabs (Stock | Purchase Bills) from Godown.jsx, or standalone brand */}
          {headerTabs || (
            <button
              className="ws-tab"
              style={{ fontWeight: 800, fontSize: '0.88rem', color: 'var(--text-primary)', marginRight: 4 }}
              onClick={() => setActiveView('intake')}
              title="Stock Intake — main screen"
            >
              <InventoryIcon size={16} /> Inventory
            </button>
          )}
          <WsDivider />
          {/* Internal view tabs */}
          {TABS.map(tab => (
            <button
              key={tab.key}
              className={`ws-tab ${activeView === tab.key ? 'active' : ''}`}
              onClick={() => setActiveView(tab.key)}
            >
              {tab.icon} {tab.label}
            </button>
          ))}
        </WorkspaceTopBar>

        {/* ── Body ─────────────────────────────────────────────────────────── */}
        <div className="inv-body">

          {/* ── LEFT main area — switches by activeView ─────────────────── */}
          <div className="inv-main">

            {/* ── INTAKE ─────────────────────────────────────────────────── */}
            {/* Keep mounted always so rows aren't lost when switching tabs */}
            <div style={{ display: activeView === 'intake' ? 'flex' : 'none', flexDirection: 'column', height: '100%', paddingTop: 12 }}>
              <StockIntakeSheet
                products={products}
                prefillProduct={prefillProduct}
                rows={intakeRows}
                setRows={setIntakeRows}
                distributor={intakeDistributor}
                setDistributor={setIntakeDistributor}
                adjustments={intakeAdjustments}
                isSidebarCollapsed={isSidebarCollapsed}
                setIsSidebarCollapsed={setIsSidebarCollapsed}
                editingRowKey={editingRowKey}
                setEditingRowKey={setEditingRowKey}
                onPrint={printGRN}
                onSaved={(n) => {
                  setAlert({ type: 'success', msg: `✓ ${n} item${n !== 1 ? 's' : ''} recorded` })
                  setPrefillProduct(null)
                  load()
                }}
              />
            </div>

            {/* ── CATALOGUE ──────────────────────────────────────────────── */}
            {activeView === 'catalogue' && (
              <div className="inv-full-panel">
                <div className="inv-panel-toolbar">
                  <div className="search-bar" style={{ minWidth: 220, height: 34 }}>
                    <span style={{ color: 'var(--text-muted)', display: 'flex', alignItems: 'center' }}><SearchIcon size={15} /></span>
                    <input value={search} onChange={e => setSearch(e.target.value)} placeholder="Search products…" autoFocus />
                  </div>
                  <CustomSelect className="form-select" style={{ height: 34, fontSize: '0.82rem', minWidth: 140, width: 'auto', flexShrink: 0 }}
                    value={catFilter} onChange={e => setCatFilter(e.target.value)}>
                    <option value="">All Categories</option>
                    {categories.map(c => <option key={c} value={c}>{c}</option>)}
                  </CustomSelect>
                  <CustomSelect className="form-select" style={{ height: 34, fontSize: '0.82rem', minWidth: 120, width: 'auto', flexShrink: 0 }}
                    value={stockStatusFilter} onChange={e => setStockStatusFilter(e.target.value)}>
                    <option value="">All Status</option>
                    <option value="in">In Stock</option>
                    <option value="low">Low Stock</option>
                    <option value="out">Out of Stock</option>
                  </CustomSelect>
                  <div style={{ flex: 1 }} />
                  {isRefreshing && (
                    <span className="toolbar-refresh-spinner">
                      <span className="spin" /> Refreshing…
                    </span>
                  )}
                  <span style={{ fontSize: '0.78rem', color: 'var(--text-muted)', fontWeight: 600 }}>
                    {filtered.length} of {products.length} products
                  </span>
                </div>

                <div className="inv-table-wrap">
                  {/* Dense inventory grid — reference-style columns, compact spacing.
                      Money columns drop the ₹ (header carries it); %/cost figures
                      are computed (deriveInv), nothing new is stored. Barcode,
                      category, brand, wholesale/distributor prices etc. live in the
                      edit panel. */}
                  <style>{`
                    .data-table.inv-dense th { padding: 6px 7px; font-size: 10px; letter-spacing: .02em; }
                    .data-table.inv-dense td { padding: 4px 7px; font-size: 11.5px; }
                    .data-table.inv-dense .td-primary { font-size: 11.5px; line-height: 1.2; }
                    .data-table.inv-dense .td-mono { font-size: 10.5px; }
                  `}</style>
                  {loading ? (
                    <div className="page-loader"><span className="spinner" /> Loading…</div>
                  ) : (
                    <table className="data-table inv-dense">
                      <thead><tr>
                        <th style={{ textAlign: 'left' }}>Code</th>
                        <th style={{ textAlign: 'left' }}>Name</th>
                        <th>HSN</th>
                        <th style={{ textAlign: 'right' }}>Stock</th>
                        <th>Unit</th>
                        <th style={{ textAlign: 'right' }}>MRP ₹</th>
                        <th style={{ textAlign: 'right' }}>Cost ₹</th>
                        <th style={{ textAlign: 'right' }}>Sell ₹</th>
                        <th style={{ textAlign: 'right' }} title="Total GST rate">Tax%</th>
                        <th style={{ textAlign: 'right' }} title="Discount off MRP">Disc%</th>
                        <th style={{ textAlign: 'right' }} title="Return on cost = (Sell−Cost)/Cost">ROI%</th>
                        <th style={{ textAlign: 'right' }} title="Margin on selling = (Sell−Cost)/Sell">Profit%</th>
                        <th style={{ textAlign: 'right' }} title="Landed cost incl. GST">NetCost</th>
                        <th style={{ textAlign: 'right' }} title="MRP net of GST (taxable value)">NetMRP</th>
                        <th>Status</th>
                        <th style={{ width: 88 }}>Actions</th>
                      </tr></thead>
                      <tbody>
                        {filtered.length === 0 ? (
                          <tr><td colSpan={16}>
                            <div className="empty-state"><div className="empty-icon"><InventoryIcon size={22} /></div><h3>No products found</h3></div>
                          </td></tr>
                        ) : filtered.map(p => {
                          const status = getStatus(p)
                          const isLow = status !== 'In Stock'
                          const d = deriveInv(p)
                          const good = 'var(--success, #16a34a)'
                          return (
                            <tr
                              key={p.id}
                              style={{ background: isLow ? 'rgba(239,68,68,.03)' : undefined, cursor: 'context-menu' }}
                              onContextMenu={e => {
                                e.preventDefault()
                                setCtxMenu({
                                  x: e.clientX, y: e.clientY,
                                  items: [
                                    {
                                      label: 'Edit Product',
                                      icon: <EditIcon size={13} />,
                                      action: () => setEditProduct(p),
                                    },
                                    {
                                      label: 'Add to Stock Intake',
                                      icon: <ZapIcon size={13} />,
                                      action: () => goIntake(p),
                                    },
                                    {
                                      label: 'Adjust Stock',
                                      icon: <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>,
                                      action: () => { setAdjustForm({ ...defaultAdjust, product_id: p.id }); setShowAdjustModal(true) },
                                    },
                                    {
                                      label: 'Transfer Stock',
                                      icon: <SyncIcon size={13} />,
                                      action: () => { setTransferForm({ ...defaultTransfer, product_id: p.id }); setShowTransferModal(true) },
                                    },
                                    { divider: true },
                                    {
                                      label: 'Copy Product Code',
                                      icon: <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>,
                                      action: () => navigator.clipboard.writeText(p.sku || p.id),
                                    },
                                    {
                                      label: 'Copy Name',
                                      icon: <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>,
                                      action: () => navigator.clipboard.writeText(p.name),
                                    },
                                  ],
                                })
                              }}
                            >
                              <td className="td-mono" style={{ textAlign: 'left' }}>{p.sku || '—'}</td>
                              <td className="td-primary" style={{ textAlign: 'left' }}>
                                {p.name}
                                {p.barcode && <div style={{ color: 'var(--text-muted)', fontFamily: 'monospace', fontSize: '0.66rem' }}>{p.barcode}</div>}
                              </td>
                              <td className="td-mono">{p.hsn_sac || '—'}</td>
                              <td style={{ textAlign: 'right', fontWeight: 700, color: isLow ? 'var(--danger)' : 'inherit' }}>
                                {p.stock_qty ?? p.quantity ?? 0}
                              </td>
                              <td style={{ color: 'var(--text-muted)' }}>{p.unit || 'pcs'}</td>
                              <td style={{ textAlign: 'right' }}>{num(d.mrp || null)}</td>
                              <td style={{ textAlign: 'right' }}>{num(d.cost || null)}</td>
                              <td style={{ textAlign: 'right', fontWeight: 600 }}>{num(d.sell || null)}</td>
                              <td style={{ textAlign: 'right', color: 'var(--text-muted)' }}>{d.gst ? `${d.gst.toFixed(0)}%` : '—'}</td>
                              <td style={{ textAlign: 'right', color: 'var(--text-muted)' }}>{pct(d.discPct)}</td>
                              <td style={{ textAlign: 'right', color: d.roi == null ? 'var(--text-muted)' : d.roi >= 0 ? good : 'var(--danger)' }}>{pct(d.roi)}</td>
                              <td style={{ textAlign: 'right', color: d.profit == null ? 'var(--text-muted)' : d.profit >= 0 ? good : 'var(--danger)' }}>{pct(d.profit)}</td>
                              <td style={{ textAlign: 'right' }}>{num(d.netCost)}</td>
                              <td style={{ textAlign: 'right' }}>{num(d.netMrp)}</td>
                              <td><span className={`badge ${status === 'In Stock' ? 'badge-success' : status === 'Low' ? 'badge-warning' : 'badge-danger'}`}>{status}</span></td>
                              <td>
                                <div style={{ display: 'flex', gap: 4 }}>
                                  <button
                                    className="btn btn-primary btn-sm"
                                    style={{ padding: '3px 10px', fontSize: '0.72rem', display: 'inline-flex', alignItems: 'center', gap: 4 }}
                                    onClick={() => goIntake(p)}
                                    title={`Switch to Stock Intake and add stock for ${p.name}`}
                                  >
                                    <ZapIcon size={11} /> ± Stock
                                  </button>
                                  <button
                                    className="btn btn-secondary btn-sm"
                                    style={{ padding: '3px 9px', fontSize: '0.72rem' }}
                                    onClick={() => setEditProduct(p)}
                                    title="Edit product details"
                                  >
                                    <EditIcon size={11} />
                                  </button>
                                </div>
                              </td>
                            </tr>
                          )
                        })}
                      </tbody>
                    </table>
                  )}
                </div>
              </div>
            )}

            {/* ── Global portals ────────────────────────────────────────────── */}
            <ContextMenu menu={ctxMenu} onClose={() => setCtxMenu(null)} />
            <UnsavedChangesModal blocker={blocker} message={dirtyMessage} />

            {/* ── GODOWNS ────────────────────────────────────────────────── */}
            {activeView === 'godowns' && (
              <div className="inv-full-panel">
                <div className="inv-panel-toolbar" style={{ justifyContent: 'space-between' }}>
                  <span style={{ fontWeight: 700, fontSize: '0.95rem', display: 'inline-flex', alignItems: 'center', gap: 7 }}>
                    <WarehouseIcon size={15} /> Godowns &amp; Stock Transfers
                  </span>
                  <button className="btn btn-primary btn-sm" style={{ display: 'inline-flex', alignItems: 'center', gap: 5 }}
                    onClick={() => { setTransferForm(defaultTransfer); setShowTransferModal(true) }}>
                    <SyncIcon size={12} /> Transfer Stock
                  </button>
                </div>

                <div style={{ display: 'grid', gridTemplateColumns: '340px 1fr', gap: 16, flex: 1, minHeight: 0, overflow: 'hidden' }}>
                  {/* Left: Locations list + add form */}
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 12, overflowY: 'auto' }}>
                    <div style={{ fontWeight: 700, fontSize: '0.82rem', color: 'var(--text-secondary)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>Locations</div>
                    {godowns.length === 0 ? (
                      <p style={{ color: 'var(--text-muted)', fontSize: '0.82rem' }}>No godowns registered. Add one below.</p>
                    ) : godowns.map(g => (
                      <div key={g.id} style={{ padding: '12px 14px', background: 'var(--bg-2)', border: '1px solid var(--border)', borderRadius: 10 }}>
                        <div style={{ fontWeight: 700, fontSize: '0.88rem' }}>{g.name}</div>
                        {g.address && <div style={{ fontSize: '0.76rem', color: 'var(--text-muted)', marginTop: 3 }}>{g.address}</div>}
                        <span className="badge badge-success" style={{ fontSize: '0.65rem', marginTop: 6, display: 'inline-block' }}>Active</span>
                      </div>
                    ))}

                    <form onSubmit={handleAddGodown} style={{ display: 'flex', flexDirection: 'column', gap: 8, background: 'var(--bg-3)', padding: 14, borderRadius: 10, border: '1px solid var(--border)', marginTop: 4 }}>
                      <div style={{ fontWeight: 700, fontSize: '0.82rem', marginBottom: 2 }}>Register New Godown</div>
                      <input className="form-input" style={{ height: 34, fontSize: '0.82rem' }} placeholder="Godown name *" value={newGodownName} onChange={e => setNewGodownName(e.target.value)} required />
                      <input className="form-input" style={{ height: 34, fontSize: '0.82rem' }} placeholder="Address / location" value={newGodownAddress} onChange={e => setNewGodownAddress(e.target.value)} />
                      <button type="submit" className="btn btn-primary btn-sm" disabled={submitting} style={{ alignSelf: 'flex-start', display: 'inline-flex', alignItems: 'center', gap: 5 }}>
                        <PlusIcon size={12} /> {submitting ? 'Saving…' : 'Register Godown'}
                      </button>
                    </form>
                  </div>

                  {/* Right: Transfer log */}
                  <div style={{ display: 'flex', flexDirection: 'column', minHeight: 0 }}>
                    <div style={{ fontWeight: 700, fontSize: '0.82rem', color: 'var(--text-secondary)', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: 10 }}>Transfer Log</div>
                    <div className="inv-table-wrap">
                      <table className="data-table" style={{ fontSize: '0.8rem' }}>
                        <thead><tr><th>Date</th><th>From</th><th>To</th><th>Item</th><th>Qty</th></tr></thead>
                        <tbody>
                          {transfers.length === 0 ? (
                            <tr><td colSpan={5} style={{ textAlign: 'center', color: 'var(--text-muted)', padding: '28px 0' }}>No stock transfers recorded yet.</td></tr>
                          ) : transfers.map(t => (
                            <tr key={t.id}>
                              <td>{t.transfer_date}</td>
                              <td style={{ color: '#ef4444', fontWeight: 600 }}>{t.from_godown_name}</td>
                              <td style={{ color: '#22c55e', fontWeight: 600 }}>{t.to_godown_name}</td>
                              <td>{(t.items || []).map(it => <div key={it.id}>{it.product_name}</div>)}</td>
                              <td style={{ fontWeight: 700 }}>{(t.items || []).map(it => <div key={it.id}>{it.quantity}</div>)}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </div>
                </div>
              </div>
            )}
          </div>

          {/* ── RIGHT sidebar — always visible ──────────────────────────── */}
          <div className="inv-sidebar" style={{ display: isSidebarCollapsed ? 'none' : 'flex', overflowY: editingRowKey ? 'hidden' : 'auto' }}>
            {activeView === 'intake' && intakeRows.length > 0 && (
              <div style={{
                display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                padding: '10px 14px', borderBottom: '1px solid var(--border)',
                background: 'var(--bg-3)', flexShrink: 0
              }}>
                <span style={{ fontSize: '0.78rem', fontWeight: 800, textTransform: 'uppercase', letterSpacing: '0.05em', color: 'var(--text-muted)' }}>
                  {editingRowKey ? 'Product Details' : 'Purchase Summary'}
                </span>
                <button
                  type="button"
                  onClick={() => setIsSidebarCollapsed(true)}
                  style={{
                    background: 'none', border: 'none', cursor: 'pointer',
                    color: 'var(--text-muted)', display: 'flex', alignItems: 'center',
                    justifyContent: 'center', padding: 4, borderRadius: 4,
                    transition: 'background .15s, color .15s'
                  }}
                  onMouseEnter={e => { e.currentTarget.style.background = 'var(--bg-4)'; e.currentTarget.style.color = 'var(--text-primary)' }}
                  onMouseLeave={e => { e.currentTarget.style.background = 'none'; e.currentTarget.style.color = 'var(--text-muted)' }}
                  title="Collapse right panel"
                >
                  <SidebarIcon size={16} />
                </button>
              </div>
            )}
            {activeView === 'intake' && editingRowKey && intakeRows.find(r => r._key === editingRowKey) ? (
              (() => {
                const editingRow = intakeRows.find(r => r._key === editingRowKey)
                const isNew = editingRow._type === 'new'
                const p = {
                  id: isNew ? undefined : editingRow.product_id,
                  name: editingRow.name || '',
                  description: editingRow.description || '',
                  brand: editingRow.brand || '',
                  category: editingRow.category || '',
                  unit: editingRow.unit || 'pcs',
                  sku: editingRow.sku || '',
                  barcode: editingRow.barcode || '',
                  hsn_sac: editingRow.hsn_sac || '',
                  selling_price: editingRow.selling_price || '',
                  wholesale_price: editingRow.wholesale_price || '',
                  distributor_price: editingRow.distributor_price || '',
                  cost_price: editingRow.cost_price || '',
                  mrp: editingRow.mrp || '',
                  cgst_rate: editingRow.cgst_rate || '',
                  sgst_rate: editingRow.sgst_rate || '',
                  min_stock: editingRow.min_stock || '',
                }

                return (
                  <ProductFormModal
                    key={editingRowKey}
                    inline={true}
                    open={true}
                    product={p}
                    prefillBarcode={isNew ? editingRow.barcode : ''}
                    onClose={() => setEditingRowKey(null)}
                    onChange={(field, value) => {
                      setIntakeRows(prev => prev.map(r => {
                        if (r._key === editingRowKey) {
                          return {
                            ...r,
                            [field]: value,
                            ...(field === 'name' ? { name: value } : {}),
                            ...(field === 'selling_price' ? { selling_price: String(value) } : {}),
                            ...(field === 'cost_price' ? { cost_price: String(value) } : {}),
                          }
                        }
                        return r
                      }))
                    }}
                    onSaved={(type, data) => {
                      load()
                      if (type === 'updated' && data) {
                        setIntakeRows(prev => prev.map(r => {
                          if (r.product_id === data.id) {
                            return {
                              ...r,
                              name: data.name || '',
                              sku: data.sku || '',
                              category: data.category || '',
                              unit: data.unit || 'pcs',
                              brand: data.brand || '',
                              hsn_sac: data.hsn_sac || '',
                              cgst_rate: data.cgst_rate != null ? String(data.cgst_rate) : '',
                              sgst_rate: data.sgst_rate != null ? String(data.sgst_rate) : '',
                              min_stock: data.min_stock != null ? String(data.min_stock) : '',
                              description: data.description || '',
                              wholesale_price: data.wholesale_price != null ? String(data.wholesale_price) : '',
                              distributor_price: data.distributor_price != null ? String(data.distributor_price) : '',
                              mrp: data.mrp != null ? String(data.mrp) : '',
                              barcodes: data.barcodes || [],
                              current_sell: data.selling_price ?? null,
                              current_cost: data.cost_price ?? null,
                              selling_price: data.selling_price != null ? String(data.selling_price) : r.selling_price,
                              cost_price: data.cost_price != null ? String(data.cost_price) : r.cost_price,
                            }
                          }
                          return r
                        }))
                      } else if (type === 'created' && data) {
                        setIntakeRows(prev => prev.map(r => {
                          if (r._key === editingRowKey) {
                            return {
                              ...r,
                              _type: 'existing',
                              product_id: data.id,
                              name: data.name || '',
                              barcode: data.barcode || '',
                              sku: data.sku || '',
                              category: data.category || '',
                              unit: data.unit || 'pcs',
                              brand: data.brand || '',
                              hsn_sac: data.hsn_sac || '',
                              cgst_rate: data.cgst_rate != null ? String(data.cgst_rate) : '',
                              sgst_rate: data.sgst_rate != null ? String(data.sgst_rate) : '',
                              min_stock: data.min_stock != null ? String(data.min_stock) : '',
                              description: data.description || '',
                              wholesale_price: data.wholesale_price != null ? String(data.wholesale_price) : '',
                              distributor_price: data.distributor_price != null ? String(data.distributor_price) : '',
                              mrp: data.mrp != null ? String(data.mrp) : '',
                              current_stock: 0,
                              current_sell: data.selling_price ?? null,
                              current_cost: data.cost_price ?? null,
                              selling_price: data.selling_price != null ? String(data.selling_price) : r.selling_price,
                              cost_price: data.cost_price != null ? String(data.cost_price) : r.cost_price,
                            }
                          }
                          return r
                        }))
                      }
                      setEditingRowKey(null)
                      setAlert({ type: 'success', msg: `Product successfully ${type}!` })
                    }}
                  />
                )
              })()
            ) : (
              <>
                {/* Stats */}
                <div style={{ display: 'flex', borderBottom: '1px solid var(--border)', flexShrink: 0 }}>
                  {[
                    { label: 'Products', value: totalProducts, color: 'var(--accent)', tab: 'catalogue' },
                    { label: 'Low',      value: lowStock,      color: '#d97706',        tab: 'catalogue', filter: 'low' },
                    { label: 'Out',      value: outStock,      color: '#ef4444',        tab: 'catalogue', filter: 'out' },
                  ].map(s => (
                    <button key={s.label} className="inv-stat-chip" onClick={() => {
                      if (s.filter) setStockStatusFilter(s.filter)
                      setActiveView(s.tab)
                    }}>
                      <span style={{ fontSize: '1.45rem', fontWeight: 800, color: s.color, lineHeight: 1, fontVariantNumeric: 'tabular-nums' }}>{s.value}</span>
                      <span style={{ fontSize: '0.6rem', fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.06em', color: 'var(--text-muted)', marginTop: 3 }}>{s.label}</span>
                    </button>
                  ))}
                </div>

                {/* Stock alerts */}
                <div style={{ flex: 1, padding: '10px 10px', overflow: 'hidden', display: 'flex', flexDirection: 'column' }}>
                  <div style={{ fontSize: '0.58rem', fontWeight: 800, textTransform: 'uppercase', letterSpacing: '0.07em', color: 'var(--text-muted)', marginBottom: 8 }}>
                    Stock Alerts
                  </div>
                  {loading ? (
                    <div style={{ color: 'var(--text-muted)', fontSize: '0.78rem' }}>Loading…</div>
                  ) : lowStockItems.length === 0 ? (
                    <div style={{ color: '#22c55e', fontSize: '0.78rem', fontWeight: 600, display: 'flex', alignItems: 'center', gap: 6 }}>
                      <CheckIcon size={14} /> All products have stock
                    </div>
                  ) : (
                    <div style={{ display: 'flex', flexDirection: 'column', gap: 4, overflowY: 'auto' }}>
                      {lowStockItems.map(p => {
                        const st = getStatus(p)
                        return (
                          <div key={p.id} className="inv-alert-row"
                            style={{ background: st === 'Out' ? 'rgba(239,68,68,.05)' : 'rgba(217,119,6,.04)' }}
                            onClick={() => goIntake(p)}
                            title={`Click to update stock for ${p.name}`}
                          >
                            <span style={{ flex: 1, fontSize: '0.75rem', fontWeight: 600, color: 'var(--text-primary)', lineHeight: 1.25 }}>{p.name}</span>
                            <span style={{ fontSize: '0.72rem', fontWeight: 800, color: st === 'Out' ? '#ef4444' : '#d97706', whiteSpace: 'nowrap', fontVariantNumeric: 'tabular-nums' }}>
                              {p.stock_qty ?? p.quantity ?? 0} {p.unit || 'pcs'}
                            </span>
                          </div>
                        )
                      })}
                      {products.filter(p => getStatus(p) !== 'In Stock').length > 10 && (
                        <button className="btn btn-secondary btn-sm" style={{ marginTop: 4 }}
                          onClick={() => { setStockStatusFilter('low'); setActiveView('catalogue') }}>
                          View all alerts →
                        </button>
                      )}
                    </div>
                  )}
                </div>

                {/* Purchase panel (distributor · tax breakdown · summary · payment · print) */}
                {activeView === 'intake' && intakeRows.length > 0 && (
                  <IntakePurchasePanel rows={intakeRows} authFetch={authFetch} distributor={intakeDistributor} setDistributor={setIntakeDistributor} adjustments={intakeAdjustments} setAdjustments={setIntakeAdjustments} payment={intakePayment} setPayment={setIntakePayment} onPrint={printGRN} />
                )}
              </>
            )}
          </div>
        </div>
      </div>

      {/* ── Modals ──────────────────────────────────────────────────────────── */}
      <LabelPrintModal open={showLabelModal} onClose={() => setShowLabelModal(false)} products={products} preselectIds={[...selectedIds]} />
      <BulkAddProductsModal open={showBulkAdd} existingProducts={products} onClose={() => setShowBulkAdd(false)} onSaved={(n) => { setAlert({ type: 'success', msg: `${n} product(s) added!` }); load() }} />
      <ProductFormModal
        open={showAddModal || !!editProduct} product={editProduct} prefillBarcode={prefillBarcode}
        onClose={() => { setShowAddModal(false); setEditProduct(null) }}
        onSaved={(what) => { setShowAddModal(false); setEditProduct(null); setAlert({ type: 'success', msg: `Product ${what} successfully!` }); load() }}
      />
      <ScanStockInModal open={showScanModal} initialCode={scanInitialCode}
        onClose={() => { setShowScanModal(false); setScanInitialCode(''); setSearch('') }}
        onStocked={() => load()} onAddNew={(code) => { setPrefillBarcode(code); setEditProduct(null); setShowAddModal(true) }} />

      {/* Adjust Stock Modal */}
      {showAdjustModal && (
        <div className="modal-overlay" onClick={e => e.target === e.currentTarget && setShowAdjustModal(false)}>
          <div className="modal">
            <div className="modal-header">
              <span className="modal-title"><ZapIcon size={14} style={{ marginRight: 6 }} /> Adjust Stock</span>
              <button className="btn btn-ghost btn-icon" onClick={() => setShowAdjustModal(false)}><CloseIcon size={16} /></button>
            </div>
            <form onSubmit={handleAdjust}>
              <div className="modal-body">
                <div className="form-group mb-4">
                  <label className="form-label">Select Product *</label>
                  <CustomSelect className="form-select" value={adjustForm.product_id} onChange={e => setAdjField('product_id', e.target.value)} required>
                    <option value="">Choose a product…</option>
                    {products.map(p => <option key={p.id} value={p.id}>{p.name} (Stock: {p.stock_qty ?? p.quantity ?? 0} {p.unit || ''})</option>)}
                  </CustomSelect>
                </div>
                <div className="grid grid-2 gap-3 mb-4">
                  <div className="form-group">
                    <label className="form-label">Movement Type</label>
                    <CustomSelect className="form-select" value={adjustForm.movement_type} onChange={e => setAdjField('movement_type', e.target.value)}>
                      <option value="stock_in">Stock In</option>
                      <option value="stock_out">Stock Out</option>
                      <option value="adjustment">Adjustment</option>
                    </CustomSelect>
                  </div>
                  <div className="form-group">
                    <label className="form-label">Quantity</label>
                    <input type="number" className="form-input" placeholder="0" min="0" step="any" value={adjustForm.quantity} onChange={e => setAdjField('quantity', e.target.value)} required />
                  </div>
                </div>
                <div className="form-group mb-4">
                  <label className="form-label">Reason *</label>
                  <input className="form-input" required placeholder="e.g. Damaged goods, count correction…" value={adjustForm.reason} onChange={e => setAdjField('reason', e.target.value)} />
                </div>
                <div className="form-group">
                  <label className="form-label">Reference</label>
                  <input className="form-input" placeholder="PO / GRN number…" value={adjustForm.reference} onChange={e => setAdjField('reference', e.target.value)} />
                </div>
              </div>
              <div className="modal-footer">
                <button type="button" className="btn btn-secondary" onClick={() => setShowAdjustModal(false)}>Cancel</button>
                <button type="submit" className="btn btn-primary" disabled={submitting}>
                  {submitting ? <><span className="spinner" style={{ width: 14, height: 14, borderWidth: 2 }} /> Adjusting…</> : <><CheckIcon size={14} /> Apply</>}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Transfer Stock Modal */}
      {showTransferModal && (
        <div className="modal-overlay" onClick={e => e.target === e.currentTarget && setShowTransferModal(false)}>
          <div className="modal">
            <div className="modal-header">
              <span className="modal-title"><SyncIcon size={14} style={{ marginRight: 6 }} /> Transfer Stock</span>
              <button className="btn btn-ghost btn-icon" onClick={() => setShowTransferModal(false)}><CloseIcon size={16} /></button>
            </div>
            <form onSubmit={handleTransferStock}>
              <div className="modal-body">
                <div className="form-group mb-4">
                  <label className="form-label">Select Product *</label>
                  <CustomSelect className="form-select" value={transferForm.product_id} onChange={e => setTrsfField('product_id', e.target.value)} required>
                    <option value="">Choose a product…</option>
                    {products.map(p => <option key={p.id} value={p.id}>{p.name} (Total Stock: {p.stock_qty ?? p.quantity ?? 0} {p.unit || ''})</option>)}
                  </CustomSelect>
                </div>
                <div className="grid grid-2 gap-3 mb-4">
                  <div className="form-group">
                    <label className="form-label">From Godown *</label>
                    <CustomSelect className="form-select" value={transferForm.from_godown_id} onChange={e => setTrsfField('from_godown_id', e.target.value)} required>
                      <option value="">Select source…</option>
                      {godowns.map(g => <option key={g.id} value={g.id}>{g.name}</option>)}
                    </CustomSelect>
                  </div>
                  <div className="form-group">
                    <label className="form-label">To Godown *</label>
                    <CustomSelect className="form-select" value={transferForm.to_godown_id} onChange={e => setTrsfField('to_godown_id', e.target.value)} required>
                      <option value="">Select destination…</option>
                      {godowns.map(g => <option key={g.id} value={g.id}>{g.name}</option>)}
                    </CustomSelect>
                  </div>
                </div>
                <div className="form-group mb-4">
                  <label className="form-label">Quantity *</label>
                  <input type="number" className="form-input" placeholder="0" min="0.001" step="any" value={transferForm.quantity} onChange={e => setTrsfField('quantity', e.target.value)} required />
                </div>
                <div className="form-group">
                  <label className="form-label">Notes</label>
                  <input className="form-input" placeholder="Reason for transfer…" value={transferForm.notes} onChange={e => setTrsfField('notes', e.target.value)} />
                </div>
              </div>
              <div className="modal-footer">
                <button type="button" className="btn btn-secondary" onClick={() => setShowTransferModal(false)}>Cancel</button>
                <button type="submit" className="btn btn-primary" disabled={submitting}>
                  {submitting ? <><span className="spinner" style={{ width: 14, height: 14, borderWidth: 2 }} /> Transferring…</> : <><CheckIcon size={14} /> Transfer Stock</>}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </PageShell>
  )
}
