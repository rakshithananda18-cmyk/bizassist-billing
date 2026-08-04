// ============================================================================
// Page: Purchases.jsx
// Description: Purchase Ledger & OCR Bill Processing. Registers vendor purchase
//              bills, supports parsing scanned PDFs via Claude/Groq OCR, creates
//              new batches, and records debit note purchase returns.
// ============================================================================
import React, { useEffect, useState, useCallback, useRef } from 'react'
import { useSearchParams } from 'react-router-dom'
import PageShell from '../components/common/PageShell'
import { useAuth } from '../contexts/AuthContext'
import { useConfirm } from '../contexts/ConfirmContext'
import { BillsIcon, CheckIcon, CopyIcon, ChevronLeftIcon, ChevronRightIcon, CloseIcon, DownloadIcon, ImportIcon, InfoIcon, SearchIcon, SyncIcon, UploadIcon, ExpandIcon } from '../components/Icons'
import CustomSelect from '../components/common/CustomSelect'
import PurchaseOcrModal from '../components/purchases/PurchaseOcrModal'
import PurchaseReturnModal from '../components/purchases/PurchaseReturnModal'
import PurchaseDetailModal from '../components/purchases/PurchaseDetailModal'
import WorkspaceTopBar, { WsDivider } from '../components/common/WorkspaceTopBar'
import { usePageLifecycle } from '../hooks/usePageLifecycle'
import ContextMenu from '../components/common/ContextMenu'
import UnsavedChangesModal from '../components/common/UnsavedChangesModal'
import { logger } from '../utils/logger'

const fmt = (n) =>
  n != null ? `₹${Number(n).toLocaleString('en-IN', { maximumFractionDigits: 2 })}` : '—'

