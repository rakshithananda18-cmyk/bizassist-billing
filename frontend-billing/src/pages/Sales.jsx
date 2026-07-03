// ============================================================================
// Page: Sales.jsx
// Description: POS Counter Orchestrator. Manages multi-tab active carts, product
//              scanning, pricing tier selection, payment flow, and receipt printing.
//              Integrated with offline outbox sync and collaborative SSE sessions.
// ============================================================================
import React, { useEffect, useState, useCallback, useRef, useMemo } from 'react'
import { useNavigate, useSearchParams, useLocation } from 'react-router-dom'
import { IS_LOCAL_APP } from '../config'
import AppLayout from '../layouts/AppLayout'
import { useAuth, useBusinessConfig } from '../contexts/AuthContext'
import { AlertIcon, BillsIcon, CheckIcon, ChevronRightIcon, CloseIcon, TagIcon } from '../components/Icons'
// Shared formatting helpers (money / today / amount-in-words) live in utils/format.
import { fmt, getTodayDateStr } from '../utils/format'
// Invoice money-math (line totals, intra/inter GST split, change due) — pure + tested.
import { lineTotal, computeInvoiceTotals, changeDue, buildInvoicePayload, columnTotals, suggestedTenders, schemeDiscount } from '../utils/invoiceMath'
import { logger } from '../utils/logger'
import { useBillingProfile } from '../hooks/useBillingProfile'
import TotalBreakupModal from '../components/sales/TotalBreakupModal'
import PosTotalBar from '../components/sales/PosTotalBar'
import InvoiceBreakdownCard from '../components/sales/InvoiceBreakdownCard'
import TenderChips from '../components/sales/TenderChips'
import CheckoutModal from '../components/sales/CheckoutModal'
import ThermalReceipt from '../components/sales/ThermalReceipt'
import PosTopBar from '../components/sales/PosTopBar'
import ProductSearchBar from '../components/sales/ProductSearchBar'
import CartTableHeader from '../components/sales/CartTableHeader'
import CartEmptyRows from '../components/sales/CartEmptyRows'
import CartItemRow from '../components/sales/CartItemRow'
import CartFooterRow from '../components/sales/CartFooterRow'
import { PosCounterSettingsModal } from '../components/sales/PosSettingsModals'
import { OpenShiftModal, CloseShiftModal, CashMovementModal } from '../components/sales/ShiftModals'
import usePaymentFlow from '../hooks/usePaymentFlow'
import { syncManager } from '../sync/syncManager'
import { pendingInvoiceRows } from '../sync/pendingInvoices'

// ============================================================================
// ── 2. GLOBAL DEFAULTS & VALUE SCHEMAS ──
// ============================================================================
const colLabels = {
  sku: 'Item Code',
  name: 'Item Name',
  batch: 'Batch',
  serial: 'Serial / IMEI',
  attrs: 'Item Details (Size/Color/Warranty…)',
  price_option: 'Price Option',
  mrp: 'MRP',
  hsn: 'HSN',
  qty: 'Quantity',
  unit: 'Unit',
  rate: 'Price Per Unit Before Tax',
  price: 'Total Before Tax',
  discount: 'Discount',
  tax: 'Tax',
  total: 'Total After Tax'
}

const emptyItem = () => ({ product_id: '', product: '', qty: 1, price: '', discount: 0, sku: '—', is_custom: false, batch_no: '', expiry_date: '', serial_no: '', attributes: {}, selected_price: '', selected_price_label: 'Standard Price' })

const defaultForm = {
  customer_id: '',
  godown_id: '',
  due_date: getTodayDateStr(),
  items: [],
  gst_enabled: false,
  notes: '',
  payment_mode: 'cash',
  amount_received: '',
  bill_discount_type: 'amount',   // 'amount' (flat ₹) | 'percent'
  bill_discount_value: '',        // the ₹ or % the cashier types at checkout
  cash_discount: '',              // POST-tax cash discount / round-off (₹) — reduces payable, not GST (R4)
}

// Effective hosting mode for invoice-number tagging — the SAME source config.js
// uses to pick the backend (and useRealtimeLeader uses for SSE). Web is ALWAYS
// cloud; a desktop app uses its own per-device `bizassist_hosting_mode`. We must
// NOT read settings.general.hosting_mode (null until the slow /settings fetch
// returns → an `LCL-` flash on cloud bills, §9.3b).
function effectiveHostingMode() {
  if (!IS_LOCAL_APP) return 'cloud'
  const m = (typeof localStorage !== 'undefined' && localStorage.getItem('bizassist_hosting_mode')) || 'local'
  return m.toLowerCase()
}

