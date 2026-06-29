// ============================================================================
// Page: Purchases.jsx
// Description: Purchase Ledger & OCR Bill Processing. Registers vendor purchase
//              bills, supports parsing scanned PDFs via Claude/Groq OCR, creates
//              new batches, and records debit note purchase returns.
// ============================================================================
import React, { useEffect, useState, useCallback, useRef } from 'react'
import AppLayout from '../layouts/AppLayout'
import { useAuth } from '../contexts/AuthContext'
import { BillsIcon, CheckIcon, ChevronLeftIcon, ChevronRightIcon, CloseIcon, DownloadIcon, ImportIcon, InfoIcon, SearchIcon, SyncIcon, UploadIcon, ExpandIcon } from '../components/Icons'
import CustomSelect from '../components/common/CustomSelect'

const fmt = (n) =>
  n != null ? `₹${Number(n).toLocaleString('en-IN', { maximumFractionDigits: 2 })}` : '—'

// ============================================================================
// ── 2. STATE INITIALIZATION (BILLS & MODALS) ──
// ============================================================================
export default function Purchases() {
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
      if (['purchase', 'payment', 'party'].includes(e.detail.entity)) {
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
    <AppLayout title="Purchases">
      <div className="slide-up">

        {alert && (
          <div className={`alert alert-${alert.type} mb-4`}>
            {alert.type === 'success' ? '✅' : '❌'} {alert.msg}
            <button onClick={() => setAlert(null)} style={{ marginLeft: 'auto', background: 'none', border: 'none', color: 'inherit', cursor: 'pointer' }} aria-label="Close"><CloseIcon size={16} /></button>
          </div>
        )}

        {/* Header */}
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

        {/* Tabs + Search */}
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
          <div className="search-bar">
            <span style={{ color: 'var(--text-muted)', display: 'flex', alignItems: 'center' }}><SearchIcon size={16} /></span>
            <input value={search} onChange={e => setSearch(e.target.value)} placeholder="Search bills…" />
          </div>
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
                <th>Actions</th>
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
                  <tr key={b.id}>
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
                    <td><button className="btn btn-secondary btn-sm" onClick={() => handleViewDetail(b)}>View</button></td>
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
            <div style={{ position: 'relative' }}>
              <button type="button" onClick={() => setIsFullScreen(true)} style={{ position: 'absolute', top: 6, right: 6, zIndex: 10, background: 'var(--bg-1)', border: '1px solid var(--border)', borderRadius: 'var(--radius-sm)', padding: 4, cursor: 'pointer', color: 'var(--text-secondary)' }} title="Full Screen">
                <ExpandIcon size={14} />
              </button>
              <div className="data-table-wrap">{tableContent}</div>
            </div>
          )
        })()}
      </div>


      {/* Upload Modal */}
      {showModal && (
        <div className="modal-overlay" onClick={e => e.target === e.currentTarget && setShowModal(false)}>
          <div className="modal" style={{ maxWidth: step === 'review' ? '1200px' : '520px', width: '95%' }}>
            <div className="modal-header">
              <span className="modal-title">
                {step === 'upload' ? <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}><BillsIcon size={14} /> Upload Bill</span> : '🔍 Review Extracted Data'}
              </span>
              <button className="btn btn-ghost btn-icon" onClick={() => setShowModal(false)} aria-label="Close"><CloseIcon size={16} /></button>
            </div>

            <div className="modal-body">
              {step === 'upload' ? (
                <>
                  {/* Drag-drop zone */}
                  <div
                    onDragOver={e => { e.preventDefault(); setDragOver(true) }}
                    onDragLeave={() => setDragOver(false)}
                    onDrop={handleFileDrop}
                    onClick={() => fileRef.current?.click()}
                    style={{
                      border: `2px dashed ${dragOver ? 'var(--accent)' : 'var(--border)'}`,
                      borderRadius: 'var(--radius-lg)',
                      padding: '40px 24px',
                      textAlign: 'center',
                      cursor: 'pointer',
                      background: dragOver ? 'var(--accent-dim)' : 'var(--bg-3)',
                      transition: 'all 180ms ease',
                      display: 'flex',
                      flexDirection: 'column',
                      alignItems: 'center',
                      gap: 12,
                    }}
                  >
                    {dragOver ? <DownloadIcon size={32} style={{ color: 'var(--accent)' }} /> : <UploadIcon size={32} style={{ color: 'var(--accent)' }} />}
                    <div>
                      <div style={{ fontWeight: 600, color: 'var(--text-primary)', marginBottom: 4 }}>
                        {file ? file.name : 'Drag & drop your bill here'}
                      </div>
                      <div style={{ fontSize: '0.8rem', color: 'var(--text-muted)' }}>
                        {file ? `${(file.size / 1024).toFixed(1)} KB · ${file.type || 'file'}` : 'or click to browse · PDF, PNG, JPG supported'}
                      </div>
                    </div>
                    {file && (
                      <span className="badge badge-success">✓ File selected</span>
                    )}
                  </div>
                  <input
                    ref={fileRef}
                    type="file"
                    accept=".pdf,.png,.jpg,.jpeg"
                    style={{ display: 'none' }}
                    onChange={e => setFile(e.target.files?.[0] || null)}
                  />
                </>
              ) : (
                <>
                  {/* Extracted items review */}
                  <div className="alert alert-info mb-4" style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                    <InfoIcon size={16} style={{ color: 'var(--info)', marginRight: 6, display: 'inline-block', verticalAlign: 'middle' }} /> <span>AI extracted the following details. Correct any fields and verify product mappings before confirming.</span>
                  </div>

                  {/* Header info editing */}
                  <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: 16, marginBottom: 20 }}>
                    <div className="form-group">
                      <label className="form-label">Supplier Name</label>
                      <input
                        type="text"
                        className="form-input"
                        value={extracted?.supplier_name || ''}
                        onChange={e => handleHeaderChange('supplier_name', e.target.value)}
                      />
                    </div>
                    <div className="form-group">
                      <label className="form-label">Bill / Invoice Number</label>
                      <input
                        type="text"
                        className="form-input"
                        value={extracted?.invoice_number || ''}
                        onChange={e => handleHeaderChange('invoice_number', e.target.value)}
                      />
                    </div>
                    <div className="form-group">
                      <label className="form-label">Invoice Date</label>
                      <input
                        type="text"
                        className="form-input"
                        value={extracted?.invoice_date || ''}
                        onChange={e => handleHeaderChange('invoice_date', e.target.value)}
                        placeholder="YYYY-MM-DD"
                      />
                    </div>
                  </div>

                  {/* Table of items */}
                  <div style={{ marginBottom: 12 }}>
                    <div className="data-table-wrap" style={{ overflowX: 'auto' }}>
                      <table className="data-table" style={{ minWidth: 1000 }}>
                        <thead>
                          <tr>
                            <th>Extracted Info</th>
                            <th>Catalog Product</th>
                            <th>Product Name</th>
                            <th>Qty</th>
                            <th>Rate</th>
                            <th>Factor</th>
                            <th>P. Unit</th>
                            <th>Batch</th>
                            <th>Expiry</th>
                            <th>Barcode</th>
                            <th style={{ textAlign: 'right' }}>Total</th>
                          </tr>
                        </thead>
                        <tbody>
                          {extracted?.items?.length ? extracted.items.map((item, index) => {
                            const isMatched = item.is_matched || item.product_id;
                            const confidence = item.confidence_score != null ? Math.round(item.confidence_score * 100) : 0;
                            return (
                              <tr key={index}>
                                <td>
                                  <div style={{ fontWeight: 600, color: 'var(--text-primary)', fontSize: '0.82rem', maxWidth: 180, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }} title={item.product_name}>
                                    {item.product_name || '—'}
                                  </div>
                                  <div style={{ marginTop: 2 }}>
                                    {isMatched ? (
                                      <span className="badge badge-success" style={{ fontSize: '0.65rem', padding: '2px 6px' }}>Matched ({confidence}%)</span>
                                    ) : (
                                      <span className="badge badge-warning" style={{ fontSize: '0.65rem', padding: '2px 6px' }}>New Product</span>
                                    )}
                                  </div>
                                </td>
                                <td>
                                  <CustomSelect
                                    className="form-select"
                                    style={{ fontSize: '0.8rem', padding: '5px 8px', width: 150 }}
                                    value={item.product_id || 'new'}
                                    onChange={e => {
                                      const val = e.target.value;
                                      if (val === 'new') {
                                        handleItemChange(index, 'product_id', null);
                                        handleItemChange(index, 'is_matched', false);
                                      } else {
                                        const pid = parseInt(val);
                                        const matchedProd = catalogProducts.find(p => p.id === pid);
                                        handleItemChange(index, 'product_id', pid);
                                        handleItemChange(index, 'is_matched', true);
                                        if (matchedProd) {
                                          handleItemChange(index, 'product_name', matchedProd.name);
                                        }
                                      }
                                    }}
                                  >
                                    <option value="new">+ Create New Product</option>
                                    {catalogProducts.map(p => (
                                      <option key={p.id} value={p.id}>{p.name}</option>
                                    ))}
                                  </CustomSelect>
                                </td>
                                <td>
                                  <input
                                    type="text"
                                    className="form-input"
                                    style={{ fontSize: '0.8rem', padding: '5px 8px', width: 140 }}
                                    value={item.product_name || ''}
                                    onChange={e => handleItemChange(index, 'product_name', e.target.value)}
                                  />
                                </td>
                                <td>
                                  <input
                                    type="number"
                                    className="form-input"
                                    style={{ fontSize: '0.8rem', padding: '5px 8px', width: 65 }}
                                    value={item.quantity ?? 0}
                                    onChange={e => handleItemChange(index, 'quantity', parseFloat(e.target.value) || 0)}
                                  />
                                </td>
                                <td>
                                  <input
                                    type="number"
                                    className="form-input"
                                    style={{ fontSize: '0.8rem', padding: '5px 8px', width: 85 }}
                                    value={item.unit_price ?? 0}
                                    onChange={e => handleItemChange(index, 'unit_price', parseFloat(e.target.value) || 0)}
                                  />
                                </td>
                                <td>
                                  <input
                                    type="number"
                                    className="form-input"
                                    style={{ fontSize: '0.8rem', padding: '5px 8px', width: 60 }}
                                    value={item.conversion_factor ?? 1.0}
                                    onChange={e => handleItemChange(index, 'conversion_factor', parseFloat(e.target.value) || 1.0)}
                                  />
                                </td>
                                <td>
                                  <input
                                    type="text"
                                    className="form-input"
                                    style={{ fontSize: '0.8rem', padding: '5px 8px', width: 75 }}
                                    value={item.purchase_unit || ''}
                                    onChange={e => handleItemChange(index, 'purchase_unit', e.target.value)}
                                    placeholder="Box"
                                  />
                                </td>
                                <td>
                                  <input
                                    type="text"
                                    className="form-input"
                                    style={{ fontSize: '0.8rem', padding: '5px 8px', width: 85 }}
                                    value={item.batch || ''}
                                    onChange={e => handleItemChange(index, 'batch', e.target.value)}
                                    placeholder="Batch"
                                  />
                                </td>
                                <td>
                                  <input
                                    type="text"
                                    className="form-input"
                                    style={{ fontSize: '0.8rem', padding: '5px 8px', width: 90 }}
                                    value={item.expiry || ''}
                                    onChange={e => handleItemChange(index, 'expiry', e.target.value)}
                                    placeholder="Expiry"
                                  />
                                </td>
                                <td>
                                  <input
                                    type="text"
                                    className="form-input"
                                    style={{ fontSize: '0.8rem', padding: '5px 8px', width: 105 }}
                                    value={item.barcode || ''}
                                    onChange={e => handleItemChange(index, 'barcode', e.target.value)}
                                    placeholder="Barcode"
                                  />
                                </td>
                                <td style={{ fontWeight: 600, color: 'var(--text-primary)', textAlign: 'right', fontSize: '0.82rem' }}>
                                  {fmt(item.line_total)}
                                </td>
                              </tr>
                            );
                          }) : (
                            <tr><td colSpan={11} style={{ textAlign: 'center', color: 'var(--text-muted)' }}>No items extracted</td></tr>
                          )}
                        </tbody>
                      </table>
                    </div>

                    {/* Summary statistics */}
                    <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 24, marginTop: 16, fontSize: '0.85rem', fontWeight: 600 }}>
                      <div>Subtotal: <span style={{ color: 'var(--text-secondary)' }}>{fmt(extracted?.subtotal)}</span></div>
                      <div>Total Tax: <span style={{ color: 'var(--text-secondary)' }}>{fmt((extracted?.cgst_total || 0) + (extracted?.sgst_total || 0) + (extracted?.igst_total || 0))}</span></div>
                      <div>Grand Total: <span style={{ color: 'var(--success)', fontSize: '1.0rem', fontWeight: 700 }}>{fmt(extracted?.total_amount)}</span></div>
                    </div>
                  </div>
                </>
              )}
            </div>

            <div className="modal-footer">
              {step === 'upload' ? (
                <>
                  <button className="btn btn-secondary" onClick={() => setShowModal(false)}>Cancel</button>
                  <button
                    className="btn btn-primary"
                    disabled={!file || uploading}
                    onClick={handleUpload}
                  >
                    {uploading
                      ? <><span className="spinner" style={{ width: 14, height: 14, borderWidth: 2 }} /> Extracting…</>
                      : <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}><ImportIcon size={14} /> Upload & Extract</span>}
                  </button>
                </>
              ) : (
                <>
                  <button className="btn btn-secondary" onClick={() => setStep('upload')}><ChevronLeftIcon size={14} style={{ marginRight: 6, display: 'inline-block', verticalAlign: 'middle' }} /> Back</button>
                  <button className="btn btn-primary" disabled={confirming} onClick={handleConfirm}>
                    {confirming
                      ? <><span className="spinner" style={{ width: 14, height: 14, borderWidth: 2 }} /> Confirming…</>
                      : <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}><CheckIcon size={14} /> Confirm Bill</span>}
                  </button>
                </>
              )}
            </div>
          </div>
        </div>
      )}

      {/* 🔄 Purchase Returns (Debit Note) Modal */}
      {showReturnModal && (
        <div className="modal-overlay" onClick={e => e.target === e.currentTarget && setShowReturnModal(false)}>
          <div className="modal" style={{ maxWidth: returnStep === 'enter_items' ? '850px' : '480px', width: '95%' }}>
            <div className="modal-header">
              <span className="modal-title"><SyncIcon size={16} style={{ marginRight: 6, display: 'inline-block', verticalAlign: 'middle' }} /> Record Purchase Return (Debit Note)</span>
              <button className="btn btn-ghost btn-icon" onClick={() => setShowReturnModal(false)} aria-label="Close"><CloseIcon size={16} /></button>
            </div>

            <div className="modal-body">
              {returnStep === 'select_bill' ? (
                <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
                  <div className="form-group">
                    <label className="form-label" style={{ fontWeight: 600 }}>1. Select Supplier</label>
                    <CustomSelect
                      className="form-input"
                      value={returnSupplier}
                      onChange={e => {
                        setReturnSupplier(e.target.value)
                        setReturnBillId('')
                      }}
                    >
                      <option value="">-- Choose Supplier --</option>
                      {Array.from(new Set(bills.filter(b => b.status === 'confirmed').map(b => b.supplier_name))).map(sup => (
                        <option key={sup} value={sup}>{sup}</option>
                      ))}
                    </CustomSelect>
                  </div>

                  {returnSupplier && (
                    <div className="form-group">
                      <label className="form-label" style={{ fontWeight: 600 }}>2. Select Confirmed Bill</label>
                      <CustomSelect
                        className="form-input"
                        value={returnBillId}
                        onChange={e => setReturnBillId(e.target.value)}
                      >
                        <option value="">-- Choose Purchase Invoice --</option>
                        {bills
                          .filter(b => b.status === 'confirmed' && b.supplier_name === returnSupplier)
                          .map(b => (
                            <option key={b.id} value={b.id}>
                              {b.invoice_number || b.bill_number || `#${b.id}`} ({new Date(b.date || b.invoice_date).toLocaleDateString('en-IN')}) - Total: {fmt(b.total_amount)}
                            </option>
                          ))}
                      </CustomSelect>
                    </div>
                  )}
                </div>
              ) : (
                <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.85rem', borderBottom: '1px solid var(--border)', paddingBottom: 10 }}>
                    <div><strong>Supplier:</strong> {returnSupplier}</div>
                    <div><strong>Original Bill:</strong> {bills.find(b => String(b.id) === String(returnBillId))?.invoice_number || bills.find(b => String(b.id) === String(returnBillId))?.bill_number || `#${returnBillId}`}</div>
                  </div>

                  <div className="form-group">
                    <label className="form-label" style={{ fontWeight: 600 }}>Debit Note Number (Optional)</label>
                    <input
                      type="text"
                      className="form-input"
                      value={debitNoteNoInput}
                      onChange={e => setDebitNoteNoInput(e.target.value)}
                      placeholder="e.g. DN-0001 (Leave blank to auto-generate)"
                    />
                  </div>

                  <div className="data-table-wrap" style={{ maxHeight: '250px', overflowY: 'auto' }}>
                    <table className="data-table" style={{ fontSize: '0.82rem' }}>
                      <thead>
                        <tr>
                          <th>Item Name</th>
                          <th style={{ width: 80, textAlign: 'center' }}>Original Qty</th>
                          <th style={{ width: 100, textAlign: 'center' }}>Return Qty</th>
                          <th>Return Reason</th>
                          <th style={{ width: 90, textAlign: 'right' }}>Price</th>
                        </tr>
                      </thead>
                      <tbody>
                        {returnLines.map((line, idx) => (
                          <tr key={idx}>
                            <td className="td-primary">{line.product_name}</td>
                            <td style={{ textAlign: 'center' }}>{line.max_quantity}</td>
                            <td style={{ textAlign: 'center' }}>
                              <input
                                type="number"
                                className="form-input"
                                style={{ padding: '4px 6px', fontSize: '0.8rem', width: '80px', textAlign: 'center' }}
                                min="0"
                                max={line.max_quantity}
                                step="any"
                                value={line.quantity || ''}
                                onChange={e => {
                                  const val = parseFloat(e.target.value) || 0
                                  setReturnLines(prev => {
                                    const updated = [...prev]
                                    updated[idx].quantity = val
                                    return updated
                                  })
                                }}
                                placeholder="0"
                              />
                            </td>
                            <td>
                              <CustomSelect
                                className="form-input"
                                style={{ padding: '4px 6px', fontSize: '0.8rem' }}
                                value={line.reason}
                                onChange={e => {
                                  const val = e.target.value
                                  setReturnLines(prev => {
                                    const updated = [...prev]
                                    updated[idx].reason = val
                                    return updated
                                  })
                                }}
                              >
                                <option value="Damaged">Damaged</option>
                                <option value="Defective">Defective</option>
                                <option value="Incorrect Item">Incorrect Item</option>
                                <option value="Shortage">Shortage</option>
                                <option value="Expired">Expired</option>
                              </CustomSelect>
                            </td>
                            <td style={{ textAlign: 'right', fontWeight: 600 }}>{fmt(line.unit_price)}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>

                  {/* Return Summary */}
                  {(() => {
                    let sub = 0, tax = 0
                    returnLines.forEach(l => {
                      const qty = parseFloat(l.quantity) || 0
                      const p = parseFloat(l.unit_price) || 0
                      const taxable = qty * p
                      sub += taxable
                      tax += taxable * (((parseFloat(l.cgst_rate) || 0) + (parseFloat(l.sgst_rate) || 0) + (parseFloat(l.igst_rate) || 0)) / 100)
                    })
                    const total = sub + tax
                    return (
                      <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 20, fontSize: '0.85rem', fontWeight: 600, borderTop: '1px solid var(--border)', paddingTop: 10 }}>
                        <div>Return Subtotal: <span style={{ color: 'var(--text-secondary)' }}>{fmt(sub)}</span></div>
                        <div>Return Tax: <span style={{ color: 'var(--text-secondary)' }}>{fmt(tax)}</span></div>
                        <div>Grand Total: <span style={{ color: 'var(--accent)', fontWeight: 700 }}>{fmt(total)}</span></div>
                      </div>
                    )
                  })()}

                  <div className="form-group">
                    <label className="form-label" style={{ fontWeight: 600 }}>Remarks / Reason for Return</label>
                    <textarea
                      className="form-input"
                      rows={2}
                      value={returnNote}
                      onChange={e => setReturnNote(e.target.value)}
                      placeholder="Add any internal remarks here..."
                    />
                  </div>
                </div>
              )}
            </div>

            <div className="modal-footer">
              {returnStep === 'select_bill' ? (
                <>
                  <button className="btn btn-secondary" onClick={() => setShowReturnModal(false)}>Cancel</button>
                  <button
                    className="btn btn-primary"
                    disabled={!returnBillId}
                    onClick={handleSelectBillNext}
                  >
                    Next Step <ChevronRightIcon size={14} style={{ marginLeft: 6, display: 'inline-block', verticalAlign: 'middle' }} />
                  </button>
                </>
              ) : (
                <>
                  <button className="btn btn-secondary" onClick={() => setReturnStep('select_bill')}><ChevronLeftIcon size={14} style={{ marginRight: 6, display: 'inline-block', verticalAlign: 'middle' }} /> Back</button>
                  <button className="btn btn-primary" disabled={confirming} onClick={handleSaveReturn}>
                    {confirming ? 'Recording Return…' : <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}><CheckIcon size={14} /> Confirm & Save Return</span>}
                  </button>
                </>
              )}
            </div>
          </div>
        </div>
      )}

      {/* 📄 View Details Modal */}
      {showDetailModal && selectedDetail && (
        <div className="modal-overlay" onClick={e => e.target === e.currentTarget && setShowDetailModal(false)}>
          <div className="modal" style={{ maxWidth: '750px', width: '95%' }}>
            <div className="modal-header">
              <span className="modal-title">
                {selectedDetail.invoice_type === 'debit_note' ? <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}><SyncIcon size={14} /> Debit Note Details</span> : <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}><BillsIcon size={14} /> Purchase Invoice Details</span>}
              </span>
              <button className="btn btn-ghost btn-icon" onClick={() => setShowDetailModal(false)} aria-label="Close"><CloseIcon size={16} /></button>
            </div>

            <div className="modal-body" style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
              {/* Document Header */}
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: 16, borderBottom: '1px solid var(--border)', paddingBottom: 16 }}>
                <div>
                  <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>Document Number</div>
                  <div style={{ fontWeight: 700, color: 'var(--text-primary)', fontFamily: 'monospace' }}>
                    {selectedDetail.invoice_number || selectedDetail.bill_number || `#${selectedDetail.id}`}
                  </div>
                </div>
                <div>
                  <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>Supplier</div>
                  <div style={{ fontWeight: 600, color: 'var(--text-primary)' }}>{selectedDetail.supplier_name || '—'}</div>
                </div>
                <div>
                  <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>Date</div>
                  <div style={{ color: 'var(--text-primary)' }}>
                    {selectedDetail.date || selectedDetail.invoice_date ? new Date(selectedDetail.date || selectedDetail.invoice_date).toLocaleDateString('en-IN') : '—'}
                  </div>
                </div>
                <div>
                  <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>Type & Status</div>
                  <div>
                    <span className={`badge ${selectedDetail.invoice_type === 'debit_note' ? 'badge-accent' : (selectedDetail.status === 'confirmed' ? 'badge-success' : 'badge-warning')}`}>
                      {selectedDetail.invoice_type === 'debit_note' ? 'Debit Note (Return)' : `Bill: ${selectedDetail.status || 'pending'}`}
                    </span>
                  </div>
                </div>
              </div>

              {/* Items Table */}
              <div>
                <h3 style={{ fontSize: '0.9rem', fontWeight: 700, color: 'var(--text-secondary)', marginBottom: 10 }}>Line Items</h3>
                <div className="data-table-wrap">
                  <table className="data-table" style={{ fontSize: '0.8rem' }}>
                    <thead>
                      <tr>
                        <th>Item Description</th>
                        <th>HSN/SAC</th>
                        <th style={{ textAlign: 'center' }}>Qty</th>
                        <th style={{ textAlign: 'right' }}>Price</th>
                        <th style={{ textAlign: 'center' }}>Tax Rates</th>
                        <th style={{ textAlign: 'right' }}>Line Total</th>
                      </tr>
                    </thead>
                    <tbody>
                      {(selectedDetail.lines || selectedDetail.items || []).map((li, idx) => {
                        const taxDesc = li.igst_rate > 0 
                          ? `IGST ${li.igst_rate}%` 
                          : `CGST ${li.cgst_rate}% + SGST ${li.sgst_rate}%`
                        return (
                          <tr key={idx}>
                            <td className="td-primary" style={{ fontWeight: 500 }}>
                              {li.product_name}
                              {li.batch && <span style={{ display: 'block', fontSize: '0.7rem', color: 'var(--text-muted)' }}>Batch: {li.batch} {li.expiry ? `(Exp: ${li.expiry})` : ''}</span>}
                            </td>
                            <td className="td-mono">{li.hsn_sac || '—'}</td>
                            <td style={{ textAlign: 'center' }}>{li.quantity} {li.purchase_unit || li.unit || 'Nos'}</td>
                            <td style={{ textAlign: 'right' }}>{fmt(li.unit_price)}</td>
                            <td style={{ textAlign: 'center', color: 'var(--text-muted)' }}>{taxDesc}</td>
                            <td style={{ textAlign: 'right', fontWeight: 600, color: 'var(--text-primary)' }}>{fmt(li.line_total)}</td>
                          </tr>
                        )
                      })}
                    </tbody>
                  </table>
                </div>
              </div>

              {/* Summary Breakdown */}
              <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: 8, borderTop: '1px solid var(--border)', paddingTop: 16 }}>
                <div style={{ display: 'flex', width: '280px', justifyContent: 'space-between', fontSize: '0.82rem' }}>
                  <span style={{ color: 'var(--text-secondary)' }}>Subtotal:</span>
                  <span style={{ fontWeight: 600, color: 'var(--text-primary)' }}>{fmt(selectedDetail.subtotal)}</span>
                </div>
                {selectedDetail.cgst_total > 0 && (
                  <>
                    <div style={{ display: 'flex', width: '280px', justifyContent: 'space-between', fontSize: '0.82rem' }}>
                      <span style={{ color: 'var(--text-secondary)' }}>CGST Total:</span>
                      <span style={{ fontWeight: 600, color: 'var(--text-primary)' }}>{fmt(selectedDetail.cgst_total)}</span>
                    </div>
                    <div style={{ display: 'flex', width: '280px', justifyContent: 'space-between', fontSize: '0.82rem' }}>
                      <span style={{ color: 'var(--text-secondary)' }}>SGST Total:</span>
                      <span style={{ fontWeight: 600, color: 'var(--text-primary)' }}>{fmt(selectedDetail.sgst_total)}</span>
                    </div>
                  </>
                )}
                {selectedDetail.igst_total > 0 && (
                  <div style={{ display: 'flex', width: '280px', justifyContent: 'space-between', fontSize: '0.82rem' }}>
                    <span style={{ color: 'var(--text-secondary)' }}>IGST Total:</span>
                    <span style={{ fontWeight: 600, color: 'var(--text-primary)' }}>{fmt(selectedDetail.igst_total)}</span>
                  </div>
                )}
                <div style={{ display: 'flex', width: '280px', justifyContent: 'space-between', fontSize: '1.0rem', fontWeight: 700, borderTop: '1px solid var(--border)', paddingTop: 8, marginTop: 4 }}>
                  <span style={{ color: 'var(--text-primary)' }}>Grand Total:</span>
                  <span style={{ color: 'var(--success)' }}>{fmt(selectedDetail.total_amount)}</span>
                </div>
              </div>

              {/* Notes */}
              {selectedDetail.notes && (
                <div style={{ background: 'var(--bg-3)', padding: 12, borderRadius: 'var(--radius-sm)', fontSize: '0.8rem', color: 'var(--text-secondary)', borderLeft: '3px solid var(--border)' }}>
                  <strong>Note:</strong> {selectedDetail.notes}
                </div>
              )}
            </div>

            <div className="modal-footer">
              <button className="btn btn-primary" onClick={() => setShowDetailModal(false)}>Close</button>
            </div>
          </div>
        </div>
      )}
    </AppLayout>
  )
}
