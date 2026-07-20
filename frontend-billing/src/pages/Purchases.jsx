// ============================================================================
// Page: Purchases.jsx
// Description: Purchase Ledger & OCR Bill Processing. Registers vendor purchase
//              bills, supports parsing scanned PDFs via Claude/Groq OCR, creates
//              new batches, and records debit note purchase returns.
// ============================================================================
import React, { useEffect, useState, useCallback, useRef } from 'react'
import PageShell from '../components/common/PageShell'
import { useAuth } from '../contexts/AuthContext'
import { BillsIcon, CheckIcon, ChevronLeftIcon, ChevronRightIcon, CloseIcon, DownloadIcon, ImportIcon, InfoIcon, SearchIcon, SyncIcon, UploadIcon, ExpandIcon } from '../components/Icons'
import CustomSelect from '../components/common/CustomSelect'
import PurchaseOcrModal from '../components/purchases/PurchaseOcrModal'
import PurchaseReturnModal from '../components/purchases/PurchaseReturnModal'
import PurchaseDetailModal from '../components/purchases/PurchaseDetailModal'
import WorkspaceTopBar, { WsDivider } from '../components/common/WorkspaceTopBar'
import { usePageLifecycle } from '../hooks/usePageLifecycle'
import ContextMenu from '../components/common/ContextMenu'
import UnsavedChangesModal from '../components/common/UnsavedChangesModal'

const fmt = (n) =>
  n != null ? `₹${Number(n).toLocaleString('en-IN', { maximumFractionDigits: 2 })}` : '—'

// ============================================================================
// ── 2. STATE INITIALIZATION (BILLS & MODALS) ──
// ============================================================================
export default function Purchases({ embedded = false, headerTabs = null }) {
  const { authFetch, settings } = useAuth()

  const settingsRef = useRef(settings)
  useEffect(() => {
    settingsRef.current = settings
  }, [settings])

  const [bills, setBills]           = useState([])
  const [debitNotes, setDebitNotes] = useState([])
  const [loading, setLoading]       = useState(true)
  const [activeTab, setActiveTab]   = useState('Pending Review')
  const [isFullScreen, setIsFullScreen] = useState(false)
  const [search, setSearch]         = useState('')
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
    onResume:     () => { /* silent refresh handled inline */ },
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

  // Approval-table completeness: a row the owner does NOT approve must be
  // removable before commit — a wrongly-extracted line never reaches the books.
  const handleRemoveItem = (index) => {
    setExtracted(prev => {
      if (!prev) return null
      return { ...prev, items: prev.items.filter((_, i) => i !== index) }
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

      newItems[index] = item;
      
      const qty = parseFloat(item.quantity) || 0
      const price = parseFloat(item.unit_price) || 0
      const cgst = parseFloat(item.cgst_rate) || 0
      const sgst = parseFloat(item.sgst_rate) || 0
      const igst = parseFloat(item.igst_rate) || 0
      
      const taxable = qty * price
      item.taxable_value = parseFloat(taxable.toFixed(2))
      
      const cgstAmt = taxable * (cgst / 100)
      const sgstAmt = taxable * (sgst / 100)
      const igstAmt = taxable * (igst / 100)
      
      item.cgst_amount = parseFloat(cgstAmt.toFixed(2))
      item.sgst_amount = parseFloat(sgstAmt.toFixed(2))
      item.igst_amount = parseFloat(igstAmt.toFixed(2))
      
      item.line_total = parseFloat((taxable + cgstAmt + sgstAmt + igstAmt).toFixed(2))
      
      let subtotal = 0
      let cgst_total = 0
      let sgst_total = 0
      let igst_total = 0
      
      newItems.forEach(it => {
        const itQty = parseFloat(it.quantity) || 0
        const itPrice = parseFloat(it.unit_price) || 0
        const itTaxable = itQty * itPrice
        subtotal += itTaxable
        cgst_total += itTaxable * ((parseFloat(it.cgst_rate) || 0) / 100)
        sgst_total += itTaxable * ((parseFloat(it.sgst_rate) || 0) / 100)
        igst_total += itTaxable * ((parseFloat(it.igst_rate) || 0) / 100)
      })
      
      const total_amount = subtotal + cgst_total + sgst_total + igst_total
      
      return {
        ...prev,
        items: newItems,
        subtotal: parseFloat(subtotal.toFixed(2)),
        cgst_total: parseFloat(cgst_total.toFixed(2)),
        sgst_total: parseFloat(sgst_total.toFixed(2)),
        igst_total: parseFloat(igst_total.toFixed(2)),
        total_amount: parseFloat(total_amount.toFixed(2))
      }
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
    window.addEventListener('focus', load)
    window.addEventListener('sync-event', handleSync)
    return () => {
      window.removeEventListener('focus', load)
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
        setAlert({ type: 'danger', msg: 'Failed to confirm bill.' })
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
  return (
    <PageShell embedded={embedded} title="Purchases">
      <div className={`slide-up${headerTabs ? ' ws-embed' : ''}`}>

        {/* Embedded (Godown): the SAME 48px workspace bar as the Stock tab —
            workspace tabs · divider · view tabs · actions · window controls. */}
        {headerTabs && (
          <WorkspaceTopBar
            actions={
              <>
                <button className="btn btn-secondary btn-sm" style={{ display: 'inline-flex', alignItems: 'center', gap: 5 }} onClick={openReturnModal}>
                  <SyncIcon size={13} /> Record Return
                </button>
                <button className="btn btn-primary btn-sm" style={{ display: 'inline-flex', alignItems: 'center', gap: 5 }} onClick={openModal}>
                  <UploadIcon size={13} /> Upload Bill
                </button>
              </>
            }
          >
            {headerTabs}
            <WsDivider />
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
        {!headerTabs && (
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
        <div className="flex items-center justify-between page-subbar" style={{ flexWrap: 'wrap', gap: 12 }}>
          {!headerTabs ? (
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
          ) : <div />}
          <div className="search-bar">
            <span style={{ color: 'var(--text-muted)', display: 'flex', alignItems: 'center' }}><SearchIcon size={16} /></span>
            <input value={search} onChange={e => setSearch(e.target.value)} placeholder="Search bills…" />
          </div>
          {isRefreshing && (
            <span className="toolbar-refresh-spinner">
              <span className="spin" /> Refreshing…
            </span>
          )}
        </div>

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
                        { label: 'Copy Bill No', icon: <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>, action: () => navigator.clipboard.writeText(b.invoice_number || b.bill_number || String(b.id)) },
                        { label: 'Copy Supplier', icon: <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>, action: () => navigator.clipboard.writeText(b.supplier_name || '') },
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