// ============================================================================
// ── 3. STATE INITIALIZATION (COUNTER & DB DATA) ──
// ============================================================================
export default function Sales(props = {}) {
  const { authFetch, profile, user } = useAuth()
  // Business-type billing profile (Phase 2) — follows the counter-mode switcher
  // live; FAIL-OPEN (null when offline → no behavior change).
  const { profile: billingProfile } = useBillingProfile()
  const { config, attributesSchema, t } = useBusinessConfig()
  const navigate = useNavigate()
  const [searchParams, setSearchParams] = useSearchParams()
  const liveCounter = searchParams.get('live_counter')
  const liveClientId = searchParams.get('client_id')
  const isLiveView = props.isLiveViewMode || !!liveCounter
  const isOwner = (user?.role || '').toLowerCase() !== 'cashier'
  const location = useLocation()

  // Collaborative live counter states
  const [editState, setEditState] = useState('idle') // 'idle' | 'requesting' | 'granted' | 'denied'
  const [activeSessions, setActiveSessions] = useState({}) // counter -> { client_id, username }
  const [isLockedByManager, setIsLockedByManager] = useState(false)
  const [managerClientId, setManagerClientId] = useState(null)
  const [managerUsername, setManagerUsername] = useState(null)
  const [showRemoteRequestModal, setShowRemoteRequestModal] = useState(false)
  const [isRemoteCartLoading, setIsRemoteCartLoading] = useState(isLiveView)
  const [connectionStatus, setConnectionStatus] = useState('connecting') // 'connecting' | 'offline' | 'timeout'

  const activeCashierClientId = activeSessions[liveCounter]?.client_id || liveClientId

  const [customers, setCustomers]     = useState([])
  const [products, setProducts]       = useState([])
  const [godowns, setGodowns]         = useState([])
  const [loading, setLoading]         = useState(true)
  const [settings, setSettings]       = useState(null)
  const [submitting, setSubmitting]   = useState(false)
  const [alert, setAlert]             = useState(null)
  const [searchQuery, setSearchQuery] = useState('')
  const [selectedIndex, setSelectedIndex] = useState(-1)
  const [showSettingsModal, setShowSettingsModal] = useState(false)
  const [settingsInitialTab, setSettingsInitialTab] = useState('general')
  const [showBreakupModal, setShowBreakupModal] = useState(false)
  const [bindingAction, setBindingAction] = useState(null)
  const [dbInvoices, setDbInvoices]   = useState([])
  const [showPayConfirmModal, setShowPayConfirmModal] = useState(false)
  const [staffList, setStaffList] = useState([])

  // ── Shift & cash-drawer management (Phase 3) ──────────────────────────────
  // undefined = still checking · null = NO open shift (billing locked behind
  // the OpenShiftModal gatekeeper — every role, owner included) · object = open.
  // Live-view (owner watching a remote counter) is exempt: it's the CASHIER's
  // shift, not the viewer's.
  const [shift, setShift] = useState(undefined)
  const [showCloseShiftModal, setShowCloseShiftModal] = useState(false)
  const [showCashMovementModal, setShowCashMovementModal] = useState(false)

  const refreshShift = useCallback(async () => {
    if (isLiveView) return
    try {
      const res = await authFetch('/shifts/current')
      if (res.ok) {
        const data = await res.json().catch(() => null)
        setShift(data?.shift ?? null)
      } else {
        setShift(null)
      }
    } catch {
      // Offline: FAIL-OPEN like the billing profile — don't brick the counter
      // on a network blip. The backend still strictly enforces the gate when
      // the bill (or the offline outbox replay) reaches it.
      setShift(s => (s === undefined ? { offline: true } : s))
    }
  }, [authFetch, isLiveView])

  useEffect(() => { refreshShift() }, [refreshShift])

  // ============================================================================
  // ── 4. OFFLINE SYNC OUTBOX BINDINGS ──
  // ============================================================================
  // ── Offline sync (R7b Slice 3c) ───────────────────────────────────────────
  // Bills saved while offline live in the durable outbox until reconnect. We mirror
  // the pending list into state (for the "N unsynced" badge) AND a ref (so number
  // allocation can read it without re-running the data load). `mergePending` folds
  // the queued invoice numbers into the "known invoices" the allocator sees, so two
  // offline bills never collide on the same number (which the server's inner wall
  // would silently drop).
  const [pendingSync, setPendingSync] = useState([])
  const pendingSyncRef = useRef([])
  const refreshPendingSync = useCallback(async () => {
    try {
      const ops = await syncManager.pending()
      pendingSyncRef.current = ops
      setPendingSync(ops)
    } catch { /* outbox unavailable — ignore */ }
  }, [])
  const enqueueOffline = useCallback(async (op) => {
    const rec = await syncManager.queue(op)
    await refreshPendingSync()
    return rec
  }, [refreshPendingSync])
  const mergePending = useCallback(
    (invs) => [...(invs || []), ...pendingInvoiceRows(pendingSyncRef.current)],
    [],
  )

  // ============================================================================
  // ── 5. FUNCTION KEYS & COLUMN ORDER PERSISTENCE ──
  // ============================================================================
  const defaultFuncKeys = {
    qtyFocus: 'F2',
    discountFocus: 'F3',
    checkoutDiscountFocus: 'F7',
    removeItem: 'F4',
    amountReceivedFocus: 'F8',
    barcodeFocus: 'F9',
    customerFocus: 'F11',
    remarksFocus: 'F12',
    configureShortcuts: 'F1',
    paymentProceed: 'Enter',
    paymentCancel: 'Escape',
    // Payment flow navigation
    flowForward: 'Enter',
    flowBack: 'Shift+Enter',
    // Key to move from item scanning → payment flow (customer → amount → mode)
    proceedToPayment: 'Escape',
  }

  const [funcKeys, setFuncKeys] = useState(() => {
    const saved = localStorage.getItem('pos_func_keys')
    if (saved) {
      try {
        return JSON.parse(saved)
      } catch (e) {
        logger.error('[SALES] failed to parse pos_func_keys', e)
      }
    }
    return defaultFuncKeys
  })

  const [columnOrder, setColumnOrder] = useState(() => {
    const saved = localStorage.getItem('pos_column_order')
    if (saved) {
      try {
        const parsed = JSON.parse(saved)
        if (Array.isArray(parsed) && parsed.length > 0) {
          if (!parsed.includes('batch')) {
            const nameIdx = parsed.indexOf('name')
            if (nameIdx !== -1) {
              parsed.splice(nameIdx + 1, 0, 'batch')
            } else {
              parsed.push('batch')
            }
          }
          if (!parsed.includes('price_option')) {
            const batchIdx = parsed.indexOf('batch')
            if (batchIdx !== -1) {
              parsed.splice(batchIdx + 1, 0, 'price_option')
            } else {
              parsed.push('price_option')
            }
          }
          if (!parsed.includes('serial')) {
            const batchIdx = parsed.indexOf('batch')
            if (batchIdx !== -1) {
              parsed.splice(batchIdx + 1, 0, 'serial')
            } else {
              parsed.push('serial')
            }
          }
          if (!parsed.includes('rate')) {
            const qtyIdx = parsed.indexOf('qty')
            if (qtyIdx !== -1) {
              parsed.splice(qtyIdx + 1, 0, 'rate')
            } else {
              parsed.push('rate')
            }
          }
          if (!parsed.includes('attrs')) {
            const serialIdx = parsed.indexOf('serial')
            if (serialIdx !== -1) {
              parsed.splice(serialIdx + 1, 0, 'attrs')
            } else {
              parsed.push('attrs')
            }
          }
          return parsed
        }
      } catch (e) {
        logger.error('[SALES] failed to parse pos_column_order', e)
      }
    }
    return ['sku', 'name', 'batch', 'serial', 'attrs', 'price_option', 'mrp', 'hsn', 'qty', 'unit', 'rate', 'price', 'discount', 'tax', 'total']
  })


  const [priceSelectorIndex, setPriceSelectorIndex] = useState(null)
  const [selectedPriceOptIndex, setSelectedPriceOptIndex] = useState(0)

  const handleMoveColumn = (index, direction) => {
    const nextOrder = [...columnOrder]
    if (direction === 'up' && index > 0) {
      const temp = nextOrder[index - 1]
      nextOrder[index - 1] = nextOrder[index]
      nextOrder[index] = temp
    } else if (direction === 'down' && index < nextOrder.length - 1) {
      const temp = nextOrder[index + 1]
      nextOrder[index + 1] = nextOrder[index]
      nextOrder[index] = temp
    }
    setColumnOrder(nextOrder)
    localStorage.setItem('pos_column_order', JSON.stringify(nextOrder))
  }

  const getStickyLeftOffsets = (order, visibleObj) => {
    const offsets = {}
    let currentOffset = 40
    let freezeAllowed = true

    for (let i = 0; i < order.length; i++) {
      const col = order[i]
      const isVisible = col === 'sku' ? visibleObj.sku :
                        col === 'mrp' ? visibleObj.mrp :
                        col === 'hsn' ? visibleObj.hsn :
                        col === 'unit' ? visibleObj.unit :
                        col === 'discount' ? visibleObj.discount :
                        col === 'tax' ? visibleObj.tax :
                        col === 'batch' ? visibleObj.batch :
                        col === 'price_option' ? visibleObj.price_option :
                        col === 'rate' ? visibleObj.rate :
                        true

      if (!isVisible) continue

      if (freezeAllowed && (col === 'sku' || col === 'name')) {
        offsets[col] = currentOffset
        if (col === 'sku') {
          currentOffset += 95
        } else if (col === 'name') {
          currentOffset += 180
        }
      } else {
        freezeAllowed = false
      }
    }
    return offsets
  }

  // ============================================================================
  // ── 6. BATCHES & PRICE SELECTOR RESOLVERS ──
  // ============================================================================
  const getPriceOptions = (item) => {
    if (!item || item.is_custom || !item.product_id) return []
    const p = products.find(prod => prod.id === item.product_id)
    if (!p) return []

    const rawOptions = []

    // Base standard prices first
    rawOptions.push(
      { label: 'Standard Price', price: p.selling_price, created_at: null, formatted_date: 'Base Product' },
      { label: 'Wholesale Price', price: p.wholesale_price, created_at: null, formatted_date: 'Base Product' },
      { label: 'Distributor Price', price: p.distributor_price, created_at: null, formatted_date: 'Base Product' },
      { label: 'MRP', price: p.mrp, created_at: null, formatted_date: 'Base Product' }
    )

    // Gather batches and sort them by created_at descending (latest first)
    const batches = productBatches[item.product_id] || []
    const sortedBatches = [...batches].sort((a, b) => {
      const dateA = a.created_at ? new Date(a.created_at) : new Date(0)
      const dateB = b.created_at ? new Date(b.created_at) : new Date(0)
      return dateB - dateA
    })

    sortedBatches.forEach(b => {
      if (b.selling_price && b.selling_price > 0) {
        rawOptions.push({
          label: `Batch ${b.batch_no || '—'} Price`,
          price: b.selling_price,
          created_at: b.created_at,
          formatted_date: b.created_at ? new Date(b.created_at).toLocaleDateString('en-GB') : '—'
        })
      }
      if (b.mrp && b.mrp > 0) {
        rawOptions.push({
          label: `Batch ${b.batch_no || '—'} MRP`,
          price: b.mrp,
          created_at: b.created_at,
          formatted_date: b.created_at ? new Date(b.created_at).toLocaleDateString('en-GB') : '—'
        })
      }
    })

    const seen = new Set()
    const options = []
    rawOptions.forEach(opt => {
      const val = parseFloat(opt.price)
      if (val && val > 0 && !seen.has(val)) {
        seen.add(val)
        options.push({
          label: opt.label,
          price: val,
          created_at: opt.created_at,
          formatted_date: opt.formatted_date
        })
      }
    })

    return options
  }

  const handlePriceInputFocus = (index) => {
    // Popup selector is disabled in favor of inline dropdown and rate columns
    setPriceSelectorIndex(null)
  }

  const handleSelectPriceOption = (price, label) => {
    if (priceSelectorIndex !== null) {
      setForm(f => {
        const items = [...f.items]
        const item = items[priceSelectorIndex]
        if (item) {
          const p = products.find(prod => prod.id === item.product_id)
          let newPrice = price
          let newDiscount = 0
          const qty = parseFloat(item.qty) || 1
          
          if (p && parseFloat(p.mrp) > 0 && price <= parseFloat(p.mrp)) {
             newPrice = parseFloat(p.mrp)
             newDiscount = schemeDiscount(p.mrp, price, qty)
          }

          items[priceSelectorIndex] = {
            ...item,
            price: newPrice,
            discount: newDiscount,
            selected_price: price,
            selected_price_label: label || 'Custom Price'
          }
        }
        return { ...f, items }
      })
      setPriceSelectorIndex(null)
      setSelectedPriceOptIndex(0)
      setTimeout(() => barcodeRef.current?.focus(), 50)
    }
  }

  // Update a line's quantity AND keep the auto "MRP-as-price" scheme discount in
  // sync with qty. The discount is stored as an absolute amount = (MRP − chosen
  // price) × qty, so it MUST rescale when qty changes — otherwise the line bills
  // toward MRP (the overcharge bug: chose ₹200 at qty 1, raised to qty 4, was
  // billing ₹920 instead of ₹800). Mirrors the re-add path. We only touch the
  // discount while the line is in scheme mode (price == MRP, a chosen price at/
  // below MRP, no manually-typed price); otherwise qty alone changes.
  // Returns a copy of `item` with qty set and the MRP-scheme discount rescaled to
  // the new qty. EVERY qty-change path (typing, +, arrow keys) must go through
  // this, or the absolute discount stays at its old-qty value and the line bills
  // toward MRP. No rescale when the cashier typed a custom price (no scheme).
  const withQty = (item, newQty) => {
    const updated = { ...item, qty: newQty }
    if (updated.product_id) {
      const p = products.find(prod => prod.id === updated.product_id)
      const mrp = p ? (parseFloat(p.mrp) || 0) : (parseFloat(updated.mrp) || 0)
      const selPrice = parseFloat(updated.selected_price) || 0
      
      if (mrp > 0 && selPrice <= mrp) {
        updated.price = mrp
        updated.discount = schemeDiscount(mrp, selPrice, newQty)
      } else {
        updated.price = selPrice
        updated.discount = 0
      }
    }
    return updated
  }

  const handleQtyChange = (index, value) => {
    if (isLiveView && editState !== 'granted') return
    setForm(f => {
      const items = [...f.items]
      if (!items[index]) return f
      items[index] = withQty(items[index], value)
      return { ...f, items }
    })
  }

  const clientIdRef = useRef(Math.random().toString(36).substring(7))
  const clientId = clientIdRef.current
  const lastIncomingSyncRef = useRef(null)
  const isSystemLoadingRef = useRef(false)
  const tabsRef = useRef(null) // mirrors `tabs` for stale-closure-free reads in the SSE handler

  // POS cart scope (gap G5). The in-progress cart is PER-TERMINAL: two cashiers
  // at two terminals must have independent open bills, so we do NOT mirror a
  // live cart from another client into this one (silent cross-terminal LWW could
  // erase an in-progress sale — exactly the clobber observed in the 2-device soak).
  // Real-time sync of COMMITTED data (invoices/stock/products/payments) is
  // unaffected — that still flows. A deliberate, intentful cart hand-off
  // (waiter→counter) is Phase 4 (presence + soft-lock), not blind mirroring.
  // Flip to true only to restore the old shared-cart behavior (single-cashier use).
  const POS_CROSS_DEVICE_CART_SYNC = false

  // True when any tab in this cart state holds at least one line item.
  const cartHasItems = (tabsArr) =>
    Array.isArray(tabsArr) && tabsArr.some(t => (t?.form?.items?.length || 0) > 0)

  const [tabs, setTabs] = useState(() => {
    const uid = user?.user_id || user?.id
    if (isLiveView) {
      const savedLiveTabsStr = uid ? localStorage.getItem(`pos_live_minimized_tabs_${uid}`) : null
      if (savedLiveTabsStr) {
        try {
          const savedLiveTabs = JSON.parse(savedLiveTabsStr)
          if (Array.isArray(savedLiveTabs) && savedLiveTabs.length > 0) {
            return savedLiveTabs
          }
        } catch (e) {
          logger.error('[SALES] failed to parse minimized live tabs', e)
        }
      }
      return [
        { id: '1', name: `Loading Counter ${liveCounter || ''}...`, form: defaultForm }
      ]
    }
    const savedTabsStr = uid ? localStorage.getItem(`pos_minimized_tabs_${uid}`) : null
    const savedActiveId = uid ? localStorage.getItem(`pos_minimized_active_id_${uid}`) : null
    if (savedTabsStr && savedActiveId) {
      try {
        const savedTabs = JSON.parse(savedTabsStr)
        if (Array.isArray(savedTabs) && savedTabs.length > 0) {
          return savedTabs
        }
      } catch (e) {
        logger.error('[SALES] failed to parse minimized tabs', e)
      }
    }
    return [
      { id: '1', name: 'Invoice #1001', form: defaultForm }
    ]
  })

  // ============================================================================
  // ── 7. POS TAB & CART STATE MACHINE ──
  // ============================================================================
  const [activeTabId, setActiveTabId] = useState(() => {
    const uid = user?.user_id || user?.id
    if (isLiveView) {
      const savedActiveId = uid ? localStorage.getItem(`pos_live_minimized_active_id_${uid}`) : null
      if (savedActiveId) return savedActiveId
      return '1'
    }
    const savedActiveId = uid ? localStorage.getItem(`pos_minimized_active_id_${uid}`) : null
    if (savedActiveId) return savedActiveId
    return '1'
  })

  const activeTab = tabs.find(t => t.id === activeTabId) || tabs[0] || { id: '1', name: 'Invoice #1001', form: defaultForm }
  const form = activeTab.form

  const setForm = useCallback((updater) => {
    setTabs(prevTabs => prevTabs.map(t => {
      if (t.id === activeTabId) {
        const nextForm = typeof updater === 'function' ? updater(t.form) : updater
        return { ...t, form: nextForm }
      }
      return t
    }))
  }, [activeTabId])

  useEffect(() => {
    tabsRef.current = tabs // keep a fresh handle for the SSE receive guard below
    if (isLiveView) return // do NOT persist live counter view tabs to local storage!

    const uid = user?.user_id || user?.id
    if (!uid) return

    // Persist cart state locally — restored on page reload (per-device, always on)
    localStorage.setItem(`pos_minimized_tabs_${uid}`, JSON.stringify(tabs))
    localStorage.setItem(`pos_minimized_active_id_${uid}`, activeTabId)
  }, [tabs, activeTabId, user?.user_id, user?.id, isLiveView])

  // ============================================================================
  // ── 7.5. HANDLE LOCATION STATE (Duplicate / Credit Note) ──
  // ============================================================================
  useEffect(() => {
    if (!location.state) return
    const { duplicateFrom, creditNoteFrom } = location.state
    const sourceInvoice = duplicateFrom || creditNoteFrom
    if (!sourceInvoice) return

    // Clear state so we don't reload it again if user navigates back and forth
    window.history.replaceState({}, document.title)

    authFetch(`/sales/${encodeURIComponent(sourceInvoice)}/print-payload`)
      .then(res => res.json())
      .then(payload => {
        if (!payload || !payload.invoice) return

        const inv = payload.invoice
        const lines = payload.lines || []
        
        // Map payload items back to POS form structure
        const cartItems = lines.map(line => {
           // We might not have full product data in payload, but we have enough for POS
           return {
             ...emptyItem(),
             product_id: '', 
             product: line.name || '',
             qty: line.qty ? parseFloat(line.qty) : 1,
             rate: line.rate ? parseFloat(line.rate) : 0,
             price: line.rate ? parseFloat(line.rate) : 0,
             discount: line.discount ? parseFloat(line.discount) : 0,
             sku: '—',
             hsn: line.hsn || '',
             unit: line.unit || 'Nos',
             is_custom: true // mark as custom so POS doesn't try to sync prices with db
           }
        })

        const newForm = {
           ...defaultForm,
           customer_id: payload.buyer?.name || '', // Will map as free-text unless matching customer is found
           items: cartItems,
           gst_enabled: !!(payload.seller?.gstin),
           notes: creditNoteFrom ? `Credit Note for Invoice ${sourceInvoice}` : '',
        }
        
        // Create new tab
        const newId = Math.random().toString(36).substring(7)
        setTabs(prev => [
           ...prev,
           { id: newId, name: creditNoteFrom ? `CN-${sourceInvoice}` : `Dup-${sourceInvoice}`, form: newForm }
        ])
        setActiveTabId(newId)
      })
      .catch(e => logger.error('Failed to load invoice for duplication', e))

  }, [location.state, authFetch])

  // ============================================================================
  // ── 8. COLLABORATIVE LIVE COUNTER (SSE) ──
  // ============================================================================
  useEffect(() => {
    if (isLiveView) {
      const uid = user?.user_id || user?.id
      if (uid) {
        localStorage.removeItem(`pos_live_minimized_${uid}`)
        localStorage.removeItem(`pos_live_minimized_counter_${uid}`)
        localStorage.removeItem(`pos_live_minimized_client_id_${uid}`)
        localStorage.removeItem(`pos_live_minimized_tabs_${uid}`)
        localStorage.removeItem(`pos_live_minimized_active_id_${uid}`)
        window.dispatchEvent(new Event('pos_minimized_changed'))
      }
    }
  }, [isLiveView, user?.user_id, user?.id])

  useEffect(() => {
    if (props.isLiveViewMode && !liveCounter) {
      logger.warn('[SALES] Entered live-view without counter ID, redirecting to Live Counters list.')
      navigate('/pos-live-counter')
    }
  }, [props.isLiveViewMode, liveCounter, navigate])

  const broadcastMessage = useCallback(async (msg) => {
    try {
      await authFetch('/realtime/broadcast', {
        method: 'POST',
        body: JSON.stringify(msg)
      })
    } catch (err) {
      logger.error('[SALES] Failed to broadcast realtime message:', err)
    }
  }, [authFetch])

  useEffect(() => {
    if (isLockedByManager) return

    const shouldBroadcast =
      POS_CROSS_DEVICE_CART_SYNC ||
      (isLiveView && editState === 'granted') ||
      (!isLiveView && effectiveHostingMode() === 'cloud')
    if (!shouldBroadcast) return

    const uid = user?.user_id || user?.id
    if (!uid) return

    const isSalesSyncEnabled = settings?.general?.realtime_sync_sales !== false
    if (!isSalesSyncEnabled) return

    // Skip broadcast if this update was triggered by receiving a remote sync event
    const matchesSync = lastIncomingSyncRef.current &&
      JSON.stringify(tabs) === JSON.stringify(lastIncomingSyncRef.current.tabs) &&
      activeTabId === lastIncomingSyncRef.current.activeTabId

    if (matchesSync) {
      return
    }

    // Skip broadcast if the system is currently loading background data
    if (isSystemLoadingRef.current) {
      return
    }

    // State has deviated, clear the sync ref
    lastIncomingSyncRef.current = null

    const now = Date.now()
    localStorage.setItem(`pos_cart_updated_at_${uid}`, now.toString())

    const currentCounter = isLiveView
      ? liveCounter
      : ((user?.counter_prefix || '').trim().replace(/-$/, '') || ((user?.role || '').toLowerCase() !== 'cashier' ? 'OW' : 'INV'))

    // 1. Send instant cart sync broadcast over active SSE stream
    logger.info('[SALES] Broadcasting cart sync to SSE:', { clientId, tabsCount: tabs?.length, activeTabId, counter: currentCounter, isLiveView })
    broadcastMessage({
      type: 'pos.cart_sync',
      client_id: clientId,
      user_id: uid,
      tabs,
      active_tab_id: activeTabId,
      counter: currentCounter,
      is_live_view: isLiveView,
      timestamp: now
    })

    // 2. Debounce database backup sync (600ms)
    const t = setTimeout(async () => {
      try {
        await authFetch('/realtime/sync-cart', {
          method: 'POST',
          body: JSON.stringify({
            client_id: clientId,
            user_id: uid,
            tabs,
            active_tab_id: activeTabId,
            counter: currentCounter,
            is_live_view: isLiveView,
            timestamp: now
          })
        })
      } catch (err) {
        logger.error('[SALES] Failed to broadcast cart sync:', err)
      }
    }, 600)

    return () => clearTimeout(t)
  }, [tabs, activeTabId, user?.user_id, user?.id, authFetch, clientId, settings, isLiveView, editState, isLockedByManager, broadcastMessage, liveCounter])

  useEffect(() => {
    const handleSync = (e) => {
      const d = e.detail || {}
      const { type, client_id, user_id: remoteUserId, tabs: remoteTabs, active_tab_id: remoteActiveTabId, timestamp: remoteTimestamp } = d

      // 1. pos.cart_sync handling
      if (type === 'pos.cart_sync' && client_id !== clientId) {
        logger.info('[SALES] Received cart sync event:', { client_id, isLiveView, activeCashierClientId, counter: d.counter, is_live_view: d.is_live_view, tabs: remoteTabs })
        if (isLiveView) {
          const isTargetCounter = (client_id === activeCashierClientId) || (d.counter && d.counter === liveCounter)
          if (isTargetCounter) {
            setIsRemoteCartLoading(false)
            if (Array.isArray(remoteTabs) && remoteTabs.length > 0) {
              setTabs(remoteTabs)
            }
            if (remoteActiveTabId) {
              setActiveTabId(remoteActiveTabId)
            }
          }
          return
        }

        if (isLockedByManager && (client_id === managerClientId || d.is_live_view)) {
          if (Array.isArray(remoteTabs) && remoteTabs.length > 0) {
            setTabs(remoteTabs)
          }
          if (remoteActiveTabId) {
            setActiveTabId(remoteActiveTabId)
          }
          return
        }

        // Standard cashier-to-cashier sync check
        const currentUserId = user?.user_id || user?.id
        if (remoteUserId && String(remoteUserId) !== String(currentUserId)) {
          return
        }

        if (!POS_CROSS_DEVICE_CART_SYNC) return

        const isSalesSyncEnabled = settings?.general?.realtime_sync_sales !== false
        if (!isSalesSyncEnabled) return

        const uid = user?.user_id || user?.id
        if (!uid) return

        const localTimestamp = parseInt(localStorage.getItem(`pos_cart_updated_at_${uid}`) || '0', 10)
        if (remoteTimestamp && remoteTimestamp > localTimestamp) {
          if (!cartHasItems(remoteTabs) && cartHasItems(tabsRef.current)) return

          lastIncomingSyncRef.current = {
            tabs: remoteTabs,
            activeTabId: remoteActiveTabId,
            timestamp: remoteTimestamp
          }
          localStorage.setItem(`pos_cart_updated_at_${uid}`, remoteTimestamp.toString())
          
          if (Array.isArray(remoteTabs) && remoteTabs.length > 0) {
            setTabs(remoteTabs)
          }
          if (remoteActiveTabId) {
            setActiveTabId(remoteActiveTabId)
          }
        }
      }

      // 2. Remote control handshake logic
      if (type === 'pos.request_cart' && d.target_client_id === clientId) {
        logger.info('[SALES] Received initial cart request from manager:', d.requester_client_id)
        broadcastMessage({
          type: 'pos.cart_sync',
          client_id: clientId,
          user_id: user?.user_id || user?.id,
          tabs: tabsRef.current || tabs,
          active_tab_id: activeTabId,
          timestamp: Date.now()
        })
      }

      if (type === 'pos.request_edit' && d.target_client_id === clientId) {
        logger.info('[SALES] Manager requesting edit access:', d.requester_username)
        setManagerClientId(d.requester_client_id)
        setManagerUsername(d.requester_username)
        setShowRemoteRequestModal(true)
      }

      if (type === 'pos.grant_edit' && d.target_client_id === clientId) {
        logger.info('[SALES] Edit access granted by cashier!')
        setEditState('granted')
      }

      if (type === 'pos.deny_edit' && d.target_client_id === clientId) {
        logger.info('[SALES] Edit access denied by cashier.')
        setEditState('denied')
      }

      if (type === 'pos.release_edit' && d.target_client_id === clientId) {
        logger.info('[SALES] Manager released edit access.')
        setIsLockedByManager(false)
        setAlert({ type: 'success', message: 'Manager released control of this terminal.' })
      }
    }

    window.addEventListener('sync-event', handleSync)
    return () => window.removeEventListener('sync-event', handleSync)
  }, [clientId, settings, user?.user_id, user?.id, isLiveView, activeCashierClientId, isLockedByManager, managerClientId, activeTabId, broadcastMessage])

  useEffect(() => {
    if (isLiveView && activeCashierClientId) {
      setConnectionStatus('connecting')
      const requestCart = () => {
        logger.info('[SALES] Requesting initial cart state from cashier:', activeCashierClientId)
        broadcastMessage({
          type: 'pos.request_cart',
          target_client_id: activeCashierClientId,
          requester_client_id: clientId,
        })
      }
      requestCart()
      // Retry once after 2.5 seconds if no cart received (fallback if network transient)
      const retryTimer = setTimeout(requestCart, 2500)
      
      // Set timeout warning after 8 seconds
      const timeoutTimer = setTimeout(() => {
        setConnectionStatus(prev => prev === 'connecting' ? 'timeout' : prev)
      }, 8000)

      return () => {
        clearTimeout(retryTimer)
        clearTimeout(timeoutTimer)
      }
    }
  }, [isLiveView, activeCashierClientId, clientId, broadcastMessage])

  useEffect(() => {
    const handlePresence = (e) => {
      const d = e.detail
      if (!d || d.type !== 'pos.presence' || !d.client_id || !d.counter) return
      setActiveSessions(prev => ({
        ...prev,
        [d.counter]: { client_id: d.client_id, username: d.username }
      }))
    }
    window.addEventListener('sync-event', handlePresence)
    return () => window.removeEventListener('sync-event', handlePresence)
  }, [])

  useEffect(() => {
    if (isLiveView) {
      const session = activeSessions[liveCounter]
      if (session && session.client_id !== liveClientId) {
        logger.info(`[SALES] Session client ID changed for counter ${liveCounter} to ${session.client_id}. Updating search params.`)
        setSearchParams({ live_counter: liveCounter, client_id: session.client_id })
        setConnectionStatus('connecting')
      } else if (!session && !liveClientId) {
        setConnectionStatus('offline')
      }
    }
  }, [isLiveView, liveCounter, liveClientId, activeSessions, setSearchParams])

  const handleSelectCounter = useCallback((val) => {
    if (!isOwner) return
    const ownerPrefix = (user?.counter_prefix || '').trim() || 'OW'
    if (val === ownerPrefix) {
      logger.info('[SALES] Owner switching back to own counter (exiting live counter view)')
      navigate('/sales')
    } else {
      const session = activeSessions[val]
      if (session) {
        logger.info(`[SALES] Owner selecting counter ${val} (client: ${session.client_id}) — entering live view`)
        navigate(`/live-view?live_counter=${encodeURIComponent(val)}&client_id=${encodeURIComponent(session.client_id)}`)
      } else {
        logger.info(`[SALES] Owner selecting counter ${val} (no active session) — entering live view`)
        navigate(`/live-view?live_counter=${encodeURIComponent(val)}`)
      }
    }
  }, [isOwner, user?.counter_prefix, activeSessions, navigate])



  useEffect(() => {
    setPriceSelectorIndex(null)
    setSelectedPriceOptIndex(0)
  }, [activeTabId])

  // This LOGIN's invoice-number prefix (multi-terminal POS §9.3a/§9.3b).
  // - Counter token: staff-assigned `user.counter_prefix` (owner defaults 'OW',
  //   cashier fallback 'INV') — drives the per-login series so two logins differ.
  // - Mode/instance namespace (§9.3b): CLOUD is the clean source-of-truth series
  //   (`C1-0001`); a LOCAL/hybrid device tags its series `LCL-` (`LCL-C1-0001`)
  //   so its numbers can NEVER collide with the cloud series when they migrate /
  //   sync up. The number is final at issue time — never re-numbered (GST-safe).
  const getCounterPrefix = useCallback(() => {
    // BILLING prefix is ALWAYS this login's OWN counter. The owner's counter
    // dropdown is VIEW-only — picking a counter opens the Live Counters page
    // (read-only), it never changes the billing series. Billing as another active
    // counter would mint a duplicate number; editing another counter's bills is
    // the future Phase 4 request→approve (soft-lock) flow.
    const raw = (user?.counter_prefix || '').trim()
    const counter = raw
      ? (raw.endsWith('-') ? raw.slice(0, -1) : raw)
      : ((user?.role || '').toLowerCase() !== 'cashier' ? 'OW' : 'INV')
    // Use the EFFECTIVE mode (same source as config.js / realtime), NOT
    // settings.general.hosting_mode. That setting is null until the (slow) /settings
    // fetch returns, so on web/cloud it briefly defaulted to 'local' → an `LCL-`
    // FLASH on cloud bills. Web is ALWAYS cloud; desktop uses its own mode choice.
    const mode = effectiveHostingMode()
    const tag = mode === 'cloud' ? '' : 'LCL-'
    return `${tag}${counter}-`
  }, [user?.counter_prefix, user?.role])

  const availableCounters = useMemo(() => {
    if ((user?.role || '').toLowerCase() === 'cashier') return []
    const ownerPrefix = (user?.counter_prefix || '').trim() || 'OW'
    const tag = effectiveHostingMode() === 'cloud' ? '' : 'LCL-'
    const mode = effectiveHostingMode()
    if (mode !== 'cloud') {
      return [{
        label: `${tag}${ownerPrefix}`,
        value: ownerPrefix
      }]
    }
    const prefixes = [ownerPrefix]
    staffList.forEach(s => {
      if ((s.role || '').toLowerCase() === 'cashier') {
        const p = (s.counter_prefix || '').trim()
        if (p && !prefixes.includes(p)) {
          prefixes.push(p)
        }
      }
    })
    return prefixes.map(p => ({
      label: `${tag}${p}`,
      value: p
    }))
  }, [user?.role, user?.counter_prefix, staffList])

  // Highest number already used WITHIN this terminal's own prefix series. We
  // must NOT mix series (the old code derived the prefix from whichever invoice
  // had the global-max number, which scrambles multi-counter numbering).
  const maxNumInSeries = (existingInvoices, prefix) => {
    let maxNum = 0
    existingInvoices.forEach(inv => {
      const invNo = inv.invoice_number || inv.invoice_no || ''
      if (invNo && invNo.startsWith(prefix)) {
        const m = invNo.slice(prefix.length).match(/(\d+)/)
        if (m) { const num = parseInt(m[1]); if (num > maxNum) maxNum = num }
      }
    })
    return maxNum
  }

  const syncTabNames = useCallback((currentTabs, existingInvoices) => {
    const prefix = getCounterPrefix()
    const nextDbVal = maxNumInSeries(existingInvoices, prefix) + 1

    const usedNumbers = new Set(existingInvoices.map(inv => inv.invoice_number || inv.invoice_no || ''))

    let currentNum = nextDbVal
    return currentTabs.map(tab => {
      const hasItems = tab.form?.items?.length > 0
      const currentTabName = tab.name
      
      if (hasItems && !usedNumbers.has(currentTabName) && currentTabName !== 'Invoice #1001' && !currentTabName.startsWith('Invoice #')) {
        usedNumbers.add(currentTabName)
        return tab
      } else {
        let candidate = `${prefix}${String(currentNum).padStart(4, '0')}`
        while (usedNumbers.has(candidate)) {
          currentNum++
          candidate = `${prefix}${String(currentNum).padStart(4, '0')}`
        }
        usedNumbers.add(candidate)
        currentNum++
        return { ...tab, name: candidate }
      }
    })
  }, [getCounterPrefix])

  const handleToggleColumnSetting = async (key, val) => {
    if (!settings) return
    const updated = {
      ...settings,
      transactions: {
        ...settings.transactions,
        [key]: val
      }
    }
    setSettings(updated)
    try {
      await authFetch('/settings', {
        method: 'PUT',
        body: JSON.stringify(updated)
      })
    } catch (err) {
      logger.error('[SALES] failed to save settings', err)
    }
  }



  useEffect(() => {
    const targetUid = user?.user_id || user?.id
    if (targetUid) {
      localStorage.removeItem(`pos_minimized_${targetUid}`)
      window.dispatchEvent(new Event('pos_minimized_changed'))
    }
  }, [user?.user_id, user?.id])
  
  const [productBatches, setProductBatches] = useState({})
  
  const upiVpa = profile?.phone ? `${profile.phone}@upi` : 'bizassist@upi'
  const [merchantState, setMerchantState] = useState(() => localStorage.getItem('pos_merchant_state') || '37')

  const barcodeRef = useRef(null)
  const tableContainerRef = useRef(null)

  // Focus handling is managed directly in openPaymentFlow

  // Dynamic empty row count — fills the visible table area
  const [emptyRowCount, setEmptyRowCount] = useState(12)
  useEffect(() => {
    const el = tableContainerRef.current
    if (!el) return
    const ROW_H = 35
    const HEAD_H = 37
    const update = () => {
      const used = HEAD_H + form.items.length * ROW_H
      const extra = Math.max(3, Math.floor((el.clientHeight - used) / ROW_H))
      setEmptyRowCount(extra)
    }
    update()
    const ro = new ResizeObserver(update)
    ro.observe(el)
    return () => ro.disconnect()
  }, [form.items.length])

  const getNextInvoiceNo = useCallback((existingInvoices) => {
    const prefix = getCounterPrefix()
    const nextVal = maxNumInSeries(existingInvoices, prefix) + 1
    return `${prefix}${String(nextVal).padStart(4, '0')}`
  }, [getCounterPrefix])

  /**
   * matchesKey — checks if a keyboard event matches a configurable key descriptor.
   * Descriptors can be plain keys like "Enter", "F5", "Escape",
   * or modifier combos like "Shift+Enter", "Shift+F5", "Ctrl+Enter".
   */
  const matchesKey = (e, descriptor) => {
    if (!descriptor) return false
    const parts = descriptor.split('+')
    const key = parts[parts.length - 1]          // last segment is the actual key
    const wantsShift = parts.includes('Shift')
    const wantsCtrl  = parts.includes('Ctrl')
    const wantsAlt   = parts.includes('Alt')
    return (
      e.key === key &&
      e.shiftKey === wantsShift &&
      e.ctrlKey  === wantsCtrl  &&
      e.altKey   === wantsAlt
    )
  }

  // ============================================================================
  // ── 9. ON-MOUNT DATA INITIALIZERS ──
  // ============================================================================
  const load = useCallback(() => {
    isSystemLoadingRef.current = true
    setLoading(true)
    Promise.all([
      authFetch('/billing/customers').then(r => r.ok ? r.json() : []).catch(() => []),
      authFetch('/products?per_page=1000').then(r => r.ok ? r.json() : { items: [] }).catch(() => ({ items: [] })),
      authFetch('/billing/godowns').then(r => r.ok ? r.json() : []).catch(() => []),
      authFetch('/settings').then(r => r.ok ? r.json() : null).catch(() => null),
      authFetch('/billing/invoices').then(r => r.ok ? r.json() : []).catch(() => []),
      ((user?.role || '').toLowerCase() !== 'cashier')
        ? authFetch('/staff').then(r => r.ok ? r.json() : []).catch(() => [])
        : Promise.resolve([]),
    ]).then(([cust, prod, gods, sett, invs, staff]) => {
      const custItems = Array.isArray(cust) ? cust : (cust && Array.isArray(cust.items) ? cust.items : [])
      const prodItems = prod && Array.isArray(prod.items) ? prod.items : []
      setCustomers(custItems)
      setProducts(prodItems)
      setGodowns(gods)
      setDbInvoices(invs)
      setStaffList(staff)
      if (sett) {
        setSettings(sett)
      }
      
      const defaultGodownId = gods.length > 0 ? gods[0].id : ''
      setForm(f => ({
        ...f,
        customer_id: f.customer_id || '',
        godown_id: f.godown_id || defaultGodownId
      }))

      // Dynamically rename initial tab to match database next number and resolve
      // duplicates — folding in any offline-queued bills so numbers don't collide.
      setTabs(prev => syncTabNames(prev, mergePending(invs)))
    }).finally(() => {
      setLoading(false)
      setTimeout(() => barcodeRef.current?.focus(), 100)
      setTimeout(() => {
        isSystemLoadingRef.current = false
      }, 500)
    })
  }, [authFetch, setForm, getNextInvoiceNo, user?.role])

  const settingsRef = useRef(settings)
  useEffect(() => {
    settingsRef.current = settings
  }, [settings])

  useEffect(() => {
    load()
    const handleSync = (e) => {
      const currentSettings = settingsRef.current
      const isSalesSyncEnabled = currentSettings?.general?.realtime_sync_sales !== false
      if (!isSalesSyncEnabled) return
      logger.debug('[SALES] Real-time sync event received:', e.detail)
      if (['invoice', 'product', 'party'].includes(e.detail.entity)) {
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

  // Flush the offline outbox whenever we (re)connect, then refresh the server
  // list + the "unsynced" badge. flushOutbox is a no-op while offline.
  useEffect(() => {
    refreshPendingSync()
    const syncNow = async () => {
      try {
        const summary = await syncManager.flushOutbox()
        if (summary && summary.sent) {
          const invs = await authFetch('/billing/invoices').then(r => r.ok ? r.json() : null).catch(() => null)
          if (invs) {
            setDbInvoices(invs)
            isSystemLoadingRef.current = true
            setTabs(prev => syncTabNames(prev, mergePending(invs)))
            setTimeout(() => {
              isSystemLoadingRef.current = false
            }, 500)
          }
        }
      } finally {
        refreshPendingSync()
      }
    }
    const onOnline = () => { syncNow() }
    window.addEventListener('online', onOnline)
    if (typeof navigator === 'undefined' || navigator.onLine !== false) syncNow()
    return () => window.removeEventListener('online', onOnline)
  }, [authFetch, syncTabNames, mergePending, refreshPendingSync])

  // Listen for window focus to reload batches/dated prices for all items in the cart
  useEffect(() => {
    const handleFocusRefresh = async () => {
      if (form.items && form.items.length > 0) {
        for (const item of form.items) {
          if (item.product_id && !item.is_custom) {
            try {
              const res = await authFetch(`/products/${item.product_id}/stock`)
              if (res.ok) {
                const data = await res.json()
                setProductBatches(prev => ({
                  ...prev,
                  [item.product_id]: data.batches || []
                }))
              }
            } catch (err) {
              logger.error('[SALES] failed to update batches on focus', err)
            }
          }
        }
      }
    }

    window.addEventListener('focus', handleFocusRefresh)
    return () => {
      window.removeEventListener('focus', handleFocusRefresh)
    }
  }, [form.items, authFetch])

  // Business-type billing profile (Phase 2): vertical line fields decide which
  // cart columns show by DEFAULT — pharmacy gets batch/expiry, electronics/
  // mobile/repair get serial — while the owner's explicit settings still win.
  // FAIL-OPEN: profile null (offline) → settings-only behavior, unchanged.
  const profileLineFields = billingProfile?.line_fields || []
  // Dynamic vertical fields beyond the native cart columns (textile size/color,
  // electronics warranty, repair job-card…) — rendered as a DETAILS column and
  // packed into each line's `attributes` JSON blob on save.
  const NATIVE_LINE_FIELDS = ['batch_no', 'expiry_date', 'serial_no', 'mrp', 'sac']
  const extraAttrFields = profileLineFields.filter(f => !NATIVE_LINE_FIELDS.includes(f))
  const colVisible = {
    attrs: extraAttrFields.length > 0,
    sku: settings?.transactions?.pos_show_sku !== false,
    unit: settings?.transactions?.pos_show_unit !== false,
    discount: settings?.transactions?.pos_show_discount !== false,
    tax: settings?.transactions?.pos_show_tax !== false,
    hsn: settings?.transactions?.pos_show_hsn === true,
    mrp: settings?.transactions?.pos_show_mrp === true
         || (settings?.transactions?.pos_show_mrp !== false && profileLineFields.includes('mrp')),
    batch: settings?.transactions?.pos_show_batch !== false,
    serial: settings?.transactions?.pos_show_serial === true
            || (settings?.transactions?.pos_show_serial !== false && profileLineFields.includes('serial_no')),
    price_option: true,
    rate: true
  }

  const handleNewBill = () => {
    if (isLiveView && editState !== 'granted') return
    const newId = Date.now().toString()
    const newForm = {
      ...defaultForm,
      customer_id: '',
      godown_id: godowns.length > 0 ? godowns[0].id : '',
      due_date: getTodayDateStr(),
    }
    setTabs(prev => {
      const updated = [...prev, { id: newId, name: 'TEMP', form: newForm }]
      return syncTabNames(updated, mergePending(dbInvoices))
    })
    setActiveTabId(newId)
    setPriceSelectorIndex(null)
    setSelectedPriceOptIndex(0)
    setTimeout(() => barcodeRef.current?.focus(), 100)
  }

  // ============================================================================
  // ── 10. TABS & CARTS MUTATORS ──
  // ============================================================================
  const closeTab = useCallback((tabId, e, forceClose = false) => {
    if (e) e.stopPropagation()
    if (isLiveView && editState !== 'granted') return
    const tabToClose = tabs.find(t => t.id === tabId)
    if (!forceClose && tabToClose && tabToClose.form.items.length > 0) {
      if (!window.confirm(`Are you sure you want to close ${tabToClose.name}? Unsaved changes will be lost.`)) {
        return
      }
    }
    
    setPriceSelectorIndex(null)
    setSelectedPriceOptIndex(0)

    if (tabs.length === 1) {
      const newId = Date.now().toString()
      const newForm = {
        ...defaultForm,
        customer_id: '',
        godown_id: godowns.length > 0 ? godowns[0].id : '',
        due_date: getTodayDateStr(),
      }
      setTabs([{ id: newId, name: 'TEMP', form: newForm }])
      setActiveTabId(newId)
      isSystemLoadingRef.current = true
      authFetch('/billing/invoices').then(r => r.ok ? r.json() : []).then(invs => {
        setDbInvoices(invs)
        setTabs(prev => syncTabNames(prev, mergePending(invs)))
      }).catch(() => {
        // Offline — keep last-known server list + queued bills for numbering.
        setTabs(prev => syncTabNames(prev, mergePending(dbInvoices)))
      }).finally(() => {
        setTimeout(() => {
          isSystemLoadingRef.current = false
        }, 500)
      })
      setTimeout(() => barcodeRef.current?.focus(), 100)
      return
    }

    const newTabs = tabs.filter(t => t.id !== tabId)
    setTabs(newTabs)
    if (activeTabId === tabId) {
      const remainingTab = newTabs[newTabs.length - 1]
      setActiveTabId(remainingTab.id)
    }
  }, [tabs, activeTabId, godowns, authFetch, syncTabNames, mergePending, dbInvoices])

  const handleMinimize = () => {
    const targetUid = user?.user_id || user?.id
    if (targetUid) {
      if (isLiveView) {
        localStorage.setItem(`pos_live_minimized_${targetUid}`, 'true')
        localStorage.setItem(`pos_live_minimized_counter_${targetUid}`, liveCounter || '')
        localStorage.setItem(`pos_live_minimized_client_id_${targetUid}`, activeCashierClientId || '')
        localStorage.setItem(`pos_live_minimized_tabs_${targetUid}`, JSON.stringify(tabs))
        localStorage.setItem(`pos_live_minimized_active_id_${targetUid}`, activeTabId)
      } else {
        localStorage.setItem(`pos_minimized_${targetUid}`, 'true')
      }
      window.dispatchEvent(new Event('pos_minimized_changed'))
    }
    const lastPage = sessionStorage.getItem('last_page') || '/'
    navigate(lastPage)
  }


  
  useEffect(() => {
    if (!form.customer_id || customers.length === 0) return
    const cust = customers.find(c => String(c.id) === String(form.customer_id))
    if (cust) {
      setField('gst_enabled', !!cust.gstin)
      
      const tier = cust.price_tier || 'standard'
      setForm(f => {
        const items = f.items.map(it => {
          if (it.is_custom || it.has_custom_price) return it
          const prod = products.find(p => p.id === it.product_id)
          if (!prod) return it
          let basePrice = prod.selling_price || 0
          if (tier === 'wholesale') {
            basePrice = prod.wholesale_price || basePrice
          } else if (tier === 'distributor') {
            basePrice = prod.distributor_price || basePrice
          }
          
          let finalPrice = basePrice
          let finalDiscount = 0
          if (prod.mrp && parseFloat(prod.mrp) > 0 && basePrice <= parseFloat(prod.mrp)) {
            finalPrice = parseFloat(prod.mrp)
            finalDiscount = finalPrice - basePrice
          }
          
          return { ...it, price: finalPrice, discount: finalDiscount }
        })
        return { ...f, items }
      })
    }
  }, [form.customer_id, customers, products])

  const setField = (k, v) => {
    if (isLiveView && editState !== 'granted') return
    setForm(f => ({ ...f, [k]: v }))
  }
  
  const setItem = (i, kOrUpdates, v) => {
    if (isLiveView && editState !== 'granted') return
    setForm(f => {
      const items = [...f.items]
      const item = items[i]
      if (item) {
        const updates = typeof kOrUpdates === 'object' ? kOrUpdates : { [kOrUpdates]: v }
        const updatedItem = { ...item, ...updates }
        
        const qty = parseFloat(updatedItem.qty) || 0
        const mrpFieldVal = parseFloat(updatedItem.price) || 0
        const selPrice = parseFloat(updatedItem.selected_price) || 0
        const p = products.find(prod => prod.id === updatedItem.product_id)
        const mrp = p ? (parseFloat(p.mrp) || 0) : mrpFieldVal
        
        if (updatedItem.product_id) {
          if (mrp > 0 && selPrice <= mrp) {
            updatedItem.price = mrp
            updatedItem.discount = schemeDiscount(mrp, selPrice, qty)
          } else {
            updatedItem.price = selPrice
            updatedItem.discount = 0
          }
        } else {
          if ('selected_price' in updates) {
            updatedItem.price = parseFloat(updatedItem.selected_price) || 0
          }
        }
        
        items[i] = updatedItem
      }
      return { ...f, items }
    })
  }
  
  const addCustomItemToCart = useCallback(() => {
    if (isLiveView && editState !== 'granted') return
    setForm(f => {
      let items = [...f.items]
      items.push({
        product_id: '',
        product: '',
        price: '',
        sku: '—',
        discount: 0,
        qty: 1,
        is_custom: true,
        batch_no: '',
        expiry_date: '',
        serial_no: '',
        attributes: {},
        selected_price: '',
        selected_price_label: 'Standard Price'
      })
      return { ...f, items }
    })
    setSearchQuery('')
    setSelectedIndex(-1)
  }, [isLiveView, editState])

  const removeItem = (i) => {
    if (isLiveView && editState !== 'granted') return
    setForm(f => ({ ...f, items: f.items.filter((_, idx) => idx !== i) }))
    setPriceSelectorIndex(null)
    setSelectedPriceOptIndex(0)
  }

  // Buyer state vs merchant state decides intra (CGST+SGST) vs inter (IGST).
  const selectedCust = customers.find(c => String(c.id) === String(form.customer_id))
  const custState = selectedCust && selectedCust.gstin ? selectedCust.gstin.trim().slice(0, 2) : ''
  const isIntrastate = custState ? custState === merchantState : true

  // Money-math is pure + unit-tested in utils/invoiceMath (lineTotal imported above).
  const { subtotal, discount: billDiscountAmt, discountedSubtotal, cgstAmt, sgstAmt, igstAmt, gstAmt, grandTotal, roundOff, cashDiscount: cashDiscountAmt, payable } =
    computeInvoiceTotals(form.items, {
      isIntrastate,
      billDiscountType: form.bill_discount_type,
      billDiscountValue: form.bill_discount_value,
      cashDiscount: parseFloat(form.cash_discount) || 0,
    })
  const colFooter = columnTotals(form.items)   // per-column totals for the cart footer row

  // Receipt header lines, rendered in the saved order + alignment (Settings → Print).
  const amountReceivedNum = parseFloat(form.amount_received) || 0
  // Change is against the PAYABLE (= grand total − cash discount). With no cash
  // discount, payable === grandTotal, so this is unchanged for existing flows.
  const changeToReturn = changeDue(amountReceivedNum, payable)

  const {
    showPaymentPopup,
    setShowPaymentPopup,
    paymentFocusTarget,
    setPaymentFocusTarget,
    openPaymentFlow,
    executeSaveInvoice,
    handleSaveInvoice,
  } = usePaymentFlow({
    form,
    setForm,
    grandTotal,
    payable,
    cashDiscountAmt,
    gstAmt,
    billDiscountAmt,
    changeToReturn,
    activeTab,
    activeTabId,
    closeTab,
    setTabs,
    syncTabNames,
    setDbInvoices,
    settings,
    authFetch,
    setAlert,
    setSubmitting,
    barcodeRef,
    enqueueOffline,
  })

  // Live Counters presence (plan §9.2 Stage 1): publish a lightweight READ-ONLY
  // snapshot (counter, item count, cart total, current bill) so the owner's Live
  // Counters view can watch this till live. Cloud only; this is NOT cart sync —
  // no cart contents are applied anywhere, just metrics. Debounced on cart edits,
  // plus a heartbeat; the consumer marks a counter idle when the heartbeat stops.
  useEffect(() => {
    if (effectiveHostingMode() !== 'cloud') return
    if (settingsRef.current?.general?.realtime_sync_sales === false) return
    const counter = getCounterPrefix().replace(/-$/, '')
    const items = (form?.items || []).filter(it => it.product)
    const publish = () => {
      authFetch('/realtime/presence', {
        method: 'POST',
        body: JSON.stringify({
          client_id: clientId,
          counter,
          item_count: items.length,
          cart_total: grandTotal || 0,
          active_bill: activeTab?.name || null,
          status: 'active',
          timestamp: Date.now(),
        }),
      }).catch(() => {})
    }
    const t = setTimeout(publish, 600)        // debounce rapid cart edits
    const hb = setInterval(publish, 20000)    // heartbeat while idle
    return () => { clearTimeout(t); clearInterval(hb) }
  }, [form?.items, grandTotal, activeTab?.name, clientId, getCounterPrefix, authFetch])

  // Entry mode: the RESOLVED billing profile wins (it follows the device's
  // counter-mode switcher for multi-type businesses); config is the fallback.
  const entryMode = billingProfile?.entry_mode || config?.billing?.entry_mode || 'search'
  const groupedProducts = products.reduce((acc, p) => {
    const cat = p.category || 'General';
    if (!acc[cat]) acc[cat] = [];
    acc[cat].push(p);
    return acc;
  }, {})

  const fetchBatchesForProduct = useCallback(async (productId) => {
    if (!productId || productBatches[productId]) return
    try {
      const res = await authFetch(`/products/${productId}/stock`)
      if (res.ok) {
        const data = await res.json()
        setProductBatches(prev => ({
          ...prev,
          [productId]: data.batches || []
        }))
      }
    } catch (err) {
      logger.error('[SALES] failed to fetch batches', err)
    }
  }, [authFetch, productBatches])

  const addProductToCart = useCallback(async (product) => {
    if (isLiveView && editState !== 'granted') return
    // 1. Fetch batches to get the latest stock/price options
    let batches = null
    if (product.id) {
      try {
        const res = await authFetch(`/products/${product.id}/stock`)
        if (res.ok) {
          const data = await res.json()
          batches = data.batches || []
          setProductBatches(prev => ({ ...prev, [product.id]: batches }))
        }
      } catch (err) {
        logger.error('[SALES] batch fetch failed', err)
      }
    }

    // Determine if the product is already in the cart
    const isAlreadyPresent = form.items.some(it => it.product_id === product.id)

    // Resolve default price tier based on customer tier OR profile category type
    let resolvedTier = 'standard'
    setForm(f => {
      const cust = customers.find(c => String(c.id) === String(f.customer_id))
      let tier = cust ? (cust.price_tier || 'standard') : 'standard'
      
      if (tier === 'standard') {
        let businessDefaultTier = 'standard'
        const bizCategory = (profile?.business_category || profile?.business_type || profile?.category || '').toLowerCase()
        const savedUser = localStorage.getItem('billing_user')
        let userRole = ''
        if (savedUser) {
          try {
            userRole = (JSON.parse(savedUser).role || '').toLowerCase()
          } catch (e) {
            logger.debug('[SALES] could not parse billing_user for price tier; defaulting role to ""', e)
          }
        }
        if (bizCategory.includes('wholesale') || userRole.includes('wholesale')) {
          businessDefaultTier = 'wholesale'
        } else if (bizCategory.includes('distributor') || userRole.includes('distributor')) {
          businessDefaultTier = 'distributor'
        }
        tier = businessDefaultTier
      }
      resolvedTier = tier
      return f
    })

    const defaultPrice = (() => {
      let price = product.selling_price || 0
      if (resolvedTier === 'wholesale') {
        price = product.wholesale_price || price
      } else if (resolvedTier === 'distributor') {
        price = product.distributor_price || price
      }
      return price
    })()

    setForm(f => {
      let items = [...f.items]
      const existingIdx = items.findIndex(it => it.product_id === product.id)
      if (existingIdx !== -1) {
        items[existingIdx] = {
          ...items[existingIdx],
          qty: (parseFloat(items[existingIdx].qty) || 0) + 1,
          price: items[existingIdx].price, // preserve already selected price
          cgst_rate: product.cgst_rate || 0,
          sgst_rate: product.sgst_rate || 0,
          igst_rate: product.igst_rate || 0,
        }
        const updatedItem = items[existingIdx]
        const qty = updatedItem.qty
        const selPrice = parseFloat(updatedItem.selected_price) || 0
        const mrp = parseFloat(product.mrp) || 0
        if (mrp > 0 && selPrice <= mrp) {
          updatedItem.discount = schemeDiscount(mrp, selPrice, qty)
        }
      } else {
        let finalPrice = defaultPrice
        let finalDiscount = 0
        if (product.mrp && parseFloat(product.mrp) > 0 && defaultPrice <= parseFloat(product.mrp)) {
          finalPrice = parseFloat(product.mrp)
          finalDiscount = schemeDiscount(product.mrp, defaultPrice, 1)
        }
        items.push({
          product_id: product.id,
          product: product.name,
          price: finalPrice,
          sku: product.sku || product.barcode || '—',
          discount: finalDiscount,
          qty: 1,
          is_custom: false,
          batch_no: '',
          expiry_date: '',
          serial_no: '',
          attributes: {},
          cgst_rate: product.cgst_rate || 0,
          sgst_rate: product.sgst_rate || 0,
          igst_rate: product.igst_rate || 0,
          selected_price: defaultPrice,
          selected_price_label: resolvedTier === 'wholesale' ? 'Wholesale Price' :
                                resolvedTier === 'distributor' ? 'Distributor Price' :
                                'Standard Price'
        })
      }
      return { ...f, items }
    })
    
    setSearchQuery('')
    setSelectedIndex(-1)
    
    // Check if there are extra prices apart from standard 4 base prices
    const standardBasePrices = [
      parseFloat(product.selling_price),
      parseFloat(product.wholesale_price),
      parseFloat(product.distributor_price),
      parseFloat(product.mrp)
    ].filter(v => v && v > 0)

    const rawOptions = [
      { label: 'Standard Price', price: product.selling_price },
      { label: 'Wholesale Price', price: product.wholesale_price },
      { label: 'Distributor Price', price: product.distributor_price },
      { label: 'MRP', price: product.mrp }
    ]
    if (batches) {
      batches.forEach(b => {
        if (b.selling_price && b.selling_price > 0) {
          rawOptions.push({ label: `Batch ${b.batch_no || '—'} Price`, price: b.selling_price })
        }
        if (b.mrp && b.mrp > 0) {
          rawOptions.push({ label: `Batch ${b.batch_no || '—'} MRP`, price: b.mrp })
        }
      })
    }
    const seen = new Set()
    const options = []
    rawOptions.forEach(opt => {
      const val = parseFloat(opt.price)
      if (val && val > 0 && !seen.has(val)) {
        seen.add(val)
        options.push({ label: opt.label, price: val })
      }
    })

    const hasNonStandardPrices = options.some(opt => {
      const pVal = parseFloat(opt.price)
      return !standardBasePrices.includes(pVal)
    })

    const shouldShowSelector = hasNonStandardPrices && !isAlreadyPresent

    if (shouldShowSelector) {
      setForm(f => {
        const targetIdx = f.items.findIndex(it => it.product_id === product.id)
        if (targetIdx !== -1) {
          setPriceSelectorIndex(targetIdx)
          setSelectedPriceOptIndex(0)
        }
        return f
      })
    } else {
      setPriceSelectorIndex(null)
      setSelectedPriceOptIndex(0)
      setTimeout(() => barcodeRef.current?.focus(), 50)
    }
  }, [customers, fetchBatchesForProduct, productBatches, authFetch, profile])

  const handleSelectProduct = useCallback((product) => {
    addProductToCart(product)
  }, [addProductToCart])

  const handleSearchKeyDown = (e) => {
    if (priceSelectorIndex !== null) {
      const options = getPriceOptions(form.items[priceSelectorIndex])
      if (e.key === 'ArrowLeft' || e.key === 'ArrowUp') {
        e.preventDefault()
        e.stopPropagation()
        setSelectedPriceOptIndex(prev => Math.max(0, prev - 1))
        return
      }
      if (e.key === 'ArrowRight' || e.key === 'ArrowDown') {
        e.preventDefault()
        e.stopPropagation()
        setSelectedPriceOptIndex(prev => Math.min(options.length - 1, prev + 1))
        return
      }
      if (e.key === 'Enter' || e.key === 'Escape') {
        e.preventDefault()
        e.stopPropagation()
        const opt = options[selectedPriceOptIndex] || options[0]
        if (opt) {
          handleSelectPriceOption(opt.price, opt.label)
        } else {
          setPriceSelectorIndex(null)
          setTimeout(() => barcodeRef.current?.focus(), 50)
        }
        return
      }
    }

    if (!searchQuery.trim()) {
      if (e.key === 'ArrowUp' || e.key === 'ArrowDown') {
        e.preventDefault()
        setForm(f => {
          if (f.items.length === 0) return f
          const items = [...f.items]
          const lastIdx = items.length - 1
          if (!items[lastIdx].product) return f
          const currentQty = parseFloat(items[lastIdx].qty) || 0
          const newQty = e.key === 'ArrowUp' ? currentQty + 1 : Math.max(1, currentQty - 1)
          items[lastIdx] = withQty(items[lastIdx], newQty)
          return { ...f, items }
        })
      }
      // Proceed-to-payment key (default: Esc) when barcode is empty
      if (matchesKey(e, funcKeys.proceedToPayment) || e.key === 'Escape') {
        e.preventDefault()
        e.stopPropagation()
        if (form.items.length > 0) {
          openPaymentFlow('customer')
        }
        return
      }
      // Enter on empty barcode with items in cart → open payment popup
      if (e.key === 'Enter') {
        e.preventDefault()
        if (form.items.length > 0) {
          openPaymentFlow('customer')
        }
        return
      }
      return
    }

    if (e.key === 'ArrowDown') {
      e.preventDefault()
      setSelectedIndex(prev => Math.min(filteredProducts.length - 1, prev + 1))
    } else if (e.key === 'ArrowUp') {
      e.preventDefault()
      setSelectedIndex(prev => Math.max(-1, prev - 1))
    } else if (e.key === 'Enter') {
      e.preventDefault()
      if (selectedIndex !== -1 && filteredProducts[selectedIndex]) {
        addProductToCart(filteredProducts[selectedIndex])
      } else if (searchQuery.trim()) {
        const code = searchQuery.trim()
        const exactMatch = products.find(p => p.barcode === code || (p.sku && p.sku === code))
        if (exactMatch) {
          addProductToCart(exactMatch)
        } else if (filteredProducts.length > 0) {
          addProductToCart(filteredProducts[0])
        } else {
          addCustomItemToCart()
          setForm(f => {
            const items = [...f.items]
            if (items.length > 0) {
              items[items.length - 1].product = code
            }
            return { ...f, items }
          })
        }
      }
    } else if (e.key === 'Escape') {
      // If text in search → clear it (stay focused for user to try again or click Custom Item)
      e.preventDefault()
      setSearchQuery('')
      setSelectedIndex(-1)
    }
  }



  // usePaymentFlow hook now provides handleSaveInvoice, openPaymentFlow, and executeSaveInvoice




  const handleClear = () => {
    if (form.items.length > 0) {
      if (!window.confirm('Reset current bill fields? Unsaved changes will be lost.')) return
    }
    setForm({
      ...defaultForm,
      customer_id: '',
      godown_id: godowns.length > 0 ? godowns[0].id : '',
      due_date: getTodayDateStr(),
    })
    setPriceSelectorIndex(null)
    setSelectedPriceOptIndex(0)
    setAlert(null)
    setSearchQuery('')
    setTimeout(() => barcodeRef.current?.focus(), 100)
  }

  // Accidental exit prevention handler
  const handleCloseConfirm = useCallback(() => {
    const lastPage = sessionStorage.getItem('last_page') || '/'
    if (form.items.length > 0) {
      if (window.confirm('Are you sure you want to close this bill? Unsaved changes will be lost.')) {
        navigate(lastPage)
      }
    } else {
      navigate(lastPage)
    }
  }, [form.items, navigate])

  // Helper selectors to focus cells for hotkeys
  const focusLastQty = () => {
    const inputs = document.querySelectorAll('.pos-cart-table tbody tr input.qty-input')
    if (inputs.length > 0) {
      inputs[inputs.length - 1].focus()
    }
  }

  const focusLastDiscount = () => {
    const inputs = document.querySelectorAll('.pos-cart-table tbody tr input.discount-input')
    if (inputs.length > 0) {
      inputs[inputs.length - 1].focus()
    }
  }

  const removeLastItem = () => {
    if (form.items.length > 0) {
      removeItem(form.items.length - 1)
    }
  }

  const focusNotes = () => {
    const el = document.querySelector('.pos-form-section textarea')
    el?.focus()
  }

  // ============================================================================
  // ── 11. KEYBOARD SHORTCUTS & SCANNER LISTENERS ──
  // ============================================================================
  // Keyboard POS Shortcuts
  useEffect(() => {
    const handleKeyDown = (e) => {
      if ((isLiveView && editState !== 'granted') || isLockedByManager) {
        if (e.key !== 'Escape') {
          return
        }
      }
      // If we are currently binding a key, capture the key press
      if (bindingAction) {
        e.preventDefault()
        e.stopPropagation()
        const pressedKey = e.key
        if (pressedKey !== 'Escape') {
          let keyToSave = pressedKey
          if (pressedKey.length === 1) {
            keyToSave = pressedKey.toUpperCase()
          }
          const nextKeys = { ...funcKeys, [bindingAction]: keyToSave }
          setFuncKeys(nextKeys)
          localStorage.setItem('pos_func_keys', JSON.stringify(nextKeys))
        }
        setBindingAction(null)
        return
      }

      // If price selector is active, prioritize price selector navigation keys
      if (priceSelectorIndex !== null) {
        const item = form.items[priceSelectorIndex]
        const options = getPriceOptions(item)
        if (e.key === 'ArrowLeft' || e.key === 'ArrowUp') {
          e.preventDefault()
          setSelectedPriceOptIndex(prev => Math.max(0, prev - 1))
          return
        }
        if (e.key === 'ArrowRight' || e.key === 'ArrowDown') {
          e.preventDefault()
          setSelectedPriceOptIndex(prev => Math.min(options.length - 1, prev + 1))
          return
        }
        if (e.key === 'Enter' || e.key === 'Escape') {
          e.preventDefault()
          const opt = options[selectedPriceOptIndex] || options[0]
          if (opt) {
            handleSelectPriceOption(opt.price, opt.label)
          } else {
            setPriceSelectorIndex(null)
            setTimeout(() => barcodeRef.current?.focus(), 50)
          }
          return
        }
        return
      }

      if (showSettingsModal || showBreakupModal) return

      if (showPaymentPopup) {
        return
      }

      // New Bill (Ctrl+T)
      if (e.ctrlKey && e.key.toLowerCase() === 't') {
        e.preventDefault()
        handleNewBill()
      }

      // Close Bill Tab (Ctrl+W)
      if (e.ctrlKey && e.key.toLowerCase() === 'w') {
        e.preventDefault()
        closeTab(activeTabId)
      }

      // Save & Print Bill (Ctrl+P / F10)
      if ((e.ctrlKey && e.key.toLowerCase() === 'p') || e.key === 'F10') {
        e.preventDefault()
        handleSaveInvoice(true)
      }

      // Save Bill Only (Ctrl+S)
      if (e.ctrlKey && e.key.toLowerCase() === 's') {
        e.preventDefault()
        handleSaveInvoice(false)
      }

      // Other/Credit payments shortcut (Ctrl+M)
      if (e.ctrlKey && e.key.toLowerCase() === 'm') {
        e.preventDefault()
        setForm(f => ({ ...f, payment_mode: 'credit', amount_received: '0' }))
        openPaymentFlow('amountReceived')
      }

      // Full Breakup modal toggle (Ctrl+F)
      if (e.ctrlKey && e.key.toLowerCase() === 'f') {
        e.preventDefault()
        setShowBreakupModal(true)
      }

      // Increment last item quantity on pressing "+"
      if (e.key === '+') {
        const activeEl = document.activeElement
        const isSearchInput = activeEl === barcodeRef.current
        const isBody = activeEl === document.body || !activeEl || activeEl.tagName === 'BUTTON' || activeEl.className === 'pos-hotkey-btn'
        
        if (isSearchInput || isBody) {
          e.preventDefault()
          e.stopPropagation()
          
          setForm(f => {
            if (f.items.length === 0) return f
            const items = [...f.items]
            const lastIdx = items.length - 1
            const currentQty = parseFloat(items[lastIdx].qty) || 0
            items[lastIdx] = withQty(items[lastIdx], currentQty + 1)
            return { ...f, items }
          })
          
          // Clear any + character typed in search input
          setSearchQuery(prev => prev.replace('+', ''))
          setTimeout(() => barcodeRef.current?.focus(), 50)
          return
        }
      }

      // Check which action is mapped to e.key
      const getActionForKey = (key) => {
        return Object.keys(funcKeys).find(action => {
          const boundKey = funcKeys[action]
          if (!boundKey || !key) return false
          if (boundKey.length === 1 && key.length === 1) {
            return boundKey.toLowerCase() === key.toLowerCase()
          }
          return boundKey === key
        })
      }

      const action = getActionForKey(e.key)
      if (action) {
        e.preventDefault()
        if (action === 'qtyFocus') focusLastQty()
        else if (action === 'discountFocus') focusLastDiscount()
        else if (action === 'removeItem') removeLastItem()
        else if (action === 'amountReceivedFocus') openPaymentFlow()
        else if (action === 'barcodeFocus') barcodeRef.current?.focus()
        else if (action === 'customerFocus') openPaymentFlow('customer')
        else if (action === 'remarksFocus') openPaymentFlow('remarks')
        else if (action === 'configureShortcuts') {
          setSettingsInitialTab('shortcuts')
          setShowSettingsModal(true)
        }
      }

      // ── Universal Proceed-to-Payment (Escape / configurable) ──────────────────
      // Fires from ANYWHERE in the POS: barcode, qty cell, discount cell, etc.
      // Modals and price-selector already returned early above.
      if (matchesKey(e, funcKeys.proceedToPayment) || e.key === 'Escape') {
        const activeEl = document.activeElement
        const isInTable = activeEl && (activeEl.closest?.('table') || activeEl.classList?.contains('pos-cell-input'))
        if (isInTable) {
          e.preventDefault()
          e.stopPropagation()
          barcodeRef.current?.focus()
          return
        }

        // If we are in the barcode scanner and there is text, let the search keydown handler clear the text (don't proceed to payment)
        if (document.activeElement === barcodeRef.current && searchQuery.trim() !== '') {
          if (e.key === 'Escape') {
            return
          }
          e.preventDefault()
          e.stopPropagation()
          setSearchQuery('')
          setSelectedIndex(-1)
          return
        }



        e.preventDefault()
        e.stopPropagation()

        // Toggle to payment section
        if (searchQuery) {
          setSearchQuery('')
          setSelectedIndex(-1)
        }

        // Blur whichever cell input the user was in, then go to customer field
        document.activeElement?.blur()
        openPaymentFlow('customer')
      }
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [showSettingsModal, showBreakupModal, settingsInitialTab, showPayConfirmModal, searchQuery, handleSaveInvoice, activeTabId, closeTab, handleNewBill, funcKeys, bindingAction, priceSelectorIndex, selectedPriceOptIndex, form.items, matchesKey, showPaymentPopup, openPaymentFlow, executeSaveInvoice])

  // Auto refocus barcode input when modals close
  useEffect(() => {
    if (!showPaymentPopup && !showSettingsModal && !showBreakupModal) {
      setTimeout(() => barcodeRef.current?.focus(), 100)
    }
  }, [showPaymentPopup, showSettingsModal, showBreakupModal])

  const stickyOffsets = getStickyLeftOffsets(columnOrder, colVisible)

  const filteredProducts = searchQuery.trim()
    ? products.filter(p =>
        p.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
        (p.barcode && p.barcode.toLowerCase().includes(searchQuery.toLowerCase())) ||
        (p.sku && p.sku.toLowerCase().includes(searchQuery.toLowerCase()))
      ).slice(0, 8)
    : []

  // ============================================================================
  // ── 12. POS COUNTER RENDER (JSX) ──
  // ============================================================================
  return (
    <AppLayout title="POS Counter">
      <div style={{ height: '100%', display: 'flex', flexDirection: 'column', position: 'relative' }}>
        
        {isLiveView && isRemoteCartLoading && (
          <div style={{
            position: 'absolute',
            top: 44, // below the PosTopBar
            left: 0, right: 0, bottom: 0,
            background: 'var(--bg-1)',
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
            justifyContent: 'center',
            zIndex: 1000,
            gap: 16
          }}>
            {connectionStatus === 'connecting' && (
              <>
                <div style={{
                  width: 40, height: 40,
                  border: '3px solid rgba(255,255,255,0.08)',
                  borderTopColor: 'var(--accent)',
                  borderRadius: '50%',
                  animation: 'spin 1s linear infinite'
                }} />
                <div style={{ fontSize: '0.85rem', color: 'var(--text-secondary)' }}>
                  Connecting to Counter <strong>{liveCounter}</strong>... Fetching active cart.
                </div>
              </>
            )}

            {connectionStatus === 'offline' && (
              <>
                <div style={{ fontSize: '2rem' }}>🔌</div>
                <div style={{ fontSize: '0.9rem', fontWeight: 600, color: '#ef4444' }}>
                  Counter {liveCounter} is Offline
                </div>
                <div style={{ fontSize: '0.82rem', color: 'var(--text-muted)', maxWidth: 320, textAlign: 'center', lineHeight: 1.4 }}>
                  This counter does not have an active session. Real-time view is only available when the cashier is online.
                </div>
              </>
            )}

            {connectionStatus === 'timeout' && (
              <>
                <div style={{ fontSize: '2rem' }}>⏳</div>
                <div style={{ fontSize: '0.9rem', fontWeight: 600, color: '#f59e0b' }}>
                  Connection Timeout
                </div>
                <div style={{ fontSize: '0.82rem', color: 'var(--text-muted)', maxWidth: 320, textAlign: 'center', lineHeight: 1.4 }}>
                  No response from Counter {liveCounter}. The terminal might have closed their tab, or went to sleep/offline.
                </div>
                <button
                  type="button"
                  className="btn btn-primary"
                  onClick={() => {
                    setConnectionStatus('connecting')
                    broadcastMessage({
                      type: 'pos.request_cart',
                      target_client_id: liveClientId,
                      requester_client_id: clientId,
                    })
                  }}
                  style={{ fontSize: '0.78rem', padding: '6px 14px', background: 'var(--accent)', color: '#fff', border: 'none', borderRadius: 4, cursor: 'pointer' }}
                >
                  Retry Connection
                </button>
              </>
            )}

            <button
              type="button"
              className="btn btn-secondary"
              onClick={() => navigate('/pos-live-counter')}
              style={{ fontSize: '0.78rem', padding: '6px 14px', background: 'rgba(255,255,255,0.08)', border: '1px solid var(--border)', borderRadius: 4, cursor: 'pointer', color: 'var(--text-primary)' }}
            >
              Exit Live View
            </button>
          </div>
        )}

        {/* Tab-Style Bar */}
        <PosTopBar
          tabs={tabs}
          activeTabId={activeTabId}
          onSelectTab={setActiveTabId}
          onCloseTab={closeTab}
          onNewBill={handleNewBill}
          onMinimize={handleMinimize}
          onClose={isLiveView ? () => navigate('/pos-live-counter') : handleCloseConfirm}
          onOpenSettings={() => {
            setSettingsInitialTab('general')
            setShowSettingsModal(true)
          }}
          funcKeys={funcKeys}
          counterPrefix={isLiveView ? liveCounter : getCounterPrefix().replace(/-$/, '')}
          canManageCounters={(user?.role || '').toLowerCase() !== 'cashier'}
          onManageCounters={() => navigate('/staff')}
          availableCounters={availableCounters}
          onSelectCounter={handleSelectCounter}
          liveModeStatus={isLiveView ? { counter: liveCounter, isEditing: editState === 'granted' } : null}
        />

        {/* ── Shift status strip (Phase 3) — visible whenever a shift is open ── */}
        {!isLiveView && shift && !shift.offline && (
          <div style={{
            background: 'var(--bg-3)', borderBottom: '1px solid var(--border)',
            padding: '4px 16px', display: 'flex', alignItems: 'center',
            justifyContent: 'space-between', fontSize: '0.76rem', color: 'var(--text-muted)',
          }}>
            <span>
              <span style={{ color: '#22c55e', fontWeight: 800 }}>● Shift open</span>
              {shift.start_time && <> since {new Date(shift.start_time + (shift.start_time.endsWith('Z') ? '' : 'Z')).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</>}
              {' '}· float ₹{Number(shift.opening_cash || 0).toFixed(2)}
            </span>
            <span style={{ display: 'flex', gap: 6 }}>
              <button
                type="button"
                className="btn btn-secondary btn-sm"
                style={{ fontSize: '0.72rem', padding: '2px 10px' }}
                onClick={() => setShowCashMovementModal(true)}
              >
                Cash In / Out
              </button>
              <button
                type="button"
                className="btn btn-secondary btn-sm"
                style={{ fontSize: '0.72rem', padding: '2px 10px' }}
                onClick={async () => { await refreshShift(); setShowCloseShiftModal(true) }}
              >
                Close Register / End Shift
              </button>
            </span>
          </div>
        )}

        {/* ── Shift gatekeeper (Phase 3): no open shift → billing stays locked ── */}
        <OpenShiftModal
          open={!isLiveView && shift === null}
          authFetch={authFetch}
          operatorName={user?.username}
          onOpened={(s) => setShift(s)}
        />
        <CloseShiftModal
          open={showCloseShiftModal}
          authFetch={authFetch}
          shift={shift && !shift.offline ? shift : null}
          onClose={() => setShowCloseShiftModal(false)}
          onClosed={() => { setShowCloseShiftModal(false); setShift(null) }}
        />
        <CashMovementModal
          open={showCashMovementModal}
          authFetch={authFetch}
          onClose={() => setShowCashMovementModal(false)}
          onRecorded={() => { setShowCashMovementModal(false); refreshShift() }}
        />

        {isLiveView && (
          <div style={{
            background: 'var(--bg-3)',
            borderBottom: '1px solid var(--border)',
            padding: '8px 16px',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            fontSize: '0.82rem',
            color: 'var(--text-primary)',
            zIndex: 99
          }}>
            <div>
              <span>Viewing Counter: <strong>{liveCounter}</strong></span>
              {editState === 'granted' && <span style={{ color: '#22c55e', marginLeft: 12, fontWeight: 700 }}>● Editing Active</span>}
              {editState === 'requesting' && <span style={{ color: '#f59e0b', marginLeft: 12, fontWeight: 700 }}>● Requesting Access...</span>}
              {editState === 'denied' && <span style={{ color: '#ef4444', marginLeft: 12, fontWeight: 700 }}>● Request Denied</span>}
              {editState === 'idle' && <span style={{ color: 'var(--text-muted)', marginLeft: 12 }}>● View Only</span>}
            </div>
            <div style={{ display: 'flex', gap: 8 }}>
              {editState === 'idle' && (
                <button
                  type="button"
                  className="btn btn-primary"
                  onClick={() => {
                    setEditState('requesting')
                    broadcastMessage({
                      type: 'pos.request_edit',
                      target_client_id: liveClientId,
                      requester_client_id: clientId,
                      requester_username: user?.username || 'Owner'
                    })
                  }}
                  style={{ fontSize: '0.78rem', padding: '4px 10px', background: 'var(--accent)', color: '#fff', border: 'none', borderRadius: 4, cursor: 'pointer' }}
                >
                  Request Edit Access
                </button>
              )}
              {editState === 'requesting' && (
                <button
                  type="button"
                  className="btn btn-secondary"
                  onClick={() => {
                    setEditState('idle')
                  }}
                  style={{ fontSize: '0.78rem', padding: '4px 10px', background: 'rgba(255,255,255,0.08)', color: 'var(--text-primary)', border: '1px solid var(--border)', borderRadius: 4, cursor: 'pointer' }}
                >
                  Cancel Request
                </button>
              )}
              {editState === 'granted' && (
                <button
                  type="button"
                  className="btn btn-success"
                  onClick={() => {
                    setEditState('idle')
                    broadcastMessage({
                      type: 'pos.release_edit',
                      target_client_id: liveClientId,
                      requester_client_id: clientId
                    })
                  }}
                  style={{ fontSize: '0.78rem', padding: '4px 10px', background: '#22c55e', color: '#fff', border: 'none', borderRadius: 4, cursor: 'pointer' }}
                >
                  Release Edit & Save
                </button>
              )}
              {editState === 'denied' && (
                <button
                  type="button"
                  className="btn btn-secondary"
                  onClick={() => setEditState('idle')}
                  style={{ fontSize: '0.78rem', padding: '4px 10px', background: 'rgba(255,255,255,0.08)', color: 'var(--text-primary)', border: '1px solid var(--border)', borderRadius: 4, cursor: 'pointer' }}
                >
                  Reset
                </button>
              )}
              <button
                type="button"
                className="btn btn-secondary"
                onClick={() => navigate('/pos-live-counter')}
                style={{ fontSize: '0.78rem', padding: '4px 10px', background: 'rgba(255,255,255,0.08)', color: 'var(--text-primary)', border: '1px solid var(--border)', borderRadius: 4, cursor: 'pointer' }}
              >
                Exit Live View
              </button>
            </div>
          </div>
        )}

        {/* Workspace body split */}
        <div
          className="pos-workspace"
          style={{
            userSelect: (isLiveView && editState !== 'granted') ? 'none' : 'auto',
            opacity: (isLiveView && editState !== 'granted') ? 0.95 : 1,
          }}
        >
          
          {/* Left Pane (72% width) */}
          <div className="pos-left-pane">
            
            {pendingSync.length > 0 && (
              <div
                role="status"
                style={{
                  display: 'inline-flex', alignItems: 'center', gap: 6, marginBottom: 8,
                  padding: '4px 10px', fontSize: '0.78rem', borderRadius: 999,
                  background: 'rgba(245, 158, 11, 0.15)', color: '#f59e0b',
                  border: '1px solid rgba(245, 158, 11, 0.4)',
                }}
              >
                <span style={{ width: 7, height: 7, borderRadius: 999, background: '#f59e0b' }} />
                {pendingSync.length} bill{pendingSync.length > 1 ? 's' : ''} saved offline — will sync when online
              </div>
            )}

            {alert && (
              <div className={`alert alert-${alert.type} mb-3`} style={{ padding: '8px 12px', fontSize: '0.82rem', alignItems: 'center' }}>
                {alert.type === 'success' ? <CheckIcon size={14} style={{ marginRight: 4 }} /> : <AlertIcon size={14} style={{ marginRight: 4 }} />}
                <span>{alert.msg}</span>
                <button onClick={() => setAlert(null)} style={{ marginLeft: 'auto', background: 'none', border: 'none', color: 'inherit', cursor: 'pointer' }} aria-label="Close"><CloseIcon size={16} /></button>
              </div>
            )}

            {/* Product autocomplete search */}
            <ProductSearchBar
              ref={barcodeRef}
              searchQuery={searchQuery}
              onSearchChange={(v) => { setSearchQuery(v); setSelectedIndex(-1) }}
              onKeyDown={handleSearchKeyDown}
              placeholder={`Scan barcode or search by ${t('product', 'item')} code, model no or name (F9)…`}
              onAddCustom={addCustomItemToCart}
              filteredProducts={filteredProducts}
              selectedIndex={selectedIndex}
              onHoverIndex={setSelectedIndex}
              onPick={addProductToCart}
              disabled={isLiveView && editState !== 'granted'}
            />

            {/* Cart Table list container */}
            <div className="pos-cart-wrapper" style={{ position: 'relative', display: 'flex', flexDirection: 'column', flex: 1, overflow: 'hidden' }}>
              <div ref={tableContainerRef} className="pos-cart-container" style={{ flex: 1, overflow: 'auto' }}>
                <table className="pos-cart-table" style={{ pointerEvents: (isLiveView && editState !== 'granted') ? 'none' : 'auto' }}>
                  <CartTableHeader
                    columnOrder={columnOrder}
                    colVisible={colVisible}
                    stickyOffsets={stickyOffsets}
                    t={t}
                    hasItems={form.items.length > 0}
                    extraAttrFields={extraAttrFields}
                  />
                  <tbody>
                    {form.items.length === 0 ? (
                      <CartEmptyRows
                        rowCount={emptyRowCount}
                        columnOrder={columnOrder}
                        colVisible={colVisible}
                        stickyOffsets={stickyOffsets}
                      />
                    ) : (
                      form.items.map((item, i) => (
                        <CartItemRow
                          key={i}
                          item={item}
                          index={i}
                          columnOrder={columnOrder}
                          colVisible={colVisible}
                          stickyOffsets={stickyOffsets}
                          products={products}
                          productBatches={productBatches}
                          setProductBatches={setProductBatches}
                          isIntrastate={isIntrastate}
                          setItem={setItem}
                          onQtyChange={handleQtyChange}
                          onRemove={removeItem}
                          setForm={setForm}
                          getPriceOptions={getPriceOptions}
                          authFetch={authFetch}
                          logger={logger}
                          extraAttrFields={extraAttrFields}
                        />
                      ))
                    )}
                  </tbody>
                  {form.items.length > 0 && (
                    <CartFooterRow
                      columnOrder={columnOrder}
                      colVisible={colVisible}
                      stickyOffsets={stickyOffsets}
                      colFooter={colFooter}
                      gstAmt={gstAmt}
                      grandTotal={grandTotal}
                    />
                  )}
                </table>
              </div>

              {priceSelectorIndex !== null && (
                <div
                  className="modal-overlay"
                  onClick={() => setPriceSelectorIndex(null)}
                  style={{ zIndex: 2010 }}
                >
                  <div
                    className="modal"
                    style={{
                      maxWidth: '580px',
                      background: 'var(--glass-bg)',
                      backdropFilter: 'blur(30px) saturate(190%)',
                      WebkitBackdropFilter: 'blur(30px) saturate(190%)',
                      border: '1px solid var(--glass-border)',
                      color: 'var(--text-primary)',
                      boxShadow: 'var(--shadow-lg)'
                    }}
                    onClick={e => e.stopPropagation()}
                  >
                    <div className="modal-header" style={{ borderBottom: '1px solid var(--border)' }}>
                      <span className="modal-title" style={{ fontSize: '1.1rem', fontWeight: 800, display: 'inline-flex', alignItems: 'center', gap: '6px', color: 'var(--text-primary)' }}>
                        <TagIcon size={18} style={{ color: 'var(--accent)' }} /> Price Selection — {form.items[priceSelectorIndex]?.product}
                      </span>
                      <button
                        className="btn btn-ghost btn-icon"
                        onClick={() => setPriceSelectorIndex(null)}
                        style={{ color: 'var(--text-muted)' }}
                       aria-label="Close"><CloseIcon size={16} /></button>
                    </div>
                    <div className="modal-body" style={{ padding: '16px 20px' }}>
                      <p style={{ fontSize: '0.82rem', color: 'var(--text-secondary)', marginBottom: '12px' }}>
                        Multiple prices found for this item. Use <kbd>↑</kbd> <kbd>↓</kbd> arrows and <kbd>Enter</kbd> / <kbd>Esc</kbd> or click a row to select.
                      </p>
                      
                      <div style={{ overflowX: 'auto', border: '1px solid var(--border)', borderRadius: 'var(--radius-md)' }}>
                        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.88rem' }}>
                          <thead>
                            <tr style={{ background: 'var(--bg-3)', borderBottom: '1px solid var(--border)', textAlign: 'left' }}>
                              <th style={{ padding: '10px 12px', fontWeight: 700, color: 'var(--text-muted)' }}>Price Option</th>
                              <th style={{ padding: '10px 12px', fontWeight: 700, color: 'var(--text-muted)' }}>Date Added</th>
                              <th style={{ padding: '10px 12px', fontWeight: 700, color: 'var(--text-muted)', textAlign: 'right' }}>Price</th>
                            </tr>
                          </thead>
                          <tbody>
                            {getPriceOptions(form.items[priceSelectorIndex]).map((opt, oIdx) => {
                              const isSelected = oIdx === selectedPriceOptIndex;
                              return (
                                <tr
                                  key={oIdx}
                                  style={{
                                    background: isSelected ? 'var(--accent-glow)' : 'transparent',
                                    borderBottom: '1px solid var(--border)',
                                    cursor: 'pointer',
                                    transition: 'background 0.15s ease',
                                    color: isSelected ? 'var(--text-primary)' : 'var(--text-secondary)',
                                    fontWeight: isSelected ? 600 : 'normal'
                                  }}
                                  onClick={() => handleSelectPriceOption(opt.price, opt.label)}
                                  onMouseEnter={() => setSelectedPriceOptIndex(oIdx)}
                                >
                                  <td style={{ padding: '12px' }}>
                                    <span>{opt.label}</span>
                                  </td>
                                  <td style={{ padding: '12px', color: isSelected ? 'var(--text-primary)' : 'var(--text-muted)' }}>
                                    {opt.formatted_date}
                                  </td>
                                  <td style={{ padding: '12px', textAlign: 'right', fontWeight: 700, color: isSelected ? 'var(--accent)' : 'var(--text-primary)' }}>
                                    {fmt(opt.price)}
                                  </td>
                                </tr>
                              );
                            })}
                          </tbody>
                        </table>
                      </div>
                    </div>
                  </div>
                </div>
              )}
            </div>

            {/* Bottom Sticky Totals Bar — extracted to components/sales/PosTotalBar */}
            {!showPaymentPopup && (
              <div style={{ pointerEvents: (isLiveView && editState !== 'granted') ? 'none' : 'auto' }}>
                <PosTotalBar
                  subtotal={subtotal}
                  gstAmt={gstAmt}
                  grandTotal={grandTotal}
                  onPay={openPaymentFlow}
                />
              </div>
            )}

          </div>

          {/* Right Pane (42% in menu mode) */}
          {entryMode === 'menu' && (
            <div
              className="pos-right-pane"
              style={{
                width: '42%',
                height: '100%',
                display: 'flex',
                flexDirection: 'column',
                padding: '16px',
                background: 'var(--bg)',
                borderLeft: '1px solid var(--border)',
                overflowY: 'auto',
                gap: '20px'
              }}
            >
              <div style={{ fontSize: '1.1rem', fontWeight: 800, color: 'var(--text-primary)', borderBottom: '2.5px solid var(--accent)', paddingBottom: '6px', marginBottom: '4px' }}>
                <InventoryIcon size={16} style={{ marginRight: 6, display: 'inline-block', verticalAlign: 'middle' }} /> Menu / Catalogue
              </div>
              {Object.keys(groupedProducts).length === 0 ? (
                <div style={{ textAlign: 'center', color: 'var(--text-muted)', fontSize: '0.9rem', marginTop: '40px' }}>
                  No products found in stock.
                </div>
              ) : (
                Object.entries(groupedProducts).map(([catName, items]) => (
                  <div key={catName} style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                    <h3 style={{ fontSize: '0.9rem', fontWeight: 700, color: 'var(--accent)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
                      {catName}
                    </h3>
                    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(140px, 1fr))', gap: '10px' }}>
                      {items.map(p => (
                        <div
                          key={p.id}
                          className="menu-product-card"
                          onClick={() => handleSelectProduct(p)}
                          style={{
                            background: 'var(--bg-2)',
                            border: '1.5px solid var(--border)',
                            borderRadius: '10px',
                            padding: '10px',
                            cursor: 'pointer',
                            transition: 'all 0.15s ease',
                            display: 'flex',
                            flexDirection: 'column',
                            justifyContent: 'space-between',
                            minHeight: '85px',
                            boxShadow: '0 2px 4px rgba(0,0,0,0.02)'
                          }}
                          onMouseEnter={(e) => {
                            e.currentTarget.style.borderColor = 'var(--accent)'
                            e.currentTarget.style.transform = 'translateY(-2px)'
                            e.currentTarget.style.boxShadow = '0 4px 12px rgba(249,115,22,0.1)'
                          }}
                          onMouseLeave={(e) => {
                            e.currentTarget.style.borderColor = 'var(--border)'
                            e.currentTarget.style.transform = 'none'
                            e.currentTarget.style.boxShadow = '0 2px 4px rgba(0,0,0,0.02)'
                          }}
                        >
                          <div style={{ fontWeight: 600, fontSize: '0.82rem', color: 'var(--text-primary)', lineHeight: 1.3 }}>
                            {p.name}
                          </div>
                          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginTop: '6px' }}>
                            <span style={{ fontSize: '0.72rem', color: 'var(--text-muted)' }}>
                              {p.unit || 'pcs'}
                            </span>
                            <span style={{ fontWeight: 700, fontSize: '0.85rem', color: 'var(--accent)' }}>
                              {fmt(p.selling_price)}
                            </span>
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                ))
              )}
            </div>
          )}

        </div>

      </div>

      {/* Breakup Details Modal — extracted to components/sales/TotalBreakupModal */}
      <TotalBreakupModal
        open={showBreakupModal}
        onClose={() => setShowBreakupModal(false)}
        subtotal={subtotal}
        gstAmt={gstAmt}
        isIntrastate={isIntrastate}
        cgstAmt={cgstAmt}
        sgstAmt={sgstAmt}
        igstAmt={igstAmt}
        grandTotal={grandTotal}
        amountReceived={amountReceivedNum}
        changeToReturn={changeToReturn}
        paymentMode={form.payment_mode}
        upiVpa={upiVpa}
      />

      {/* Payment Tendering Modal Popup */}
      {/* Checkout Modal Component */}
      <CheckoutModal
        open={showPaymentPopup}
        onClose={() => setShowPaymentPopup(false)}
        form={form}
        setForm={setForm}
        subtotal={subtotal}
        gstAmt={gstAmt}
        grandTotal={grandTotal}
        payable={payable}
        roundOff={roundOff}
        cashDiscountAmt={cashDiscountAmt}
        cgstAmt={cgstAmt}
        sgstAmt={sgstAmt}
        igstAmt={igstAmt}
        billDiscountAmt={billDiscountAmt}
        customers={customers}
        setCustomers={setCustomers}
        godowns={godowns}
        upiVpa={upiVpa}
        authFetch={authFetch}
        onSaveInvoice={executeSaveInvoice}
        submitting={submitting}
        setAlert={setAlert}
        focusTarget={paymentFocusTarget}
        funcKeys={funcKeys}
      />

      {/* Main Settings Modal */}
      {showSettingsModal && (
        <PosCounterSettingsModal
          onClose={() => setShowSettingsModal(false)}
          upiVpa={upiVpa}
          merchantState={merchantState}
          setMerchantState={setMerchantState}
          settings={settings}
          onToggleColumn={handleToggleColumnSetting}
          columnOrder={columnOrder}
          colVisible={colVisible}
          colLabels={colLabels}
          onMoveColumn={handleMoveColumn}
          funcKeys={funcKeys}
          setFuncKeys={setFuncKeys}
          onAdvancedSettings={() => { setShowSettingsModal(false); navigate('/settings'); }}
          defaultFuncKeys={defaultFuncKeys}
          initialTab={settingsInitialTab}
        />
      )}

      
      {/* Print-only thermal receipt container rendered via Portal directly in document.body */}
      <ThermalReceipt
        settings={settings}
        profile={profile}
        activeTab={activeTab}
        form={form}
        customers={customers}
        user={user}
        isIntrastate={isIntrastate}
        subtotal={subtotal}
        billDiscountAmt={billDiscountAmt}
        cgstAmt={cgstAmt}
        sgstAmt={sgstAmt}
        igstAmt={igstAmt}
        cashDiscountAmt={cashDiscountAmt}
        roundOff={roundOff}
        grandTotal={grandTotal}
        payable={payable}
        changeToReturn={changeToReturn}
        colFooter={colFooter}
      />

      {showRemoteRequestModal && (
        <div style={{
          position: 'fixed',
          top: 0, left: 0, right: 0, bottom: 0,
          background: 'rgba(0,0,0,0.6)',
          backdropFilter: 'blur(4px)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          zIndex: 2000
        }}>
          <div className="card shadow-lg animate-fade-in" style={{
            width: '100%',
            maxWidth: 420,
            padding: 24,
            borderRadius: 12,
            background: 'var(--bg-surface, #ffffff)',
            border: '1px solid var(--border)',
            textAlign: 'center'
          }}>
            <h3 style={{ fontSize: '1.1rem', fontWeight: 700, color: 'var(--text-primary)', marginBottom: 12 }}>
              Remote Edit Request
            </h3>
            <p style={{ fontSize: '0.85rem', color: 'var(--text-secondary)', lineHeight: 1.5, marginBottom: 20 }}>
              Manager <strong>{managerUsername}</strong> is requesting temporary access to view and edit your active bill. Allow?
            </p>
            <div style={{ display: 'flex', gap: 12, justifyContent: 'center' }}>
              <button
                onClick={() => {
                  setShowRemoteRequestModal(false)
                  setIsLockedByManager(true)
                  broadcastMessage({
                    type: 'pos.grant_edit',
                    target_client_id: managerClientId,
                    grantor_client_id: clientId,
                  })
                }}
                style={{
                  padding: '8px 20px', borderRadius: 6,
                  background: '#22c55e', color: '#fff', border: 'none',
                  fontSize: '0.8rem', fontWeight: 700, cursor: 'pointer'
                }}
              >
                Allow
              </button>
              <button
                onClick={() => {
                  setShowRemoteRequestModal(false)
                  broadcastMessage({
                    type: 'pos.deny_edit',
                    target_client_id: managerClientId,
                    grantor_client_id: clientId,
                  })
                }}
                style={{
                  padding: '8px 20px', borderRadius: 6,
                  background: 'rgba(255,255,255,0.08)', color: 'var(--text-primary)',
                  border: '1px solid var(--border)',
                  fontSize: '0.8rem', fontWeight: 600, cursor: 'pointer'
                }}
              >
                Deny
              </button>
            </div>
          </div>
        </div>
      )}

      {isLockedByManager && (
        <div style={{
          position: 'fixed',
          top: 0, left: 0, right: 0, bottom: 0,
          background: 'rgba(0,0,0,0.06)',
          zIndex: 1999,
          pointerEvents: 'auto',
          userSelect: 'none'
        }}>
          <div style={{
            position: 'absolute',
            top: 20,
            left: '50%',
            transform: 'translateX(-50%)',
            background: 'var(--accent, #f97316)',
            color: '#fff',
            padding: '8px 18px',
            borderRadius: 20,
            fontSize: '0.82rem',
            fontWeight: 700,
            boxShadow: '0 4px 12px rgba(0,0,0,0.25)',
            display: 'flex',
            alignItems: 'center',
            gap: 8,
            animation: 'pulse 2s infinite'
          }}>
            <span>🔒</span>
            <span>Managed Mode Active — Controlled by Owner</span>
          </div>
        </div>
      )}
    </AppLayout>
  )
}
