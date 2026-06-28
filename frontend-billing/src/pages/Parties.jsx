import React, { useEffect, useState, useCallback, useRef } from 'react'
import AppLayout from '../layouts/AppLayout'
import { useAuth } from '../contexts/AuthContext'
import { BillsIcon, CheckIcon, CloseIcon, ContactsIcon, HandshakeIcon, InventoryIcon, MessageIcon, PlusIcon, PrinterIcon, SearchIcon, SyncIcon, UserIcon, WarehouseIcon } from '../components/Icons'
import { logger } from '../utils/logger'
import { buildUpiUri, buildWhatsAppShareUrl, normalizePhoneIN } from '../utils/share'
import { applyDelta, hasDelta } from '../sync/applyDelta'
import CustomSelect from '../components/common/CustomSelect'

const fmt = (n) =>
  n != null ? `₹${Number(n).toLocaleString('en-IN', { maximumFractionDigits: 2 })}` : '—'

const defaultForm = {
  party_type: 'customer',
  name: '', phone: '', email: '', gstin: '', address: '',
  credit_limit: '', payment_terms: 'net30',
}

export default function Parties() {
  const { authFetch, user, settings } = useAuth()

  const settingsRef = useRef(settings)
  useEffect(() => {
    settingsRef.current = settings
  }, [settings])

  const [customers, setCustomers]   = useState([])
  const [vendors, setVendors]       = useState([])
  const [invoices, setInvoices]     = useState([])
  const [purchases, setPurchases]   = useState([])
  const [loading, setLoading]       = useState(true)
  const [activeTab, setActiveTab]   = useState('Customers')
  const [isFullScreen, setIsFullScreen] = useState(false)
  const [search, setSearch]         = useState('')
  const [showModal, setShowModal]   = useState(false)
  const [form, setForm]             = useState(defaultForm)
  const [submitting, setSubmitting] = useState(false)
  const [alert, setAlert]           = useState(null)

  const [selectedParty, setSelectedParty] = useState(null) // { type: 'customer'|'vendor', name: '', id: '' }
  const [partyHistory, setPartyHistory]   = useState([])

  // Sales Returns / Credit Notes States
  const [showReturnModal, setShowReturnModal] = useState(false)
  const [returningInvoice, setReturningInvoice] = useState(null)
  const [returnLines, setReturnLines] = useState([])
  const [returnNote, setReturnNote] = useState('')
  const [savingReturn, setSavingReturn] = useState(false)

  const load = useCallback(() => {
    setLoading(true)
    Promise.all([
      authFetch('/billing/customers').then(r => r.ok ? r.json() : []).catch(() => []),
      authFetch('/billing/vendors').then(r => r.ok ? r.json() : []).catch(() => []),
      authFetch('/billing/invoices').then(r => r.ok ? r.json() : []).catch(() => []),
      authFetch('/purchases').then(r => r.ok ? r.json() : []).catch(() => []),
    ]).then(([c, v, invs, purchs]) => {
      const custItems = Array.isArray(c) ? c : (c && Array.isArray(c.items) ? c.items : [])
      const vendItems = Array.isArray(v) ? v : (v && Array.isArray(v.items) ? v.items : [])
      const invItems = Array.isArray(invs) ? invs : (invs && Array.isArray(invs.items) ? invs.items : [])
      const purchItems = Array.isArray(purchs) ? purchs : (purchs && Array.isArray(purchs.items) ? purchs.items : [])
      setCustomers(custItems)
      setVendors(vendItems)
      setInvoices(invItems)
      setPurchases(purchItems)
    }).finally(() => setLoading(false))
  }, [authFetch])

  useEffect(() => {
    load()
    const handleSync = (e) => {
      const currentSettings = settingsRef.current
      const isPartiesSyncEnabled = currentSettings?.general?.realtime_sync_parties !== false
      if (!isPartiesSyncEnabled) return
      logger.debug('[PARTIES] Real-time sync event received:', e.detail)

      // Phase 1 (delta push): in CLOUD mode every client reads the same cloud
      // DB, so we can splice the changed party row straight into the list and
      // skip the full refetch. In hybrid/local the UI reads the LOCAL DB (which
      // the SSE delta hasn't written yet), so we keep the refetch-after-pull path.
      const hostingMode = currentSettings?.general?.hosting_mode || 'local'
      if (hostingMode === 'cloud' && e.detail.entity === 'party' && hasDelta(e.detail)) {
        if (e.detail.kind === 'vendor') {
          setVendors(prev => applyDelta(prev, e.detail, { kind: 'vendor' }))
        } else {
          setCustomers(prev => applyDelta(prev, e.detail, { kind: 'customer' }))
        }
        return
      }

      if (['party', 'invoice', 'purchase', 'payment'].includes(e.detail.entity)) {
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

  const [balanceFilter, setBalanceFilter] = useState('')
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

  const getList = () => {
    let items = []
    if (activeTab === 'Customers') items = [...customers]
    else if (activeTab === 'Vendors') items = [...vendors]
    else items = invoices.filter(i => !i.customer_id)

    // Apply Search
    const q = search.toLowerCase()
    items = items.filter(p => {
      if (activeTab === 'Other Invoices') {
        return !q || p.invoice_number?.toLowerCase().includes(q) || p.notes?.toLowerCase().includes(q)
      }
      
      // Balance filter (Outstanding Dues / Nil)
      const outstanding = parseFloat(p.outstanding_balance ?? 0)
      if (balanceFilter === 'due' && outstanding <= 0) return false
      if (balanceFilter === 'nil' && outstanding > 0) return false

      return !q || p.name?.toLowerCase().includes(q) || p.phone?.includes(q) || p.gstin?.toLowerCase().includes(q)
    })

    // Apply Sorting
    if (sortConfig.key && sortConfig.direction) {
      items.sort((a, b) => {
        let aVal = a[sortConfig.key]
        let bVal = b[sortConfig.key]

        if (sortConfig.key === 'outstanding_balance') {
          aVal = parseFloat(a.outstanding_balance ?? 0)
          bVal = parseFloat(b.outstanding_balance ?? 0)
        } else if (sortConfig.key === 'last_date') {
          aVal = activeTab === 'Customers' ? (a.last_invoice_date || '') : (a.last_purchase_date || '')
          bVal = activeTab === 'Customers' ? (b.last_invoice_date || '') : (b.last_purchase_date || '')
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

  const filtered = getList()

  const setField = (k, v) => setForm(f => ({ ...f, [k]: v }))

  const handleSubmit = async (e) => {
    e.preventDefault()
    setSubmitting(true)
    const isCustomer = form.party_type === 'customer'
    const endpoint = isCustomer ? '/billing/customers' : '/billing/vendors'

    // Build a schema-clean payload — strip frontend-only fields
    const payload = isCustomer
      ? {
          name: form.name,
          phone: form.phone || null,
          email: form.email || null,
          gstin: form.gstin || null,
          address: form.address || null,
          state_code: form.state_code || null,
          pan: form.pan || null,
          credit_limit: form.credit_limit ? parseFloat(form.credit_limit) : 0,
          credit_days: 30,
          price_tier: 'standard',
        }
      : {
          name: form.name,
          phone: form.phone || null,
          email: form.email || null,
          gstin: form.gstin || null,
          address: form.address || null,
          state_code: form.state_code || null,
          pan: form.pan || null,
          payment_terms_days: 30,
        }

    try {
      const res = await authFetch(endpoint, {
        method: 'POST',
        body: JSON.stringify(payload),
      })
      if (res.ok) {
        setAlert({ type: 'success', msg: `${isCustomer ? 'Customer' : 'Vendor'} added!` })
        setShowModal(false)
        setForm(defaultForm)
        load()
      } else {
        const err = await res.json().catch(() => ({}))
        // Pydantic 422 returns detail as array — flatten to readable string
        const detail = Array.isArray(err.detail)
          ? err.detail.map(d => `${d.loc?.slice(-1)[0] ?? 'field'}: ${d.msg}`).join('; ')
          : (err.detail || 'Failed to add party.')
        setAlert({ type: 'danger', msg: detail })
      }
    } catch {
      setAlert({ type: 'danger', msg: 'Network error.' })
    } finally {
      setSubmitting(false)
    }
  }

  const handlePrintInvoice = async (invoiceNo) => {
    if (!invoiceNo) return
    try {
      const res = await authFetch(`/sales/${invoiceNo}/pdf`)
      if (res.ok) {
        const blob = await res.blob()
        const url = window.URL.createObjectURL(blob)
        const iframe = document.createElement('iframe')
        iframe.style.display = 'none'
        iframe.src = url
        document.body.appendChild(iframe)
        iframe.onload = () => {
          iframe.contentWindow.print()
        }
      } else {
        setAlert({ type: 'danger', msg: 'Failed to load PDF for printing.' })
      }
    } catch (err) {
      logger.error('[PARTIES] print invoice failed', err)
      setAlert({ type: 'danger', msg: 'Error printing invoice.' })
    }
  }

  const handleViewInvoices = (customer) => {
    const custInvs = invoices.filter(i => i.customer_id === customer.id)
    setSelectedParty({ type: 'customer', name: customer.name, id: customer.id })
    setPartyHistory(custInvs)
  }

  const handleViewPurchases = (vendor) => {
    const vendPurchs = purchases.filter(p => p.supplier_id === vendor.id)
    setSelectedParty({ type: 'vendor', name: vendor.name, id: vendor.id })
    setPartyHistory(vendPurchs)
  }

  const handleWhatsAppReminder = (party) => {
    const balance = parseFloat(party.outstanding_balance || 0)
    if (balance <= 0) return

    const upiVpa = localStorage.getItem('pos_upi_vpa') || 'bizassist@upi'
    const businessName = (user?.business_name || 'BizAssist Merchant').toUpperCase()

    const upiLink = buildUpiUri({ vpa: upiVpa, payeeName: businessName, amount: balance })
    const message = `Hi ${party.name}, a friendly reminder that you have an outstanding balance of ₹${balance.toLocaleString('en-IN')} with ${businessName}. Please clear it via UPI to: ${upiVpa}. Click to pay directly: ${upiLink}. Thank you!`

    window.open(buildWhatsAppShareUrl(party.phone, message), '_blank')
  }

  const handleWhatsAppShareInvoice = (invoice, customer = null) => {
    const invoiceNo = invoice.invoice_number || invoice.invoice_no
    const total = parseFloat(invoice.total_amount || 0)
    const paid = parseFloat(invoice.paid_amount || 0)
    const balance = Math.max(total - paid, 0)
    
    let phone = ''
    if (customer && customer.phone) {
      phone = customer.phone
    } else if (invoice.customer_phone) {
      phone = invoice.customer_phone
    } else {
      const input = window.prompt("Enter Customer's WhatsApp Number (10 digits):")
      if (!input) return
      phone = input
    }
    
    const upiVpa = localStorage.getItem('pos_upi_vpa') || 'bizassist@upi'
    const businessName = (user?.business_name || 'BizAssist Merchant').toUpperCase()
    
    let message = `Hi ${customer?.name || 'Customer'},\n\nHere is your Invoice ${invoiceNo} from ${businessName}:\nDate: ${invoice.date || invoice.invoice_date}\nTotal Amount: ₹${total.toLocaleString('en-IN')}\n`
    if (balance > 0) {
      const upiLink = buildUpiUri({ vpa: upiVpa, payeeName: businessName, amount: balance, note: `INV-${invoiceNo}` })
      message += `Balance Due: ₹${balance.toLocaleString('en-IN')}.\nYou can pay online using this UPI link: ${upiLink}\n`
    }
    message += `\nThank you for your business!`
    
    window.open(buildWhatsAppShareUrl(phone, message), '_blank')
  }

  const handleOpenReturn = async (invoice) => {
    const invoiceNo = invoice.invoice_number || invoice.invoice_no
    setLoading(true)
    try {
      const res = await authFetch(`/sales/${invoiceNo}`)
      if (res.ok) {
        const detail = await res.json()
        setReturningInvoice(detail)
        // Map lines
        const lines = detail.lines.map(li => ({
          product_id: li.product_id,
          product_name: li.product_name,
          quantity: 0,
          max_quantity: li.quantity,
          unit_price: li.unit_price,
          cgst_rate: li.cgst_rate || 0,
          sgst_rate: li.sgst_rate || 0,
          igst_rate: li.igst_rate || 0,
          cess_rate: li.cess_rate || 0,
          unit: li.unit || 'Nos',
          hsn_sac: li.hsn_sac || ''
        }))
        setReturnLines(lines)
        setReturnNote('')
        setShowReturnModal(true)
      } else {
        const err = await res.json().catch(() => ({}))
        setAlert({ type: 'danger', msg: err.detail || 'Failed to fetch invoice details.' })
      }
    } catch (e) {
      logger.error('[PARTIES] failed to open return', e)
      setAlert({ type: 'danger', msg: 'Network error fetching invoice details.' })
    } finally {
      setLoading(false)
    }
  }

  const handleSaveReturn = async () => {
    const activeLines = returnLines.filter(l => l.quantity > 0)
    if (activeLines.length === 0) {
      window.dispatchEvent(new CustomEvent('show_toast', {
        detail: { type: 'error', msg: 'Please enter a return quantity greater than zero for at least one item.' }
      }))
      return
    }
    
    const invalidLine = activeLines.find(l => l.quantity > l.max_quantity)
    if (invalidLine) {
      window.dispatchEvent(new CustomEvent('show_toast', {
        detail: { type: 'error', msg: `Return quantity for ${invalidLine.product_name} cannot exceed original quantity (${invalidLine.max_quantity}).` }
      }))
      return
    }

    setSavingReturn(true)
    try {
      const res = await authFetch('/credit-notes', {
        method: 'POST',
        body: JSON.stringify({
          invoice_id: returningInvoice.id,
          lines: activeLines.map(l => ({
            product_id: l.product_id,
            product_name: l.product_name,
            quantity: parseFloat(l.quantity),
            unit_price: parseFloat(l.unit_price),
            cgst_rate: parseFloat(l.cgst_rate),
            sgst_rate: parseFloat(l.sgst_rate),
            igst_rate: parseFloat(l.igst_rate),
            hsn_sac: l.hsn_sac,
            unit: l.unit
          })),
          note: returnNote
        })
      })
      
      if (res.ok) {
        setAlert({ type: 'success', msg: 'Sales return (Credit Note) recorded successfully! Stock and customer balance updated.' })
        setShowReturnModal(false)
        setReturningInvoice(null)
        setReturnLines([])
        setReturnNote('')
        load()
      } else {
        const err = await res.json().catch(() => ({}))
        setAlert({ type: 'danger', msg: err.detail || 'Failed to record sales return.' })
      }
    } catch (e) {
      logger.error('[PARTIES] failed to save return', e)
      setAlert({ type: 'danger', msg: 'Network error saving return.' })
    } finally {
      setSavingReturn(false)
    }
  }

  return (
    <AppLayout title="Parties & Invoices">
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
            <h1 className="page-title">Parties & Invoices</h1>
            <p className="page-subtitle">Manage CRM relationships and view customer invoices</p>
          </div>
          <div className="page-actions">
            <button className="btn btn-primary" onClick={() => { setForm(defaultForm); setShowModal(true) }}>
              <PlusIcon size={14} /> Add Party
            </button>
          </div>
        </div>

        {/* Tabs + Search & Filters */}
        <div className="flex items-center justify-between page-subbar" style={{ flexWrap: 'wrap', gap: 12 }}>
          <div className="tabs" style={{ margin: 0 }}>
            <button className={`tab${activeTab === 'Customers' ? ' active' : ''}`} onClick={() => setActiveTab('Customers')}>
              Customers <span style={{ marginLeft: 4, fontSize: '0.68rem', opacity: 0.7 }}>({customers.length})</span>
            </button>
            <button className={`tab${activeTab === 'Vendors' ? ' active' : ''}`} onClick={() => setActiveTab('Vendors')}>
              Vendors <span style={{ marginLeft: 4, fontSize: '0.68rem', opacity: 0.7 }}>({vendors.length})</span>
            </button>
            <button className={`tab${activeTab === 'Other Invoices' ? ' active' : ''}`} onClick={() => setActiveTab('Other Invoices')}>
              Casual / Other Invoices <span style={{ marginLeft: 4, fontSize: '0.68rem', opacity: 0.7 }}>({invoices.filter(i => !i.customer_id).length})</span>
            </button>
          </div>
          <div style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
            <div className="search-bar" style={{ width: 180 }}>
              <span style={{ color: 'var(--text-muted)', display: 'flex', alignItems: 'center' }}><SearchIcon size={16} /></span>
              <input value={search} onChange={e => setSearch(e.target.value)} placeholder={`Search ${activeTab.toLowerCase()}…`} />
            </div>
            {activeTab !== 'Other Invoices' && (
              <CustomSelect
                value={balanceFilter}
                onChange={e => setBalanceFilter(e.target.value)}
                style={{
                  background: 'var(--bg-2)',
                  border: '1px solid var(--border)',
                  borderRadius: 'var(--radius-md)',
                  color: 'var(--text-primary)',
                  padding: '6px 12px',
                  fontSize: '0.82rem',
                  cursor: 'pointer'
                }}
              >
                <option value="">All Balances</option>
                <option value="due">Outstanding Due</option>
                <option value="nil">Nil / Zero Balance</option>
              </CustomSelect>
            )}
          </div>
        </div>

        {/* Table */}
        {(() => {
          const tableContent = (
            <table className="data-table">
              <thead>
                {activeTab === 'Customers' && (
                  <tr>
                    <th className="sortable" onClick={() => handleSort('name')}>
                      Name
                      <span className={`sort-indicator ${sortConfig.key === 'name' && sortConfig.direction ? 'active' : ''}`}>
                        {sortConfig.key === 'name' && sortConfig.direction ? (sortConfig.direction === 'asc' ? '▲' : '▼') : '⇅'}
                      </span>
                    </th>
                    <th>Phone</th>
                    <th>Email</th>
                    <th>GSTIN</th>
                    <th className="sortable" onClick={() => handleSort('outstanding_balance')}>
                      Outstanding
                      <span className={`sort-indicator ${sortConfig.key === 'outstanding_balance' && sortConfig.direction ? 'active' : ''}`}>
                        {sortConfig.key === 'outstanding_balance' && sortConfig.direction ? (sortConfig.direction === 'asc' ? '▲' : '▼') : '⇅'}
                      </span>
                    </th>
                    <th className="sortable" onClick={() => handleSort('last_date')}>
                      Last Invoice
                      <span className={`sort-indicator ${sortConfig.key === 'last_date' && sortConfig.direction ? 'active' : ''}`}>
                        {sortConfig.key === 'last_date' && sortConfig.direction ? (sortConfig.direction === 'asc' ? '▲' : '▼') : '⇅'}
                      </span>
                    </th>
                    <th>Actions</th>
                  </tr>
                )}
                {activeTab === 'Vendors' && (
                  <tr>
                    <th className="sortable" onClick={() => handleSort('name')}>
                      Name
                      <span className={`sort-indicator ${sortConfig.key === 'name' && sortConfig.direction ? 'active' : ''}`}>
                        {sortConfig.key === 'name' && sortConfig.direction ? (sortConfig.direction === 'asc' ? '▲' : '▼') : '⇅'}
                      </span>
                    </th>
                    <th>Phone</th>
                    <th>GSTIN</th>
                    <th className="sortable" onClick={() => handleSort('outstanding_balance')}>
                      Outstanding
                      <span className={`sort-indicator ${sortConfig.key === 'outstanding_balance' && sortConfig.direction ? 'active' : ''}`}>
                        {sortConfig.key === 'outstanding_balance' && sortConfig.direction ? (sortConfig.direction === 'asc' ? '▲' : '▼') : '⇅'}
                      </span>
                    </th>
                    <th className="sortable" onClick={() => handleSort('last_date')}>
                      Last Purchase
                      <span className={`sort-indicator ${sortConfig.key === 'last_date' && sortConfig.direction ? 'active' : ''}`}>
                        {sortConfig.key === 'last_date' && sortConfig.direction ? (sortConfig.direction === 'asc' ? '▲' : '▼') : '⇅'}
                      </span>
                    </th>
                    <th>Actions</th>
                  </tr>
                )}
                {activeTab === 'Other Invoices' && (
                  <tr>
                    <th className="sortable" onClick={() => handleSort('invoice_number')}>
                      Invoice #
                      <span className={`sort-indicator ${sortConfig.key === 'invoice_number' && sortConfig.direction ? 'active' : ''}`}>
                        {sortConfig.key === 'invoice_number' && sortConfig.direction ? (sortConfig.direction === 'asc' ? '▲' : '▼') : '⇅'}
                      </span>
                    </th>
                    <th className="sortable" onClick={() => handleSort('date')}>
                      Date
                      <span className={`sort-indicator ${sortConfig.key === 'date' && sortConfig.direction ? 'active' : ''}`}>
                        {sortConfig.key === 'date' && sortConfig.direction ? (sortConfig.direction === 'asc' ? '▲' : '▼') : '⇅'}
                      </span>
                    </th>
                    <th>Customer</th>
                    <th>Items</th>
                    <th className="sortable" onClick={() => handleSort('total_amount')}>
                      Amount
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
                  </tr>
                )}
              </thead>
              <tbody>
                {filtered.length === 0 ? (
                  <tr><td colSpan={7}>
                    <div className="empty-state">
                      <div className="empty-icon"><ContactsIcon size={24} /></div>
                      <h3>No items found</h3>
                      <p>{search ? 'Try a different search.' : 'No transactions or details available.'}</p>
                    </div>
                  </td></tr>
                ) : filtered.map(p => {
                  if (activeTab === 'Other Invoices') {
                    return (
                      <tr key={p.id}>
                        <td className="td-mono td-primary">
                          {p.invoice_number || `#${p.id}`}
                          {p.invoice_type === 'credit_note' && (
                            <span style={{ fontSize: '0.65rem', display: 'block', color: 'var(--accent)' }}>
                              <SyncIcon size={14} style={{ marginRight: 6, display: 'inline-block', verticalAlign: 'middle' }} /> RETURN (CN)
                            </span>
                          )}
                        </td>
                        <td>{p.date ? new Date(p.date).toLocaleDateString('en-IN') : '—'}</td>
                        <td style={{ color: 'var(--text-muted)' }}>Casual / Walk-in</td>
                        <td style={{ color: 'var(--text-muted)' }}>{p.item_count ?? (p.items?.length ?? '—')}</td>
                        <td style={{ color: 'var(--text-primary)', fontWeight: 600 }}>{fmt(p.total_amount)}</td>
                        <td><span className={`badge ${p.status === 'paid' ? 'badge-success' : 'badge-warning'}`}>{p.status || 'unpaid'}</span></td>
                        <td>
                          <div style={{ display: 'flex', gap: 6 }}>
                            <button className="btn btn-secondary btn-sm" onClick={() => handlePrintInvoice(p.invoice_number || p.invoice_no)}><PrinterIcon size={14} style={{ marginRight: 6, display: 'inline-block', verticalAlign: 'middle' }} /> Print</button>
                            <button className="btn btn-secondary btn-sm" onClick={() => handleWhatsAppShareInvoice(p)} title="Share invoice on WhatsApp"><MessageIcon size={14} style={{ marginRight: 6, display: 'inline-block', verticalAlign: 'middle' }} /> Share</button>
                            {p.invoice_type !== 'credit_note' && (
                              <button className="btn btn-secondary btn-sm" onClick={() => handleOpenReturn(p)} title="Record Sales Return / Credit Note"><SyncIcon size={14} style={{ marginRight: 6, display: 'inline-block', verticalAlign: 'middle' }} /> Return</button>
                            )}
                          </div>
                        </td>
                      </tr>
                    )
                  }
                  const outstanding = parseFloat(p.outstanding_balance ?? 0)
                  return (
                    <tr key={p.id}>
                      <td>
                        <div style={{ fontWeight: 600, color: 'var(--text-primary)' }}>{p.name}</div>
                        {p.address && <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>{p.address}</div>}
                      </td>
                      <td>{p.phone || '—'}</td>
                      {activeTab === 'Customers' && <td style={{ color: 'var(--text-muted)', fontSize: '0.82rem' }}>{p.email || '—'}</td>}
                      <td className="td-mono" style={{ fontSize: '0.78rem' }}>{p.gstin || '—'}</td>
                      <td>{outstanding > 0 ? <span className="badge badge-danger">{fmt(outstanding)}</span> : <span className="badge badge-success">Nil</span>}</td>
                      <td style={{ color: 'var(--text-muted)', fontSize: '0.82rem' }}>
                        {activeTab === 'Customers'
                          ? (p.last_invoice_date ? new Date(p.last_invoice_date).toLocaleDateString('en-IN') : '—')
                          : (p.last_purchase_date ? new Date(p.last_purchase_date).toLocaleDateString('en-IN') : '—')
                        }
                      </td>
                      <td style={{ display: 'flex', gap: 6 }}>
                        {activeTab === 'Customers' ? (
                          <>
                            <button className="btn btn-secondary btn-sm" onClick={() => handleViewInvoices(p)}><BillsIcon size={14} style={{ marginRight: 6, display: 'inline-block', verticalAlign: 'middle' }} /> View Invoices</button>
                            {outstanding > 0 && (
                              <button className="btn btn-sm" style={{ backgroundColor: '#166534', color: '#ffffff', border: 'none' }} onClick={() => handleWhatsAppReminder(p)} title="Send payment reminder on WhatsApp"><MessageIcon size={14} style={{ marginRight: 4, display: 'inline-block', verticalAlign: 'middle' }} /> Send Reminder</button>
                            )}
                          </>
                        ) : (
                          <button className="btn btn-secondary btn-sm" onClick={() => handleViewPurchases(p)}><InventoryIcon size={14} style={{ marginRight: 4, display: 'inline-block', verticalAlign: 'middle' }} /> View Purchases</button>
                        )}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          )
          if (loading) return <div className="page-loader"><span className="spinner" /> Loading…</div>
          if (isFullScreen) return (
            <div className="table-fullscreen-overlay" onClick={e => { if (e.target === e.currentTarget) setIsFullScreen(false) }}>
              <div className="table-fullscreen-panel">
                <div className="table-fullscreen-header">
                  <h3>Contacts & Dues — {activeTab}</h3>
                  <button type="button" className="table-fullscreen-btn" onClick={() => setIsFullScreen(false)}>✕ Close</button>
                </div>
                <div className="data-table-wrap">{tableContent}</div>
              </div>
            </div>
          )
          return (
            <>
              <div style={{ display: 'flex', justifyContent: 'flex-end', marginBottom: 8 }}>
                <button type="button" className="table-fullscreen-btn" onClick={() => setIsFullScreen(true)}>⛶ Fullscreen</button>
              </div>
              <div className="data-table-wrap">{tableContent}</div>
            </>
          )
        })()}

      </div>

      {/* Add Party Modal */}
      {showModal && (
        <div className="modal-overlay" onClick={e => e.target === e.currentTarget && setShowModal(false)}>
          <div className="modal modal-lg">
            <div className="modal-header">
              <span className="modal-title"><HandshakeIcon size={16} style={{ marginRight: 6, display: 'inline-block', verticalAlign: 'middle' }} /> Add Party</span>
              <button className="btn btn-ghost btn-icon" onClick={() => setShowModal(false)} aria-label="Close"><CloseIcon size={16} /></button>
            </div>
            <form onSubmit={handleSubmit}>
              <div className="modal-body">
                {/* Type toggle */}
                <div className="flex items-center gap-2 mb-4">
                  <span style={{ fontSize: '0.82rem', color: 'var(--text-secondary)' }}>Type:</span>
                  <div className="tabs">
                    <button type="button" className={`tab${form.party_type === 'customer' ? ' active' : ''}`} onClick={() => setField('party_type', 'customer')}>
                      <UserIcon size={14} style={{ marginRight: 6, display: 'inline-block', verticalAlign: 'middle' }} /> Customer
                    </button>
                    <button type="button" className={`tab${form.party_type === 'vendor' ? ' active' : ''}`} onClick={() => setField('party_type', 'vendor')}>
                      <WarehouseIcon size={14} style={{ marginRight: 6, display: 'inline-block', verticalAlign: 'middle' }} /> Vendor
                    </button>
                  </div>
                </div>
                <div className="grid grid-2 gap-3 mb-4">
                  <div className="form-group">
                    <label className="form-label">Name *</label>
                    <input className="form-input" placeholder="Full name or business name" value={form.name} onChange={e => setField('name', e.target.value)} required />
                  </div>
                  <div className="form-group">
                    <label className="form-label">Phone</label>
                    <input className="form-input" placeholder="+91 98765 43210" value={form.phone} onChange={e => setField('phone', e.target.value)} />
                  </div>
                  <div className="form-group">
                    <label className="form-label">Email</label>
                    <input type="email" className="form-input" placeholder="email@example.com" value={form.email} onChange={e => setField('email', e.target.value)} />
                  </div>
                  <div className="form-group">
                    <label className="form-label">GSTIN</label>
                    <input className="form-input" placeholder="22AAAAA0000A1Z5" value={form.gstin} onChange={e => setField('gstin', e.target.value)} />
                  </div>
                  <div className="form-group">
                    <label className="form-label">Credit Limit (₹)</label>
                    <input type="number" className="form-input" placeholder="e.g. 50000" min="0" step="any" value={form.credit_limit} onChange={e => setField('credit_limit', e.target.value)} />
                  </div>
                  <div className="form-group">
                    <label className="form-label">Payment Terms</label>
                    <CustomSelect className="form-select" value={form.payment_terms} onChange={e => setField('payment_terms', e.target.value)}>
                      <option value="immediate">Immediate</option>
                      <option value="net7">Net 7 days</option>
                      <option value="net15">Net 15 days</option>
                      <option value="net30">Net 30 days</option>
                      <option value="net45">Net 45 days</option>
                      <option value="net60">Net 60 days</option>
                    </CustomSelect>
                  </div>
                </div>
                <div className="form-group">
                  <label className="form-label">Address</label>
                  <textarea className="form-textarea" style={{ minHeight: 70 }} placeholder="Full address…" value={form.address} onChange={e => setField('address', e.target.value)} />
                </div>
              </div>
              <div className="modal-footer">
                <button type="button" className="btn btn-secondary" onClick={() => setShowModal(false)}>Cancel</button>
                <button type="submit" className="btn btn-primary" disabled={submitting}>
                  {submitting ? <><span className="spinner" style={{ width: 14, height: 14, borderWidth: 2 }} /> Saving…</> : <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}><CheckIcon size={14} /> Add Party</span>}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Selected Party Transaction Lookup Modal */}
      {selectedParty && (
        <div className="modal-overlay" onClick={e => e.target === e.currentTarget && setSelectedParty(null)}>
          <div className="modal modal-lg">
            <div className="modal-header">
              <span className="modal-title" style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
                {selectedParty.type === 'customer' ? <BillsIcon size={16} /> : <InventoryIcon size={16} />}
                <span>{selectedParty.type === 'customer' ? 'Invoices' : 'Purchases'} for {selectedParty.name}</span>
              </span>
              <button className="btn btn-ghost btn-icon" onClick={() => setSelectedParty(null)} aria-label="Close"><CloseIcon size={16} /></button>
            </div>
            <div className="modal-body">
              <div className="data-table-wrap" style={{ maxHeight: '60vh', overflowY: 'auto' }}>
                <table className="data-table">
                  <thead>
                    {selectedParty.type === 'customer' ? (
                      <tr>
                        <th>Invoice #</th>
                        <th>Date</th>
                        <th>Items</th>
                        <th>Total</th>
                        <th>Status</th>
                        <th>Actions</th>
                      </tr>
                    ) : (
                      <tr>
                        <th>Bill #</th>
                        <th>Date</th>
                        <th>Items</th>
                        <th>Total</th>
                        <th>Status</th>
                      </tr>
                    )}
                  </thead>
                  <tbody>
                    {partyHistory.length === 0 ? (
                      <tr>
                        <td colSpan={selectedParty.type === 'customer' ? 6 : 5} style={{ textAlign: 'center', color: 'var(--text-muted)', padding: '20px' }}>
                          No transactions found for this party.
                        </td>
                      </tr>
                    ) : partyHistory.map(item => (
                      <tr key={item.id}>
                        <td className="td-mono td-primary">
                          {selectedParty.type === 'customer' ? (item.invoice_number || `#${item.id}`) : (item.bill_number || `#${item.id}`)}
                          {item.invoice_type === 'credit_note' && (
                            <span style={{ fontSize: '0.65rem', display: 'block', color: 'var(--accent)' }}>
                              <SyncIcon size={14} style={{ marginRight: 6, display: 'inline-block', verticalAlign: 'middle' }} /> RETURN (CN)
                            </span>
                          )}
                        </td>
                        <td>
                          {item.date ? new Date(item.date).toLocaleDateString('en-IN') : '—'}
                        </td>
                        <td style={{ color: 'var(--text-muted)' }}>
                          {item.item_count ?? item.items?.length ?? '—'}
                        </td>
                        <td style={{ color: 'var(--text-primary)', fontWeight: 600 }}>
                          {fmt(item.total_amount)}
                        </td>
                        <td>
                          <span className={`badge ${item.status === 'paid' || item.status === 'confirmed' ? 'badge-success' : 'badge-warning'}`}>
                            {item.status || 'pending'}
                          </span>
                        </td>
                        {selectedParty.type === 'customer' && (
                          <td>
                            <div style={{ display: 'flex', gap: 6 }}>
                              <button
                                className="btn btn-secondary btn-sm"
                                onClick={() => handlePrintInvoice(item.invoice_number || item.invoice_no)}
                              >
                                <PrinterIcon size={14} style={{ marginRight: 6, display: 'inline-block', verticalAlign: 'middle' }} /> Print
                              </button>
                              <button
                                className="btn btn-secondary btn-sm"
                                onClick={() => handleWhatsAppShareInvoice(item, selectedParty)}
                                title="Share invoice on WhatsApp"
                              >
                                <MessageIcon size={14} style={{ marginRight: 6, display: 'inline-block', verticalAlign: 'middle' }} /> Share
                              </button>
                              {item.invoice_type !== 'credit_note' && (
                                <button
                                  className="btn btn-secondary btn-sm"
                                  onClick={() => handleOpenReturn(item)}
                                  title="Record Sales Return / Credit Note"
                                >
                                  <SyncIcon size={14} style={{ marginRight: 6, display: 'inline-block', verticalAlign: 'middle' }} /> Return
                                </button>
                              )}
                            </div>
                          </td>
                        )}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
            <div className="modal-footer">
              <button className="btn btn-secondary" onClick={() => setSelectedParty(null)}>Close</button>
            </div>
          </div>
        </div>
      )}
      {showReturnModal && returningInvoice && (
        <div className="modal-overlay" onClick={e => e.target === e.currentTarget && setShowReturnModal(false)}>
          <div className="modal modal-lg" style={{ maxWidth: '850px', width: '95%' }}>
            <div className="modal-header">
              <span className="modal-title"><SyncIcon size={16} style={{ marginRight: 6, display: 'inline-block', verticalAlign: 'middle' }} /> Record Sales Return (Credit Note)</span>
              <button className="btn btn-ghost btn-icon" onClick={() => { setShowReturnModal(false); setReturningInvoice(null); }} aria-label="Close"><CloseIcon size={16} /></button>
            </div>
            <div className="modal-body">
              <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.85rem', borderBottom: '1px solid var(--border)', paddingBottom: 10, marginBottom: 15 }}>
                <div><strong>Customer:</strong> {returningInvoice.customer || 'Walk-in / Casual'}</div>
                <div><strong>Original Invoice:</strong> {returningInvoice.invoice_no} ({returningInvoice.invoice_date})</div>
              </div>

              <div className="data-table-wrap" style={{ maxHeight: '300px', overflowY: 'auto', marginBottom: 15 }}>
                <table className="data-table" style={{ fontSize: '0.82rem' }}>
                  <thead>
                    <tr>
                      <th>Item Name</th>
                      <th style={{ width: 100, textAlign: 'center' }}>Original Qty</th>
                      <th style={{ width: 120, textAlign: 'center' }}>Return Qty</th>
                      <th style={{ width: 100, textAlign: 'right' }}>Unit Price</th>
                      <th style={{ width: 100, textAlign: 'right' }}>GST Rate</th>
                      <th style={{ width: 120, textAlign: 'right' }}>Refund Total</th>
                    </tr>
                  </thead>
                  <tbody>
                    {returnLines.map((line, idx) => {
                      const taxRate = (line.cgst_rate || 0) + (line.sgst_rate || 0) + (line.igst_rate || 0)
                      const returnQty = parseFloat(line.quantity) || 0
                      const price = parseFloat(line.unit_price) || 0
                      const refundLineTotal = returnQty * price * (1 + taxRate / 100)

                      return (
                        <tr key={idx}>
                          <td className="td-primary">{line.product_name}</td>
                          <td style={{ textAlign: 'center' }}>{line.max_quantity}</td>
                          <td style={{ textAlign: 'center' }}>
                            <input
                              type="number"
                              className="form-input"
                              style={{ padding: '4px 6px', fontSize: '0.8rem', width: '80px', textAlign: 'center', margin: '0 auto' }}
                              min="0"
                              max={line.max_quantity}
                              step="any"
                              value={line.quantity || ''}
                              onChange={e => {
                                const val = Math.min(Math.max(parseFloat(e.target.value) || 0, 0), line.max_quantity)
                                setReturnLines(prev => {
                                  const updated = [...prev]
                                  updated[idx].quantity = val
                                  return updated
                                })
                              }}
                              placeholder="0"
                            />
                          </td>
                          <td style={{ textAlign: 'right' }}>{fmt(line.unit_price)}</td>
                          <td style={{ textAlign: 'right' }}>{taxRate}%</td>
                          <td style={{ textAlign: 'right', fontWeight: 600 }}>{fmt(refundLineTotal)}</td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </div>

              {/* Summary */}
              {(() => {
                let sub = 0, tax = 0
                returnLines.forEach(l => {
                  const qty = parseFloat(l.quantity) || 0
                  const p = parseFloat(l.unit_price) || 0
                  const taxRate = (l.cgst_rate || 0) + (l.sgst_rate || 0) + (l.igst_rate || 0)
                  const taxable = qty * p
                  sub += taxable
                  tax += taxable * (taxRate / 100)
                })
                const total = sub + tax
                return (
                  <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 20, fontSize: '0.85rem', fontWeight: 600, borderTop: '1px solid var(--border)', paddingTop: 10, marginBottom: 15 }}>
                    <div>Return Subtotal: <span style={{ color: 'var(--text-secondary)' }}>{fmt(sub)}</span></div>
                    <div>Return Tax: <span style={{ color: 'var(--text-secondary)' }}>{fmt(tax)}</span></div>
                    <div>Grand Total: <span style={{ color: 'var(--accent)', fontWeight: 700 }}>{fmt(total)}</span></div>
                  </div>
                )
              })()}

              <div className="form-group">
                <label className="form-label" style={{ fontWeight: 600 }}>Remarks / Reason for Return</label>
                <textarea
                  className="form-textarea"
                  style={{ minHeight: 60 }}
                  value={returnNote}
                  onChange={e => setReturnNote(e.target.value)}
                  placeholder="Reason for return, damaged goods, client change, etc..."
                />
              </div>
            </div>
            <div className="modal-footer">
              <button className="btn btn-secondary" onClick={() => { setShowReturnModal(false); setReturningInvoice(null); }} disabled={savingReturn}>Cancel</button>
              <button
                className="btn btn-primary"
                disabled={savingReturn || returnLines.every(l => !(parseFloat(l.quantity) > 0))}
                onClick={handleSaveReturn}
              >
                {savingReturn ? <><span className="spinner" style={{ width: 14, height: 14, borderWidth: 2 }} /> Saving…</> : <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}><CheckIcon size={14} /> Record Return</span>}
              </button>
            </div>
          </div>
        </div>
      )}
    </AppLayout>
  )
}