// ============================================================================
// ── 2. STATE INITIALIZATION (BILLS & MODALS) ──
// ============================================================================
export default function Purchases({ embedded = false, headerTabs = null, inlinePage = false }) {
  // See Stock.jsx — same trial flag, same removal condition. Purchase Bills
  // already had showMinimize={false}, so only the close button differs here.
  const { authFetch, settings } = useAuth()
  const confirm = useConfirm()

  const settingsRef = useRef(settings)
  useEffect(() => {
    settingsRef.current = settings
  }, [settings])

  const [bills, setBills]           = useState([])
  const [debitNotes, setDebitNotes] = useState([])
  const [loading, setLoading]       = useState(true)
  const [activeTab, setActiveTab]   = useState('Pending Review')
  const [isFullScreen, setIsFullScreen] = useState(false)
  // `?vendor=` seeds the search box so Contacts can drill through to a supplier's
  // bills. The existing filter already matches supplier_name — no second filter.
  const [urlParams] = useSearchParams()
  const [search, setSearch]         = useState(urlParams.get('vendor') || '')
  const [showModal, setShowModal]   = useState(false)
  const [dragOver, setDragOver]     = useState(false)
  const [file, setFile]             = useState(null)
  const [uploading, setUploading]   = useState(false)
  const [step, setStep]             = useState('upload') // 'upload' | 'review'
  const [extracted, setExtracted]   = useState(null)
  const [confirming, setConfirming] = useState(false)
  const [alert, setAlert]           = useState(null)
  const [catalogProducts, setCatalogProducts] = useState([])
  const fileRef = useRef()

  // Purchase Returns / Debit Notes States
  const [showReturnModal, setShowReturnModal] = useState(false)
  const [returnStep, setReturnStep] = useState('select_bill') // 'select_bill' | 'enter_items'
  const [returnSupplier, setReturnSupplier] = useState('')
  const [returnBillId, setReturnBillId] = useState('')
  const [returnLines, setReturnLines] = useState([])
  const [returnNote, setReturnNote] = useState('')
  const [debitNoteNoInput, setDebitNoteNoInput] = useState('')

  // Detail Viewer State
  const [showDetailModal, setShowDetailModal] = useState(false)
  const [selectedDetail, setSelectedDetail] = useState(null)

  const [sortConfig, setSortConfig] = useState({ key: '', direction: '' })

  // Right-click context menu
  const [ctxMenu, setCtxMenu] = useState(null)

  // Page lifecycle: guard when OCR review is in-progress, refresh on tab resume
  const { blocker, isRefreshing, dirtyMessage } = usePageLifecycle({
    isDirty:      () => showModal && step === 'review' && extracted !== null,
    dirtyMessage: 'You are reviewing a scanned bill. Leave and discard changes?',
    onResume:     () => load(),   // throttled refresh on return (was a window 'focus' listener)
  })

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

  useEffect(() => {
    if (showModal && step === 'review') {
      authFetch('/products?per_page=1000')
        .then(r => r.ok ? r.json() : { items: [] })
        .then(data => {
          setCatalogProducts(data.items || [])
        })
        .catch(() => {})
    }
  }, [showModal, step, authFetch])

  const handleHeaderChange = (field, value) => {
    setExtracted(prev => {
      if (!prev) return null
      return { ...prev, [field]: value }
    })
  }

  const recalculateDraftTotals = (draft, items) => {
    let subtotal = 0
    let cgst_total = 0
    let sgst_total = 0
    let igst_total = 0

    const normalizedItems = items.map(item => {
      const quantity = parseFloat(item.quantity) || 0
      const unitPrice = parseFloat(item.unit_price) || 0
      const taxable_value = Number((quantity * unitPrice).toFixed(2))
      const cgst_amount = Number((taxable_value * ((parseFloat(item.cgst_rate) || 0) / 100)).toFixed(2))
      const sgst_amount = Number((taxable_value * ((parseFloat(item.sgst_rate) || 0) / 100)).toFixed(2))
      const igst_amount = Number((taxable_value * ((parseFloat(item.igst_rate) || 0) / 100)).toFixed(2))
      const line_total = Number((taxable_value + cgst_amount + sgst_amount + igst_amount).toFixed(2))
      subtotal += taxable_value
      cgst_total += cgst_amount
      sgst_total += sgst_amount
      igst_total += igst_amount
      return { ...item, taxable_value, cgst_amount, sgst_amount, igst_amount, line_total }
    })

    subtotal = Number(subtotal.toFixed(2))
    cgst_total = Number(cgst_total.toFixed(2))
    sgst_total = Number(sgst_total.toFixed(2))
    igst_total = Number(igst_total.toFixed(2))
    const cess_total = parseFloat(draft.cess_total) || 0
    const discount_total = parseFloat(draft.discount_total) || 0
    const round_off = parseFloat(draft.round_off) || 0

    return {
      ...draft,
      items: normalizedItems,
      subtotal,
      cgst_total,
      sgst_total,
      igst_total,
      total_amount: Number((subtotal + cgst_total + sgst_total + igst_total + cess_total - discount_total + round_off).toFixed(2)),
    }
  }

  // Approval-table completeness: a row the owner does NOT approve must be
  // removable before commit — a wrongly-extracted line never reaches the books.
  const handleRemoveItem = (index) => {
    setExtracted(prev => {
      if (!prev) return null
      return recalculateDraftTotals(prev, prev.items.filter((_, i) => i !== index))
    })
  }

  const handleItemChange = (index, field, value) => {
    setExtracted(prev => {
      if (!prev) return null
      const newItems = [...prev.items]
      const item = { ...newItems[index] }
      
      // Keep keys aligned to schema
      if (field === 'quantity') {
        item.quantity = value;
      } else if (field === 'unit_price') {
        item.unit_price = value;
      } else {
        item[field] = value;
      }

      newItems[index] = item
      return recalculateDraftTotals(prev, newItems)
    })
  }

  // ============================================================================
  // ── 3. DATA LOADERS & INITIAL EFFECTS ──
  // ============================================================================
  const load = useCallback(() => {
    setLoading(true)
    Promise.all([
      authFetch('/purchases').then(r => r.ok ? r.json() : []),
      authFetch('/purchases/debit-notes').then(r => r.ok ? r.json() : [])
    ])
      .then(([purData, dnData]) => {
        setBills(Array.isArray(purData) ? purData : [])
        setDebitNotes(Array.isArray(dnData) ? dnData : [])
      })
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [authFetch])

  useEffect(() => {
    load()
    const handleSync = (e) => {
      const currentSettings = settingsRef.current
      const isPurchasesSyncEnabled = currentSettings?.general?.realtime_sync_purchases !== false
      if (!isPurchasesSyncEnabled) return
      logger.debug('[PURCHASES] Real-time sync event received:', e.detail)
      if (['purchase', 'payment', 'party'].includes(e.detail.entity) || e.detail?.type === 'sync.reconnect') {
        load()
      }
    }
    // Foreground refresh (focus/visibility) is handled by usePageLifecycle,
    // throttled — no separate 'focus' listener here (that caused a double reload).
    window.addEventListener('sync-event', handleSync)
    return () => {
      window.removeEventListener('sync-event', handleSync)
    }
  }, [load])

  const getFilteredItems = () => {
    const q = search.toLowerCase()
    let items = []
    if (activeTab === 'Returns (Debit Notes)') {
      items = debitNotes.filter(dn => {
        return !q || dn.invoice_number?.toLowerCase().includes(q) || dn.supplier_name?.toLowerCase().includes(q)
      })
    } else {
      items = bills.filter(b => {
        if (activeTab === 'Pending Review' && b.status !== 'pending') return false
        if (activeTab === 'Confirmed' && b.status !== 'confirmed') return false
        return !q || b.invoice_number?.toLowerCase().includes(q) || b.bill_number?.toLowerCase().includes(q) || b.supplier_name?.toLowerCase().includes(q)
      })
    }

    if (sortConfig.key && sortConfig.direction) {
      items.sort((a, b) => {
        let aVal = a[sortConfig.key]
        let bVal = b[sortConfig.key]

        if (sortConfig.key === 'id_number') {
          aVal = a.invoice_number || a.bill_number || `#${a.id}`
          bVal = b.invoice_number || b.bill_number || `#${b.id}`
        } else if (sortConfig.key === 'date') {
          aVal = a.date || a.invoice_date || ''
          bVal = b.date || b.invoice_date || ''
        } else if (sortConfig.key === 'item_count') {
          aVal = a.item_count ?? a.items?.length ?? a.lines?.length ?? 0
          bVal = b.item_count ?? b.items?.length ?? b.lines?.length ?? 0
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

  const filtered = getFilteredItems()

  const handleFileDrop = (e) => {
    e.preventDefault()
    setDragOver(false)
    const dropped = e.dataTransfer?.files?.[0]
    if (dropped) setFile(dropped)
  }

  // ============================================================================
  // ── 4. BILL UPLOAD & AI OCR EXTRACTOR ──
  // ============================================================================
  const handleUpload = async () => {
    if (!file) return
    setUploading(true)
    const fd = new FormData()
    fd.append('file', file)
    try {
      const res = await authFetch('/purchases/upload', {
        method: 'POST',
        headers: {},
        body: fd,
      })
      if (res.ok) {
        const data = await res.json()
        setExtracted(data)
        setStep('review')
      } else {
        setAlert({ type: 'danger', msg: 'Upload failed. Please try again.' })
        setShowModal(false)
      }
    } catch {
      setAlert({ type: 'danger', msg: 'Network error during upload.' })
      setShowModal(false)
    } finally {
      setUploading(false)
    }
  }

  const handleConfirm = async () => {
    if (!extracted) return
    const summary = []
    if (extracted.supplier_name) summary.push({ key: 'supplier', label: 'Supplier', value: extracted.supplier_name })
    if (extracted.total_amount != null) summary.push({ key: 'total', label: 'Total', value: fmt(extracted.total_amount) })
    if (Array.isArray(extracted.lines)) summary.push({ key: 'items', label: 'Items', value: String(extracted.lines.length) })
    const ok = await confirm({
      mode: 'create',
      title: 'Add purchase bill?',
      message: 'Confirm this bill and add it to purchases — stock and the supplier ledger will update.',
      summary,
      confirmText: 'Confirm & add',
    })
    if (!ok) return
    setConfirming(true)
    try {
      const res = await authFetch('/purchases/confirm', {
        method: 'POST',
        body: JSON.stringify(extracted)
      })
      if (res.ok) {
        setAlert({ type: 'success', msg: 'Bill confirmed and added to purchases!' })
        setShowModal(false)
        resetModal()
        load()
      } else {
        const error = await res.json().catch(() => null)
        setAlert({
          type: 'danger',
          msg: error?.detail || 'The bill could not be confirmed. Please review it and try again.'
        })
      }
    } catch {
      setAlert({ type: 'danger', msg: 'Network error.' })
    } finally {
      setConfirming(false)
    }
  }

  const resetModal = () => {
    setFile(null)
    setStep('upload')
    setExtracted(null)
    setDragOver(false)
  }

  const openModal = () => { resetModal(); setShowModal(true) }

  // Returns logic
  const resetReturnForm = () => {
    setReturnStep('select_bill')
    setReturnSupplier('')
    setReturnBillId('')
    setReturnLines([])
    setReturnNote('')
    setDebitNoteNoInput('')
  }

  const openReturnModal = () => {
    resetReturnForm()
    setShowReturnModal(true)
  }

  const handleSelectBillNext = () => {
    const origBill = bills.find(b => String(b.id) === String(returnBillId))
    if (!origBill) return
    
    const lines = (origBill.lines || []).map(li => ({
      product_id: li.product_id,
      product_name: li.product_name,
      quantity: 0,
      max_quantity: li.quantity || 1,
      unit_price: li.unit_price || 0,
      cgst_rate: li.cgst_rate || 0,
      sgst_rate: li.sgst_rate || 0,
      igst_rate: li.igst_rate || 0,
      hsn_sac: li.hsn_sac,
      unit: li.unit || 'Nos',
      reason: 'Damaged'
    }))
    
    setReturnLines(lines)
    setReturnStep('enter_items')
  }

  const handleSaveReturn = async () => {
    const activeLines = returnLines.filter(l => l.quantity > 0)
    if (activeLines.length === 0) {
      setAlert({ type: 'danger', msg: 'Please enter a return quantity greater than zero for at least one item.' })
      return
    }
    
    const invalidLine = activeLines.find(l => l.quantity > l.max_quantity)
    if (invalidLine) {
      setAlert({ type: 'danger', msg: `Return quantity for ${invalidLine.product_name} cannot exceed original quantity (${invalidLine.max_quantity}).` })
      return
    }

    const ok = await confirm({
      mode: 'create',
      title: 'Record purchase return?',
      message: `Record this debit note for ${activeLines.length} item${activeLines.length > 1 ? 's' : ''}? Stock and the supplier ledger will update.`,
      confirmText: 'Record return',
    })
    if (!ok) return

    setConfirming(true)
    try {
      const res = await authFetch('/purchases/debit-notes', {
        method: 'POST',
        body: JSON.stringify({
          original_purchase_id: parseInt(returnBillId),
          debit_note_number: debitNoteNoInput || undefined,
          lines: activeLines.map(l => ({
            product_id: l.product_id,
            quantity: parseFloat(l.quantity),
            reason: l.reason
          })),
          note: returnNote
        })
      })
      if (res.ok) {
        setAlert({ type: 'success', msg: 'Debit note recorded successfully! Stock and supplier ledger updated.' })
        setShowReturnModal(false)
        resetReturnForm()
        load()
      } else {
        const err = await res.json().catch(() => ({}))
        setAlert({ type: 'danger', msg: err.detail || 'Failed to record debit note.' })
      }
    } catch {
      setAlert({ type: 'danger', msg: 'Network error.' })
    } finally {
      setConfirming(false)
    }
  }

  const handleViewDetail = (item) => {
    setSelectedDetail(item)
    setShowDetailModal(true)
  }

  // ============================================================================
  // ── 5. RENDER BILLS CATALOG LAYOUT (JSX) ──
  // ============================================================================
  // True when the workspace toolbar is on screen, so the sub-tabs and the
  // standalone page header must NOT also render — otherwise the view shows the
  // Pending/Confirmed/Returns tabs twice, and its own title under the
  // workspace's. Was `headerTabs` alone, which missed the inlinePage case.
  const tabsInBar = Boolean(headerTabs) || inlinePage

  // Search box, defined once. It goes INSIDE the workspace toolbar when
  // embedded — otherwise this view spends a whole 48px row on a single input,
  // which is what the other three tabs stopped doing.
  const searchBox = (
    <div className="search-bar" style={{ margin: 0, height: 34, boxSizing: 'border-box', display: 'flex', alignItems: 'center', flex: '1 1 170px', minWidth: 150, maxWidth: 280 }}>
      <span style={{ color: 'var(--text-muted)', display: 'flex', alignItems: 'center' }}><SearchIcon size={16} /></span>
      <input value={search} onChange={e => setSearch(e.target.value)} placeholder="Search bills…" style={{ fontSize: '0.82rem' }} />
    </div>
  )

  return (
    <PageShell embedded={embedded} title="Purchases">
      <div className={`${tabsInBar ? 'fade-in ws-embed' : 'slide-up'}`}>

        {/* Embedded (Godown): the SAME 48px workspace bar as the Stock tab —
            workspace tabs · divider · view tabs · actions · window controls.
            `inlinePage` gets it too: StockWorkspace passes no headerTabs (its
            tabs live in the page header), and without this the tab rendered NO
            toolbar and fell through to the standalone page header below —
            a second "Purchases" title under the workspace's own. */}
        {(headerTabs || inlinePage) && (
          <WorkspaceTopBar
            settingsTab="transactions"
            windowControls={!inlinePage}
            showMinimize={false}
            actions={
              <>
                {searchBox}
                <button className="btn btn-secondary btn-sm" style={{ display: 'inline-flex', alignItems: 'center', gap: 5 }} onClick={openReturnModal}>
                  <SyncIcon size={13} /> Record Return
                </button>
                <button className="btn btn-primary btn-sm" style={{ display: 'inline-flex', alignItems: 'center', gap: 5 }} onClick={openModal}>
                  <UploadIcon size={13} /> Upload Bill
                </button>
              </>
            }
          >
            {/* Page icon & name — matches Stock.jsx left alignment. Said
                "Stock & Inventory" on the PURCHASES bar; harmless while both
                tabs showed the same string, wrong the moment this bar appears
                under a workspace header that already says it. */}
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, paddingRight: 4 }}>
              <BillsIcon size={18} style={{ color: 'var(--accent)' }} />
              <span style={{ fontWeight: 800, fontSize: '0.9rem', color: 'var(--text-primary)', whiteSpace: 'nowrap' }}>
                Purchase Bills
              </span>
            </div>
            <WsDivider />
            {/* Outer workspace tabs (Stock & Items | Purchase Bills) */}
            {headerTabs}
            {headerTabs && <WsDivider />}
            {/* Inner sub-tabs: Pending Review · Confirmed · Returns */}
            {['Pending Review', 'Confirmed', 'Returns (Debit Notes)'].map(t => (
              <button key={t} className={`ws-tab ${activeTab === t ? 'active' : ''}`} onClick={() => setActiveTab(t)}>
                {t}
                <span style={{ fontSize: '0.68rem', opacity: 0.7 }}>
                  ({
                    t === 'Returns (Debit Notes)'
                      ? debitNotes.length
                      : bills.filter(b => b.status === (t === 'Pending Review' ? 'pending' : 'confirmed')).length
                  })
                </span>
              </button>
            ))}
          </WorkspaceTopBar>
        )}

        {alert && (
          <div className={`alert alert-${alert.type} mb-4`}>
            {alert.type === 'success' ? '✅' : '❌'} {alert.msg}
            <button onClick={() => setAlert(null)} style={{ marginLeft: 'auto', background: 'none', border: 'none', color: 'inherit', cursor: 'pointer' }} aria-label="Close"><CloseIcon size={16} /></button>
          </div>
        )}

        {/* Standalone header (legacy /purchases route only) */}
        {!tabsInBar && (
          <div className="page-header">
            <div className="page-header-left">
              <h1 className="page-title">Purchases</h1>
              <p className="page-subtitle">Upload and manage supplier bills with AI-powered extraction</p>
            </div>
            <div className="page-actions">
              <button className="btn btn-secondary" style={{ marginRight: 8 }} onClick={openReturnModal}>
                <SyncIcon size={14} style={{ marginRight: 6, display: 'inline-block', verticalAlign: 'middle' }} /> Record Return
              </button>
              <button className="btn btn-primary" onClick={openModal}>
                ⬆ Upload Bill
              </button>
            </div>
          </div>
        )}

        {/* Tabs + Search (tabs live in the top bar when embedded) */}
        {!tabsInBar && (
        <div className="flex items-center justify-between page-subbar" style={{ flexWrap: 'wrap', gap: 12 }}>
          <div className="tabs">
            {['Pending Review', 'Confirmed', 'Returns (Debit Notes)'].map(t => (
              <button key={t} className={`tab${activeTab === t ? ' active' : ''}`} onClick={() => setActiveTab(t)}>
                {t}
                <span style={{ marginLeft: 4, fontSize: '0.68rem', opacity: 0.7 }}>
                  ({
                    t === 'Returns (Debit Notes)'
                      ? debitNotes.length
                      : bills.filter(b => b.status === (t === 'Pending Review' ? 'pending' : 'confirmed')).length
                  })
                </span>
              </button>
            ))}
          </div>
          {searchBox}
          {isRefreshing && (
            <span className="toolbar-refresh-spinner">
              <span className="spin" /> Refreshing…
            </span>
          )}
        </div>
        )}

        {/* Table */}
        {(() => {
          const tableContent = (
            <table className="data-table">
              <thead><tr>
                <th className="sortable" onClick={() => handleSort('id_number')}>
                  Bill / Return #
                  <span className={`sort-indicator ${sortConfig.key === 'id_number' && sortConfig.direction ? 'active' : ''}`}>
                    {sortConfig.key === 'id_number' && sortConfig.direction ? (sortConfig.direction === 'asc' ? '▲' : '▼') : '⇅'}
                  </span>
                </th>
                <th className="sortable" onClick={() => handleSort('supplier_name')}>
                  Supplier
                  <span className={`sort-indicator ${sortConfig.key === 'supplier_name' && sortConfig.direction ? 'active' : ''}`}>
                    {sortConfig.key === 'supplier_name' && sortConfig.direction ? (sortConfig.direction === 'asc' ? '▲' : '▼') : '⇅'}
                  </span>
                </th>
                <th className="sortable" onClick={() => handleSort('date')}>
                  Date
                  <span className={`sort-indicator ${sortConfig.key === 'date' && sortConfig.direction ? 'active' : ''}`}>
                    {sortConfig.key === 'date' && sortConfig.direction ? (sortConfig.direction === 'asc' ? '▲' : '▼') : '⇅'}
                  </span>
                </th>
                <th className="sortable" onClick={() => handleSort('item_count')}>
                  Items
                  <span className={`sort-indicator ${sortConfig.key === 'item_count' && sortConfig.direction ? 'active' : ''}`}>
                    {sortConfig.key === 'item_count' && sortConfig.direction ? (sortConfig.direction === 'asc' ? '▲' : '▼') : '⇅'}
                  </span>
                </th>
                <th className="sortable" onClick={() => handleSort('total_amount')}>
                  Total
                  <span className={`sort-indicator ${sortConfig.key === 'total_amount' && sortConfig.direction ? 'active' : ''}`}>
                    {sortConfig.key === 'total_amount' && sortConfig.direction ? (sortConfig.direction === 'asc' ? '▲' : '▼') : '⇅'}
                  </span>
                </th>
                <th className="sortable" onClick={() => handleSort('status')}>
                  Status
                  <span className={`sort-indicator ${sortConfig.key === 'status' && sortConfig.direction ? 'active' : ''}`}>
                    {sortConfig.key === 'status' && sortConfig.direction ? (sortConfig.direction === 'asc' ? '▲' : '▼') : '⇅'}
                  </span>
                </th>
                <th style={{ textAlign: 'right' }}>Actions</th>
              </tr></thead>
              <tbody>
                {filtered.length === 0 ? (
                  <tr><td colSpan={7}>
                    <div className="empty-state">
                      <div className="empty-icon">{activeTab === 'Returns (Debit Notes)' ? <SyncIcon size={24} /> : <BillsIcon size={24} />}</div>
                      <h3>{activeTab === 'Returns (Debit Notes)' ? 'No returns found' : 'No bills found'}</h3>
                      <p>{search ? 'Try a different search term.' : (activeTab === 'Returns (Debit Notes)' ? 'Record a return to get started.' : 'Upload a bill to get started.')}</p>
                    </div>
                  </td></tr>
                ) : filtered.map(b => (
                  <tr
                    key={b.id}
                    style={{ cursor: 'context-menu' }}
                    onContextMenu={e => {
                      e.preventDefault()
                      setCtxMenu({ x: e.clientX, y: e.clientY, items: [
                        { label: 'View Details', icon: <BillsIcon size={13} />, action: () => handleViewDetail(b) },
                        { divider: true },
                        { label: 'Copy Bill No', icon: <CopyIcon size={13} />, action: () => navigator.clipboard.writeText(b.invoice_number || b.bill_number || String(b.id)) },
                        { label: 'Copy Supplier', icon: <CopyIcon size={13} />, action: () => navigator.clipboard.writeText(b.supplier_name || '') },
                      ]})
                    }}
                  >
                    <td className="td-mono td-primary">{b.invoice_number || b.bill_number || `#${b.id}`}</td>
                    <td className="td-primary">{b.supplier_name || '—'}</td>
                    <td>{b.date || b.invoice_date ? new Date(b.date || b.invoice_date).toLocaleDateString('en-IN') : '—'}</td>
                    <td style={{ color: 'var(--text-muted)' }}>{b.item_count ?? b.items?.length ?? b.lines?.length ?? '—'}</td>
                    <td style={{ color: 'var(--text-primary)', fontWeight: 600 }}>{fmt(b.total_amount)}</td>
                    <td>
                      {activeTab === 'Returns (Debit Notes)' ? (
                        <span className="badge badge-accent">Returned</span>
                      ) : (
                        <span className={`badge ${b.status === 'confirmed' ? 'badge-success' : 'badge-warning'}`}>{b.status || 'pending'}</span>
                      )}
                    </td>
                    <td style={{ textAlign: 'right' }}>
                      <div style={{ display: 'flex', gap: 6, justifyContent: 'flex-end' }}>
                        <button className="btn btn-secondary btn-sm" onClick={() => handleViewDetail(b)}>View</button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )
          if (loading) return <div className="page-loader"><span className="spinner" /> Loading bills…</div>
          if (isFullScreen) return (
            <div className="table-fullscreen-overlay" onClick={e => { if (e.target === e.currentTarget) setIsFullScreen(false) }}>
              <div className="table-fullscreen-panel">
                <div className="table-fullscreen-header">
                  <h3>Purchase Bills — {activeTab}</h3>
                  <button type="button" className="table-fullscreen-btn" onClick={() => setIsFullScreen(false)}>✕ Close</button>
                </div>
                <div className="data-table-wrap">{tableContent}</div>
              </div>
            </div>
          )
          return (
            <div style={{ position: 'relative', display: 'flex', flexDirection: 'column', flex: 1, minHeight: 0 }}>
              <button type="button" onClick={() => setIsFullScreen(true)} style={{ position: 'absolute', top: 6, right: 6, zIndex: 10, background: 'var(--bg-1)', border: '1px solid var(--border)', borderRadius: 'var(--radius-sm)', padding: 4, cursor: 'pointer', color: 'var(--text-secondary)' }} title="Full Screen">
                <ExpandIcon size={14} />
              </button>
              <div className="data-table-wrap">{tableContent}</div>
            </div>
          )
        })()}
      </div>


      {/* Upload Modal */}
      {/* 🔍 Upload & Review (OCR) Modal — extracted to components/purchases/PurchaseOcrModal */}
      {showModal && (
        <PurchaseOcrModal
          setShowModal={setShowModal}
          step={step} setStep={setStep}
          dragOver={dragOver} setDragOver={setDragOver}
          handleFileDrop={handleFileDrop}
          fileRef={fileRef}
          file={file} setFile={setFile}
          extracted={extracted}
          handleHeaderChange={handleHeaderChange}
          handleItemChange={handleItemChange}
          handleRemoveItem={handleRemoveItem}
          catalogProducts={catalogProducts}
          uploading={uploading} handleUpload={handleUpload}
          confirming={confirming} handleConfirm={handleConfirm}
        />
      )}

      {/* 🔄 Purchase Returns (Debit Note) Modal */}
      {/* 🔄 Purchase Returns (Debit Note) Modal — extracted to components/purchases/PurchaseReturnModal */}
      {showReturnModal && (
        <PurchaseReturnModal
          setShowReturnModal={setShowReturnModal}
          returnStep={returnStep} setReturnStep={setReturnStep}
          returnSupplier={returnSupplier} setReturnSupplier={setReturnSupplier}
          returnBillId={returnBillId} setReturnBillId={setReturnBillId}
          bills={bills}
          debitNoteNoInput={debitNoteNoInput} setDebitNoteNoInput={setDebitNoteNoInput}
          returnLines={returnLines} setReturnLines={setReturnLines}
          returnNote={returnNote} setReturnNote={setReturnNote}
          handleSelectBillNext={handleSelectBillNext}
          confirming={confirming}
          handleSaveReturn={handleSaveReturn}
        />
      )}

      {/* 📄 View Details Modal */}
      {/* 📄 View Details Modal — extracted to components/purchases/PurchaseDetailModal */}
      {showDetailModal && selectedDetail && (
        <PurchaseDetailModal selectedDetail={selectedDetail} setShowDetailModal={setShowDetailModal} />
      )}
      <ContextMenu menu={ctxMenu} onClose={() => setCtxMenu(null)} />
      <UnsavedChangesModal blocker={blocker} message={dirtyMessage} />
    </PageShell>
  )
}
