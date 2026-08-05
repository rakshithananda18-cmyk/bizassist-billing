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
import { BillsIcon, CheckIcon, CopyIcon, CloseIcon, ContactsIcon, HandshakeIcon, InventoryIcon, MessageIcon, PlusIcon, PrinterIcon, SearchIcon, SyncIcon, UserIcon, WarehouseIcon, ExpandIcon } from '../components/Icons'
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

export default function Parties({ embedded = false, headerTabs = null, inlinePage = false }) {
  // `inlinePage` — ContactsPayments owns the page header and the workspace tabs,
  // so this view renders only its own toolbar and body. `headerTabs` is the
  // older arrangement where the tabs were injected into that toolbar; both are
  // "embedded", hence the combined flag.
  const inWorkspace = Boolean(headerTabs) || inlinePage
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
      // per_page is REQUIRED here. The endpoints default to 20 and this page has
      // no pagination control, so without it the list silently stopped at the
      // 20th contact alphabetically and the tab badge reported that truncated
      // count as the total — 23 customers displayed as "Customers (20)".
      // Matches InvoicesListView's `/invoices?per_page=500`.
      authFetch('/billing/customers?per_page=500').then(r => r.ok ? r.json() : []).catch(() => []),
      authFetch('/billing/vendors?per_page=500').then(r => r.ok ? r.json() : []).catch(() => []),
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

  // Deactivate = "stop transacting with them"; the row stays and every past
  // invoice, payment and ledger line keeps working. There is deliberately no
  // delete: unlike a product, a party is referenced by money history from the
  // moment it exists, so the products contract's "should never have existed"
  // case has no honest equivalent here.
  const togglePartyActive = async (p) => {
    const next = p.is_active === false
    const kind = activeTab === 'Customers' ? 'customers' : 'vendors'
    try {
      const res = await authFetch(`/billing/${kind}/${p.id}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ is_active: next }),
      })
      if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || 'Update failed')
      setAlert({ type: 'success', msg: `${p.name} ${next ? 'reactivated' : 'deactivated'}.` })
      load()
    } catch (e) {
      setAlert({ type: 'danger', msg: e.message })
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

  // The vendor half of handleViewInvoices. Purchase bills live on the Stock
  // workspace's Purchase tab, whose search already matches supplier_name, so
  // this seeds it rather than adding a second filter.
  const handleViewPurchases = (vendor) => {
    navigate(`/stock/purchase?vendor=${encodeURIComponent(vendor.name)}`)
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

  // Search / Filter / Sort, defined once and placed differently per layout:
  // INSIDE the workspace toolbar when embedded (one bar, not two), or in the
  // standalone `.page-subbar` on the legacy route. Measured before merging —
  // toolbar 488px + these 160px + a flexible search against 979px available,
  // so the row genuinely holds them rather than hiding half.
  const filterControls = (
    <>
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
    </>
  )

  return (
    <PageShell embedded={embedded} title="Parties & Invoices">
      <div className={`${inWorkspace ? 'fade-in ws-embed' : 'slide-up'}`}>

        {alert && (
          <div className={`alert alert-${alert.type} mb-4`}>
            {alert.type === 'success' ? '✅' : '❌'} {alert.msg}
            <button onClick={() => setAlert(null)} style={{ marginLeft: 'auto', background: 'none', border: 'none', color: 'inherit', cursor: 'pointer' }} aria-label="Close"><CloseIcon size={16} /></button>
          </div>
        )}

        {/* Signature Page Header — owned by ContactsPayments when embedded. */}
        {!inlinePage && (
        <div className="page-header">
          <div className="page-header-left">
            <h1 className="page-title">
              <ContactsIcon size={20} style={{ color: 'var(--accent)' }} /> Contacts & Payments
            </h1>
            <p className="page-subtitle">Manage customer & vendor accounts, credit limits, outstanding balances, and payment transactions</p>
          </div>
          <div className="page-actions">
            <button className="btn btn-primary" onClick={() => { setForm(defaultForm); setShowModal(true) }}>
              <PlusIcon size={14} /> Add Party
            </button>
          </div>
        </div>
        )}

        {/* Embedded (Godown): 48px workspace bar */}
        {inWorkspace && (
          <WorkspaceTopBar
            settingsTab="parties"
            actions={inlinePage ? (
              <>
                {filterControls}
                <button className="btn btn-primary btn-sm"
                  onClick={() => { setForm(defaultForm); setShowModal(true) }}>
                  <PlusIcon size={13} /> Add Party
                </button>
              </>
            ) : null}
          >
            {headerTabs}
            {headerTabs && <WsDivider />}
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

        {/* ── Unified filter bar: Search | FilterDropdown | SortDropdown ── */}
        {!inWorkspace && (
          <div className="page-subbar" style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
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
            {filterControls}
          </div>
        )}

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
                            { label: 'Copy Invoice No', icon: <CopyIcon size={13} />, action: () => navigator.clipboard.writeText(p.invoice_number || p.invoice_no || '') },
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
                        {/* This cell was the literal string "Casual / Walk-in"
                            for every row. The tab filters on `!customer_id`, so
                            the label was right for most rows and WRONG for any
                            invoice that recorded a customer NAME without ever
                            getting an FK — those exist (LCL-OW-0015 carries
                            customer='Varshini' with customer_id = NULL) and the
                            owner was being told a named sale was a walk-in.

                            Show what the row actually holds; fall back to the
                            walk-in wording only when there is genuinely no
                            customer on it. */}
                        <td style={{ color: p.customer ? 'var(--text-primary)' : 'var(--text-muted)' }}>
                          {p.customer || p.customer_name || 'Casual / Walk-in'}
                          {p.customer && (
                            <span
                              title="This invoice records a customer name but is not linked to a customer record, so it does not appear in that customer's ledger."
                              style={{ marginLeft: 6, fontSize: '0.62rem', color: 'var(--warning, #b45309)', fontWeight: 600 }}
                            >
                              UNLINKED
                            </span>
                          )}
                        </td>
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
                      className={p.is_active === false ? 'row-inactive' : undefined}
                      style={{ cursor: 'context-menu' }}
                      onContextMenu={e => {
                        e.preventDefault()
                        setCtxMenu({ x: e.clientX, y: e.clientY, items: [
                          { label: 'View Invoices', icon: <BillsIcon size={13} />, action: () => navigate(`/parties/invoices?customer=${encodeURIComponent(p.name)}`) },
                          { label: 'Send Payment Reminder', icon: <MessageIcon size={13} />, action: () => handleWhatsAppReminder(p) },
                          { divider: true },
                          // Lives in the right-click menu, not the action rail.
                          // The rail is icon-only precisely because text buttons
                          // there made Actions the widest column in the table
                          // (347px of 1203px) and pushed the grid past its
                          // container — same reason products puts it here.
                          {
                            label: p.is_active === false
                              ? `Reactivate ${activeTab === 'Customers' ? 'Customer' : 'Vendor'}`
                              : `Deactivate ${activeTab === 'Customers' ? 'Customer' : 'Vendor'}`,
                            icon: <CheckIcon size={13} />,
                            action: () => togglePartyActive(p),
                          },
                          { divider: true },
                          { label: 'Copy Phone', icon: <CopyIcon size={13} />, action: () => navigator.clipboard.writeText(p.phone || '') },
                          { label: 'Copy Name', icon: <CopyIcon size={13} />, action: () => navigator.clipboard.writeText(p.name || '') },
                        ]})
                      }}
                    >
                      <td>
                        <div style={{ fontWeight: 600, color: 'var(--text-primary)' }}>
                          {p.name}
                          {p.is_active === false && <span className="tag-inactive">Inactive</span>}
                        </div>
                        {/* One line, ellipsised, full text on hover. A postal
                            address wrapped to 2-3 lines here was setting the
                            height of EVERY cell in the row — measured 109px per
                            contact, of which 46px was this element alone. The
                            address is reference detail, not something scanned
                            down a list; the row is for finding the party. */}
                        {p.address && (
                          <div className="row-subline" title={p.address}>{p.address}</div>
                        )}
                      </td>
                      <td>{p.phone || '—'}</td>
                      {activeTab === 'Customers' && (
                        <td className="td-clip" style={{ color: 'var(--text-muted)', fontSize: '0.82rem' }} title={p.email || ''}>{p.email || '—'}</td>
                      )}
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
                        {/* ICON-ONLY, with the label in `title`. Text buttons
                            made this the widest column in the table by a
                            distance — 347px of 1203px, which is what pushed the
                            grid 235px past its container and cut the column in
                            half. InvoiceActions already renders row actions this
                            way, which is why the Invoices grid fits; this is the
                            same convention, not a new one. Every action is also
                            in the row's right-click menu. */}
                        {activeTab === 'Customers' ? (
                          <>
                            <button className="btn btn-secondary btn-sm row-act" onClick={() => handleViewInvoices(p)}
                              title="View invoices" aria-label="View invoices"><BillsIcon size={14} /></button>
                            {outstanding > 0 && !isCashier && (
                              <button
                                className="btn btn-secondary btn-sm row-act"
                                onClick={() => navigate(`/parties/payments?customer=${encodeURIComponent(p.name)}`)}
                                title="Settle — view this customer's transactions"
                                aria-label="Settle dues"
                              >
                                <CheckIcon size={14} />
                              </button>
                            )}
                            {outstanding > 0 && (
                              <button className="btn btn-sm row-act" style={{ backgroundColor: '#166534', color: '#ffffff', border: 'none' }}
                                onClick={() => handleWhatsAppReminder(p)}
                                title="Send payment reminder on WhatsApp" aria-label="Send payment reminder"><MessageIcon size={14} /></button>
                            )}
                          </>
                        ) : (
                          <button className="btn btn-secondary btn-sm row-act" onClick={() => handleViewPurchases(p)}
                            title="View purchases" aria-label="View purchases"><InventoryIcon size={14} /></button>
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
