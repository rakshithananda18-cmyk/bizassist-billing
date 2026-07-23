// ============================================================================
// Page: Parties.jsx
// Description: Customer and Vendor Directory. Handles listing business contacts,
//              tracking outstanding balances, viewing ledger histories, and sharing
//              payment reminders/UPI payment links via WhatsApp.
// ============================================================================
import React, { useEffect, useState, useCallback, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import PageShell from '../components/common/PageShell'
import { useAuth } from '../contexts/AuthContext'
import { BillsIcon, CheckIcon, CloseIcon, ContactsIcon, HandshakeIcon, InventoryIcon, MessageIcon, PlusIcon, PrinterIcon, SearchIcon, SyncIcon, UserIcon, WarehouseIcon, ExpandIcon } from '../components/Icons'
import PartyFormModal from '../components/parties/PartyFormModal'
import SaleReturnModal from '../components/parties/SaleReturnModal'
import { logger } from '../utils/logger'
import { buildUpiUri, buildWhatsAppShareUrl, normalizePhoneIN } from '../utils/share'
import { applyDelta, hasDelta } from '../sync/applyDelta'
import FilterDropdown from '../components/common/FilterDropdown'
import SortDropdown from '../components/common/SortDropdown'
import WorkspaceTopBar, { WsDivider } from '../components/common/WorkspaceTopBar'
import { usePageLifecycle } from '../hooks/usePageLifecycle'
import ContextMenu from '../components/common/ContextMenu'
import UnsavedChangesModal from '../components/common/UnsavedChangesModal'
import { useDocLabels } from '../hooks/useDocLabels'
import { useConfirm } from '../contexts/ConfirmContext'
import { summariseFields, isDirty } from '../utils/diffFields'

const fmt = (n) =>
  n != null ? `₹${Number(n).toLocaleString('en-IN', { maximumFractionDigits: 2 })}` : '—'

const defaultForm = {
  party_type: 'customer',
  name: '', phone: '', email: '', gstin: '', address: '',
  credit_limit: '', payment_terms: 'net30',
}

// Fields shown in the add / discard confirmation for a party.
const PARTY_FIELDS = [
  { key: 'party_type', label: 'Type', map: { customer: 'Customer', vendor: 'Vendor' } },
  { key: 'name', label: 'Name' },
  { key: 'phone', label: 'Phone' },
  { key: 'email', label: 'Email' },
  { key: 'gstin', label: 'GSTIN' },
  { key: 'address', label: 'Address' },
  { key: 'credit_limit', label: 'Credit limit', money: true },
  { key: 'payment_terms', label: 'Payment terms' },
]

export default function Parties({ embedded = false, headerTabs = null }) {
  const { authFetch, user, settings } = useAuth()
  const navigate = useNavigate()
  const label = useDocLabels()
  const confirm = useConfirm()

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

  // selectedParty / partyHistory removed: "View Invoices" now navigates to the
  // Invoices tab (/parties/invoices?customer=name) instead of opening a modal.

  // Returns
  const [showReturnModal, setShowReturnModal] = useState(false)
  // settleParty removed — "Settle" now navigates to /parties/payments?customer=name.
  const isCashier = (user?.role || '').toLowerCase() === 'cashier'
  const [returningInvoice, setReturningInvoice] = useState(null)
  const [returnLines, setReturnLines] = useState([])
  const [returnNote, setReturnNote] = useState('')
  const [savingReturn, setSavingReturn] = useState(false)

  // Right-click context menu
  const [ctxMenu, setCtxMenu] = useState(null)

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

  // Page lifecycle: guard when form modal is open with typed data
  const { blocker, isRefreshing, dirtyMessage } = usePageLifecycle({
    isDirty:      () => showModal && form.name !== '',
    dirtyMessage: 'You have an unsaved contact form. Leave this page?',
    onResume:     load,
  })

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

      if (['party', 'invoice', 'purchase', 'payment'].includes(e.detail.entity) || e.detail?.type === 'sync.reconnect') {
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

  // Prompt before discarding a half-filled Add-Party form.
  const requestCloseModal = async () => {
    if (isDirty(defaultForm, form, PARTY_FIELDS)) {
      const ok = await confirm({ mode: 'discard', entity: form.name?.trim() || 'this party' })
      if (!ok) return
    }
    setShowModal(false)
  }

  const handleSubmit = async (e) => {
    e.preventDefault()
    const isCustomer = form.party_type === 'customer'

    // Double-check step — summarise the new party before it's created.
    const summary = summariseFields(form, PARTY_FIELDS)
    const entity = form.name?.trim() || (isCustomer ? 'this customer' : 'this vendor')
    if (!(await confirm({ mode: 'create', entity, summary }))) return

    setSubmitting(true)
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

  // Navigate to the Invoices tab, pre-filtered to this customer's invoices.
  // The Invoices tab (InvoicesPage) reads ?customer= from the URL and shows a
  // clearable chip, so the user can remove the filter to see all invoices.
  const handleViewInvoices = (customer) => {
    navigate(`/parties/invoices?customer=${encodeURIComponent(customer.name)}`)
  }

  const handleViewPurchases = (vendor) => {
    // Vendor purchases: still use local state (no dedicated Purchases tab yet).
    // TODO: add a Purchases tab to the workspace and navigate similarly.
    confirm({
      mode: 'alert',
      title: 'Coming soon',
      message: `Purchases view for ${vendor.name} — coming soon in the workspace.`,
    })
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
        setAlert({ type: 'success', msg: `${label('sale_return')} recorded successfully! Stock and customer balance updated.` })
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
    <PageShell embedded={embedded} title="Parties & Invoices">
      <div className={`slide-up${headerTabs ? ' ws-embed' : ''}`}>

        {alert && (
          <div className={`alert alert-${alert.type} mb-4`}>
            {alert.type === 'success' ? '✅' : '❌'} {alert.msg}
            <button onClick={() => setAlert(null)} style={{ marginLeft: 'auto', background: 'none', border: 'none', color: 'inherit', cursor: 'pointer' }} aria-label="Close"><CloseIcon size={16} /></button>
          </div>
        )}

        {/* Embedded (Khata): the SAME 48px workspace bar as Godown's tabs —
            workspace tabs · divider · view tabs · actions · window controls. */}
        {headerTabs && (
          <WorkspaceTopBar
            settingsTab="transactions"
            windowControls={false}
            actions={
              <button className="btn btn-primary btn-sm" style={{ display: 'inline-flex', alignItems: 'center', gap: 5 }} onClick={() => { setForm(defaultForm); setShowModal(true) }}>
                <PlusIcon size={13} /> Add Party
              </button>
            }
          >
            {headerTabs}
            <WsDivider />
            <button className={`ws-tab ${activeTab === 'Customers' ? 'active' : ''}`} onClick={() => setActiveTab('Customers')}>
              Customers <span style={{ fontSize: '0.68rem', opacity: 0.7 }}>({customers.length})</span>
            </button>
            <button className={`ws-tab ${activeTab === 'Vendors' ? 'active' : ''}`} onClick={() => setActiveTab('Vendors')}>
              Vendors <span style={{ fontSize: '0.68rem', opacity: 0.7 }}>({vendors.length})</span>
            </button>
            <button className={`ws-tab ${activeTab === 'Other Invoices' ? 'active' : ''}`} onClick={() => setActiveTab('Other Invoices')}>
              Other Invoices <span style={{ fontSize: '0.68rem', opacity: 0.7 }}>({invoices.filter(i => !i.customer_id).length})</span>
            </button>
          </WorkspaceTopBar>
        )}

        {/* Standalone header (legacy /parties route only) */}
        {!headerTabs && (
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
        )}

        {/* ── Unified filter bar: Search | FilterDropdown | SortDropdown ── */}
        <div className="page-subbar" style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
          {!headerTabs ? (
            <div className="tabs" style={{ margin: 0, flexShrink: 0 }}>
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
          ) : null}

          {/* Search — always first */}
          <div className="search-bar" style={{ margin: 0, height: 34, boxSizing: 'border-box', display: 'flex', alignItems: 'center', flex: '1 1 200px', maxWidth: 320 }}>
            <span style={{ color: 'var(--text-muted)', display: 'flex', alignItems: 'center' }}><SearchIcon size={16} /></span>
            <input value={search} onChange={e => setSearch(e.target.value)} placeholder={`Search ${activeTab.toLowerCase()}…`} style={{ fontSize: '0.82rem' }} />
          </div>

          {activeTab !== 'Other Invoices' && (
            <FilterDropdown
              filters={[{
                key: 'balance',
                label: 'Balance',
                type: 'chips',
                value: balanceFilter,
                onChange: setBalanceFilter,
                options: [
                  { value: '', label: 'All' },
                  { value: 'due', label: 'Outstanding Due' },
                  { value: 'nil', label: 'Nil / Zero' },
                ],
              }]}
            />
          )}

          <SortDropdown
            fields={activeTab === 'Other Invoices' ? [
              { value: 'invoice_number', label: 'Invoice #' },
              { value: 'date',           label: 'Date' },
              { value: 'total_amount',   label: 'Amount' },
            ] : [
              { value: 'name',                label: 'Name' },
              { value: 'outstanding_balance', label: 'Outstanding' },
              { value: 'last_date',           label: 'Latest Sale Date' },
            ]}
            sortConfig={sortConfig}
            onSortChange={setSortConfig}
          />

          {isRefreshing && (
            <span className="toolbar-refresh-spinner">
              <span className="spin" /> Refreshing…
            </span>
          )}
        </div>

        {/* Table */}
        {(() => {
          const tableContent = (
            <table className="data-table" style={{ width: '100%', fontSize: '0.82rem' }}>
              <thead>
                {activeTab === 'Customers' && (
                  <tr>
                    <th style={{ whiteSpace: 'nowrap' }}>Name</th>
                    <th style={{ whiteSpace: 'nowrap' }}>Phone</th>
                    <th style={{ whiteSpace: 'nowrap' }}>Email</th>
                    <th style={{ whiteSpace: 'nowrap' }}>GSTIN</th>
                    <th style={{ textAlign: 'right', whiteSpace: 'nowrap' }}>Outstanding</th>
                    <th style={{ whiteSpace: 'nowrap' }}>Latest Sale Date</th>
                    <th style={{ textAlign: 'right', whiteSpace: 'nowrap' }}>Actions</th>
                  </tr>
                )}
                {activeTab === 'Vendors' && (
                  <tr>
                    <th style={{ whiteSpace: 'nowrap' }}>Name</th>
                    <th style={{ whiteSpace: 'nowrap' }}>Phone</th>
                    <th style={{ whiteSpace: 'nowrap' }}>GSTIN</th>
                    <th style={{ textAlign: 'right', whiteSpace: 'nowrap' }}>Outstanding</th>
                    <th style={{ whiteSpace: 'nowrap' }}>Last Invoice Date</th>
                    <th style={{ textAlign: 'right', whiteSpace: 'nowrap' }}>Actions</th>
                  </tr>
                )}
                {activeTab === 'Other Invoices' && (
                  <tr>
                    <th style={{ whiteSpace: 'nowrap' }}>Invoice #</th>
                    <th style={{ whiteSpace: 'nowrap' }}>Date</th>
                    <th style={{ whiteSpace: 'nowrap' }}>Customer</th>
                    <th style={{ whiteSpace: 'nowrap' }}>Items</th>
                    <th style={{ textAlign: 'right', whiteSpace: 'nowrap' }}>Amount</th>
                    <th style={{ whiteSpace: 'nowrap' }}>Status</th>
                    <th style={{ textAlign: 'right', whiteSpace: 'nowrap' }}>Actions</th>
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
                      <tr key={p.id}
                        style={{ cursor: 'context-menu' }}
                        onContextMenu={e => {
                          e.preventDefault()
                          setCtxMenu({ x: e.clientX, y: e.clientY, items: [
                            { label: 'Print Invoice', icon: <PrinterIcon size={13} />, action: () => handlePrintInvoice(p.invoice_number || p.invoice_no) },
                            { label: 'Share on WhatsApp', icon: <MessageIcon size={13} />, action: () => handleWhatsAppShareInvoice(p) },
                            { divider: true },
                            { label: 'Copy Invoice No', icon: <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>, action: () => navigator.clipboard.writeText(p.invoice_number || p.invoice_no || '') },
                          ]})
                        }}
                      >
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
                          <div style={{ display: 'flex', gap: 6, justifyContent: 'center' }}>
                            <button className="btn btn-secondary btn-sm" onClick={() => handlePrintInvoice(p.invoice_number || p.invoice_no)}><PrinterIcon size={14} style={{ marginRight: 6, display: 'inline-block', verticalAlign: 'middle' }} /> Print</button>
                            <button className="btn btn-secondary btn-sm" onClick={() => handleWhatsAppShareInvoice(p)} title="Share invoice on WhatsApp"><MessageIcon size={14} style={{ marginRight: 6, display: 'inline-block', verticalAlign: 'middle' }} /> Share</button>
                            {p.invoice_type !== 'credit_note' && (
                              <button className="btn btn-secondary btn-sm" onClick={() => handleOpenReturn(p)} title={`Record Sales Return / ${label('sale_return')}`}><SyncIcon size={14} style={{ marginRight: 6, display: 'inline-block', verticalAlign: 'middle' }} /> Return</button>
                            )}
                          </div>
                        </td>
                      </tr>
                    )
                  }
                  const outstanding = parseFloat(p.outstanding_balance ?? 0)
                  return (
                    <tr key={p.id}
                      style={{ cursor: 'context-menu' }}
                      onContextMenu={e => {
                        e.preventDefault()
                        setCtxMenu({ x: e.clientX, y: e.clientY, items: [
                          { label: 'View Invoices', icon: <BillsIcon size={13} />, action: () => navigate(`/parties/invoices?customer=${encodeURIComponent(p.name)}`) },
                          { label: 'Send Payment Reminder', icon: <MessageIcon size={13} />, action: () => handleWhatsAppReminder(p) },
                          { divider: true },
                          { label: 'Copy Phone', icon: <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>, action: () => navigator.clipboard.writeText(p.phone || '') },
                          { label: 'Copy Name', icon: <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>, action: () => navigator.clipboard.writeText(p.name || '') },
                        ]})
                      }}
                    >
                      <td>
                        <div style={{ fontWeight: 600, color: 'var(--text-primary)' }}>{p.name}</div>
                        {p.address && <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>{p.address}</div>}
                      </td>
                      <td>{p.phone || '—'}</td>
                      {activeTab === 'Customers' && <td style={{ color: 'var(--text-muted)', fontSize: '0.82rem' }}>{p.email || '—'}</td>}
                      <td className="td-mono" style={{ fontSize: '0.78rem' }}>{p.gstin || '—'}</td>
                      <td style={{ textAlign: 'right', whiteSpace: 'nowrap' }}>{outstanding > 0 ? <span className="badge badge-danger">{fmt(outstanding)}</span> : <span className="badge badge-success">Nil</span>}</td>
                      <td style={{ color: 'var(--text-muted)', fontSize: '0.82rem', whiteSpace: 'nowrap' }}>
                        {activeTab === 'Customers'
                          ? (p.last_invoice_date ? new Date(p.last_invoice_date).toLocaleDateString('en-IN') : '—')
                          : (p.last_purchase_date ? new Date(p.last_purchase_date).toLocaleDateString('en-IN') : '—')
                        }
                      </td>
                      <td style={{ textAlign: 'right', whiteSpace: 'nowrap' }}>
                        <div style={{ display: 'flex', gap: 6, justifyContent: 'flex-end' }}>
                        {activeTab === 'Customers' ? (
                          <>
                            <button className="btn btn-secondary btn-sm" onClick={() => handleViewInvoices(p)}><BillsIcon size={14} style={{ marginRight: 6, display: 'inline-block', verticalAlign: 'middle' }} /> View Invoices</button>
                            {outstanding > 0 && !isCashier && (
                              <button
                                className="btn btn-secondary btn-sm"
                                onClick={() => navigate(`/parties/payments?customer=${encodeURIComponent(p.name)}`)}
                                title="View this customer's transactions in the Payments tab"
                              >
                                <CheckIcon size={14} style={{ marginRight: 4, display: 'inline-block', verticalAlign: 'middle' }} /> Settle
                              </button>
                            )}
                            {outstanding > 0 && (
                              <button className="btn btn-sm" style={{ backgroundColor: '#166534', color: '#ffffff', border: 'none' }} onClick={() => handleWhatsAppReminder(p)} title="Send payment reminder on WhatsApp"><MessageIcon size={14} style={{ marginRight: 4, display: 'inline-block', verticalAlign: 'middle' }} /> Send Reminder</button>
                            )}
                          </>
                        ) : (
                          <button className="btn btn-secondary btn-sm" onClick={() => handleViewPurchases(p)}><InventoryIcon size={14} style={{ marginRight: 4, display: 'inline-block', verticalAlign: 'middle' }} /> View Purchases</button>
                        )}
                        </div>
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
            <div style={{ position: 'relative', display: 'flex', flexDirection: 'column', flex: 1, minHeight: 0 }}>
              <button type="button" onClick={() => setIsFullScreen(true)} style={{ position: 'absolute', top: 6, right: 6, zIndex: 10, background: 'var(--bg-1)', border: '1px solid var(--border)', borderRadius: 'var(--radius-sm)', padding: 4, cursor: 'pointer', color: 'var(--text-secondary)' }} title="Full Screen">
                <ExpandIcon size={14} />
              </button>
              <div className="data-table-wrap">{tableContent}</div>
            </div>
          )
        })()}

      </div>

      {/* Add Party Modal */}
      {/* Add Party Modal — extracted to components/parties/PartyFormModal */}
      {showModal && (
        <PartyFormModal form={form} setField={setField} handleSubmit={handleSubmit} submitting={submitting} setShowModal={requestCloseModal} />
      )}

      {/* PartyDetailModal removed — "View Invoices" now navigates to the Invoices
          tab (/parties/invoices?customer=name) which shows a filterable table with
          full invoice actions (print, share, return, record payment). */}
      {/* Sale Return (Credit Note) Modal — extracted to components/parties/SaleReturnModal */}
      {showReturnModal && returningInvoice && (
        <SaleReturnModal
          returningInvoice={returningInvoice} setReturningInvoice={setReturningInvoice}
          returnLines={returnLines} setReturnLines={setReturnLines}
          returnNote={returnNote} setReturnNote={setReturnNote}
          handleSaveReturn={handleSaveReturn} savingReturn={savingReturn}
          setShowReturnModal={setShowReturnModal} form={form}
        />
      )}
      {/* SettleDuesModal removed — "Settle" now navigates to the Transactions tab
          (/parties/payments?customer=name) pre-filtered to that customer.
          The Transactions tab's workspace top bar has a Settle Dues button that handles
          the FIFO settlement flow from there. */}
      <ContextMenu menu={ctxMenu} onClose={() => setCtxMenu(null)} />
      <UnsavedChangesModal blocker={blocker} message={dirtyMessage} />
    </PageShell>
  )
}
